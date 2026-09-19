"""Google Takeout queries — calendar."""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps.google_queries.filters import (
    FilterState,
    _cal_where,
    _query_df,
    _year_where,
    data_bounds,
    previous_window,
)

_DURATION_CAP_SEC = 24 * 3600
_SCATTER_DURATION_CAP_SEC = 12 * 3600


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    cal_w, cal_p = _cal_where("c", f)
    y_w, y_p = _year_where("x", f)
    row = conn.execute(
        f"""
        SELECT
            (SELECT count(*)::BIGINT FROM google.calendar_events c
             WHERE {cal_w}) AS calendar_events,
            (SELECT count(*)::BIGINT FROM google.photos x
             WHERE {y_w}) AS photos,
            (SELECT count(*)::BIGINT FROM google.maps_saves x
             WHERE {y_w}) AS map_saves,
            (SELECT count(*)::BIGINT FROM google.play_installs x
             WHERE {y_w}) AS play_installs,
            (SELECT count(*)::BIGINT FROM google.activity x
             WHERE {y_w}) AS activity_events,
            (SELECT count(DISTINCT c.day)::BIGINT FROM google.calendar_events c
             WHERE {cal_w} AND c.day IS NOT NULL) AS active_calendar_days,
            (SELECT coalesce(sum(c.duration_sec), 0)::DOUBLE / 3600.0
             FROM google.calendar_events c
             WHERE {cal_w}
               AND coalesce(c.all_day, 0) = 0
               AND c.duration_sec BETWEEN 1 AND {_DURATION_CAP_SEC}
            ) AS calendar_hours,
            (SELECT count(*)::BIGINT FROM google.play_purchases x
             WHERE {y_w}) AS play_purchases,
            (SELECT count(DISTINCT x.country_code)::BIGINT FROM google.maps_saves x
             WHERE {y_w} AND x.country_code IS NOT NULL) AS map_countries,
            (SELECT count(DISTINCT x.day)::BIGINT FROM google.photos x
             WHERE {y_w} AND x.day IS NOT NULL) AS photo_days
        """,
        [*cal_p, *y_p, *y_p, *y_p, *y_p, *cal_p, *cal_p, *y_p, *y_p, *y_p],
    ).df()
    return row


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


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _cal_where("c", f)
    empty = pd.DataFrame(
        [
            {
                "longest_streak_days": 0,
                "longest_streak_events": 0,
                "busiest_day": None,
                "busiest_day_events": 0,
            }
        ]
    )
    has_days = conn.execute(
        f"""
        SELECT count(*)::BIGINT FROM google.calendar_events c
        WHERE {where} AND c.day IS NOT NULL
        """,
        params,
    ).fetchone()
    if has_days is None or has_days[0] == 0:
        return empty
    df = _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT c.day, count(*)::BIGINT AS events
            FROM google.calendar_events c
            WHERE {where} AND c.day IS NOT NULL
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
            coalesce((SELECT max(streak_days) FROM streaks), 0) AS longest_streak_days,
            coalesce((SELECT max(streak_events) FROM streaks), 0)
                AS longest_streak_events,
            (SELECT day FROM busiest) AS busiest_day,
            coalesce((SELECT events FROM busiest), 0) AS busiest_day_events
        """,
        params,
    )
    return empty if df.empty else df


def calendar_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _cal_where("c", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', c.year, c.month) AS year_month,
            count(*)::BIGINT AS events
        FROM google.calendar_events c
        WHERE {where} AND c.year IS NOT NULL AND c.month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def calendar_by_name(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    where, params = _year_where("c", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(c.calendar_name, '(unknown)') AS calendar,
            count(*)::BIGINT AS events
        FROM google.calendar_events c
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def calendar_top_summaries(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _cal_where("c", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(c.summary, '(untitled)') AS summary,
            count(*)::BIGINT AS events
        FROM google.calendar_events c
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def weekday_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _cal_where("c", f)
    return _query_df(
        conn,
        f"""
        SELECT
            isodow(c.ts_start_local)::INT AS dow,
            hour(c.ts_start_local) AS hour,
            count(*)::BIGINT AS events
        FROM google.calendar_events c
        WHERE {where}
          AND c.ts_start_local IS NOT NULL
          AND coalesce(c.all_day, 0) = 0
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _cal_where("c", f)
    return _query_df(
        conn,
        f"""
        SELECT c.day AS day, count(*)::BIGINT AS events
        FROM google.calendar_events c
        WHERE {where} AND c.day IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def surfaces_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Long-form year_month × surface event counts (noise filter on calendar only)."""
    cal_w, cal_p = _cal_where("c", f)
    y_w, y_p = _year_where("x", f)
    return _query_df(
        conn,
        f"""
        SELECT year_month, surface, events FROM (
            SELECT
                printf('%04d-%02d', c.year, c.month) AS year_month,
                'calendar_events' AS surface,
                count(*)::BIGINT AS events
            FROM google.calendar_events c
            WHERE {cal_w} AND c.year IS NOT NULL AND c.month IS NOT NULL
            GROUP BY 1

            UNION ALL

            SELECT
                printf('%04d-%02d', x.year, x.month),
                'photos',
                count(*)::BIGINT
            FROM google.photos x
            WHERE {y_w} AND x.year IS NOT NULL AND x.month IS NOT NULL
            GROUP BY 1

            UNION ALL

            SELECT
                printf('%04d-%02d', x.year, x.month),
                'maps_saves',
                count(*)::BIGINT
            FROM google.maps_saves x
            WHERE {y_w} AND x.year IS NOT NULL AND x.month IS NOT NULL
            GROUP BY 1

            UNION ALL

            SELECT
                printf('%04d-%02d', x.year, x.month),
                'play_installs',
                count(*)::BIGINT
            FROM google.play_installs x
            WHERE {y_w} AND x.year IS NOT NULL AND x.month IS NOT NULL
            GROUP BY 1

            UNION ALL

            SELECT
                printf('%04d-%02d', x.year, x.month),
                'activity',
                count(*)::BIGINT
            FROM google.activity x
            WHERE {y_w} AND x.year IS NOT NULL AND x.month IS NOT NULL
            GROUP BY 1
        )
        ORDER BY year_month, surface
        """,
        [*cal_p, *y_p, *y_p, *y_p, *y_p],
    )


def calendar_hours_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _cal_where("c", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', c.year, c.month) AS year_month,
            (sum(c.duration_sec)::DOUBLE / 3600.0) AS hours
        FROM google.calendar_events c
        WHERE {where}
          AND c.year IS NOT NULL AND c.month IS NOT NULL
          AND coalesce(c.all_day, 0) = 0
          AND c.duration_sec BETWEEN 1 AND {_DURATION_CAP_SEC}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def duration_vs_hour_scatter(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 2000
) -> pd.DataFrame:
    where, params = _cal_where("c", f)
    return _query_df(
        conn,
        f"""
        SELECT
            hour(c.ts_start_local) AS hour,
            (c.duration_sec::DOUBLE / 3600.0) AS duration_hours,
            c.calendar_name,
            c.summary
        FROM google.calendar_events c
        WHERE {where}
          AND c.ts_start_local IS NOT NULL
          AND coalesce(c.all_day, 0) = 0
          AND c.duration_sec BETWEEN 1 AND {_SCATTER_DURATION_CAP_SEC}
        ORDER BY c.ts_start_local DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def summary_rank_bump(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, top_n: int = 8
) -> pd.DataFrame:
    where, params = _cal_where("c", f)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT
                c.year,
                coalesce(c.summary, '(untitled)') AS summary,
                count(*)::BIGINT AS events
            FROM google.calendar_events c
            WHERE {where} AND c.year IS NOT NULL
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT
                year,
                summary,
                events,
                rank() OVER (PARTITION BY year ORDER BY events DESC) AS rnk
            FROM yearly
        )
        SELECT year, summary, events, rnk
        FROM ranked
        WHERE rnk <= ?
        ORDER BY year, rnk
        """,
        [*params, top_n],
    )


def calendar_stacked_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit_calendars: int = 6
) -> pd.DataFrame:
    where, params = _cal_where("c", f)
    return _query_df(
        conn,
        f"""
        WITH monthly AS (
            SELECT
                printf('%04d-%02d', c.year, c.month) AS year_month,
                coalesce(c.calendar_name, '(unknown)') AS calendar,
                count(*)::BIGINT AS events
            FROM google.calendar_events c
            WHERE {where} AND c.year IS NOT NULL AND c.month IS NOT NULL
            GROUP BY 1, 2
        ),
        top AS (
            SELECT calendar
            FROM (
                SELECT calendar, sum(events) AS n
                FROM monthly
                GROUP BY 1
                ORDER BY n DESC
                LIMIT ?
            )
        )
        SELECT
            year_month,
            CASE WHEN calendar IN (SELECT calendar FROM top) THEN calendar
                 ELSE 'Other' END AS calendar,
            sum(events)::BIGINT AS events
        FROM monthly
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        [*params, limit_calendars],
    )


def calendar_kind_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _cal_where("e", f)
    return _query_df(
        conn,
        f"""
        SELECT
            CASE WHEN e.all_day = 1 THEN 'all-day' ELSE 'timed' END AS kind,
            count(*)::BIGINT AS events
        FROM google.calendar_events e
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        """,
        params,
    )


# --- Compare / correlate loaders --------------------------------------------


def calendar_events_monthly_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    return calendar_monthly(conn, f)


def calendar_events_daily_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    df = calendar_daily(conn, f)
    if df.empty:
        return df
    return df.rename(columns={"day": "day", "events": "events"})


def calendar_name_options(conn: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    rows = conn.execute("""
        SELECT calendar_name, count(*) AS n
        FROM google.calendar_events
        WHERE calendar_name IS NOT NULL
        GROUP BY 1
        ORDER BY n DESC
        LIMIT 40
        """).fetchall()
    return [{"value": r[0], "label": f"{r[0]} ({r[1]})"} for r in rows]


def calendar_for_name_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end, calendar=entity)
    return calendar_monthly(conn, f)
