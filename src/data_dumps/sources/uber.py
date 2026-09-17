"""Uber GDPR export → DuckDB.

Keep-list: rider lifetime trips (no coords / address strings / card numbers),
Eats order line items (no special instructions), ratings received, and support
ticket messages. Dropped: profile (email/phone/name/signup coords), payment
methods, saved locations, and rider/eats app analytics (IPs, device ids, GPS).
"""

from __future__ import annotations

import csv
import hashlib
import io
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Rome")

TRIPS_BASENAME = "rider_lifetime_trips-0.csv"
RATINGS_BASENAME = "rider_lifetime_ratings_received-0.csv"
ORDERS_BASENAME = "user_orders-0.csv"
SUPPORT_BASENAME = "customer_support_tickets-0.csv"

KEEP_CSV_BASENAMES = {
    TRIPS_BASENAME,
    RATINGS_BASENAME,
    ORDERS_BASENAME,
    SUPPORT_BASENAME,
}

UBER_TABLES = [
    "uber.trips",
    "uber.order_items",
    "uber.ratings",
    "uber.support_messages",
]

# Export columns we never persist (even if present on a keep-list CSV).
TRIP_DROP_COLUMNS = {
    "request_lat",
    "request_lng",
    "begintrip_lat",
    "begintrip_lng",
    "dropoff_lat",
    "dropoff_lng",
    "destination_lat",
    "destination_lng",
    "begintrip_string",
    "destination_string",
    "card_number",
}

ORDER_DROP_COLUMNS = {
    "special_instructions",
}


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {"N/A", "NA", "NONE", "NULL", "/"}


def _cell(row: dict[str, Any], *names: str) -> str | None:
    lower = {(k or "").strip().lower(): k for k in row if k}
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
    raw = str(value).strip()
    ts = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(raw, errors="coerce")
        if pd.isna(ts):
            return None
        py = ts.to_pydatetime()
        if py.tzinfo is None:
            py = py.replace(tzinfo=UTC)
        return py.astimezone(UTC)
    return ts.to_pydatetime().astimezone(UTC)


def _parse_local_naive(value: Any) -> datetime | None:
    """Parse export *_local timestamps as naive wall-clock (no TZ convert)."""
    if _blank(value):
        return None
    raw = str(value).strip()
    # Many Uber "local" stamps are ISO with Z but already shifted to city TZ.
    if raw.endswith("Z") or "+" in raw[10:]:
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime().replace(tzinfo=None)
    ts = pd.to_datetime(raw, errors="coerce")
    if pd.isna(ts):
        return None
    py = ts.to_pydatetime()
    return py.replace(tzinfo=None) if py.tzinfo is None else py.replace(tzinfo=None)


def _ts_pair_from_utc(value: Any) -> tuple[datetime | None, datetime | None]:
    ts = _parse_datetime(value)
    if ts is None:
        return None, None
    utc_naive = ts.astimezone(UTC).replace(tzinfo=None)
    local_naive = ts.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return utc_naive, local_naive


def _year_month_hour(
    local_naive: datetime | None, utc_naive: datetime | None = None
) -> tuple[int | None, int | None, int | None, int | None]:
    src = local_naive or utc_naive
    if src is None:
        return None, None, None, None
    return src.year, src.month, src.isoweekday(), src.hour


def _to_int(value: Any) -> int | None:
    if _blank(value):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if _blank(value):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _to_bool(value: Any) -> bool | None:
    if _blank(value):
        return None
    raw = str(value).strip().lower()
    if raw in {"true", "1", "yes", "y"}:
        return True
    if raw in {"false", "0", "no", "n"}:
        return False
    return None


def _money(row: dict[str, Any], *names: str) -> float | None:
    return _to_float(_cell(row, *names))


