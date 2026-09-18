"""Filter state and DuckDB queries for the Google Takeout explorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util

# Noise calendar names (matched lowercased). Also exclude any name containing 'nba'.
_NOISE_CALENDAR_NAMES: tuple[str, ...] = (
    "sleep",
    "sleep(1)",
    "daily briefing",
    "nba 2022-23 schedule",
)

_DURATION_CAP_SEC = 24 * 3600
_SCATTER_DURATION_CAP_SEC = 12 * 3600


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    calendar: str | None = None
    exclude_noise: bool = True

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        if self.calendar:
            chips.append(("calendar", f"calendar: {self.calendar}"))
        if self.exclude_noise:
            chips.append(("exclude_noise", "hide noise calendars"))
        return chips


def _year_where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    where, params = query_util.year_clause(alias, f.year_start, f.year_end)
    return where, params


def _noise_clause(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    """Exclude known noise calendars unless an explicit calendar lock is set."""
    if not f.exclude_noise or f.calendar:
        return "1=1", []
    p = f"{alias}." if alias else ""
    placeholders = ", ".join("?" for _ in _NOISE_CALENDAR_NAMES)
    clause = (
        f"({p}calendar_name IS NULL OR ("
        f"lower({p}calendar_name) NOT IN ({placeholders}) "
        f"AND {p}calendar_name NOT ILIKE '%nba%'"
        f"))"
    )
    return clause, list(_NOISE_CALENDAR_NAMES)


def _cal_where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    where, params = _year_where(alias, f)
    if f.calendar:
        p = f"{alias}." if alias else ""
        extra = f"{p}calendar_name = ?"
        where = f"({where}) AND {extra}" if where != "1=1" else extra
        params = [*params, f.calendar]
    noise_w, noise_p = _noise_clause(alias, f)
    if noise_w != "1=1":
        where = f"({where}) AND {noise_w}" if where != "1=1" else noise_w
        params = [*params, *noise_p]
    return where, params


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def previous_window(f: FilterState) -> FilterState | None:
    bounds = query_util.previous_year_bounds(f.year_start, f.year_end)
    if bounds is None:
        return None
    return FilterState(
        year_start=bounds[0],
        year_end=bounds[1],
        calendar=f.calendar,
        exclude_noise=f.exclude_noise,
    )


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(day)::DATE, max(day)::DATE
        FROM (
            SELECT year, day FROM google.calendar_events WHERE day IS NOT NULL
            UNION ALL
            SELECT year, day FROM google.photos WHERE day IS NOT NULL
            UNION ALL
            SELECT year, day FROM google.activity WHERE day IS NOT NULL
            UNION ALL
            SELECT year, day FROM google.maps_saves WHERE day IS NOT NULL
            UNION ALL
            SELECT year, day FROM google.play_installs WHERE day IS NOT NULL
        )
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2015, 2015
    calendars = [r[0] for r in conn.execute("""
            SELECT calendar_name, count(*) AS n
            FROM google.calendar_events
            WHERE calendar_name IS NOT NULL
            GROUP BY 1
            ORDER BY n DESC, calendar_name
            """).fetchall() if r[0]]
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "calendars": calendars,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int | None,
    year_end: int | None,
    calendar: str | None = None,
    exclude_noise: bool = True,
) -> FilterState:
    ys = int(year_start) if year_start is not None else bounds.get("min_year")
    ye = int(year_end) if year_end is not None else bounds.get("max_year")
    if ys is not None and ye is not None and ys > ye:
        ys, ye = ye, ys
    mn, mx = bounds.get("min_year"), bounds.get("max_year")
    if ys is not None and mn is not None:
        ys = max(int(ys), int(mn))
    if ye is not None and mx is not None:
        ye = min(int(ye), int(mx))
    if ys is not None and ye is not None and ys > ye:
        ys, ye = ye, ys
    cal = None if not calendar or calendar == "(all)" else calendar
    return FilterState(
        year_start=ys,
        year_end=ye,
        calendar=cal,
        exclude_noise=bool(exclude_noise),
    )


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


def play_installs_monthly_total(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
) -> pd.DataFrame:
    return play_installs_monthly(
        conn, FilterState(year_start=year_start, year_end=year_end)
    )


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
