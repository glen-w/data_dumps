"""Shared constants and CSV helpers for Amazon ingest."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from zoneinfo import ZoneInfo

import pandas as pd

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
    (
        "info",
        re.compile(r"\b(what|who|when|where|how|define|wikipedia|tell me)\b", re.I),
    ),
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
                        if (
                            prev is None
                            or _prefer_curated(prev[1].filename, info.filename)
                            == info.filename
                        ):
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
        return zf.open(info), info  # type: ignore[return-value]
