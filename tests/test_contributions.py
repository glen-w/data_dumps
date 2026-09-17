"""Smoke tests for the thin CONTRIBUTIONS registry."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from data_dumps import compare_queries as cq
from data_dumps import correlation_queries as crq
from data_dumps.contributions import (
    COMPARE_SERIES,
    CONTRIBUTIONS,
    CORRELATE_METRICS,
    SOURCES,
    explorer_contributions,
)
from data_dumps.ingest import SOURCES as INGEST_SOURCES
from data_dumps.sources.browser import BrowserSource
from data_dumps.sources.ring import RingSource

from .test_ring_ingest import make_mini_ring_zip

FIXTURES = Path(__file__).parent / "fixtures"


def test_sources_derived_from_contributions():
    assert SOURCES is INGEST_SOURCES or [s.name for s in SOURCES] == [
        s.name for s in INGEST_SOURCES
    ]
    names = [s.name for s in SOURCES]
    assert "spotify" in names
    assert "spotify_account" in names
    assert "amazon" in names
    assert len(SOURCES) == len({id(s) for s in SOURCES})


def test_series_merged_from_contributions():
    compare_ids = {s.id for s in COMPARE_SERIES}
    corr_ids = {m.id for m in CORRELATE_METRICS}
    assert "spotify_hours" in compare_ids
    assert "browser_urls_last_seen" in compare_ids
    assert "ring_events" in compare_ids
    assert "sleep_snore" in compare_ids
    assert "amazon_alexa" in compare_ids
    assert "amazon_kindle" in compare_ids
    assert "browser_search_urls" in compare_ids
    assert "ring_offline_flips" in compare_ids
    assert "slack_active_people" in compare_ids
    assert "duolingo_progress" in compare_ids
    assert "duolingo_inventory" in compare_ids
    assert "duolingo_league_tier" in compare_ids
    assert "duolingo_language" in compare_ids
    assert "amazon_searches" in compare_ids
    assert "amazon_audible" in compare_ids
    assert "amazon_video" in compare_ids
    assert "amazon_music" in compare_ids
    assert "twitter_dms" in compare_ids
    assert "linkedin_connections" in compare_ids
    assert "linkedin_reactions" in compare_ids
    assert "linkedin_shares" in compare_ids
    assert "telegram_reactions" in compare_ids
    assert "ring_motion" in compare_ids
    assert "ring_app_events" in compare_ids
    assert "spotify_searches" in compare_ids
    assert "thunderbird_signals" in compare_ids
    assert "duolingo_inventory" in corr_ids
    assert "duolingo_league_tier" in corr_ids
    assert "amazon_searches" in corr_ids
    assert "twitter_dms" in corr_ids
    assert "spotify_searches" in corr_ids
    assert "spotify_late_hours" in corr_ids
    assert "browser_urls_last_seen" in corr_ids
    assert "ring_events" in corr_ids
    assert "sleep_noise" in corr_ids
    assert "slack_active_people" in corr_ids
    # Every compare series has a fetch callable.
    assert all(callable(s.fetch) for s in COMPARE_SERIES)
    assert all(callable(m.fetch) for m in CORRELATE_METRICS)
    # Ids must be unique within each catalog.
    assert len(compare_ids) == len(COMPARE_SERIES)
    assert len(corr_ids) == len(CORRELATE_METRICS)


def test_explorer_tabs_register_series():
    """Every tabbed Contribution exposes at least one Compare + Correlate series."""
    for c in explorer_contributions():
        assert c.compare_series, f"{c.slug} missing compare_series"
        assert c.correlate_metrics, f"{c.slug} missing correlate_metrics"


def test_explorer_contributions_have_gates():
    tabs = explorer_contributions()
    assert len(tabs) >= 10
    assert all(
        c.tab_label and c.tab_icon and c.gate_table and c.data_bounds for c in tabs
    )
    assert all(c.tab_icon.startswith("lucide:") for c in tabs)
    slugs = {c.slug for c in tabs}
    assert "spotify_account" not in slugs
    assert "spotify" in slugs


def test_contribution_count():
    assert len(CONTRIBUTIONS) >= len(SOURCES)


def test_ingest_import_does_not_pull_marimo():
    import sys

    before = {m for m in sys.modules if m == "marimo" or m.startswith("marimo.")}
    import data_dumps.ingest  # noqa: F401

    after = {m for m in sys.modules if m == "marimo" or m.startswith("marimo.")}
    assert after == before


@pytest.fixture
def browser_ring_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "br_ring.duckdb"))
    inbox = tmp_path / "browser"
    inbox.mkdir()
    (inbox / "history-sky.json").write_bytes(
        (FIXTURES / "browser_history_sky_mini.json").read_bytes()
    )
    (inbox / "history.json").write_bytes(
        (FIXTURES / "browser_history_legacy_concat.json").read_bytes()
    )
    BrowserSource().load(inbox, conn)
    RingSource().load(make_mini_ring_zip(tmp_path), conn)
    yield conn
    conn.close()


def test_browser_and_ring_available_and_fetch(browser_ring_conn):
    avail = {s.id for s in cq.list_available_series(browser_ring_conn)}
    assert "browser_urls_last_seen" in avail
    assert "browser_search_urls" in avail
    assert "ring_events" in avail
    assert "ring_offline_flips" in avail

    monthly = cq.fetch_monthly(
        browser_ring_conn,
        [
            cq.SeriesSelection("browser_urls_last_seen"),
            cq.SeriesSelection("browser_search_urls"),
            cq.SeriesSelection("ring_events"),
            cq.SeriesSelection("ring_offline_flips"),
        ],
    )
    assert not monthly.empty
    assert set(monthly["series_id"]) <= {
        "browser_urls_last_seen",
        "browser_search_urls",
        "ring_events",
        "ring_offline_flips",
    }
    assert "year_month" in monthly.columns

    long_df = crq.fetch_panel(
        browser_ring_conn,
        ["browser_urls_last_seen", "ring_events", "ring_offline_flips"],
        grain="daily",
    )
    assert not long_df.empty
    assert set(long_df["metric_id"]) <= {
        "browser_urls_last_seen",
        "ring_events",
        "ring_offline_flips",
    }

    monthly_corr = crq.fetch_panel(
        browser_ring_conn,
        ["browser_search_urls", "ring_offline_flips"],
        grain="monthly",
    )
    assert set(monthly_corr["metric_id"]) <= {
        "browser_search_urls",
        "ring_offline_flips",
    }

    bounds = cq.compare_bounds(browser_ring_conn)
    assert bounds["n_series"] >= 2
    corr_b = crq.correlate_bounds(browser_ring_conn)
    assert corr_b["n_metrics"] >= 2
