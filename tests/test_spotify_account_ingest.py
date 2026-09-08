"""Spotify Account Data ingest smoke tests."""

import json
import zipfile
from pathlib import Path

import duckdb

from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.base import Source
from data_dumps.sources.spotify_account import SpotifyAccountSource
from data_dumps.spotify_queries import (
    has_account_data,
    library_counts,
    library_never_played,
    library_overlap,
    playlist_sizes,
    search_volume,
    top_searches,
)

from .conftest import make_mini_spotify_zip


def make_mini_account_zip(path: Path) -> Path:
    zip_path = path / "mini_account.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        prefix = "Spotify Account Data"
        zf.writestr(
            f"{prefix}/StreamingHistory_music_0.json",
            json.dumps(
                [
                    {
                        "endTime": "2025-09-05 03:49",
                        "artistName": "Wax",
                        "trackName": "Ox",
                        "msPlayed": 172140,
                    },
                    {
                        "endTime": "2025-09-06 10:00",
                        "artistName": "Other",
                        "trackName": "Song",
                        "msPlayed": 1000,
                    },
                ]
            ),
        )
        zf.writestr(
            f"{prefix}/StreamingHistory_podcast_0.json",
            json.dumps(
                [
                    {
                        "endTime": "2025-09-05 04:00",
                        "podcastName": "Show",
                        "episodeName": "Ep 1",
                        "msPlayed": 2000,
                    }
                ]
            ),
        )
        zf.writestr(
            f"{prefix}/YourLibrary.json",
            json.dumps(
                {
                    "tracks": [
                        {
                            "album": "A",
                            "artist": "Wax",
                            "track": "Ox",
                            "uri": "spotify:track:abc",
                        },
                        {
                            "album": "B",
                            "artist": "Never",
                            "track": "Heard",
                            "uri": "spotify:track:def",
                        },
                    ],
                    "albums": [],
                    "shows": [],
                    "episodes": [],
                    "artists": [{"name": "Wax", "uri": "spotify:artist:x"}],
                }
            ),
        )
        zf.writestr(
            f"{prefix}/Playlist1.json",
            json.dumps(
                {
                    "playlists": [
                        {
                            "name": "Favs",
                            "lastModifiedDate": "2026-08-14",
                            "numberOfFollowers": 0,
                            "items": [
                                {
                                    "track": {
                                        "trackName": "Kiss Me",
                                        "artistName": "Sixpence",
                                        "albumName": "S",
                                        "trackUri": "spotify:track:1",
                                    },
                                    "addedDate": "2026-08-14",
                                }
                            ],
                        }
                    ]
                }
            ),
        )
        zf.writestr(
            f"{prefix}/SearchQueries.json",
            json.dumps(
                [
                    {
                        "platform": "OSX_ARM64",
                        "searchTime": "2026-06-11T17:43:53.617Z[UTC]",
                        "searchQuery": "wax",
                        "searchInteractionURIs": "[]",
                    }
                ]
            ),
        )
        zf.writestr(
            f"{prefix}/Identity.json",
            json.dumps({"displayName": "secret", "firstName": "nope"}),
        )
    return zip_path


def test_detect_account_zip(tmp_path):
    zip_path = make_mini_account_zip(tmp_path)
    source = SpotifyAccountSource()
    assert source.detect(zip_path)
    assert isinstance(source, Source)
    assert pick_source(zip_path) is not None
    assert pick_source(zip_path).name == "spotify_account"


def test_detect_rejects_extended_history(tmp_path):
    zip_path = make_mini_spotify_zip(tmp_path)
    assert not SpotifyAccountSource().detect(zip_path)


def test_load_account_zip(tmp_path):
    zip_path = make_mini_account_zip(tmp_path)
    db_path = tmp_path / "ingest.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE SCHEMA spotify")
    conn.execute("CREATE TABLE spotify.plays (track_name VARCHAR)")
    conn.execute("INSERT INTO spotify.plays VALUES ('keep-me')")
    source = SpotifyAccountSource()
    source.load(zip_path, conn)
    inv = source.inventory(conn)
    assert inv["n_account_plays"] == 3
    assert inv["n_library"] == 3
    assert inv["n_playlists"] == 1
    assert inv["n_searches"] == 1
    assert "not spotify.plays" in inv["summary"]

    n_plays = conn.execute("SELECT count(*) FROM spotify.plays").fetchone()
    assert n_plays is not None and n_plays[0] == 1

    kinds = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT kind FROM spotify.account_plays"
        ).fetchall()
    }
    assert kinds == {"track", "episode"}

    raw_names = {p.name for p in raw_dir("spotify_account").iterdir()}
    assert "Identity.json" not in raw_names
    assert "YourLibrary.json" in raw_names
    conn.close()


def test_cli_ingest_account(tmp_path):
    zip_path = make_mini_account_zip(tmp_path)
    db_path = tmp_path / "catalog.duckdb"
    rc = main([str(zip_path), "--db", str(db_path)])
    assert rc == 0
    conn = duckdb.connect(str(db_path), read_only=True)
    n = conn.execute("SELECT count(*) FROM spotify.playlist_items").fetchone()
    assert n is not None and n[0] == 1
    conn.close()


def test_account_queries(tmp_path):
    zip_path = make_mini_account_zip(tmp_path)
    db_path = tmp_path / "q.duckdb"
    conn = duckdb.connect(str(db_path))
    SpotifyAccountSource().load(zip_path, conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS spotify.plays (track_name VARCHAR, artist_name VARCHAR, kind VARCHAR, hours DOUBLE)"
    )
    conn.execute("INSERT INTO spotify.plays VALUES ('Ox', 'Wax', 'track', 2.0)")
    assert has_account_data(conn)
    counts = library_counts(conn)
    assert "track" in counts["item_kind"].tolist()
    overlap = library_overlap(conn)
    assert "Ox" in overlap["track_name"].tolist()
    never = library_never_played(conn)
    assert "Heard" in never["track_name"].tolist()
    assert playlist_sizes(conn).iloc[0]["playlist_name"] == "Favs"
    assert not search_volume(conn).empty
    assert top_searches(conn).iloc[0]["search_query"] == "wax"
    conn.close()
