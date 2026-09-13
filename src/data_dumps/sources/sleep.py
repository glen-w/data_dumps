"""Sleep as Android export → DuckDB.

Canonical package is sleep-export.zip (sleep-export.csv + optional
prefs.xml / noise.json / alarms.json). Also accepts a bare sleep-export.csv
or a folder containing it.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Rome")

CORE_COLS = {
    "Id",
    "Tz",
    "From",
    "To",
    "Sched",
    "Hours",
    "Rating",
    "Comment",
    "Framerate",
    "Snore",
    "Noise",
    "Cycles",
    "DeepSleep",
    "LenAdjust",
    "Geo",
}
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
TAG_RE = re.compile(r"#\w+")
EVENT_RE = re.compile(r"^([A-Z0-9_]+)-(\d+)$")

SLEEP_TABLES = [
    "sleep.sessions",
    "sleep.events",
    "sleep.actigraphy",
    "sleep.alarms",
]

# Sleep as Android alarms.json ``daysOfWeek.days`` bitmask, Monday = bit 0.
ALARM_DAY_BITS = [
    (1, "Mon"),
    (2, "Tue"),
    (4, "Wed"),
    (8, "Thu"),
    (16, "Fri"),
    (32, "Sat"),
    (64, "Sun"),
]

ALARM_COLUMNS = [
    "id",
    "hour",
    "minute",
    "enabled",
    "days_mask",
    "days",
    "label",
    "smart_window_min",
    "next_time_local",
]


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {"N/A", "NA", "NONE", "NULL"}


def _parse_saa_dt(value: str, tz_name: str | None) -> datetime | None:
    """Parse Sleep as Android 'dd. MM. yyyy H:mm' (or without spaces)."""
    if _blank(value):
        return None
    raw = str(value).strip()
    naive: datetime | None = None
    for fmt in ("%d. %m. %Y %H:%M", "%d.%m.%Y %H:%M", "%d. %m. %Y %H:%M:%S"):
        try:
            naive = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    else:
        ts = pd.to_datetime(raw, dayfirst=True, errors="coerce")
        if pd.isna(ts):
            # Retry ISO-ish timestamps without dayfirst
            ts = pd.to_datetime(raw, dayfirst=False, errors="coerce")
        if pd.isna(ts):
            return None
        naive = ts.to_pydatetime().replace(tzinfo=None)

    if naive is None:
        return None
    tz: ZoneInfo | None = None
    if tz_name and not _blank(tz_name):
        try:
            tz = ZoneInfo(str(tz_name).strip())
        except ZoneInfoNotFoundError:
            tz = None
    if tz is None:
        tz = LOCAL_TZ
    return naive.replace(tzinfo=tz)


def _ts_pair(dt: datetime | None) -> tuple[datetime | None, datetime | None]:
    if dt is None:
        return None, None
    utc_naive = dt.astimezone(UTC).replace(tzinfo=None)
    local_naive = dt.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return utc_naive, local_naive


def _float(value: Any) -> float | None:
    if _blank(value):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    f = _float(value)
    if f is None:
        return None
    return int(f)


def _find_csv(path: Path) -> Path | None:
    if path.is_file() and path.name == "sleep-export.csv":
        return path
    if path.is_dir():
        direct = path / "sleep-export.csv"
        if direct.exists():
            return direct
        matches = list(path.rglob("sleep-export.csv"))
        return matches[0] if matches else None
    return None


def _extract_to_raw(path: Path) -> Path:
    dest = raw_dir("sleep")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            zf.extractall(dest)
    elif path.is_file() and path.name.endswith(".csv"):
        shutil.copy2(path, dest / "sleep-export.csv")
    elif path.is_dir():
        csv_path = _find_csv(path)
        if csv_path is None:
            raise FileNotFoundError(f"no sleep-export.csv under {path}")
        shutil.copy2(csv_path, dest / "sleep-export.csv")
        for side in ("prefs.xml", "noise.json", "alarms.json"):
            cand = path / side
            if cand.exists():
                shutil.copy2(cand, dest / side)
    else:
        raise FileNotFoundError(f"unsupported sleep path: {path}")
    return dest


def _classify_header(header: list[str]) -> tuple[list[str], list[int], list[int]]:
    names: list[str] = []
    act_idxs: list[int] = []
    ev_idxs: list[int] = []
    for i, raw in enumerate(header):
        h = (raw or "").strip().strip('"')
        names.append(h)
        if h in CORE_COLS:
            continue
        if TIME_RE.match(h):
            act_idxs.append(i)
        elif h == "Event" or h.startswith("Event"):
            ev_idxs.append(i)
    return names, act_idxs, ev_idxs


def _parse_export(csv_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    text = csv_path.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    names, act_idxs, ev_idxs = _classify_header(header)
    core_idx = {n: names.index(n) for n in CORE_COLS if n in names}

    session_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    act_rows: list[dict[str, Any]] = []

    for row in reader:
        if not row or all(not (c or "").strip() for c in row):
            continue

        def cell(col: str, _row: list[str] = row) -> str:
            idx = core_idx.get(col)
            if idx is None or idx >= len(_row):
                return ""
            return (_row[idx] or "").strip()

        sid = cell("Id")
        if not sid:
            continue
        tz_name = cell("Tz") or None
        from_dt = _parse_saa_dt(cell("From"), tz_name)
        to_dt = _parse_saa_dt(cell("To"), tz_name)
        sched_dt = _parse_saa_dt(cell("Sched"), tz_name)
        from_utc, from_local = _ts_pair(from_dt)
        to_utc, to_local = _ts_pair(to_dt)
        sched_utc, sched_local = _ts_pair(sched_dt)
        comment = cell("Comment")
        tags = " ".join(sorted(set(TAG_RE.findall(comment)))) if comment else None
        hours = _float(cell("Hours"))
        deep = _float(cell("DeepSleep"))
        deep_hours = (hours * deep) if hours is not None and deep is not None else None

        session_rows.append(
            {
                "id": sid,
                "tz": tz_name,
                "from_utc": from_utc,
                "from_local": from_local,
                "to_utc": to_utc,
                "to_local": to_local,
                "sched_utc": sched_utc,
                "sched_local": sched_local,
                "hours": hours,
                "rating": _float(cell("Rating")),
                "comment": comment or None,
                "tags": tags,
                "framerate": _int(cell("Framerate")),
                "snore": _int(cell("Snore")),
                "noise": _float(cell("Noise")),
                "cycles": _int(cell("Cycles")),
                "deep_sleep": deep,
                "deep_hours": deep_hours,
                "len_adjust": _int(cell("LenAdjust")),
                "geo": cell("Geo") or None,
                "local_date": from_local.date() if from_local else None,
                "year": from_local.year if from_local else None,
                "weekday": from_local.isoweekday() if from_local else None,
                "bed_hour": from_local.hour if from_local else None,
                "wake_hour": to_local.hour if to_local else None,
            }
        )

        seen_events: set[str] = set()
        for i in ev_idxs:
            if i >= len(row):
                continue
            raw_ev = (row[i] or "").strip()
            if not raw_ev or raw_ev in seen_events:
                continue
            seen_events.add(raw_ev)
            m = EVENT_RE.match(raw_ev)
            if m:
                etype, ets = m.group(1), int(m.group(2))
                ev_dt = datetime.fromtimestamp(ets / 1000.0, tz=UTC)
            else:
                etype, ev_dt = raw_ev, None
            ev_utc, ev_local = _ts_pair(ev_dt)
            event_rows.append(
                {
                    "session_id": sid,
                    "event_type": etype,
                    "event_raw": raw_ev,
                    "ts_utc": ev_utc,
                    "ts_local": ev_local,
                }
            )

        for i in act_idxs:
            if i >= len(row):
                continue
            val = (row[i] or "").strip()
            if not val:
                continue
            act_rows.append(
                {
                    "session_id": sid,
                    "bucket_label": names[i],
                    "value": _float(val),
                }
            )

    sessions = pd.DataFrame(session_rows)
    events = pd.DataFrame(event_rows)
    actigraphy = pd.DataFrame(act_rows)
    if sessions.empty:
        sessions = pd.DataFrame(
            columns=[
                "id",
                "tz",
                "from_utc",
                "from_local",
                "to_utc",
                "to_local",
                "sched_utc",
                "sched_local",
                "hours",
                "rating",
                "comment",
                "tags",
                "framerate",
                "snore",
                "noise",
                "cycles",
                "deep_sleep",
                "deep_hours",
                "len_adjust",
                "geo",
                "local_date",
                "year",
                "weekday",
                "bed_hour",
                "wake_hour",
            ]
        )
    if events.empty:
        events = pd.DataFrame(
            columns=["session_id", "event_type", "event_raw", "ts_utc", "ts_local"]
        )
    if actigraphy.empty:
        actigraphy = pd.DataFrame(columns=["session_id", "bucket_label", "value"])
    return sessions, events, actigraphy


def _decode_alarm_days(mask: int | None) -> str | None:
    if mask is None or mask <= 0:
        return None
    return " ".join(name for bit, name in ALARM_DAY_BITS if mask & bit)


def _parse_alarms(path: Path) -> pd.DataFrame:
    """Parse the ``alarms.json`` sidecar (list of alarm dicts) into a flat frame."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return pd.DataFrame(columns=ALARM_COLUMNS)
    items = payload if isinstance(payload, list) else payload.get("alarms", [])
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dow = item.get("daysOfWeek")
        mask = dow.get("days") if isinstance(dow, dict) else item.get("days")
        mask_int = _int(mask)
        next_ms = _int(item.get("time"))
        next_local = (
            datetime.fromtimestamp(next_ms / 1000.0, tz=UTC)
            .astimezone(LOCAL_TZ)
            .replace(tzinfo=None)
            if next_ms and next_ms > 0
            else None
        )
        rows.append(
            {
                "id": _int(item.get("id")),
                "hour": _int(item.get("hour")),
                "minute": _int(item.get("minutes", item.get("minute"))),
                "enabled": bool(item.get("enabled", False)),
                "days_mask": mask_int,
                "days": _decode_alarm_days(mask_int),
                "label": item.get("label") or item.get("name") or None,
                "smart_window_min": _int(item.get("nonDeepsleepWakeupWindow")),
                "next_time_local": next_local,
            }
        )
    if not rows:
        return pd.DataFrame(columns=ALARM_COLUMNS)
    return pd.DataFrame(rows, columns=ALARM_COLUMNS)


class SleepSource:
    name = "sleep"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.name == "sleep-export.csv":
            return True
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    names = zf.namelist()
            except zipfile.BadZipFile:
                return False
            return any(n.endswith("sleep-export.csv") for n in names)
        if path.is_dir():
            return _find_csv(path) is not None
        return False

    def tables(self) -> list[str]:
        return list(SLEEP_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        raw = _extract_to_raw(path)
        csv_path = raw / "sleep-export.csv"
        if not csv_path.exists():
            found = _find_csv(raw)
            if found is None:
                raise FileNotFoundError("sleep-export.csv missing after extract")
            csv_path = found
        sessions, events, actigraphy = _parse_export(csv_path)
        alarms_path = raw / "alarms.json"
        alarms = (
            _parse_alarms(alarms_path)
            if alarms_path.exists()
            else pd.DataFrame(columns=ALARM_COLUMNS)
        )
        conn.execute("CREATE SCHEMA IF NOT EXISTS sleep")
        conn.execute("DROP TABLE IF EXISTS sleep.alarms")
        conn.execute("DROP TABLE IF EXISTS sleep.actigraphy")
        conn.execute("DROP TABLE IF EXISTS sleep.events")
        conn.execute("DROP TABLE IF EXISTS sleep.sessions")
        conn.register("_sleep_sessions", sessions)
        conn.register("_sleep_events", events)
        conn.register("_sleep_actigraphy", actigraphy)
        conn.execute("CREATE TABLE sleep.sessions AS SELECT * FROM _sleep_sessions")
        conn.execute("CREATE TABLE sleep.events AS SELECT * FROM _sleep_events")
        conn.execute("CREATE TABLE sleep.actigraphy AS SELECT * FROM _sleep_actigraphy")
        conn.unregister("_sleep_sessions")
        conn.unregister("_sleep_events")
        conn.unregister("_sleep_actigraphy")
        conn.execute("""
            CREATE TABLE sleep.alarms (
                id INTEGER,
                hour INTEGER,
                minute INTEGER,
                enabled BOOLEAN,
                days_mask INTEGER,
                days VARCHAR,
                label VARCHAR,
                smart_window_min INTEGER,
                next_time_local TIMESTAMP
            )
        """)
        if not alarms.empty:
            conn.register("_sleep_alarms", alarms)
            conn.execute("INSERT INTO sleep.alarms BY NAME SELECT * FROM _sleep_alarms")
            conn.unregister("_sleep_alarms")

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        n = conn.execute("SELECT count(*) FROM sleep.sessions").fetchone()
        n_ev = conn.execute("SELECT count(*) FROM sleep.events").fetchone()
        n_act = conn.execute("SELECT count(*) FROM sleep.actigraphy").fetchone()
        n_alarm = conn.execute("SELECT count(*) FROM sleep.alarms").fetchone()
        span = conn.execute(
            "SELECT min(local_date), max(local_date) FROM sleep.sessions"
        ).fetchone()
        n_sessions = n[0] if n else 0
        first, last = (span[0], span[1]) if span else (None, None)
        summary = (
            f"sleep.sessions={n_sessions} events={n_ev[0] if n_ev else 0} "
            f"actigraphy={n_act[0] if n_act else 0} "
            f"alarms={n_alarm[0] if n_alarm else 0} span={first}→{last}"
        )
        return {
            "n_sessions": n_sessions,
            "n_events": n_ev[0] if n_ev else 0,
            "n_actigraphy": n_act[0] if n_act else 0,
            "n_alarms": n_alarm[0] if n_alarm else 0,
            "first_day": first,
            "last_day": last,
            "summary": summary,
        }
