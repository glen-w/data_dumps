"""Twitter query robustness tests."""

from __future__ import annotations

from pathlib import Path

import duckdb

from data_dumps.sources.twitter import TwitterSource
from data_dumps.twitter_queries import (
    NARRATIVE_CONTEXT_KEYS,
    FilterState,
    comeback_accounts,
    data_bounds,
    filter_from_widgets,
    forgotten_accounts,
    has_table,
    narrative_context,
    scoreboard,
    top_liked_accounts,
)
from tests.test_twitter_ingest import make_mini_twitter_dir


def _conn(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    root = make_mini_twitter_dir(tmp_path)
    db = tmp_path / "q.duckdb"
    conn = duckdb.connect(str(db))
    TwitterSource().load(root, conn)
    return conn


def test_filter_full_span_no_year_chip(tmp_path):
    conn = _conn(tmp_path)
    bounds = data_bounds(conn)
    f = filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        tweet_types=[],
        media_kinds=[],
        langs=[],
    )
    assert f.year_start is None
    assert f.year_end is None
    assert f.chip_labels() == []
    conn.close()


def test_scoreboard_empty_year_still_returns_row(tmp_path):
    conn = _conn(tmp_path)
    f = FilterState(year_start=1900, year_end=1901)
    df = scoreboard(conn, f)
    assert len(df) == 1
    assert int(df.iloc[0]["tweets"]) == 0
    conn.close()


def test_scoreboard_compare_predates_data(tmp_path):
    conn = _conn(tmp_path)
    bounds = data_bounds(conn)
    f = FilterState(year_start=bounds["min_year"], year_end=bounds["min_year"])
    df = scoreboard(conn, f, compare_previous=True)
    assert len(df) == 1
    assert "compare_note" in df.columns
    assert df.iloc[0]["compare_note"]
    conn.close()


def test_forgotten_and_comeback_empty_on_short_history(tmp_path):
    conn = _conn(tmp_path)
    f = FilterState()
    assert forgotten_accounts(conn, f).empty
    assert comeback_accounts(conn, f).empty
    conn.close()


def test_has_table_guards(tmp_path):
    conn = _conn(tmp_path)
    assert has_table(conn, "tweets")
    assert has_table(conn, "dm_messages")
    deleted = conn.execute("SELECT count(*) FROM twitter.deleted_tweets").fetchone()
    assert deleted is not None and deleted[0] == 0
    conn.close()


def test_top_liked_accounts_empty_on_mini(tmp_path):
    conn = _conn(tmp_path)
    assert top_liked_accounts(conn, FilterState()).empty
    conn.close()


def test_narrative_context_is_aggregates_only(tmp_path):
    conn = _conn(tmp_path)
    ctx = narrative_context(conn, FilterState())
    assert set(ctx.keys()) <= NARRATIVE_CONTEXT_KEYS
    blob = str(ctx)
    assert "hello world" not in blob.lower()
    assert "skip me" not in blob.lower()
    assert "full_text" not in blob
    conn.close()
