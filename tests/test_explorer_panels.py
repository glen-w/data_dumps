"""Render-smoke tests for the explorer panels on synthetic warehouses.

These exercise the query → Plotly → Marimo wiring end-to-end without a
running kernel: ``make_*_controls`` + ``render_*_panel`` must return a Marimo
element with default widget values. They catch broken imports, missing
columns, and figure-construction errors that pure query tests miss.
"""

from __future__ import annotations

import duckdb
import marimo as mo
import plotly.express as px
import pytest

from data_dumps import amazon_queries as amzq
from data_dumps import browser_queries as brq
from data_dumps import compare_queries as cq
from data_dumps import correlation_queries as crq
from data_dumps import slack_queries as skq
from data_dumps import spotify_queries as spq
from data_dumps import telegram_queries as tgq
from data_dumps.explorer_panels import (
    make_amazon_controls,
    make_browser_controls,
    make_compare_controls,
    make_correlate_controls,
    make_linkedin_controls,
    make_miband_controls,
    make_ring_controls,
    make_slack_controls,
    make_sleep_controls,
    make_spotify_controls,
    make_telegram_controls,
    render_amazon_panel,
    render_browser_panel,
    render_compare_panel,
    render_correlate_panel,
    render_linkedin_panel,
    render_miband_panel,
    render_ring_panel,
    render_slack_panel,
    render_sleep_panel,
    render_spotify_panel,
    render_telegram_panel,
)
from data_dumps.sleep_queries import data_bounds as sl_bounds
from data_dumps.sources.amazon import AmazonSource
from data_dumps.sources.browser import BrowserSource
from data_dumps.sources.linkedin import LinkedInSource
from data_dumps.sources.ring import RingSource
from data_dumps.sources.slack import SlackSource
from data_dumps.sources.sleep import SleepSource
from data_dumps.sources.telegram import TelegramSource

from .conftest import make_plays_conn
from .test_amazon_ingest import make_mini_amazon_dir
from .test_linkedin_ingest import make_mini_linkedin_zip
from .test_ring_ingest import make_mini_ring_zip
from .test_slack_ingest import ALICE, make_mini_slack_zip
from .test_sleep_queries import _make_zip as make_sleep_zip
from .test_telegram_ingest import make_mini_telegram_dir

ISO_DOW = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
TG_DOW = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}


def _add_miband(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS miband")
    conn.execute("""
        CREATE TABLE miband.heart_rate AS
        SELECT
            ts_local, ts_local AS ts_utc, rate, NULL::VARCHAR AS rate_zone,
            ts_local::DATE AS local_date, year(ts_local) AS year,
            isodow(ts_local) AS weekday, hour(ts_local) AS hour
        FROM (
            SELECT
                TIMESTAMP '2020-01-07 22:30:00' + INTERVAL (i * 10) MINUTE AS ts_local,
                55 + (i % 7) AS rate
            FROM range(0, 48) t(i)
        )
        """)


@pytest.fixture
def combo_conn(tmp_path, monkeypatch):
    """Spotify plays + Sleep sessions/alarms + Mi Band HR in one warehouse."""
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn, _ = make_plays_conn(tmp_path)
    SleepSource().load(make_sleep_zip(tmp_path), conn)
    _add_miband(conn)
    yield conn
    conn.close()


@pytest.fixture
def sk_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "sk.duckdb"))
    SlackSource().load(make_mini_slack_zip(tmp_path), conn)
    yield conn
    conn.close()


@pytest.fixture
def tg_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "tg.duckdb"))
    TelegramSource().load(make_mini_telegram_dir(tmp_path), conn)
    yield conn
    conn.close()


@pytest.fixture
def li_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "li.duckdb"))
    LinkedInSource().load(make_mini_linkedin_zip(tmp_path), conn)
    yield conn
    conn.close()


@pytest.fixture
def amz_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    root = make_mini_amazon_dir(tmp_path)
    conn = duckdb.connect(str(tmp_path / "amz.duckdb"))
    AmazonSource().load(root, conn)
    yield conn
    conn.close()


def _is_marimo_element(obj) -> bool:
    return hasattr(obj, "_repr_html_") or hasattr(obj, "text")


def test_render_sleep_panel_with_all_cross_sources(combo_conn):
    bounds = sl_bounds(combo_conn)
    controls = make_sleep_controls(mo, bounds)
    out = render_sleep_panel(
        mo=mo,
        px=px,
        conn=combo_conn,
        bounds=bounds,
        controls=controls,
        dow_labels=ISO_DOW,
    )
    assert _is_marimo_element(out)
    html = out._repr_html_()
    # New sections are present.
    for needle in (
        "Regularity",
        "Heart rate overlay",
        "Alarms",
        "Late-night Spotify",
        "Actigraphy",
    ):
        assert needle in html, needle


