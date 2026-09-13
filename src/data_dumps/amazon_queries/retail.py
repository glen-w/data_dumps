"""Amazon retail / order analytics queries."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps.amazon_queries.filters import (
    FilterState,
    _item_where,
    _query_df,
    _year_clause,
)


def scoreboard(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _item_where(f)
    yw, yp = _year_clause("r", f)
    return _query_df(
        conn,
        f"""
        WITH base AS (
            SELECT * FROM amazon.order_items i WHERE {where}
        ),
        baskets AS (
            SELECT order_id, count(*)::DOUBLE AS n_items
            FROM base
            WHERE NOT is_cancelled
            GROUP BY order_id
        )
        SELECT
            (SELECT count(*) FROM base)::BIGINT AS order_lines,
            (SELECT count(DISTINCT order_id) FROM base)::BIGINT AS orders,
            (SELECT count(DISTINCT asin) FROM base)::BIGINT AS asins,
            (SELECT count(DISTINCT currency) FROM base WHERE currency IS NOT NULL)
                ::BIGINT AS currencies,
            (SELECT coalesce(sum(CASE WHEN is_cancelled THEN 1 ELSE 0 END), 0)
                FROM base)::BIGINT AS cancelled_lines,
            (SELECT round(coalesce(sum(line_total)
                FILTER (WHERE NOT is_cancelled), 0), 2) FROM base) AS spend_sum_mixed,
            (SELECT round(avg(n_items), 2) FROM baskets) AS avg_basket_items,
            (SELECT count(DISTINCT order_id)::BIGINT FROM amazon.returns r
                WHERE {yw}) AS return_orders
        """,
        params + yp,
    )


def spend_by_currency(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            currency,
            count(*)::BIGINT AS lines,
            count(DISTINCT order_id)::BIGINT AS orders,
            round(sum(coalesce(line_total, 0)), 2) AS spend
        FROM amazon.order_items i
        WHERE {where} AND currency IS NOT NULL
        GROUP BY 1
        ORDER BY spend DESC
        """,
        params,
    )


