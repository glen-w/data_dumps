"""Xiaomi Mi Band / Mi Fit heart-rate CSV → DuckDB (one-off).

Expects heart_rate.csv (or any CSV) with columns dateTime,rate,rateZone.
"""

from __future__ import annotations

import csv
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Rome")

MIBAND_TABLES = ["miband.heart_rate"]


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {"N/A", "NA", "NONE", "NULL"}


def _parse_dt(value: str) -> datetime | None:
    if _blank(value):
        return None
    raw = str(value).strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(raw, fmt)
            # Mi Fit exports are local wall time; treat as Europe/Rome historically
            aware = naive.replace(tzinfo=LOCAL_TZ)
            return aware
        except ValueError:
            continue
    ts = pd.to_datetime(raw, dayfirst=True, errors="coerce")
    if pd.isna(ts):
        return None
    py = ts.to_pydatetime()
    if py.tzinfo is None:
        py = py.replace(tzinfo=LOCAL_TZ)
    return py


def _find_csv(path: Path) -> Path | None:
    if path.is_file() and path.suffix.lower() == ".csv":
        return path
    if path.is_dir():
        preferred = path / "heart_rate.csv"
        if preferred.exists():
            return preferred
        for cand in path.glob("*.csv"):
            return cand
    return None


def _looks_like_hr_csv(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except OSError:
        return False
    if not header:
        return False
    cols = {c.strip() for c in header}
    return "dateTime" in cols and "rate" in cols


class MiBandSource:
    name = "miband"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        csv_path = _find_csv(path) if path.is_dir() else (path if path.is_file() else None)
        if csv_path is None:
            return False
        if csv_path.name == "heart_rate.csv":
            return True
        return _looks_like_hr_csv(csv_path)

    def tables(self) -> list[str]:
        return list(MIBAND_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        csv_path = _find_csv(path) if path.is_dir() else path
        if csv_path is None or not csv_path.is_file():
            raise FileNotFoundError(f"no heart_rate CSV at {path}")

        dest = raw_dir("miband")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        shutil.copy2(csv_path, dest / "heart_rate.csv")

        rows: list[dict[str, Any]] = []
        with csv_path.open(encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt = _parse_dt(row.get("dateTime") or "")
                if dt is None:
                    continue
                rate_raw = row.get("rate")
                if _blank(rate_raw):
                    continue
                try:
                    rate = int(float(str(rate_raw).strip()))
                except ValueError:
                    continue
                zone = (row.get("rateZone") or "").strip() or None
                rows.append(
                    {
                        "ts_utc": dt.astimezone(UTC).replace(tzinfo=None),
                        "ts_local": dt.astimezone(LOCAL_TZ).replace(tzinfo=None),
                        "rate": rate,
                        "rate_zone": zone,
                        "local_date": dt.astimezone(LOCAL_TZ).date(),
                        "year": dt.astimezone(LOCAL_TZ).year,
                        "weekday": dt.astimezone(LOCAL_TZ).isoweekday(),
                        "hour": dt.astimezone(LOCAL_TZ).hour,
                    }
                )
        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame(
                columns=[
                    "ts_utc",
                    "ts_local",
                    "rate",
                    "rate_zone",
                    "local_date",
                    "year",
                    "weekday",
                    "hour",
                ]
            )
        # Deduplicate on ts_utc keeping last
        if not df.empty:
            df = df.drop_duplicates(subset=["ts_utc"], keep="last")

        conn.execute("CREATE SCHEMA IF NOT EXISTS miband")
        conn.execute("DROP TABLE IF EXISTS miband.heart_rate")
        conn.register("_miband_hr", df)
        conn.execute("CREATE TABLE miband.heart_rate AS SELECT * FROM _miband_hr")
        conn.unregister("_miband_hr")

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        n = conn.execute("SELECT count(*) FROM miband.heart_rate").fetchone()
        span = conn.execute(
            "SELECT min(local_date), max(local_date), avg(rate), min(rate), max(rate) "
            "FROM miband.heart_rate"
        ).fetchone()
        n_rows = n[0] if n else 0
        first = span[0] if span else None
        last = span[1] if span else None
        avg_r = span[2] if span else None
        summary = (
            f"miband.heart_rate={n_rows} span={first}→{last} "
            f"avg={avg_r:.1f}" if avg_r is not None else f"miband.heart_rate={n_rows}"
        )
        return {
            "n_readings": n_rows,
            "first_day": first,
            "last_day": last,
            "avg_rate": avg_r,
            "summary": summary,
        }
