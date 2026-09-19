"""Google Takeout queries — maps."""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps.google_queries.filters import (
    FilterState,
    _query_df,
    _year_where,
)


def maps_by_country(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 30
) -> pd.DataFrame:
    where, params = _year_where("m", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(m.country_code, '??') AS country_code,
            count(*)::BIGINT AS saves
        FROM google.maps_saves m
        WHERE {where}
        GROUP BY 1
        ORDER BY saves DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def maps_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_where("m", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', m.year, m.month) AS year_month,
            count(*)::BIGINT AS saves
        FROM google.maps_saves m
        WHERE {where} AND m.year IS NOT NULL AND m.month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def maps_reviews_table(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_where("m", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(m.place_name, '(unnamed)') AS place_name,
            coalesce(m.country_code, '??') AS country_code,
            m.rating,
            m.day
        FROM google.maps_reviews m
        WHERE {where}
        ORDER BY m.day DESC NULLS LAST, place_name
        """,
        params,
    )


def forgotten_places(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 2,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _year_where("m", f)
    return _query_df(
        conn,
        f"""
        WITH place_span AS (
            SELECT
                coalesce(m.place_name, '(unnamed)') AS place,
                coalesce(m.country_code, '??') AS country_code,
                count(*)::BIGINT AS saves,
                max(m.saved_utc) AS last_ts
            FROM google.maps_saves m
            WHERE {where} AND m.place_name IS NOT NULL
            GROUP BY 1, 2
        )
        SELECT place, country_code, saves, last_ts::DATE AS last_day
        FROM place_span
        WHERE last_ts < current_timestamp - (? * INTERVAL '1 year')
        ORDER BY saves DESC, last_day
        LIMIT ?
        """,
        [*params, silent_years, limit],
    )


def comeback_places(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 2,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _year_where("m", f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                coalesce(m.place_name, '(unnamed)') AS place,
                m.saved_utc AS ts,
                lag(m.saved_utc) OVER (
                    PARTITION BY m.place_name ORDER BY m.saved_utc
                ) AS prev_ts
            FROM google.maps_saves m
            WHERE {where} AND m.place_name IS NOT NULL AND m.saved_utc IS NOT NULL
        )
        SELECT
            place,
            prev_ts::DATE AS previous_day,
            ts::DATE AS return_day,
            date_diff('day', prev_ts, ts) AS gap_days
        FROM ordered
        WHERE prev_ts IS NOT NULL
          AND date_diff('day', prev_ts, ts) >= (? * 365)
        ORDER BY gap_days DESC
        LIMIT ?
        """,
        [*params, silent_years, limit],
    )


def country_rank_bump(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, top_n: int = 8
) -> pd.DataFrame:
    where, params = _year_where("m", f)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT
                m.year,
                coalesce(m.country_code, '??') AS country_code,
                count(*)::BIGINT AS saves
            FROM google.maps_saves m
            WHERE {where} AND m.year IS NOT NULL
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT
                year,
                country_code,
                saves,
                rank() OVER (PARTITION BY year ORDER BY saves DESC) AS rnk
            FROM yearly
        )
        SELECT year, country_code, saves, rnk
        FROM ranked
        WHERE rnk <= ?
        ORDER BY year, rnk
        """,
        [*params, top_n],
    )


def maps_rating_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_where("m", f)
    return _query_df(
        conn,
        f"""
        SELECT
            m.rating,
            count(*)::BIGINT AS reviews
        FROM google.maps_reviews m
        WHERE {where} AND m.rating IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def maps_reviews_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_where("m", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', m.year, m.month) AS year_month,
            count(*)::BIGINT AS reviews,
            round(avg(m.rating), 2) AS avg_rating
        FROM google.maps_reviews m
        WHERE {where} AND m.year IS NOT NULL AND m.month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def saved_place_titles(
    conn: duckdb.DuckDBPyConnection, *, limit: int = 200
) -> pd.DataFrame:
    """List name + title only. URLs and notes can carry street addresses."""
    return _query_df(
        conn,
        """
        SELECT
            coalesce(list_name, '(unknown)') AS list_name,
            coalesce(title, '(untitled)') AS title
        FROM google.saved_places
        ORDER BY list_name, title
        LIMIT ?
        """,
        [limit],
    )


def maps_saves_monthly_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    return maps_monthly(conn, FilterState(year_start=year_start, year_end=year_end))


def maps_saves_daily_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _year_where("m", f)
    return _query_df(
        conn,
        f"""
        SELECT m.day AS day, count(*)::BIGINT AS saves
        FROM google.maps_saves m
        WHERE {where} AND m.day IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )
