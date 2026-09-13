"""Filter state and DuckDB queries for the Sleep as Android explorer."""

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
    tags: list[str] | None = None
    min_rating: float | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        if self.tags:
            chips.append(("tags", "tags " + ", ".join(self.tags)))
        if self.min_rating is not None:
            chips.append(("rating", f"rating ≥ {self.min_rating}"))
        return chips


def _where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    p = f"{alias}." if alias else ""
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
    if f.min_rating is not None:
        clauses.append(f"{p}rating >= ?")
        params.append(f.min_rating)
    if f.tags:
        tag_parts = []
        for tag in f.tags:
            tag_parts.append(f"list_contains(string_split({p}tags, ' '), ?)")
            params.append(tag)
        clauses.append("(" + " OR ".join(tag_parts) + ")")
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
            min(local_date)::DATE, max(local_date)::DATE
        FROM sleep.sessions
        WHERE local_date IS NOT NULL
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2017, 2026
    tags = conn.execute("""
        SELECT DISTINCT tag
        FROM sleep.sessions, unnest(string_split(tags, ' ')) AS t(tag)
        WHERE tags IS NOT NULL AND tags != '' AND tag != ''
        ORDER BY 1
        """).fetchdf()
    tag_list = [t for t in tags["tag"].tolist() if t] if not tags.empty else []
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "tags": tag_list,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    tags: list[str] | None = None,
    min_rating: float | None = None,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    rating = min_rating if min_rating and min_rating > 0 else None
    return FilterState(
        year_start=ys,
        year_end=ye,
        tags=tags or None,
        min_rating=rating,
    )


def has_miband_hr(conn: duckdb.DuckDBPyConnection) -> bool:
    return query_util.has_table(conn, "miband", "heart_rate")


def has_spotify_plays(conn: duckdb.DuckDBPyConnection) -> bool:
    return query_util.has_table(conn, "spotify", "plays")


