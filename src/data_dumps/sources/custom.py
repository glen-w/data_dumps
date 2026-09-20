"""User-described event export → ``custom.sources`` / ``custom.events``.

A folder or zip whose root (or single enclosing folder) contains
``data_dumps.json`` plus one CSV, JSON, or JSONL file. Not a plugin scan:
this is one built-in loader. Code dashboards go in the single file
``$DATA_DUMPS_ROOT/user_contributions.py`` (see ``user_extensions``).
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

MANIFEST_NAME = "data_dumps.json"
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
DEFAULT_TZ = "Europe/Paris"
DEFAULT_ICON = "lucide:puzzle"

# Column names that must never land in custom.events, even if the manifest
# points time/entity/value at them.
_FORBIDDEN = frozenset(
    {
        "email",
        "e_mail",
        "email_address",
        "mail",
        "ip",
        "ip_address",
        "client_ip",
        "remote_addr",
        "remote_ip",
        "phone",
        "phone_number",
        "mobile",
        "telephone",
        "tel",
        "ssid",
        "password",
        "passwd",
        "ssn",
    }
)

_TABLES = ["custom.sources", "custom.events"]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def forbidden_column(name: str) -> bool:
    """True for email / IP / phone-like column names (and the static deny list)."""
    token = _norm(name)
    if not token or token in _FORBIDDEN:
        return token in _FORBIDDEN or not token
    if "email" in token or "phone" in token or "password" in token:
        return True
    if token == "ip" or token.endswith("_ip") or token.startswith("ip_"):
        return True
    return False


def _manifest_member(names: list[str]) -> str | None:
    hits = [
        name
        for name in names
        if Path(name).name == MANIFEST_NAME and not name.startswith("__MACOSX")
    ]
    if MANIFEST_NAME in hits:
        return MANIFEST_NAME
    rooted = [
        name for name in hits if name.count("/") == 1 and not name.startswith("/")
    ]
    if len(rooted) == 1:
        return rooted[0]
    return None


def _zip_names(path: Path) -> list[str] | None:
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    except zipfile.BadZipFile:
        return None


def manifest_exists(path: Path) -> bool:
    path = path.resolve()
    if path.is_dir():
        return (path / MANIFEST_NAME).is_file()
    if path.is_file() and path.suffix.lower() == ".zip":
        names = _zip_names(path)
        return names is not None and _manifest_member(names) is not None
    return False


def _read_manifest_bytes(path: Path) -> tuple[dict[str, Any], str]:
    """Return parsed manifest and the directory prefix inside a zip ('' for a folder)."""
    path = path.resolve()
    if path.is_dir():
        raw = (path / MANIFEST_NAME).read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("custom: data_dumps.json must be an object")
        return parsed, ""
    names = _zip_names(path)
    if names is None:
        raise ValueError(f"custom: not a zip: {path.name}")
    member = _manifest_member(names)
    if member is None:
        raise ValueError("custom: data_dumps.json not at the zip root")
    with zipfile.ZipFile(path) as zf:
        raw = zf.read(member).decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("custom: data_dumps.json must be an object")
    parent = str(Path(member).parent)
    prefix = "" if parent == "." else parent
    return parsed, prefix


def _safe_relative(name: str) -> Path:
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts or not name.strip():
        raise ValueError("custom: file must be a relative path inside the export")
    return rel


def _read_data_bytes(path: Path, prefix: str, relative: Path) -> bytes:
    path = path.resolve()
    if path.is_dir():
        target = path / relative
        if not target.is_file():
            raise ValueError(f"custom: missing data file {relative.as_posix()}")
        return target.read_bytes()
    member = relative.as_posix() if not prefix else f"{prefix}/{relative.as_posix()}"
    with zipfile.ZipFile(path) as zf:
        try:
            return zf.read(member)
        except KeyError as exc:
            raise ValueError(f"custom: zip has no {member}") from exc


def _records_from_obj(obj: Any) -> list[Any]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("events", "rows", "data", "items"):
            value = obj.get(key)
            if isinstance(value, list):
                return value
        lists = [value for value in obj.values() if isinstance(value, list)]
        if len(lists) == 1:
            return lists[0]
    raise ValueError(
        "custom: JSON must be a list of objects, or an object with an events/rows/data list"
    )


def _frame_from_bytes(raw: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
    if lower.endswith(".jsonl") or lower.endswith(".ndjson"):
        rows = []
        for line in raw.decode("utf-8-sig").splitlines():
            text = line.strip()
            if text:
                rows.append(json.loads(text))
        return pd.DataFrame(rows)
    if lower.endswith(".json"):
        return pd.DataFrame(_records_from_obj(json.loads(raw.decode("utf-8-sig"))))
    raise ValueError("custom: file must be .csv, .json, or .jsonl")


def _find_col(columns: list[str], wanted: str) -> str | None:
    wanted_norm = _norm(wanted)
    for col in columns:
        if col == wanted or _norm(str(col)) == wanted_norm:
            return str(col)
    return None


def _require_safe(role: str, column: str) -> None:
    if forbidden_column(column):
        raise ValueError(
            f"custom: {role} column {column!r} looks like email, IP, or phone — pick another"
        )


def _parse_times(series: pd.Series, tz: ZoneInfo) -> tuple[pd.Series, pd.Series]:
    parsed = pd.to_datetime(series, errors="coerce", utc=False)
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        local = parsed.dt.tz_convert(tz)
        utc = parsed.dt.tz_convert("UTC")
    else:
        local = parsed.dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward")
        utc = local.dt.tz_convert("UTC")
    return utc.dt.tz_localize(None), local.dt.tz_localize(None)


def _reserved_slugs() -> set[str]:
    from data_dumps.contributions import active_contributions

    return {item.slug for item in active_contributions()}


def _validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    slug = str(manifest.get("slug") or "").strip()
    if not SLUG_RE.match(slug):
        raise ValueError(
            "custom: slug must match ^[a-z][a-z0-9_]{0,31}$ (lowercase, no spaces)"
        )
    if slug in _reserved_slugs():
        raise ValueError(
            f"custom: slug {slug!r} is already a built-in or plug-in source"
        )
    file_name = manifest.get("file")
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("custom: manifest needs a string 'file'")
    time_col = manifest.get("time")
    if not isinstance(time_col, str) or not time_col.strip():
        raise ValueError("custom: manifest needs a string 'time' column")
    tz_name = str(manifest.get("timezone") or DEFAULT_TZ)
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"custom: unknown timezone {tz_name!r}") from exc
    label = str(manifest.get("label") or slug).strip() or slug
    icon = str(manifest.get("icon") or DEFAULT_ICON).strip() or DEFAULT_ICON
    if not icon.startswith("lucide:"):
        icon = DEFAULT_ICON
    entity = manifest.get("entity")
    value = manifest.get("value")
    entity_name = str(entity).strip() if isinstance(entity, str) else ""
    value_name = str(value).strip() if isinstance(value, str) else ""
    drop = manifest.get("drop") or []
    if not isinstance(drop, list) or not all(isinstance(item, str) for item in drop):
        raise ValueError("custom: drop must be a list of column names")
    grain = str(manifest.get("grain") or "one row per event")
    return {
        "slug": slug,
        "label": label,
        "icon": icon,
        "timezone": tz_name,
        "tz": tz,
        "grain": grain,
        "file": _safe_relative(file_name),
        "time": time_col.strip(),
        "entity": entity_name,
        "value": value_name,
        "drop": [_norm(item) for item in drop],
    }


def _events_frame(raw: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    if raw.empty:
        raise ValueError("custom: data file has no rows")
    columns = [str(col) for col in raw.columns]
    time_col = _find_col(columns, spec["time"])
    if time_col is None:
        raise ValueError(f"custom: time column {spec['time']!r} not in the file")
    _require_safe("time", time_col)
    entity_col = _find_col(columns, spec["entity"]) if spec["entity"] else None
    value_col = _find_col(columns, spec["value"]) if spec["value"] else None
    if spec["entity"] and entity_col is None:
        raise ValueError(f"custom: entity column {spec['entity']!r} not in the file")
    if spec["value"] and value_col is None:
        raise ValueError(f"custom: value column {spec['value']!r} not in the file")
    if entity_col:
        _require_safe("entity", entity_col)
    if value_col:
        _require_safe("value", value_col)
    dropped = set(spec["drop"])
    for col in (time_col, entity_col, value_col):
        if col and _norm(col) in dropped:
            raise ValueError(f"custom: drop list includes the mapped column {col!r}")

    utc, local = _parse_times(raw[time_col], spec["tz"])
    frame = pd.DataFrame(
        {
            "source_slug": spec["slug"],
            "ts_utc": utc,
            "ts_local": local,
        }
    )
    frame = frame.dropna(subset=["ts_local"])
    if frame.empty:
        raise ValueError(
            "custom: no rows had a parseable time. Use ISO-8601 datetimes in the time column."
        )
    local_ok = frame["ts_local"]
    frame["year"] = local_ok.dt.year.astype("int64")
    frame["month"] = local_ok.dt.month.astype("int64")
    frame["dow"] = (local_ok.dt.dayofweek + 1).astype("int64")
    frame["hour"] = local_ok.dt.hour.astype("int64")
    if entity_col:
        frame["entity"] = raw.loc[frame.index, entity_col].map(
            lambda item: "" if pd.isna(item) else str(item)
        )
    else:
        frame["entity"] = ""
    if value_col:
        frame["value"] = pd.to_numeric(
            raw.loc[frame.index, value_col], errors="coerce"
        ).fillna(0.0)
    else:
        frame["value"] = 1.0
    frame["entity"] = frame["entity"].astype(str)
    return frame.reset_index(drop=True)


def _ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS custom")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom.sources (
            slug VARCHAR PRIMARY KEY,
            label VARCHAR,
            icon VARCHAR,
            timezone VARCHAR,
            grain VARCHAR,
            entity_column VARCHAR,
            value_column VARCHAR
        )
        """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom.events (
            source_slug VARCHAR,
            ts_utc TIMESTAMP,
            ts_local TIMESTAMP,
            year INTEGER,
            month INTEGER,
            dow INTEGER,
            hour INTEGER,
            entity VARCHAR,
            value DOUBLE
        )
        """)


def _write_raw(
    spec: dict[str, Any], events: pd.DataFrame, manifest: dict[str, Any]
) -> None:
    dest = raw_dir("custom") / spec["slug"]
    dest.mkdir(parents=True, exist_ok=True)
    kept = {
        key: manifest[key]
        for key in (
            "slug",
            "label",
            "icon",
            "timezone",
            "grain",
            "file",
            "time",
            "entity",
            "value",
        )
        if key in manifest and manifest[key] not in (None, "")
    }
    (dest / MANIFEST_NAME).write_text(
        json.dumps(kept, indent=2) + "\n", encoding="utf-8"
    )
    # Cleaned rows only — original email / IP / phone columns are not copied.
    events.to_csv(dest / "events.csv", index=False)


class CustomSource:
    """One manifest export. Re-ingest replaces that slug and leaves the others."""

    name = "custom"

    def __init__(self) -> None:
        self._loaded_slug: str | None = None

    def detect(self, path: Path) -> bool:
        return manifest_exists(path)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        manifest, prefix = _read_manifest_bytes(path)
        spec = _validate_manifest(manifest)
        raw_bytes = _read_data_bytes(path, prefix, spec["file"])
        raw = _frame_from_bytes(raw_bytes, spec["file"].name)
        events = _events_frame(raw, spec)
        _ensure_schema(conn)
        conn.execute("DELETE FROM custom.events WHERE source_slug = ?", [spec["slug"]])
        conn.execute("DELETE FROM custom.sources WHERE slug = ?", [spec["slug"]])
        conn.execute(
            """
            INSERT INTO custom.sources VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                spec["slug"],
                spec["label"],
                spec["icon"],
                spec["timezone"],
                spec["grain"],
                spec["entity"],
                spec["value"],
            ],
        )
        conn.register("_custom_events", events)
        conn.execute("""
            INSERT INTO custom.events
            SELECT source_slug, ts_utc, ts_local, year, month, dow, hour, entity, value
            FROM _custom_events
            """)
        conn.unregister("_custom_events")
        _write_raw(spec, events, manifest)
        self._loaded_slug = spec["slug"]

    def tables(self) -> list[str]:
        return list(_TABLES)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        _ensure_schema(conn)
        n_sources = conn.execute("SELECT count(*) FROM custom.sources").fetchone()
        n_events = conn.execute("SELECT count(*) FROM custom.events").fetchone()
        span = conn.execute("""
            SELECT min(CAST(ts_local AS DATE)), max(CAST(ts_local AS DATE))
            FROM custom.events
            """).fetchone()
        sources = int(n_sources[0]) if n_sources else 0
        events = int(n_events[0]) if n_events else 0
        first = span[0] if span else None
        last = span[1] if span else None
        window = f" {first}→{last}" if first and last else ""
        loaded = f" loaded={self._loaded_slug}" if self._loaded_slug else ""
        return {
            "n_sources": sources,
            "n_events": events,
            "summary": f"custom: {sources} sources, {events} events{window}{loaded}",
        }
