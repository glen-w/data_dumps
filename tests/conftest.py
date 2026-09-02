"""Synthetic DuckDB fixtures for tests (no real GDPR dump)."""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from data_dumps.enrich.musicbrainz import create_schema


# Keep ingest/load from writing into the developer's live raw/ warehouse.
@pytest.fixture(autouse=True)
def isolate_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))


def _insert_play(
    conn: duckdb.DuckDBPyConnection,
    *,
    played_at: str,
    artist: str | None,
    track: str | None,
    track_id: str | None,
    hours: float,
    kind: str = "track",
    album: str | None = "Album",
    platform: str = "android",
    country: str = "IT",
    skipped: bool = False,
    full_play: bool = True,
    shuffle: bool = False,
    reason_start: str = "clickrow",
    show: str | None = None,
) -> None:
    ts = datetime.fromisoformat(played_at)
    ms = int(hours * 3600000)
    conn.execute(
        """
        INSERT INTO spotify.plays VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            ts,
            ts,
            ts,
            ms,
            hours,
            kind,
            track,
            artist,
            album,
            f"spotify:track:{track_id}" if track_id else None,
            None,
            show,
            None,
            None,
            None,
            track_id,
            None,
            reason_start,
            "trackdone" if full_play else "endplay",
            full_play,
            shuffle,
            skipped,
            False,
            False,
            country,
            platform,
            platform,
            ts.year,
            ts.month,
        ],
    )


def make_plays_conn(tmp_path: Path) -> tuple[duckdb.DuckDBPyConnection, Path]:
    db_path = tmp_path / "test.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE SCHEMA spotify")
    conn.execute("""
        CREATE TABLE spotify.plays (
            ts_utc TIMESTAMP,
            played_at TIMESTAMPTZ,
            played_at_local TIMESTAMP,
            ms_played BIGINT,
            hours DOUBLE,
            kind VARCHAR,
            track_name VARCHAR,
            artist_name VARCHAR,
            album_name VARCHAR,
            spotify_track_uri VARCHAR,
            episode_name VARCHAR,
            episode_show_name VARCHAR,
            spotify_episode_uri VARCHAR,
            audiobook_title VARCHAR,
            audiobook_chapter_title VARCHAR,
            track_id VARCHAR,
            episode_id VARCHAR,
            reason_start VARCHAR,
            reason_end VARCHAR,
            full_play BOOLEAN,
            shuffle BOOLEAN,
            skipped BOOLEAN,
            offline BOOLEAN,
            incognito_mode BOOLEAN,
            conn_country VARCHAR,
            platform_bucket VARCHAR,
            platform_raw VARCHAR,
            year BIGINT,
            month BIGINT
        )
        """)

    # Alpha — dominant artist, many plays in 2018–2020
    for i in range(12):
        _insert_play(
            conn,
            played_at=f"2018-06-{i + 1:02d}T10:00:00",
            artist="Alpha",
            track=f"Alpha Song {i}",
            track_id=f"alpha{i}",
            hours=2.0,
            platform="android",
            country="IT",
        )
    for i in range(5):
        _insert_play(
            conn,
            played_at=f"2020-03-{i + 1:02d}T12:00:00",
            artist="Alpha",
            track="Alpha Song 0",
            track_id="alpha0",
            hours=1.0,
        )

    # Old Star — forgotten pattern (heavy 2016, silent since)
    for i in range(15):
        _insert_play(
            conn,
            played_at=f"2016-03-{i + 1:02d}T08:00:00",
            artist="Old Star",
            track="Ancient Hit",
            track_id="old1",
            hours=2.0,
        )

    # Return Act — comeback (2016 then 2020)
    _insert_play(
        conn,
        played_at="2016-01-15T09:00:00",
        artist="Return Act",
        track="Early Song",
        track_id="ret1",
        hours=3.0,
    )
    for i in range(4):
        _insert_play(
            conn,
            played_at=f"2020-08-{i + 1:02d}T14:00:00",
            artist="Return Act",
            track="Back Again",
            track_id="ret2",
            hours=2.0,
        )

    # Repeat vs discovery tracks
    _insert_play(
        conn,
        played_at="2018-05-01T11:00:00",
        artist="Gamma",
        track="Catalog Track",
        track_id="cat1",
        hours=1.0,
    )
    for i in range(3):
        _insert_play(
            conn,
            played_at=f"2020-05-{i + 1:02d}T11:00:00",
            artist="Gamma",
            track="Catalog Track",
            track_id="cat1",
            hours=1.0,
        )
    _insert_play(
        conn,
        played_at="2020-06-01T11:00:00",
        artist="Gamma",
        track="Fresh Track",
        track_id="new1",
        hours=2.0,
    )

    # Episode / platform / skip variety
    _insert_play(
        conn,
        played_at="2019-07-01T20:00:00",
        artist=None,
        track=None,
        track_id=None,
        hours=1.5,
        kind="episode",
        show="Test Podcast",
    )
    _insert_play(
        conn,
        played_at="2019-07-02T21:00:00",
        artist="Skip Artist",
        track="Skipped",
        track_id="skip1",
        hours=0.1,
        skipped=True,
        full_play=False,
        shuffle=True,
        reason_start="fwdbtn",
        platform="osx",
        country="GB",
    )
    _insert_play(
        conn,
        played_at="2019-08-01T22:00:00",
        artist="Echo Artist",
        track="Echo Song",
        track_id="echo1",
        hours=1.0,
        platform="echo_dot",
        country="DE",
    )

    return conn, db_path


def populate_mb_data(conn: duckdb.DuckDBPyConnection) -> None:
    create_schema(conn)
    conn.execute("""
        INSERT INTO spotify.mb_artists VALUES
        ('mbid-alpha', 'Alpha', 'rock', 'US', 1990, NULL, '{}')
        """)
    conn.execute("""
        INSERT INTO spotify.mb_match VALUES
        ('artist', 'Alpha', '', 'mbid-alpha', 0.95, current_timestamp)
        """)
    conn.execute("""
        INSERT INTO spotify.mb_recordings VALUES
        ('mbid-cat1', 'Catalog Track', 'Gamma', '2010', '2010s', '{}')
        """)
    conn.execute("""
        INSERT INTO spotify.mb_match VALUES
        ('track', 'Catalog Track', 'Gamma', 'mbid-cat1', 0.9, current_timestamp)
        """)


@pytest.fixture
def plays_conn(tmp_path):
    conn, path = make_plays_conn(tmp_path)
    yield conn, path
    conn.close()


@pytest.fixture
def plays_conn_mb(plays_conn):
    conn, path = plays_conn
    populate_mb_data(conn)
    return conn, path


def make_mini_spotify_zip(path: Path) -> Path:
    """Tiny Extended History zip for ingest smoke tests."""
    json_path = Path(__file__).parent / "fixtures" / "streaming_history_mini.json"
    zip_path = path / "mini_spotify.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        inner = "Spotify Extended Streaming History/Streaming_History_Audio_0.json"
        zf.write(json_path, inner)
    return zip_path
