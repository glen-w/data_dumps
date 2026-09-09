"""Filter state and DuckDB queries for the Mi Band HR explorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        return chips


def _where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    p = f"{alias}." if alias else ""
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(local_date)::DATE, max(local_date)::DATE
        FROM miband.heart_rate
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2018, 2019
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    return FilterState(year_start=ys, year_end=ye)


def scoreboard(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS readings,
            round(avg(rate), 1) AS avg_bpm,
            min(rate)::INT AS min_bpm,
            max(rate)::INT AS max_bpm,
            count(DISTINCT local_date)::BIGINT AS days
        FROM miband.heart_rate h
        WHERE {where}
        """,
        params,
    )


def daily_avg(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        SELECT
            local_date AS day,
            round(avg(rate), 1) AS avg_bpm,
            min(rate)::INT AS min_bpm,
            max(rate)::INT AS max_bpm,
            count(*)::BIGINT AS readings
        FROM miband.heart_rate h
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def hour_of_day(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        SELECT hour, round(avg(rate), 1) AS avg_bpm, count(*)::BIGINT AS readings
        FROM miband.heart_rate h
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def weekday_hour_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        SELECT weekday AS dow, hour, round(avg(rate), 1) AS avg_bpm
        FROM miband.heart_rate h
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def zone_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(rate_zone, '(none)') AS rate_zone,
            count(*)::BIGINT AS readings
        FROM miband.heart_rate h
        WHERE {where}
        GROUP BY 1
        ORDER BY readings DESC
        """,
        params,
    )


def extremes(conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 15) -> pd.DataFrame:
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        (
            SELECT ts_local, rate, rate_zone, 'high' AS kind
            FROM miband.heart_rate h
            WHERE {where}
            ORDER BY rate DESC
            LIMIT {limit}
        )
        UNION ALL
        (
            SELECT ts_local, rate, rate_zone, 'low' AS kind
            FROM miband.heart_rate h
            WHERE {where}
            ORDER BY rate ASC
            LIMIT {limit}
        )
        ORDER BY kind, rate DESC
        """,
        params + params,
    )
