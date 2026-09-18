"""Filter state and DuckDB queries for the Airbnb explorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    role: str | None = None  # guest | host | other
    status: str | None = None
    place: str | None = None  # search place lock (city or country label)

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        if self.role:
            chips.append(("role", f"role: {self.role}"))
        if self.status:
            chips.append(("status", f"status: {self.status}"))
        if self.place:
            chips.append(("place", f"place: {self.place}"))
        return chips


def _place_expr(alias: str) -> str:
    p = f"{alias}." if alias else ""
    return f"coalesce(nullif({p}city, ''), {p}country)"


def _res_where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    p = f"{alias}." if alias else ""
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
    if f.role:
        clauses.append(f"{p}role = ?")
        params.append(f.role)
    if f.status:
        clauses.append(f"{p}status = ?")
        params.append(f.status)
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _search_where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    p = f"{alias}." if alias else ""
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
    if f.place:
        clauses.append(f"{_place_expr(alias)} = ?")
        params.append(f.place)
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
            min(day)::DATE, max(day)::DATE
        FROM (
            SELECT year, start_date AS day FROM airbnb.reservations
            WHERE start_date IS NOT NULL
            UNION ALL
            SELECT year, cast(ts_local AS DATE) FROM airbnb.searches
            WHERE ts_local IS NOT NULL
        )
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2014, 2014
    roles = [r[0] for r in conn.execute("""
            SELECT role FROM airbnb.reservations
            WHERE role IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """).fetchall() if r[0]]
    statuses = [r[0] for r in conn.execute("""
            SELECT status FROM airbnb.reservations
            WHERE status IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """).fetchall() if r[0]]
    places = [r[0] for r in conn.execute(f"""
            SELECT {_place_expr("s")} AS place, count(*) AS n
            FROM airbnb.searches s
            WHERE {_place_expr("s")} IS NOT NULL
            GROUP BY 1
            ORDER BY n DESC, place
            LIMIT 40
            """).fetchall() if r[0]]
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "roles": roles,
        "statuses": statuses,
        "places": places,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int | None,
    year_end: int | None,
    role: str | None = None,
    status: str | None = None,
    place: str | None = None,
) -> FilterState:
    ys = year_start if year_start is not None else bounds.get("min_year")
    ye = year_end if year_end is not None else bounds.get("max_year")
    role_v = None if not role or role == "(all)" else role
    status_v = None if not status or status == "(all)" else status
    place_v = None if not place or place == "(all)" else place
    return FilterState(
        year_start=ys,
        year_end=ye,
        role=role_v,
        status=status_v,
        place=place_v,
    )


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare_previous: bool = False,
) -> pd.DataFrame:
    where, params = _res_where("r", f)
    sw, sp = _search_where("s", f)
    current = _query_df(
        conn,
        f"""
        SELECT
            (SELECT count(*)::BIGINT FROM airbnb.reservations r WHERE {where}) AS reservations,
            (SELECT count(*)::BIGINT FROM airbnb.reservations r
             WHERE {where} AND r.status = 'accepted') AS accepted,
            (SELECT coalesce(sum(r.nights), 0)::BIGINT FROM airbnb.reservations r
             WHERE {where} AND r.status = 'accepted') AS nights,
            (SELECT count(*)::BIGINT FROM airbnb.reservations r
             WHERE {where} AND r.role = 'guest' AND r.status = 'accepted') AS guest_stays,
            (SELECT count(*)::BIGINT FROM airbnb.reservations r
             WHERE {where} AND r.role = 'host' AND r.status = 'accepted') AS host_bookings,
            (SELECT count(*)::BIGINT FROM airbnb.searches s WHERE {sw}) AS searches,
            (SELECT count(DISTINCT {_place_expr("s")})::BIGINT
             FROM airbnb.searches s
             WHERE {sw} AND {_place_expr("s")} IS NOT NULL) AS search_places
        """,
        [*params, *params, *params, *params, *params, *sp, *sp],
    )
    if not compare_previous or f.year_start is None or f.year_end is None:
        return current
    span = f.year_end - f.year_start
    prev = FilterState(
        year_start=f.year_start - span - 1,
        year_end=f.year_start - 1,
        role=f.role,
        status=f.status,
        place=f.place,
    )
    prev_df = scoreboard(conn, prev, compare_previous=False)
    out = current.copy()
    for col in current.columns:
        if col not in prev_df.columns:
            continue
        cur_v = current.iloc[0][col]
        prev_v = prev_df.iloc[0][col]
        out[f"{col}_prev"] = prev_v
        try:
            if prev_v and float(prev_v) != 0:
                out[f"{col}_delta_pct"] = round(
                    100.0 * (float(cur_v) - float(prev_v)) / float(prev_v), 1
                )
        except (TypeError, ValueError):
            pass
    return out


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        WITH days AS (
            SELECT DISTINCT start_date AS day
            FROM airbnb.reservations r
            WHERE {where} AND r.status = 'accepted' AND r.start_date IS NOT NULL
        ),
        ordered AS (
            SELECT day, day - INTERVAL (row_number() OVER (ORDER BY day)) DAY AS grp
            FROM days
        ),
        streaks AS (
            SELECT count(*)::INT AS streak_days, min(day) AS streak_start, max(day) AS streak_end
            FROM ordered GROUP BY grp
        )
        SELECT
            coalesce((SELECT max(streak_days) FROM streaks), 0) AS longest_streak_trips,
            (SELECT streak_start FROM streaks ORDER BY streak_days DESC LIMIT 1)
                AS longest_streak_start,
            (SELECT streak_end FROM streaks ORDER BY streak_days DESC LIMIT 1)
                AS longest_streak_end,
            (SELECT count(*) FROM days) AS active_trip_days
        """,
        params,
    )


