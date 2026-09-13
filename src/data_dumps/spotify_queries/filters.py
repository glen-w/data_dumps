"""Spotify filter state and WHERE helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd


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
