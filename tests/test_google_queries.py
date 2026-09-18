"""Google Takeout query smoke tests on the synthetic multipart fixture."""

from __future__ import annotations

import duckdb
import pytest

from data_dumps import google_queries as gq
from data_dumps.sources.google import GoogleSource

from .test_google_ingest import FORBIDDEN_COLUMNS, make_mini_google_dir


@pytest.fixture
def google_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    # Avoid basename "google.duckdb" — DuckDB confuses file catalog with schema name.
    conn = duckdb.connect(str(tmp_path / "gq.duckdb"))
    GoogleSource().load(make_mini_google_dir(tmp_path), conn)
    yield conn
    conn.close()


@pytest.fixture
def google_filters(google_conn):
    bounds = gq.data_bounds(google_conn)
    return gq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        exclude_noise=True,
    )


def test_duration_vs_hour_scatter_columns(google_conn, google_filters):
    scatter = gq.duration_vs_hour_scatter(google_conn, google_filters)
    assert {"hour", "duration_hours", "calendar_name", "summary"} <= set(
        scatter.columns
    )
    assert not scatter.empty


def test_summary_rank_bump(google_conn, google_filters):
    bump = gq.summary_rank_bump(google_conn, google_filters)
    assert {"year", "summary", "events", "rnk"} <= set(bump.columns)
    assert not bump.empty
    assert int(bump["rnk"].min()) >= 1


def test_play_purchase_totals_scrubs_payment_strings(google_conn, google_filters):
    totals = gq.play_purchase_totals(google_conn, google_filters)
    assert not totals.empty
    assert int(totals.iloc[0]["purchase_count"]) >= 1
    blob = " ".join(str(x) for x in totals.iloc[0].tolist())
    assert "secret@example.com" not in blob
    assert "PayPal" not in blob

    # Raw purchase values also stay scrubbed (query path does not reintroduce them).
    purchase_blob = " ".join(
        str(x)
        for row in google_conn.execute("SELECT * FROM google.play_purchases").fetchall()
        for x in row
    )
    assert "secret@example.com" not in purchase_blob
    assert "PayPal" not in purchase_blob


def test_forgotten_apps(google_conn, google_filters):
    forgotten = gq.forgotten_apps(google_conn, google_filters, silent_years=2)
    assert {"app", "installs", "last_update"} <= set(forgotten.columns)
    assert "Old Calculator" in set(forgotten["app"])


def test_noise_filter_reduces_calendar_count(google_conn):
    bounds = gq.data_bounds(google_conn)
    noisy = gq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        exclude_noise=True,
    )
    all_cal = gq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        exclude_noise=False,
    )
    n_noisy = int(gq.scoreboard(google_conn, noisy).iloc[0]["calendar_events"])
    n_all = int(gq.scoreboard(google_conn, all_cal).iloc[0]["calendar_events"])
    assert n_noisy < n_all
    assert n_all == 4
    assert n_noisy == 2


def test_forbidden_columns_absent(google_conn):
    cols = {
        r[0].lower()
        for r in google_conn.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'google'
            """
        ).fetchall()
    }
    assert not (cols & FORBIDDEN_COLUMNS)
