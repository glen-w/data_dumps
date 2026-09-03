"""MusicBrainz enrichment: genres and release decades without Spotify API."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import duckdb
import requests

from data_dumps.paths import warehouse_db

USER_AGENT = "data-dumps/0.2 (personal GDPR explorer)"
MB_BASE = "https://musicbrainz.org/ws/2"
REQUEST_INTERVAL = 1.0
REQUEST_TIMEOUT = 45
RETRYABLE_STATUS = frozenset({429, 503})


class MusicBrainzError(Exception):
    """MusicBrainz API or enrichment error."""


def _mb_get(path: str, *, retries: int = 5) -> dict[str, Any]:
    url = f"{MB_BASE}/{path}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_error: str | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = type(exc).__name__
            wait = 2 ** (attempt + 1)
            print(
                f"musicbrainz: {last_error} on {path}, "
                f"retry {attempt + 1}/{retries} in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)
            continue
        if resp.status_code in RETRYABLE_STATUS:
            last_error = f"HTTP {resp.status_code}"
            wait = 2 ** (attempt + 1)
            print(
                f"musicbrainz: {last_error} on {path}, "
                f"retry {attempt + 1}/{retries} in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)
            continue
        if resp.status_code != 200:
            raise MusicBrainzError(f"MusicBrainz {resp.status_code}: {url}")
        return resp.json()
    raise MusicBrainzError(
        f"MusicBrainz failed after {retries} retries: {url} ({last_error})"
    )


def _decade_from_date(date_str: str | None) -> str | None:
    if not date_str or len(date_str) < 4:
        return None
    try:
        year = int(date_str[:4])
    except ValueError:
        return None
    if year < 1900:
        return "pre-1900"
    decade = (year // 10) * 10
    return f"{decade}s"


def _primary_tag(tags: list[dict[str, Any]]) -> str | None:
    if not tags:
        return None
    scored = sorted(tags, key=lambda t: t.get("count", 0), reverse=True)
    return scored[0].get("name")


def create_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS spotify")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spotify.mb_artists (
            mbid VARCHAR PRIMARY KEY,
            name VARCHAR,
            primary_tag VARCHAR,
            country VARCHAR,
            begin_year INT,
            end_year INT,
            raw_json VARCHAR
        )
        """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spotify.mb_recordings (
            mbid VARCHAR PRIMARY KEY,
            name VARCHAR,
            artist_name VARCHAR,
            first_release_date VARCHAR,
            decade VARCHAR,
            raw_json VARCHAR
        )
        """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spotify.mb_match (
            entity_type VARCHAR,
            dump_name VARCHAR,
            dump_artist VARCHAR,
            mbid VARCHAR,
            confidence DOUBLE,
            matched_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (entity_type, dump_name, dump_artist)
        )
        """)


