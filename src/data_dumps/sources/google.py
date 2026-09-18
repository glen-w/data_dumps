"""Google Takeout multipart export → DuckDB.

Folder of ``takeout-*.zip`` (or an extracted ``Takeout/`` tree). Keep-list only:

- Calendar ICS events
- Play Store installs / library / purchases / subscriptions (payment + IP scrubbed)
- Maps reviews + saved places (name + country_code only; no street/GPS)
- Saved lists (Want to go / Favourite places — title + URL; Addresses dropped)
- Photos supplemental metadata (timestamps only; geo dropped; media bytes stay in zip)
- My Activity HTML (YouTube / Drive / Gemini / Takeout)
- Tasks
- Dump inventory across all zip parts

Dropped at ingest: access logs (IPs/Gaia), mail mbox bodies, contacts, profile /
account HTML, Pay/Wallet, street addresses, photo/maps GPS, device configuration.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Paris")

ZIP_GLOB = "takeout-*.zip"
TAKEOUT_PREFIX = "Takeout/"

GOOGLE_TABLES = [
    "google.dump_inventory",
    "google.calendar_events",
    "google.play_installs",
    "google.play_library",
    "google.play_purchases",
    "google.play_subscriptions",
    "google.maps_reviews",
    "google.maps_saves",
    "google.saved_places",
    "google.photos",
    "google.activity",
    "google.tasks",
]

# Product path prefixes → inventory category.
_CATEGORY_RULES: list[tuple[str, str]] = [
    ("Google Photos/", "photos"),
    ("Drive/", "drive"),
    ("Mail/", "mail"),
    ("Access log activity/", "access_log"),
    ("Calendar/", "calendar"),
    ("Google Play Store/", "play"),
    ("Maps/", "maps"),
    ("Maps (your places)/", "maps"),
    ("Saved/", "saved"),
    ("My Activity/", "activity"),
    ("Fit/", "fit"),
    ("Tasks/", "tasks"),
    ("Contacts/", "contacts"),
    ("Profile/", "profile"),
    ("Google Account/", "account"),
    ("Google Pay/", "payments"),
    ("Google Wallet/", "payments"),
    ("Chrome/", "chrome"),
    ("Android Device Configuration Service/", "devices"),
]

_DROP_PREFIXES = (
    "Access log activity/",
    "Contacts/",
    "Profile/",
    "Google Account/",
    "Google Pay/",
    "Google Wallet/",
    "Android Device Configuration Service/",
    "Saved/Addresses.csv",
)

_ACTIVITY_DATE_RE = re.compile(
    r"^(\d{1,2} \w{3} \d{4}, \d{1,2}:\d{2}:\d{2} (?:AM |PM )?[A-Z]{3,4})$"
)
_ACTIVITY_DATE_RE2 = re.compile(
    r"^(\d{1,2} \w{3} \d{4}, \d{1,2}:\d{2}:\d{2} [A-Z]{3,5})$"
)


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {"N/A", "NA", "NONE", "NULL"}


def _empty(cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})


def _parse_utc(value: Any) -> datetime | None:
    if _blank(value):
        return None
    ts = pd.to_datetime(str(value).strip(), utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    py = ts.to_pydatetime()
    if py.tzinfo is None:
        py = py.replace(tzinfo=UTC)
    return py.astimezone(UTC)


def _ts_fields(utc: datetime | None) -> dict[str, Any]:
    if utc is None:
        return {
            "ts_utc": None,
            "ts_local": None,
            "year": None,
            "month": None,
            "day": None,
        }
    local = utc.astimezone(LOCAL_TZ)
    return {
        "ts_utc": utc.replace(tzinfo=None),
        "ts_local": local.replace(tzinfo=None),
        "year": local.year,
        "month": local.month,
        "day": local.date(),
    }


def _parse_activity_ts(text: str) -> datetime | None:
    raw = text.strip()
    # "29 Jan 2021, 19:12:27 CEST" — dateutil via pandas often works.
    ts = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(ts):
        # Fallback: strip timezone abbreviation and assume LOCAL_TZ.
        m = re.match(
            r"^(\d{1,2} \w{3} \d{4}, \d{1,2}:\d{2}:\d{2})",
            raw,
        )
        if not m:
            return None
        naive = pd.to_datetime(m.group(1), errors="coerce")
        if pd.isna(naive):
            return None
        local = naive.to_pydatetime().replace(tzinfo=LOCAL_TZ)
        return local.astimezone(UTC)
    return ts.to_pydatetime().astimezone(UTC)


def _category_for(rel: str) -> str:
    for prefix, cat in _CATEGORY_RULES:
        if rel.startswith(prefix) or rel == prefix.rstrip("/"):
            return cat
    return "other"


def _should_drop(rel: str) -> str | None:
    for prefix in _DROP_PREFIXES:
        if rel.startswith(prefix) or rel == prefix:
            return "pii_or_access_log"
    if rel.endswith(".mbox") or rel.endswith("/All mail Including Spam and Trash.mbox"):
        return "mail_mbox_not_loaded"
    lower = rel.lower()
    if lower.endswith(
        (".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4", ".gif", ".webp")
    ):
        if rel.startswith("Google Photos/") or rel.startswith("Drive/"):
            return "media_bytes_on_disk"
    if rel.startswith("Drive/") and not rel.endswith(".json"):
        return "drive_bytes_on_disk"
    if rel.startswith("Google Photos/") and not rel.endswith(".json"):
        return "media_bytes_on_disk"
    return None


def _takeout_rel(member: str) -> str | None:
    name = member.replace("\\", "/")
    if not name.startswith(TAKEOUT_PREFIX):
        return None
    return name[len(TAKEOUT_PREFIX) :]


def _is_takeout_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            for n in zf.namelist()[:40]:
                if n.replace("\\", "/").startswith(TAKEOUT_PREFIX):
                    return True
    except (OSError, zipfile.BadZipFile):
        return False
    return False


def _resolve_inputs(path: Path) -> tuple[list[Path], Path | None]:
    """Return (zip_paths, extract_root)."""
    path = path.resolve()
    if path.is_file() and path.suffix.lower() == ".zip":
        return [path], None
    if not path.is_dir():
        return [], None
    if (path / "Takeout").is_dir():
        zips = sorted(path.glob(ZIP_GLOB))
        return zips, path / "Takeout"
    zips = sorted(path.glob(ZIP_GLOB))
    if zips:
        return zips, None
    # Nested folder containing takeout zips
    nested = sorted(path.rglob(ZIP_GLOB))
    if nested:
        return nested, None
    return [], None


def _unfold_ics(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _parse_ics_dt(value: str, params: str) -> datetime | None:
    raw = value.strip()
    if "VALUE=DATE" in params.upper() or (len(raw) == 8 and raw.isdigit()):
        try:
            d = date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=LOCAL_TZ).astimezone(UTC)
    # Floating or Z
    m = re.match(r"^(\d{8})T(\d{6})(Z)?$", raw)
    if not m:
        ts = _parse_utc(raw)
        return ts
    ymd, hms, zulu = m.group(1), m.group(2), m.group(3)
    try:
        dt = datetime(
            int(ymd[0:4]),
            int(ymd[4:6]),
            int(ymd[6:8]),
            int(hms[0:2]),
            int(hms[2:4]),
            int(hms[4:6]),
        )
    except ValueError:
        return None
    if zulu or "Z" in raw:
        return dt.replace(tzinfo=UTC)
    # TZID in params
    tz_m = re.search(r"TZID=([^;:]+)", params)
    if tz_m:
        try:
            tz = ZoneInfo(tz_m.group(1).strip())
            return dt.replace(tzinfo=tz).astimezone(UTC)
        except Exception:
            pass
    return dt.replace(tzinfo=LOCAL_TZ).astimezone(UTC)


def parse_calendar_ics(text: str, filename: str) -> list[dict[str, Any]]:
    lines = _unfold_ics(text)
    cal_name = Path(filename).stem
    rows: list[dict[str, Any]] = []
    in_event = False
    fields: dict[str, tuple[str, str]] = {}
    for line in lines:
        if line.startswith("X-WR-CALNAME:"):
            cal_name = line.split(":", 1)[1].strip()
            continue
        if line == "BEGIN:VEVENT":
            in_event = True
            fields = {}
            continue
        if line == "END:VEVENT" and in_event:
            in_event = False
            uid = fields.get("UID", ("", ""))[1] or None
            summary = fields.get("SUMMARY", ("", ""))[1] or None
            status = fields.get("STATUS", ("", ""))[1] or None
            start = None
            end = None
            if "DTSTART" in fields:
                start = _parse_ics_dt(fields["DTSTART"][1], fields["DTSTART"][0])
            if "DTEND" in fields:
                end = _parse_ics_dt(fields["DTEND"][1], fields["DTEND"][0])
            # Skip missing/invalid starts and Google habit placeholders at epoch
            # (DTSTART:19700101T000000Z) or other out-of-range junk years.
            if start is None:
                continue
            tf = _ts_fields(start)
            year = tf["year"]
            if year is None or year < 1995 or year > 2035:
                continue
            dur = None
            if end:
                dur = max(0, int((end - start).total_seconds()))
            rows.append(
                {
                    "calendar_name": cal_name,
                    "uid": uid,
                    "summary": summary,
                    "status": status,
                    "ts_start_utc": tf["ts_utc"],
                    "ts_start_local": tf["ts_local"],
                    "ts_end_utc": end.replace(tzinfo=None) if end else None,
                    "duration_sec": dur,
                    "year": year,
                    "month": tf["month"],
                    "day": tf["day"],
                    "all_day": (
                        1
                        if start.hour == 0
                        and start.minute == 0
                        and (end is None or (end - start) >= timedelta(hours=23))
                        else 0
                    ),
                }
            )
            continue
        if not in_event or ":" not in line:
            continue
        # PROP;params:value
        left, right = line.split(":", 1)
        if ";" in left:
            prop, params = left.split(";", 1)
        else:
            prop, params = left, ""
        prop = prop.upper()
        if prop in {"UID", "SUMMARY", "STATUS", "DTSTART", "DTEND"}:
            fields[prop] = (params, right)
    return rows


def parse_activity_html(html: str, product_folder: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    chunks = html.split('class="outer-cell')
    for chunk in chunks[1:]:
        # Product title
        prod_m = re.search(
            r'class="mdl-typography--title"[^>]*>(.*?)</p>',
            chunk,
            re.S,
        )
        product = product_folder
        if prod_m:
            product = re.sub(r"<[^>]+>", "", prod_m.group(1)).strip() or product_folder
        body_m = re.search(
            r'class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1"(?! mdl-typography--text-right)[^>]*>(.*?)</div>',
            chunk,
            re.S,
        )
        if not body_m:
            continue
        body = body_m.group(1)
        links = re.findall(r'<a href="([^"]+)"[^>]*>(.*?)</a>', body, re.S)
        plain = re.sub(r"<br\s*/?>", "\n", body)
        plain = re.sub(r"<[^>]+>", "\n", plain)
        lines = [
            re.sub(r"\s+", " ", L).replace("\xa0", " ").strip()
            for L in plain.split("\n")
        ]
        lines = [L for L in lines if L]
        dt_line = None
        dt_idx = None
        for i, line in enumerate(lines):
            if _ACTIVITY_DATE_RE2.match(line) or _ACTIVITY_DATE_RE.match(line):
                dt_line = line
                dt_idx = i
                break
            # looser: contains month abbr + year + time
            if re.search(r"\d{1,2} \w{3} \d{4}, \d{1,2}:\d{2}:\d{2}", line):
                dt_line = line
                dt_idx = i
                break
        if dt_line is None or dt_idx is None:
            continue
        before = lines[:dt_idx]
        action = before[0] if before else None
        title_parts = before[1:] if len(before) > 1 else []
        if not title_parts and links:
            title_parts = [re.sub(r"<[^>]+>", "", t).strip() for _, t in links]
        title = " · ".join(p for p in title_parts if p) or None
        url = links[0][0] if links else None
        utc = _parse_activity_ts(dt_line)
        tf = _ts_fields(utc)
        rows.append(
            {
                "product": product,
                "action": action,
                "title": title,
                "url": url,
                **{k: tf[k] for k in ("ts_utc", "ts_local", "year", "month", "day")},
            }
        )
    return rows


def _read_member(
    zf: zipfile.ZipFile, name: str, max_bytes: int = 80_000_000
) -> bytes | None:
    info = zf.getinfo(name)
    if info.file_size > max_bytes:
        return None
    return zf.read(name)


class GoogleSource:
    name = "google"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            return _is_takeout_zip(path)
        if not path.is_dir():
            return False
        if (path / "Takeout" / "Calendar").is_dir():
            return True
        if (path / "Takeout" / "My Activity").is_dir():
            return True
        if any(_is_takeout_zip(z) for z in path.glob(ZIP_GLOB)):
            return True
        return any(_is_takeout_zip(z) for z in path.rglob(ZIP_GLOB))

    def tables(self) -> list[str]:
        return list(GOOGLE_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        raw = raw_dir("google")
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "source_path.txt").write_text(str(path) + "\n", encoding="utf-8")

        zip_paths, extract_root = _resolve_inputs(path)
        if not zip_paths and extract_root is None:
            raise FileNotFoundError(f"No Google Takeout found under {path}")

        inventory: list[dict[str, Any]] = []
        frames: dict[str, list[dict[str, Any]]] = {
            "calendar_events": [],
            "play_installs": [],
            "play_library": [],
            "play_purchases": [],
            "play_subscriptions": [],
            "maps_reviews": [],
            "maps_saves": [],
            "saved_places": [],
            "photos": [],
            "activity": [],
            "tasks": [],
        }

        opened: list[zipfile.ZipFile] = []
        try:
            for zp in zip_paths:
                zf = zipfile.ZipFile(zp)
                opened.append(zf)
                self._ingest_zip(zf, zp.name, inventory, frames)
            if extract_root is not None and not zip_paths:
                self._ingest_dir(extract_root, inventory, frames)
            elif extract_root is not None and zip_paths:
                # Prefer zips; skip dir to avoid double-count.
                pass
        finally:
            for zf in opened:
                zf.close()

        conn.execute("DROP SCHEMA IF EXISTS google CASCADE")
        conn.execute("CREATE SCHEMA google")
        self._create_tables(conn)

        inv_df = (
            pd.DataFrame(inventory)
            if inventory
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
        conn.register("_g_inv", inv_df)
        conn.execute("INSERT INTO google.dump_inventory BY NAME SELECT * FROM _g_inv")
        conn.unregister("_g_inv")

        table_cols = {
            "calendar_events": [
                "calendar_name",
                "uid",
                "summary",
                "status",
                "ts_start_utc",
                "ts_start_local",
                "ts_end_utc",
                "duration_sec",
                "year",
                "month",
                "day",
                "all_day",
            ],
            "play_installs": [
                "title",
                "document_type",
                "device_model",
                "device_manufacturer",
                "first_install_utc",
                "first_install_local",
                "last_update_utc",
                "year",
                "month",
                "day",
            ],
            "play_library": [
                "title",
                "document_type",
                "acquisition_utc",
                "acquisition_local",
                "year",
                "month",
                "day",
            ],
            "play_purchases": [
                "title",
                "document_type",
                "invoice_price",
                "user_country",
                "purchase_utc",
                "purchase_local",
                "year",
                "month",
                "day",
            ],
            "play_subscriptions": [
                "title",
                "document_type",
                "state",
                "expiration_utc",
                "expiration_local",
                "year",
                "month",
                "day",
            ],
            "maps_reviews": [
                "place_name",
                "country_code",
                "rating",
                "reviewed_utc",
                "reviewed_local",
                "year",
                "month",
                "day",
            ],
            "maps_saves": [
                "place_name",
                "country_code",
                "saved_utc",
                "saved_local",
                "year",
                "month",
                "day",
            ],
            "saved_places": [
                "list_name",
                "title",
                "url",
                "note",
            ],
            "photos": [
                "title",
                "album",
                "relative_path",
                "taken_utc",
                "taken_local",
                "year",
                "month",
                "day",
            ],
            "activity": [
                "product",
                "action",
                "title",
                "url",
                "ts_utc",
                "ts_local",
                "year",
                "month",
                "day",
            ],
            "tasks": [
                "list_title",
                "task_id",
                "title",
                "status",
                "created_utc",
                "completed_utc",
                "scheduled_utc",
                "year",
                "month",
                "day",
            ],
        }

        for table, cols in table_cols.items():
            rows = frames[table]
            df = pd.DataFrame(rows) if rows else _empty(cols)
            for c in cols:
                if c not in df.columns:
                    df[c] = None
            df = df[cols]
            tmp = f"_g_{table}"
            conn.register(tmp, df)
            conn.execute(f"INSERT INTO google.{table} BY NAME SELECT * FROM {tmp}")
            conn.unregister(tmp)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        def n(table: str) -> int:
            row = conn.execute(f"SELECT count(*) FROM google.{table}").fetchone()
            return int(row[0]) if row else 0

        cal = n("calendar_events")
        photos = n("photos")
        maps = n("maps_saves")
        play = n("play_installs")
        act = n("activity")
        inv = n("dump_inventory")
        span = conn.execute("""
            SELECT min(d), max(d) FROM (
                SELECT day AS d FROM google.calendar_events WHERE day IS NOT NULL
                UNION ALL
                SELECT day FROM google.photos WHERE day IS NOT NULL
                UNION ALL
                SELECT day FROM google.activity WHERE day IS NOT NULL
                UNION ALL
                SELECT day FROM google.maps_saves WHERE day IS NOT NULL
                UNION ALL
                SELECT day FROM google.play_installs WHERE day IS NOT NULL
            )
            """).fetchone()
        first_d = span[0] if span else None
        last_d = span[1] if span else None
        bytes_row = conn.execute(
            "SELECT coalesce(sum(bytes), 0) FROM google.dump_inventory"
        ).fetchone()
        total_bytes = int(bytes_row[0]) if bytes_row else 0
        summary = (
            f"google: {cal:,} calendar · {photos:,} photos · {maps:,} map saves · "
            f"{play:,} installs · {act:,} activity · inventory {inv:,} files "
            f"({total_bytes / (1024**3):.1f} GiB)"
        )
        if first_d and last_d:
            summary += f" · {first_d} → {last_d}"
        return {
            "summary": summary,
            "calendar_events": cal,
            "photos": photos,
            "maps_saves": maps,
            "play_installs": play,
            "activity": act,
            "dump_inventory": inv,
        }

    def _create_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE google.dump_inventory (
                zip_part VARCHAR,
                path VARCHAR,
                ext VARCHAR,
                category VARCHAR,
                bytes BIGINT,
                ingested BOOLEAN,
                skip_reason VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE google.calendar_events (
                calendar_name VARCHAR,
                uid VARCHAR,
                summary VARCHAR,
                status VARCHAR,
                ts_start_utc TIMESTAMP,
                ts_start_local TIMESTAMP,
                ts_end_utc TIMESTAMP,
                duration_sec INTEGER,
                year INTEGER,
                month INTEGER,
                day DATE,
                all_day INTEGER
            )
            """)
        conn.execute("""
            CREATE TABLE google.play_installs (
                title VARCHAR,
                document_type VARCHAR,
                device_model VARCHAR,
                device_manufacturer VARCHAR,
                first_install_utc TIMESTAMP,
                first_install_local TIMESTAMP,
                last_update_utc TIMESTAMP,
                year INTEGER,
                month INTEGER,
                day DATE
            )
            """)
        conn.execute("""
            CREATE TABLE google.play_library (
                title VARCHAR,
                document_type VARCHAR,
                acquisition_utc TIMESTAMP,
                acquisition_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                day DATE
            )
            """)
        conn.execute("""
            CREATE TABLE google.play_purchases (
                title VARCHAR,
                document_type VARCHAR,
                invoice_price VARCHAR,
                user_country VARCHAR,
                purchase_utc TIMESTAMP,
                purchase_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                day DATE
            )
            """)
        conn.execute("""
            CREATE TABLE google.play_subscriptions (
                title VARCHAR,
                document_type VARCHAR,
                state VARCHAR,
                expiration_utc TIMESTAMP,
                expiration_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                day DATE
            )
            """)
        conn.execute("""
            CREATE TABLE google.maps_reviews (
                place_name VARCHAR,
                country_code VARCHAR,
                rating INTEGER,
                reviewed_utc TIMESTAMP,
                reviewed_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                day DATE
            )
            """)
        conn.execute("""
            CREATE TABLE google.maps_saves (
                place_name VARCHAR,
                country_code VARCHAR,
                saved_utc TIMESTAMP,
                saved_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                day DATE
            )
            """)
        conn.execute("""
            CREATE TABLE google.saved_places (
                list_name VARCHAR,
                title VARCHAR,
                url VARCHAR,
                note VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE google.photos (
                title VARCHAR,
                album VARCHAR,
                relative_path VARCHAR,
                taken_utc TIMESTAMP,
                taken_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                day DATE
            )
            """)
        conn.execute("""
            CREATE TABLE google.activity (
                product VARCHAR,
                action VARCHAR,
                title VARCHAR,
                url VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                day DATE
            )
            """)
        conn.execute("""
            CREATE TABLE google.tasks (
                list_title VARCHAR,
                task_id VARCHAR,
                title VARCHAR,
                status VARCHAR,
                created_utc TIMESTAMP,
                completed_utc TIMESTAMP,
                scheduled_utc TIMESTAMP,
                year INTEGER,
                month INTEGER,
                day DATE
            )
            """)

    def _ingest_zip(
        self,
        zf: zipfile.ZipFile,
        zip_name: str,
        inventory: list[dict[str, Any]],
        frames: dict[str, list[dict[str, Any]]],
    ) -> None:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = _takeout_rel(info.filename)
            if rel is None:
                continue
            ext = Path(rel).suffix.lower().lstrip(".") or None
            cat = _category_for(rel)
            skip = _should_drop(rel)
            ingested = False
            skip_reason = skip
            # Selective parse
            try:
                if skip is None and self._try_parse_member(
                    zf, info.filename, rel, frames
                ):
                    ingested = True
                    skip_reason = None
                elif skip is None and cat in {
                    "calendar",
                    "play",
                    "maps",
                    "saved",
                    "activity",
                    "tasks",
                    "photos",
                }:
                    # Attempted but not a keep file shape
                    if not ingested:
                        skip_reason = skip_reason or "not_keep_list_shape"
            except Exception as exc:  # noqa: BLE001 — inventory continues
                skip_reason = f"parse_error:{type(exc).__name__}"
                ingested = False

            inventory.append(
                {
                    "zip_part": zip_name,
                    "path": rel,
                    "ext": ext,
                    "category": cat,
                    "bytes": int(info.file_size),
                    "ingested": ingested,
                    "skip_reason": skip_reason,
                }
            )

    def _ingest_dir(
        self,
        root: Path,
        inventory: list[dict[str, Any]],
        frames: dict[str, list[dict[str, Any]]],
    ) -> None:
        for fp in root.rglob("*"):
            if not fp.is_file():
                continue
            rel = fp.relative_to(root).as_posix()
            ext = fp.suffix.lower().lstrip(".") or None
            cat = _category_for(rel)
            skip = _should_drop(rel)
            ingested = False
            skip_reason = skip
            if skip is None:
                try:
                    data = fp.read_bytes()
                    if self._try_parse_bytes(rel, data, frames):
                        ingested = True
                        skip_reason = None
                except Exception as exc:  # noqa: BLE001
                    skip_reason = f"parse_error:{type(exc).__name__}"
            inventory.append(
                {
                    "zip_part": "(extracted)",
                    "path": rel,
                    "ext": ext,
                    "category": cat,
                    "bytes": fp.stat().st_size,
                    "ingested": ingested,
                    "skip_reason": skip_reason,
                }
            )

    def _try_parse_member(
        self,
        zf: zipfile.ZipFile,
        member: str,
        rel: str,
        frames: dict[str, list[dict[str, Any]]],
    ) -> bool:
        data = _read_member(zf, member)
        if data is None:
            return False
        return self._try_parse_bytes(rel, data, frames)

    def _try_parse_bytes(
        self,
        rel: str,
        data: bytes,
        frames: dict[str, list[dict[str, Any]]],
    ) -> bool:
        # Calendar
        if rel.startswith("Calendar/") and rel.lower().endswith(".ics"):
            text = data.decode("utf-8", errors="replace")
            frames["calendar_events"].extend(parse_calendar_ics(text, rel))
            return True

        # Play Store
        if rel == "Google Play Store/Installs.json":
            frames["play_installs"].extend(self._parse_installs(data))
            return True
        if rel == "Google Play Store/Library.json":
            frames["play_library"].extend(self._parse_library(data))
            return True
        if rel == "Google Play Store/Purchase History.json":
            frames["play_purchases"].extend(self._parse_purchases(data))
            return True
        if rel == "Google Play Store/Subscriptions.json":
            frames["play_subscriptions"].extend(self._parse_subscriptions(data))
            return True

        # Maps
        if rel == "Maps (your places)/Reviews.json":
            frames["maps_reviews"].extend(self._parse_maps_reviews(data))
            return True
        if rel == "Maps (your places)/Saved Places.json":
            frames["maps_saves"].extend(self._parse_maps_saves(data))
            return True

        # Saved lists (no Addresses)
        if rel in {"Saved/Want to go.csv", "Saved/Favourite places.csv"}:
            list_name = "want_to_go" if "Want" in rel else "favourite"
            frames["saved_places"].extend(self._parse_saved_csv(data, list_name))
            return True

        # Photos metadata
        if rel.startswith("Google Photos/") and rel.endswith(
            ".supplemental-metadata.json"
        ):
            row = self._parse_photo_meta(rel, data)
            if row:
                frames["photos"].append(row)
                return True

        # My Activity
        if rel.startswith("My Activity/") and rel.endswith("My Activity.html"):
            parts = rel.split("/")
            folder = parts[1] if len(parts) > 2 else "Activity"
            text = data.decode("utf-8", errors="replace")
            frames["activity"].extend(parse_activity_html(text, folder))
            return True

        # Tasks
        if rel == "Tasks/Tasks.json":
            frames["tasks"].extend(self._parse_tasks(data))
            return True

        return False

    def _parse_installs(self, data: bytes) -> list[dict[str, Any]]:
        payload = json.loads(data.decode("utf-8"))
        rows: list[dict[str, Any]] = []
        for item in payload if isinstance(payload, list) else []:
            inst = item.get("install") or {}
            doc = inst.get("doc") or {}
            device = inst.get("deviceAttribute") or {}
            first = _parse_utc(inst.get("firstInstallationTime"))
            last = _parse_utc(inst.get("lastUpdateTime"))
            tf = _ts_fields(first)
            rows.append(
                {
                    "title": doc.get("title"),
                    "document_type": doc.get("documentType"),
                    "device_model": device.get("model")
                    or device.get("deviceDisplayName"),
                    "device_manufacturer": device.get("manufacturer"),
                    "first_install_utc": tf["ts_utc"],
                    "first_install_local": tf["ts_local"],
                    "last_update_utc": last.replace(tzinfo=None) if last else None,
                    "year": tf["year"],
                    "month": tf["month"],
                    "day": tf["day"],
                }
            )
        return rows

    def _parse_library(self, data: bytes) -> list[dict[str, Any]]:
        payload = json.loads(data.decode("utf-8"))
        rows: list[dict[str, Any]] = []
        for item in payload if isinstance(payload, list) else []:
            lib = item.get("libraryDoc") or {}
            doc = lib.get("doc") or {}
            acq = _parse_utc(lib.get("acquisitionTime"))
            tf = _ts_fields(acq)
            rows.append(
                {
                    "title": doc.get("title"),
                    "document_type": doc.get("documentType"),
                    "acquisition_utc": tf["ts_utc"],
                    "acquisition_local": tf["ts_local"],
                    "year": tf["year"],
                    "month": tf["month"],
                    "day": tf["day"],
                }
            )
        return rows

    def _parse_purchases(self, data: bytes) -> list[dict[str, Any]]:
        payload = json.loads(data.decode("utf-8"))
        rows: list[dict[str, Any]] = []
        for item in payload if isinstance(payload, list) else []:
            ph = item.get("purchaseHistory") or {}
            doc = ph.get("doc") or {}
            purchase = _parse_utc(ph.get("purchaseTime"))
            tf = _ts_fields(purchase)
            # Deliberately omit paymentMethodTitle (emails) and IPs.
            rows.append(
                {
                    "title": doc.get("title"),
                    "document_type": doc.get("documentType"),
                    "invoice_price": ph.get("invoicePrice"),
                    "user_country": ph.get("userCountry"),
                    "purchase_utc": tf["ts_utc"],
                    "purchase_local": tf["ts_local"],
                    "year": tf["year"],
                    "month": tf["month"],
                    "day": tf["day"],
                }
            )
        return rows

    def _parse_subscriptions(self, data: bytes) -> list[dict[str, Any]]:
        payload = json.loads(data.decode("utf-8"))
        rows: list[dict[str, Any]] = []
        for item in payload if isinstance(payload, list) else []:
            sub = item.get("subscription") or {}
            doc = sub.get("doc") or {}
            exp = _parse_utc(sub.get("expirationDate"))
            tf = _ts_fields(exp)
            rows.append(
                {
                    "title": doc.get("title"),
                    "document_type": doc.get("documentType"),
                    "state": sub.get("state"),
                    "expiration_utc": tf["ts_utc"],
                    "expiration_local": tf["ts_local"],
                    "year": tf["year"],
                    "month": tf["month"],
                    "day": tf["day"],
                }
            )
        return rows

    def _parse_maps_reviews(self, data: bytes) -> list[dict[str, Any]]:
        payload = json.loads(data.decode("utf-8"))
        feats = payload.get("features") if isinstance(payload, dict) else []
        rows: list[dict[str, Any]] = []
        for feat in feats or []:
            props = feat.get("properties") or {}
            loc = props.get("location") or {}
            reviewed = _parse_utc(props.get("date"))
            tf = _ts_fields(reviewed)
            rows.append(
                {
                    "place_name": loc.get("name"),
                    "country_code": loc.get("country_code"),
                    "rating": props.get("five_star_rating_published"),
                    "reviewed_utc": tf["ts_utc"],
                    "reviewed_local": tf["ts_local"],
                    "year": tf["year"],
                    "month": tf["month"],
                    "day": tf["day"],
                }
            )
        return rows

    def _parse_maps_saves(self, data: bytes) -> list[dict[str, Any]]:
        payload = json.loads(data.decode("utf-8"))
        feats = payload.get("features") if isinstance(payload, dict) else []
        rows: list[dict[str, Any]] = []
        for feat in feats or []:
            props = feat.get("properties") or {}
            loc = props.get("location") or {}
            saved = _parse_utc(props.get("date"))
            tf = _ts_fields(saved)
            name = loc.get("name")
            if _blank(name):
                # Fallback: leave null rather than invent from URL/coords.
                name = None
            rows.append(
                {
                    "place_name": name,
                    "country_code": loc.get("country_code"),
                    "saved_utc": tf["ts_utc"],
                    "saved_local": tf["ts_local"],
                    "year": tf["year"],
                    "month": tf["month"],
                    "day": tf["day"],
                }
            )
        return rows

    def _parse_saved_csv(self, data: bytes, list_name: str) -> list[dict[str, Any]]:
        text = data.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows: list[dict[str, Any]] = []
        for row in reader:
            title = (row.get("Title") or "").strip()
            url = (row.get("URL") or "").strip()
            note = (row.get("Note") or "").strip() or None
            if not title and not url:
                continue
            rows.append(
                {
                    "list_name": list_name,
                    "title": title or None,
                    "url": url or None,
                    "note": note,
                }
            )
        return rows

    def _parse_photo_meta(self, rel: str, data: bytes) -> dict[str, Any] | None:
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        taken_raw = None
        ptt = payload.get("photoTakenTime") or {}
        if isinstance(ptt, dict):
            taken_raw = ptt.get("timestamp") or ptt.get("formatted")
        if _blank(taken_raw):
            ct = payload.get("creationTime") or {}
            if isinstance(ct, dict):
                taken_raw = ct.get("timestamp") or ct.get("formatted")
        utc = None
        if taken_raw is not None and str(taken_raw).isdigit():
            try:
                utc = datetime.fromtimestamp(int(taken_raw), tz=UTC)
            except (OverflowError, OSError, ValueError):
                utc = None
        if utc is None:
            utc = _parse_utc(taken_raw)
        tf = _ts_fields(utc)
        parts = Path(rel).parts
        album = parts[1] if len(parts) > 2 else None
        # Never keep geoData / geoDataExif
        return {
            "title": payload.get("title")
            or Path(rel).name.replace(".supplemental-metadata.json", ""),
            "album": album,
            "relative_path": rel,
            "taken_utc": tf["ts_utc"],
            "taken_local": tf["ts_local"],
            "year": tf["year"],
            "month": tf["month"],
            "day": tf["day"],
        }

    def _parse_tasks(self, data: bytes) -> list[dict[str, Any]]:
        payload = json.loads(data.decode("utf-8"))
        rows: list[dict[str, Any]] = []
        for lst in payload.get("items") or []:
            list_title = lst.get("title") or "Tasks"
            for task in lst.get("items") or []:
                created = _parse_utc(task.get("created") or task.get("updated"))
                completed = _parse_utc(task.get("completed"))
                scheduled = None
                for st in task.get("scheduled_time") or []:
                    if st.get("current"):
                        scheduled = _parse_utc(st.get("start"))
                        break
                tf = _ts_fields(created or completed or scheduled)
                rows.append(
                    {
                        "list_title": list_title,
                        "task_id": task.get("id"),
                        "title": task.get("title") or None,
                        "status": task.get("status"),
                        "created_utc": (
                            created.replace(tzinfo=None) if created else None
                        ),
                        "completed_utc": (
                            completed.replace(tzinfo=None) if completed else None
                        ),
                        "scheduled_utc": (
                            scheduled.replace(tzinfo=None) if scheduled else None
                        ),
                        "year": tf["year"],
                        "month": tf["month"],
                        "day": tf["day"],
                    }
                )
        return rows
