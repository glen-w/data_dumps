"""ChatGPT query smoke tests on synthetic warehouse."""

from __future__ import annotations

import duckdb

from data_dumps import chatgpt_queries as cgq
from data_dumps.sources.chatgpt import ChatGPTSource

from .test_chatgpt_ingest import make_mini_chatgpt_zip


def _conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "q.duckdb"))
    ChatGPTSource().load(make_mini_chatgpt_zip(tmp_path), conn)
    return conn


def test_query_suite(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    bounds = cgq.data_bounds(conn)
    assert bounds["min_year"] <= bounds["max_year"]
    f = cgq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    score = cgq.scoreboard(conn, f, compare_previous=True)
    assert not score.empty
    assert "messages" in score.columns
    assert not cgq.streak_stats(conn, f).empty
    assert not cgq.messages_monthly(conn, f).empty
    assert not cgq.model_mix(conn, f).empty
    assert not cgq.weekday_heatmap(conn, f).empty
    assert not cgq.calendar_daily(conn, f).empty
    assert not cgq.top_conversations(conn, f).empty
    assert not cgq.conversation_scatter(conn, f).empty
    _ = cgq.forgotten_conversations(conn, f)
    _ = cgq.comeback_conversations(conn, f)
    assert not cgq.model_rank_bump(conn, f).empty
    _ = cgq.reply_latency(conn, f)
    _ = cgq.gizmo_usage(conn, f)
    assert not cgq.asset_extension_mix(conn).empty
    assert not cgq.title_tokens(conn, f).empty
    ctx = cgq.narrative_context(conn, f)
    assert "scoreboard" in ctx
    assert set(ctx) <= cgq.NARRATIVE_CONTEXT_KEYS
    conn.close()
