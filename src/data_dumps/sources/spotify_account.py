"""Spotify Account Data ZIP → DuckDB (library, playlists, searches).

This is a different export from Extended Streaming History. It must never
replace ``spotify.plays``. Account streaming JSON is a ~1-year slice with
names only (no URI / platform / skip).
"""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

ACCOUNT_FOLDER = "Spotify Account Data"
LOCAL_TZ = ZoneInfo("Europe/Rome")

KEEP_JSON_EXACT = {"YourLibrary.json", "Playlist1.json", "SearchQueries.json"}

ACCOUNT_TABLES = [
    "spotify.account_plays",
    "spotify.library_items",
    "spotify.playlists",
    "spotify.playlist_items",
    "spotify.searches",
]


def _is_keep_json(name: str) -> bool:
    base = Path(name).name
    if base in KEEP_JSON_EXACT:
        return True
    return base.startswith("StreamingHistory_") and base.endswith(".json")


def _parse_end_time(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_search_time(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.replace("[UTC]", "").replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _local_pair(ts: datetime | None) -> tuple[datetime | None, datetime | None]:
    if ts is None:
        return None, None
    utc_naive = ts.astimezone(UTC).replace(tzinfo=None)
    local_naive = ts.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return utc_naive, local_naive


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


class SpotifyAccountSource:
    name = "spotify_account"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    return any(ACCOUNT_FOLDER in n for n in zf.namelist())
            except (OSError, zipfile.BadZipFile):
                return False
        return self._account_dir(path) is not None

    def _account_dir(self, path: Path) -> Path | None:
        if not path.is_dir():
            return None
        if self._looks_like_account(path):
            return path
        nested = path / ACCOUNT_FOLDER
        if nested.is_dir() and self._looks_like_account(nested):
            return nested
        return None

    def _looks_like_account(self, path: Path) -> bool:
        names = {p.name for p in path.iterdir() if p.is_file()}
        if "YourLibrary.json" in names or "Playlist1.json" in names:
            return True
        return any(
            n.startswith("StreamingHistory_") and n.endswith(".json") for n in names
        )

    def tables(self) -> list[str]:
        return list(ACCOUNT_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        raw = self._materialize(path)
        conn.execute("CREATE SCHEMA IF NOT EXISTS spotify")
        for table in (
            "account_plays",
            "library_items",
            "playlist_items",
            "playlists",
            "searches",
        ):
            conn.execute(f"DROP TABLE IF EXISTS spotify.{table}")

        conn.execute("""
            CREATE TABLE spotify.account_plays (
                played_at TIMESTAMP,
                played_at_local TIMESTAMP,
                ms_played BIGINT,
                hours DOUBLE,
                kind VARCHAR,
                track_name VARCHAR,
                artist_name VARCHAR,
                episode_name VARCHAR,
                episode_show_name VARCHAR,
                audiobook_title VARCHAR,
                audiobook_chapter_title VARCHAR,
                audiobook_author VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE spotify.library_items (
                item_kind VARCHAR,
                name VARCHAR,
                artist_name VARCHAR,
                album_name VARCHAR,
                show_name VARCHAR,
                publisher VARCHAR,
                uri VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE spotify.playlists (
                playlist_name VARCHAR,
                last_modified DATE,
                n_followers BIGINT,
                n_items BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE spotify.playlist_items (
                playlist_name VARCHAR,
                position INTEGER,
                added_date DATE,
                track_name VARCHAR,
                artist_name VARCHAR,
                album_name VARCHAR,
                track_uri VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE spotify.searches (
                searched_at TIMESTAMP,
                searched_at_local TIMESTAMP,
                search_query VARCHAR,
                platform VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)

        self._insert(conn, "spotify.account_plays", self._plays_frame(raw))
        self._insert(conn, "spotify.library_items", self._library_frame(raw))
        playlists_df, items_df = self._playlist_frames(raw)
        self._insert(conn, "spotify.playlists", playlists_df)
        self._insert(conn, "spotify.playlist_items", items_df)
        self._insert(conn, "spotify.searches", self._searches_frame(raw))

    def _materialize(self, path: Path) -> Path:
        dest = raw_dir("spotify_account")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if ACCOUNT_FOLDER not in name or not _is_keep_json(name):
                        continue
                    zf.extract(name, dest)
            nested = dest / ACCOUNT_FOLDER
            if nested.is_dir():
                for f in nested.iterdir():
                    shutil.move(str(f), str(dest / f.name))
                shutil.rmtree(nested, ignore_errors=True)
        else:
            src = self._account_dir(path)
            if src is None:
                raise FileNotFoundError(f"No Spotify Account Data JSON in {path}")
            for f in src.iterdir():
                if f.is_file() and _is_keep_json(f.name):
                    shutil.copy2(f, dest / f.name)
        return dest

    def _insert(
        self, conn: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame
    ) -> None:
        tmp = "_sa_" + table.replace(".", "_")
        conn.register(tmp, df)
        conn.execute(f"INSERT INTO {table} BY NAME SELECT * FROM {tmp}")
        conn.unregister(tmp)

    def _plays_frame(self, raw: Path) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        specs = (
            ("StreamingHistory_music_*.json", "track"),
            ("StreamingHistory_podcast_*.json", "episode"),
            ("StreamingHistory_audiobook_*.json", "audiobook"),
        )
        for pattern, kind in specs:
            for path in sorted(raw.glob(pattern)):
                payload = _read_json(path)
                if not isinstance(payload, list):
                    continue
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    ts = _parse_end_time(item.get("endTime"))
                    utc_naive, local_naive = _local_pair(ts)
                    ms = int(item.get("msPlayed") or 0)
                    rows.append(
                        {
                            "played_at": utc_naive,
                            "played_at_local": local_naive,
                            "ms_played": ms,
                            "hours": ms / 3_600_000.0,
                            "kind": kind,
                            "track_name": item.get("trackName"),
                            "artist_name": item.get("artistName")
                            or item.get("authorName"),
                            "episode_name": item.get("episodeName"),
                            "episode_show_name": item.get("podcastName"),
                            "audiobook_title": item.get("audiobookName"),
                            "audiobook_chapter_title": item.get("chapterName"),
                            "audiobook_author": (
                                item.get("authorName") if kind == "audiobook" else None
                            ),
                            "year": local_naive.year if local_naive else None,
                            "month": local_naive.month if local_naive else None,
                        }
                    )
        if not rows:
            return pd.DataFrame(
                columns=[
                    "played_at",
                    "played_at_local",
                    "ms_played",
                    "hours",
                    "kind",
                    "track_name",
                    "artist_name",
                    "episode_name",
                    "episode_show_name",
                    "audiobook_title",
                    "audiobook_chapter_title",
                    "audiobook_author",
                    "year",
                    "month",
                ]
            )
        return pd.DataFrame(rows)

    def _library_frame(self, raw: Path) -> pd.DataFrame:
        path = raw / "YourLibrary.json"
        columns = [
            "item_kind",
            "name",
            "artist_name",
            "album_name",
            "show_name",
            "publisher",
            "uri",
        ]
        if not path.is_file():
            return pd.DataFrame(columns=columns)
        payload = _read_json(path)
        if not isinstance(payload, dict):
            return pd.DataFrame(columns=columns)
        rows: list[dict[str, Any]] = []
        for item in payload.get("tracks") or []:
            rows.append(
                {
                    "item_kind": "track",
                    "name": item.get("track"),
                    "artist_name": item.get("artist"),
                    "album_name": item.get("album"),
                    "show_name": None,
                    "publisher": None,
                    "uri": item.get("uri"),
                }
            )
        for item in payload.get("albums") or []:
            rows.append(
                {
                    "item_kind": "album",
                    "name": item.get("album"),
                    "artist_name": item.get("artist"),
                    "album_name": item.get("album"),
                    "show_name": None,
                    "publisher": None,
                    "uri": item.get("uri"),
                }
            )
        for item in payload.get("shows") or []:
            rows.append(
                {
                    "item_kind": "show",
                    "name": item.get("name"),
                    "artist_name": None,
                    "album_name": None,
                    "show_name": item.get("name"),
                    "publisher": item.get("publisher"),
                    "uri": item.get("uri"),
                }
            )
        for item in payload.get("episodes") or []:
            rows.append(
                {
                    "item_kind": "episode",
                    "name": item.get("name"),
                    "artist_name": None,
                    "album_name": None,
                    "show_name": item.get("show"),
                    "publisher": None,
                    "uri": item.get("uri"),
                }
            )
        for item in payload.get("artists") or []:
            rows.append(
                {
                    "item_kind": "artist",
                    "name": item.get("name"),
                    "artist_name": item.get("name"),
                    "album_name": None,
                    "show_name": None,
                    "publisher": None,
                    "uri": item.get("uri"),
                }
            )
        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(rows)

    def _playlist_frames(self, raw: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
        pl_cols = ["playlist_name", "last_modified", "n_followers", "n_items"]
        item_cols = [
            "playlist_name",
            "position",
            "added_date",
            "track_name",
            "artist_name",
            "album_name",
            "track_uri",
        ]
        path = raw / "Playlist1.json"
        empty_pl = pd.DataFrame(columns=pl_cols)
        empty_items = pd.DataFrame(columns=item_cols)
        if not path.is_file():
            return empty_pl, empty_items
        payload = _read_json(path)
        playlists = payload.get("playlists") if isinstance(payload, dict) else None
        if not playlists:
            return empty_pl, empty_items
        pl_rows: list[dict[str, Any]] = []
        item_rows: list[dict[str, Any]] = []
        for pl in playlists:
            name = pl.get("name")
            items = pl.get("items") or []
            last_mod = pl.get("lastModifiedDate")
            last_date = None
            if isinstance(last_mod, str) and last_mod:
                try:
                    last_date = datetime.strptime(last_mod[:10], "%Y-%m-%d").date()
                except ValueError:
                    last_date = None
            pl_rows.append(
                {
                    "playlist_name": name,
                    "last_modified": last_date,
                    "n_followers": int(pl.get("numberOfFollowers") or 0),
                    "n_items": len(items),
                }
            )
            for idx, item in enumerate(items):
                track = item.get("track") if isinstance(item, dict) else None
                if not isinstance(track, dict):
                    track = {}
                added = item.get("addedDate") if isinstance(item, dict) else None
                added_date = None
                if isinstance(added, str) and added:
                    try:
                        added_date = datetime.strptime(added[:10], "%Y-%m-%d").date()
                    except ValueError:
                        added_date = None
                item_rows.append(
                    {
                        "playlist_name": name,
                        "position": idx,
                        "added_date": added_date,
                        "track_name": track.get("trackName"),
                        "artist_name": track.get("artistName"),
                        "album_name": track.get("albumName"),
                        "track_uri": track.get("trackUri"),
                    }
                )
        return (
            pd.DataFrame(pl_rows) if pl_rows else empty_pl,
            pd.DataFrame(item_rows) if item_rows else empty_items,
        )

    def _searches_frame(self, raw: Path) -> pd.DataFrame:
        columns = [
            "searched_at",
            "searched_at_local",
            "search_query",
            "platform",
            "year",
            "month",
        ]
        path = raw / "SearchQueries.json"
        if not path.is_file():
            return pd.DataFrame(columns=columns)
        payload = _read_json(path)
        if not isinstance(payload, list):
            return pd.DataFrame(columns=columns)
        rows: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            ts = _parse_search_time(item.get("searchTime"))
            utc_naive, local_naive = _local_pair(ts)
            platform = item.get("platform") or None
            if isinstance(platform, str) and not platform.strip():
                platform = None
            rows.append(
                {
                    "searched_at": utc_naive,
                    "searched_at_local": local_naive,
                    "search_query": item.get("searchQuery"),
                    "platform": platform,
                    "year": local_naive.year if local_naive else None,
                    "month": local_naive.month if local_naive else None,
                }
            )
        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(rows)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        plays = conn.execute(
            "SELECT count(*)::BIGINT, min(played_at), max(played_at) FROM spotify.account_plays"
        ).fetchone()
        lib = conn.execute(
            "SELECT count(*)::BIGINT FROM spotify.library_items"
        ).fetchone()
        pl = conn.execute("SELECT count(*)::BIGINT FROM spotify.playlists").fetchone()
        searches = conn.execute(
            "SELECT count(*)::BIGINT FROM spotify.searches"
        ).fetchone()
        assert plays is not None and lib is not None and pl is not None
        assert searches is not None
        inv = {
            "n_account_plays": plays[0],
            "first_play": plays[1],
            "last_play": plays[2],
            "n_library": lib[0],
            "n_playlists": pl[0],
            "n_searches": searches[0],
        }
        inv["summary"] = (
            f"spotify.account_plays: {inv['n_account_plays']:,} rows "
            f"(1-year Account Data slice, not spotify.plays) | "
            f"{inv['first_play']} → {inv['last_play']} | "
            f"library {inv['n_library']:,} | "
            f"playlists {inv['n_playlists']:,} | "
            f"searches {inv['n_searches']:,}"
        )
        return inv
