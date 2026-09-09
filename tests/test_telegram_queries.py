"""Telegram FilterState and query smoke tests."""

import json

import duckdb
import pytest

from data_dumps.sources.telegram import TelegramSource
from data_dumps.telegram_queries import (
    NARRATIVE_CONTEXT_KEYS,
    PEOPLE_CHAT_TYPES,
    FilterState,
    _where_and_params,
    bump_chart_chats,
    calendar_daily,
    calls_by_year,
    chat_reply_scatter,
    circadian_heatmap,
    comeback_chats,
    data_bounds,
    emoji_in_text,
    filter_from_widgets,
    forgotten_chats,
    me_vs_them,
    media_mix,
    message_length_buckets,
    messages_by_chat,
    messages_by_chat_type,
    monthly_by_chat_type,
    monthly_messages,
    narrative_context,
    per_sender_breakdown,
    reaction_mix,
    reply_edges,
    scoreboard,
    streak_stats,
    text_stats,
    top_words,
)

from .test_telegram_ingest import make_mini_telegram_dir


@pytest.fixture
def tg_conn(tmp_path):
    export = make_mini_telegram_dir(tmp_path)
    db_path = tmp_path / "tg.duckdb"
    conn = duckdb.connect(str(db_path))
    TelegramSource().load(export, conn)
    yield conn
    conn.close()


def test_chip_labels_full_year_hidden():
    bounds = {"min_year": 2023, "max_year": 2024}
    f = filter_from_widgets(
        bounds,
        year_start=2023,
        year_end=2024,
        chat_types=[],
        event_types=[],
        media_kinds=[],
    )
    labels = [field for field, _ in f.chip_labels()]
    assert "year_range" not in labels


def test_where_params_order():
    f = FilterState(
        year_start=2023,
        year_end=2024,
        chat_types=["personal_chat"],
        chat_ids=[222],
        event_types=["message"],
        media_kinds=["photo"],
    )
    where, params = _where_and_params(f)
    assert "year >=" in where
    assert "c.type IN" in where
    assert "c.type NOT IN" in where
    assert "chat_id IN" in where
    assert "event_type IN" in where
    assert "media_kind IN" in where
    assert params[:6] == [2023, 2024, "personal_chat", 222, "message", "photo"]
    assert "bot_chat" in params
    assert "private_group" in params


def test_queries_on_mini(tg_conn):
    bounds = data_bounds(tg_conn)
    assert bounds["min_year"] <= bounds["max_year"]
    f = FilterState()
    score = scoreboard(tg_conn, f)
    # Default scope excludes bot_chat (Sci Bot), so Ada's 3 events only.
    assert int(score.iloc[0]["events"]) == 3
    monthly = monthly_messages(tg_conn, f)
    assert not monthly.empty
    chats = messages_by_chat(tg_conn, f)
    assert "Ada" in set(chats["chat_name"])
    mix = media_mix(tg_conn, f)
    assert "photo" in set(mix["media_kind"])
    circ = circadian_heatmap(tg_conn, f)
    assert not circ.empty


def test_wave2_queries_on_mini(tg_conn):
    f = FilterState()
    me = me_vs_them(tg_conn, f)
    assert set(me.columns) >= {"year", "me", "them"}
    assert int(me["me"].sum()) == 1
    # Sci Bot excluded by default scope; only Ada's personal_chat reply counts.
    assert int(me["them"].sum()) == 1

    with_bots = me_vs_them(tg_conn, FilterState(include_bots=True))
    assert int(with_bots["them"].sum()) == 2
    assert (
        int(scoreboard(tg_conn, FilterState(include_bots=True)).iloc[0]["events"]) == 4
    )

    mix = media_mix(tg_conn, f, exclude_none=True)
    assert "none" not in set(mix["media_kind"])
    assert "photo" in set(mix["media_kind"])

    mix_all = media_mix(tg_conn, f, exclude_none=False)
    assert "none" in set(mix_all["media_kind"])

    cal = calendar_daily(tg_conn, f)
    assert not cal.empty
    bump = bump_chart_chats(tg_conn, f)
    assert not bump.empty
    assert "Ada" in set(bump["chat_name"])

    streak = streak_stats(tg_conn, f)
    assert int(streak.iloc[0]["longest_streak_days"]) >= 1

    forgotten = forgotten_chats(tg_conn, f, min_events=50)
    assert forgotten.empty
    assert comeback_chats(tg_conn, f).empty

    scatter = chat_reply_scatter(tg_conn, f)
    ada = scatter.loc[scatter["chat_name"] == "Ada"].iloc[0]
    assert float(ada["reply_pct"]) > 0
    assert "last_day" in scatter.columns

    monthly_types = monthly_by_chat_type(tg_conn, f)
    assert "chat_type" in monthly_types.columns
    assert "personal_chat" in set(monthly_types["chat_type"])

    react = reaction_mix(tg_conn, f)
    assert "👍" in set(react["emoji"])
    assert int(react.loc[react["emoji"] == "👍", "reactions"].iloc[0]) == 1

    assert calls_by_year(tg_conn, f).empty
    tg_conn.execute("""
        INSERT INTO telegram.messages (
            chat_id, message_id, event_type, ts_utc, ts_local,
            action, media_kind, year, month
        ) VALUES (
            222, 99, 'service',
            TIMESTAMP '2024-01-15 10:03:00',
            TIMESTAMP '2024-01-15 11:03:00',
            'phone_call', 'none', 2024, 1
        )
        """)
    calls = calls_by_year(tg_conn, FilterState())
    assert int(calls["calls"].sum()) == 1
    assert int(calls.iloc[0]["year"]) == 2024

    people = FilterState(chat_types=list(PEOPLE_CHAT_TYPES))
    score = scoreboard(tg_conn, people)
    assert int(score.iloc[0]["chats"]) == 1
    assert "reply_pct" in score.columns

    compared = scoreboard(
        tg_conn, FilterState(year_start=2024, year_end=2024), compare_previous=True
    )
    assert "current" in set(compared["window"])
    assert any(str(w).startswith("previous") for w in compared["window"])