def test_render_sleep_panel_without_optional_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    SleepSource().load(make_sleep_zip(tmp_path, with_alarms=False), conn)
    bounds = sl_bounds(conn)
    out = render_sleep_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=bounds,
        controls=make_sleep_controls(mo, bounds),
        dow_labels=ISO_DOW,
    )
    html = out._repr_html_()
    assert "HR overlay needs" in html
    assert "needs `spotify.plays`" in html or "spotify.plays" in html
    conn.close()


def test_render_spotify_panel(combo_conn):
    bounds = spq.data_bounds(combo_conn)
    controls = make_spotify_controls(mo, bounds)
    out = render_spotify_panel(
        mo=mo,
        px=px,
        conn=combo_conn,
        bounds=bounds,
        mb_ready=False,
        controls=controls,
    )
    html = out._repr_html_()
    for needle in (
        "Milestones",
        "Rank movement",
        "Album depth",
        "Longest listening sessions",
        "Hours by weekday × hour",
    ):
        assert needle in html, needle
    # Narration was not triggered (button not clicked) -> no LLM call.
    assert "Narrate this view" in html
    assert "### Narrative" not in html


@pytest.fixture
def br_conn(tmp_path, monkeypatch):
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures"
    inbox = tmp_path / "firefox"
    inbox.mkdir()
    (inbox / "history-2026-09-10T01-36-58.json").write_bytes(
        (fixtures / "browser_history_sky_mini.json").read_bytes()
    )
    (inbox / "history.json").write_bytes(
        (fixtures / "browser_history_legacy_concat.json").read_bytes()
    )
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "br.duckdb"))
    BrowserSource().load(inbox, conn)
    yield conn
    conn.close()


def test_render_browser_panel(br_conn):
    bounds = brq.data_bounds(br_conn)
    controls = make_browser_controls(mo, bounds)
    html = render_browser_panel(
        mo=mo,
        px=px,
        conn=br_conn,
        bounds=bounds,
        controls=controls,
    )._repr_html_()
    for needle in ("Narrate this view", "Scoreboard", "Top domains"):
        assert needle in html, needle
    assert "### Narration" not in html


def test_render_slack_panel_and_spotlight(sk_conn):
    bounds = skq.data_bounds(sk_conn)
    controls = make_slack_controls(mo, bounds)
    kwargs = dict(
        mo=mo, px=px, conn=sk_conn, bounds=bounds, controls=controls, dow_labels=ISO_DOW
    )
    html = render_slack_panel(**kwargs)._repr_html_()
    for needle in (
        "Slack workspace",
        "Scoreboard",
        "Channels",
        "Comeback channels",
        "Person spotlight",
        "Pick a person",
        "Threads",
        "Reactions",
        "Rhythm",
        "Bots",
    ):
        assert needle in html, needle
    assert "Team baseline uses" not in html

    # Spotlight via the click-to-lock state (same path as clicking a bar).
    controls.set_person(ALICE)
    html_spot = render_slack_panel(**kwargs)._repr_html_()
    assert "Team baseline uses" in html_spot
    assert "Alice Example" in html_spot
    assert "Collaborators" in html_spot

    # Clear button resets the state override.
    controls.clear_person._update(1)  # simulate one click
    html_cleared = render_slack_panel(**kwargs)._repr_html_()
    assert "Team baseline uses" not in html_cleared


def test_render_telegram_panel(tg_conn):
    bounds = tgq.data_bounds(tg_conn)
    controls = make_telegram_controls(mo, bounds)
    kwargs = dict(
        mo=mo,
        px=px,
        conn=tg_conn,
        bounds=bounds,
        dow_labels=TG_DOW,
        controls=controls,
    )
    html = render_telegram_panel(**kwargs)._repr_html_()
    for needle in (
        "Text — words, emoji, length",
        "People — lock a group chat",
        "Who talks",
    ):
        assert needle in html, needle

    # Lock the one personal chat: per-sender title changes and Sankey path runs.
    controls.set_chat_name("Ada")
    html_locked = render_telegram_panel(**kwargs)._repr_html_()
    assert "Ada" in html_locked


@pytest.fixture
def tb_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    from data_dumps.sources.thunderbird import ThunderbirdSource

    from .test_thunderbird_ingest import make_mini_gloda_profile

    conn = duckdb.connect(str(tmp_path / "tb.duckdb"))
    ThunderbirdSource().load(make_mini_gloda_profile(tmp_path), conn)
    yield conn
    conn.close()


