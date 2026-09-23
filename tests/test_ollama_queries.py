"""Ollama query smoke tests."""

from __future__ import annotations

import json

import duckdb
import pytest

from data_dumps import ollama_queries as olq
from data_dumps.contribution_series import OLLAMA_COMPARE, OLLAMA_CORRELATE
from data_dumps.sources.ollama import OllamaSource

from .test_ollama_ingest import make_mini_ollama_db


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data_root"))
    db = duckdb.connect(str(tmp_path / "ol_q.duckdb"))
    OllamaSource().load(make_mini_ollama_db(tmp_path), db)
    return db


def test_bounds_scoreboard_and_views(conn):
    bounds = olq.data_bounds(conn)
    assert bounds["min_year"] == 2025
    assert bounds["max_year"] == 2026
    assert "gemma3:12b" in bounds["models"]
    filters = olq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    score = olq.scoreboard(conn, filters, compare_previous=True)
    assert int(score.iloc[0]["chats"]) == 2
    assert int(score.iloc[0]["messages"]) == 4
    assert int(score.iloc[0]["attachments"]) == 1
    assert int(score.iloc[0]["thinking_messages"]) == 1
    assert score.iloc[0]["median_reply_minutes"] == pytest.approx(0.31, abs=0.05)
    assert not olq.messages_monthly(conn, filters).empty
    assert not olq.model_mix(conn, filters).empty
    assert not olq.model_stack(conn, filters).empty
    assert not olq.model_rank_bump(conn, filters).empty
    assert not olq.thinking_by_model(conn, filters).empty
    assert not olq.tool_name_mix(conn, filters).empty
    assert not olq.top_chats(conn, filters).empty
    assert not olq.chat_scatter(conn, filters).empty
    assert not olq.message_length_buckets(conn, filters).empty
    assert not olq.chat_depth(conn, filters).empty
    assert not olq.reply_latency(conn, filters).empty
    assert not olq.attachment_mix(conn, filters).empty
    assert olq.weekday_heatmap(conn, filters) is not None
    tokens = olq.message_tokens(conn, filters, role="user")
    assert "term" in tokens.columns
    ctx = olq.narrative_context(conn, filters)
    assert olq.NARRATIVE_CONTEXT_KEYS <= set(ctx)
    dumped = json.dumps(ctx, default=str)
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in dumped


def test_model_filter(conn):
    bounds = olq.data_bounds(conn)
    filters = olq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        models=["gemma3:12b"],
    )
    score = olq.scoreboard(conn, filters)
    assert int(score.iloc[0]["chats"]) == 1
    assert int(score.iloc[0]["messages"]) == 2


def test_compare_series(conn):
    bounds = olq.data_bounds(conn)
    for spec in OLLAMA_COMPARE:
        assert spec.available(conn)
        entity = None
        if spec.requires_entity:
            opts = spec.entity_options(conn) if spec.entity_options else []
            assert opts
            entity = opts[0]["value"]
        frame = spec.fetch(conn, bounds["min_year"], bounds["max_year"], entity)
        assert not frame.empty
        assert "value" in frame.columns
    for metric in OLLAMA_CORRELATE:
        assert metric.available(conn)
        monthly = metric.fetch(conn, bounds["min_year"], bounds["max_year"], "monthly")
        assert not monthly.empty


def test_title_search_is_bound(conn):
    bounds = olq.data_bounds(conn)
    injected = olq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        title_search="' OR 1=1 --",
    )
    injected_score = olq.scoreboard(conn, injected)
    assert int(injected_score.iloc[0]["chats"]) == 0
    matched = olq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        title_search="Hello",
    )
    matched_score = olq.scoreboard(conn, matched)
    assert int(matched_score.iloc[0]["chats"]) == 1


def test_locked_transcript(conn):
    bounds = olq.data_bounds(conn)
    filters = olq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        chat_id="c1",
    )
    thread = olq.chat_messages(conn, filters)
    assert not thread.empty
    names = " ".join(str(v) for v in thread["attachments"].fillna(""))
    assert "notes.py" in names
