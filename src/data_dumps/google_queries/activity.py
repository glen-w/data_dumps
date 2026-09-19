"""Google Takeout queries — activity."""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps.google_queries.filters import (
    FilterState,
    _query_df,
    _year_where,
)


def photos_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', p.year, p.month) AS year_month,
            count(*)::BIGINT AS photos
        FROM google.photos p
        WHERE {where} AND p.year IS NOT NULL AND p.month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def photos_by_album(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(p.album, '(unknown)') AS album,
            count(*)::BIGINT AS photos
        FROM google.photos p
        WHERE {where}
        GROUP BY 1
        ORDER BY photos DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def photos_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT p.day AS day, count(*)::BIGINT AS photos
        FROM google.photos p
        WHERE {where} AND p.day IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def photos_weekday_heatmap(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            isodow(p.taken_local)::INT AS dow,
            hour(p.taken_local) AS hour,
            count(*)::BIGINT AS photos
        FROM google.photos p
        WHERE {where}
          AND p.taken_local IS NOT NULL
          AND (
              hour(p.taken_local) <> 0
              OR minute(p.taken_local) <> 0
              OR second(p.taken_local) <> 0
          )
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def activity_by_product(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(a.product, '(unknown)') AS product,
            count(*)::BIGINT AS events
        FROM google.activity a
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        """,
        params,
    )


def activity_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', a.year, a.month) AS year_month,
            count(*)::BIGINT AS events
        FROM google.activity a
        WHERE {where} AND a.year IS NOT NULL AND a.month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def activity_weekday_heatmap(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            isodow(a.ts_local)::INT AS dow,
            hour(a.ts_local) AS hour,
            count(*)::BIGINT AS events
        FROM google.activity a
        WHERE {where} AND a.ts_local IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def footprint_by_category(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            coalesce(category, 'other') AS category,
            count(*)::BIGINT AS files,
            coalesce(sum(bytes), 0)::BIGINT AS bytes,
            count(*) FILTER (WHERE ingested)::BIGINT AS ingested_files
        FROM google.dump_inventory
        GROUP BY 1
        ORDER BY bytes DESC
        """,
    )


def saved_lists_summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            coalesce(list_name, '(unknown)') AS list_name,
            count(*)::BIGINT AS places
        FROM google.saved_places
        GROUP BY 1
        ORDER BY places DESC
        """,
    )


def tasks_summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            coalesce(status, '(unknown)') AS status,
            count(*)::BIGINT AS tasks
        FROM google.tasks
        GROUP BY 1
        ORDER BY tasks DESC
        """,
    )


def activity_by_action(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(a.product, '(unknown)') AS product,
            coalesce(a.action, '(unknown)') AS action,
            count(*)::BIGINT AS events
        FROM google.activity a
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY events DESC
        """,
        params,
    )


def activity_product_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', a.year, a.month) AS year_month,
            coalesce(a.product, '(unknown)') AS product,
            count(*)::BIGINT AS events
        FROM google.activity a
        WHERE {where} AND a.year IS NOT NULL AND a.month IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, events DESC
        """,
        params,
    )


def activity_top_titles(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    """Title + product + action only. Activity URLs stay out of the panel."""
    where, params = _year_where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(a.title, '(untitled)') AS title,
            coalesce(a.product, '(unknown)') AS product,
            coalesce(a.action, '(unknown)') AS action,
            count(*)::BIGINT AS events
        FROM google.activity a
        WHERE {where} AND a.title IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY events DESC, title
        LIMIT ?
        """,
        [*params, limit],
    )


def tasks_timeline(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Monthly completed vs open counts from created/completed timestamps."""
    where, params = _year_where("t", f)
    return _query_df(
        conn,
        f"""
        WITH dated AS (
            SELECT
                coalesce(
                    CASE WHEN t.completed_utc IS NOT NULL THEN
                        printf('%04d-%02d', year(t.completed_utc), month(t.completed_utc))
                    END,
                    CASE WHEN t.created_utc IS NOT NULL THEN
                        printf('%04d-%02d', year(t.created_utc), month(t.created_utc))
                    END,
                    CASE WHEN t.year IS NOT NULL AND t.month IS NOT NULL THEN
                        printf('%04d-%02d', t.year, t.month)
                    END
                ) AS year_month,
                t.status
            FROM google.tasks t
            WHERE {where}
        )
        SELECT
            year_month,
            count(*) FILTER (
                WHERE lower(coalesce(status, '')) IN ('completed', 'complete')
            )::BIGINT AS completed,
            count(*) FILTER (
                WHERE lower(coalesce(status, '')) NOT IN ('completed', 'complete')
            )::BIGINT AS open
        FROM dated
        WHERE year_month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def photos_monthly_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    return photos_monthly(conn, FilterState(year_start=year_start, year_end=year_end))


def photos_daily_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    return photos_daily(conn, FilterState(year_start=year_start, year_end=year_end))
