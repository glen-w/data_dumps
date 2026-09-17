"""Spotify listening Wrapped queries."""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps.spotify_queries.filters import FilterState, _query_df, _where_and_params


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare_previous: bool = False,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            count(*)::BIGINT AS plays,
            round(sum(hours), 1) AS hours,
            count(DISTINCT artist_name) FILTER (WHERE artist_name IS NOT NULL) AS artists,
            count(DISTINCT track_name) FILTER (WHERE track_name IS NOT NULL) AS tracks,
            round(100.0 * avg(CASE WHEN skipped THEN 1.0 ELSE 0.0 END), 1) AS skip_pct,
            min(played_at)::DATE AS first_day,
            max(played_at)::DATE AS last_day
        FROM spotify.plays
        WHERE {where}
    """
    current = _query_df(conn, sql, params)
    if not compare_previous or f.year_start is None or f.year_end is None:
        current["window"] = "current"
        return current

    span = f.year_end - f.year_start + 1
    prev_start = f.year_start - span
    prev_end = f.year_start - 1
    min_row = conn.execute("SELECT min(year)::INT FROM spotify.plays").fetchone()
    assert min_row is not None
    min_year = min_row[0]
    if prev_start < min_year:
        current["window"] = "current"
        current["compare_note"] = (
            f"previous window ({prev_start}–{prev_end}) predates data (min year {min_year})"
        )
        return current
    prev_f = FilterState(
        year_start=prev_start,
        year_end=prev_end,
        kinds=list(f.kinds),
        platform_buckets=list(f.platform_buckets),
        conn_countries=list(f.conn_countries),
        artist_search=f.artist_search,
        artist_name=f.artist_name,
        album_name=f.album_name,
        track_name=f.track_name,
        episode_show_name=f.episode_show_name,
    )
    prev_where, prev_params = _where_and_params(prev_f)
    prev_sql = f"""
        SELECT
            count(*)::BIGINT AS plays,
            round(sum(hours), 1) AS hours,
            count(DISTINCT artist_name) FILTER (WHERE artist_name IS NOT NULL) AS artists,
            count(DISTINCT track_name) FILTER (WHERE track_name IS NOT NULL) AS tracks,
            round(100.0 * avg(CASE WHEN skipped THEN 1.0 ELSE 0.0 END), 1) AS skip_pct,
            min(played_at)::DATE AS first_day,
            max(played_at)::DATE AS last_day
        FROM spotify.plays
        WHERE {prev_where}
    """
    prev = _query_df(conn, prev_sql, prev_params)
    current["window"] = "current"
    prev["window"] = f"previous ({prev_start}–{prev_end})"
    return pd.concat([current, prev], ignore_index=True)


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        WITH daily AS (
            SELECT played_at::DATE AS day, sum(hours) AS hours
            FROM spotify.plays
            WHERE {where}
            GROUP BY 1
        ),
        ranked AS (
            SELECT
                day,
                hours,
                day - (row_number() OVER (ORDER BY day))::INT AS grp
            FROM daily
        ),
        streaks AS (
            SELECT grp, count(*) AS streak_days, sum(hours) AS streak_hours
            FROM ranked
            GROUP BY grp
        ),
        busiest AS (
            SELECT day, round(hours, 2) AS hours
            FROM daily
            ORDER BY hours DESC
            LIMIT 1
        )
        SELECT
            (SELECT max(streak_days) FROM streaks) AS longest_streak_days,
            (SELECT round(max(streak_hours), 1) FROM streaks) AS longest_streak_hours,
            (SELECT day FROM busiest) AS busiest_day,
            (SELECT hours FROM busiest) AS busiest_day_hours
    """
    return _query_df(conn, sql, params)


