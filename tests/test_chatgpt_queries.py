"""ChatGPT query smoke tests on synthetic warehouse."""

from __future__ import annotations

import duckdb

from data_dumps import chatgpt_queries as cgq
from data_dumps.contribution_series import CHATGPT_COMPARE, CHATGPT_CORRELATE
from data_dumps.sources.chatgpt import ChatGPTSource, flatten_parts, model_family

from .test_chatgpt_ingest import make_mini_chatgpt_zip


def _conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "chatgpt_q.duckdb"))
    ChatGPTSource().load(make_mini_chatgpt_zip(tmp_path), conn)
    return conn


def test_flatten_parts_and_model_family():
    text, images = flatten_parts(
        {
            "content_type": "multimodal_text",
            "parts": [
                "hello",
                {"content_type": "image_asset_pointer", "asset_pointer": "x"},
            ],
        }
    )
    assert text == "hello"
    assert images == 1
    thoughts, _ = flatten_parts(
        {
            "content_type": "thoughts",
            "thoughts": [{"summary": "think", "content": "long"}],
        }
    )
    assert thoughts == "think"
    assert model_family("gpt-5-2-thinking") == "gpt-5"
    assert model_family("gpt-4o") == "gpt-4o"
    assert model_family("text-davinci-002-render-sha") == "gpt-3.5"
    assert model_family(None) is None


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
    assert "dow" in cgq.weekday_heatmap(conn, f).columns
    assert not cgq.calendar_daily(conn, f).empty
    assert not cgq.top_conversations(conn, f).empty
    assert not cgq.conversation_scatter(conn, f).empty
    _ = cgq.forgotten_conversations(conn, f)
    comebacks = cgq.comeback_conversations(conn, f)
    assert not comebacks.empty  # fixture has ≥90d gap on c-3
    assert not cgq.model_rank_bump(conn, f).empty
    _ = cgq.reply_latency(conn, f)
    assert not cgq.gizmo_usage(conn, f).empty
    assert not cgq.asset_extension_mix(conn).empty
    assert not cgq.title_tokens(conn, f).empty
    shared = cgq.shared_list(conn, f)
    assert not shared.empty
    assert "Basketball" in str(shared.iloc[0]["title"])
    ctx = cgq.narrative_context(conn, f)
    assert "scoreboard" in ctx
    assert set(ctx) <= cgq.NARRATIVE_CONTEXT_KEYS
    # Aggregates only — no raw message bodies in narrative context
    blob = str(ctx).lower()
    assert "explain box and one" not in blob
    assert "refactor this" not in blob
    conn.close()


def test_filters_compose(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    bounds = cgq.data_bounds(conn)
    by_title = cgq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        title_search="Basketball",
    )
    assert any(k == "title_search" for k, _ in by_title.chip_labels())
    tops = cgq.top_conversations(conn, by_title)
    assert not tops.empty
    assert all("basketball" in t.lower() for t in tops["title"])

    by_role = cgq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        roles=["user"],
    )
    role_mix = cgq.role_mix(conn, by_role)
    assert list(role_mix["role"]) == ["user"]

    by_model = cgq.filter_from_widgets(
        bounds,
        year_start=2024,
        year_end=2025,
        model_families=["gpt-4o"],
    )
    models = cgq.model_mix(conn, by_model)
    assert not models.empty
    assert set(models["model_family"]) == {"gpt-4o"}

    locked = cgq.FilterState(
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        conversation_id=str(tops.iloc[0]["conversation_id"]),
    )
    thread = cgq.conversation_messages(conn, locked)
    assert not thread.empty
    assert set(thread["role"]).issubset({"user", "assistant"})

    shared_only = cgq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        shared_only=True,
    )
    shared_tops = cgq.top_conversations(conn, shared_only)
    assert not shared_tops.empty
    assert bool(shared_tops.iloc[0]["is_shared"])
    conn.close()


def test_compare_and_correlate_series(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    bounds = cgq.data_bounds(conn)
    for spec in CHATGPT_COMPARE:
        assert spec.available(conn)
        entity = None
        if spec.requires_entity:
            opts = spec.entity_options(conn) if spec.entity_options else []
            assert opts
            entity = opts[0]["value"]
        df = spec.fetch(conn, bounds["min_year"], bounds["max_year"], entity)
        assert not df.empty
        assert "value" in df.columns
    for metric in CHATGPT_CORRELATE:
        assert metric.available(conn)
        daily = metric.fetch(conn, bounds["min_year"], bounds["max_year"], "daily")
        monthly = metric.fetch(conn, bounds["min_year"], bounds["max_year"], "monthly")
        assert not daily.empty
        assert not monthly.empty
    conn.close()


def test_filter_digest_and_clear():
    f = cgq.FilterState(
        year_start=2024,
        year_end=2025,
        roles=["user"],
        conversation_id="c-1",
        shared_only=True,
    )
    d1 = f.filter_digest()
    f.clear_field("conversation_id")
    f.clear_field("shared_only")
    f.clear_field("role")
    assert f.conversation_id is None
    assert f.shared_only is False
    assert f.roles == []
    assert f.filter_digest() != d1


def test_message_language_queries(tmp_path, monkeypatch):
    from data_dumps.wordcloud_util import frequencies_from_frame, wordcloud_png

    conn = _conn(tmp_path, monkeypatch)
    bounds = cgq.data_bounds(conn)
    f = cgq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    tokens = cgq.message_tokens(conn, f, role="user")
    assert not tokens.empty
    words = set(tokens["term"])
    assert "explain" in words
    assert "refactor" in words
    assert "and" not in words
    assert "the" not in words
    pooled = cgq.message_tokens(conn, f, role="all")
    assert not pooled.empty
    assert set(pooled["role"]) == {"all"}

    modality = cgq.modality_monthly(conn, f)
    assert not modality.empty
    assert int(modality["assistant_chars"].sum()) > 0
    assert not cgq.content_type_monthly(conn, f).empty
    lengths = cgq.message_length_buckets(conn, f)
    assert "<40" in set(lengths["bucket"])
    depth = cgq.conversation_depth(conn, f)
    assert not depth.empty
    flags = cgq.conversation_flags(conn, f)
    assert set(flags["flag"]) == {
        "archived",
        "starred",
        "study_mode",
        "do_not_remember",
    }
    assets = cgq.assets_monthly(conn, f)
    assert not assets.empty
    assert int(assets["files"].sum()) >= 1

    bigrams = cgq.user_bigrams(conn, f)
    assert list(bigrams.columns) == ["term", "n"]
    distinctive = cgq.distinctive_terms(conn, f, min_count=1)
    assert {"term", "n_user", "n_assistant", "score"} <= set(distinctive.columns)

    png = wordcloud_png(frequencies_from_frame(tokens))
    assert png is not None
    assert png.startswith(b"\x89PNG")
    assert wordcloud_png({}) is None
    conn.close()