def has_alarms(conn: duckdb.DuckDBPyConnection) -> bool:
    return query_util.has_table(conn, "sleep", "alarms")


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS nights,
            round(avg(hours), 2) AS avg_hours,
            round(avg(deep_sleep), 3) AS avg_deep_frac,
            round(avg(deep_hours), 2) AS avg_deep_hours,
            round(avg(rating), 2) AS avg_rating,
            round(avg(cycles), 1) AS avg_cycles,
            round(avg(noise), 4) AS avg_noise,
            sum(CASE WHEN coalesce(snore, 0) > 0 THEN 1 ELSE 0 END)::BIGINT AS snore_nights,
            round(avg(bed_hour + extract(minute FROM from_local) / 60.0), 2)
                AS avg_bed_hour,
            round(avg(wake_hour + extract(minute FROM to_local) / 60.0), 2)
                AS avg_wake_hour
        FROM sleep.sessions s
        WHERE {where}
        """,
        params,
    )


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare_previous: bool = False,
) -> pd.DataFrame:
    """Scoreboard KPIs; optionally append the previous equal-length year window."""
    current = _scoreboard_row(conn, f)
    if not compare_previous or f.year_start is None or f.year_end is None:
        current["window"] = "current"
        return current

    span = f.year_end - f.year_start + 1
    prev_start = f.year_start - span
    prev_end = f.year_start - 1
    min_row = conn.execute("SELECT min(year)::INT FROM sleep.sessions").fetchone()
    assert min_row is not None
    min_year = min_row[0]
    if min_year is None or prev_start < min_year:
        current["window"] = "current"
        current["compare_note"] = (
            f"previous window ({prev_start}–{prev_end}) predates data (min year {min_year})"
        )
        return current
    prev_f = FilterState(
        year_start=prev_start,
        year_end=prev_end,
        tags=list(f.tags) if f.tags else None,
        min_rating=f.min_rating,
    )
    prev = _scoreboard_row(conn, prev_f)
    current["window"] = "current"
    prev["window"] = f"previous ({prev_start}–{prev_end})"
    return pd.concat([current, prev], ignore_index=True)


def regularity_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Sleep regularity: bedtime/wake spread and weekend-vs-weekday shift.

    Bedtimes after midnight are shifted by +24h so 23:30 and 00:30 are
    one hour apart, not 23. Weekend nights are Friday and Saturday
    (ISO weekday of the bedtime), i.e. nights followed by a free morning.
    """
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        WITH n AS (
            SELECT
                (CASE WHEN bed_hour < 12 THEN bed_hour + 24 ELSE bed_hour END)
                    + extract(minute FROM from_local) / 60.0 AS bed_h,
                wake_hour + extract(minute FROM to_local) / 60.0 AS wake_h,
                hours,
                weekday IN (5, 6) AS weekend_night
            FROM sleep.sessions s
            WHERE {where} AND bed_hour IS NOT NULL AND wake_hour IS NOT NULL
        )
        SELECT
            count(*)::BIGINT AS nights,
            round(stddev_samp(bed_h), 2) AS bedtime_stddev_h,
            round(stddev_samp(wake_h), 2) AS wake_stddev_h,
            round(stddev_samp(hours), 2) AS hours_stddev,
            round(
                avg(bed_h) FILTER (WHERE weekend_night)
                - avg(bed_h) FILTER (WHERE NOT weekend_night),
                2
            ) AS social_jetlag_bed_h,
            round(
                avg(wake_h) FILTER (WHERE weekend_night)
                - avg(wake_h) FILTER (WHERE NOT weekend_night),
                2
            ) AS social_jetlag_wake_h,
            round(
                100.0 * avg(CASE WHEN hours >= 7.0 THEN 1.0 ELSE 0.0 END), 1
            ) AS nights_7h_pct
        FROM n
        """,
        params,
    )


def circadian_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Nights by ISO weekday x bedtime hour (local)."""
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT weekday AS dow, bed_hour AS hour, count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND weekday IS NOT NULL AND bed_hour IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def snore_noise_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            date_trunc('month', local_date)::DATE AS month,
            round(avg(snore), 1) AS avg_snore,
            round(avg(noise), 4) AS avg_noise,
            round(
                100.0 * avg(CASE WHEN coalesce(snore, 0) > 0 THEN 1.0 ELSE 0.0 END), 1
            ) AS snore_nights_pct,
            count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        WITH nights AS (
            SELECT local_date, hours
            FROM sleep.sessions s
            WHERE {where} AND local_date IS NOT NULL AND hours IS NOT NULL
        ),
        flagged AS (
            SELECT local_date, hours >= 7.0 AS enough
            FROM nights
        ),
        ordered AS (
            SELECT
                local_date,
                enough,
                local_date - (row_number() OVER (PARTITION BY enough ORDER BY local_date))::INT
                    AS grp
            FROM flagged
            WHERE enough
        ),
        streaks AS (
            SELECT count(*)::BIGINT AS streak_len
            FROM ordered
            GROUP BY grp
        )
        SELECT
            coalesce(max(streak_len), 0)::BIGINT AS longest_7h_streak,
            coalesce(
                (SELECT streak_len FROM (
                    SELECT grp, count(*)::BIGINT AS streak_len, max(local_date) AS last_d
                    FROM ordered GROUP BY grp
                ) t ORDER BY last_d DESC LIMIT 1),
                0
            )::BIGINT AS current_7h_streak
        FROM streaks
        """,
        params,
    )


def monthly_hours(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            date_trunc('month', local_date)::DATE AS month,
            round(avg(hours), 2) AS avg_hours,
            round(avg(deep_hours), 2) AS avg_deep_hours,
            round(avg(rating), 2) AS avg_rating,
            count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def hours_over_time(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day, hours, deep_hours, rating, cycles
        FROM sleep.sessions s
        WHERE {where} AND local_date IS NOT NULL
        ORDER BY 1
        """,
        params,
    )