def _already_matched(
    conn: duckdb.DuckDBPyConnection,
    entity_type: str,
    dump_name: str,
    dump_artist: str = "",
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM spotify.mb_match
        WHERE entity_type = ? AND dump_name = ? AND dump_artist = ?
        """,
        [entity_type, dump_name, dump_artist],
    ).fetchone()
    return row is not None


def search_artist(name: str) -> tuple[str | None, float]:
    query = quote(f"artist:{name}")
    data = _mb_get(f"artist/?query={query}&limit=5&fmt=json")
    artists = data.get("artists", [])
    if not artists:
        return None, 0.0
    best = artists[0]
    score = float(best.get("score", 0))
    return best.get("id"), score / 100.0


def fetch_artist(mbid: str) -> dict[str, Any]:
    return _mb_get(f"artist/{mbid}?inc=tags+genres&fmt=json")


def search_recording(track: str, artist: str) -> tuple[str | None, float]:
    query = quote(f"recording:{track} AND artist:{artist}")
    data = _mb_get(f"recording/?query={query}&limit=5&fmt=json")
    recordings = data.get("recordings", [])
    if not recordings:
        return None, 0.0
    best = recordings[0]
    score = float(best.get("score", 0))
    return best.get("id"), score / 100.0


def fetch_recording(mbid: str) -> dict[str, Any]:
    return _mb_get(f"recording/{mbid}?inc=releases&fmt=json")


def enrich_artists(
    conn: duckdb.DuckDBPyConnection,
    *,
    limit: int | None = None,
    min_hours: float = 1.0,
) -> int:
    rows = conn.execute(
        """
        SELECT artist_name, round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE kind = 'track' AND artist_name IS NOT NULL
        GROUP BY 1
        HAVING sum(hours) >= ?
        ORDER BY hours DESC
        """,
        [min_hours],
    ).fetchall()
    if limit:
        rows = rows[:limit]
    enriched = 0
    for artist_name, _hours in rows:
        if _already_matched(conn, "artist", artist_name, ""):
            continue
        try:
            time.sleep(REQUEST_INTERVAL)
            mbid, confidence = search_artist(artist_name)
            if not mbid:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO spotify.mb_match
                    (entity_type, dump_name, dump_artist, mbid, confidence)
                    VALUES ('artist', ?, '', NULL, 0)
                    """,
                    [artist_name],
                )
                continue
            time.sleep(REQUEST_INTERVAL)
            detail = fetch_artist(mbid)
        except MusicBrainzError as exc:
            print(f"artist: {artist_name} skipped ({exc})", file=sys.stderr)
            continue
        tags = detail.get("tags", []) or detail.get("genres", [])
        begin = detail.get("life-span", {}).get("begin") or ""
        end = detail.get("life-span", {}).get("end") or ""
        begin_year = int(begin[:4]) if len(begin) >= 4 else None
        end_year = int(end[:4]) if len(end) >= 4 else None
        conn.execute(
            """
            INSERT OR REPLACE INTO spotify.mb_artists
            (mbid, name, primary_tag, country, begin_year, end_year, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                mbid,
                detail.get("name"),
                _primary_tag(tags),
                detail.get("country"),
                begin_year,
                end_year,
                json.dumps(detail),
            ],
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO spotify.mb_match
            (entity_type, dump_name, dump_artist, mbid, confidence)
            VALUES ('artist', ?, '', ?, ?)
            """,
            [artist_name, mbid, confidence],
        )
        enriched += 1
        print(f"artist: {artist_name} → {mbid} ({confidence:.2f})")
    return enriched


