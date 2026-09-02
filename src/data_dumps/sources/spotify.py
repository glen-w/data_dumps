"""Spotify Extended Streaming History → DuckDB."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import duckdb

HISTORY_FOLDER = "Spotify Extended Streaming History"
AUDIO_GLOB = "Streaming_History_Audio_*.json"
VIDEO_GLOB = "Streaming_History_Video_*.json"


class SpotifySource:
    name = "spotify"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                return any(HISTORY_FOLDER in n for n in zf.namelist())
        if path.is_dir():
            return any(path.glob(AUDIO_GLOB)) or any(path.glob(VIDEO_GLOB))
        return False

    def tables(self) -> list[str]:
        return ["spotify.plays"]

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        raw_dir = self._materialize(path)
        json_glob = str(raw_dir / "Streaming_History_*.json").replace("'", "''")
        conn.execute("CREATE SCHEMA IF NOT EXISTS spotify")
        conn.execute("DROP TABLE IF EXISTS spotify.plays_raw")
        conn.execute(
            f"""
            CREATE TABLE spotify.plays_raw AS
            SELECT * FROM read_json(
                '{json_glob}',
                format = 'array',
                union_by_name = true
            )
            """
        )
        conn.execute("DROP TABLE IF EXISTS spotify.plays")
        conn.execute(
            """
            CREATE TABLE spotify.plays AS
            WITH base AS (
                SELECT
                    ts::TIMESTAMP AS ts_utc,
                    platform,
                    ms_played::BIGINT AS ms_played,
                    conn_country,
                    master_metadata_track_name AS track_name,
                    master_metadata_album_artist_name AS artist_name,
                    master_metadata_album_album_name AS album_name,
                    spotify_track_uri,
                    episode_name,
                    episode_show_name,
                    spotify_episode_uri,
                    audiobook_title,
                    audiobook_chapter_title,
                    audiobook_uri,
                    reason_start,
                    reason_end,
                    shuffle,
                    skipped,
                    offline,
                    offline_timestamp,
                    incognito_mode,
                    CASE
                        WHEN spotify_track_uri IS NOT NULL THEN 'track'
                        WHEN spotify_episode_uri IS NOT NULL THEN 'episode'
                        WHEN audiobook_uri IS NOT NULL THEN 'audiobook'
                        ELSE 'other'
                    END AS kind,
                    regexp_extract(spotify_track_uri, ':(\\w+)$', 1) AS track_id,
                    regexp_extract(spotify_episode_uri, ':(\\w+)$', 1) AS episode_id
                FROM spotify.plays_raw
            ),
            offline_fixed AS (
                SELECT
                    *,
                    CASE
                        WHEN offline_timestamp IS NOT NULL AND offline_timestamp > 2000000000
                            THEN to_timestamp(offline_timestamp::DOUBLE / 1000)
                        WHEN offline_timestamp IS NOT NULL AND offline_timestamp > 100
                            THEN to_timestamp(offline_timestamp::DOUBLE)
                        ELSE NULL
                    END AS offline_ts
                FROM base
            ),
            timed AS (
                SELECT
                    *,
                    CASE
                        WHEN offline_ts IS NOT NULL
                            AND offline_ts > ts_utc - INTERVAL '7 days'
                            AND offline_ts < ts_utc + INTERVAL '7 days'
                            THEN offline_ts
                        ELSE ts_utc
                    END AS played_at
                FROM offline_fixed
            )
            SELECT
                ts_utc,
                played_at,
                (played_at AT TIME ZONE 'Europe/Rome')::TIMESTAMP AS played_at_local,
                ms_played,
                ms_played / 3600000.0 AS hours,
                kind,
                track_name,
                artist_name,
                album_name,
                spotify_track_uri,
                episode_name,
                episode_show_name,
                spotify_episode_uri,
                audiobook_title,
                audiobook_chapter_title,
                track_id,
                episode_id,
                reason_start,
                reason_end,
                reason_end = 'trackdone' AS full_play,
                shuffle,
                skipped,
                offline,
                incognito_mode,
                conn_country,
                CASE
                    WHEN platform ILIKE '%echo%' OR platform ILIKE '%amazon_salmon%' THEN 'echo_dot'
                    WHEN platform ILIKE '%android%' THEN 'android'
                    WHEN platform ILIKE '%osx%' OR platform ILIKE '%os x%' THEN 'osx'
                    WHEN platform ILIKE '%webplayer%' OR platform ILIKE '%websocket%' THEN 'web'
                    WHEN platform = 'not_applicable' THEN 'unknown'
                    ELSE 'other'
                END AS platform_bucket,
                platform AS platform_raw,
                year(played_at) AS year,
                month(played_at) AS month
            FROM timed
            ORDER BY played_at
            """
        )
        conn.execute("DROP TABLE spotify.plays_raw")

    def _materialize(self, path: Path) -> Path:
        repo_root = Path(__file__).resolve().parents[3]
        raw_dir = repo_root / "raw" / "spotify"
        if raw_dir.exists():
            shutil.rmtree(raw_dir)
        raw_dir.mkdir(parents=True)

        path = path.resolve()
        if path.is_file():
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if HISTORY_FOLDER in name and name.endswith(".json"):
                        zf.extract(name, raw_dir)
            nested = raw_dir / HISTORY_FOLDER
            if nested.exists():
                for f in nested.iterdir():
                    shutil.move(str(f), str(raw_dir / f.name))
                nested.rmdir()
        else:
            for pattern in (AUDIO_GLOB, VIDEO_GLOB):
                for f in path.glob(pattern):
                    shutil.copy2(f, raw_dir / f.name)
        return raw_dir

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        row = conn.execute(
            """
            SELECT
                count(*)::BIGINT AS n_plays,
                round(sum(hours), 1) AS total_hours,
                min(played_at) AS first_play,
                max(played_at) AS last_play,
                round(100.0 * avg(CASE WHEN skipped THEN 1.0 ELSE 0.0 END), 1) AS skip_pct,
                count(*) FILTER (WHERE year = 2017)::BIGINT AS plays_2017
            FROM spotify.plays
            """
        ).fetchone()
        return {
            "n_plays": row[0],
            "total_hours": row[1],
            "first_play": row[2],
            "last_play": row[3],
            "skip_pct": row[4],
            "plays_2017": row[5],
        }
