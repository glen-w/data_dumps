"""MusicBrainz enrichment helpers and CLI."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from data_dumps.enrich.musicbrainz import (
    MusicBrainzError,
    _already_matched,
    _decade_from_date,
    _mb_get,
    _primary_tag,
    count_pending,
    create_schema,
    enrich_artists,
)


def test_decade_from_date():
    assert _decade_from_date("1984-06-01") == "1980s"
    assert _decade_from_date("1899") == "pre-1900"
    assert _decade_from_date(None) is None


def test_primary_tag():
    tags = [{"name": "rock", "count": 10}, {"name": "pop", "count": 50}]
    assert _primary_tag(tags) == "pop"
    assert _primary_tag([]) is None


def test_already_matched(plays_conn):
    conn, _ = plays_conn
    create_schema(conn)
    conn.execute("""
        INSERT INTO spotify.mb_match
        (entity_type, dump_name, dump_artist, mbid, confidence)
        VALUES ('artist', 'Alpha', '', NULL, 0)
        """)
    assert _already_matched(conn, "artist", "Alpha", "")


def test_count_pending(plays_conn):
    conn, _ = plays_conn
    create_schema(conn)
    stats = count_pending(conn, artist_limit=10, track_limit=10, min_artist_hours=1.0)
    assert stats["artists_pending"] > 0
    assert stats["tracks_pending"] > 0


def test_enrich_artists_mock(plays_conn):
    conn, _ = plays_conn
    create_schema(conn)
    fake_artist = {
        "name": "Alpha",
        "tags": [{"name": "rock", "count": 5}],
        "life-span": {"begin": "1990", "end": ""},
        "country": "US",
    }
    with patch(
        "data_dumps.enrich.musicbrainz.search_artist",
        return_value=("mbid-test", 0.9),
    ):
        with patch(
            "data_dumps.enrich.musicbrainz.fetch_artist",
            return_value=fake_artist,
        ):
            with patch("data_dumps.enrich.musicbrainz.time.sleep"):
                n = enrich_artists(conn, limit=1, min_hours=1.0)
    assert n == 1
    row = conn.execute(
        "SELECT mbid FROM spotify.mb_match WHERE mbid = 'mbid-test'"
    ).fetchone()
    assert row is not None and row[0] == "mbid-test"


def test_cli_defaults_are_uncapped(plays_conn):
    conn, db_path = plays_conn
    conn.close()
    from data_dumps.enrich.musicbrainz import main

    with patch(
        "data_dumps.enrich.musicbrainz.run_enrichment",
        return_value={"artists_enriched": 0, "tracks_enriched": 0},
    ) as mock_run:
        rc = main(["--db", str(db_path)])
    assert rc == 0
    kwargs = mock_run.call_args.kwargs
    assert kwargs["artist_limit"] is None
    assert kwargs["track_limit"] is None


def test_dry_run_cli(plays_conn, tmp_path):
    conn, db_path = plays_conn
    conn.close()
    from data_dumps.enrich.musicbrainz import main

    rc = main(["--db", str(db_path), "--dry-run", "--artist-limit", "5"])
    assert rc == 0


def test_db_lock_message(plays_conn):
    conn, db_path = plays_conn
    conn.close()
    from data_dumps.enrich.musicbrainz import main

    rc = main(["--db", str(db_path), "--dry-run"])
    assert rc == 0


def test_mb_get_retries_timeout():
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"artists": []}
    with patch(
        "data_dumps.enrich.musicbrainz.requests.get",
        side_effect=[requests.ReadTimeout("timed out"), ok],
    ) as mock_get:
        with patch("data_dumps.enrich.musicbrainz.time.sleep"):
            data = _mb_get("artist/?query=x")
    assert data == {"artists": []}
    assert mock_get.call_count == 2


def test_mb_get_retries_503():
    busy = MagicMock(status_code=503)
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"ok": True}
    with patch(
        "data_dumps.enrich.musicbrainz.requests.get",
        side_effect=[busy, ok],
    ):
        with patch("data_dumps.enrich.musicbrainz.time.sleep"):
            assert _mb_get("artist/abc") == {"ok": True}


def test_mb_get_exhausted_retries():
    with patch(
        "data_dumps.enrich.musicbrainz.requests.get",
        side_effect=requests.ReadTimeout("timed out"),
    ):
        with patch("data_dumps.enrich.musicbrainz.time.sleep"):
            with pytest.raises(MusicBrainzError, match="failed after"):
                _mb_get("artist/abc", retries=2)


def test_enrich_artists_skips_timeout(plays_conn):
    conn, _ = plays_conn
    create_schema(conn)
    with patch(
        "data_dumps.enrich.musicbrainz.search_artist",
        side_effect=MusicBrainzError("timed out"),
    ):
        with patch("data_dumps.enrich.musicbrainz.time.sleep"):
            n = enrich_artists(conn, limit=1, min_hours=1.0)
    assert n == 0
    row = conn.execute("SELECT count(*) FROM spotify.mb_match").fetchone()
    assert row is not None and row[0] == 0
