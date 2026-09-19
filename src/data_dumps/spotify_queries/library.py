"""Spotify Account Data / library / search queries."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util
from data_dumps.spotify_queries.filters import _query_df


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


def has_account_data(conn: duckdb.DuckDBPyConnection) -> bool:
    return query_util.has_table(
        conn, "spotify", "library_items"
    ) or query_util.has_table(conn, "spotify", "playlists")


def library_counts(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    if not query_util.has_table(conn, "spotify", "library_items"):
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
    if not query_util.has_table(conn, "spotify", "library_items"):
        return pd.DataFrame(
            columns=["track_name", "artist_name", "play_hours", "in_plays"]
        )
    if not query_util.has_table(conn, "spotify", "plays"):
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
    if not query_util.has_table(
        conn, "spotify", "library_items"
    ) or not query_util.has_table(conn, "spotify", "plays"):
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
    if not query_util.has_table(conn, "spotify", "playlists"):
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
    if not query_util.has_table(conn, "spotify", "searches"):
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


def search_volume_filtered(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
) -> pd.DataFrame:
    if not query_util.has_table(conn, "spotify", "searches"):
        return pd.DataFrame(columns=["year_month", "searches"])
    clauses = ["year IS NOT NULL", "month IS NOT NULL"]
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, "", year_start, year_end)
    where = " AND ".join(clauses)
    df = _query_df(
        conn,
        f"""
        SELECT year, month, count(*)::BIGINT AS searches
        FROM spotify.searches
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def calendar_daily_searches(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
) -> pd.DataFrame:
    if not query_util.has_table(conn, "spotify", "searches"):
        return pd.DataFrame(columns=["day", "searches"])
    clauses = ["searched_at_local IS NOT NULL"]
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, "", year_start, year_end)
    where = " AND ".join(clauses)
    return _query_df(
        conn,
        f"""
        SELECT cast(searched_at_local AS DATE) AS day, count(*)::BIGINT AS searches
        FROM spotify.searches
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def top_searches(conn: duckdb.DuckDBPyConnection, *, limit: int = 20) -> pd.DataFrame:
    if not query_util.has_table(conn, "spotify", "searches"):
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


def searched_but_rarely_played(
    conn: duckdb.DuckDBPyConnection, *, limit: int = 15, max_plays: int = 3
) -> pd.DataFrame:
    """Account-data search queries that match an artist/track but were barely played.

    Matching is a case-insensitive substring test against artist and track
    names in Extended History. Queries with no name match are excluded so the
    table stays about music you looked for, not typos.
    """
    cols = ["search_query", "searches", "matched_plays", "example_match"]
    if not query_util.has_table(
        conn, "spotify", "searches"
    ) or not query_util.has_table(conn, "spotify", "plays"):
        return pd.DataFrame(columns=cols)
    return _query_df(
        conn,
        """
        WITH q AS (
            SELECT lower(trim(search_query)) AS query, count(*)::BIGINT AS searches
            FROM spotify.searches
            WHERE search_query IS NOT NULL AND length(trim(search_query)) >= 3
            GROUP BY 1
        ),
        names AS (
            SELECT DISTINCT
                lower(artist_name) AS artist_l,
                lower(track_name) AS track_l,
                artist_name,
                track_name
            FROM spotify.plays
            WHERE kind = 'track' AND artist_name IS NOT NULL
        ),
        matched AS (
            SELECT
                q.query,
                q.searches,
                n.artist_name,
                n.track_name
            FROM q
            JOIN names n
              ON contains(n.artist_l, q.query) OR contains(n.track_l, q.query)
        ),
        plays_for AS (
            SELECT
                m.query,
                m.searches,
                count(p.track_name)::BIGINT AS matched_plays,
                min(m.artist_name || ' — ' || m.track_name) AS example_match
            FROM matched m
            LEFT JOIN spotify.plays p
              ON p.kind = 'track'
             AND p.artist_name = m.artist_name
             AND p.track_name = m.track_name
            GROUP BY 1, 2
        )
        SELECT query AS search_query, searches, matched_plays, example_match
        FROM plays_for
        WHERE matched_plays <= ?
        ORDER BY searches DESC, matched_plays ASC, search_query
        LIMIT ?
        """,
        [max_plays, limit],
    )
