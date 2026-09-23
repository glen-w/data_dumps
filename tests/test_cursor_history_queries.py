"""Cursor History query smoke tests."""

from __future__ import annotations

import duckdb
import pytest

from data_dumps import cursor_history_queries as chq
from data_dumps.sources.cursor_history import CursorHistorySource

from .test_cursor_history_ingest import make_mini_cursor_history_dir


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data_root"))
    db = duckdb.connect(str(tmp_path / "ch_q.duckdb"))
    CursorHistorySource().load(make_mini_cursor_history_dir(tmp_path), db)
    return db


def test_bounds_and_scoreboard(conn):
    bounds = chq.data_bounds(conn)
    assert bounds["min_year"] <= bounds["max_year"]
    filters = chq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    score = chq.scoreboard(conn, filters)
    assert int(score.iloc[0]["sessions"]) >= 1
    assert int(score.iloc[0]["messages"]) >= 1
    assert "avg_session_depth" in score.columns
    monthly = chq.messages_monthly(conn, filters)
    assert not monthly.empty
    tools = chq.tool_name_mix(conn, filters)
    assert not tools.empty
    fam = chq.tool_family_mix(conn, filters)
    assert not fam.empty
    top = chq.top_sessions(conn, filters)
    assert not top.empty
    circ = chq.weekday_heatmap(conn, filters)
    assert circ is not None
    depth = chq.session_depth(conn, filters)
    assert not depth.empty
    lengths = chq.message_length_buckets(conn, filters)
    assert not lengths.empty
    density = chq.tool_density(conn, filters)
    assert not density.empty
    latency = chq.reply_latency(conn, filters)
    assert not latency.empty


def test_text_search(conn):
    bounds = chq.data_bounds(conn)
    filters = chq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        text_search="loader",
    )
    hits = chq.search_messages(conn, filters)
    assert not hits.empty
    assert "snippet" in hits.columns


def test_text_search_special_chars_bound(conn):
    """User input with SQL metacharacters must not break the query."""
    bounds = chq.data_bounds(conn)
    filters = chq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        text_search="'); DROP TABLE cursor_history.messages;--",
    )
    hits = chq.search_messages(conn, filters)
    assert hits.empty
    # Table still intact
    assert (
        conn.execute("SELECT count(*) FROM cursor_history.messages").fetchone()[0] >= 1
    )


def test_tool_bump_and_mode(conn):
    bounds = chq.data_bounds(conn)
    filters = chq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    bump = chq.tool_family_rank_bump(conn, filters)
    assert "rank" in bump.columns or bump.empty
    modes = chq.unified_mode_mix(conn, filters)
    assert not modes.empty
    assert "agent" in set(modes["unified_mode"].astype(str))
