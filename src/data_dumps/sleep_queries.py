"""Filter state and DuckDB queries for the Sleep as Android explorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    tags: list[str] | None = None
    min_rating: float | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        if self.tags:
            chips.append(("tags", "tags " + ", ".join(self.tags)))
        if self.min_rating is not None:
            chips.append(("rating", f"rating ≥ {self.min_rating}"))
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
    if f.min_rating is not None:
        clauses.append(f"{p}rating >= ?")
        params.append(f.min_rating)
    if f.tags:
        tag_parts = []
        for tag in f.tags:
            tag_parts.append(f"list_contains(string_split({p}tags, ' '), ?)")
            params.append(tag)
        clauses.append("(" + " OR ".join(tag_parts) + ")")
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
        FROM sleep.sessions
        WHERE local_date IS NOT NULL
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2017, 2026
    tags = conn.execute("""
        SELECT DISTINCT unnest(string_split(tags, ' ')) AS tag
        FROM sleep.sessions
        WHERE tags IS NOT NULL AND tags != ''
        ORDER BY 1
        """).fetchdf()
    tag_list = [t for t in tags["tag"].tolist() if t] if not tags.empty else []
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "tags": tag_list,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    tags: list[str] | None = None,
    min_rating: float | None = None,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    rating = min_rating if min_rating and min_rating > 0 else None
    return FilterState(
        year_start=ys,
        year_end=ye,
        tags=tags or None,
        min_rating=rating,
    )


def scoreboard(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS nights,
            round(avg(hours), 2) AS avg_hours,
            round(avg(deep_sleep), 3) AS avg_deep_frac,
            round(avg(deep_hours), 2) AS avg_deep_hours,
            round(avg(rating), 2) AS avg_rating,
            round(avg(cycles), 1) AS avg_cycles,
            round(avg(noise), 4) AS avg_noise,
            sum(CASE WHEN coalesce(snore, 0) > 0 THEN 1 ELSE 0 END)::BIGINT AS snore_nights,
            round(avg(bed_hour + extract(minute FROM from_local) / 60.0), 2)
                AS avg_bed_hour,
            round(avg(wake_hour + extract(minute FROM to_local) / 60.0), 2)
                AS avg_wake_hour
        FROM sleep.sessions s
        WHERE {where}
        """,
        params,
    )


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        WITH nights AS (
            SELECT local_date, hours
            FROM sleep.sessions s
            WHERE {where} AND local_date IS NOT NULL AND hours IS NOT NULL
        ),
        flagged AS (
            SELECT local_date, hours >= 7.0 AS enough
            FROM nights
        ),
        ordered AS (
            SELECT
                local_date,
                enough,
                local_date - (row_number() OVER (PARTITION BY enough ORDER BY local_date))::INT
                    AS grp
            FROM flagged
            WHERE enough
        ),
        streaks AS (
            SELECT count(*)::BIGINT AS streak_len
            FROM ordered
            GROUP BY grp
        )
        SELECT
            coalesce(max(streak_len), 0)::BIGINT AS longest_7h_streak,
            coalesce(
                (SELECT streak_len FROM (
                    SELECT grp, count(*)::BIGINT AS streak_len, max(local_date) AS last_d
                    FROM ordered GROUP BY grp
                ) t ORDER BY last_d DESC LIMIT 1),
                0
            )::BIGINT AS current_7h_streak
        FROM streaks
        """,
        params,
    )


def monthly_hours(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            date_trunc('month', local_date)::DATE AS month,
            round(avg(hours), 2) AS avg_hours,
            round(avg(deep_hours), 2) AS avg_deep_hours,
            round(avg(rating), 2) AS avg_rating,
            count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def hours_over_time(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day, hours, deep_hours, rating, cycles
        FROM sleep.sessions s
        WHERE {where} AND local_date IS NOT NULL
        ORDER BY 1
        """,
        params,
    )


def bedtime_distribution(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT bed_hour AS hour, count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND bed_hour IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def wake_distribution(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT wake_hour AS hour, count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND wake_hour IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def weekday_hours(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            weekday AS dow,
            round(avg(hours), 2) AS avg_hours,
            round(avg(rating), 2) AS avg_rating,
            count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND weekday IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day, hours, rating
        FROM sleep.sessions s
        WHERE {where} AND local_date IS NOT NULL
        ORDER BY 1
        """,
        params,
    )


def event_type_counts(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT e.event_type, count(*)::BIGINT AS events
        FROM sleep.events e
        JOIN sleep.sessions s ON s.id = e.session_id
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        LIMIT 25
        """,
        params,
    )


def tag_breakdown(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            unnest(string_split(s.tags, ' ')) AS tag,
            count(*)::BIGINT AS nights,
            round(avg(hours), 2) AS avg_hours
        FROM sleep.sessions s
        WHERE {where} AND tags IS NOT NULL AND tags != ''
        GROUP BY 1
        HAVING tag != ''
        ORDER BY nights DESC
        """,
        params,
    )


def best_worst_nights(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 10
) -> tuple[pd.DataFrame, pd.DataFrame]:
    where, params = _where("s", f)
    cols = """
        local_date AS day, hours, deep_hours, rating, cycles, tags, comment
        FROM sleep.sessions s
        WHERE {where} AND hours IS NOT NULL
    """
    best = _query_df(
        conn,
        f"SELECT {cols.format(where=where)} ORDER BY hours DESC LIMIT {limit}",
        params,
    )
    worst = _query_df(
        conn,
        f"SELECT {cols.format(where=where)} ORDER BY hours ASC LIMIT {limit}",
        params,
    )
    return best, worst


def sample_actigraphy(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit_sessions: int = 1
) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        WITH pick AS (
            SELECT id, local_date
            FROM sleep.sessions s
            WHERE {where}
            ORDER BY local_date DESC
            LIMIT {limit_sessions}
        )
        SELECT p.local_date AS day, a.bucket_label, a.value
        FROM sleep.actigraphy a
        JOIN pick p ON p.id = a.session_id
        WHERE a.value IS NOT NULL
        ORDER BY p.local_date, a.bucket_label
        """,
        params,
    )


def stage_event_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Count stage-related START events per year."""
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            s.year,
            e.event_type,
            count(*)::BIGINT AS events
        FROM sleep.events e
        JOIN sleep.sessions s ON s.id = e.session_id
        WHERE {where}
          AND e.event_type IN (
              'DEEP_START', 'LIGHT_START', 'REM_START', 'AWAKE_START',
              'DEEP_END', 'LIGHT_END', 'REM_END', 'AWAKE_END'
          )
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )
