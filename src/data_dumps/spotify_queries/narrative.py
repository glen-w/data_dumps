"""Spotify LLM narrative aggregates."""

from __future__ import annotations

from typing import Any

import duckdb

from data_dumps.spotify_queries.filters import FilterState
from data_dumps.spotify_queries.listening import (
    comeback_artists,
    discovery_vs_repeats,
    forgotten_artists,
    scoreboard,
    streak_stats,
    top_artists,
    top_tracks,
)

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
