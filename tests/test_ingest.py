"""Ingest smoke tests on mini Spotify zip and extracted folders."""

import shutil
from pathlib import Path

import duckdb
import pytest

from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.base import Source
from data_dumps.sources.spotify import SpotifySource

from .conftest import make_mini_spotify_zip

FIXTURE_JSON = Path(__file__).parent / "fixtures" / "streaming_history_mini.json"
IP_COLUMNS = {"ip_addr", "ip_addr_decrypted"}


def _play_columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in conn.execute("DESCRIBE spotify.plays").fetchall()}


def _assert_ips_stripped(conn: duckdb.DuckDBPyConnection) -> None:
    cols = _play_columns(conn)
    leaked = cols & IP_COLUMNS
    assert not leaked, f"IP columns survived ingest: {leaked}"
    tables = {r[0] for r in conn.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'spotify'
            """).fetchall()}
    assert "plays" in tables
    assert "plays_raw" not in tables


def test_detect_mini_zip(tmp_path):
    zip_path = make_mini_spotify_zip(tmp_path)
    source = SpotifySource()
    assert source.detect(zip_path)
    assert isinstance(source, Source)


def test_detect_history_folder(tmp_path):
    folder = tmp_path / "Spotify Extended Streaming History"
    folder.mkdir()
    shutil.copy2(FIXTURE_JSON, folder / "Streaming_History_Audio_2016.json")
    assert SpotifySource().detect(folder)


def test_detect_extracted_zip_root(tmp_path):
    root = tmp_path / "extracted"
    nested = root / "Spotify Extended Streaming History"
    nested.mkdir(parents=True)
    shutil.copy2(FIXTURE_JSON, nested / "Streaming_History_Audio_2016.json")
    assert SpotifySource().detect(root)


def test_detect_rejects_unrelated_dir(tmp_path):
    (tmp_path / "notes.txt").write_text("not a dump")
    assert not SpotifySource().detect(tmp_path)
    assert pick_source(tmp_path) is None


def test_pick_source_zip(tmp_path):
    zip_path = make_mini_spotify_zip(tmp_path)
    source = pick_source(zip_path)
    assert source is not None
    assert source.name == "spotify"


def test_load_mini_zip(tmp_path):
    zip_path = make_mini_spotify_zip(tmp_path)
    db_path = tmp_path / "ingest.duckdb"
    conn = duckdb.connect(str(db_path))
    source = SpotifySource()
    source.load(zip_path, conn)
    inv = source.inventory(conn)
    assert inv["n_plays"] == 3
    assert "summary" in inv
    assert "spotify.plays" in inv["summary"]
    kinds = conn.execute(
        "SELECT DISTINCT kind FROM spotify.plays ORDER BY 1"
    ).fetchall()
    assert ("track",) in kinds
    assert ("episode",) in kinds
    platforms = conn.execute(
        "SELECT DISTINCT platform_bucket FROM spotify.plays ORDER BY 1"
    ).fetchall()
    assert ("android",) in platforms
    assert ("echo_dot",) in platforms
    names = conn.execute(
        "SELECT track_name FROM spotify.plays WHERE kind = 'track' ORDER BY 1"
    ).fetchall()
    assert ("Mini Song A",) in names
    _assert_ips_stripped(conn)
    raw_json = list(raw_dir("spotify").glob("*.json"))
    assert raw_json, "expected extracted JSON under DATA_DUMPS_ROOT/raw/spotify"
    conn.close()


def test_load_from_nested_folder(tmp_path):
    root = tmp_path / "extracted"
    nested = root / "Spotify Extended Streaming History"
    nested.mkdir(parents=True)
    shutil.copy2(FIXTURE_JSON, nested / "Streaming_History_Audio_2016.json")
    db_path = tmp_path / "folder.duckdb"
    conn = duckdb.connect(str(db_path))
    SpotifySource().load(root, conn)
    n = conn.execute("SELECT count(*) FROM spotify.plays").fetchone()
    assert n is not None and n[0] == 3
    _assert_ips_stripped(conn)
    conn.close()


def test_cli_ingest_help():
    with pytest.raises(SystemExit) as ei:
        main(["--help"])
    assert ei.value.code == 0


def test_cli_ingest_mini(tmp_path):
    zip_path = make_mini_spotify_zip(tmp_path)
    db_path = tmp_path / "catalog.duckdb"
    rc = main([str(zip_path), "--db", str(db_path)])
    assert rc == 0
    conn = duckdb.connect(str(db_path), read_only=True)
    n = conn.execute("SELECT count(*) FROM spotify.plays").fetchone()
    assert n is not None and n[0] == 3
    _assert_ips_stripped(conn)
    conn.close()


def test_all_null_string_columns_are_varchar(tmp_path):
    """A dump with no audiobooks must not leave audiobook_* typed as JSON.

    ``read_json`` infers all-NULL columns as JSON; queries that coalesce them
    with track/episode names (e.g. ``milestones``) then fail to cast.
    """
    from data_dumps.spotify_queries import FilterState, milestones

    zip_path = make_mini_spotify_zip(tmp_path)
    conn = duckdb.connect(str(tmp_path / "types.duckdb"))
    SpotifySource().load(zip_path, conn)
    types = {
        row[0]: row[1] for row in conn.execute("DESCRIBE spotify.plays").fetchall()
    }
    for col in (
        "track_name",
        "artist_name",
        "album_name",
        "episode_name",
        "episode_show_name",
        "audiobook_title",
        "audiobook_chapter_title",
        "reason_start",
        "reason_end",
        "conn_country",
    ):
        assert types[col] == "VARCHAR", (col, types[col])
    ms = milestones(conn, FilterState())
    assert ms.iloc[0]["longest_play_title"] is not None
    conn.close()


def test_cli_missing_path(tmp_path):
    rc = main([str(tmp_path / "nope.zip")])
    assert rc == 1