def bedtime_distribution(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT bed_hour AS hour, count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND bed_hour IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def wake_distribution(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT wake_hour AS hour, count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND wake_hour IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def weekday_hours(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            weekday AS dow,
            round(avg(hours), 2) AS avg_hours,
            round(avg(rating), 2) AS avg_rating,
            count(*)::BIGINT AS nights
        FROM sleep.sessions s
        WHERE {where} AND weekday IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day, hours, rating
        FROM sleep.sessions s
        WHERE {where} AND local_date IS NOT NULL
        ORDER BY 1
        """,
        params,
    )


def event_type_counts(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT e.event_type, count(*)::BIGINT AS events
        FROM sleep.events e
        JOIN sleep.sessions s ON s.id = e.session_id
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        LIMIT 25
        """,
        params,
    )


def tag_breakdown(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            tag,
            count(*)::BIGINT AS nights,
            round(avg(hours), 2) AS avg_hours
        FROM sleep.sessions s, unnest(string_split(s.tags, ' ')) AS t(tag)
        WHERE {where} AND s.tags IS NOT NULL AND s.tags != '' AND tag != ''
        GROUP BY tag
        ORDER BY nights DESC
        """,
        params,
    )


def best_worst_nights(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 10
) -> tuple[pd.DataFrame, pd.DataFrame]:
    where, params = _where("s", f)
    cols = """
        local_date AS day, hours, deep_hours, rating, cycles, tags, comment
        FROM sleep.sessions s
        WHERE {where} AND hours IS NOT NULL
    """
    best = _query_df(
        conn,
        f"SELECT {cols.format(where=where)} ORDER BY hours DESC LIMIT {limit}",
        params,
    )
    worst = _query_df(
        conn,
        f"SELECT {cols.format(where=where)} ORDER BY hours ASC LIMIT {limit}",
        params,
    )
    return best, worst


def sample_actigraphy(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit_sessions: int = 1
) -> pd.DataFrame:
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        WITH pick AS (
            SELECT id, local_date
            FROM sleep.sessions s
            WHERE {where}
            ORDER BY local_date DESC
            LIMIT {limit_sessions}
        )
        SELECT p.local_date AS day, a.bucket_label, a.value
        FROM sleep.actigraphy a
        JOIN pick p ON p.id = a.session_id
        WHERE a.value IS NOT NULL
        ORDER BY p.local_date, a.bucket_label
        """,
        params,
    )


def session_heart_rate(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit_sessions: int = 5
) -> pd.DataFrame:
    """Mi Band HR readings inside the latest N sessions (for actigraphy overlay).

    Returns an empty frame when ``miband.heart_rate`` is not ingested.
    """
    if not has_miband_hr(conn):
        return pd.DataFrame(columns=["day", "ts_local", "minutes_in", "rate"])
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        WITH pick AS (
            SELECT id, local_date, from_local, to_local
            FROM sleep.sessions s
            WHERE {where} AND from_local IS NOT NULL AND to_local IS NOT NULL
            ORDER BY local_date DESC
            LIMIT {limit_sessions}
        )
        SELECT
            p.local_date AS day,
            h.ts_local,
            round(epoch(h.ts_local - p.from_local) / 60.0, 1) AS minutes_in,
            h.rate
        FROM miband.heart_rate h
        JOIN pick p ON h.ts_local >= p.from_local AND h.ts_local <= p.to_local
        ORDER BY p.local_date, h.ts_local
        """,
        params,
    )


def nightly_heart_rate(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Per-night resting HR from Mi Band readings that fall inside each session."""
    if not has_miband_hr(conn):
        return pd.DataFrame(
            columns=["day", "hours", "rating", "avg_bpm", "min_bpm", "readings"]
        )
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            s.local_date AS day,
            s.hours,
            s.rating,
            round(avg(h.rate), 1) AS avg_bpm,
            min(h.rate)::INT AS min_bpm,
            count(*)::BIGINT AS readings
        FROM sleep.sessions s
        JOIN miband.heart_rate h
          ON h.ts_local >= s.from_local AND h.ts_local <= s.to_local
        WHERE {where} AND s.from_local IS NOT NULL AND s.to_local IS NOT NULL
        GROUP BY 1, 2, 3
        HAVING count(*) >= 5
        ORDER BY 1
        """,
        params,
    )


def alarm_vs_wake(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Scheduled alarm (``Sched``) vs actual wake, in minutes (negative = woke early)."""
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            local_date AS day,
            sched_local,
            to_local,
            round(epoch(to_local - sched_local) / 60.0, 1) AS wake_minus_alarm_min,
            hours,
            rating
        FROM sleep.sessions s
        WHERE {where} AND sched_local IS NOT NULL AND to_local IS NOT NULL
          AND abs(epoch(to_local - sched_local)) <= 4 * 3600
        ORDER BY 1
        """,
        params,
    )


def alarm_summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Configured alarms from ``alarms.json`` (if ingested into ``sleep.alarms``)."""
    if not has_alarms(conn):
        return pd.DataFrame(columns=["hour", "minute", "enabled", "days", "label"])
    return _query_df(
        conn,
        """
        SELECT hour, minute, enabled, days, label
        FROM sleep.alarms
        ORDER BY enabled DESC, hour, minute
        """,
    )


def late_night_spotify_vs_sleep(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    from_hour: int = 22,
) -> pd.DataFrame:
    """Same-evening Spotify hours (>= ``from_hour`` local, before bedtime) vs sleep.

    Joins ``spotify.plays`` to ``sleep.sessions`` on the evening date of the
    bedtime (``from_local``). Nights without listening are kept with 0 h so
    the "no music" baseline is visible. Empty when Spotify is not ingested.
    """
    if not has_spotify_plays(conn):
        return pd.DataFrame(
            columns=["day", "hours", "rating", "deep_hours", "late_spotify_hours"]
        )
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        WITH nights AS (
            SELECT
                id, local_date, from_local, hours, rating, deep_hours,
                -- evening date: bedtimes after midnight belong to the prior evening
                CASE WHEN bed_hour < 12
                     THEN (from_local::DATE - INTERVAL 1 DAY)::DATE
                     ELSE from_local::DATE END AS evening
            FROM sleep.sessions s
            WHERE {where} AND from_local IS NOT NULL AND hours IS NOT NULL
        ),
        late AS (
            SELECT
                played_at_local::DATE AS evening,
                sum(hours) AS late_hours
            FROM spotify.plays
            WHERE hour(played_at_local) >= {int(from_hour)}
            GROUP BY 1
        )
        SELECT
            n.local_date AS day,
            n.hours,
            n.rating,
            n.deep_hours,
            round(coalesce(l.late_hours, 0), 2) AS late_spotify_hours
        FROM nights n
        LEFT JOIN late l ON l.evening = n.evening
        ORDER BY 1
        """,
        params,
    )


def late_night_spotify_buckets(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    from_hour: int = 22,
) -> pd.DataFrame:
    """Bucket nights by late-evening Spotify hours and average sleep KPIs."""
    df = late_night_spotify_vs_sleep(conn, f, from_hour=from_hour)
    if df.empty:
        return pd.DataFrame(
            columns=["bucket", "nights", "avg_hours", "avg_rating", "avg_deep_hours"]
        )
    bins = [-0.001, 0.0, 0.5, 1.0, 2.0, float("inf")]
    labels = ["none", "≤30 min", "30–60 min", "1–2 h", ">2 h"]
    out = df.copy()
    out["bucket"] = pd.cut(out["late_spotify_hours"], bins=bins, labels=labels)
    grouped = (
        out.groupby("bucket", observed=True)
        .agg(
            nights=("hours", "size"),
            avg_hours=("hours", "mean"),
            avg_rating=("rating", "mean"),
            avg_deep_hours=("deep_hours", "mean"),
        )
        .reset_index()
    )
    for col in ("avg_hours", "avg_rating", "avg_deep_hours"):
        grouped[col] = grouped[col].round(2)
    grouped["bucket"] = grouped["bucket"].astype(str)
    return grouped


def stage_event_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Count stage-related START events per year."""
    where, params = _where("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            s.year,
            e.event_type,
            count(*)::BIGINT AS events
        FROM sleep.events e
        JOIN sleep.sessions s ON s.id = e.session_id
        WHERE {where}
          AND e.event_type IN (
              'DEEP_START', 'LIGHT_START', 'REM_START', 'AWAKE_START',
              'DEEP_END', 'LIGHT_END', 'REM_END', 'AWAKE_END'
          )
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )
