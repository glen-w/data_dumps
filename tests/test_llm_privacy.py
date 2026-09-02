"""Ensure LLM narrative context never includes raw play fields."""

import json

from data_dumps.spotify_queries import (
    NARRATIVE_CONTEXT_KEYS,
    FilterState,
    narrative_context,
)

FORBIDDEN_RAW_KEYS = frozenset(
    {
        "ts_utc",
        "ms_played",
        "spotify_track_uri",
        "platform_raw",
        "played_at",
    }
)


def _collect_keys(obj, found: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            _collect_keys(v, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, found)


def test_narrative_context_allowlist(plays_conn):
    conn, _ = plays_conn
    ctx = narrative_context(conn, FilterState(year_start=2020))
    assert set(ctx.keys()) == NARRATIVE_CONTEXT_KEYS

    found: set[str] = set()
    _collect_keys(ctx, found)
    assert not FORBIDDEN_RAW_KEYS.intersection(found)


def test_narrative_context_bounded_lists(plays_conn):
    conn, _ = plays_conn
    ctx = narrative_context(conn, FilterState())
    assert len(ctx["top_artists"]) <= 10
    assert len(ctx["top_tracks"]) <= 10
    assert len(ctx["comebacks"]) <= 5
    assert len(ctx["forgotten"]) <= 5


def test_narrative_context_serializable(plays_conn):
    conn, _ = plays_conn
    ctx = narrative_context(conn, FilterState(year_start=2020))
    blob = json.dumps(ctx, default=str)
    assert "filter_digest" in blob
