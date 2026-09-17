"""Filter state and DuckDB queries for the Uber explorer."""

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
    city: str | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        if self.city:
            chips.append(("city", f"city: {self.city}"))
        return chips


def _trip_where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    p = f"{alias}." if alias else ""
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
    if f.city:
        clauses.append(f"{p}city_name = ?")
        params.append(f.city)
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _order_where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    return _trip_where(alias, f)


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
            SELECT year, cast(request_ts_local AS DATE) AS day
            FROM uber.trips
            WHERE request_ts_local IS NOT NULL
            UNION ALL
            SELECT year, cast(request_ts_local AS DATE) AS day
            FROM uber.order_items
            WHERE request_ts_local IS NOT NULL
        )
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2014, 2014
    cities = [r[0] for r in conn.execute("""
            SELECT city_name FROM (
                SELECT city_name, count(*) AS n FROM uber.trips
                WHERE city_name IS NOT NULL GROUP BY 1
                UNION ALL
                SELECT city_name, count(*) FROM uber.order_items
                WHERE city_name IS NOT NULL GROUP BY 1
            )
            GROUP BY 1
            ORDER BY sum(n) DESC, city_name
            """).fetchall() if r[0]]
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "cities": cities,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    city: str | None = None,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    city_lock = city if city and city != "(all)" else None
    return FilterState(year_start=ys, year_end=ye, city=city_lock)


