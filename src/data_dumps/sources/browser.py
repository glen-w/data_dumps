"""Browser history JSON exports → DuckDB (`browser.pages`).

Supports:
- Firefox Sky History Export: ``[{id,url,title,lastVisitTime,visitCount}, …]``
- Chrome-style History Export: same fields plus ``lastVisitTimeTimestamp`` /
  ``typedCount`` (and optionally concatenated JSON arrays in one file)

Grain is one row per URL (last visit + visit count). Visit-level
``places.sqlite`` ingest is a future extension.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
import tldextract

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Rome")

BROWSER_TABLES = ["browser.pages", "browser.ingest_meta"]

SOURCE_FIREFOX_SKY = "firefox_sky"
SOURCE_LEGACY_CHROME = "legacy_chrome"

# Query params stripped from stored URLs (privacy).
SENSITIVE_PARAMS = frozenset(
    {
        "secret",
        "token",
        "password",
        "passwd",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "client_secret",
        "auth",
        "authorization",
        "session",
        "sessionid",
        "sid",
        "sig",
        "signature",
        "otp",
        "code",
    }
)

# Static host / etld1 → category (BrowserHistoryVisualizer-style allowlist).
CATEGORY_MAP: dict[str, str] = {
    "google.com": "search",
    "duckduckgo.com": "search",
    "bing.com": "search",
    "yahoo.com": "search",
    "youtube.com": "video",
    "youtu.be": "video",
    "vimeo.com": "video",
    "netflix.com": "video",
    "twitch.tv": "video",
    "wikipedia.org": "reference",
    "wikidata.org": "reference",
    "github.com": "dev",
    "gitlab.com": "dev",
    "bitbucket.org": "dev",
    "stackoverflow.com": "dev",
    "stackexchange.com": "dev",
    "huggingface.co": "dev",
    "npmjs.com": "dev",
    "pypi.org": "dev",
    "crates.io": "dev",
    "docker.com": "dev",
    "linkedin.com": "social",
    "twitter.com": "social",
    "x.com": "social",
    "facebook.com": "social",
    "instagram.com": "social",
    "reddit.com": "social",
    "amazon.com": "shopping",
    "amazon.co.uk": "shopping",
    "amazon.es": "shopping",
    "amazon.fr": "shopping",
    "amazon.de": "shopping",
    "ebay.com": "shopping",
    "ebay.fr": "shopping",
    "carrefour.fr": "shopping",
    "etsy.com": "shopping",
    "paypal.com": "finance",
    "stripe.com": "finance",
    "docs.google.com": "productivity",
    "drive.google.com": "productivity",
    "notion.so": "productivity",
    "notion.site": "productivity",
    "gmail.com": "mail",
    "mail.google.com": "mail",
    "outlook.com": "mail",
    "news.ycombinator.com": "news",
    "bbc.com": "news",
    "bbc.co.uk": "news",
    "nytimes.com": "news",
    "theguardian.com": "news",
    "medium.com": "reading",
    "substack.com": "reading",
    "spotify.com": "music",
    "open.spotify.com": "music",
    "soundcloud.com": "music",
    "chatgpt.com": "ai",
    "openai.com": "ai",
    "claude.ai": "ai",
    "anthropic.com": "ai",
    "gemini.google.com": "ai",
    "perplexity.ai": "ai",
}

SEARCH_HOST_HINTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("google.", "google", ("q", "query")),
    ("duckduckgo.com", "duckduckgo", ("q",)),
    ("bing.com", "bing", ("q",)),
    ("youtube.com", "youtube", ("search_query", "q")),
    ("search.yahoo.com", "yahoo", ("p", "q")),
    ("ecosia.org", "ecosia", ("q",)),
    ("startpage.com", "startpage", ("query", "q")),
)

_EXTRACTOR = tldextract.TLDExtract(
    suffix_list_urls=(),
    fallback_to_snapshot=True,
    cache_dir=None,
)

_PRIVATE_HOST_RE = re.compile(
    r"^(localhost|127\.0\.0\.1|0\.0\.0\.0|::1)$|"
    r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.)|"
    r"\.local$",
    re.IGNORECASE,
)


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {"N/A", "NA", "NONE", "NULL"}


def _load_json_values(path: Path) -> list[Any]:
    """Parse one or more concatenated top-level JSON values from a file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    decoder = json.JSONDecoder()
    idx = 0
    parts: list[Any] = []
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        obj, end = decoder.raw_decode(text, idx)
        parts.append(obj)
        idx = end
    return parts


