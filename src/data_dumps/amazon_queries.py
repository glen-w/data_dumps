"""Filter state and DuckDB queries for the Amazon Marimo dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    marketplaces: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    dept_families: list[str] = field(default_factory=list)
    include_cancelled: bool = False

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        if self.marketplaces:
            chips.append(("marketplaces", "mkts " + ",".join(self.marketplaces)))
        if self.currencies:
            chips.append(("currencies", "fx " + ",".join(self.currencies)))
        if self.dept_families:
            chips.append(("dept_families", "types " + ",".join(self.dept_families)))
        if self.include_cancelled:
            chips.append(("cancelled", "incl. cancelled"))
        return chips


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    marketplaces: list[str] | None = None,
    currencies: list[str] | None = None,
    dept_families: list[str] | None = None,
    include_cancelled: bool = False,
) -> FilterState:
    return FilterState(
        year_start=year_start,
        year_end=year_end,
        marketplaces=list(marketplaces or []),
        currencies=list(currencies or []),
        dept_families=list(dept_families or []),
        include_cancelled=include_cancelled,
    )


def _year_clause(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    prefix = f"{alias}." if alias else ""
    if f.year_start is not None:
        clauses.append(f"{prefix}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{prefix}year <= ?")
        params.append(f.year_end)
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _item_where(f: FilterState, alias: str = "i") -> tuple[str, list[Any]]:
    parts: list[str] = []
    params: list[Any] = []
    yw, yp = _year_clause(alias, f)
    if yw != "1=1":
        parts.append(yw)
        params.extend(yp)
    if not f.include_cancelled:
        parts.append(f"NOT {alias}.is_cancelled")
    if f.marketplaces:
        placeholders = ", ".join("?" for _ in f.marketplaces)
        parts.append(f"{alias}.marketplace IN ({placeholders})")
        params.extend(f.marketplaces)
    if f.currencies:
        placeholders = ", ".join("?" for _ in f.currencies)
        parts.append(f"{alias}.currency IN ({placeholders})")
        params.extend(f.currencies)
    if f.dept_families:
        placeholders = ", ".join("?" for _ in f.dept_families)
        parts.append(f"{alias}.dept_family IN ({placeholders})")
        params.extend(f.dept_families)
    where = " AND ".join(parts) if parts else "1=1"
    return where, params


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def has_table(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = conn.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'amazon' AND table_name = ?
        """,
        [table],
    ).fetchone()
    return row is not None and row[0] > 0


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            min(year)::INT,
            max(year)::INT,
            min(order_ts_local)::DATE,
            max(order_ts_local)::DATE
        FROM amazon.order_items
        WHERE year IS NOT NULL
        """
    ).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        # Fall back to alexa intents
        row2 = conn.execute(
            """
            SELECT min(year)::INT, max(year)::INT
            FROM amazon.alexa_intents WHERE year IS NOT NULL
            """
        ).fetchone()
        if row2 and row2[0] is not None:
            min_year, max_year = row2[0], row2[1]
        else:
            min_year, max_year = 2015, 2026
    marketplaces = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT marketplace FROM amazon.order_items
            WHERE marketplace IS NOT NULL ORDER BY 1
            """
        ).fetchall()
    ]
    currencies = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT currency FROM amazon.order_items
            WHERE currency IS NOT NULL ORDER BY 1
            """
        ).fetchall()
    ]
    families = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT dept_family FROM amazon.order_items
            WHERE dept_family IS NOT NULL ORDER BY 1
            """
        ).fetchall()
    ]
    return {
        "min_year": int(min_year),
        "max_year": int(max_year),
        "first_day": row[2],
        "last_day": row[3],
        "marketplaces": marketplaces,
        "currencies": currencies,
        "dept_families": families,
    }


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


def top_products(conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 25) -> pd.DataFrame:
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


def alexa_scoreboard(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS utterances,
            count(DISTINCT utterance_tag)::BIGINT AS tags,
            min(intent_ts_local)::TIMESTAMP AS first_ts,
            max(intent_ts_local)::TIMESTAMP AS last_ts
        FROM amazon.alexa_intents a
        WHERE {where}
        """,
        params,
    )


def alexa_tags(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT utterance_tag AS tag, count(*)::BIGINT AS n
        FROM amazon.alexa_intents a
        WHERE {where}
        GROUP BY 1
        ORDER BY n DESC
        """,
        params,
    )


def alexa_circadian(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT dow, hour, count(*)::BIGINT AS events
        FROM amazon.alexa_intents a
        WHERE {where} AND dow IS NOT NULL AND hour IS NOT NULL
        GROUP BY 1, 2
        """,
        params,
    )


def alexa_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            count(*)::BIGINT AS utterances
        FROM amazon.alexa_intents a
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def alexa_devices(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("s", f)
    return _query_df(
        conn,
        f"""
        SELECT coalesce(device_type, 'unknown') AS device_type, count(*)::BIGINT AS events
        FROM amazon.alexa_sessions s
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        """,
        params,
    )


def alexa_show_engagement(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            sum(voice_count)::BIGINT AS voice,
            sum(touch_count)::BIGINT AS touch,
            sum(impression_count)::BIGINT AS impressions
        FROM amazon.alexa_show_daily s
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def alexa_skills(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT skill_name, stage, status, enabled_ts_utc
        FROM amazon.alexa_skills
        ORDER BY enabled_ts_utc DESC NULLS LAST
        LIMIT 50
        """,
    )


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


def alexa_tag_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            utterance_tag AS tag,
            count(*)::BIGINT AS n
        FROM amazon.alexa_intents a
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def alexa_top_utterances(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 25
) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT utterance, utterance_tag AS tag, count(*)::BIGINT AS n
        FROM amazon.alexa_intents a
        WHERE {where} AND utterance IS NOT NULL AND length(utterance) > 2
        GROUP BY 1, 2
        ORDER BY n DESC
        LIMIT ?
        """,
        params + [limit],
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


def rufus_top(conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 20) -> pd.DataFrame:
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
