"""Google Takeout queries — play."""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps.google_queries.filters import (
    FilterState,
    _query_df,
    _year_where,
)


def play_installs_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', p.year, p.month) AS year_month,
            count(*)::BIGINT AS installs
        FROM google.play_installs p
        WHERE {where} AND p.year IS NOT NULL AND p.month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def play_top_apps(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(p.title, '(unknown)') AS app,
            count(*)::BIGINT AS installs,
            min(p.first_install_local)::DATE AS first_seen,
            max(p.last_update_utc)::DATE AS last_update
        FROM google.play_installs p
        WHERE {where}
        GROUP BY 1
        ORDER BY installs DESC, app
        LIMIT ?
        """,
        [*params, limit],
    )


def play_by_device(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(p.device_model, '(unknown)') AS device,
            count(*)::BIGINT AS installs
        FROM google.play_installs p
        WHERE {where}
        GROUP BY 1
        ORDER BY installs DESC
        """,
        params,
    )


def forgotten_apps(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 2,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    years = max(int(silent_years), 1)
    return _query_df(
        conn,
        f"""
        WITH app_span AS (
            SELECT
                coalesce(p.title, '(unknown)') AS app,
                count(*)::BIGINT AS installs,
                max(p.last_update_utc) AS last_ts
            FROM google.play_installs p
            WHERE {where}
            GROUP BY 1
            HAVING count(*) >= 1
        )
        SELECT app, installs, last_ts::DATE AS last_update
        FROM app_span
        WHERE last_ts IS NOT NULL
          AND last_ts < current_timestamp - (? * INTERVAL '1 year')
        ORDER BY last_update, installs DESC
        LIMIT ?
        """,
        [*params, years, limit],
    )


def play_purchases_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', p.year, p.month) AS year_month,
            count(*)::BIGINT AS purchases
        FROM google.play_purchases p
        WHERE {where} AND p.year IS NOT NULL AND p.month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def play_purchase_totals(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Purchase count + optional A$/ $ amount parse (no FX conversion)."""
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS purchase_count,
            sum(
                CASE
                    WHEN regexp_matches(
                        trim(coalesce(p.invoice_price, '')),
                        '^(A\\$|\\$)\\d+\\.\\d{{2}}$'
                    )
                    THEN try_cast(
                        regexp_extract(
                            trim(p.invoice_price),
                            '(A\\$|\\$)(\\d+\\.\\d{{2}})',
                            2
                        ) AS DOUBLE
                    )
                    ELSE NULL
                END
            ) AS parsed_spend_aud
        FROM google.play_purchases p
        WHERE {where}
        """,
        params,
    )


def play_library_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', p.year, p.month) AS year_month,
            coalesce(p.document_type, '(unknown)') AS document_type,
            count(*)::BIGINT AS items
        FROM google.play_library p
        WHERE {where} AND p.year IS NOT NULL AND p.month IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, items DESC
        """,
        params,
    )


def play_library_top(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(p.title, '(untitled)') AS title,
            coalesce(p.document_type, '(unknown)') AS document_type,
            count(*)::BIGINT AS items,
            min(p.day) AS first_day
        FROM google.play_library p
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY items DESC, title
        LIMIT ?
        """,
        [*params, limit],
    )


def play_subscription_states(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(p.state, '(unknown)') AS state,
            count(*)::BIGINT AS subscriptions
        FROM google.play_subscriptions p
        WHERE {where}
        GROUP BY 1
        ORDER BY subscriptions DESC
        """,
        params,
    )


def play_subscriptions_table(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 40
) -> pd.DataFrame:
    where, params = _year_where("p", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(p.title, '(untitled)') AS title,
            coalesce(p.document_type, '(unknown)') AS document_type,
            coalesce(p.state, '(unknown)') AS state,
            p.expiration_utc::DATE AS expires
        FROM google.play_subscriptions p
        WHERE {where}
        ORDER BY p.expiration_utc DESC NULLS LAST, title
        LIMIT ?
        """,
        [*params, limit],
    )


def play_installs_monthly_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    return play_installs_monthly(
        conn, FilterState(year_start=year_start, year_end=year_end)
    )
