"""Amazon GDPR multipart export → DuckDB.

Supports a folder of ``All Data Categories*.zip`` (+ FileDescriptions.csv), a
single curated zip, or an extracted ``Your Amazon Orders/`` tree.

Privacy: addresses, cards, IPs, emails, phones, gift contacts, geolocation,
device serials, and voice audio are not loaded. Alexa utterance text is kept
(personal dump); contact names on intents are dropped. Device IDs are hashed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterator
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Rome")

ORDER_HISTORY = "Order History.csv"
CURATED_ORDER = "Your Amazon Orders/Order History.csv"
ZIP_GLOB = "All Data Categories*.zip"

# Members larger than this are skipped unless listed in ALLOW_LARGE.
MAX_MEMBER_BYTES = 50 * 1024 * 1024
ALLOW_LARGE = {
    "intent-2-1.csv",
    "questionunderstandings-2-1.csv",
    "alexa and echo devices.echo_show_generic_events.csv",
    "alexa.adsdata.csv",
}

AMAZON_TABLES = [
    "amazon.dump_inventory",
    "amazon.ingest_meta",
    "amazon.order_items",
    "amazon.orders",
    "amazon.digital_items",
    "amazon.returns",
    "amazon.cart_events",
    "amazon.searches",
    "amazon.search_clicks",
    "amazon.video_views",
    "amazon.video_searches",
    "amazon.audible_listens",
    "amazon.audible_library",
    "amazon.music_plays",
    "amazon.music_searches",
    "amazon.music_library",
    "amazon.alexa_intents",
    "amazon.alexa_sessions",
    "amazon.alexa_show_daily",
    "amazon.alexa_skills",
    "amazon.alexa_routines",
    "amazon.alexa_app_events",
    "amazon.kindle_sessions",
    "amazon.wishlists",
    "amazon.rufus_queries",
    "amazon.subscriptions",
    "amazon.product_impressions",
    "amazon.devices_summary",
]

DEPT_FAMILY_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "books",
        (
            "paperback",
            "hardcover",
            "broché",
            "broche",
            "kindle",
            "ebook",
            "livre",
        ),
    ),
    (
        "electronics",
        (
            "electronics",
            "personal computers",
            "ordinateur",
            "pc ",
            "camera",
            "téléphone",
            "telephone",
        ),
    ),
    (
        "home",
        (
            "kitchen",
            "office",
            "outils",
            "home",
            "garden",
            "furniture",
            "appliance",
        ),
    ),
    ("health_beauty", ("health", "beauty", "santé", "sante", "hygiène", "hygiene")),
    ("media_physical", ("audio cd", "dvd", "vinyl", "blu-ray", "bluray")),
    ("apparel_sport_toy", ("apparel", "clothing", "sports", "toy", "jouet", "shoe")),
]

UTTERANCE_TAGS: list[tuple[str, re.Pattern[str]]] = [
    (
        "music",
        re.compile(
            r"\b(play|pause|resume|spotify|music|song|album|radio|volume|quieter|louder)\b",
            re.I,
        ),
    ),
    (
        "smart_home",
        re.compile(
            r"\b(light|lamp|thermostat|temperature|percent|turn (on|off)|dim|bright)\b",
            re.I,
        ),
    ),
    (
        "timer",
        re.compile(r"\b(timer|alarm|remind|reminder|stopwatch)\b", re.I),
    ),
    ("weather", re.compile(r"\b(weather|forecast|temperature outside|rain)\b", re.I)),
    ("shopping", re.compile(r"\b(order|buy|cart|amazon|shop|purchase|track)\b", re.I)),
    ("info", re.compile(r"\b(what|who|when|where|how|define|wikipedia|tell me)\b", re.I)),
]


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {
        "N/A",
        "NA",
        "NONE",
        "NULL",
        "NOT AVAILABLE",
        "NOT APPLICABLE",
        "NOT AVAILABLE.",
        "DATA NOT AVAILABLE",
    }


def _cell(row: dict[str, Any], *names: str) -> str | None:
    lower = {str(k).strip().lower(): k for k in row if k is not None}
    for name in names:
        key = lower.get(name.lower())
        if key is None:
            continue
        val = row.get(key)
        if _blank(val):
            return None
        return str(val).strip()
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if _blank(value):
        return None
    raw = str(value).strip().strip('"')
    ts = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    py = ts.to_pydatetime(warn=False)
    if py.tzinfo is None:
        py = py.replace(tzinfo=UTC)
    return py.astimezone(UTC)


def _ts_pair(value: Any) -> tuple[datetime | None, datetime | None]:
    ts = _parse_datetime(value)
    if ts is None:
        return None, None
    utc_naive = ts.astimezone(UTC).replace(tzinfo=None)
    local_naive = ts.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return utc_naive, local_naive


def _year_month(
    utc_naive: datetime | None, local_naive: datetime | None
) -> tuple[int | None, int | None]:
    src = local_naive or utc_naive
    if src is None:
        return None, None
    return src.year, src.month


def _money(value: Any) -> float | None:
    if _blank(value):
        return None
    raw = str(value).strip().replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _intish(value: Any) -> int | None:
    if _blank(value):
        return None
    raw = str(value).strip().replace(",", "")
    try:
        return int(float(raw))
    except ValueError:
        return None


def _hash_id(value: str | None) -> str | None:
    if value is None or _blank(value):
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _dept_family(dept: str | None) -> str:
    if not dept:
        return "other"
    low = dept.casefold()
    for family, needles in DEPT_FAMILY_RULES:
        if any(n in low for n in needles):
            return family
    return "other"


def _marketplace_from_website(website: str | None) -> str | None:
    if not website:
        return None
    low = website.casefold()
    for code, needles in (
        ("fr", ("amazon.fr", ".fr")),
        ("uk", ("amazon.co.uk", ".co.uk", "amazon.uk")),
        ("us", ("amazon.com",)),
        ("es", ("amazon.es",)),
        ("de", ("amazon.de",)),
        ("it", ("amazon.it",)),
    ):
        if any(n in low for n in needles):
            return code
    return "other"


def _utterance_tag(text: str | None) -> str:
    if not text:
        return "other"
    for tag, pat in UTTERANCE_TAGS:
        if pat.search(text):
            return tag
    return "other"


def _category_for_path(path: str) -> str:
    low = path.casefold()
    ext = Path(path).suffix.casefold()
    if ext == ".wav" or "/audio_messages/" in low or ext == ".mp3":
        return "voice_audio"
    if ext in {".eml"}:
        return "email_eml"
    if ext == ".pdf" or "invoic" in low:
        return "invoices_pdf"
    if ext in {".jpeg", ".jpg", ".png", ".gif"}:
        return "images"
    if "alexa" in low or "echo" in low:
        return "alexa_telemetry"
    if "kindle" in low or "audible" in low:
        return "kindle"
    if "your amazon orders" in low or "order history" in low or "search quer" in low:
        return "commerce_csv"
    if "prime video" in low or "listening activity" in low or "music" in low:
        return "media_csv"
    if ext in {".csv", ".json"}:
        return "structured_other"
    return "other"


def _basename_key(path: str) -> str:
    return Path(path).name.casefold()


def _prefer_curated(a: str, b: str) -> str:
    """Return the preferred of two member paths for the same basename."""
    a_cur = a.casefold().startswith("your ")
    b_cur = b.casefold().startswith("your ")
    if a_cur and not b_cur:
        return a
    if b_cur and not a_cur:
        return b
    # Prefer higher version suffix (-4 over -2) then longer path detail.
    def score(p: str) -> tuple[int, int]:
        m = re.search(r"-(\d+)(?:\.|/|$)", Path(p).stem)
        ver = int(m.group(1)) if m else 0
        return ver, len(p)

    return a if score(a) >= score(b) else b


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _read_csv_dicts(
    raw: bytes, *, required: set[str] | None = None
) -> list[dict[str, str]]:
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    fields = {(f or "").strip() for f in reader.fieldnames}
    if required and not required.issubset({f.casefold() for f in fields}):
        return []
    rows: list[dict[str, str]] = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _iter_csv_dicts(fh: BinaryIO) -> Iterator[dict[str, str]]:
    text = io.TextIOWrapper(fh, encoding="utf-8-sig", errors="replace", newline="")
    reader = csv.DictReader(text)
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        yield {(k or "").strip(): (v or "").strip() for k, v in row.items()}


class _ZipBundle:
    """Index of member paths across one or more Amazon category zips."""

    def __init__(self, zip_paths: list[Path]) -> None:
        self.zip_paths = zip_paths
        self._zfs: list[zipfile.ZipFile] = []
        self.by_basename: dict[str, tuple[zipfile.ZipFile, zipfile.ZipInfo]] = {}
        self.by_suffix: dict[str, tuple[zipfile.ZipFile, zipfile.ZipInfo]] = {}
        self.all_infos: list[tuple[str, zipfile.ZipInfo]] = []  # zip name, info

    def open(self) -> None:
        for zp in self.zip_paths:
            zf = zipfile.ZipFile(zp)
            self._zfs.append(zf)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                self.all_infos.append((zp.name, info))
                key = _basename_key(info.filename)
                existing = self.by_basename.get(key)
                if existing is None:
                    self.by_basename[key] = (zf, info)
                else:
                    _, old = existing
                    chosen = _prefer_curated(old.filename, info.filename)
                    if chosen == info.filename:
                        self.by_basename[key] = (zf, info)
                # Also index curated relative suffixes
                low = info.filename.replace("\\", "/")
                self.by_suffix[low.casefold()] = (zf, info)
                if "/" in low:
                    # last two segments for "Your X/Y.csv"
                    parts = low.split("/")
                    if len(parts) >= 2:
                        tail = "/".join(parts[-2:]).casefold()
                        prev = self.by_suffix.get(tail)
                        if prev is None or _prefer_curated(prev[1].filename, info.filename) == info.filename:
                            self.by_suffix[tail] = (zf, info)

    def close(self) -> None:
        for zf in self._zfs:
            zf.close()
        self._zfs.clear()

    def find(self, *candidates: str) -> tuple[zipfile.ZipFile, zipfile.ZipInfo] | None:
        for cand in candidates:
            low = cand.replace("\\", "/").casefold()
            if low in self.by_suffix:
                return self.by_suffix[low]
            if _basename_key(cand) in self.by_basename:
                hit = self.by_basename[_basename_key(cand)]
                # Prefer curated when searching by basename alone
                return hit
        return None

    def read(self, *candidates: str) -> bytes | None:
        hit = self.find(*candidates)
        if hit is None:
            return None
        zf, info = hit
        if info.file_size > MAX_MEMBER_BYTES:
            if _basename_key(info.filename) not in ALLOW_LARGE:
                return None
        return zf.read(info)

    def open_member(self, *candidates: str) -> tuple[BinaryIO, zipfile.ZipInfo] | None:
        hit = self.find(*candidates)
        if hit is None:
            return None
        zf, info = hit
        if info.file_size > MAX_MEMBER_BYTES:
            if _basename_key(info.filename) not in ALLOW_LARGE:
                return None
        return zf.open(info), info


class AmazonSource:
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
                n.endswith(CURATED_ORDER)
                or n.endswith(ORDER_HISTORY)
                or Path(n).name == ORDER_HISTORY
                for n in names
            )
        if not path.is_dir():
            return False
        if (path / "Your Amazon Orders" / ORDER_HISTORY).is_file():
            return True
        if (path / ORDER_HISTORY).is_file():
            return True
        zips = list(path.glob(ZIP_GLOB))
        if not zips:
            return False
        # Prefer detecting via zip 3 / any zip with order history
        for zp in zips:
            try:
                with zipfile.ZipFile(zp) as zf:
                    for n in zf.namelist():
                        if n.replace("\\", "/").endswith(CURATED_ORDER) or Path(
                            n
                        ).name == ORDER_HISTORY:
                            return True
            except (OSError, zipfile.BadZipFile):
                continue
        return bool((path / "FileDescriptions.csv").is_file() and zips)

    def tables(self) -> list[str]:
        return list(AMAZON_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        raw = raw_dir("amazon")
        raw.mkdir(parents=True, exist_ok=True)

        zip_paths, extract_root = self._resolve_inputs(path)
        bundle: _ZipBundle | None = None
        meta_rows: list[dict[str, Any]] = []
        inventory_rows: list[dict[str, Any]] = []

        frames: dict[str, pd.DataFrame] = {}
        try:
            if zip_paths:
                bundle = _ZipBundle(zip_paths)
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
        self._create_tables(conn)

        frames["dump_inventory"] = (
            pd.DataFrame(inventory_rows)
            if inventory_rows
            else _empty(
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
            else _empty(["logical_name", "source_path", "rows_raw", "rows_kept", "note"])
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
        voice = conn.execute(
            """
            SELECT coalesce(sum(bytes), 0), count(*)
            FROM amazon.dump_inventory WHERE category = 'voice_audio'
            """
        ).fetchone()
        voice_bytes = int(voice[0]) if voice else 0
        voice_files = int(voice[1]) if voice else 0
        currencies = conn.execute(
            """
            SELECT list(DISTINCT currency ORDER BY currency)
            FROM amazon.order_items WHERE currency IS NOT NULL
            """
        ).fetchone()
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

    def _resolve_inputs(
        self, path: Path
    ) -> tuple[list[Path], Path | None]:
        if path.is_file() and path.suffix.lower() == ".zip":
            return [path], None
        if not path.is_dir():
            return [], None
        if (path / "Your Amazon Orders" / ORDER_HISTORY).is_file():
            zips = sorted(path.glob(ZIP_GLOB))
            return zips, path
        zips = sorted(path.glob(ZIP_GLOB))
        if zips:
            return zips, None
        if (path / ORDER_HISTORY).is_file():
            return [], path
        return [], None

    def _build_inventory(self, bundle: _ZipBundle) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for zip_name, info in bundle.all_infos:
            path = info.filename.replace("\\", "/")
            ext = Path(path).suffix.casefold() or "(none)"
            cat = _category_for_path(path)
            ingested = False
            skip: str | None = None
            if cat == "voice_audio":
                skip = "voice_audio_not_loaded"
            elif cat in {"email_eml", "invoices_pdf"}:
                skip = "binary_artifact"
            elif info.file_size > MAX_MEMBER_BYTES and _basename_key(path) not in ALLOW_LARGE:
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
            cat = _category_for_path(rel)
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
        self, bundle: _ZipBundle, meta: list[dict[str, Any]]
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
        out["orders"] = _empty(
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
                        return p.open("rb"), type(
                            "I", (), {"filename": str(p.relative_to(root)), "file_size": p.stat().st_size}
                        )()
                    matches = list(root.rglob(Path(cand).name))
                    if matches:
                        m = matches[0]
                        return m.open("rb"), type(
                            "I",
                            (),
                            {
                                "filename": str(m.relative_to(root)),
                                "file_size": m.stat().st_size,
                            },
                        )()
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

    def _orders(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "order_id",
            "asin",
            "product_name",
            "department",
            "dept_family",
            "quantity",
            "currency",
            "unit_price",
            "unit_tax",
            "line_total",
            "shipping_charge",
            "discounts",
            "order_status",
            "is_cancelled",
            "website",
            "marketplace",
            "order_ts_utc",
            "order_ts_local",
            "ship_ts_utc",
            "year",
            "month",
            "surface",
        ]
        raw = bundle.read(
            CURATED_ORDER,
            f"Your Amazon Orders/{ORDER_HISTORY}",
            ORDER_HISTORY,
        )
        if raw is None:
            self._meta(meta, "order_items", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            order_id = _cell(rec, "Order ID")
            if not order_id:
                continue
            utc, local = _ts_pair(_cell(rec, "Order Date"))
            year, month = _year_month(utc, local)
            ship_utc, _ = _ts_pair(_cell(rec, "Ship Date"))
            status = _cell(rec, "Order Status")
            website = _cell(rec, "Website")
            dept = _cell(rec, "Department")
            qty = _intish(_cell(rec, "Original Quantity")) or 1
            unit = _money(_cell(rec, "Unit Price"))
            tax = _money(_cell(rec, "Unit Price Tax"))
            total = _money(_cell(rec, "Total Amount"))
            if total is None and unit is not None:
                total = unit * qty + (tax or 0) * qty
            rows.append(
                {
                    "order_id": order_id,
                    "asin": _cell(rec, "ASIN"),
                    "product_name": _cell(rec, "Product Name"),
                    "department": dept,
                    "dept_family": _dept_family(dept),
                    "quantity": qty,
                    "currency": _cell(rec, "Currency"),
                    "unit_price": unit,
                    "unit_tax": tax,
                    "line_total": total,
                    "shipping_charge": _money(_cell(rec, "Shipping Charge")),
                    "discounts": _money(_cell(rec, "Total Discounts")),
                    "order_status": status,
                    "is_cancelled": (status or "").casefold() == "cancelled",
                    "website": website,
                    "marketplace": _marketplace_from_website(website),
                    "order_ts_utc": utc,
                    "order_ts_local": local,
                    "ship_ts_utc": ship_utc,
                    "year": year,
                    "month": month,
                    "surface": "retail",
                }
            )
        self._meta(meta, "order_items", ORDER_HISTORY, len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _digital(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "order_id",
            "asin",
            "product_name",
            "marketplace",
            "currency",
            "price",
            "quantity",
            "order_status",
            "order_ts_utc",
            "order_ts_local",
            "year",
            "month",
            "is_gift",
            "surface",
        ]
        raw = bundle.read(
            "Your Amazon Orders/Digital Content Orders.csv",
            "Digital Content Orders.csv",
        )
        if raw is None:
            self._meta(meta, "digital_items", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(_cell(rec, "Order Date"))
            year, month = _year_month(utc, local)
            mkt = _cell(rec, "Marketplace")
            rows.append(
                {
                    "order_id": _cell(rec, "Order ID"),
                    "asin": _cell(rec, "ASIN"),
                    "product_name": _cell(rec, "Product Name"),
                    "marketplace": _marketplace_from_website(mkt) or (mkt or None),
                    "currency": _cell(rec, "Price Currency Code", "Base Currency Code"),
                    "price": _money(_cell(rec, "Price", "Transaction Amount")),
                    "quantity": _intish(_cell(rec, "Quantity Ordered", "Original Quantity"))
                    or 1,
                    "order_status": _cell(rec, "Order Status"),
                    "order_ts_utc": utc,
                    "order_ts_local": local,
                    "year": year,
                    "month": month,
                    "is_gift": (_cell(rec, "Gift Item") or "").casefold() == "yes",
                    "surface": "digital",
                }
            )
        self._meta(meta, "digital_items", "Digital Content Orders.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _returns(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "order_id",
            "asin",
            "product_name",
            "return_reason",
            "refund_amount",
            "currency",
            "status",
            "return_ts_utc",
            "return_ts_local",
            "year",
            "month",
            "source_kind",
        ]
        rows: list[dict[str, Any]] = []
        raw_n = 0
        for kind, candidates, mapping in (
            (
                "refund_details",
                ("Your Returns & Refunds/Refund Details.csv", "Refund Details.csv"),
                {
                    "order_id": ("Order ID",),
                    "refund_amount": ("Refund Amount",),
                    "currency": ("Currency",),
                    "status": ("Reversal Status", "Payment Status"),
                    "reason": ("Reversal Reason",),
                    "ts": ("Refund Date", "Creation Date"),
                },
            ),
            (
                "return_requests",
                ("Your Returns & Refunds/Return Requests.csv", "Return Requests.csv"),
                {
                    "order_id": ("Order ID",),
                    "asin": ("ASIN",),
                    "product_name": ("Product Name",),
                    "reason": ("Return Reason Code",),
                },
            ),
            (
                "returns_status",
                ("Your Returns & Refunds/Returns Status.csv", "Returns Status.csv"),
                {
                    "order_id": ("Order ID",),
                    "refund_amount": ("Return Amount",),
                    "currency": ("Return Amount Currency",),
                    "reason": ("Return Reason",),
                    "status": ("Return Resolution", "Return Receivable State"),
                    "ts": ("Date of Return", "Return Creation Date"),
                },
            ),
        ):
            raw = bundle.read(*candidates)
            if raw is None:
                continue
            records = _read_csv_dicts(raw)
            raw_n += len(records)
            for rec in records:
                utc, local = _ts_pair(_cell(rec, *mapping.get("ts", ())))
                year, month = _year_month(utc, local)
                rows.append(
                    {
                        "order_id": _cell(rec, *mapping.get("order_id", ("Order ID",))),
                        "asin": _cell(rec, *mapping.get("asin", ("ASIN",))),
                        "product_name": _cell(
                            rec, *mapping.get("product_name", ("Product Name",))
                        ),
                        "return_reason": _cell(rec, *mapping.get("reason", ("",))),
                        "refund_amount": _money(
                            _cell(rec, *mapping.get("refund_amount", ("",)))
                        ),
                        "currency": _cell(rec, *mapping.get("currency", ("",))),
                        "status": _cell(rec, *mapping.get("status", ("",))),
                        "return_ts_utc": utc,
                        "return_ts_local": local,
                        "year": year,
                        "month": month,
                        "source_kind": kind,
                    }
                )
        self._meta(meta, "returns", "returns/*", raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _cart(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "asin",
            "product_name",
            "quantity",
            "cart_source",
            "added_ts_utc",
            "added_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Your Amazon Orders/Cart History.csv", "Cart History.csv"
        )
        if raw is None:
            self._meta(meta, "cart_events", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(_cell(rec, "Date Added to Cart", "Add Date"))
            year, month = _year_month(utc, local)
            rows.append(
                {
                    "asin": _cell(rec, "ASIN"),
                    "product_name": _cell(rec, "Product Name"),
                    "quantity": _intish(_cell(rec, "Order Quantity", "Cart Amount")),
                    "cart_source": _cell(rec, "Cart Source", "Status"),
                    "added_ts_utc": utc,
                    "added_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "cart_events", "Cart History.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _searches(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "query_id",
            "keywords",
            "department",
            "marketplace",
            "device_category",
            "clicked",
            "added",
            "purchased",
            "abandoned",
            "reformulated",
            "n_clicked",
            "n_ordered",
            "search_ts_utc",
            "search_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Your Shopping Search/Search Queries.csv", "Search Queries.csv"
        )
        if raw is None:
            self._meta(meta, "searches", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(
                _cell(rec, "First Search Time (GMT)", "Last search Time (GMT)")
            )
            year, month = _year_month(utc, local)
            country = _cell(rec, "Country Code")
            rows.append(
                {
                    "query_id": _cell(rec, "Query ID"),
                    "keywords": _cell(rec, "Keywords", "First Search Query String"),
                    "department": _cell(rec, "Department", "All Department (APS) or Category"),
                    "marketplace": (country or "").casefold() or None,
                    "device_category": _cell(rec, "Device Category", "Application / Browser Name"),
                    "clicked": (_cell(rec, "Clicked Any Item (Y/N)") or "").upper() == "Y",
                    "added": (_cell(rec, "Added Any Item (Y/N)") or "").upper() == "Y",
                    "purchased": (_cell(rec, "Purchased Any Item (Y/N)") or "").upper()
                    == "Y",
                    "abandoned": (_cell(rec, "Query Abandoned (Y/N)") or "").upper() == "Y",
                    "reformulated": (_cell(rec, "Query Reformulated (Y/N)") or "").upper()
                    == "Y",
                    "n_clicked": _intish(_cell(rec, "Number of Clicked Items")),
                    "n_ordered": _intish(_cell(rec, "Number of Items Ordered")),
                    "search_ts_utc": utc,
                    "search_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "searches", "Search Queries.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _search_clicks(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["clicked_asin", "added_asin", "borrowed_asin"]
        raw = bundle.read(
            "Your Shopping Search/Search Product Clicks.csv",
            "Search Product Clicks.csv",
        )
        if raw is None:
            self._meta(meta, "search_clicks", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows = [
            {
                "clicked_asin": _cell(rec, "Clicked Items"),
                "added_asin": _cell(rec, "Items Added to Cart or List"),
                "borrowed_asin": _cell(rec, "Items Borrowed"),
            }
            for rec in records
        ]
        self._meta(meta, "search_clicks", "Search Product Clicks.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _video_views(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "title",
            "seconds_viewed",
            "device_model",
            "content_quality",
            "country_code",
            "start_ts_utc",
            "start_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Your Prime Video Viewing Activity/Viewing History.csv",
            "Viewing History.csv",
        )
        if raw is None:
            self._meta(meta, "video_views", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(_cell(rec, "Playback Start Datetime (UTC)"))
            year, month = _year_month(utc, local)
            title = _cell(rec, "Title")
            if title:
                title = title.strip('"')
            rows.append(
                {
                    "title": title,
                    "seconds_viewed": _intish(_cell(rec, "Seconds Viewed")),
                    "device_model": (_cell(rec, "Device Model") or "").strip('"') or None,
                    "content_quality": (
                        _cell(rec, "Content Quality Delivered") or ""
                    ).strip('"')
                    or None,
                    "country_code": (_cell(rec, "Country Code") or "").strip('"') or None,
                    "start_ts_utc": utc,
                    "start_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "video_views", "Viewing History.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _video_searches(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["query", "device_name", "search_ts_utc", "search_ts_local", "year", "month"]
        raw = bundle.read(
            "Your Prime Video Viewing Activity/Search History.csv",
            "Search History.csv",
        )
        # Ambiguous basename — prefer Prime Video path via find order above
        if raw is None:
            self._meta(meta, "video_searches", None, 0, 0, "missing")
            return _empty(cols)
        # If we accidentally got Music search (2 cols), skip incompatible
        records = _read_csv_dicts(raw)
        if records and "Search Query from Customer" not in records[0]:
            # Music search history — leave for music_searches
            self._meta(meta, "video_searches", None, 0, 0, "wrong_file")
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(_cell(rec, "Search Request Date"))
            year, month = _year_month(utc, local)
            rows.append(
                {
                    "query": _cell(rec, "Search Query from Customer"),
                    "device_name": _cell(rec, "Device Name"),
                    "search_ts_utc": utc,
                    "search_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "video_searches", "PV Search History", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _audible_listens(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "asin",
            "product_name",
            "duration_ms",
            "narration_speed",
            "start_ts_utc",
            "start_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Your Audible Library & Listening/Listening History.csv",
        )
        if raw is None:
            self._meta(meta, "audible_listens", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(_cell(rec, "Start Date"))
            year, month = _year_month(utc, local)
            rows.append(
                {
                    "asin": _cell(rec, "ASIN"),
                    "product_name": _cell(rec, "Product Name"),
                    "duration_ms": _intish(_cell(rec, "Event Duration Milliseconds")),
                    "narration_speed": _money(_cell(rec, "Narration Speed")),
                    "start_ts_utc": utc,
                    "start_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "audible_listens", "Audible Listening History", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _audible_library(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["asin", "title", "authors", "length_minutes", "purchase_ts_utc", "year"]
        raw = bundle.read("Your Audible Library & Listening/Library.csv", "Library.csv")
        if raw is None:
            self._meta(meta, "audible_library", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, _ = _ts_pair(_cell(rec, "Purchase Date", "Last Updated"))
            rows.append(
                {
                    "asin": _cell(rec, "ASIN"),
                    "title": _cell(rec, "Title", "Product Name"),
                    "authors": _cell(rec, "Authors"),
                    "length_minutes": _intish(_cell(rec, "Length in Minutes")),
                    "purchase_ts_utc": utc,
                    "year": utc.year if utc else None,
                }
            )
        self._meta(meta, "audible_library", "Library.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _music_plays(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "asin",
            "product_name",
            "device_type",
            "listen_ms",
            "track_ms",
            "play_ts_utc",
            "play_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read("Your Listening Activity/Listening History.csv")
        if raw is None:
            self._meta(meta, "music_plays", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(_cell(rec, "Date"))
            year, month = _year_month(utc, local)
            rows.append(
                {
                    "asin": _cell(rec, "ASIN"),
                    "product_name": _cell(rec, "Product Name"),
                    "device_type": _cell(rec, "Device Type"),
                    "listen_ms": _intish(_cell(rec, "Listen Duration in Milliseconds")),
                    "track_ms": _intish(_cell(rec, "Track Length in Milliseconds")),
                    "play_ts_utc": utc,
                    "play_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "music_plays", "Music Listening History", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _music_searches(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["query", "search_ts_utc", "search_ts_local", "year", "month"]
        raw = bundle.read("Your Listening Activity/Search History.csv")
        if raw is None:
            self._meta(meta, "music_searches", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(_cell(rec, "Event Date"))
            year, month = _year_month(utc, local)
            rows.append(
                {
                    "query": _cell(rec, "Query"),
                    "search_ts_utc": utc,
                    "search_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "music_searches", "Music Search History", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _music_library(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["asin", "title", "artist_name", "album_name", "primary_genre", "saved_ts_utc", "year"]
        raw = bundle.read("Your Music Library/Saved Music.csv", "Saved Music.csv")
        if raw is None:
            self._meta(meta, "music_library", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, _ = _ts_pair(_cell(rec, "Creation Date", "Last Updated Date"))
            rows.append(
                {
                    "asin": _cell(rec, "ASIN"),
                    "title": _cell(rec, "Title"),
                    "artist_name": _cell(rec, "Artist Name"),
                    "album_name": _cell(rec, "Album Name"),
                    "primary_genre": _cell(rec, "Primary Genre", "Album Primary Genre"),
                    "saved_ts_utc": utc,
                    "year": utc.year if utc else None,
                }
            )
        self._meta(meta, "music_library", "Saved Music.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _alexa_intents(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "utterance",
            "utterance_tag",
            "playing_song",
            "intent_ts_utc",
            "intent_ts_local",
            "year",
            "month",
            "hour",
            "dow",
        ]
        opened = bundle.open_member(
            "Additional Data/Alexa/Alexa/NLU/Intent-2-1.csv",
            "Intent-2-1.csv",
        )
        if opened is None:
            self._meta(meta, "alexa_intents", None, 0, 0, "missing")
            return _empty(cols)
        fh, info = opened
        rows: list[dict[str, Any]] = []
        raw_n = 0
        with fh:
            for rec in _iter_csv_dicts(fh):
                raw_n += 1
                utterance = _cell(rec, "Utterance text")
                utc, local = _ts_pair(_cell(rec, "Utterance Creation Date"))
                year, month = _year_month(utc, local)
                src = local or utc
                rows.append(
                    {
                        "utterance": utterance,
                        "utterance_tag": _utterance_tag(utterance),
                        "playing_song": _cell(rec, "Currently Playing Song"),
                        "intent_ts_utc": utc,
                        "intent_ts_local": local,
                        "year": year,
                        "month": month,
                        "hour": src.hour if src else None,
                        "dow": src.isoweekday() if src else None,
                    }
                )
        self._meta(meta, "alexa_intents", info.filename, raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _alexa_sessions(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "device_type",
            "device_app",
            "locale",
            "marketplace",
            "event_ts_utc",
            "event_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Additional Data/Alexa and Echo Devices.Device_Session_Events/"
            "Alexa and Echo Devices.Device_Session_Events.csv",
            "Alexa and Echo Devices.Device_Session_Events.csv",
        )
        if raw is None:
            self._meta(meta, "alexa_sessions", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(
                _cell(rec, "Event Creation Date", "Event Recording Date")
            )
            year, month = _year_month(utc, local)
            rows.append(
                {
                    "device_type": _cell(rec, "Device Type"),
                    "device_app": _cell(rec, "Device Application"),
                    "locale": _cell(rec, "Device Locale"),
                    "marketplace": _cell(rec, "Marketplace"),
                    "event_ts_utc": utc,
                    "event_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "alexa_sessions", "Device_Session_Events", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _alexa_show_daily(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "event_ts_utc",
            "event_ts_local",
            "year",
            "month",
            "voice_count",
            "touch_count",
            "impression_count",
        ]
        opened = bundle.open_member(
            "Additional Data/Alexa and Echo Devices.Echo_Show_Generic_Events/"
            "Alexa and Echo Devices.Echo_Show_Generic_Events.csv",
            "Alexa and Echo Devices.Echo_Show_Generic_Events.csv",
        )
        if opened is None:
            self._meta(meta, "alexa_show_daily", None, 0, 0, "missing")
            return _empty(cols)
        fh, info = opened
        rows: list[dict[str, Any]] = []
        raw_n = 0
        with fh:
            for rec in _iter_csv_dicts(fh):
                raw_n += 1
                utc, local = _ts_pair(_cell(rec, "Event Creation Date"))
                year, month = _year_month(utc, local)
                rows.append(
                    {
                        "event_ts_utc": utc,
                        "event_ts_local": local,
                        "year": year,
                        "month": month,
                        "voice_count": _intish(_cell(rec, "Voice Engagement Count")) or 0,
                        "touch_count": _intish(_cell(rec, "Touch Engagement Count")) or 0,
                        "impression_count": _intish(_cell(rec, "Impression Count")) or 0,
                    }
                )
        self._meta(meta, "alexa_show_daily", info.filename, raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _alexa_skills(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["skill_name", "stage", "status", "enabled_ts_utc", "year"]
        raw = bundle.read(
            "Additional Data/Alexa/Skills/Skills-2.csv",
            "Skills-2.csv",
            "Skills.csv",
        )
        if raw is None:
            self._meta(meta, "alexa_skills", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, _ = _ts_pair(_cell(rec, "Enablement Date"))
            rows.append(
                {
                    "skill_name": _cell(rec, "SkillName", "Skill Name"),
                    "stage": _cell(rec, "SkillStage"),
                    "status": _cell(rec, "EnablementStatus"),
                    "enabled_ts_utc": utc,
                    "year": utc.year if utc else None,
                }
            )
        self._meta(meta, "alexa_skills", "Skills", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _alexa_routines(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["routine_name", "status", "payload_preview"]
        raw = bundle.read(
            "Additional Data/Alexa/Routines/Routines-4.json",
            "Additional Data/Alexa/Routines/Routines-2.json",
            "Routines.json",
        )
        if raw is None:
            self._meta(meta, "alexa_routines", None, 0, 0, "missing")
            return _empty(cols)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._meta(meta, "alexa_routines", "Routines.json", 0, 0, "bad_json")
            return _empty(cols)
        items = data if isinstance(data, list) else data.get("routines") or data.get("Automations") or [data]
        rows: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("friendlyName")
                or item.get("name")
                or item.get("routineName")
                or item.get("Name")
            )
            status = item.get("status") or item.get("Status")
            preview = json.dumps(item)[:500]
            rows.append(
                {
                    "routine_name": str(name) if name else None,
                    "status": str(status) if status else None,
                    "payload_preview": preview,
                }
            )
        self._meta(meta, "alexa_routines", "Routines.json", len(items), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _alexa_app_events(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "event_name",
            "platform",
            "device_make",
            "device_model",
            "event_ts_utc",
            "event_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Additional Data/Alexa/Devices/Mobile/CustomerInteraction_000-1.csv",
            "CustomerInteraction_000-1.csv",
        )
        if raw is None:
            self._meta(meta, "alexa_app_events", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(_cell(rec, "interaction_date"))
            year, month = _year_month(utc, local)
            rows.append(
                {
                    "event_name": _cell(rec, "event_name"),
                    "platform": _cell(rec, "device_platform_name"),
                    "device_make": _cell(rec, "device_make"),
                    "device_model": _cell(rec, "device_model"),
                    "event_ts_utc": utc,
                    "event_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "alexa_app_events", "CustomerInteraction", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _kindle_sessions(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "content_id",
            "duration_ms",
            "session_ts_utc",
            "session_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Additional Data/Kindle.Devices.ReadingSession/Kindle.Devices.ReadingSession.csv",
            "Kindle.Devices.ReadingSession.csv",
        )
        if raw is None:
            self._meta(meta, "kindle_sessions", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = _ts_pair(
                _cell(
                    rec,
                    "start_timestamp",
                    "startDate",
                    "Start Date",
                    "sessionStart",
                    "timestamp",
                    "Date",
                )
            )
            year, month = _year_month(utc, local)
            rows.append(
                {
                    "content_id": _cell(rec, "ASIN", "asin", "contentid", "contentId"),
                    "duration_ms": _intish(
                        _cell(
                            rec,
                            "total_reading_millis",
                            "totalReadingMillis",
                            "Total Reading Millis",
                            "duration",
                        )
                    ),
                    "session_ts_utc": utc,
                    "session_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "kindle_sessions", "ReadingSession", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _wishlists(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["list_name", "asin", "title", "raw_json"]
        rows: list[dict[str, Any]] = []
        raw_n = 0
        for cand in (
            "Additional Data/Amazon.Lists.Wishlist.2.2/Amazon.Lists.Wishlist.json",
            "Additional Data/Amazon.Lists.Wishlist.2.1/Amazon.Lists.Wishlist.json",
            "Additional Data/Amazon.Lists.Wishlist.1.1/Amazon.Lists.Wishlist.json",
            "Amazon.Lists.Wishlist.json",
        ):
            raw = bundle.read(cand)
            if raw is None:
                continue
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            raw_n += 1
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    {
                        "list_name": str(
                            item.get("listName")
                            or item.get("name")
                            or item.get("title")
                            or Path(cand).parent.name
                        ),
                        "asin": item.get("asin") or item.get("ASIN"),
                        "title": item.get("title") or item.get("productName"),
                        "raw_json": json.dumps(item)[:1000],
                    }
                )
        self._meta(meta, "wishlists", "Wishlist.json", raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _rufus(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["query", "asin", "product_name", "query_ts_utc", "query_ts_local", "year", "month"]
        raw = bundle.read(
            "Additional Data/SearchHistory.RufusConversations/Rufus.Conversation.Queries.csv",
            "Rufus.Conversation.Queries.csv",
        )
        if raw is None:
            self._meta(meta, "rufus_queries", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            q = _cell(
                rec,
                "Typed Query",
                "Autocompleted Query",
                "Query",
                "query",
                "Question",
                "Utterance",
                "Customer Query",
            )
            # Fall back to product context when typed query blank
            if q is None:
                q = _cell(rec, "Product Name")
            utc, local = _ts_pair(
                _cell(
                    rec,
                    "Request Date",
                    "Timestamp",
                    "Event Date",
                    "Date",
                    "Creation Date",
                    "Query Date",
                )
            )
            year, month = _year_month(utc, local)
            rows.append(
                {
                    "query": q,
                    "asin": _cell(rec, "ASIN", "asin"),
                    "product_name": _cell(rec, "Product Name"),
                    "query_ts_utc": utc,
                    "query_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "rufus_queries", "Rufus Queries", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _subscriptions(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "subscription_id",
            "status",
            "start_ts_utc",
            "end_ts_utc",
            "year",
        ]
        raw = bundle.read(
            "Additional Data/Digital.Subscriptions.2/Subscriptions.csv",
            "Subscriptions.csv",
        )
        if raw is None:
            self._meta(meta, "subscriptions", None, 0, 0, "missing")
            return _empty(cols)
        records = _read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            start, _ = _ts_pair(
                _cell(rec, "Subscription Start Date", "Contract Start Date", "Start Date")
            )
            end, _ = _ts_pair(
                _cell(rec, "Subscription End Date", "Contract End Date", "End Date")
            )
            rows.append(
                {
                    "subscription_id": _cell(
                        rec, "Subscription ID", "SubscriptionId", "subscriptionId"
                    ),
                    "status": _cell(rec, "Status", "Subscription Status"),
                    "start_ts_utc": start,
                    "end_ts_utc": end,
                    "year": start.year if start else None,
                }
            )
        self._meta(meta, "subscriptions", "Subscriptions.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _product_impressions(
        self, bundle: Any, meta: list[dict[str, Any]]
    ) -> pd.DataFrame:
        """Detail-page / buy-again impressions — no city/postal/UA/referer."""
        cols = [
            "kind",
            "asin",
            "product_name",
            "marketplace",
            "country_code",
            "device_type",
            "currency",
            "list_price",
            "seen_ts_utc",
            "seen_ts_local",
            "year",
            "month",
        ]
        rows: list[dict[str, Any]] = []
        raw_n = 0
        sources = (
            (
                "detail_page",
                (
                    "Additional Data/Request All Your Data.Detail Page Glance View Impressions/"
                    "Request All Your Data.Detail Page Glance View Impressions.csv",
                    "Request All Your Data.Detail Page Glance View Impressions.csv",
                ),
            ),
            (
                "buy_again",
                (
                    "Additional Data/Request All Your Data.Buy Again Customer Shopping Impressions/"
                    "Request All Your Data.Buy Again Customer Shopping Impressions.csv",
                    "Request All Your Data.Buy Again Customer Shopping Impressions.csv",
                ),
            ),
        )
        for kind, candidates in sources:
            raw = bundle.read(*candidates)
            if raw is None:
                continue
            records = _read_csv_dicts(raw)
            raw_n += len(records)
            for rec in records:
                utc, local = _ts_pair(_cell(rec, "creation_date", "Creation Date"))
                year, month = _year_month(utc, local)
                mkt = _cell(rec, "marketplace_id", "Marketplace")
                rows.append(
                    {
                        "kind": kind,
                        "asin": _cell(rec, "ASIN", "asin"),
                        "product_name": _cell(rec, "product_name", "Product Name"),
                        "marketplace": _marketplace_from_website(mkt) or mkt,
                        "country_code": _cell(
                            rec, "customer_country_code", "country_code", "Country Code"
                        ),
                        "device_type": _cell(rec, "device_type", "Device Type"),
                        "currency": _cell(
                            rec,
                            "website_list_price_currency_code",
                            "list_price_currency_code",
                        ),
                        "list_price": _money(
                            _cell(
                                rec,
                                "website_list_price",
                                "list_price_amount",
                                "merchant_asin_price",
                            )
                        ),
                        "seen_ts_utc": utc,
                        "seen_ts_local": local,
                        "year": year,
                        "month": month,
                    }
                )
        self._meta(meta, "product_impressions", "impressions/*", raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else _empty(cols)

    def _devices_summary(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        """Fire device registration — no serial plaintext, no IP."""
        cols = [
            "surface",
            "device_model",
            "amazon_model_name",
            "state",
            "customer_type",
            "serial_hash",
            "first_registered_utc",
            "last_registered_utc",
            "year",
        ]
        rows: list[dict[str, Any]] = []
        raw_n = 0
        for surface, candidates in (
            (
                "fire_tv",
                ("Your Fire TV Device & Setup/Device Registration.csv",),
            ),
            (
                "fire_tablet",
                ("Your Fire Tablet Device & Setup/Device Registration.csv",),
            ),
        ):
            raw = bundle.read(*candidates)
            if raw is None:
                continue
            records = _read_csv_dicts(raw)
            raw_n += len(records)
            for rec in records:
                first, _ = _ts_pair(_cell(rec, "First Time Registered"))
                last, _ = _ts_pair(_cell(rec, "Last Time Registered"))
                serial = _cell(rec, "Device Serial Number")
                rows.append(
                    {
                        "surface": surface,
                        "device_model": _cell(rec, "Device Model"),
                        "amazon_model_name": _cell(rec, "Amazon Device Model Name"),
                        "state": _cell(rec, "State"),
                        "customer_type": _cell(rec, "Customer Type"),
                        "serial_hash": _hash_id(serial),
                        "first_registered_utc": first,
                        "last_registered_utc": last,
                        "year": first.year if first else None,
                    }
                )
        if rows:
            df = pd.DataFrame(rows, columns=cols)
            df = df.drop_duplicates(
                subset=["surface", "serial_hash", "first_registered_utc"],
                keep="first",
            )
            self._meta(meta, "devices_summary", "Device Registration", raw_n, len(df))
            return df
        self._meta(meta, "devices_summary", None, 0, 0, "missing")
        return _empty(cols)

    def _rebuild_orders(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("DELETE FROM amazon.orders")
        conn.execute(
            """
            INSERT INTO amazon.orders
            SELECT
                order_id,
                min(order_ts_utc) AS order_ts_utc,
                min(order_ts_local) AS order_ts_local,
                min(year) AS year,
                min(month) AS month,
                any_value(marketplace) AS marketplace,
                any_value(website) AS website,
                any_value(currency) AS currency,
                count(*)::BIGINT AS n_items,
                sum(CASE WHEN NOT is_cancelled THEN coalesce(line_total, 0) ELSE 0 END)
                    AS total_amount,
                bool_or(is_cancelled) AS is_cancelled,
                any_value(order_status) AS status
            FROM amazon.order_items
            GROUP BY order_id
            """
        )

    def _create_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute(
            """
            CREATE TABLE amazon.dump_inventory (
                zip_part VARCHAR,
                path VARCHAR,
                ext VARCHAR,
                category VARCHAR,
                bytes BIGINT,
                ingested BOOLEAN,
                skip_reason VARCHAR
            );
            CREATE TABLE amazon.ingest_meta (
                logical_name VARCHAR,
                source_path VARCHAR,
                rows_raw BIGINT,
                rows_kept BIGINT,
                note VARCHAR
            );
            CREATE TABLE amazon.order_items (
                order_id VARCHAR,
                asin VARCHAR,
                product_name VARCHAR,
                department VARCHAR,
                dept_family VARCHAR,
                quantity BIGINT,
                currency VARCHAR,
                unit_price DOUBLE,
                unit_tax DOUBLE,
                line_total DOUBLE,
                shipping_charge DOUBLE,
                discounts DOUBLE,
                order_status VARCHAR,
                is_cancelled BOOLEAN,
                website VARCHAR,
                marketplace VARCHAR,
                order_ts_utc TIMESTAMP,
                order_ts_local TIMESTAMP,
                ship_ts_utc TIMESTAMP,
                year BIGINT,
                month BIGINT,
                surface VARCHAR
            );
            CREATE TABLE amazon.orders (
                order_id VARCHAR,
                order_ts_utc TIMESTAMP,
                order_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT,
                marketplace VARCHAR,
                website VARCHAR,
                currency VARCHAR,
                n_items BIGINT,
                total_amount DOUBLE,
                is_cancelled BOOLEAN,
                status VARCHAR
            );
            CREATE TABLE amazon.digital_items (
                order_id VARCHAR,
                asin VARCHAR,
                product_name VARCHAR,
                marketplace VARCHAR,
                currency VARCHAR,
                price DOUBLE,
                quantity BIGINT,
                order_status VARCHAR,
                order_ts_utc TIMESTAMP,
                order_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT,
                is_gift BOOLEAN,
                surface VARCHAR
            );
            CREATE TABLE amazon.returns (
                order_id VARCHAR,
                asin VARCHAR,
                product_name VARCHAR,
                return_reason VARCHAR,
                refund_amount DOUBLE,
                currency VARCHAR,
                status VARCHAR,
                return_ts_utc TIMESTAMP,
                return_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT,
                source_kind VARCHAR
            );
            CREATE TABLE amazon.cart_events (
                asin VARCHAR,
                product_name VARCHAR,
                quantity BIGINT,
                cart_source VARCHAR,
                added_ts_utc TIMESTAMP,
                added_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.searches (
                query_id VARCHAR,
                keywords VARCHAR,
                department VARCHAR,
                marketplace VARCHAR,
                device_category VARCHAR,
                clicked BOOLEAN,
                added BOOLEAN,
                purchased BOOLEAN,
                abandoned BOOLEAN,
                reformulated BOOLEAN,
                n_clicked BIGINT,
                n_ordered BIGINT,
                search_ts_utc TIMESTAMP,
                search_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.search_clicks (
                clicked_asin VARCHAR,
                added_asin VARCHAR,
                borrowed_asin VARCHAR
            );
            CREATE TABLE amazon.video_views (
                title VARCHAR,
                seconds_viewed BIGINT,
                device_model VARCHAR,
                content_quality VARCHAR,
                country_code VARCHAR,
                start_ts_utc TIMESTAMP,
                start_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.video_searches (
                query VARCHAR,
                device_name VARCHAR,
                search_ts_utc TIMESTAMP,
                search_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.audible_listens (
                asin VARCHAR,
                product_name VARCHAR,
                duration_ms BIGINT,
                narration_speed DOUBLE,
                start_ts_utc TIMESTAMP,
                start_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.audible_library (
                asin VARCHAR,
                title VARCHAR,
                authors VARCHAR,
                length_minutes BIGINT,
                purchase_ts_utc TIMESTAMP,
                year BIGINT
            );
            CREATE TABLE amazon.music_plays (
                asin VARCHAR,
                product_name VARCHAR,
                device_type VARCHAR,
                listen_ms BIGINT,
                track_ms BIGINT,
                play_ts_utc TIMESTAMP,
                play_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.music_searches (
                query VARCHAR,
                search_ts_utc TIMESTAMP,
                search_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.music_library (
                asin VARCHAR,
                title VARCHAR,
                artist_name VARCHAR,
                album_name VARCHAR,
                primary_genre VARCHAR,
                saved_ts_utc TIMESTAMP,
                year BIGINT
            );
            CREATE TABLE amazon.alexa_intents (
                utterance VARCHAR,
                utterance_tag VARCHAR,
                playing_song VARCHAR,
                intent_ts_utc TIMESTAMP,
                intent_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT,
                hour BIGINT,
                dow BIGINT
            );
            CREATE TABLE amazon.alexa_sessions (
                device_type VARCHAR,
                device_app VARCHAR,
                locale VARCHAR,
                marketplace VARCHAR,
                event_ts_utc TIMESTAMP,
                event_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.alexa_show_daily (
                event_ts_utc TIMESTAMP,
                event_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT,
                voice_count BIGINT,
                touch_count BIGINT,
                impression_count BIGINT
            );
            CREATE TABLE amazon.alexa_skills (
                skill_name VARCHAR,
                stage VARCHAR,
                status VARCHAR,
                enabled_ts_utc TIMESTAMP,
                year BIGINT
            );
            CREATE TABLE amazon.alexa_routines (
                routine_name VARCHAR,
                status VARCHAR,
                payload_preview VARCHAR
            );
            CREATE TABLE amazon.alexa_app_events (
                event_name VARCHAR,
                platform VARCHAR,
                device_make VARCHAR,
                device_model VARCHAR,
                event_ts_utc TIMESTAMP,
                event_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.kindle_sessions (
                content_id VARCHAR,
                duration_ms BIGINT,
                session_ts_utc TIMESTAMP,
                session_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.wishlists (
                list_name VARCHAR,
                asin VARCHAR,
                title VARCHAR,
                raw_json VARCHAR
            );
            CREATE TABLE amazon.rufus_queries (
                query VARCHAR,
                asin VARCHAR,
                product_name VARCHAR,
                query_ts_utc TIMESTAMP,
                query_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.subscriptions (
                subscription_id VARCHAR,
                status VARCHAR,
                start_ts_utc TIMESTAMP,
                end_ts_utc TIMESTAMP,
                year BIGINT
            );
            CREATE TABLE amazon.product_impressions (
                kind VARCHAR,
                asin VARCHAR,
                product_name VARCHAR,
                marketplace VARCHAR,
                country_code VARCHAR,
                device_type VARCHAR,
                currency VARCHAR,
                list_price DOUBLE,
                seen_ts_utc TIMESTAMP,
                seen_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            );
            CREATE TABLE amazon.devices_summary (
                surface VARCHAR,
                device_model VARCHAR,
                amazon_model_name VARCHAR,
                state VARCHAR,
                customer_type VARCHAR,
                serial_hash VARCHAR,
                first_registered_utc TIMESTAMP,
                last_registered_utc TIMESTAMP,
                year BIGINT
            );
            """
        )
