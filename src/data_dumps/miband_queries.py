"""Filter state and DuckDB queries for the Mi Band HR explorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util


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


def has_sleep_sessions(conn: duckdb.DuckDBPyConnection) -> bool:
    return query_util.has_table(conn, "sleep", "sessions")


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


def previous_window(f: FilterState) -> FilterState | None:
    bounds = query_util.previous_year_bounds(f.year_start, f.year_end)
    if bounds is None:
        return None
    return FilterState(
        year_start=bounds[0],
        year_end=bounds[1],
    )


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
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


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare_previous: bool = False,
) -> pd.DataFrame:
    """Scoreboard KPIs; optionally append the previous equal-length year window."""
    current = _scoreboard_row(conn, f)
    current["window"] = "current"
    if not compare_previous:
        return current
    prev_f = previous_window(f)
    if prev_f is None:
        return current
    min_row = conn.execute("SELECT min(year)::INT FROM miband.heart_rate").fetchone()
    assert min_row is not None
    min_year = min_row[0]
    if min_year is None or prev_f.year_start is None or prev_f.year_start < min_year:
        current["compare_note"] = (
            f"previous window ({prev_f.year_start}–{prev_f.year_end}) "
            f"predates data (min year {min_year})"
        )
        return current
    prev = _scoreboard_row(conn, prev_f)
    prev["window"] = f"previous ({prev_f.year_start}–{prev_f.year_end})"
    return pd.concat([current, prev], ignore_index=True)


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


def monthly_avg(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("h", f)
    df = _query_df(
        conn,
        f"""
        SELECT
            year,
            month(local_date)::INT AS month,
            round(avg(rate), 1) AS avg_bpm,
            min(rate)::INT AS min_bpm,
            max(rate)::INT AS max_bpm,
            count(*)::BIGINT AS readings,
            count(DISTINCT local_date)::BIGINT AS days
        FROM miband.heart_rate h
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


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


def weekday_hour_heatmap(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
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


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day, round(avg(rate), 1) AS avg_bpm,
               count(*)::BIGINT AS readings
        FROM miband.heart_rate h
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1
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


def zone_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("h", f)
    df = _query_df(
        conn,
        f"""
        SELECT
            year,
            month(local_date)::INT AS month,
            coalesce(rate_zone, '(none)') AS rate_zone,
            count(*)::BIGINT AS readings
        FROM miband.heart_rate h
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
        """,
        params,
    )
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def resting_hr_daily(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, night_end_hour: int = 6
) -> pd.DataFrame:
    """Night-hour resting HR proxy: avg BPM for hours 0..night_end_hour-1."""
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        SELECT
            local_date AS day,
            round(avg(rate), 1) AS resting_bpm,
            min(rate)::INT AS min_bpm,
            count(*)::BIGINT AS readings
        FROM miband.heart_rate h
        WHERE {where}
          AND local_date IS NOT NULL
          AND hour >= 0 AND hour < ?
        GROUP BY 1
        HAVING count(*) >= 3
        ORDER BY 1
        """,
        [*params, night_end_hour],
    )


def resting_hr_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, night_end_hour: int = 6
) -> pd.DataFrame:
    where, params = _where("h", f)
    df = _query_df(
        conn,
        f"""
        SELECT
            year,
            month(local_date)::INT AS month,
            round(avg(rate), 1) AS resting_bpm,
            count(*)::BIGINT AS readings,
            count(DISTINCT local_date)::BIGINT AS nights
        FROM miband.heart_rate h
        WHERE {where}
          AND local_date IS NOT NULL
          AND hour >= 0 AND hour < ?
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        [*params, night_end_hour],
    )
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def high_hr_day_streaks(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, bpm_threshold: float = 90.0
) -> pd.DataFrame:
    """Longest / current streaks of days whose average BPM exceeds threshold."""
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT local_date AS day, avg(rate) AS avg_bpm
            FROM miband.heart_rate h
            WHERE {where} AND local_date IS NOT NULL
            GROUP BY 1
        ),
        flagged AS (
            SELECT day, avg_bpm >= ? AS elevated
            FROM daily
        ),
        ordered AS (
            SELECT
                day,
                elevated,
                day - (row_number() OVER (PARTITION BY elevated ORDER BY day))::INT
                    AS grp
            FROM flagged
            WHERE elevated
        ),
        streaks AS (
            SELECT count(*)::BIGINT AS streak_len, max(day) AS last_d
            FROM ordered
            GROUP BY grp
        )
        SELECT
            coalesce(max(streak_len), 0)::BIGINT AS longest_high_hr_streak,
            coalesce(
                (SELECT streak_len FROM streaks ORDER BY last_d DESC LIMIT 1),
                0
            )::BIGINT AS current_high_hr_streak,
            ?::DOUBLE AS bpm_threshold
        FROM streaks
        """,
        [*params, bpm_threshold, bpm_threshold],
    )


def anomalous_days(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    window: int = 14,
    z_threshold: float = 1.5,
    limit: int = 25,
) -> pd.DataFrame:
    """Days whose avg BPM is far from a trailing rolling mean (z-score)."""
    where, params = _where("h", f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT
                local_date AS day,
                round(avg(rate), 1) AS avg_bpm,
                count(*)::BIGINT AS readings
            FROM miband.heart_rate h
            WHERE {where} AND local_date IS NOT NULL
            GROUP BY 1
        ),
        rolled AS (
            SELECT
                day,
                avg_bpm,
                readings,
                avg(avg_bpm) OVER (
                    ORDER BY day
                    ROWS BETWEEN ? PRECEDING AND 1 PRECEDING
                ) AS roll_mean,
                stddev_samp(avg_bpm) OVER (
                    ORDER BY day
                    ROWS BETWEEN ? PRECEDING AND 1 PRECEDING
                ) AS roll_std
            FROM daily
        )
        SELECT
            day,
            avg_bpm,
            round(roll_mean, 1) AS baseline_bpm,
            round((avg_bpm - roll_mean) / nullif(roll_std, 0), 2) AS z_score,
            readings
        FROM rolled
        WHERE roll_std IS NOT NULL AND roll_std > 0
          AND abs((avg_bpm - roll_mean) / roll_std) >= ?
        ORDER BY abs((avg_bpm - roll_mean) / roll_std) DESC
        LIMIT ?
        """,
        [*params, window, window, z_threshold, limit],
    )


def extremes(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 15
) -> pd.DataFrame:
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


def sleep_nightly_overlay(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Avg HR inside sleep sessions vs sleep hours (empty if sleep not ingested)."""
    if not has_sleep_sessions(conn):
        return pd.DataFrame(
            columns=["day", "hours", "rating", "avg_bpm", "min_bpm", "readings"]
        )
    clauses: list[str] = [
        "s.from_local IS NOT NULL",
        "s.to_local IS NOT NULL",
    ]
    params: list[Any] = []
    if f.year_start is not None:
        clauses.append("year(s.local_date) >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append("year(s.local_date) <= ?")
        params.append(f.year_end)
    where = " AND ".join(clauses)
    return _query_df(
        conn,
        f"""
        SELECT
            s.local_date AS day,
            s.hours,
            s.rating,
            round(avg(h.rate), 1) AS avg_bpm,
            min(h.rate)::INT AS min_bpm,
            count(*)::BIGINT AS readings
        FROM sleep.sessions s
        JOIN miband.heart_rate h
          ON h.ts_local >= s.from_local AND h.ts_local <= s.to_local
        WHERE {where}
        GROUP BY 1, 2, 3
        HAVING count(*) >= 5
        ORDER BY 1
        """,
        params,
    )
