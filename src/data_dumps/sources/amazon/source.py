"""Amazon GDPR multipart export → DuckDB (loader orchestration)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

from . import helpers as H
from .alexa import AlexaMixin
from .digital_media import DigitalMediaMixin
from .orders import OrdersMixin
from .schema import create_tables
from .searches import SearchesMixin


class AmazonSource(OrdersMixin, SearchesMixin, DigitalMediaMixin, AlexaMixin):
    name = "amazon"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    names = {n.replace("\\", "/") for n in zf.namelist()}
            except (OSError, zipfile.BadZipFile):
                return False
            return any(
                n.endswith(H.CURATED_ORDER)
                or n.endswith(H.ORDER_HISTORY)
                or Path(n).name == H.ORDER_HISTORY
                for n in names
            )
        if not path.is_dir():
            return False
        if (path / "Your Amazon Orders" / H.ORDER_HISTORY).is_file():
            return True
        if (path / H.ORDER_HISTORY).is_file():
            return True
        zips = list(path.glob(H.ZIP_GLOB))
        if not zips:
            return False
        # Prefer detecting via zip 3 / any zip with order history
        for zp in zips:
            try:
                with zipfile.ZipFile(zp) as zf:
                    for n in zf.namelist():
                        if (
                            n.replace("\\", "/").endswith(H.CURATED_ORDER)
                            or Path(n).name == H.ORDER_HISTORY
                        ):
                            return True
            except (OSError, zipfile.BadZipFile):
                continue
        return bool((path / "FileDescriptions.csv").is_file() and zips)

    def tables(self) -> list[str]:
        return list(H.AMAZON_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        raw = raw_dir("amazon")
        raw.mkdir(parents=True, exist_ok=True)

        zip_paths, extract_root = self._resolve_inputs(path)
        bundle: H._ZipBundle | None = None
        meta_rows: list[dict[str, Any]] = []
        inventory_rows: list[dict[str, Any]] = []

        frames: dict[str, pd.DataFrame] = {}
        try:
            if zip_paths:
                bundle = H._ZipBundle(zip_paths)
                bundle.open()
                inventory_rows = self._build_inventory(bundle)
                frames = self._load_from_bundle(bundle, meta_rows)
            elif extract_root is not None:
                inventory_rows = self._inventory_from_dir(extract_root)
                frames = self._load_from_dir(extract_root, meta_rows)
            else:
                raise FileNotFoundError(f"No Amazon export found under {path}")
        finally:
            if bundle is not None:
                bundle.close()

        # Persist a small pointer file for replay docs (not the multi-GB zips).
        pointer = raw / "source_path.txt"
        pointer.write_text(str(path) + "\n", encoding="utf-8")

        conn.execute("DROP SCHEMA IF EXISTS amazon CASCADE")
        conn.execute("CREATE SCHEMA amazon")
        create_tables(conn)

        frames["dump_inventory"] = (
            pd.DataFrame(inventory_rows)
            if inventory_rows
            else H._empty(
                [
                    "zip_part",
                    "path",
                    "ext",
                    "category",
                    "bytes",
                    "ingested",
                    "skip_reason",
                ]
            )
        )
        frames["ingest_meta"] = (
            pd.DataFrame(meta_rows)
            if meta_rows
            else H._empty(
                ["logical_name", "source_path", "rows_raw", "rows_kept", "note"]
            )
        )

        for table, df in frames.items():
            if df is None:
                continue
            tmp = f"_amz_{table}"
            conn.register(tmp, df)
            conn.execute(f"INSERT INTO amazon.{table} BY NAME SELECT * FROM {tmp}")
            conn.unregister(tmp)

        self._rebuild_orders(conn)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        def n(table: str) -> int:
            row = conn.execute(f"SELECT count(*) FROM amazon.{table}").fetchone()
            return int(row[0]) if row else 0

        items = n("order_items")
        intents = n("alexa_intents")
        inv = n("dump_inventory")
        voice = conn.execute("""
            SELECT coalesce(sum(bytes), 0), count(*)
            FROM amazon.dump_inventory WHERE category = 'voice_audio'
            """).fetchone()
        voice_bytes = int(voice[0]) if voice else 0
        voice_files = int(voice[1]) if voice else 0
        currencies = conn.execute("""
            SELECT list(DISTINCT currency ORDER BY currency)
            FROM amazon.order_items WHERE currency IS NOT NULL
            """).fetchone()
        curr = currencies[0] if currencies else []
        summary = (
            f"amazon: {items} order lines · {intents} alexa intents · "
            f"{voice_files} voice files ({voice_bytes / 1e9:.1f} GB shadowed) · "
            f"{inv} inventory rows · currencies={curr}"
        )
        return {
            "summary": summary,
            "n_order_items": items,
            "n_alexa_intents": intents,
            "n_inventory": inv,
            "voice_files": voice_files,
        }

    def _resolve_inputs(self, path: Path) -> tuple[list[Path], Path | None]:
        if path.is_file() and path.suffix.lower() == ".zip":
            return [path], None
        if not path.is_dir():
            return [], None
        if (path / "Your Amazon Orders" / H.ORDER_HISTORY).is_file():
            zips = sorted(path.glob(H.ZIP_GLOB))
            return zips, path
        zips = sorted(path.glob(H.ZIP_GLOB))
        if zips:
            return zips, None
        if (path / H.ORDER_HISTORY).is_file():
            return [], path
        return [], None

    def _build_inventory(self, bundle: H._ZipBundle) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for zip_name, info in bundle.all_infos:
            path = info.filename.replace("\\", "/")
            ext = Path(path).suffix.casefold() or "(none)"
            cat = H._category_for_path(path)
            ingested = False
            skip: str | None = None
            if cat == "voice_audio":
                skip = "voice_audio_not_loaded"
            elif cat in {"email_eml", "invoices_pdf"}:
                skip = "binary_artifact"
            elif (
                info.file_size > H.MAX_MEMBER_BYTES
                and H._basename_key(path) not in H.ALLOW_LARGE
            ):
                skip = "oversize"
            elif cat in {
                "commerce_csv",
                "media_csv",
                "alexa_telemetry",
                "kindle",
                "structured_other",
            }:
                # Mark potentially loaded; refined per-loader via ingest_meta.
                ingested = skip is None and ext in {".csv", ".json"}
            rows.append(
                {
                    "zip_part": zip_name,
                    "path": path,
                    "ext": ext,
                    "category": cat,
                    "bytes": int(info.file_size),
                    "ingested": bool(ingested and skip is None),
                    "skip_reason": skip,
                }
            )
        return rows

    def _inventory_from_dir(self, root: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            rel = str(f.relative_to(root)).replace("\\", "/")
            ext = f.suffix.casefold() or "(none)"
            cat = H._category_for_path(rel)
            skip = None
            if cat == "voice_audio":
                skip = "voice_audio_not_loaded"
            rows.append(
                {
                    "zip_part": "(extracted)",
                    "path": rel,
                    "ext": ext,
                    "category": cat,
                    "bytes": f.stat().st_size,
                    "ingested": skip is None and ext in {".csv", ".json"},
                    "skip_reason": skip,
                }
            )
        return rows

    def _load_from_bundle(
        self, bundle: H._ZipBundle, meta: list[dict[str, Any]]
    ) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        out["order_items"] = self._orders(bundle, meta)
        out["digital_items"] = self._digital(bundle, meta)
        out["returns"] = self._returns(bundle, meta)
        out["cart_events"] = self._cart(bundle, meta)
        out["searches"] = self._searches(bundle, meta)
        out["search_clicks"] = self._search_clicks(bundle, meta)
        out["video_views"] = self._video_views(bundle, meta)
        out["video_searches"] = self._video_searches(bundle, meta)
        out["audible_listens"] = self._audible_listens(bundle, meta)
        out["audible_library"] = self._audible_library(bundle, meta)
        out["music_plays"] = self._music_plays(bundle, meta)
        out["music_searches"] = self._music_searches(bundle, meta)
        out["music_library"] = self._music_library(bundle, meta)
        out["alexa_intents"] = self._alexa_intents(bundle, meta)
        out["alexa_sessions"] = self._alexa_sessions(bundle, meta)
        out["alexa_show_daily"] = self._alexa_show_daily(bundle, meta)
        out["alexa_skills"] = self._alexa_skills(bundle, meta)
        out["alexa_routines"] = self._alexa_routines(bundle, meta)
        out["alexa_app_events"] = self._alexa_app_events(bundle, meta)
        out["kindle_sessions"] = self._kindle_sessions(bundle, meta)
        out["wishlists"] = self._wishlists(bundle, meta)
        out["rufus_queries"] = self._rufus(bundle, meta)
        out["subscriptions"] = self._subscriptions(bundle, meta)
        out["product_impressions"] = self._product_impressions(bundle, meta)
        out["devices_summary"] = self._devices_summary(bundle, meta)
        # orders filled after insert
        out["orders"] = H._empty(
            [
                "order_id",
                "order_ts_utc",
                "order_ts_local",
                "year",
                "month",
                "marketplace",
                "website",
                "currency",
                "n_items",
                "total_amount",
                "is_cancelled",
                "status",
            ]
        )
        return out

    def _load_from_dir(
        self, root: Path, meta: list[dict[str, Any]]
    ) -> dict[str, pd.DataFrame]:
        """Load curated CSVs from an extracted tree (zip 3 layout)."""

        class _DirBundle:
            def read(self, *candidates: str) -> bytes | None:
                for cand in candidates:
                    p = root / cand
                    if p.is_file():
                        return p.read_bytes()
                    # basename search
                    matches = list(root.rglob(Path(cand).name))
                    if matches:
                        return matches[0].read_bytes()
                return None

            def open_member(self, *candidates: str):
                for cand in candidates:
                    p = root / cand
                    if p.is_file():
                        return (
                            p.open("rb"),
                            type(
                                "I",
                                (),
                                {
                                    "filename": str(p.relative_to(root)),
                                    "file_size": p.stat().st_size,
                                },
                            )(),
                        )
                    matches = list(root.rglob(Path(cand).name))
                    if matches:
                        m = matches[0]
                        return (
                            m.open("rb"),
                            type(
                                "I",
                                (),
                                {
                                    "filename": str(m.relative_to(root)),
                                    "file_size": m.stat().st_size,
                                },
                            )(),
                        )
                return None

            def find(self, *candidates: str):
                return None

        return self._load_from_bundle(_DirBundle(), meta)  # type: ignore[arg-type]

    def _meta(
        self,
        meta: list[dict[str, Any]],
        logical: str,
        source: str | None,
        raw_n: int,
        kept: int,
        note: str = "",
    ) -> None:
        meta.append(
            {
                "logical_name": logical,
                "source_path": source,
                "rows_raw": raw_n,
                "rows_kept": kept,
                "note": note or None,
            }
        )