def enrich_recordings(
    conn: duckdb.DuckDBPyConnection,
    *,
    limit: int | None = None,
    min_hours: float = 0.5,
) -> int:
    rows = conn.execute(
        """
        SELECT track_name, artist_name, round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE kind = 'track' AND track_name IS NOT NULL AND artist_name IS NOT NULL
        GROUP BY 1, 2
        HAVING sum(hours) >= ?
        ORDER BY hours DESC
        """,
        [min_hours],
    ).fetchall()
    if limit:
        rows = rows[:limit]
    enriched = 0
    for track_name, artist_name, _hours in rows:
        if _already_matched(conn, "track", track_name, artist_name):
            continue
        try:
            time.sleep(REQUEST_INTERVAL)
            mbid, confidence = search_recording(track_name, artist_name)
            if not mbid:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO spotify.mb_match
                    (entity_type, dump_name, dump_artist, mbid, confidence)
                    VALUES ('track', ?, ?, NULL, 0)
                    """,
                    [track_name, artist_name],
                )
                continue
            time.sleep(REQUEST_INTERVAL)
            detail = fetch_recording(mbid)
        except MusicBrainzError as exc:
            print(
                f"track: {track_name} / {artist_name} skipped ({exc})",
                file=sys.stderr,
            )
            continue
        release_date = None
        for rel in detail.get("releases", []):
            date = rel.get("date")
            if date:
                release_date = date
                break
        decade = _decade_from_date(release_date)
        conn.execute(
            """
            INSERT OR REPLACE INTO spotify.mb_recordings
            (mbid, name, artist_name, first_release_date, decade, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                mbid,
                detail.get("title"),
                artist_name,
                release_date,
                decade,
                json.dumps(detail),
            ],
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO spotify.mb_match
            (entity_type, dump_name, dump_artist, mbid, confidence)
            VALUES ('track', ?, ?, ?, ?)
            """,
            [track_name, artist_name, mbid, confidence],
        )
        enriched += 1
        print(f"track: {track_name} / {artist_name} → {mbid} ({confidence:.2f})")
    return enriched


def count_pending(
    conn: duckdb.DuckDBPyConnection,
    *,
    artist_limit: int | None = None,
    track_limit: int | None = None,
    min_artist_hours: float = 1.0,
    min_track_hours: float = 0.5,
) -> dict[str, int]:
    """Count artists/tracks that would be enriched (excluding already matched)."""
    artist_rows = conn.execute(
        """
        SELECT artist_name
        FROM spotify.plays
        WHERE kind = 'track' AND artist_name IS NOT NULL
        GROUP BY 1
        HAVING sum(hours) >= ?
        ORDER BY sum(hours) DESC
        """,
        [min_artist_hours],
    ).fetchall()
    if artist_limit:
        artist_rows = artist_rows[:artist_limit]
    artists_pending = sum(
        1 for (name,) in artist_rows if not _already_matched(conn, "artist", name, "")
    )

    track_rows = conn.execute(
        """
        SELECT track_name, artist_name
        FROM spotify.plays
        WHERE kind = 'track' AND track_name IS NOT NULL AND artist_name IS NOT NULL
        GROUP BY 1, 2
        HAVING sum(hours) >= ?
        ORDER BY sum(hours) DESC
        """,
        [min_track_hours],
    ).fetchall()
    if track_limit:
        track_rows = track_rows[:track_limit]
    tracks_pending = sum(
        1
        for track_name, artist_name in track_rows
        if not _already_matched(conn, "track", track_name, artist_name)
    )
    return {
        "artists_pending": artists_pending,
        "tracks_pending": tracks_pending,
        "artists_total": len(artist_rows),
        "tracks_total": len(track_rows),
    }


def run_enrichment(
    conn: duckdb.DuckDBPyConnection,
    *,
    artist_limit: int | None = None,
    track_limit: int | None = None,
    min_artist_hours: float = 1.0,
    min_track_hours: float = 0.5,
) -> dict[str, int]:
    create_schema(conn)
    artists = enrich_artists(conn, limit=artist_limit, min_hours=min_artist_hours)
    tracks = enrich_recordings(conn, limit=track_limit, min_hours=min_track_hours)
    return {"artists_enriched": artists, "tracks_enriched": tracks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enrich Spotify plays with MusicBrainz metadata",
        epilog=(
            "Stop the Marimo notebook or docker compose app before running — "
            "DuckDB single-writer (see docs/WAREHOUSE.md). "
            "--artist-limit / --track-limit default to 0 (no cap): the full "
            "library is the assumed run. MusicBrainz has no free-tier count "
            "quota (only ~1 req/s). Pass a positive N to batch a smaller set."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=warehouse_db(),
        help="DuckDB catalog path",
    )
    parser.add_argument(
        "--artist-limit",
        type=int,
        default=0,
        help="Max artists to enrich (default 0 = full dataset, no cap)",
    )
    parser.add_argument(
        "--track-limit",
        type=int,
        default=0,
        help="Max tracks to enrich (default 0 = full dataset, no cap)",
    )
    parser.add_argument(
        "--min-artist-hours",
        type=float,
        default=1.0,
        help="Minimum lifetime hours to enrich an artist",
    )
    parser.add_argument(
        "--min-track-hours",
        type=float,
        default=0.5,
        help="Minimum lifetime hours to enrich a track",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pending counts without calling MusicBrainz",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"error: no warehouse at {args.db}", file=sys.stderr)
        return 1

    try:
        conn = duckdb.connect(str(args.db))
    except duckdb.Error as exc:
        print(
            f"error: cannot open {args.db}: {exc}. "
            "Stop the Marimo notebook first (DuckDB single-writer).",
            file=sys.stderr,
        )
        return 1

    artist_limit = args.artist_limit or None
    track_limit = args.track_limit or None

    try:
        if args.dry_run:
            create_schema(conn)
            stats = count_pending(
                conn,
                artist_limit=artist_limit,
                track_limit=track_limit,
                min_artist_hours=args.min_artist_hours,
                min_track_hours=args.min_track_hours,
            )
            print(
                f"dry-run: {stats['artists_pending']} artists pending "
                f"(of {stats['artists_total']}), "
                f"{stats['tracks_pending']} tracks pending "
                f"(of {stats['tracks_total']})"
            )
            if artist_limit or track_limit:
                print(
                    "note: counts are capped by --artist-limit / --track-limit "
                    "(not total library size). Use 0 for no cap."
                )
            return 0
        stats = run_enrichment(
            conn,
            artist_limit=artist_limit,
            track_limit=track_limit,
            min_artist_hours=args.min_artist_hours,
            min_track_hours=args.min_track_hours,
        )
        print(
            f"done: {stats['artists_enriched']} artists, "
            f"{stats['tracks_enriched']} tracks enriched"
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