def previous_window(f: FilterState) -> FilterState | None:
    bounds = query_util.previous_year_bounds(f.year_start, f.year_end)
    if bounds is None:
        return None
    return FilterState(year_start=bounds[0], year_end=bounds[1], city=f.city)


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    t_where, t_params = _trip_where("t", f)
    o_where, o_params = _order_where("o", f)
    return _query_df(
        conn,
        f"""
        SELECT
            (
                SELECT count(*)::BIGINT FROM uber.trips t WHERE {t_where}
            ) AS trips,
            (
                SELECT count(*)::BIGINT FROM uber.trips t
                WHERE {t_where} AND coalesce(t.is_completed, false)
            ) AS completed_trips,
            (
                SELECT coalesce(round(sum(t.fare_usd), 2), 0)
                FROM uber.trips t
                WHERE {t_where} AND coalesce(t.is_completed, false)
            ) AS trip_fare_usd,
            (
                SELECT coalesce(round(sum(t.trip_distance_miles), 1), 0)
                FROM uber.trips t
                WHERE {t_where} AND coalesce(t.is_completed, false)
            ) AS miles,
            (
                SELECT count(DISTINCT o.order_key)::BIGINT
                FROM uber.order_items o WHERE {o_where}
            ) AS eats_orders,
            (
                SELECT coalesce(round(sum(order_total), 2), 0) FROM (
                    SELECT o.order_key, max(o.order_price_local) AS order_total
                    FROM uber.order_items o
                    WHERE {o_where}
                    GROUP BY 1
                )
            ) AS eats_spend_local_sum
        """,
        t_params + t_params + t_params + t_params + o_params + o_params,
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


def trips_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', t.year, t.month) AS year_month,
            count(*)::BIGINT AS trips,
            count(*) FILTER (WHERE coalesce(t.is_completed, false))::BIGINT
                AS completed,
            coalesce(round(sum(t.fare_usd) FILTER (
                WHERE coalesce(t.is_completed, false)
            ), 2), 0) AS fare_usd
        FROM uber.trips t
        WHERE {where} AND t.year IS NOT NULL AND t.month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def trips_by_city(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(t.city_name, '(unknown)') AS city,
            count(*)::BIGINT AS trips,
            count(*) FILTER (WHERE coalesce(t.is_completed, false))::BIGINT
                AS completed,
            coalesce(round(sum(t.fare_usd) FILTER (
                WHERE coalesce(t.is_completed, false)
            ), 2), 0) AS fare_usd
        FROM uber.trips t
        WHERE {where}
        GROUP BY 1
        ORDER BY trips DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def trips_by_product(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 15
) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(t.global_product, t.product_type, '(unknown)') AS product,
            count(*)::BIGINT AS trips,
            coalesce(round(sum(t.fare_usd) FILTER (
                WHERE coalesce(t.is_completed, false)
            ), 2), 0) AS fare_usd
        FROM uber.trips t
        WHERE {where}
        GROUP BY 1
        ORDER BY trips DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def status_breakdown(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        SELECT coalesce(t.status, '(unknown)') AS status, count(*)::BIGINT AS trips
        FROM uber.trips t
        WHERE {where}
        GROUP BY 1
        ORDER BY trips DESC
        """,
        params,
    )


def weekday_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """ISO weekday (1=Mon … 7=Sun) × hour local for trips."""
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        SELECT t.weekday::INT AS dow, t.hour, count(*)::BIGINT AS events
        FROM uber.trips t
        WHERE {where} AND t.weekday IS NOT NULL AND t.hour IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def calendar_daily_trips(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        SELECT
            cast(t.request_ts_local AS DATE) AS day,
            count(*)::BIGINT AS events
        FROM uber.trips t
        WHERE {where} AND t.request_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT cast(t.request_ts_local AS DATE) AS day, count(*)::BIGINT AS events
            FROM uber.trips t
            WHERE {where} AND t.request_ts_local IS NOT NULL
            GROUP BY 1
        ),
        ranked AS (
            SELECT
                day,
                events,
                day - (row_number() OVER (ORDER BY day))::INT AS grp
            FROM daily
        ),
        streaks AS (
            SELECT grp, count(*) AS streak_days, sum(events) AS streak_events
            FROM ranked
            GROUP BY grp
        ),
        busiest AS (
            SELECT day, events FROM daily ORDER BY events DESC LIMIT 1
        )
        SELECT
            (SELECT max(streak_days) FROM streaks) AS longest_streak_days,
            (SELECT max(streak_events) FROM streaks) AS longest_streak_events,
            (SELECT day FROM busiest) AS busiest_day,
            (SELECT events FROM busiest) AS busiest_day_events
        """,
        params,
    )


def forgotten_cities(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_trips: int = 3,
    silent_years: int = 2,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        WITH city_span AS (
            SELECT
                coalesce(t.city_name, '(unknown)') AS city,
                count(*)::BIGINT AS trips,
                max(t.request_ts_utc) AS last_ts
            FROM uber.trips t
            WHERE {where}
            GROUP BY 1
            HAVING count(*) >= ?
        )
        SELECT city, trips, last_ts::DATE AS last_day
        FROM city_span
        WHERE last_ts < current_timestamp - (? * INTERVAL '1 year')
        ORDER BY trips DESC
        LIMIT ?
        """,
        [*params, min_trips, silent_years, limit],
    )


def comeback_cities(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 2,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        WITH filtered AS (
            SELECT
                coalesce(t.city_name, '(unknown)') AS city,
                t.request_ts_utc AS ts_utc
            FROM uber.trips t
            WHERE {where} AND t.request_ts_utc IS NOT NULL
        ),
        city_span AS (
            SELECT
                city,
                min(ts_utc) AS first_in_window,
                max(ts_utc) AS last_in_window,
                count(*)::BIGINT AS window_trips
            FROM filtered
            GROUP BY 1
        ),
        prior AS (
            SELECT
                coalesce(t.city_name, '(unknown)') AS city,
                max(t.request_ts_utc) AS last_before
            FROM uber.trips t
            INNER JOIN city_span a
                ON coalesce(t.city_name, '(unknown)') = a.city
            WHERE t.request_ts_utc < a.first_in_window
            GROUP BY 1
        )
        SELECT
            a.city,
            a.window_trips,
            p.last_before::DATE AS last_before,
            a.first_in_window::DATE AS returned_on
        FROM city_span a
        INNER JOIN prior p ON a.city = p.city
        WHERE p.last_before < a.first_in_window - (? * INTERVAL '1 year')
        ORDER BY a.window_trips DESC
        LIMIT ?
        """,
        [*params, silent_years, limit],
    )


def city_rank_bump(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    top_n: int = 8,
) -> pd.DataFrame:
    """Yearly city rank movement for bump chart."""
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT
                t.year,
                coalesce(t.city_name, '(unknown)') AS city,
                count(*)::BIGINT AS trips
            FROM uber.trips t
            WHERE {where} AND t.year IS NOT NULL
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT
                year,
                city,
                trips,
                row_number() OVER (PARTITION BY year ORDER BY trips DESC, city) AS rank
            FROM yearly
        ),
        keep AS (
            SELECT city FROM ranked WHERE rank <= ? GROUP BY 1
        )
        SELECT r.year, r.city, r.trips, r.rank
        FROM ranked r
        INNER JOIN keep k ON r.city = k.city
        ORDER BY r.year, r.rank
        """,
        [*params, top_n],
    )


def fare_vs_distance_scatter(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 500
) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        SELECT
            t.trip_distance_miles AS miles,
            t.fare_usd,
            coalesce(t.city_name, '(unknown)') AS city,
            coalesce(t.global_product, t.product_type, '(unknown)') AS product,
            t.request_ts_local
        FROM uber.trips t
        WHERE {where}
          AND coalesce(t.is_completed, false)
          AND t.trip_distance_miles IS NOT NULL
          AND t.fare_usd IS NOT NULL
          AND t.trip_distance_miles > 0
          AND t.fare_usd > 0
        ORDER BY t.request_ts_utc DESC NULLS LAST
        LIMIT ?
        """,
        [*params, limit],
    )


def eats_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _order_where("o", f)
    return _query_df(
        conn,
        f"""
        WITH orders AS (
            SELECT
                o.order_key,
                o.year,
                o.month,
                max(o.order_price_local) AS order_total,
                max(o.currency) AS currency
            FROM uber.order_items o
            WHERE {where} AND o.year IS NOT NULL AND o.month IS NOT NULL
            GROUP BY 1, 2, 3
        )
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS orders,
            round(sum(order_total), 2) AS spend_local_sum
        FROM orders
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def eats_by_restaurant(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    where, params = _order_where("o", f)
    return _query_df(
        conn,
        f"""
        WITH orders AS (
            SELECT
                o.order_key,
                max(o.restaurant_name) AS restaurant,
                max(o.city_name) AS city,
                max(o.order_price_local) AS order_total
            FROM uber.order_items o
            WHERE {where}
            GROUP BY 1
        )
        SELECT
            coalesce(restaurant, '(unknown)') AS restaurant,
            coalesce(city, '(unknown)') AS city,
            count(*)::BIGINT AS orders,
            round(sum(order_total), 2) AS spend_local_sum
        FROM orders
        GROUP BY 1, 2
        ORDER BY orders DESC, spend_local_sum DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def ratings_summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            count(*)::BIGINT AS n_ratings,
            round(avg(stars), 2) AS avg_stars,
            count(*) FILTER (WHERE stars = 5)::BIGINT AS five_star,
            count(*) FILTER (WHERE stars <= 3)::BIGINT AS three_or_below
        FROM uber.ratings
        """,
    )


def support_summary(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _trip_where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS messages,
            count(DISTINCT cast(ts_local AS DATE))::BIGINT AS days,
            min(ts_local) AS first_ts,
            max(ts_local) AS last_ts
        FROM uber.support_messages s
        WHERE {where}
        """,
        params,
    )


# --- Compare / Correlations helpers ---


def trips_monthly_total(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    return trips_monthly(conn, f)[["year_month", "trips"]].rename(
        columns={"trips": "trips"}
    )


def trips_daily_total(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _trip_where("t", f)
    return _query_df(
        conn,
        f"""
        SELECT cast(t.request_ts_local AS DATE) AS day, count(*)::BIGINT AS trips
        FROM uber.trips t
        WHERE {where} AND t.request_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def eats_orders_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    return eats_monthly(conn, f)[["year_month", "orders"]]


def eats_orders_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _order_where("o", f)
    return _query_df(
        conn,
        f"""
        SELECT
            cast(o.request_ts_local AS DATE) AS day,
            count(DISTINCT o.order_key)::BIGINT AS orders
        FROM uber.order_items o
        WHERE {where} AND o.request_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def city_options(conn: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    rows = conn.execute("""
        SELECT city_name, count(*)::BIGINT AS n
        FROM uber.trips
        WHERE city_name IS NOT NULL
        GROUP BY 1
        ORDER BY n DESC, city_name
        LIMIT 40
        """).fetchall()
    return [{"value": r[0], "label": f"{r[0]} ({r[1]})"} for r in rows]


def trips_monthly_for_city(
    conn: duckdb.DuckDBPyConnection, f: FilterState, city: str
) -> pd.DataFrame:
    locked = FilterState(year_start=f.year_start, year_end=f.year_end, city=city)
    return trips_monthly(conn, locked)[["year_month", "trips"]]
