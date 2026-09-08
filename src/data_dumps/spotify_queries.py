"""Shared filter state and DuckDB queries for the Spotify Marimo dashboard."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

NARRATIVE_CONTEXT_KEYS = frozenset(
    {
        "filter_digest",
        "filters",
        "scoreboard",
        "streak",
        "discovery",
        "top_artists",
        "top_tracks",
        "comebacks",
        "forgotten",
    }
)


@dataclass
class FilterState:
    """One filter state drives every dashboard query."""

    year_start: int | None = None
    year_end: int | None = None
    kinds: list[str] = field(default_factory=list)
    platform_buckets: list[str] = field(default_factory=list)
    conn_countries: list[str] = field(default_factory=list)
    artist_search: str | None = None
    artist_name: str | None = None
    album_name: str | None = None
    track_name: str | None = None
    episode_show_name: str | None = None

    def has_entity_lock(self) -> bool:
        return any(
            [
                self.artist_name,
                self.album_name,
                self.track_name,
                self.episode_show_name,
            ]
        )

    def chip_labels(self) -> list[tuple[str, str]]:
        """Return (field, label) pairs for active filter chips."""
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        for k in self.kinds:
            chips.append(("kind", f"kind={k}"))
        for p in self.platform_buckets:
            chips.append(("platform", f"platform={p}"))
        for c in self.conn_countries:
            chips.append(("country", f"country={c}"))
        if self.artist_search:
            chips.append(("artist_search", f"search: {self.artist_search}"))
        if self.artist_name:
            chips.append(("artist_name", f"artist: {self.artist_name}"))
        if self.album_name:
            chips.append(("album_name", f"album: {self.album_name}"))
        if self.track_name:
            chips.append(("track_name", f"track: {self.track_name}"))
        if self.episode_show_name:
            chips.append(("episode_show_name", f"show: {self.episode_show_name}"))
        return chips

    def filter_digest(self) -> str:
        """Stable hash for LLM cache keys."""
        payload = {
            "year_start": self.year_start,
            "year_end": self.year_end,
            "kinds": sorted(self.kinds),
            "platform_buckets": sorted(self.platform_buckets),
            "conn_countries": sorted(self.conn_countries),
            "artist_search": self.artist_search,
            "artist_name": self.artist_name,
            "album_name": self.album_name,
            "track_name": self.track_name,
            "episode_show_name": self.episode_show_name,
        }
        blob = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def clear_field(self, field_name: str) -> None:
        if field_name == "year_range":
            self.year_start = None
            self.year_end = None
        elif field_name == "kind":
            self.kinds = []
        elif field_name == "platform":
            self.platform_buckets = []
        elif field_name == "country":
            self.conn_countries = []
        elif field_name == "artist_search":
            self.artist_search = None
        elif field_name == "artist_name":
            self.artist_name = None
        elif field_name == "album_name":
            self.album_name = None
        elif field_name == "track_name":
            self.track_name = None
        elif field_name == "episode_show_name":
            self.episode_show_name = None


def _where_and_params(
    f: FilterState,
    *,
    table_alias: str = "",
    date_col: str = "played_at",
) -> tuple[str, list[Any]]:
    prefix = f"{table_alias}." if table_alias else ""
    clauses: list[str] = []
    params: list[Any] = []

    if f.year_start is not None:
        clauses.append(f"{prefix}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{prefix}year <= ?")
        params.append(f.year_end)
    if f.kinds:
        placeholders = ", ".join("?" for _ in f.kinds)
        clauses.append(f"{prefix}kind IN ({placeholders})")
        params.extend(f.kinds)
    if f.platform_buckets:
        placeholders = ", ".join("?" for _ in f.platform_buckets)
        clauses.append(f"{prefix}platform_bucket IN ({placeholders})")
        params.extend(f.platform_buckets)
    if f.conn_countries:
        placeholders = ", ".join("?" for _ in f.conn_countries)
        clauses.append(f"{prefix}conn_country IN ({placeholders})")
        params.extend(f.conn_countries)
    if f.artist_search:
        clauses.append(f"contains(lower({prefix}artist_name), lower(?))")
        params.append(f.artist_search)
    if f.artist_name:
        clauses.append(f"{prefix}artist_name = ?")
        params.append(f.artist_name)
    if f.album_name:
        clauses.append(f"{prefix}album_name = ?")
        params.append(f.album_name)
    if f.track_name:
        clauses.append(f"{prefix}track_name = ?")
        params.append(f.track_name)
    if f.episode_show_name:
        clauses.append(f"{prefix}episode_show_name = ?")
        params.append(f.episode_show_name)

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any],
) -> pd.DataFrame:
    return conn.execute(sql, params).df()


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT AS min_year,
            max(year)::INT AS max_year,
            min(played_at)::DATE AS first_day,
            max(played_at)::DATE AS last_day
        FROM spotify.plays
        """).fetchone()
    assert row is not None
    kinds = conn.execute(
        "SELECT DISTINCT kind FROM spotify.plays ORDER BY 1"
    ).fetchall()
    platforms = conn.execute(
        "SELECT DISTINCT platform_bucket FROM spotify.plays ORDER BY 1"
    ).fetchall()
    countries = conn.execute(
        "SELECT DISTINCT conn_country FROM spotify.plays WHERE conn_country IS NOT NULL ORDER BY 1"
    ).fetchall()
    return {
        "min_year": row[0],
        "max_year": row[1],
        "first_day": row[2],
        "last_day": row[3],
        "kinds": [r[0] for r in kinds],
        "platforms": [r[0] for r in platforms],
        "countries": [r[0] for r in countries],
    }