def test_render_miband_panel(combo_conn):
    from data_dumps import miband_queries as mbq

    bounds = mbq.data_bounds(combo_conn)
    controls = make_miband_controls(mo, bounds)
    html = render_miband_panel(
        mo=mo,
        px=px,
        conn=combo_conn,
        bounds=bounds,
        controls=controls,
        dow_labels=ISO_DOW,
    )._repr_html_()
    for needle in (
        "Mi Band heart rate",
        "Scoreboard",
        "Longitudinal",
        "Resting HR",
        "Anomalies",
    ):
        assert needle in html, needle


@pytest.fixture
def ring_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "ring_wh.duckdb"))
    RingSource().load(make_mini_ring_zip(tmp_path), conn)
    yield conn
    conn.close()


def test_render_ring_panel(ring_conn):
    from data_dumps import ring_queries as ringq

    bounds = ringq.data_bounds(ring_conn)
    controls = make_ring_controls(mo, bounds)
    html = render_ring_panel(
        mo=mo,
        px=px,
        conn=ring_conn,
        bounds=bounds,
        controls=controls,
        dow_labels=ISO_DOW,
    )._repr_html_()
    for needle in (
        "Ring",
        "Scoreboard",
        "Data footprint",
        "Device online/offline",
        "App activity spikes",
        "Billing",
    ):
        assert needle in html, needle


def test_render_linkedin_panel(li_conn):
    from data_dumps import linkedin_queries as liq

    bounds = liq.data_bounds(li_conn)
    controls = make_linkedin_controls(mo, bounds)
    html = render_linkedin_panel(
        mo=mo,
        px=px,
        conn=li_conn,
        bounds=bounds,
        controls=controls,
        dow_labels=ISO_DOW,
    )._repr_html_()
    for needle in (
        "LinkedIn explorer",
        "Scoreboard",
        "Relationships",
        "Career",
        "Invitations",
    ):
        assert needle in html, needle


def test_render_thunderbird_panel(tb_conn):
    from data_dumps import thunderbird_queries as tbq
    from data_dumps.explorer_panels import (
        make_thunderbird_controls,
        render_thunderbird_panel,
    )

    # Messages without a local calendar day must not crash ISO week casting.
    tb_conn.execute(
        "UPDATE thunderbird.messages SET local_date = NULL "
        "WHERE gloda_id = (SELECT min(gloda_id) FROM thunderbird.messages)"
    )
    bounds = tbq.data_bounds(tb_conn)
    controls = make_thunderbird_controls(mo, bounds)
    html = render_thunderbird_panel(
        mo=mo,
        px=px,
        conn=tb_conn,
        bounds=bounds,
        controls=controls,
        dow_labels=ISO_DOW,
    )._repr_html_()
    for needle in (
        "Thunderbird mail",
        "Scoreboard",
        "Top senders",
        "Signals",
        "Relationships",
        "Forgotten",
    ):
        assert needle in html, needle


def test_render_amazon_panel(amz_conn):
    bounds = amzq.data_bounds(amz_conn)
    controls = make_amazon_controls(mo, bounds)
    out = render_amazon_panel(
        mo=mo,
        px=px,
        conn=amz_conn,
        bounds=bounds,
        controls=controls,
        dow_labels=ISO_DOW,
    )
    assert _is_marimo_element(out)
    html = out._repr_html_()
    # Always-rendered sections survive the fixture (which has orders, cart,
    # returns, alexa intents, impressions, and a shadowed voice file).
    for needle in (
        "Spend scoreboard",
        "Impulse vs planned",
        "Cart → order",
        "Refund burden by product family",
        "Alexa in the house",
        "Data footprint",
    ):
        assert needle in html, needle


def test_render_compare_panel(combo_conn):
    bounds = cq.compare_bounds(combo_conn)
    series = cq.list_available_series(combo_conn)
    controls = make_compare_controls(mo, bounds, series, conn=combo_conn)
    out = render_compare_panel(
        mo=mo,
        px=px,
        conn=combo_conn,
        bounds=bounds,
        controls=controls,
    )
    assert _is_marimo_element(out)
    html = out._repr_html_()
    assert "Compare" in html
    assert "Normalized overlay" in html
    assert "Correlations" in html
    assert "Raw monthly values" in html


def test_render_correlate_panel(combo_conn):
    bounds = crq.correlate_bounds(combo_conn)
    metrics = crq.list_available_metrics(combo_conn)
    assert len(metrics) >= 2
    controls = make_correlate_controls(mo, bounds, metrics)
    out = render_correlate_panel(
        mo=mo,
        px=px,
        conn=combo_conn,
        bounds=bounds,
        controls=controls,
    )
    assert _is_marimo_element(out)
    html = out._repr_html_()
    assert "Correlations" in html
    assert "Correlation matrix" in html
    assert "Lag scan" in html