def test_people_chat_types_preset():
    assert PEOPLE_CHAT_TYPES == [
        "personal_chat",
        "private_group",
        "private_supergroup",
        "saved_messages",
    ]


def test_year_filter_drops_bot_chat(tg_conn):
    f = FilterState(year_start=2024, year_end=2024)
    score = scoreboard(tg_conn, f)
    assert int(score.iloc[0]["events"]) == 3
    assert int(score.iloc[0]["chats"]) == 1


def test_chat_name_filter(tg_conn):
    f = FilterState(chat_name="Ada")
    score = scoreboard(tg_conn, f)
    assert int(score.iloc[0]["chats"]) == 1
    types = messages_by_chat_type(tg_conn, f)
    assert list(types["chat_type"]) == ["personal_chat"]


def test_text_analytics_on_mini(tg_conn):
    f = FilterState(include_bots=True)
    stats = text_stats(tg_conn, f)
    row = stats.iloc[0]
    assert int(row["text_messages"]) >= 1
    assert float(row["avg_chars"]) > 0
    assert set(stats.columns) >= {"question_pct", "link_pct", "emoji_pct", "edited_pct"}

    words = top_words(tg_conn, f, limit=10, min_len=3)
    assert set(words.columns) == {"word", "uses"}
    assert all(len(w) >= 3 for w in words["word"])
    assert "the" not in set(words["word"])

    # Emoji + link + question in one message.
    tg_conn.execute("""
        INSERT INTO telegram.messages (
            chat_id, message_id, event_type, ts_utc, ts_local, from_name, from_id,
            text, edited, media_kind, year, month
        ) VALUES (
            222, 98, 'message',
            TIMESTAMP '2024-01-15 10:04:00', TIMESTAMP '2024-01-15 11:04:00',
            'Ada', 222,
            'Seen this? 😀😀 https://example.org/paper', false, 'none', 2024, 1
        )
        """)
    emoji = emoji_in_text(tg_conn, FilterState())
    assert "😀" in set(emoji["emoji"])
    assert int(emoji.loc[emoji["emoji"] == "😀", "uses"].iloc[0]) == 2
    stats2 = text_stats(tg_conn, FilterState())
    assert float(stats2.iloc[0]["link_pct"]) > 0
    assert float(stats2.iloc[0]["question_pct"]) > 0
    words2 = top_words(tg_conn, FilterState(), limit=50)
    assert not any(w.startswith("http") or "example" in w for w in words2["word"])

    buckets = message_length_buckets(tg_conn, FilterState())
    assert set(buckets["who"]) <= {"me", "them"}
    assert int(buckets["messages"].sum()) >= 2


def test_per_sender_and_reply_edges(tg_conn):
    f = FilterState(chat_name="Ada")
    senders = per_sender_breakdown(tg_conn, f)
    assert set(senders.columns) >= {"sender", "is_me", "messages", "share_pct"}
    assert abs(float(senders["share_pct"].sum()) - 100.0) < 0.2
    assert senders["is_me"].any()

    edges = reply_edges(tg_conn, f)
    assert set(edges.columns) == {"source", "target", "replies"}
    assert int(edges["replies"].sum()) == 1
    assert edges.iloc[0]["source"] != edges.iloc[0]["target"]


def test_narrative_context_privacy(tg_conn):
    ctx = narrative_context(tg_conn, FilterState(year_start=2024))
    assert set(ctx.keys()) == NARRATIVE_CONTEXT_KEYS
    blob = json.dumps(ctx, default=str)
    assert "filter_digest" in blob
    # No raw message text or identifiers leak into the prompt context.
    texts = [
        r[0]
        for r in tg_conn.execute(
            "SELECT text FROM telegram.messages WHERE text IS NOT NULL AND text <> ''"
        ).fetchall()
    ]
    for t in texts:
        assert t not in blob
    for forbidden in ("\"text\":", "from_id", "phone_number", "message_id"):
        assert forbidden not in blob
    assert len(ctx["top_chats"]) <= 10
    assert FilterState(year_start=2024).filter_digest() != FilterState().filter_digest()


def test_clear_field_resets_chat_lock():
    f = FilterState(chat_name="Ada", chat_types=["personal_chat"], chat_ids=[222])
    f.clear_field("chat_id")
    assert f.chat_name is None
    assert f.chat_ids == []
    assert f.chat_types == ["personal_chat"]
