"""Browser history query smoke tests."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from data_dumps import browser_queries as brq
from data_dumps.sources.browser import BrowserSource

FIXTURES = Path(__file__).parent / "fixtures"


def _load_mini(tmp_path: Path, monkeypatch) -> duckdb.DuckDBPyConnection:
    inbox = tmp_path / "firefox"
    inbox.mkdir()
    sky = FIXTURES / "browser_history_sky_mini.json"
    legacy = FIXTURES / "browser_history_legacy_concat.json"
    (inbox / "history-2026-09-10T01-36-58.json").write_bytes(sky.read_bytes())
    (inbox / "history.json").write_bytes(legacy.read_bytes())
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    db = tmp_path / "warehouse" / "catalog.duckdb"
    db.parent.mkdir()
    conn = duckdb.connect(str(db))
    BrowserSource().load(inbox, conn)
    return conn


def test_browser_query_suite(tmp_path: Path, monkeypatch):
    conn = _load_mini(tmp_path, monkeypatch)
    try:
        bounds = brq.data_bounds(conn)
        f = brq.filter_from_widgets(
            bounds,
            year_start=bounds["min_year"],
            year_end=bounds["max_year"],
            include_private=True,
        )
        assert isinstance(brq.scoreboard(conn, f, compare=True), pd.DataFrame)
        assert not brq.top_pages(conn, f).empty
        assert not brq.category_mix(conn, f).empty
        assert not brq.monthly_last_visits(conn, f).empty
        assert not brq.search_engines(conn, f).empty
        assert not brq.monthly_search_volume(conn, f).empty
        assert not brq.local_hosts(conn, f).empty
        assert not brq.comeback_domains(conn, f).empty
        tree = brq.path_tree(conn, f, etld1="github.com")
        assert isinstance(tree, pd.DataFrame)
        assert not tree.empty
        ctx = brq.narrative_context(conn, f)
        assert "scoreboard" in ctx
        assert ctx["filter_digest"]
        # Category filter
        f_cat = brq.filter_from_widgets(
            bounds,
            year_start=bounds["min_year"],
            year_end=bounds["max_year"],
            categories=["dev"],
        )
        pages = brq.top_pages(conn, f_cat)
        assert not pages.empty
        assert (pages["category"] == "dev").all()
    finally:
        conn.close()