def top_artists(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    limit: int = 15,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.append(limit)
    sql = f"""
        SELECT
            artist_name,
            count(*)::BIGINT AS plays,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE kind = 'track' AND artist_name IS NOT NULL AND {where}
        GROUP BY 1
        ORDER BY hours DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def top_tracks(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    limit: int = 15,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.append(limit)
    sql = f"""
        SELECT
            track_name,
            artist_name,
            count(*)::BIGINT AS plays,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE kind = 'track' AND track_name IS NOT NULL AND {where}
        GROUP BY 1, 2
        ORDER BY hours DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def top_albums(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    limit: int = 15,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.append(limit)
    sql = f"""
        SELECT
            album_name,
            artist_name,
            count(*)::BIGINT AS plays,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE kind = 'track' AND album_name IS NOT NULL AND {where}
        GROUP BY 1, 2
        ORDER BY hours DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def top_shows(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    limit: int = 15,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.append(limit)
    sql = f"""
        SELECT
            episode_show_name,
            count(*)::BIGINT AS plays,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE kind = 'episode' AND episode_show_name IS NOT NULL AND {where}
        GROUP BY 1
        ORDER BY hours DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def discovery_vs_repeats(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        WITH filtered AS (
            SELECT * FROM spotify.plays WHERE kind = 'track' AND track_id IS NOT NULL AND {where}
        ),
        first_heard AS (
            SELECT track_id, min(played_at) AS first_play
            FROM spotify.plays
            WHERE kind = 'track' AND track_id IS NOT NULL
            GROUP BY 1
        ),
        window_bounds AS (
            SELECT min(played_at) AS w_start, max(played_at) AS w_end FROM filtered
        ),
        classified AS (
            SELECT
                f.track_id,
                fh.first_play,
                CASE
                    WHEN fh.first_play >= (SELECT w_start FROM window_bounds) THEN 'discovery'
                    ELSE 'repeat'
                END AS play_type
            FROM filtered f
            JOIN first_heard fh ON f.track_id = fh.track_id
        )
        SELECT
            play_type,
            count(*)::BIGINT AS plays,
            count(DISTINCT track_id) AS unique_tracks
        FROM classified
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)


def circadian_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            dayofweek(played_at_local) AS dow,
            hour(played_at_local) AS hour,
            round(sum(hours), 3) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    return _query_df(conn, sql, params)


def shuffle_intent(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            CASE WHEN shuffle THEN 'shuffle' ELSE 'not shuffle' END AS shuffle_mode,
            reason_start,
            count(*)::BIGINT AS plays,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY hours DESC
    """
    return _query_df(conn, sql, params)


def forgotten_artists(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_hours: float = 20.0,
    silent_years: int = 2,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.extend([min_hours, silent_years, limit])
    sql = f"""
        WITH artist_hours AS (
            SELECT
                artist_name,
                round(sum(hours), 1) AS total_hours,
                max(played_at) AS last_play
            FROM spotify.plays
            WHERE kind = 'track' AND artist_name IS NOT NULL AND {where}
            GROUP BY 1
            HAVING sum(hours) >= ?
        )
        SELECT artist_name, total_hours, last_play::DATE AS last_play
        FROM artist_hours
        WHERE last_play < current_timestamp - (? * INTERVAL '1 year')
        ORDER BY total_hours DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def comeback_artists(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 2,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.extend([silent_years, limit])
    sql = f"""
        WITH filtered AS (
            SELECT artist_name, played_at, hours
            FROM spotify.plays
            WHERE kind = 'track' AND artist_name IS NOT NULL AND {where}
        ),
        artist_span AS (
            SELECT
                artist_name,
                min(played_at) AS first_in_window,
                max(played_at) AS last_in_window,
                round(sum(hours), 1) AS window_hours
            FROM filtered
            GROUP BY 1
        ),
        prior AS (
            SELECT
                p.artist_name,
                max(p.played_at) AS last_before
            FROM spotify.plays p
            INNER JOIN artist_span a ON p.artist_name = a.artist_name
            WHERE p.kind = 'track'
              AND p.played_at < a.first_in_window
            GROUP BY 1
        )
        SELECT
            a.artist_name,
            a.window_hours,
            p.last_before::DATE AS last_before,
            a.first_in_window::DATE AS returned_on
        FROM artist_span a
        INNER JOIN prior p ON a.artist_name = p.artist_name
        WHERE p.last_before < a.first_in_window - (? * INTERVAL '1 year')
        ORDER BY a.window_hours DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def monthly_hours(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            year,
            month,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    df = _query_df(conn, sql, params)
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def hours_by_kind(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT year, kind, round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    return _query_df(conn, sql, params)


def hours_by_platform(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT platform_bucket, round(sum(hours), 1) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1
        ORDER BY hours DESC
    """
    return _query_df(conn, sql, params)


def hours_by_country(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            strftime(played_at, '%Y-%m') AS month,
            conn_country,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE conn_country IS NOT NULL AND {where}
        GROUP BY 1, 2
        HAVING sum(hours) > 5
        ORDER BY 1, 3 DESC
    """
    return _query_df(conn, sql, params)


def hours_by_country_total(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Total listening hours by connection country (for choropleth)."""
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            conn_country AS country,
            round(sum(hours), 2) AS hours,
            count(*)::BIGINT AS plays
        FROM spotify.plays
        WHERE conn_country IS NOT NULL AND {where}
        GROUP BY 1
        ORDER BY hours DESC
    """
    return _query_df(conn, sql, params)


def skip_trends(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            year,
            round(100.0 * avg(CASE WHEN skipped THEN 1.0 ELSE 0.0 END), 1) AS skip_pct,
            round(100.0 * avg(CASE WHEN full_play THEN 1.0 ELSE 0.0 END), 1) AS full_play_pct,
            round(100.0 * avg(CASE WHEN ms_played < 30000 THEN 1.0 ELSE 0.0 END), 1) AS under_30s_pct
        FROM spotify.plays
        WHERE kind = 'track' AND {where}
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)


def treemap_artist_album(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            artist_name,
            coalesce(album_name, '(no album)') AS album_name,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE kind = 'track' AND artist_name IS NOT NULL AND {where}
        GROUP BY 1, 2
        ORDER BY hours DESC
        LIMIT 200
    """
    return _query_df(conn, sql, params)


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            played_at::DATE AS day,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)


def bump_chart_artists(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    top_n: int = 10,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.append(top_n)
    sql = f"""
        WITH yearly AS (
            SELECT year, artist_name, sum(hours) AS hours
            FROM spotify.plays
            WHERE kind = 'track' AND artist_name IS NOT NULL AND {where}
            GROUP BY 1, 2
        ),
        top_artists AS (
            SELECT artist_name
            FROM yearly
            GROUP BY 1
            ORDER BY sum(hours) DESC
            LIMIT ?
        ),
        ranked AS (
            SELECT
                y.year,
                y.artist_name,
                y.hours,
                row_number() OVER (PARTITION BY y.year ORDER BY y.hours DESC) AS rank
            FROM yearly y
            INNER JOIN top_artists t ON y.artist_name = t.artist_name
        )
        SELECT year, artist_name, round(hours, 2) AS hours, rank
        FROM ranked
        ORDER BY year, rank
    """
    return _query_df(conn, sql, params)


def artist_hours_vs_skip(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            artist_name,
            round(sum(hours), 2) AS hours,
            round(100.0 * avg(CASE WHEN skipped THEN 1.0 ELSE 0.0 END), 1) AS skip_pct,
            count(*)::BIGINT AS plays
        FROM spotify.plays
        WHERE kind = 'track' AND artist_name IS NOT NULL AND {where}
        GROUP BY 1
        HAVING count(*) >= 10
        ORDER BY hours DESC
        LIMIT 100
    """
    return _query_df(conn, sql, params)


def kind_platform_sunburst(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            kind,
            platform_bucket,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY hours DESC
    """
    return _query_df(conn, sql, params)


def genre_treemap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f, table_alias="p")
    sql = f"""
        SELECT
            coalesce(ma.primary_tag, 'unknown') AS genre,
            p.artist_name,
            round(sum(p.hours), 2) AS hours
        FROM spotify.plays p
        LEFT JOIN spotify.mb_match m ON m.entity_type = 'artist'
            AND m.dump_name = p.artist_name
        LEFT JOIN spotify.mb_artists ma ON ma.mbid = m.mbid
        WHERE p.kind = 'track' AND p.artist_name IS NOT NULL AND {where}
        GROUP BY 1, 2
        ORDER BY hours DESC
        LIMIT 200
    """
    return _query_df(conn, sql, params)


def decade_bars(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f, table_alias="p")
    sql = f"""
        SELECT
            coalesce(mr.decade, 'unknown') AS decade,
            round(sum(p.hours), 2) AS hours,
            count(*)::BIGINT AS plays
        FROM spotify.plays p
        LEFT JOIN spotify.mb_match mt ON mt.entity_type = 'track'
            AND mt.dump_name = p.track_name AND mt.dump_artist = p.artist_name
        LEFT JOIN spotify.mb_recordings mr ON mr.mbid = mt.mbid
        WHERE p.kind = 'track' AND p.track_name IS NOT NULL AND {where}
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)


def offline_vs_online(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Hours and plays split by the export's ``offline`` flag."""
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            CASE WHEN offline THEN 'offline' ELSE 'online' END AS mode,
            count(*)::BIGINT AS plays,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)


def milestones(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """One-row table of headline moments in the filtered window."""
    where, params = _where_and_params(f)
    sql = f"""
        WITH filtered AS (
            SELECT * FROM spotify.plays WHERE {where}
        ),
        daily AS (
            SELECT played_at::DATE AS day, sum(hours) AS hours, count(*) AS plays
            FROM filtered
            GROUP BY 1
        ),
        busiest AS (SELECT * FROM daily ORDER BY hours DESC LIMIT 1),
        longest AS (
            SELECT
                coalesce(track_name, episode_name, audiobook_title::VARCHAR) AS title,
                coalesce(artist_name, episode_show_name) AS who,
                hours,
                played_at::DATE AS day
            FROM filtered
            ORDER BY hours DESC
            LIMIT 1
        ),
        first_play AS (
            SELECT
                coalesce(track_name, episode_name, audiobook_title::VARCHAR) AS title,
                coalesce(artist_name, episode_show_name) AS who,
                played_at::DATE AS day
            FROM filtered
            ORDER BY played_at ASC
            LIMIT 1
        ),
        last_play AS (
            SELECT
                coalesce(track_name, episode_name, audiobook_title::VARCHAR) AS title,
                coalesce(artist_name, episode_show_name) AS who,
                played_at::DATE AS day
            FROM filtered
            ORDER BY played_at DESC
            LIMIT 1
        ),
        most_repeated AS (
            SELECT track_name, artist_name, count(*)::BIGINT AS plays
            FROM filtered
            WHERE kind = 'track' AND track_name IS NOT NULL
            GROUP BY 1, 2
            ORDER BY plays DESC
            LIMIT 1
        )
        SELECT
            (SELECT count(*) FROM daily)::BIGINT AS days_listened,
            (SELECT round(avg(hours), 2) FROM daily) AS avg_hours_per_day,
            (SELECT day FROM busiest) AS busiest_day,
            (SELECT round(hours, 2) FROM busiest) AS busiest_day_hours,
            (SELECT plays FROM busiest)::BIGINT AS busiest_day_plays,
            (SELECT title FROM longest) AS longest_play_title,
            (SELECT who FROM longest) AS longest_play_by,
            (SELECT round(hours * 60, 1) FROM longest) AS longest_play_minutes,
            (SELECT day FROM first_play) AS first_play_day,
            (SELECT title FROM first_play) AS first_play_title,
            (SELECT who FROM first_play) AS first_play_by,
            (SELECT day FROM last_play) AS last_play_day,
            (SELECT title FROM last_play) AS last_play_title,
            (SELECT track_name FROM most_repeated) AS most_repeated_track,
            (SELECT artist_name FROM most_repeated) AS most_repeated_artist,
            (SELECT plays FROM most_repeated) AS most_repeated_plays
    """
    return _query_df(conn, sql, params)


def album_depth(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 15,
    min_plays: int = 10,
) -> pd.DataFrame:
    """Albums you go deep on: breadth (distinct tracks) x log revisit rate.

    ``depth_score = unique_tracks * ln(1 + plays / unique_tracks)`` rewards
    albums where many different tracks were played repeatedly, rather than a
    single hit on loop. No catalogue lookup: track counts come from the dump.
    """
    where, params = _where_and_params(f)
    sql = f"""
        WITH per_album AS (
            SELECT
                album_name,
                artist_name,
                count(DISTINCT track_name)::BIGINT AS unique_tracks,
                count(*)::BIGINT AS plays,
                round(sum(hours), 2) AS hours
            FROM spotify.plays
            WHERE kind = 'track' AND album_name IS NOT NULL
              AND track_name IS NOT NULL AND {where}
            GROUP BY 1, 2
            HAVING count(*) >= ?
        ),
        tops AS (
            SELECT
                album_name,
                artist_name,
                arg_max(track_name, n) AS top_track
            FROM (
                SELECT album_name, artist_name, track_name, count(*) AS n
                FROM spotify.plays
                WHERE kind = 'track' AND album_name IS NOT NULL
                  AND track_name IS NOT NULL AND {where}
                GROUP BY 1, 2, 3
            )
            GROUP BY 1, 2
        )
        SELECT
            a.album_name,
            a.artist_name,
            a.unique_tracks,
            a.plays,
            a.hours,
            round(a.plays / a.unique_tracks, 2) AS plays_per_track,
            round(a.unique_tracks * ln(1 + a.plays / a.unique_tracks), 2) AS depth_score,
            t.top_track
        FROM per_album a
        LEFT JOIN tops t
          ON t.album_name = a.album_name
         AND t.artist_name IS NOT DISTINCT FROM a.artist_name
        ORDER BY depth_score DESC, a.hours DESC
        LIMIT ?
    """
    # ``where`` appears twice (per_album, tops); placeholders bind in SQL order.
    return _query_df(conn, sql, params + [min_plays] + params + [limit])


def listening_sessions(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    gap_minutes: int = 30,
    limit: int = 15,
) -> pd.DataFrame:
    """Longest listening sessions; a new session starts after ``gap_minutes`` idle.

    The gap is measured from the end of one play (``played_at + ms_played``)
    to the start of the next.
    """
    where, params = _where_and_params(f)
    params.append(limit)
    sql = f"""
        WITH ordered AS (
            SELECT
                played_at,
                played_at_local,
                played_at + (ms_played || ' milliseconds')::INTERVAL AS ended_at,
                hours,
                artist_name,
                lag(played_at + (ms_played || ' milliseconds')::INTERVAL)
                    OVER (ORDER BY played_at) AS prev_end
            FROM spotify.plays
            WHERE {where}
        ),
        flagged AS (
            SELECT
                *,
                CASE
                    WHEN prev_end IS NULL
                      OR played_at - prev_end > INTERVAL {int(gap_minutes)} MINUTE
                    THEN 1 ELSE 0
                END AS new_session
            FROM ordered
        ),
        numbered AS (
            SELECT *, sum(new_session) OVER (ORDER BY played_at) AS session_id
            FROM flagged
        ),
        per_session AS (
            SELECT
                session_id,
                min(played_at_local) AS started_local,
                max(ended_at) AS ended_utc,
                min(played_at) AS started_utc,
                count(*)::BIGINT AS plays,
                round(sum(hours), 2) AS hours,
                count(DISTINCT artist_name)::BIGINT AS artists
            FROM numbered
            GROUP BY 1
        ),
        top_artist AS (
            SELECT session_id, arg_max(artist_name, h) AS top_artist
            FROM (
                SELECT session_id, artist_name, sum(hours) AS h
                FROM numbered
                WHERE artist_name IS NOT NULL
                GROUP BY 1, 2
            )
            GROUP BY 1
        )
        SELECT
            s.started_local,
            round(epoch(s.ended_utc - s.started_utc) / 3600.0, 2) AS span_hours,
            s.hours AS played_hours,
            s.plays,
            s.artists,
            t.top_artist
        FROM per_session s
        LEFT JOIN top_artist t USING (session_id)
        ORDER BY s.hours DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def _previous_window(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> tuple[FilterState | None, str | None]:
    """Previous equal-length year window, or (None, reason)."""
    if f.year_start is None or f.year_end is None:
        return None, "select a year range to compare against the previous window"
    span = f.year_end - f.year_start + 1
    prev_start = f.year_start - span
    prev_end = f.year_start - 1
    min_row = conn.execute("SELECT min(year)::INT FROM spotify.plays").fetchone()
    assert min_row is not None
    if min_row[0] is None or prev_start < min_row[0]:
        return None, (
            f"previous window ({prev_start}–{prev_end}) predates data "
            f"(min year {min_row[0]})"
        )
    prev = FilterState(
        year_start=prev_start,
        year_end=prev_end,
        kinds=list(f.kinds),
        platform_buckets=list(f.platform_buckets),
        conn_countries=list(f.conn_countries),
        artist_search=f.artist_search,
        artist_name=f.artist_name,
        album_name=f.album_name,
        track_name=f.track_name,
        episode_show_name=f.episode_show_name,
    )
    return prev, None


def artist_rank_movement(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 15,
) -> pd.DataFrame:
    """Top artists now with their rank in the previous equal window.

    ``rank_delta`` is positive when an artist climbed; NULL when new to the
    top list. Empty (with ``compare_note`` attr) when no year window is set.
    """
    cols = [
        "artist_name",
        "hours",
        "rank",
        "prev_hours",
        "prev_rank",
        "rank_delta",
        "status",
    ]
    prev_f, note = _previous_window(conn, f)
    if prev_f is None:
        out = pd.DataFrame(columns=cols)
        out.attrs["compare_note"] = note
        return out
    where, params = _where_and_params(f)
    prev_where, prev_params = _where_and_params(prev_f)
    sql = f"""
        WITH cur AS (
            SELECT
                artist_name,
                round(sum(hours), 2) AS hours,
                row_number() OVER (ORDER BY sum(hours) DESC) AS rank
            FROM spotify.plays
            WHERE kind = 'track' AND artist_name IS NOT NULL AND {where}
            GROUP BY 1
        ),
        prev AS (
            SELECT
                artist_name,
                round(sum(hours), 2) AS prev_hours,
                row_number() OVER (ORDER BY sum(hours) DESC) AS prev_rank
            FROM spotify.plays
            WHERE kind = 'track' AND artist_name IS NOT NULL AND {prev_where}
            GROUP BY 1
        )
        SELECT
            c.artist_name,
            c.hours,
            c.rank,
            p.prev_hours,
            p.prev_rank,
            (p.prev_rank - c.rank) AS rank_delta,
            CASE
                WHEN p.prev_rank IS NULL THEN 'new'
                WHEN p.prev_rank > c.rank THEN 'up'
                WHEN p.prev_rank < c.rank THEN 'down'
                ELSE 'same'
            END AS status
        FROM cur c
        LEFT JOIN prev p USING (artist_name)
        WHERE c.rank <= ?
        ORDER BY c.rank
    """
    out = _query_df(conn, sql, params + prev_params + [limit])
    out.attrs["compare_note"] = None
    return out


def artist_monthly_timeline(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    artists: list[str] | None = None,
    max_artists: int = 3,
) -> pd.DataFrame:
    """Monthly hours per artist for the locked artist or up to ``max_artists``."""
    names = list(artists or [])
    if not names and f.artist_name:
        names = [f.artist_name]
    if not names:
        names = top_artists(conn, f, limit=max_artists)["artist_name"].tolist()
    names = names[:max_artists]
    cols = ["year", "month", "artist_name", "hours", "year_month"]
    if not names:
        return pd.DataFrame(columns=cols)
    # Timeline ignores an artist lock so several artists can be compared.
    base = FilterState(
        year_start=f.year_start,
        year_end=f.year_end,
        kinds=list(f.kinds),
        platform_buckets=list(f.platform_buckets),
        conn_countries=list(f.conn_countries),
    )
    where, params = _where_and_params(base)
    placeholders = ", ".join("?" for _ in names)
    sql = f"""
        SELECT
            year,
            month,
            artist_name,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE kind = 'track' AND artist_name IN ({placeholders}) AND {where}
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """
    df = _query_df(conn, sql, names + params)
    df["year_month"] = (
        df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
    )
    return df[cols]
