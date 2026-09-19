"""Login, session, and access-log IPs from the original exports.

Source tables still omit addresses. This module only reads files the loaders
skip, looks public addresses up in local GeoLite2 databases, and caches the
result under the data root. Nothing is written back into the warehouse.
"""

from __future__ import annotations

import argparse
import csv
import io
import ipaddress
import json
import re
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from data_dumps.email_inventory import discover_exports
from data_dumps.export_walk import basename, iter_members, newest, parse_ytd, zip_hits
from data_dumps.paths import data_root, warehouse_db

COLUMNS = (
    "Service",
    "Provenance / use",
    "IP address",
    "First seen",
    "Last seen",
    "Events",
    "City",
    "Region",
    "Country",
    "ISP",
    "ASN",
    "Latitude",
    "Longitude",
)

# Normalized header / JSON key (letters and digits only).
_IP_KEYS = frozenset(
    {
        "ip",
        "ipaddress",
        "loginip",
        "lastip",
        "initialip",
        "mostrecentip",
        "usercreationip",
        "creationip",
    }
)
_SKIP_VALUES = frozenset({"", "n/a", "na", "none", "null", "not available"})
_SKIP_DESCENT = frozenset(
    {
        "text",
        "body",
        "message",
        "content",
        "html",
        "comment",
        "fulltext",
        "commentary",
        "subject",
        "title",
        "url",
    }
)
_LABELS = {
    "linkedin": "LinkedIn",
    "twitter": "Twitter",
    "google": "Google",
    "amazon": "Amazon",
    "uber": "Uber",
    "telegram": "Telegram",
    "chatgpt": "ChatGPT",
    "airbnb": "Airbnb",
    "ring": "Ring",
    "duolingo": "Duolingo",
    "slack": "Slack",
    "spotify_account": "Spotify",
}
# Slugs with no dedicated extractor. Key/header scan only — not message text.
_FALLBACK_SLUGS = frozenset({"chatgpt", "airbnb", "ring", "duolingo"})
_LOOSE_GLOBS = (
    "data/ip-audit*.js",
    "data/account-creation-ip*.js",
    "*/data/ip-audit*.js",
    "*/data/account-creation-ip*.js",
    "result.json",
    "*/result.json",
    "**/*.csv",
    "**/*.json",
    "**/*.js",
    "**/*.html",
)


@dataclass(frozen=True)
class IpHit:
    service: str
    use: str
    ip: str
    first: str | None = None
    last: str | None = None
    events: int = 1


@dataclass(frozen=True)
class IpLocation:
    city: str = ""
    region: str = ""
    country: str = ""
    isp: str = ""
    asn: str = ""
    lat: float | None = None
    lon: float | None = None


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def normalize_ip(value: str | None) -> str | None:
    """Return a canonical address, or None if this is not one."""
    if value is None:
        return None
    text = str(value).strip().strip("[]")
    if not text or text.lower() in _SKIP_VALUES:
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def is_public(ip: str) -> bool:
    """False for private, loopback, link-local, CGNAT, and documentation ranges."""
    try:
        return bool(ipaddress.ip_address(ip).is_global)
    except ValueError:
        return False


def _time_key(value: str) -> tuple[int, datetime | str]:
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:19]):
        try:
            return (0, datetime.fromisoformat(candidate))
        except ValueError:
            continue
    return (1, value)


def _times_in(row: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for key, value in row.items():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text or text.lower() in _SKIP_VALUES or not re.search(r"\d{4}", text):
            continue
        norm = _norm_key(str(key))
        if "offset" in norm:
            continue
        if any(
            hint in norm for hint in ("date", "time", "timestamp", "created", "active")
        ):
            found.append(text)
    return found


def _span(times: list[str]) -> tuple[str | None, str | None]:
    if not times:
        return None, None
    return min(times, key=_time_key), max(times, key=_time_key)


def _ip_csv_rows(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines[:40]):
        try:
            cells = next(csv.reader([line]))
        except csv.Error:
            continue
        if any(_norm_key(cell) in _IP_KEYS for cell in cells):
            start = index
            break
    if start is None:
        return []
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    return [
        row for row in reader if any((value or "").strip() for value in row.values())
    ]


def _csv_get(row: Mapping[str, Any], *names: str) -> str | None:
    lower = {(str(key) if key else "").strip().lower(): key for key in row}
    for name in names:
        key = lower.get(name.lower())
        if key is None:
            continue
        value = str(row.get(key) or "").strip()
        if value.lower() in _SKIP_VALUES:
            continue
        return value
    return None


def _hits_from_rows(
    service: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    use: str,
    use_of: Callable[[Mapping[str, Any]], str] | None = None,
) -> list[IpHit]:
    hits: list[IpHit] = []
    for row in rows:
        ip: str | None = None
        for key, value in row.items():
            if _norm_key(str(key)) not in _IP_KEYS:
                continue
            ip = normalize_ip(None if value is None else str(value))
            if ip:
                break
        if not ip:
            continue
        first, last = _span(_times_in(row))
        hits.append(IpHit(service, use_of(row) if use_of else use, ip, first, last, 1))
    return hits


def _walk_keys(node: Any, *, depth: int = 0) -> list[tuple[str, str, list[str]]]:
    """IP-valued keys only. Does not search inside message text."""
    if depth > 8:
        return []
    found: list[tuple[str, str, list[str]]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            norm = _norm_key(str(key))
            if norm in _IP_KEYS and isinstance(value, str):
                ip = normalize_ip(value)
                if ip:
                    found.append((str(key), ip, _times_in(node)))
                continue
            if norm in _SKIP_DESCENT:
                continue
            if isinstance(value, dict | list):
                found.extend(_walk_keys(value, depth=depth + 1))
    elif isinstance(node, list):
        for item in node[:5000]:
            if isinstance(item, dict | list):
                found.extend(_walk_keys(item, depth=depth + 1))
    return found


def extract_linkedin(path: Path) -> list[IpHit]:
    hits: list[IpHit] = []

    def use_of(row: Mapping[str, Any]) -> str:
        kind = _csv_get(row, "login type") or ""
        agent = _csv_get(row, "user agent") or ""
        label = f"account login · {kind}" if kind else "account login"
        if agent:
            short = agent if len(agent) <= 40 else agent[:37] + "..."
            label = f"{label} · {short}"
        return label

    for _name, data in iter_members(path, lambda name: basename(name) == "logins.csv"):
        hits.extend(
            _hits_from_rows(
                "LinkedIn", _ip_csv_rows(data), use="account login", use_of=use_of
            )
        )
    return hits


def extract_twitter(path: Path) -> list[IpHit]:
    hits: list[IpHit] = []

    def ok(name: str) -> bool:
        base = basename(name)
        return base.startswith("ip-audit") or base.startswith("account-creation-ip")

    globs = (
        "data/ip-audit*.js",
        "data/account-creation-ip*.js",
        "*/data/ip-audit*.js",
        "*/data/account-creation-ip*.js",
    )
    for name, data in iter_members(path, ok, globs):
        base = basename(name)
        use = (
            "account creation" if base.startswith("account-creation") else "login audit"
        )
        try:
            payload = parse_ytd(data)
        except json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            for _key, ip, times in _walk_keys(item):
                first, last = _span(times)
                hits.append(IpHit("Twitter", use, ip, first, last, 1))
    return hits


def extract_google(path: Path) -> list[IpHit]:
    hits: list[IpHit] = []

    def ok(name: str) -> bool:
        low = name.lower().replace("\\", "/")
        return "access log activity/" in low and low.endswith(".csv")

    for _name, data in iter_members(path, ok):
        hits.extend(_hits_from_rows("Google", _ip_csv_rows(data), use="access log"))
    return hits


def extract_amazon(path: Path) -> list[IpHit]:
    hits: list[IpHit] = []

    def ok(name: str) -> bool:
        return basename(name) == "device registration.csv"

    def use_of(row: Mapping[str, Any]) -> str:
        model = _csv_get(row, "amazon device model name", "device model") or ""
        return f"device registration · {model}" if model else "device registration"

    for _name, data in iter_members(path, ok):
        hits.extend(
            _hits_from_rows(
                "Amazon",
                _ip_csv_rows(data),
                use="device registration",
                use_of=use_of,
            )
        )
    return hits


def extract_uber(path: Path) -> list[IpHit]:
    """Event time and IP only. Device GPS in this file stays unread."""
    hits: list[IpHit] = []

    def ok(name: str) -> bool:
        base = basename(name)
        return "app_analytics" in base and base.endswith(".csv")

    for _name, data in iter_members(path, ok):
        hits.extend(_hits_from_rows("Uber", _ip_csv_rows(data), use="app analytics"))
    return hits


def extract_telegram(path: Path) -> list[IpHit]:
    hits: list[IpHit] = []

    def ok(name: str) -> bool:
        return basename(name) == "result.json"

    for _name, data in iter_members(path, ok, ("result.json", "*/result.json")):
        try:
            payload = json.loads(data.decode("utf-8-sig"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        sessions = payload.get("sessions")
        if not isinstance(sessions, dict):
            continue
        for item in sessions.get("list") or []:
            if not isinstance(item, dict):
                continue
            raw_ip = item.get("last_ip")
            ip = normalize_ip(raw_ip if isinstance(raw_ip, str) else None)
            if not ip:
                continue
            app = str(item.get("application_name") or "").strip()
            use = f"session · {app}" if app else "session"
            first, last = _span(
                [
                    text
                    for text in (item.get("created"), item.get("last_active"))
                    if isinstance(text, str) and text.strip()
                ]
            )
            hits.append(IpHit("Telegram", use, ip, first, last, 1))
    return hits


def _skip_fallback(name: str) -> bool:
    base = basename(name)
    if base.startswith("conversations-") or base == "chat.html":
        return True
    return "message" in base


def extract_fallback(path: Path, service: str) -> list[IpHit]:
    hits: list[IpHit] = []

    def ok(name: str) -> bool:
        if _skip_fallback(name):
            return False
        return basename(name).endswith((".csv", ".json", ".js", ".html"))

    for name, data in iter_members(path, ok, _LOOSE_GLOBS):
        base = basename(name)
        if base.endswith(".csv"):
            hits.extend(
                _hits_from_rows(service, _ip_csv_rows(data), use=Path(name).name)
            )
            continue
        if base.endswith(".html"):
            hits.extend(_html_hits(service, name, data))
            continue
        hits.extend(_json_hits(service, name, data))
    return hits


def _json_hits(service: str, name: str, data: bytes) -> list[IpHit]:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except json.JSONDecodeError:
        try:
            payload = parse_ytd(data)
        except json.JSONDecodeError:
            return []
    stem = Path(name).name
    return [
        IpHit(service, f"{stem} · {key}", ip, first, last, 1)
        for key, ip, times in _walk_keys(payload)
        for first, last in [_span(times)]
    ]


def _html_hits(service: str, name: str, data: bytes) -> list[IpHit]:
    from data_dumps.sources.airbnb import _kv_map, _parse_html_tables

    hits: list[IpHit] = []
    tables = _parse_html_tables(data.decode("utf-8", errors="replace"))
    for title, headers, rows in tables:
        if "key" not in [header.lower() for header in headers]:
            continue
        for key, value in _kv_map(rows).items():
            if _norm_key(key) not in _IP_KEYS:
                continue
            ip = normalize_ip(value)
            if not ip:
                continue
            label = title.strip() or Path(name).name
            hits.append(IpHit(service, f"{label} · {key}", ip))
    return hits


_EXTRACTORS: dict[str, Callable[[Path], list[IpHit]]] = {
    "linkedin": extract_linkedin,
    "twitter": extract_twitter,
    "google": extract_google,
    "amazon": extract_amazon,
    "uber": extract_uber,
    "telegram": extract_telegram,
}


def discover_telegram(root: Path | None = None) -> Path | None:
    root = root or data_root()
    folder = root / "telegram"
    if (folder / "result.json").is_file():
        return folder
    zips = zip_hits(folder)
    if zips:
        return newest(zips)
    if not folder.is_dir():
        return None
    for child in sorted(folder.iterdir()):
        if child.is_dir() and (child / "result.json").is_file():
            return child
    return None


def discover_ip_exports(root: Path | None = None) -> list[tuple[str, Path]]:
    root = root or data_root()
    found = list(discover_exports(root))
    telegram = discover_telegram(root)
    if telegram is not None:
        found.append(("telegram", telegram))
    return found


def scan_exports(root: Path | None = None) -> list[IpHit]:
    hits: list[IpHit] = []
    for slug, path in discover_ip_exports(root):
        extract = _EXTRACTORS.get(slug)
        try:
            if extract is not None:
                hits.extend(extract(path))
            elif slug in _FALLBACK_SLUGS:
                hits.extend(extract_fallback(path, _LABELS.get(slug, slug.title())))
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeError):
            continue
    return hits


def _aggregate(hits: list[IpHit]) -> list[IpHit]:
    buckets: dict[tuple[str, str, str], list[IpHit]] = {}
    for hit in hits:
        buckets.setdefault((hit.service, hit.use, hit.ip), []).append(hit)
    out: list[IpHit] = []
    for (service, use, ip), group in buckets.items():
        times: list[str] = []
        events = 0
        for hit in group:
            events += hit.events
            if hit.first:
                times.append(hit.first)
            if hit.last and hit.last != hit.first:
                times.append(hit.last)
        first, last = _span(times)
        out.append(IpHit(service, use, ip, first, last, events))
    out.sort(key=lambda hit: (hit.service.casefold(), hit.use.casefold(), hit.ip))
    return out


def geoip_dir() -> Path:
    return data_root() / "warehouse" / "geoip"


def _en_name(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    names = node.get("names")
    if not isinstance(names, dict) or not names:
        return ""
    value = names.get("en") or next(iter(names.values()))
    return str(value or "").strip()


def _location_from_records(city: Any, asn: Any) -> IpLocation:
    city_name = ""
    region = ""
    country = ""
    lat: float | None = None
    lon: float | None = None
    if isinstance(city, dict):
        city_name = _en_name(city.get("city"))
        country = _en_name(city.get("country"))
        subdivisions = city.get("subdivisions")
        if isinstance(subdivisions, list) and subdivisions:
            region = _en_name(subdivisions[0])
        location = city.get("location")
        if isinstance(location, dict):
            raw_lat = location.get("latitude")
            raw_lon = location.get("longitude")
            if isinstance(raw_lat, int | float) and isinstance(raw_lon, int | float):
                lat = float(raw_lat)
                lon = float(raw_lon)
    isp = ""
    asn_label = ""
    if isinstance(asn, dict):
        org = asn.get("autonomous_system_organization")
        if isinstance(org, str):
            isp = org.strip()
        number = asn.get("autonomous_system_number")
        if isinstance(number, int):
            asn_label = f"AS{number}"
        elif isinstance(number, str) and number.strip():
            asn_label = number.strip()
    return IpLocation(city_name, region, country, isp, asn_label, lat, lon)


def mmdb_present() -> tuple[bool, bool]:
    folder = geoip_dir()
    return (
        (folder / "GeoLite2-City.mmdb").is_file(),
        (folder / "GeoLite2-ASN.mmdb").is_file(),
    )


def _mmdb_lookup(ips: set[str]) -> dict[str, IpLocation]:
    import maxminddb

    folder = geoip_dir()
    city_reader = None
    asn_reader = None
    out: dict[str, IpLocation] = {}
    try:
        city_path = folder / "GeoLite2-City.mmdb"
        asn_path = folder / "GeoLite2-ASN.mmdb"
        if city_path.is_file():
            city_reader = maxminddb.open_database(str(city_path))
        if asn_path.is_file():
            asn_reader = maxminddb.open_database(str(asn_path))
        for ip in ips:
            if not is_public(ip):
                out[ip] = IpLocation()
                continue
            city = city_reader.get(ip) if city_reader is not None else None
            asn = asn_reader.get(ip) if asn_reader is not None else None
            out[ip] = _location_from_records(city, asn)
    except (OSError, ValueError, maxminddb.InvalidDatabaseError):
        for ip in ips:
            out.setdefault(ip, IpLocation())
    finally:
        if city_reader is not None:
            city_reader.close()
        if asn_reader is not None:
            asn_reader.close()
    return out


def resolve_locations(
    ips: Iterable[str],
    resolve: Callable[[str], IpLocation] | None = None,
) -> dict[str, IpLocation]:
    unique = set(ips)
    if resolve is None:
        return _mmdb_lookup(unique)
    return {ip: IpLocation() if not is_public(ip) else resolve(ip) for ip in unique}


def hits_frame(
    hits: list[IpHit],
    locations: Mapping[str, IpLocation],
) -> pd.DataFrame:
    rows = []
    for hit in _aggregate(hits):
        loc = locations.get(hit.ip, IpLocation())
        rows.append(
            {
                "Service": hit.service,
                "Provenance / use": hit.use,
                "IP address": hit.ip,
                "First seen": hit.first or "",
                "Last seen": hit.last or "",
                "Events": hit.events,
                "City": loc.city,
                "Region": loc.region,
                "Country": loc.country,
                "ISP": loc.isp,
                "ASN": loc.asn,
                "Latitude": loc.lat,
                "Longitude": loc.lon,
            }
        )
    return pd.DataFrame(rows, columns=list(COLUMNS))


def map_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """One bubble per city centroid. Size is event count, not device GPS."""
    empty = pd.DataFrame(
        columns=[
            "Place",
            "City",
            "Country",
            "Latitude",
            "Longitude",
            "Events",
            "Addresses",
        ]
    )
    if frame.empty or "Latitude" not in frame.columns:
        return empty
    plot = frame.dropna(subset=["Latitude", "Longitude"]).copy()
    if plot.empty:
        return empty
    plot["Events"] = pd.to_numeric(plot["Events"], errors="coerce").fillna(0)
    grouped = (
        plot.groupby(["City", "Country", "Latitude", "Longitude"], dropna=False)
        .agg(Events=("Events", "sum"), Addresses=("IP address", "nunique"))
        .reset_index()
    )

    def place(row: pd.Series) -> str:
        parts = [str(row["City"] or "").strip(), str(row["Country"] or "").strip()]
        return ", ".join(part for part in parts if part) or "Unknown"

    grouped["Place"] = grouped.apply(place, axis=1)
    return grouped


def _note(*, city: bool, asn: bool) -> str:
    text = (
        "Login, session, device, and access-log addresses from the original exports. "
        "The same address is repeated once per place it showed up. "
        "Source tables still do not store these. "
        "The map uses city centroids from the lookup, not device GPS."
    )
    missing: list[str] = []
    if not city:
        missing.append("`GeoLite2-City.mmdb`")
    if not asn:
        missing.append("`GeoLite2-ASN.mmdb`")
    if missing:
        text += (
            " Place "
            + " and ".join(missing)
            + " in `warehouse/geoip/` under the data root to fill location and ISP. "
            "Until then the table lists addresses only."
        )
    else:
        text += (
            " City, country, and network operator come from the local GeoLite2 files. "
            "Private and documentation addresses are listed but not plotted."
        )
    return text


def _cache_path() -> Path:
    return data_root() / "warehouse" / "ip_inventory.json"


def _stamp_targets(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    zips = zip_hits(path)
    if zips:
        return zips
    extra: list[Path] = []
    for rel in (
        "result.json",
        "data/ip-audit.js",
        "data/account-creation-ip.js",
        "data/account.js",
    ):
        child = path / rel
        if child.is_file():
            extra.append(child)
    extra.extend(sorted(path.glob("*.csv")))
    data = path / "data"
    if data.is_dir():
        extra.extend(sorted(data.glob("*.js")))
    return extra or [path]


def _stamps(exports: list[tuple[str, Path]]) -> list[list[object]]:
    paths: list[Path] = []
    db = warehouse_db()
    if db.is_file():
        paths.append(db)
    for _slug, path in exports:
        paths.extend(_stamp_targets(path))
    for name in ("GeoLite2-City.mmdb", "GeoLite2-ASN.mmdb"):
        paths.append(geoip_dir() / name)
    stamps: list[list[object]] = []
    for path in paths:
        try:
            stamp = path.stat().st_mtime_ns if path.is_file() else None
        except OSError:
            stamp = None
        stamps.append([str(path), stamp])
    stamps.sort()
    return stamps


def _read_cache(path: Path, stamps: list[list[object]]) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if payload.get("stamps") != stamps:
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None
    return pd.DataFrame(rows, columns=list(COLUMNS))


def _write_cache(path: Path, stamps: list[list[object]], frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(frame.to_json(orient="records"))
    payload = {"stamps": stamps, "rows": records}
    path.write_text(json.dumps(payload), encoding="utf-8")


def inventory_frame(
    conn: duckdb.DuckDBPyConnection,
    *,
    force: bool = False,
    resolve: Callable[[str], IpLocation] | None = None,
) -> tuple[pd.DataFrame, str]:
    """Table for the Tools tab. Uses the on-disk cache when exports have not changed."""
    conn.execute("SELECT 1")
    exports = discover_ip_exports()
    stamps = _stamps(exports)
    cache = _cache_path()
    city, asn = mmdb_present()
    note = _note(city=city, asn=asn)
    if not force and resolve is None:
        cached = _read_cache(cache, stamps)
        if cached is not None:
            return cached, note
    hits = scan_exports()
    locations = resolve_locations((hit.ip for hit in hits), resolve)
    frame = hits_frame(hits, locations)
    if resolve is None:
        try:
            _write_cache(cache, stamps, frame)
        except OSError:
            pass
    return frame, note


def main(argv: list[str] | None = None) -> int:
    """Print counts only. Addresses stay in the cache file, not the terminal."""
    parser = argparse.ArgumentParser(
        description="Rebuild the Tools IP index (counts only on stdout)"
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the cache and scan again",
    )
    args = parser.parse_args(argv)
    db = args.db or warehouse_db()
    if not db.is_file():
        print(f"error: no warehouse at {db}", file=sys.stderr)
        return 1
    conn = duckdb.connect(str(db), read_only=True)
    try:
        frame, note = inventory_frame(conn, force=args.refresh)
    finally:
        conn.close()
    print(f"{len(frame)} rows")
    if not frame.empty:
        print(f"  {int(frame['IP address'].nunique())} addresses")
        counts = frame.groupby("Service").size()
        for service, n in counts.sort_index().items():
            print(f"  {service}: {int(n)}")
    print(note)
    print(f"cache: {_cache_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
