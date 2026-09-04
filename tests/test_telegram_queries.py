"""Telegram FilterState and query smoke tests."""

import duckdb
import pytest

from data_dumps.sources.telegram import TelegramSource
from data_dumps.telegram_queries import (
    FilterState,
    _where_and_params,
    circadian_heatmap,
    data_bounds,
    filter_from_widgets,
    media_mix,
    messages_by_chat,
    messages_by_chat_type,
    monthly_messages,
    scoreboard,
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
    assert "chat_id IN" in where
    assert "event_type IN" in where
    assert "media_kind IN" in where
    assert params == [2023, 2024, "personal_chat", 222, "message", "photo"]


def test_queries_on_mini(tg_conn):
    bounds = data_bounds(tg_conn)
    assert bounds["min_year"] <= bounds["max_year"]
    f = FilterState()
    score = scoreboard(tg_conn, f)
    assert int(score.iloc[0]["events"]) == 4
    monthly = monthly_messages(tg_conn, f)
    assert not monthly.empty
    chats = messages_by_chat(tg_conn, f)
    assert "Ada" in set(chats["chat_name"])
    mix = media_mix(tg_conn, f)
    assert "photo" in set(mix["media_kind"])
    circ = circadian_heatmap(tg_conn, f)
    assert not circ.empty


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


def test_clear_field_resets_chat_lock():
    f = FilterState(chat_name="Ada", chat_types=["personal_chat"], chat_ids=[222])
    f.clear_field("chat_id")
    assert f.chat_name is None
    assert f.chat_ids == []
    assert f.chat_types == ["personal_chat"]