def has_mb_tables(conn: duckdb.DuckDBPyConnection) -> bool:
    row = conn.execute("""
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'spotify' AND table_name = 'mb_artists'
        """).fetchone()
    return row is not None and row[0] > 0


def has_mb_data(conn: duckdb.DuckDBPyConnection) -> bool:
    if not has_mb_tables(conn):
        return False
    row = conn.execute(
        "SELECT count(*)::BIGINT FROM spotify.mb_match WHERE mbid IS NOT NULL"
    ).fetchone()
    return row is not None and row[0] > 0


def has_table(conn: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    row = conn.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        """,
        [schema, table],
    ).fetchone()
    return row is not None and row[0] > 0


def has_account_data(conn: duckdb.DuckDBPyConnection) -> bool:
    return has_table(conn, "spotify", "library_items") or has_table(
        conn, "spotify", "playlists"
    )


def library_counts(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    if not has_table(conn, "spotify", "library_items"):
        return pd.DataFrame(columns=["item_kind", "n"])
    return _query_df(
        conn,
        """
        SELECT item_kind, count(*)::BIGINT AS n
        FROM spotify.library_items
        GROUP BY 1
        ORDER BY n DESC
        """,
        [],
    )


def library_overlap(
    conn: duckdb.DuckDBPyConnection, *, limit: int = 15
) -> pd.DataFrame:
    """Saved library tracks vs Extended History plays, matched on name+artist."""
    if not has_table(conn, "spotify", "library_items"):
        return pd.DataFrame(
            columns=["track_name", "artist_name", "play_hours", "in_plays"]
        )
    if not has_table(conn, "spotify", "plays"):
        return pd.DataFrame(
            columns=["track_name", "artist_name", "play_hours", "in_plays"]
        )
    return _query_df(
        conn,
        """
        SELECT
            l.name AS track_name,
            l.artist_name,
            round(coalesce(sum(p.hours), 0), 2) AS play_hours,
            count(p.track_name) > 0 AS in_plays
        FROM spotify.library_items l
        LEFT JOIN spotify.plays p
            ON p.kind = 'track'
            AND lower(p.track_name) = lower(l.name)
            AND lower(p.artist_name) = lower(l.artist_name)
        WHERE l.item_kind = 'track'
        GROUP BY 1, 2
        ORDER BY play_hours DESC, track_name
        LIMIT ?
        """,
        [limit],
    )


def library_never_played(
    conn: duckdb.DuckDBPyConnection, *, limit: int = 15
) -> pd.DataFrame:
    if not has_table(conn, "spotify", "library_items") or not has_table(
        conn, "spotify", "plays"
    ):
        return pd.DataFrame(columns=["track_name", "artist_name"])
    return _query_df(
        conn,
        """
        SELECT l.name AS track_name, l.artist_name
        FROM spotify.library_items l
        WHERE l.item_kind = 'track'
          AND NOT EXISTS (
              SELECT 1 FROM spotify.plays p
              WHERE p.kind = 'track'
                AND lower(p.track_name) = lower(l.name)
                AND lower(p.artist_name) = lower(l.artist_name)
          )
        ORDER BY l.artist_name, l.name
        LIMIT ?
        """,
        [limit],
    )


def playlist_sizes(conn: duckdb.DuckDBPyConnection, *, limit: int = 20) -> pd.DataFrame:
    if not has_table(conn, "spotify", "playlists"):
        return pd.DataFrame(columns=["playlist_name", "n_items", "last_modified"])
    return _query_df(
        conn,
        """
        SELECT playlist_name, n_items, last_modified
        FROM spotify.playlists
        ORDER BY n_items DESC, playlist_name
        LIMIT ?
        """,
        [limit],
    )


def search_volume(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    if not has_table(conn, "spotify", "searches"):
        return pd.DataFrame(columns=["year_month", "searches"])
    df = _query_df(
        conn,
        """
        SELECT year, month, count(*)::BIGINT AS searches
        FROM spotify.searches
        WHERE year IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        [],
    )
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def top_searches(conn: duckdb.DuckDBPyConnection, *, limit: int = 20) -> pd.DataFrame:
    if not has_table(conn, "spotify", "searches"):
        return pd.DataFrame(columns=["search_query", "n"])
    return _query_df(
        conn,
        """
        SELECT search_query, count(*)::BIGINT AS n
        FROM spotify.searches
        WHERE search_query IS NOT NULL AND length(search_query) > 1
        GROUP BY 1
        ORDER BY n DESC, search_query
        LIMIT ?
        """,
        [limit],
    )


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    kinds: list[str],
    platform_buckets: list[str],
    conn_countries: list[str],
    artist_search: str | None = None,
    artist_name: str | None = None,
    album_name: str | None = None,
    track_name: str | None = None,
    episode_show_name: str | None = None,
) -> FilterState:
    """Build FilterState; full year span means no year filter."""
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    return FilterState(
        year_start=ys,
        year_end=ye,
        kinds=kinds,
        platform_buckets=platform_buckets,
        conn_countries=conn_countries,
        artist_search=artist_search or None,
        artist_name=artist_name,
        album_name=album_name,
        track_name=track_name,
        episode_show_name=episode_show_name,
    )


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


def narrative_context(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
) -> dict[str, Any]:
    """Aggregates only — safe for LLM prompts."""
    score = scoreboard(conn, f, compare_previous=True)
    streak = streak_stats(conn, f)
    discovery = discovery_vs_repeats(conn, f)
    top_a = top_artists(conn, f, limit=10)
    top_t = top_tracks(conn, f, limit=10)
    comebacks = comeback_artists(conn, f, limit=5)
    forgotten = forgotten_artists(conn, f, limit=5)
    return {
        "filter_digest": f.filter_digest(),
        "filters": f.chip_labels(),
        "scoreboard": score.to_dict(orient="records"),
        "streak": streak.to_dict(orient="records"),
        "discovery": discovery.to_dict(orient="records"),
        "top_artists": top_a.to_dict(orient="records"),
        "top_tracks": top_t.to_dict(orient="records"),
        "comebacks": comebacks.to_dict(orient="records"),
        "forgotten": forgotten.to_dict(orient="records"),
    }