def _records_from_parts(parts: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, list):
            for item in part:
                if isinstance(item, dict):
                    rows.append(item)
        elif isinstance(part, dict):
            for key in ("Browser History", "history", "History"):
                nested = part.get(key)
                if isinstance(nested, list):
                    for item in nested:
                        if isinstance(item, dict):
                            rows.append(item)
                    break
            else:
                if "url" in part:
                    rows.append(part)
    return rows


def looks_like_history_records(rows: list[dict[str, Any]], sample: int = 20) -> bool:
    if not rows:
        return False
    checked = 0
    hits = 0
    for row in rows[:sample]:
        checked += 1
        if "url" not in row:
            continue
        if "lastVisitTime" in row or "lastVisitTimeTimestamp" in row:
            hits += 1
    return checked > 0 and hits >= max(1, checked // 2)


def _classify_source(rows: list[dict[str, Any]], path: Path) -> str:
    sample = rows[:30]
    if any("lastVisitTimeTimestamp" in r or "typedCount" in r for r in sample):
        return SOURCE_LEGACY_CHROME
    name = path.name.lower()
    if name.startswith("history-") or "sky" in name:
        return SOURCE_FIREFOX_SKY
    return SOURCE_FIREFOX_SKY


def _is_canonical_file(path: Path) -> bool:
    return bool(re.match(r"^history-\d{4}-\d{2}-\d{2}", path.name, re.I))


def _ms_to_utc_naive(ms: float | int) -> datetime | None:
    try:
        value = float(ms)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value > 1e14:
        value = value / 1000.0
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=UTC).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _row_timestamp(row: dict[str, Any]) -> datetime | None:
    if "lastVisitTimeTimestamp" in row and not _blank(
        row.get("lastVisitTimeTimestamp")
    ):
        return _ms_to_utc_naive(row["lastVisitTimeTimestamp"])
    raw = row.get("lastVisitTime")
    if isinstance(raw, (int, float)):
        return _ms_to_utc_naive(raw)
    if isinstance(raw, str) and raw.strip().isdigit():
        return _ms_to_utc_naive(int(raw.strip()))
    return None


def _scrub_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if not parsed.query:
        return url
    pairs = parse_qs(parsed.query, keep_blank_values=True)
    kept: list[tuple[str, str]] = []
    for key, values in pairs.items():
        if key.lower() in SENSITIVE_PARAMS:
            continue
        for value in values:
            kept.append((key, value))
    new_query = urlencode(kept, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _is_private_host(host: str) -> bool:
    if not host:
        return False
    hostname = host.split(":")[0]
    return bool(_PRIVATE_HOST_RE.search(hostname))


def _etld1(host: str) -> str | None:
    if not host:
        return None
    hostname = host.split(":")[0].lower()
    if not hostname or _is_private_host(host):
        return hostname or None
    ext = _EXTRACTOR(hostname)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    if ext.domain:
        return ext.domain.lower()
    return hostname


def _category_for(host: str | None, etld1: str | None) -> str:
    if host:
        hostname = host.split(":")[0].lower()
        if hostname in CATEGORY_MAP:
            return CATEGORY_MAP[hostname]
        if _is_private_host(host):
            return "local"
        for key, cat in CATEGORY_MAP.items():
            if hostname == key or hostname.endswith("." + key):
                return cat
    if etld1:
        if etld1 in CATEGORY_MAP:
            return CATEGORY_MAP[etld1]
        for key, cat in CATEGORY_MAP.items():
            if etld1 == key or etld1.endswith("." + key):
                return cat
    return "other"


def _search_fields(host: str | None, url: str) -> tuple[str | None, str | None]:
    if not host:
        return None, None
    host_l = host.lower()
    try:
        qs = parse_qs(urlparse(url).query)
    except ValueError:
        return None, None
    for hint, engine, keys in SEARCH_HOST_HINTS:
        if hint in host_l:
            for key in keys:
                vals = qs.get(key) or []
                if vals and not _blank(vals[0]):
                    return engine, vals[0][:500]
            return engine, None
    return None, None


def normalize_record(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    url_raw = row.get("url")
    if _blank(url_raw):
        return None
    url = _scrub_url(str(url_raw).strip())
    last_visit = _row_timestamp(row)
    if last_visit is None:
        return None
    try:
        visit_count = int(row.get("visitCount") or 0)
    except (TypeError, ValueError):
        visit_count = 0
    if visit_count < 0:
        visit_count = 0
    typed_count: int | None
    try:
        typed_count = (
            int(row["typedCount"]) if row.get("typedCount") is not None else None
        )
    except (TypeError, ValueError):
        typed_count = None
    title = row.get("title")
    title_s = None if _blank(title) else str(title).strip()[:2000]
    export_id = None if _blank(row.get("id")) else str(row.get("id"))

    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    scheme = (parsed.scheme or "").lower() or None
    host = (parsed.netloc or "").lower() or None
    path = parsed.path or "/"
    etld1 = _etld1(host) if host else None
    is_private = bool(host and _is_private_host(host))
    category = _category_for(host, etld1)
    search_engine, search_query = _search_fields(host, url)
    local = last_visit.replace(tzinfo=UTC).astimezone(LOCAL_TZ)

    return {
        "url": url,
        "title": title_s,
        "last_visit_utc": last_visit,
        "last_visit_local": local.replace(tzinfo=None),
        "visit_count": visit_count,
        "typed_count": typed_count,
        "scheme": scheme,
        "host": host,
        "path": path[:2000],
        "etld1": etld1,
        "is_private": is_private,
        "category": category,
        "search_engine": search_engine,
        "search_query": search_query,
        "sources": [source],
        "export_ids": [export_id] if export_id else [],
        "year": local.year,
        "local_date": local.date(),
        "_canonical": source == SOURCE_FIREFOX_SKY,
    }


def merge_pages(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Merge normalized rows by URL; canonical identity wins; visit_count = max."""
    by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        url = row["url"]
        existing = by_url.get(url)
        if existing is None:
            by_url[url] = dict(row)
            continue
        sources = sorted(set(existing["sources"]) | set(row["sources"]))
        export_ids = list(
            dict.fromkeys([*existing["export_ids"], *row["export_ids"]])
        )
        prefer_new = row["_canonical"] and not existing["_canonical"]
        prefer_new_time = row["last_visit_utc"] > existing["last_visit_utc"]
        if prefer_new or (prefer_new_time and not existing["_canonical"]):
            chosen = dict(row)
            chosen["visit_count"] = max(existing["visit_count"], row["visit_count"])
            if existing["typed_count"] is not None:
                if chosen["typed_count"] is None:
                    chosen["typed_count"] = existing["typed_count"]
                else:
                    chosen["typed_count"] = max(
                        existing["typed_count"], chosen["typed_count"]
                    )
            if not chosen["title"] and existing["title"]:
                chosen["title"] = existing["title"]
        else:
            chosen = dict(existing)
            chosen["visit_count"] = max(existing["visit_count"], row["visit_count"])
            if prefer_new_time:
                for key in (
                    "last_visit_utc",
                    "last_visit_local",
                    "year",
                    "local_date",
                    "title",
                ):
                    if key == "title" and not row["title"]:
                        continue
                    chosen[key] = row[key]
            if row["typed_count"] is not None:
                if chosen["typed_count"] is None:
                    chosen["typed_count"] = row["typed_count"]
                else:
                    chosen["typed_count"] = max(
                        chosen["typed_count"], row["typed_count"]
                    )
            if not chosen["title"] and row["title"]:
                chosen["title"] = row["title"]
        chosen["sources"] = sources
        chosen["export_ids"] = export_ids
        chosen["_canonical"] = existing["_canonical"] or row["_canonical"]
        by_url[url] = chosen

    records = []
    for row in by_url.values():
        row = dict(row)
        row.pop("_canonical", None)
        row["sources"] = ",".join(row["sources"])
        row["export_ids"] = ",".join(x for x in row["export_ids"] if x)
        records.append(row)
    if not records:
        return pd.DataFrame(
            columns=[
                "url",
                "title",
                "last_visit_utc",
                "last_visit_local",
                "visit_count",
                "typed_count",
                "scheme",
                "host",
                "path",
                "etld1",
                "is_private",
                "category",
                "search_engine",
                "search_query",
                "sources",
                "export_ids",
                "year",
                "local_date",
            ]
        )
    return pd.DataFrame.from_records(records)


def _history_json_files(path: Path) -> list[Path]:
    path = path.resolve()
    if path.is_file() and path.suffix.lower() == ".json":
        files = [path]
        sibling = path.parent / "history.json"
        if path.name.lower() != "history.json" and sibling.is_file():
            files.append(sibling)
        return files
    if path.is_dir():
        dated = sorted(path.glob("history-*.json"))
        bare = path / "history.json"
        files = list(dated)
        if bare.is_file():
            files.append(bare)
        for cand in sorted(path.glob("*.json")):
            if cand in files:
                continue
            try:
                parts = _load_json_values(cand)
                rows = _records_from_parts(parts)
            except (json.JSONDecodeError, OSError, UnicodeError):
                continue
            if looks_like_history_records(rows):
                files.append(cand)
        return files
    return []


def _file_priority(path: Path) -> tuple[int, str]:
    if _is_canonical_file(path):
        return (0, path.name)
    if path.name.lower() == "history.json":
        return (2, path.name)
    return (1, path.name)


class BrowserSource:
    name = "browser"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        files = _history_json_files(path)
        if not files:
            return False
        for file in files:
            try:
                parts = _load_json_values(file)
                rows = _records_from_parts(parts)
            except (json.JSONDecodeError, OSError, UnicodeError):
                continue
            if looks_like_history_records(rows):
                return True
        return False

    def tables(self) -> list[str]:
        return list(BROWSER_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        files = sorted(_history_json_files(path), key=_file_priority)
        if not files:
            raise FileNotFoundError(f"no browser history JSON at {path}")

        dest = raw_dir("browser")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        normalized: list[dict[str, Any]] = []
        meta_rows: list[dict[str, Any]] = []
        for file in files:
            shutil.copy2(file, dest / file.name)
            parts = _load_json_values(file)
            raw_rows = _records_from_parts(parts)
            if not looks_like_history_records(raw_rows):
                continue
            source = _classify_source(raw_rows, file)
            kept = 0
            for raw in raw_rows:
                rec = normalize_record(raw, source)
                if rec is None:
                    continue
                normalized.append(rec)
                kept += 1
            meta_rows.append(
                {
                    "file_name": file.name,
                    "source_label": source,
                    "raw_rows": len(raw_rows),
                    "kept_rows": kept,
                    "is_canonical": source == SOURCE_FIREFOX_SKY
                    and _is_canonical_file(file),
                }
            )

        if not normalized:
            raise ValueError(f"no usable history rows in {path}")

        pages = merge_pages(normalized)
        meta = pd.DataFrame(meta_rows)

        conn.execute("CREATE SCHEMA IF NOT EXISTS browser")
        conn.execute("DROP TABLE IF EXISTS browser.pages")
        conn.execute("DROP TABLE IF EXISTS browser.ingest_meta")
        conn.register("_browser_pages", pages)
        conn.execute("CREATE TABLE browser.pages AS SELECT * FROM _browser_pages")
        conn.unregister("_browser_pages")
        conn.register("_browser_meta", meta)
        conn.execute(
            "CREATE TABLE browser.ingest_meta AS SELECT * FROM _browser_meta"
        )
        conn.unregister("_browser_meta")

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        n = conn.execute("SELECT count(*) FROM browser.pages").fetchone()
        span = conn.execute(
            """
            SELECT min(local_date), max(local_date),
                   sum(visit_count)::BIGINT, count(*) FILTER (WHERE is_private)
            FROM browser.pages
            """
        ).fetchone()
        n_rows = int(n[0]) if n else 0
        first = span[0] if span else None
        last = span[1] if span else None
        visits = int(span[2] or 0) if span else 0
        private_n = int(span[3] or 0) if span else 0
        files = conn.execute(
            "SELECT file_name, source_label, kept_rows FROM browser.ingest_meta"
        ).fetchall()
        file_bits = ", ".join(f"{r[0]}[{r[1]}:{r[2]}]" for r in files)
        summary = (
            f"browser.pages={n_rows} visits={visits} span={first}→{last} "
            f"private={private_n} files={file_bits}"
        )
        return {
            "n_pages": n_rows,
            "visit_sum": visits,
            "first_day": first,
            "last_day": last,
            "private_pages": private_n,
            "summary": summary,
        }
