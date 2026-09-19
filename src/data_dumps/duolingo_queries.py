"""Filter state and DuckDB queries for the Duolingo explorer (light)."""

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
        chip = query_util.year_chip(self.year_start, self.year_end)
        if chip is not None:
            chips.append(chip)
        return chips


def _where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    return query_util.year_clause(alias, f.year_start, f.year_end)


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
            min(day)::DATE, max(day)::DATE
        FROM (
            SELECT year, cast(ts_local AS DATE) AS day
            FROM duolingo.progress_events
            WHERE ts_local IS NOT NULL
            UNION ALL
            SELECT year, cast(ts_local AS DATE) AS day
            FROM duolingo.leaderboards
            WHERE ts_local IS NOT NULL
            UNION ALL
            SELECT year, cast(purchase_ts_local AS DATE) AS day
            FROM duolingo.inventory
            WHERE purchase_ts_local IS NOT NULL
        )
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        joined = conn.execute(
            "SELECT year FROM duolingo.account WHERE year IS NOT NULL LIMIT 1"
        ).fetchone()
        y = int(joined[0]) if joined and joined[0] is not None else 2012
        min_year, max_year = y, y
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
    return FilterState(year_start=bounds[0], year_end=bounds[1])


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    pe_where, pe_params = _where("pe", f)
    inv_where, inv_params = _where("i", f)
    lb_where, lb_params = _where("lb", f)
    return _query_df(
        conn,
        f"""
        SELECT
            (
                SELECT count(*)::BIGINT FROM duolingo.progress_events pe
                WHERE {pe_where}
            ) AS progress_events,
            (
                SELECT count(*)::BIGINT FROM duolingo.languages
                WHERE coalesce(points, 0) > 0
            ) AS languages_with_points,
            (
                SELECT count(*)::BIGINT FROM duolingo.inventory i
                WHERE {inv_where}
            ) AS inventory_buys,
            (
                SELECT max(tier)::BIGINT FROM duolingo.leaderboards lb
                WHERE {lb_where}
            ) AS league_max_tier
        """,
        pe_params + inv_params + lb_params,
    )


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare_previous: bool = False,
) -> pd.DataFrame:
    current = _scoreboard_row(conn, f)
    current["window"] = "current"
    if not compare_previous:
        return current
    prev_f = previous_window(f)
    if prev_f is None:
        return current
    bounds = data_bounds(conn)
    if prev_f.year_start is None or prev_f.year_start < bounds["min_year"]:
        current["compare_note"] = (
            f"previous window ({prev_f.year_start}–{prev_f.year_end}) "
            f"predates data (min year {bounds['min_year']})"
        )
        return current
    prev = _scoreboard_row(conn, prev_f)
    prev["window"] = f"previous ({prev_f.year_start}–{prev_f.year_end})"
    return pd.concat([current, prev], ignore_index=True)


def languages_table(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            learning_language,
            from_language,
            coalesce(points, 0)::BIGINT AS points,
            skills_learned,
            total_lessons,
            days_active,
            last_active_local,
            prior_proficiency
        FROM duolingo.languages
        ORDER BY points DESC NULLS LAST, learning_language
        """,
    )


def leaderboard_tier_timeline(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("lb", f)
    return _query_df(
        conn,
        f"""
        SELECT
            ts_local,
            year,
            month,
            leaderboard,
            tier,
            score
        FROM duolingo.leaderboards lb
        WHERE {where}
        ORDER BY ts_local
        """,
        params,
    )


def progress_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("pe", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS events
        FROM duolingo.progress_events pe
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY year, month
        ORDER BY year, month
        """,
        params,
    )


def progress_by_language(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("pe", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(language, '(unknown)') AS language,
            count(*)::BIGINT AS events
        FROM duolingo.progress_events pe
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        """,
        params,
    )


def progress_monthly_for_language(
    conn: duckdb.DuckDBPyConnection, f: FilterState, language: str
) -> pd.DataFrame:
    where, params = _where("pe", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS events
        FROM duolingo.progress_events pe
        WHERE {where}
          AND coalesce(language, '(unknown)') = ?
          AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY year, month
        ORDER BY year, month
        """,
        [*params, language],
    )


def inventory_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("i", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS buys
        FROM duolingo.inventory i
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY year, month
        ORDER BY year, month
        """,
        params,
    )


def inventory_by_type_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("i", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            coalesce(item_type, '(unknown)') AS item_type,
            count(*)::BIGINT AS buys
        FROM duolingo.inventory i
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY year, month, item_type
        ORDER BY year, month, buys DESC
        """,
        params,
    )


def leaderboard_tier_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("lb", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            max(tier)::BIGINT AS max_tier
        FROM duolingo.leaderboards lb
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY year, month
        ORDER BY year, month
        """,
        params,
    )


def calendar_daily_progress(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("pe", f)
    return _query_df(
        conn,
        f"""
        SELECT
            cast(ts_local AS DATE) AS day,
            count(*)::BIGINT AS events
        FROM duolingo.progress_events pe
        WHERE {where} AND ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def calendar_daily_inventory(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("i", f)
    return _query_df(
        conn,
        f"""
        SELECT
            cast(purchase_ts_local AS DATE) AS day,
            count(*)::BIGINT AS buys
        FROM duolingo.inventory i
        WHERE {where} AND purchase_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def calendar_daily_league_tier(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("lb", f)
    return _query_df(
        conn,
        f"""
        SELECT
            cast(ts_local AS DATE) AS day,
            max(tier)::BIGINT AS max_tier
        FROM duolingo.leaderboards lb
        WHERE {where} AND ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def weekday_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """ISO weekday (1=Mon … 7=Sun) × hour local for progress events."""
    where, params = _where("pe", f)
    return _query_df(
        conn,
        f"""
        SELECT
            isodow(ts_local)::INT AS dow,
            extract('hour' FROM ts_local)::INT AS hour,
            count(*)::BIGINT AS events
        FROM duolingo.progress_events pe
        WHERE {where} AND ts_local IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def friends_snapshot(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            num_following,
            num_followers,
            num_blocking,
            num_blockers,
            generated_ts_local
        FROM duolingo.friends
        """,
    )


def account_summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT username, joined_at_local, year
        FROM duolingo.account
        """,
    )