def reservations_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS reservations,
            count(*) FILTER (WHERE status = 'accepted')::BIGINT AS accepted,
            coalesce(sum(nights) FILTER (WHERE status = 'accepted'), 0)::BIGINT AS nights
        FROM airbnb.reservations r
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def status_breakdown(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        SELECT status, count(*)::BIGINT AS reservations
        FROM airbnb.reservations r
        WHERE {where} AND status IS NOT NULL
        GROUP BY 1 ORDER BY reservations DESC
        """,
        params,
    )


def role_breakdown(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        SELECT role, count(*)::BIGINT AS reservations,
               coalesce(sum(nights) FILTER (WHERE status = 'accepted'), 0)::BIGINT AS nights
        FROM airbnb.reservations r
        WHERE {where} AND role IS NOT NULL
        GROUP BY 1 ORDER BY reservations DESC
        """,
        params,
    )


def nights_by_country(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Guest stays by host VAT country (coarse stay geography)."""
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        SELECT
            host_vat_country AS country,
            count(*)::BIGINT AS stays,
            coalesce(sum(nights), 0)::BIGINT AS nights
        FROM airbnb.reservations r
        WHERE {where}
          AND role = 'guest'
          AND status = 'accepted'
          AND host_vat_country IS NOT NULL
        GROUP BY 1
        ORDER BY nights DESC, stays DESC
        """,
        params,
    )


def recent_stays(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        SELECT
            confirmation_code,
            role,
            status,
            start_date,
            nights,
            guests,
            host_vat_country AS country,
            listing_id
        FROM airbnb.reservations r
        WHERE {where}
        ORDER BY start_date DESC NULLS LAST, created_at_utc DESC NULLS LAST
        LIMIT ?
        """,
        [*params, limit],
    )


def calendar_daily_starts(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        SELECT start_date AS day, count(*)::BIGINT AS events
        FROM airbnb.reservations r
        WHERE {where} AND start_date IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """,
        params,
    )


def weekday_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Guest/host reservation *creation* rhythm (created_at_local hour)."""
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        SELECT
            isodow(created_at_local)::INT AS dow,
            hour(created_at_local)::INT AS hour,
            count(*)::BIGINT AS events
        FROM airbnb.reservations r
        WHERE {where} AND created_at_local IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def searches_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _search_where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS searches
        FROM airbnb.searches s
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """,
        params,
    )


def searches_by_place(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 30
) -> pd.DataFrame:
    where, params = _search_where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(nullif(city, ''), country, '(unknown)') AS place,
            avg(search_lat) AS lat,
            avg(search_lon) AS lon,
            count(*)::BIGINT AS searches,
            count(DISTINCT country)::BIGINT AS countries
        FROM airbnb.searches s
        WHERE {where}
          AND (search_lat IS NOT NULL OR city IS NOT NULL OR country IS NOT NULL)
        GROUP BY 1
        ORDER BY searches DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def search_map_points(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Aggregated search pins for the geo bubble map (uses export lat/lon)."""
    where, params = _search_where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(nullif(city, ''), country, 'search') AS place,
            round(search_lat, 3) AS lat,
            round(search_lon, 3) AS lon,
            count(*)::BIGINT AS searches
        FROM airbnb.searches s
        WHERE {where}
          AND search_lat IS NOT NULL
          AND search_lon IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY searches DESC
        """,
        params,
    )


def forgotten_search_places(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, silent_years: int = 2
) -> pd.DataFrame:
    where, params = _search_where("s", f)
    return _query_df(
        conn,
        f"""
        WITH places AS (
            SELECT
                {_place_expr("s")} AS place,
                min(cast(ts_local AS DATE)) AS first_day,
                max(cast(ts_local AS DATE)) AS last_day,
                count(*)::BIGINT AS searches
            FROM airbnb.searches s
            WHERE {where}
              AND {_place_expr("s")} IS NOT NULL
            GROUP BY 1
        )
        SELECT place, first_day, last_day, searches,
               date_diff('year', last_day, current_date)::INT AS silent_years
        FROM places
        WHERE date_diff('year', last_day, current_date) >= ?
        ORDER BY silent_years DESC, searches DESC
        LIMIT 25
        """,
        [*params, silent_years],
    )


def comeback_search_places(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, gap_years: int = 2
) -> pd.DataFrame:
    where, params = _search_where("s", f)
    return _query_df(
        conn,
        f"""
        WITH days AS (
            SELECT
                {_place_expr("s")} AS place,
                cast(ts_local AS DATE) AS day
            FROM airbnb.searches s
            WHERE {where}
              AND {_place_expr("s")} IS NOT NULL
              AND ts_local IS NOT NULL
        ),
        gaps AS (
            SELECT place, day,
                   lag(day) OVER (PARTITION BY place ORDER BY day) AS prev_day
            FROM days
        )
        SELECT place, prev_day AS silent_from, day AS returned_on,
               date_diff('day', prev_day, day)::INT AS gap_days
        FROM gaps
        WHERE prev_day IS NOT NULL
          AND date_diff('year', prev_day, day) >= ?
        ORDER BY gap_days DESC
        LIMIT 25
        """,
        [*params, gap_years],
    )


def place_rank_bump(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, top_n: int = 8
) -> pd.DataFrame:
    where, params = _search_where("s", f)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT
                year,
                {_place_expr("s")} AS place,
                count(*)::BIGINT AS searches
            FROM airbnb.searches s
            WHERE {where}
              AND year IS NOT NULL
              AND {_place_expr("s")} IS NOT NULL
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT year, place, searches,
                   row_number() OVER (PARTITION BY year ORDER BY searches DESC) AS rank
            FROM yearly
        ),
        keep AS (
            SELECT place FROM ranked WHERE rank <= ? GROUP BY 1
        )
        SELECT r.year, r.place, r.searches, r.rank
        FROM ranked r
        INNER JOIN keep k ON k.place = r.place
        WHERE r.rank <= ?
        ORDER BY r.year, r.rank
        """,
        [*params, top_n, top_n],
    )


def reviews_summary(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    clauses: list[str] = []
    params: list[Any] = []
    if f.year_start is not None:
        clauses.append("year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append("year <= ?")
        params.append(f.year_end)
    where = " AND ".join(clauses) if clauses else "1=1"
    return _query_df(
        conn,
        f"""
        SELECT
            direction,
            count(*)::BIGINT AS reviews,
            round(avg(rating), 2) AS avg_rating,
            count(*) FILTER (WHERE rating = 5)::BIGINT AS five_stars
        FROM airbnb.reviews
        WHERE {where}
        GROUP BY 1
        ORDER BY direction
        """,
        params,
    )


def reviews_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    clauses: list[str] = []
    params: list[Any] = []
    if f.year_start is not None:
        clauses.append("year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append("year <= ?")
        params.append(f.year_end)
    where = " AND ".join(clauses) if clauses else "1=1"
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS reviews,
            round(avg(rating), 2) AS avg_rating
        FROM airbnb.reviews
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def wishlist_summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            coalesce(nullif(wishlist_name, ''), wishlist_id) AS wishlist,
            count(*) FILTER (WHERE listing_id IS NOT NULL AND listing_id != '')::BIGINT
                AS listings
        FROM airbnb.wishlists
        GROUP BY 1
        ORDER BY listings DESC, wishlist
        """,
    )


def reservations_monthly_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    return reservations_monthly(conn, f)[["year_month", "reservations"]]


def reservations_daily_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        SELECT start_date AS day, count(*)::BIGINT AS reservations
        FROM airbnb.reservations r
        WHERE {where} AND start_date IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """,
        params,
    )


def nights_monthly_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end, status="accepted")
    return reservations_monthly(conn, f)[["year_month", "nights"]]


def nights_daily_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end, status="accepted")
    where, params = _res_where("r", f)
    return _query_df(
        conn,
        f"""
        SELECT start_date AS day, coalesce(sum(nights), 0)::BIGINT AS nights
        FROM airbnb.reservations r
        WHERE {where} AND start_date IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """,
        params,
    )


def searches_monthly_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    return searches_monthly(conn, f)


def searches_daily_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _search_where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT cast(ts_local AS DATE) AS day, count(*)::BIGINT AS searches
        FROM airbnb.searches s
        WHERE {where} AND ts_local IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """,
        params,
    )


def place_options(conn: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    rows = conn.execute(f"""
        SELECT {_place_expr("s")} AS place, count(*)::BIGINT AS n
        FROM airbnb.searches s
        WHERE {_place_expr("s")} IS NOT NULL
        GROUP BY 1
        ORDER BY n DESC, place
        LIMIT 40
        """).fetchall()
    return [{"value": r[0], "label": f"{r[0]} ({r[1]})"} for r in rows if r[0]]


def searches_monthly_for_place(
    conn: duckdb.DuckDBPyConnection, f: FilterState, place: str
) -> pd.DataFrame:
    locked = FilterState(year_start=f.year_start, year_end=f.year_end, place=place)
    return searches_monthly(conn, locked)[["year_month", "searches"]]