def _trip_id(row: dict[str, Any]) -> str:
    parts = [
        _cell(row, "request_timestamp_utc") or "",
        _cell(row, "begintrip_timestamp_utc") or "",
        _cell(row, "dropoff_timestamp_utc") or "",
        _cell(row, "city_name") or "",
        _cell(row, "product_type_name") or "",
        _cell(row, "status") or "",
        _cell(row, "trip_distance_miles") or "",
        _cell(row, "original_fare_usd") or "",
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _order_key(row: dict[str, Any]) -> str:
    parts = [
        _cell(row, "City_Name", "city_name") or "",
        _cell(row, "Restaurant_Name", "restaurant_name") or "",
        _cell(row, "Request_Time_Local", "request_time_local") or "",
        _cell(row, "Order_Price", "order_price") or "",
        _cell(row, "Currency", "currency") or "",
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _item_id(row: dict[str, Any], order_key: str) -> str:
    parts = [
        order_key,
        _cell(row, "Item_Name", "item_name") or "",
        _cell(row, "Item_quantity", "item_quantity") or "",
        _cell(row, "Item_Price", "item_price") or "",
        _cell(row, "Customizations", "customizations") or "",
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _read_csv_records(data: bytes | Path) -> list[dict[str, str]]:
    if isinstance(data, Path):
        raw = data.read_bytes()
    else:
        raw = data
    text = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(text)
    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned: dict[str, str] = {}
        for k, v in row.items():
            key = (k or "").strip()
            if key == "":
                continue
            cleaned[key] = "" if v is None else str(v).strip()
        if not any(cleaned.values()):
            continue
        rows.append(cleaned)
    return rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _zip_basenames(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as zf:
        return {Path(n).name.lower() for n in zf.namelist() if not n.endswith("/")}


def _iter_csv_members(
    path: Path,
) -> list[tuple[str, bytes]]:
    """Return (basename_lower, bytes) for keep-list CSVs from zip or folder."""
    path = path.resolve()
    out: list[tuple[str, bytes]] = []
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith("/") or not name.lower().endswith(".csv"):
                    continue
                base = Path(name).name.lower()
                if base not in KEEP_CSV_BASENAMES:
                    continue
                out.append((base, zf.read(name)))
        return out

    root = _export_root(path)
    if root is None:
        return out
    for f in root.rglob("*.csv"):
        base = f.name.lower()
        if base not in KEEP_CSV_BASENAMES:
            continue
        out.append((base, f.read_bytes()))
    return out


def _export_root(path: Path) -> Path | None:
    if not path.is_dir():
        return None
    # Direct export: …/Uber Data/Rider/…
    if (path / "Rider").is_dir() or (path / "Eats").is_dir():
        return path
    nested = path / "Uber Data"
    if nested.is_dir():
        return nested
    # Folder containing the zip-extracted top folder
    for child in path.iterdir():
        if child.is_dir() and (
            (child / "Rider").is_dir() or (child / "Uber Data").is_dir()
        ):
            if (child / "Rider").is_dir():
                return child
            return child / "Uber Data"
    # Any recursive presence of the trips CSV
    hits = list(path.rglob(TRIPS_BASENAME))
    if len(hits) == 1:
        # …/Rider/file → export root is parent of Rider
        rider = hits[0].parent
        return rider.parent if rider.name.lower() == "rider" else rider
    return None


class UberSource:
    name = "uber"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                bases = _zip_basenames(path)
            except (OSError, zipfile.BadZipFile):
                return False
            return TRIPS_BASENAME in bases
        return _export_root(path) is not None and any(
            p.name.lower() == TRIPS_BASENAME for p in path.rglob("*.csv")
        )

    def tables(self) -> list[str]:
        return list(UBER_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        members = {base: data for base, data in _iter_csv_members(path)}
        if TRIPS_BASENAME not in members:
            raise FileNotFoundError(f"No {TRIPS_BASENAME} in {path}")

        dest = raw_dir("uber")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        trip_rows_raw = _read_csv_records(members[TRIPS_BASENAME])
        order_rows_raw = _read_csv_records(members.get(ORDERS_BASENAME, b""))
        rating_rows_raw = _read_csv_records(members.get(RATINGS_BASENAME, b""))
        support_rows_raw = _read_csv_records(members.get(SUPPORT_BASENAME, b""))

        trips_df = self._trips_frame(trip_rows_raw)
        orders_df = self._order_items_frame(order_rows_raw)
        ratings_df = self._ratings_frame(rating_rows_raw)
        support_df = self._support_frame(support_rows_raw)

        self._write_scrubbed_raw(
            dest,
            trip_rows_raw,
            order_rows_raw,
            rating_rows_raw,
            support_rows_raw,
        )

        frames = {
            "trips": trips_df,
            "order_items": orders_df,
            "ratings": ratings_df,
            "support_messages": support_df,
        }
        conn.execute("DROP SCHEMA IF EXISTS uber CASCADE")
        conn.execute("CREATE SCHEMA uber")
        self._create_tables(conn)
        for table, df in frames.items():
            tmp = f"_uber_{table}"
            conn.register(tmp, df if not df.empty else _empty(list(df.columns)))
            conn.execute(f"INSERT INTO uber.{table} BY NAME SELECT * FROM {tmp}")
            conn.unregister(tmp)

    def _write_scrubbed_raw(
        self,
        dest: Path,
        trips: list[dict[str, str]],
        orders: list[dict[str, str]],
        ratings: list[dict[str, str]],
        support: list[dict[str, str]],
    ) -> None:
        if trips:
            fields = [k for k in trips[0] if k.strip().lower() not in TRIP_DROP_COLUMNS]
            scrubbed = [
                {
                    k: r.get(k, "")
                    for k in fields
                    if k.strip().lower() not in TRIP_DROP_COLUMNS
                }
                for r in trips
            ]
            _write_csv(dest / TRIPS_BASENAME, fields, scrubbed)
        if orders:
            fields = [
                k for k in orders[0] if k.strip().lower() not in ORDER_DROP_COLUMNS
            ]
            scrubbed = [{k: r.get(k, "") for k in fields} for r in orders]
            _write_csv(dest / ORDERS_BASENAME, fields, scrubbed)
        if ratings:
            fields = list(ratings[0].keys())
            _write_csv(dest / RATINGS_BASENAME, fields, ratings)
        if support:
            fields = list(support[0].keys())
            _write_csv(dest / SUPPORT_BASENAME, fields, support)

    def _create_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE uber.trips (
                trip_id VARCHAR PRIMARY KEY,
                city_name VARCHAR,
                product_type VARCHAR,
                global_product VARCHAR,
                trip_timezone VARCHAR,
                currency_code VARCHAR,
                status VARCHAR,
                is_completed BOOLEAN,
                is_surged BOOLEAN,
                is_airport_trip BOOLEAN,
                is_scheduled_trip BOOLEAN,
                is_cash_trip BOOLEAN,
                request_ts_utc TIMESTAMP,
                request_ts_local TIMESTAMP,
                begin_ts_utc TIMESTAMP,
                begin_ts_local TIMESTAMP,
                dropoff_ts_utc TIMESTAMP,
                dropoff_ts_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                weekday INTEGER,
                hour INTEGER,
                eta_seconds DOUBLE,
                surge_multiplier DOUBLE,
                wait_to_begin_seconds DOUBLE,
                trip_distance_miles DOUBLE,
                trip_duration_seconds DOUBLE,
                fare_local DOUBLE,
                fare_usd DOUBLE,
                tip_local DOUBLE,
                tip_currency VARCHAR,
                credits_local DOUBLE,
                credits_usd DOUBLE,
                promotion_local DOUBLE,
                promotion_usd DOUBLE,
                payment_type VARCHAR,
                client_device VARCHAR,
                client_app_version VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE uber.order_items (
                item_id VARCHAR PRIMARY KEY,
                order_key VARCHAR,
                city_name VARCHAR,
                restaurant_name VARCHAR,
                order_status VARCHAR,
                item_name VARCHAR,
                item_quantity INTEGER,
                customizations VARCHAR,
                customization_cost_local DOUBLE,
                item_price_local DOUBLE,
                order_price_local DOUBLE,
                currency VARCHAR,
                request_ts_utc TIMESTAMP,
                request_ts_local TIMESTAMP,
                delivery_ts_utc TIMESTAMP,
                delivery_ts_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                weekday INTEGER,
                hour INTEGER
            )
            """)
        conn.execute("""
            CREATE TABLE uber.ratings (
                rating_id INTEGER PRIMARY KEY,
                stars INTEGER
            )
            """)
        conn.execute("""
            CREATE TABLE uber.support_messages (
                message_id INTEGER PRIMARY KEY,
                creator VARCHAR,
                body VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                weekday INTEGER,
                hour INTEGER
            )
            """)

    def _trips_frame(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        cols = [
            "trip_id",
            "city_name",
            "product_type",
            "global_product",
            "trip_timezone",
            "currency_code",
            "status",
            "is_completed",
            "is_surged",
            "is_airport_trip",
            "is_scheduled_trip",
            "is_cash_trip",
            "request_ts_utc",
            "request_ts_local",
            "begin_ts_utc",
            "begin_ts_local",
            "dropoff_ts_utc",
            "dropoff_ts_local",
            "year",
            "month",
            "weekday",
            "hour",
            "eta_seconds",
            "surge_multiplier",
            "wait_to_begin_seconds",
            "trip_distance_miles",
            "trip_duration_seconds",
            "fare_local",
            "fare_usd",
            "tip_local",
            "tip_currency",
            "credits_local",
            "credits_usd",
            "promotion_local",
            "promotion_usd",
            "payment_type",
            "client_device",
            "client_app_version",
        ]
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            tid = _trip_id(row)
            if tid in seen:
                # Extremely rare collision / duplicate row — suffix.
                tid = hashlib.sha1((tid + "|" + str(len(out))).encode()).hexdigest()[
                    :16
                ]
            seen.add(tid)

            req_utc, req_local_fallback = _ts_pair_from_utc(
                _cell(row, "request_timestamp_utc")
            )
            req_local = (
                _parse_local_naive(_cell(row, "request_timestamp_local"))
                or req_local_fallback
            )
            begin_utc, begin_local_fb = _ts_pair_from_utc(
                _cell(row, "begintrip_timestamp_utc")
            )
            begin_local = (
                _parse_local_naive(_cell(row, "begintrip_timestamp_local"))
                or begin_local_fb
            )
            drop_utc, drop_local_fb = _ts_pair_from_utc(
                _cell(row, "dropoff_timestamp_utc")
            )
            drop_local = (
                _parse_local_naive(_cell(row, "dropoff_timestamp_local"))
                or drop_local_fb
            )
            year, month, weekday, hour = _year_month_hour(req_local, req_utc)

            fare_local = _money(
                row,
                "original_fare_local",
                "client_upfront_fare_local",
                "base_fare_local",
            )
            fare_usd = _money(
                row,
                "original_fare_usd",
                "client_upfront_fare_usd",
                "base_fare_usd",
            )

            out.append(
                {
                    "trip_id": tid,
                    "city_name": _cell(row, "city_name"),
                    "product_type": _cell(row, "product_type_name"),
                    "global_product": _cell(row, "global_product_name"),
                    "trip_timezone": _cell(row, "timezone"),
                    "currency_code": _cell(row, "currency_code"),
                    "status": _cell(row, "status"),
                    "is_completed": _to_bool(_cell(row, "is_completed")),
                    "is_surged": _to_bool(_cell(row, "is_surged")),
                    "is_airport_trip": _to_bool(_cell(row, "is_airport_trip")),
                    "is_scheduled_trip": _to_bool(_cell(row, "is_scheduled_trip")),
                    "is_cash_trip": _to_bool(_cell(row, "is_cash_trip")),
                    "request_ts_utc": req_utc,
                    "request_ts_local": req_local,
                    "begin_ts_utc": begin_utc,
                    "begin_ts_local": begin_local,
                    "dropoff_ts_utc": drop_utc,
                    "dropoff_ts_local": drop_local,
                    "year": year,
                    "month": month,
                    "weekday": weekday,
                    "hour": hour,
                    "eta_seconds": _to_float(_cell(row, "eta")),
                    "surge_multiplier": _to_float(_cell(row, "surge_multiplier")),
                    "wait_to_begin_seconds": _to_float(
                        _cell(row, "request_to_begin_duration_seconds")
                    ),
                    "trip_distance_miles": _to_float(_cell(row, "trip_distance_miles")),
                    "trip_duration_seconds": _to_float(
                        _cell(row, "trip_duration_seconds")
                    ),
                    "fare_local": fare_local,
                    "fare_usd": fare_usd,
                    "tip_local": _money(row, "tip_amount_local_currency"),
                    "tip_currency": _cell(row, "tip_currency_code"),
                    "credits_local": _money(row, "credits_local"),
                    "credits_usd": _money(row, "credits_usd"),
                    "promotion_local": _money(row, "promotion_local"),
                    "promotion_usd": _money(row, "promotion_usd"),
                    "payment_type": _cell(row, "payment_type"),
                    "client_device": _cell(row, "client_device"),
                    "client_app_version": _cell(row, "client_app_version"),
                }
            )
        return pd.DataFrame(out, columns=cols) if out else _empty(cols)

    def _order_items_frame(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        cols = [
            "item_id",
            "order_key",
            "city_name",
            "restaurant_name",
            "order_status",
            "item_name",
            "item_quantity",
            "customizations",
            "customization_cost_local",
            "item_price_local",
            "order_price_local",
            "currency",
            "request_ts_utc",
            "request_ts_local",
            "delivery_ts_utc",
            "delivery_ts_local",
            "year",
            "month",
            "weekday",
            "hour",
        ]
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            okey = _order_key(row)
            iid = _item_id(row, okey)
            if iid in seen:
                iid = hashlib.sha1((iid + "|" + str(len(out))).encode()).hexdigest()[
                    :16
                ]
            seen.add(iid)

            req_raw = _cell(row, "Request_Time_Local", "request_time_local")
            # Export stamps are UTC ISO even when named Local.
            req_utc, req_local_fb = _ts_pair_from_utc(req_raw)
            req_local = _parse_local_naive(req_raw) or req_local_fb
            del_raw = _cell(
                row, "Final_Delivery_Time_Local", "final_delivery_time_local"
            )
            del_utc, del_local_fb = _ts_pair_from_utc(del_raw)
            del_local = _parse_local_naive(del_raw) or del_local_fb
            year, month, weekday, hour = _year_month_hour(req_local, req_utc)

            out.append(
                {
                    "item_id": iid,
                    "order_key": okey,
                    "city_name": _cell(row, "City_Name", "city_name"),
                    "restaurant_name": _cell(row, "Restaurant_Name", "restaurant_name"),
                    "order_status": _cell(row, "Order_Status", "order_status"),
                    "item_name": _cell(row, "Item_Name", "item_name"),
                    "item_quantity": _to_int(
                        _cell(row, "Item_quantity", "item_quantity")
                    ),
                    "customizations": _cell(row, "Customizations", "customizations"),
                    "customization_cost_local": _to_float(
                        _cell(
                            row,
                            "Customization_Cost_Local",
                            "customization_cost_local",
                        )
                    ),
                    "item_price_local": _to_float(
                        _cell(row, "Item_Price", "item_price")
                    ),
                    "order_price_local": _to_float(
                        _cell(row, "Order_Price", "order_price")
                    ),
                    "currency": _cell(row, "Currency", "currency"),
                    "request_ts_utc": req_utc,
                    "request_ts_local": req_local,
                    "delivery_ts_utc": del_utc,
                    "delivery_ts_local": del_local,
                    "year": year,
                    "month": month,
                    "weekday": weekday,
                    "hour": hour,
                }
            )
        return pd.DataFrame(out, columns=cols) if out else _empty(cols)

    def _ratings_frame(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        cols = ["rating_id", "stars"]
        out: list[dict[str, Any]] = []
        for i, row in enumerate(rows, start=1):
            stars = _to_int(_cell(row, "five_star_rating", "stars", "rating"))
            if stars is None:
                continue
            out.append({"rating_id": i, "stars": stars})
        return pd.DataFrame(out, columns=cols) if out else _empty(cols)

    def _support_frame(self, rows: list[dict[str, str]]) -> pd.DataFrame:
        cols = [
            "message_id",
            "creator",
            "body",
            "ts_utc",
            "ts_local",
            "year",
            "month",
            "weekday",
            "hour",
        ]
        out: list[dict[str, Any]] = []
        for i, row in enumerate(rows, start=1):
            ts_utc, ts_local = _ts_pair_from_utc(_cell(row, "Date", "date"))
            year, month, weekday, hour = _year_month_hour(ts_local, ts_utc)
            out.append(
                {
                    "message_id": i,
                    "creator": _cell(row, "Creator", "creator"),
                    "body": _cell(row, "Message", "message", "body"),
                    "ts_utc": ts_utc,
                    "ts_local": ts_local,
                    "year": year,
                    "month": month,
                    "weekday": weekday,
                    "hour": hour,
                }
            )
        return pd.DataFrame(out, columns=cols) if out else _empty(cols)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        def _scalar(sql: str) -> Any:
            row = conn.execute(sql).fetchone()
            assert row is not None
            return row[0]

        n_trips = _scalar("SELECT count(*) FROM uber.trips")
        n_completed = _scalar(
            "SELECT count(*) FROM uber.trips WHERE coalesce(is_completed, false)"
        )
        n_orders = _scalar("SELECT count(DISTINCT order_key) FROM uber.order_items")
        n_items = _scalar("SELECT count(*) FROM uber.order_items")
        n_ratings = _scalar("SELECT count(*) FROM uber.ratings")
        n_support = _scalar("SELECT count(*) FROM uber.support_messages")
        span = conn.execute("""
            SELECT min(d), max(d) FROM (
                SELECT cast(request_ts_local AS DATE) AS d FROM uber.trips
                WHERE request_ts_local IS NOT NULL
                UNION ALL
                SELECT cast(request_ts_local AS DATE) FROM uber.order_items
                WHERE request_ts_local IS NOT NULL
            )
            """).fetchone()
        first_day, last_day = (span[0], span[1]) if span else (None, None)
        cities = _scalar(
            "SELECT count(DISTINCT city_name) FROM uber.trips WHERE city_name IS NOT NULL"
        )
        summary = (
            f"uber: {n_trips} trips ({n_completed} completed), "
            f"{n_orders} eats orders / {n_items} items, "
            f"{n_ratings} ratings, {n_support} support msgs, "
            f"{cities} cities, {first_day} → {last_day}"
        )
        return {
            "n_trips": int(n_trips),
            "n_completed": int(n_completed),
            "n_orders": int(n_orders),
            "n_order_items": int(n_items),
            "n_ratings": int(n_ratings),
            "n_support": int(n_support),
            "n_cities": int(cities),
            "first_day": first_day,
            "last_day": last_day,
            "summary": summary,
        }