def life_chapters(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            year,
            coalesce(marketplace, 'unknown') AS marketplace,
            count(*)::BIGINT AS lines,
            round(sum(coalesce(line_total, 0)), 2) AS spend
        FROM amazon.order_items i
        WHERE {where} AND year IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def monthly_orders(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            count(*)::BIGINT AS lines,
            count(DISTINCT order_id)::BIGINT AS orders,
            round(sum(coalesce(line_total, 0)), 2) AS spend
        FROM amazon.order_items i
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def dept_treemap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            dept_family,
            coalesce(department, 'Unknown') AS department,
            count(*)::BIGINT AS lines,
            round(sum(coalesce(line_total, 0)), 2) AS spend
        FROM amazon.order_items i
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY spend DESC
        """,
        params,
    )


def top_products(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 25
) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            asin,
            any_value(product_name) AS product_name,
            any_value(dept_family) AS dept_family,
            count(*)::BIGINT AS times_ordered,
            round(sum(coalesce(line_total, 0)), 2) AS spend,
            any_value(currency) AS currency
        FROM amazon.order_items i
        WHERE {where} AND asin IS NOT NULL
        GROUP BY asin
        ORDER BY times_ordered DESC, spend DESC
        LIMIT ?
        """,
        params + [limit],
    )


def search_funnel(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS searches,
            sum(CASE WHEN clicked THEN 1 ELSE 0 END)::BIGINT AS clicked,
            sum(CASE WHEN added THEN 1 ELSE 0 END)::BIGINT AS added,
            sum(CASE WHEN purchased THEN 1 ELSE 0 END)::BIGINT AS purchased,
            sum(CASE WHEN abandoned THEN 1 ELSE 0 END)::BIGINT AS abandoned
        FROM amazon.searches s
        WHERE {where}
        """,
        params,
    )


def top_search_keywords(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 30
) -> pd.DataFrame:
    where, params = _year_clause("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            keywords,
            count(*)::BIGINT AS searches,
            sum(CASE WHEN purchased THEN 1 ELSE 0 END)::BIGINT AS purchased
        FROM amazon.searches s
        WHERE {where} AND keywords IS NOT NULL
        GROUP BY 1
        ORDER BY searches DESC
        LIMIT ?
        """,
        params + [limit],
    )


def returns_summary(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("r", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(return_reason, '(none)') AS return_reason,
            count(*)::BIGINT AS n,
            round(sum(coalesce(refund_amount, 0)), 2) AS refund_sum
        FROM amazon.returns r
        WHERE {where}
        GROUP BY 1
        ORDER BY n DESC
        """,
        params,
    )


def order_circadian(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            isodow(order_ts_local)::INT AS dow,
            hour(order_ts_local)::INT AS hour,
            count(*)::BIGINT AS events
        FROM amazon.order_items i
        WHERE {where} AND order_ts_local IS NOT NULL
        GROUP BY 1, 2
        """,
        params,
    )


def footprint_by_category(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            category,
            count(*)::BIGINT AS files,
            sum(bytes)::BIGINT AS bytes,
            sum(CASE WHEN ingested THEN 1 ELSE 0 END)::BIGINT AS ingested_files
        FROM amazon.dump_inventory
        GROUP BY 1
        ORDER BY bytes DESC
        """,
    )


def footprint_scoreboard(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            count(*)::BIGINT AS files,
            coalesce(sum(bytes), 0)::BIGINT AS total_bytes,
            coalesce(sum(bytes) FILTER (WHERE category = 'voice_audio'), 0)::BIGINT
                AS voice_bytes,
            count(*) FILTER (WHERE category = 'voice_audio')::BIGINT AS voice_files,
            count(*) FILTER (WHERE ingested)::BIGINT AS ingested_members
        FROM amazon.dump_inventory
        """,
    )


def surface_counts(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT 'retail_lines' AS surface, count(*)::BIGINT AS n FROM amazon.order_items
        UNION ALL SELECT 'digital', count(*) FROM amazon.digital_items
        UNION ALL SELECT 'searches', count(*) FROM amazon.searches
        UNION ALL SELECT 'alexa_intents', count(*) FROM amazon.alexa_intents
        UNION ALL SELECT 'audible_listens', count(*) FROM amazon.audible_listens
        UNION ALL SELECT 'video_views', count(*) FROM amazon.video_views
        UNION ALL SELECT 'music_plays', count(*) FROM amazon.music_plays
        UNION ALL SELECT 'kindle_sessions', count(*) FROM amazon.kindle_sessions
        UNION ALL SELECT 'rufus', count(*) FROM amazon.rufus_queries
        UNION ALL SELECT 'impressions', count(*) FROM amazon.product_impressions
        UNION ALL SELECT 'devices', count(*) FROM amazon.devices_summary
        ORDER BY n DESC
        """,
    )


def forgotten_asins(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 20
) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        WITH last_buy AS (
            SELECT
                asin,
                any_value(product_name) AS product_name,
                max(order_ts_local) AS last_ordered,
                count(*)::BIGINT AS times
            FROM amazon.order_items i
            WHERE {where} AND asin IS NOT NULL
            GROUP BY asin
        )
        SELECT *
        FROM last_buy
        WHERE times = 1
        ORDER BY last_ordered ASC NULLS LAST
        LIMIT ?
        """,
        params + [limit],
    )


def comeback_asins(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 20
) -> pd.DataFrame:
    """ASINs ordered more than once with the gap between first and last buy."""
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            asin,
            any_value(product_name) AS product_name,
            count(*)::BIGINT AS times,
            min(order_ts_local)::DATE AS first_ordered,
            max(order_ts_local)::DATE AS last_ordered,
            date_diff('day', min(order_ts_local), max(order_ts_local))::BIGINT
                AS gap_days
        FROM amazon.order_items i
        WHERE {where} AND asin IS NOT NULL AND NOT is_cancelled
        GROUP BY asin
        HAVING count(*) >= 2
        ORDER BY times DESC, gap_days DESC
        LIMIT ?
        """,
        params + [limit],
    )


def basket_sizes(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT n_items, count(*)::BIGINT AS orders
        FROM (
            SELECT order_id, count(*)::BIGINT AS n_items
            FROM amazon.order_items i
            WHERE {where}
            GROUP BY order_id
        )
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def monthly_spend_by_currency(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            currency,
            round(sum(coalesce(line_total, 0)), 2) AS spend,
            count(*)::BIGINT AS lines
        FROM amazon.order_items i
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
          AND currency IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def cancelled_by_year(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Include cancelled regardless of include_cancelled filter (needs full view)."""
    parts: list[str] = []
    params: list[Any] = []
    yw, yp = _year_clause("i", f)
    if yw != "1=1":
        parts.append(yw)
        params.extend(yp)
    if f.marketplaces:
        placeholders = ", ".join("?" for _ in f.marketplaces)
        parts.append(f"i.marketplace IN ({placeholders})")
        params.extend(f.marketplaces)
    if f.currencies:
        placeholders = ", ".join("?" for _ in f.currencies)
        parts.append(f"i.currency IN ({placeholders})")
        params.extend(f.currencies)
    if f.dept_families:
        placeholders = ", ".join("?" for _ in f.dept_families)
        parts.append(f"i.dept_family IN ({placeholders})")
        params.extend(f.dept_families)
    where = " AND ".join(parts) if parts else "1=1"
    return _query_df(
        conn,
        f"""
        SELECT
            year,
            sum(CASE WHEN is_cancelled THEN 1 ELSE 0 END)::BIGINT AS cancelled,
            sum(CASE WHEN NOT is_cancelled THEN 1 ELSE 0 END)::BIGINT AS kept
        FROM amazon.order_items i
        WHERE {where} AND year IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def order_calendar(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            order_ts_local::DATE AS day,
            count(*)::BIGINT AS lines,
            count(DISTINCT order_id)::BIGINT AS orders
        FROM amazon.order_items i
        WHERE {where} AND order_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def aov_by_marketplace(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(marketplace, 'unknown') AS marketplace,
            currency,
            count(DISTINCT order_id)::BIGINT AS orders,
            round(sum(coalesce(line_total, 0)), 2) AS spend,
            round(sum(coalesce(line_total, 0)) / nullif(count(DISTINCT order_id), 0), 2)
                AS aov
        FROM amazon.order_items i
        WHERE {where} AND currency IS NOT NULL
        GROUP BY 1, 2
        ORDER BY spend DESC
        """,
        params,
    )


def digital_vs_retail_yearly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    retail_where, retail_params = _item_where(f)
    dy, dp = _year_clause("d", f)
    return _query_df(
        conn,
        f"""
        SELECT year, 'retail' AS surface, count(*)::BIGINT AS lines
        FROM amazon.order_items i
        WHERE {retail_where} AND year IS NOT NULL
        GROUP BY 1
        UNION ALL
        SELECT d.year, 'digital' AS surface, count(*)::BIGINT AS lines
        FROM amazon.digital_items d
        WHERE {dy} AND d.year IS NOT NULL
        GROUP BY 1
        ORDER BY 1, 2
        """,
        retail_params + dp,
    )


def search_funnel_stages(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Long form for plotly funnel charts."""
    row = search_funnel(conn, f)
    if row.empty:
        return pd.DataFrame(columns=["stage", "n"])
    r = row.iloc[0]
    return pd.DataFrame(
        {
            "stage": ["searches", "clicked", "added", "purchased"],
            "n": [
                int(r["searches"] or 0),
                int(r["clicked"] or 0),
                int(r["added"] or 0),
                int(r["purchased"] or 0),
            ],
        }
    )


def footprint_by_zip(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            zip_part,
            category,
            count(*)::BIGINT AS files,
            sum(bytes)::BIGINT AS bytes
        FROM amazon.dump_inventory
        GROUP BY 1, 2
        ORDER BY bytes DESC
        """,
    )


def spend_sunburst(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """dept_family → department rows sized by spend for sunburst."""
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            dept_family,
            coalesce(department, 'Unknown') AS department,
            round(sum(coalesce(line_total, 0)), 2) AS spend,
            count(*)::BIGINT AS lines
        FROM amazon.order_items i
        WHERE {where}
        GROUP BY 1, 2
        HAVING sum(coalesce(line_total, 0)) > 0
        ORDER BY spend DESC
        """,
        params,
    )


def impulse_index_by_family(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Split each product family into impulse (one-line) vs planned (multi-line) baskets.

    A kept basket of a single line is treated as an un-planned grab; anything with
    ≥2 kept lines is treated as a planned multi-item order. Returns long form:
    ``dept_family, basket_kind, lines, spend`` — the panel pivots to shares.
    """
    where, params = _item_where(f)
    return _query_df(
        conn,
        f"""
        WITH baskets AS (
            SELECT order_id, count(*)::BIGINT AS n_items
            FROM amazon.order_items i
            WHERE {where}
            GROUP BY order_id
        )
        SELECT
            coalesce(i.dept_family, 'other') AS dept_family,
            CASE WHEN b.n_items = 1 THEN 'impulse' ELSE 'planned' END AS basket_kind,
            count(*)::BIGINT AS lines,
            round(sum(coalesce(i.line_total, 0)), 2) AS spend
        FROM amazon.order_items i
        JOIN baskets b USING (order_id)
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def cart_vs_ordered(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 30
) -> pd.DataFrame:
    """Add-to-cart ASINs vs whether they ever converted to an order.

    ``outcome`` is ``ordered`` when the ASIN appears in kept order lines inside the
    window, else ``abandoned`` (added to cart but never bought). The panel turns the
    ASIN-level rollup into a small funnel.
    """
    cw, cp = _year_clause("c", f)
    ow, op = _item_where(f)
    return _query_df(
        conn,
        f"""
        WITH carted AS (
            SELECT
                asin,
                any_value(product_name) AS product_name,
                count(*)::BIGINT AS cart_adds
            FROM amazon.cart_events c
            WHERE {cw} AND asin IS NOT NULL
            GROUP BY asin
        ),
        ordered AS (
            SELECT asin, count(*)::BIGINT AS times
            FROM amazon.order_items i
            WHERE {ow} AND asin IS NOT NULL
            GROUP BY asin
        )
        SELECT
            c.asin,
            c.product_name,
            c.cart_adds,
            CASE WHEN o.asin IS NULL THEN 'abandoned' ELSE 'ordered' END AS outcome
        FROM carted c
        LEFT JOIN ordered o USING (asin)
        ORDER BY outcome, cart_adds DESC
        LIMIT ?
        """,
        cp + op + [limit],
    )


def returns_by_family(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Return burden (orders, lines, refund sum) attributable to each product family.

    Returns are joined to ``order_items`` via ``order_id`` so the family comes from
    the bought line, not the refund row (which may lack an ASIN).
    """
    yw, yp = _year_clause("r", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(o.dept_family, 'unknown') AS dept_family,
            count(DISTINCT r.order_id)::BIGINT AS return_orders,
            count(*)::BIGINT AS return_lines,
            round(sum(coalesce(r.refund_amount, 0)), 2) AS refund_sum
        FROM amazon.returns r
        LEFT JOIN amazon.order_items o ON o.order_id = r.order_id
        WHERE {yw}
        GROUP BY 1
        ORDER BY refund_sum DESC
        """,
        yp,
    )
