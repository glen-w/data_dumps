"""Browser history JSON ingest tests."""

from __future__ import annotations

from pathlib import Path

import duckdb

from data_dumps import browser_queries as brq
from data_dumps.ingest import pick_source
from data_dumps.sources.browser import (
    SOURCE_FIREFOX_SKY,
    SOURCE_LEGACY_CHROME,
    BrowserSource,
    _scrub_url,
    looks_like_history_records,
    merge_pages,
    normalize_record,
)

FIXTURES = Path(__file__).parent / "fixtures"
SKY_FIXTURE = FIXTURES / "browser_history_sky_mini.json"
LEGACY_FIXTURE = FIXTURES / "browser_history_legacy_concat.json"


def _copy_fixtures(inbox: Path) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "history-2026-09-10T01-36-58.json").write_bytes(SKY_FIXTURE.read_bytes())
    (inbox / "history.json").write_bytes(LEGACY_FIXTURE.read_bytes())


def test_scrub_url_strips_secret():
    cleaned = _scrub_url("https://ex.com/p?secret=live_xxx&q=hi")
    assert "secret=" not in cleaned
    assert "q=hi" in cleaned


def test_normalize_search_and_private():
    import json

    sky = json.loads(SKY_FIXTURE.read_text(encoding="utf-8"))
    rec = normalize_record(sky[0], SOURCE_FIREFOX_SKY)
    assert rec is not None
    assert rec["search_engine"] == "google"
    assert rec["search_query"] == "hello"
    assert "secret=" not in rec["url"]
    assert rec["category"] == "search"

    priv = normalize_record(sky[2], SOURCE_FIREFOX_SKY)
    assert priv is not None
    assert priv["is_private"] is True
    assert priv["category"] == "local"


def test_merge_max_visit_count_and_canonical_title():
    import json

    sky = json.loads(SKY_FIXTURE.read_text(encoding="utf-8"))
    from data_dumps.sources.browser import _load_json_values, _records_from_parts

    legacy = _records_from_parts(_load_json_values(LEGACY_FIXTURE))
    rows = [
        normalize_record(sky[1], SOURCE_FIREFOX_SKY),
        normalize_record(legacy[1], SOURCE_LEGACY_CHROME),
    ]
    assert all(r is not None for r in rows)
    df = merge_pages(rows)  # type: ignore[arg-type]
    assert len(df) == 1
    row = df.iloc[0]
    assert int(row["visit_count"]) == 50
    assert row["title"] == "cursor/cursor"
    assert "firefox_sky" in row["sources"]
    assert "legacy_chrome" in row["sources"]


def test_detect_and_load_directory(tmp_path: Path, monkeypatch):
    inbox = tmp_path / "firefox"
    _copy_fixtures(inbox)
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))

    source = pick_source(inbox)
    assert isinstance(source, BrowserSource)

    db = tmp_path / "warehouse" / "catalog.duckdb"
    db.parent.mkdir()
    conn = duckdb.connect(str(db))
    try:
        source.load(inbox, conn)
        inv = source.inventory(conn)
        assert inv["n_pages"] == 5  # 4 sky + 1 unique legacy (github merged)
        n = conn.execute("SELECT count(*) FROM browser.pages").fetchone()
        assert n is not None and n[0] == 5
        github = conn.execute(
            "SELECT visit_count, title FROM browser.pages "
            "WHERE url LIKE '%github.com/cursor%'"
        ).fetchone()
        assert github is not None
        assert github[0] == 50
        assert github[1] == "cursor/cursor"
        secret_hits = conn.execute(
            "SELECT count(*) FROM browser.pages WHERE url LIKE '%secret=%'"
        ).fetchone()
        assert secret_hits is not None and secret_hits[0] == 0

        bounds = brq.data_bounds(conn)
        assert bounds["min_year"] <= 2020
        f = brq.filter_from_widgets(
            bounds,
            year_start=bounds["min_year"],
            year_end=bounds["max_year"],
        )
        score = brq.scoreboard(conn, f)
        assert int(score.iloc[0]["unique_urls"]) == 5
        domains = brq.top_domains(conn, f)
        assert not domains.empty
    finally:
        conn.close()


def test_sibling_merge_when_ingesting_canonical_file(tmp_path: Path, monkeypatch):
    inbox = tmp_path / "firefox"
    _copy_fixtures(inbox)
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    canonical = inbox / "history-2026-09-10T01-36-58.json"
    assert pick_source(canonical) is not None
    db = tmp_path / "warehouse" / "catalog.duckdb"
    db.parent.mkdir()
    conn = duckdb.connect(str(db))
    try:
        BrowserSource().load(canonical, conn)
        n = conn.execute("SELECT count(*) FROM browser.pages").fetchone()
        assert n is not None and n[0] == 5
        meta = conn.execute("SELECT count(*) FROM browser.ingest_meta").fetchone()
        assert meta is not None and meta[0] == 2
    finally:
        conn.close()


def test_looks_like_history():
    import json

    sky = json.loads(SKY_FIXTURE.read_text(encoding="utf-8"))
    assert looks_like_history_records(sky)
    assert not looks_like_history_records([{"foo": 1}])


def test_filter_text_search_parameterized(tmp_path: Path, monkeypatch):
    """Text search must not break SQL when it contains quotes."""
    inbox = tmp_path / "firefox"
    _copy_fixtures(inbox)
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    db = tmp_path / "warehouse" / "catalog.duckdb"
    db.parent.mkdir()
    conn = duckdb.connect(str(db))
    try:
        BrowserSource().load(inbox, conn)
        bounds = brq.data_bounds(conn)
        f = brq.filter_from_widgets(
            bounds,
            year_start=bounds["min_year"],
            year_end=bounds["max_year"],
            text_search="cursor'; o'reilly",
        )
        # Should run without error; may be empty
        df = brq.top_pages(conn, f)
        assert list(df.columns)
        chips = dict(f.chip_labels())
        assert "text_search" in chips
    finally:
        conn.close()


def test_hide_private_filter(tmp_path: Path, monkeypatch):
    inbox = tmp_path / "firefox"
    _copy_fixtures(inbox)
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    db = tmp_path / "warehouse" / "catalog.duckdb"
    db.parent.mkdir()
    conn = duckdb.connect(str(db))
    try:
        BrowserSource().load(inbox, conn)
        bounds = brq.data_bounds(conn)
        f = brq.filter_from_widgets(
            bounds,
            year_start=bounds["min_year"],
            year_end=bounds["max_year"],
            include_private=False,
        )
        score = brq.scoreboard(conn, f)
        assert int(score.iloc[0]["private_urls"]) == 0
        local = brq.local_hosts(conn, f)
        assert local.empty
    finally:
        conn.close()
