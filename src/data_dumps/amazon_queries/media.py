"""Amazon digital media and impression queries."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps.amazon_queries.filters import FilterState, _query_df, _year_clause


def audible_hours(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(product_name, asin) AS title,
            round(sum(coalesce(duration_ms, 0)) / 3600000.0, 2) AS hours
        FROM amazon.audible_listens a
        WHERE {where}
        GROUP BY 1
        ORDER BY hours DESC
        LIMIT 20
        """,
        params,
    )


def audible_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            round(sum(coalesce(duration_ms, 0)) / 3600000.0, 2) AS hours
        FROM amazon.audible_listens a
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def audible_calendar(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            cast(start_ts_local AS DATE) AS day,
            round(sum(coalesce(duration_ms, 0)) / 3600000.0, 2) AS hours
        FROM amazon.audible_listens a
        WHERE {where} AND start_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def video_titles(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("v", f)
    return _query_df(
        conn,
        f"""
        SELECT
            title,
            round(sum(coalesce(seconds_viewed, 0)) / 60.0, 1) AS minutes,
            count(*)::BIGINT AS sessions
        FROM amazon.video_views v
        WHERE {where} AND title IS NOT NULL
        GROUP BY 1
        ORDER BY minutes DESC
        LIMIT 20
        """,
        params,
    )


def video_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("v", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            count(*)::BIGINT AS sessions
        FROM amazon.video_views v
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def video_calendar(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("v", f)
    return _query_df(
        conn,
        f"""
        SELECT
            cast(start_ts_local AS DATE) AS day,
            count(*)::BIGINT AS sessions
        FROM amazon.video_views v
        WHERE {where} AND start_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def music_plays_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("m", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            count(*)::BIGINT AS plays
        FROM amazon.music_plays m
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def music_plays_calendar(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("m", f)
    return _query_df(
        conn,
        f"""
        SELECT
            cast(play_ts_local AS DATE) AS day,
            count(*)::BIGINT AS plays
        FROM amazon.music_plays m
        WHERE {where} AND play_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def kindle_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("k", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            count(*)::BIGINT AS sessions,
            round(sum(coalesce(duration_ms, 0)) / 3600000.0, 2) AS hours
        FROM amazon.kindle_sessions k
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def music_top_searches(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 20
) -> pd.DataFrame:
    where, params = _year_clause("m", f)
    return _query_df(
        conn,
        f"""
        SELECT query, count(*)::BIGINT AS n
        FROM amazon.music_searches m
        WHERE {where} AND query IS NOT NULL
        GROUP BY 1
        ORDER BY n DESC
        LIMIT ?
        """,
        params + [limit],
    )


def rufus_top(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 20
) -> pd.DataFrame:
    where, params = _year_clause("r", f)
    return _query_df(
        conn,
        f"""
        SELECT query, count(*)::BIGINT AS n
        FROM amazon.rufus_queries r
        WHERE {where} AND query IS NOT NULL
        GROUP BY 1
        ORDER BY n DESC
        LIMIT ?
        """,
        params + [limit],
    )


def impression_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("p", f)
    return _query_df(
        conn,
        f"""
        SELECT kind, count(*)::BIGINT AS n
        FROM amazon.product_impressions p
        WHERE {where}
        GROUP BY 1
        ORDER BY n DESC
        """,
        params,
    )


def impression_top(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 20
) -> pd.DataFrame:
    where, params = _year_clause("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            asin,
            any_value(product_name) AS product_name,
            kind,
            count(*)::BIGINT AS views
        FROM amazon.product_impressions p
        WHERE {where} AND asin IS NOT NULL
        GROUP BY asin, kind
        ORDER BY views DESC
        LIMIT ?
        """,
        params + [limit],
    )


def activity_by_country(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Video sessions + product impressions by marketplace country_code."""
    from data_dumps.amazon_queries.filters import has_table

    parts: list[str] = []
    params: list[Any] = []
    if has_table(conn, "video_views"):
        v_where, v_params = _year_clause("v", f)
        parts.append(
            f"""
            SELECT
                country_code AS country,
                count(*)::BIGINT AS events,
                'video' AS source
            FROM amazon.video_views v
            WHERE {v_where} AND country_code IS NOT NULL
            GROUP BY 1
            """
        )
        params.extend(v_params)
    if has_table(conn, "product_impressions"):
        p_where, p_params = _year_clause("p", f)
        parts.append(
            f"""
            SELECT
                country_code AS country,
                count(*)::BIGINT AS events,
                'impressions' AS source
            FROM amazon.product_impressions p
            WHERE {p_where} AND country_code IS NOT NULL
            GROUP BY 1
            """
        )
        params.extend(p_params)
    if not parts:
        return pd.DataFrame(columns=["country", "events", "video", "impressions"])
    union = " UNION ALL ".join(parts)
    return _query_df(
        conn,
        f"""
        WITH raw AS ({union})
        SELECT
            country,
            sum(events)::BIGINT AS events,
            coalesce(sum(events) FILTER (WHERE source = 'video'), 0)::BIGINT AS video,
            coalesce(sum(events) FILTER (WHERE source = 'impressions'), 0)::BIGINT
                AS impressions
        FROM raw
        GROUP BY 1
        ORDER BY events DESC
        """,
        params,
    )
