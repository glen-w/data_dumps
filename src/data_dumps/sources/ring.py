"""Ring GDPR export → DuckDB.

Expects an ``All Data Categories.zip`` (or extracted folder) with
``DeviceEvents.csv`` and ``RingDeviceRegistry/Device.csv``. Address, coords,
SSID, IPs, hardware ids, and email bodies are dropped at ingest.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/London")

DEVICE_CSV = "Device.csv"
DEVICE_EVENTS_CSV = "DeviceEvents.csv"

RING_TABLES = [
    "ring.devices",
    "ring.setups",
    "ring.locations",
    "ring.device_events",
    "ring.events",
    "ring.app_events",
    "ring.subscriptions",
    "ring.accounting",
    "ring.dump_inventory",
]

_NA_TOKENS = {
    "",
    "N/A",
    "NA",
    "NONE",
    "NULL",
    "NOT APPLICABLE",
    "NOT AVAILABLE",
}


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in _NA_TOKENS


def _cell(row: dict[str, Any], *keys: str) -> str | None:
    lower = {(k or "").strip().lower(): k for k in row if k}
    for key in keys:
        raw_key = lower.get(key.lower())
        if raw_key is None:
            continue
        val = row.get(raw_key)
        if _blank(val):
            return None
        return str(val).strip()
    return None


def _parse_bool(value: Any) -> bool | None:
    if _blank(value):
        return None
    text = str(value).strip().lower()
    if text in {"yes", "true", "1", "y"}:
        return True
    if text in {"no", "false", "0", "n"}:
        return False
    return None


def _parse_dt(value: Any) -> datetime | None:
    if _blank(value):
        return None
    raw = str(value).strip()
    ts = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(raw, errors="coerce")
        if pd.isna(ts):
            return None
        py = ts.to_pydatetime()
        if py.tzinfo is None:
            # Export timestamps without offset are treated as UTC.
            py = py.replace(tzinfo=UTC)
        return py
    return ts.to_pydatetime()


def _time_dims(dt: datetime) -> dict[str, Any]:
    local = dt.astimezone(LOCAL_TZ)
    return {
        "ts_utc": dt.astimezone(UTC).replace(tzinfo=None),
        "ts_local": local.replace(tzinfo=None),
        "local_date": local.date(),
        "year": local.year,
        "weekday": local.isoweekday(),
        "hour": local.hour,
    }


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _read_csv_bytes(data: bytes) -> list[dict[str, str]]:
    text = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(text)
    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned: dict[str, str] = {}
        for k, v in row.items():
            key = (k or "").strip()
            if key == "":
                continue
            if isinstance(v, list):
                val = ",".join(str(x) for x in v if x is not None)
            elif v is None:
                val = ""
            else:
                val = str(v)
            cleaned[key] = val.strip()
        if not any(cleaned.values()):
            continue
        rows.append(cleaned)
    return rows


def _zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as zf:
        return {n.replace("\\", "/") for n in zf.namelist()}


class RingSource:
    name = "ring"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                names = _zip_names(path)
            except (OSError, zipfile.BadZipFile):
                return False
            has_events = any(
                Path(n).name.lower() == DEVICE_EVENTS_CSV.lower() for n in names
            )
            has_device = any(
                Path(n).name.lower() == DEVICE_CSV.lower()
                and "ringdeviceregistry" in n.lower().replace("\\", "/")
                for n in names
            )
            return has_events and has_device
        if not path.is_dir():
            return False
        has_events = any(
            p.name == DEVICE_EVENTS_CSV for p in path.rglob(DEVICE_EVENTS_CSV)
        )
        has_device = any(
            p.name == DEVICE_CSV and "RingDeviceRegistry" in p.parts
            for p in path.rglob(DEVICE_CSV)
        )
        return has_events and has_device

    def tables(self) -> list[str]:
        return list(RING_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        raw = raw_dir("ring")
        if raw.exists():
            shutil.rmtree(raw)
        raw.mkdir(parents=True)

        inventory_rows: list[dict[str, Any]] = []
        frames = self._build_frames(path, raw, inventory_rows)

        conn.execute("DROP SCHEMA IF EXISTS ring CASCADE")
        conn.execute("CREATE SCHEMA ring")
        self._create_tables(conn)
        for table, df in frames.items():
            tmp = f"_ring_{table}"
            conn.register(tmp, df if not df.empty else _empty(list(df.columns)))
            conn.execute(f"INSERT INTO ring.{table} BY NAME SELECT * FROM {tmp}")
            conn.unregister(tmp)

    def _create_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE ring.devices (
                device_name VARCHAR,
                device_id VARCHAR,
                created_at TIMESTAMP,
                timezone VARCHAR,
                video_storage_enabled BOOLEAN,
                show_video_enabled BOOLEAN,
                max_days_video_is_stored VARCHAR,
                rich_notifications_eligible BOOLEAN,
                people_detection_eligible BOOLEAN,
                ai_automated_warnings_enabled BOOLEAN,
                automated_siren_enabled BOOLEAN,
                continuous_video_recording_subscribed BOOLEAN,
                offline_motion_recording_subscribed BOOLEAN
            )
            """)
        conn.execute("""
            CREATE TABLE ring.setups (
                status VARCHAR,
                description VARCHAR,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                device_id VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE ring.locations (
                location_name VARCHAR,
                city VARCHAR,
                country VARCHAR,
                timezone VARCHAR,
                location_type VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE ring.device_events (
                category VARCHAR,
                message_type VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                local_date DATE,
                year BIGINT,
                weekday BIGINT,
                hour BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE ring.events (
                event_type VARCHAR,
                detection_type VARCHAR,
                duration_seconds BIGINT,
                status VARCHAR,
                human_detected VARCHAR,
                streaming_mode VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                local_date DATE,
                year BIGINT,
                weekday BIGINT,
                hour BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE ring.app_events (
                event VARCHAR,
                os VARCHAR,
                app_version VARCHAR,
                app_brand VARCHAR,
                connectivity_type VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                local_date DATE,
                year BIGINT,
                weekday BIGINT,
                hour BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE ring.subscriptions (
                plan_id VARCHAR,
                status VARCHAR,
                quantity BIGINT,
                cancel_at_period_end BOOLEAN,
                created_at TIMESTAMP,
                current_period_start TIMESTAMP,
                current_period_end TIMESTAMP,
                start_at TIMESTAMP
            )
            """)
        conn.execute("""
            CREATE TABLE ring.accounting (
                entry_type VARCHAR,
                amount DOUBLE,
                currency_code VARCHAR,
                status VARCHAR,
                invoice_number VARCHAR,
                payment_provider VARCHAR,
                description VARCHAR,
                created_at TIMESTAMP,
                period_start TIMESTAMP,
                period_end TIMESTAMP
            )
            """)
        conn.execute("""
            CREATE TABLE ring.dump_inventory (
                path VARCHAR,
                bytes BIGINT,
                row_count BIGINT,
                kind VARCHAR
            )
            """)

    def _build_frames(
        self,
        path: Path,
        raw: Path,
        inventory_rows: list[dict[str, Any]],
    ) -> dict[str, pd.DataFrame]:
        if path.is_file() and path.suffix.lower() == ".zip":
            return self._frames_from_zip(path, raw, inventory_rows)
        return self._frames_from_dir(path, raw, inventory_rows)

    def _frames_from_zip(
        self,
        path: Path,
        raw: Path,
        inventory_rows: list[dict[str, Any]],
    ) -> dict[str, pd.DataFrame]:
        with zipfile.ZipFile(path) as zf:
            names = {n.replace("\\", "/") for n in zf.namelist()}
            by_name = {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}

            def take(
                basename: str, *, prefer_registry: bool = False
            ) -> tuple[str, bytes] | None:
                matches = [n for n in names if Path(n).name.lower() == basename.lower()]
                if not matches:
                    return None
                if prefer_registry:
                    pref = [n for n in matches if "ringdeviceregistry" in n.lower()]
                    chosen = pref[0] if pref else matches[0]
                else:
                    chosen = matches[0]
                return chosen, by_name[chosen]

            frames: dict[str, pd.DataFrame] = {}

            device_blob = take(DEVICE_CSV, prefer_registry=True)
            if device_blob:
                member, data = device_blob
                (raw / "Device.csv").write_bytes(data)
                frames["devices"] = self._parse_devices(_read_csv_bytes(data))
                inventory_rows.append(
                    {
                        "path": member,
                        "bytes": len(data),
                        "row_count": len(frames["devices"]),
                        "kind": "devices",
                    }
                )
            else:
                frames["devices"] = _empty(
                    [
                        "device_name",
                        "device_id",
                        "created_at",
                        "timezone",
                        "video_storage_enabled",
                        "show_video_enabled",
                        "max_days_video_is_stored",
                        "rich_notifications_eligible",
                        "people_detection_eligible",
                        "ai_automated_warnings_enabled",
                        "automated_siren_enabled",
                        "continuous_video_recording_subscribed",
                        "offline_motion_recording_subscribed",
                    ]
                )

            loc_blob = take("Device_location.csv", prefer_registry=True)
            if loc_blob:
                member, data = loc_blob
                (raw / "Device_location.csv").write_bytes(data)
                frames["locations"] = self._parse_locations(_read_csv_bytes(data))
                inventory_rows.append(
                    {
                        "path": member,
                        "bytes": len(data),
                        "row_count": len(frames["locations"]),
                        "kind": "locations",
                    }
                )
            else:
                frames["locations"] = _empty(
                    ["location_name", "city", "country", "timezone", "location_type"]
                )

            setup_blob = take("setups.csv") or take("Device Setup.csv")
            if setup_blob:
                member, data = setup_blob
                (raw / "setups.csv").write_bytes(data)
                frames["setups"] = self._parse_setups(_read_csv_bytes(data))
                inventory_rows.append(
                    {
                        "path": member,
                        "bytes": len(data),
                        "row_count": len(frames["setups"]),
                        "kind": "setups",
                    }
                )
            else:
                frames["setups"] = _empty(
                    ["status", "description", "created_at", "updated_at", "device_id"]
                )

            de_blob = take(DEVICE_EVENTS_CSV)
            if de_blob:
                member, data = de_blob
                (raw / "DeviceEvents.csv").write_bytes(data)
                frames["device_events"] = self._parse_device_events(
                    _read_csv_bytes(data)
                )
                inventory_rows.append(
                    {
                        "path": member,
                        "bytes": len(data),
                        "row_count": len(frames["device_events"]),
                        "kind": "device_events",
                    }
                )
            else:
                frames["device_events"] = _empty(
                    [
                        "category",
                        "message_type",
                        "ts_utc",
                        "ts_local",
                        "local_date",
                        "year",
                        "weekday",
                        "hour",
                    ]
                )

            ev_blob = None
            for n in names:
                if Path(n).name.lower() == "events.csv" and "/events/" in n.lower():
                    ev_blob = (n, by_name[n])
                    break
            if ev_blob is None:
                ev_blob = take("Events.csv")
            if ev_blob:
                member, data = ev_blob
                (raw / "Events.csv").write_bytes(data)
                frames["events"] = self._parse_events(_read_csv_bytes(data))
                inventory_rows.append(
                    {
                        "path": member,
                        "bytes": len(data),
                        "row_count": len(frames["events"]),
                        "kind": "events",
                    }
                )
            else:
                frames["events"] = _empty(
                    [
                        "event_type",
                        "detection_type",
                        "duration_seconds",
                        "status",
                        "human_detected",
                        "streaming_mode",
                        "ts_utc",
                        "ts_local",
                        "local_date",
                        "year",
                        "weekday",
                        "hour",
                    ]
                )

            sub_blob = take("subscriptions.csv")
            if sub_blob:
                member, data = sub_blob
                (raw / "subscriptions.csv").write_bytes(data)
                frames["subscriptions"] = self._parse_subscriptions(
                    _read_csv_bytes(data)
                )
                inventory_rows.append(
                    {
                        "path": member,
                        "bytes": len(data),
                        "row_count": len(frames["subscriptions"]),
                        "kind": "subscriptions",
                    }
                )
            else:
                frames["subscriptions"] = _empty(
                    [
                        "plan_id",
                        "status",
                        "quantity",
                        "cancel_at_period_end",
                        "created_at",
                        "current_period_start",
                        "current_period_end",
                        "start_at",
                    ]
                )

            acct_blob = take("Accounting.json")
            if acct_blob:
                member, data = acct_blob
                (raw / "Accounting.json").write_bytes(data)
                frames["accounting"] = self._parse_accounting(data)
                inventory_rows.append(
                    {
                        "path": member,
                        "bytes": len(data),
                        "row_count": len(frames["accounting"]),
                        "kind": "accounting",
                    }
                )
            else:
                frames["accounting"] = _empty(
                    [
                        "entry_type",
                        "amount",
                        "currency_code",
                        "status",
                        "invoice_number",
                        "payment_provider",
                        "description",
                        "created_at",
                        "period_start",
                        "period_end",
                    ]
                )

            app_member = next(
                (n for n in names if Path(n).name.lower() == "app_events.zip"),
                None,
            )
            other_blob = take("other_events.csv")
            app_rows: list[dict[str, Any]] = []
            app_bytes = 0
            if app_member:
                app_bytes = len(by_name[app_member])
                app_rows.extend(self._parse_app_events_zip(by_name[app_member]))
                inventory_rows.append(
                    {
                        "path": app_member,
                        "bytes": app_bytes,
                        "row_count": len(app_rows),
                        "kind": "app_events_zip",
                    }
                )
            if other_blob:
                member, data = other_blob
                (raw / "other_events.csv").write_bytes(data)
                extra = self._parse_app_event_rows(_read_csv_bytes(data))
                app_rows.extend(extra)
                inventory_rows.append(
                    {
                        "path": member,
                        "bytes": len(data),
                        "row_count": len(extra),
                        "kind": "other_events",
                    }
                )

            app_df = (
                pd.DataFrame(app_rows)
                if app_rows
                else _empty(
                    [
                        "event",
                        "os",
                        "app_version",
                        "app_brand",
                        "connectivity_type",
                        "ts_utc",
                        "ts_local",
                        "local_date",
                        "year",
                        "weekday",
                        "hour",
                    ]
                )
            )
            frames["app_events"] = app_df
            if not app_df.empty:
                csv_path = raw / "app_events.csv"
                app_df.to_csv(csv_path, index=False)
                inventory_rows.append(
                    {
                        "path": "raw/ring/app_events.csv",
                        "bytes": csv_path.stat().st_size,
                        "row_count": len(app_df),
                        "kind": "app_events",
                    }
                )

            # Record remaining keep-list-ish metadata files as inventory only.
            for n, data in by_name.items():
                base = Path(n).name.lower()
                if base in {
                    "device.csv",
                    "device_location.csv",
                    "deviceevents.csv",
                    "events.csv",
                    "setups.csv",
                    "subscriptions.csv",
                    "accounting.json",
                    "app_events.zip",
                    "other_events.csv",
                    "device setup.csv",
                }:
                    continue
                inventory_rows.append(
                    {
                        "path": n,
                        "bytes": len(data),
                        "row_count": None,
                        "kind": "skipped",
                    }
                )

            frames["dump_inventory"] = (
                pd.DataFrame(inventory_rows)
                if inventory_rows
                else _empty(["path", "bytes", "row_count", "kind"])
            )
            return frames

    def _frames_from_dir(
        self,
        path: Path,
        raw: Path,
        inventory_rows: list[dict[str, Any]],
    ) -> dict[str, pd.DataFrame]:
        # Zip the directory into a temp in-memory walk by reusing zip path logic:
        # build a synthetic zip of relevant files is heavy; instead walk and call parsers.
        staging = raw / "_staging.zip"
        with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in path.rglob("*"):
                if not f.is_file():
                    continue
                zf.write(f, f.relative_to(path).as_posix())
        frames = self._frames_from_zip(staging, raw, inventory_rows)
        staging.unlink(missing_ok=True)
        return frames

    def _parse_devices(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        out: list[dict[str, Any]] = []
        for row in rows:
            created = _parse_dt(_cell(row, "created_at"))
            out.append(
                {
                    "device_name": _cell(row, "device_name"),
                    "device_id": _cell(row, "device_id"),
                    "created_at": (
                        created.astimezone(UTC).replace(tzinfo=None)
                        if created
                        else None
                    ),
                    "timezone": _cell(row, "timezone"),
                    "video_storage_enabled": _parse_bool(
                        _cell(row, "video_storage_enabled")
                    ),
                    "show_video_enabled": _parse_bool(_cell(row, "show_video_enabled")),
                    "max_days_video_is_stored": _cell(row, "max_days_video_is_stored"),
                    "rich_notifications_eligible": _parse_bool(
                        _cell(row, "rich_notifications_eligible")
                    ),
                    "people_detection_eligible": _parse_bool(
                        _cell(row, "people_detection_eligible")
                    ),
                    "ai_automated_warnings_enabled": _parse_bool(
                        _cell(row, "ai_automated_warnings_enabled")
                    ),
                    "automated_siren_enabled": _parse_bool(
                        _cell(row, "automated_siren_enabled")
                    ),
                    "continuous_video_recording_subscribed": _parse_bool(
                        _cell(row, "continuous_video_recording_subscribed")
                    ),
                    "offline_motion_recording_subscribed": _parse_bool(
                        _cell(row, "offline_motion_recording_subscribed")
                    ),
                }
            )
        cols = [
            "device_name",
            "device_id",
            "created_at",
            "timezone",
            "video_storage_enabled",
            "show_video_enabled",
            "max_days_video_is_stored",
            "rich_notifications_eligible",
            "people_detection_eligible",
            "ai_automated_warnings_enabled",
            "automated_siren_enabled",
            "continuous_video_recording_subscribed",
            "offline_motion_recording_subscribed",
        ]
        return pd.DataFrame(out) if out else _empty(cols)

    def _parse_locations(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "location_name": _cell(row, "location_name"),
                    "city": _cell(row, "city"),
                    "country": _cell(row, "country"),
                    "timezone": _cell(row, "timezone"),
                    "location_type": _cell(row, "location_type"),
                }
            )
        cols = ["location_name", "city", "country", "timezone", "location_type"]
        return pd.DataFrame(out) if out else _empty(cols)

    def _parse_setups(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        out: list[dict[str, Any]] = []
        for row in rows:
            created = _parse_dt(_cell(row, "Created At", "created_at"))
            updated = _parse_dt(_cell(row, "Updated At", "updated_at"))
            out.append(
                {
                    "status": _cell(row, "Status", "status"),
                    "description": _cell(row, "Description", "description"),
                    "created_at": (
                        created.astimezone(UTC).replace(tzinfo=None)
                        if created
                        else None
                    ),
                    "updated_at": (
                        updated.astimezone(UTC).replace(tzinfo=None)
                        if updated
                        else None
                    ),
                    "device_id": _cell(row, "Device Id", "device_id"),
                }
            )
        cols = ["status", "description", "created_at", "updated_at", "device_id"]
        return pd.DataFrame(out) if out else _empty(cols)

    def _parse_device_events(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        out: list[dict[str, Any]] = []
        for row in rows:
            dt = _parse_dt(_cell(row, "Event Date", "event_date"))
            if dt is None:
                continue
            dims = _time_dims(dt)
            out.append(
                {
                    "category": _cell(row, "Category", "category"),
                    "message_type": _cell(row, "Message Type", "message_type"),
                    **dims,
                }
            )
        cols = [
            "category",
            "message_type",
            "ts_utc",
            "ts_local",
            "local_date",
            "year",
            "weekday",
            "hour",
        ]
        return pd.DataFrame(out) if out else _empty(cols)

    def _parse_events(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        out: list[dict[str, Any]] = []
        for row in rows:
            dt = _parse_dt(_cell(row, "Event Date", "event_date"))
            if dt is None:
                continue
            dur_raw = _cell(row, "Duration Seconds", "duration_seconds")
            duration: int | None = None
            if dur_raw is not None:
                try:
                    duration = int(float(dur_raw))
                except ValueError:
                    duration = None
            dims = _time_dims(dt)
            out.append(
                {
                    "event_type": _cell(row, "Event Type", "event_type"),
                    "detection_type": _cell(row, "Detection Type", "detection_type"),
                    "duration_seconds": duration,
                    "status": _cell(row, "Status", "status"),
                    "human_detected": _cell(row, "Human Detected", "human_detected"),
                    "streaming_mode": _cell(row, "Streaming Mode", "streaming_mode"),
                    **dims,
                }
            )
        cols = [
            "event_type",
            "detection_type",
            "duration_seconds",
            "status",
            "human_detected",
            "streaming_mode",
            "ts_utc",
            "ts_local",
            "local_date",
            "year",
            "weekday",
            "hour",
        ]
        return pd.DataFrame(out) if out else _empty(cols)

    def _parse_subscriptions(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        out: list[dict[str, Any]] = []
        for row in rows:
            created = _parse_dt(_cell(row, "Created", "created"))
            cps = _parse_dt(_cell(row, "Current Period Start", "current_period_start"))
            cpe = _parse_dt(_cell(row, "Current Period End", "current_period_end"))
            start = _parse_dt(_cell(row, "Start", "start"))
            qty_raw = _cell(row, "Quantity", "quantity")
            qty: int | None = None
            if qty_raw is not None:
                try:
                    qty = int(float(qty_raw))
                except ValueError:
                    qty = None
            cancel = _parse_bool(
                _cell(row, "Cancel At Period End", "cancel_at_period_end")
            )
            out.append(
                {
                    "plan_id": _cell(row, "Plan Id", "plan_id"),
                    "status": _cell(row, "Status", "status"),
                    "quantity": qty,
                    "cancel_at_period_end": cancel,
                    "created_at": (
                        created.astimezone(UTC).replace(tzinfo=None)
                        if created
                        else None
                    ),
                    "current_period_start": (
                        cps.astimezone(UTC).replace(tzinfo=None) if cps else None
                    ),
                    "current_period_end": (
                        cpe.astimezone(UTC).replace(tzinfo=None) if cpe else None
                    ),
                    "start_at": (
                        start.astimezone(UTC).replace(tzinfo=None) if start else None
                    ),
                }
            )
        cols = [
            "plan_id",
            "status",
            "quantity",
            "cancel_at_period_end",
            "created_at",
            "current_period_start",
            "current_period_end",
            "start_at",
        ]
        return pd.DataFrame(out) if out else _empty(cols)

    def _parse_accounting(self, data: bytes) -> pd.DataFrame:
        cols = [
            "entry_type",
            "amount",
            "currency_code",
            "status",
            "invoice_number",
            "payment_provider",
            "description",
            "created_at",
            "period_start",
            "period_end",
        ]
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _empty(cols)
        items = (
            payload.get("customerAccountingDataList")
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(items, list):
            return _empty(cols)
        out: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            created = _parse_dt(item.get("Creation Date"))
            ps = _parse_dt(item.get("Period Start Date"))
            pe = _parse_dt(item.get("Period End Date"))
            amount_raw = item.get("Amount")
            amount: float | None
            try:
                amount = float(amount_raw) if amount_raw is not None else None
            except (TypeError, ValueError):
                amount = None
            out.append(
                {
                    "entry_type": (
                        None if _blank(item.get("Type")) else str(item.get("Type"))
                    ),
                    "amount": amount,
                    "currency_code": (
                        None
                        if _blank(item.get("Currency Code"))
                        else str(item.get("Currency Code"))
                    ),
                    "status": (
                        None if _blank(item.get("Status")) else str(item.get("Status"))
                    ),
                    "invoice_number": (
                        None
                        if _blank(item.get("Invoice Number"))
                        else str(item.get("Invoice Number"))
                    ),
                    "payment_provider": (
                        None
                        if _blank(item.get("Payment Provider"))
                        else str(item.get("Payment Provider"))
                    ),
                    "description": (
                        None
                        if _blank(item.get("Description"))
                        else str(item.get("Description"))
                    ),
                    "created_at": (
                        created.astimezone(UTC).replace(tzinfo=None)
                        if created
                        else None
                    ),
                    "period_start": (
                        ps.astimezone(UTC).replace(tzinfo=None) if ps else None
                    ),
                    "period_end": (
                        pe.astimezone(UTC).replace(tzinfo=None) if pe else None
                    ),
                }
            )
        return pd.DataFrame(out) if out else _empty(cols)

    def _parse_app_events_zip(self, data: bytes) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                rows.extend(self._parse_app_event_rows(_read_csv_bytes(zf.read(name))))
        return rows

    def _parse_app_event_rows(self, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            dt = _parse_dt(_cell(row, "Timestamp", "timestamp"))
            if dt is None:
                continue
            props_raw = _cell(row, "Properties", "properties") or "{}"
            try:
                props = json.loads(props_raw)
            except json.JSONDecodeError:
                props = {}
            if not isinstance(props, dict):
                props = {}
            dims = _time_dims(dt)
            out.append(
                {
                    "event": _cell(row, "Event", "event"),
                    "os": None if _blank(props.get("OS")) else str(props.get("OS")),
                    "app_version": (
                        None
                        if _blank(props.get("App Version"))
                        else str(props.get("App Version"))
                    ),
                    "app_brand": (
                        None
                        if _blank(props.get("App Brand"))
                        else str(props.get("App Brand"))
                    ),
                    "connectivity_type": (
                        None
                        if _blank(props.get("Connectivity Type"))
                        else str(props.get("Connectivity Type"))
                    ),
                    **dims,
                }
            )
        return out

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        n_devices = conn.execute("SELECT count(*) FROM ring.devices").fetchone()
        n_de = conn.execute("SELECT count(*) FROM ring.device_events").fetchone()
        n_ev = conn.execute("SELECT count(*) FROM ring.events").fetchone()
        n_app = conn.execute("SELECT count(*) FROM ring.app_events").fetchone()
        span = conn.execute("""
            SELECT min(d), max(d) FROM (
                SELECT local_date AS d FROM ring.device_events
                UNION ALL
                SELECT local_date FROM ring.events
                UNION ALL
                SELECT local_date FROM ring.app_events
            )
            """).fetchone()
        footprint = conn.execute(
            "SELECT coalesce(sum(bytes), 0) FROM ring.dump_inventory"
        ).fetchone()
        nd = n_devices[0] if n_devices else 0
        nde = n_de[0] if n_de else 0
        nev = n_ev[0] if n_ev else 0
        napp = n_app[0] if n_app else 0
        first = span[0] if span else None
        last = span[1] if span else None
        bytes_total = footprint[0] if footprint else 0
        summary = (
            f"ring devices={nd} device_events={nde} motion={nev} "
            f"app_events={napp} span={first}→{last} footprint_bytes={bytes_total}"
        )
        return {
            "n_devices": nd,
            "n_device_events": nde,
            "n_events": nev,
            "n_app_events": napp,
            "first_day": first,
            "last_day": last,
            "footprint_bytes": bytes_total,
            "summary": summary,
        }
