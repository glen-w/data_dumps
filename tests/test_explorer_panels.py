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

from data_dumps import spotify_queries as spq
from data_dumps import telegram_queries as tgq
from data_dumps.explorer_panels import (
    make_sleep_controls,
    make_spotify_controls,
    make_telegram_controls,
    render_sleep_panel,
    render_spotify_panel,
    render_telegram_panel,
)
from data_dumps.llm_client import narrate
from data_dumps.sleep_queries import data_bounds as sl_bounds
from data_dumps.sources.sleep import SleepSource
from data_dumps.sources.telegram import TelegramSource

from .conftest import make_plays_conn
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
def tg_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "tg.duckdb"))
    TelegramSource().load(make_mini_telegram_dir(tmp_path), conn)
    yield conn
    conn.close()


def _is_marimo_element(obj) -> bool:
    return hasattr(obj, "_repr_html_") or hasattr(obj, "text")


def test_render_sleep_panel_with_all_cross_sources(combo_conn):
    bounds = sl_bounds(combo_conn)
    controls = make_sleep_controls(mo, bounds)
    out = render_sleep_panel(
        mo=mo, px=px, conn=combo_conn, bounds=bounds, controls=controls, dow_labels=ISO_DOW
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
        filter_from_widgets=spq.filter_from_widgets,
        scoreboard=spq.scoreboard,
        streak_stats=spq.streak_stats,
        top_artists=spq.top_artists,
        top_tracks=spq.top_tracks,
        top_albums=spq.top_albums,
        top_shows=spq.top_shows,
        discovery_vs_repeats=spq.discovery_vs_repeats,
        shuffle_intent=spq.shuffle_intent,
        circadian_heatmap=spq.circadian_heatmap,
        forgotten_artists=spq.forgotten_artists,
        comeback_artists=spq.comeback_artists,
        monthly_hours=spq.monthly_hours,
        hours_by_kind=spq.hours_by_kind,
        hours_by_platform=spq.hours_by_platform,
        hours_by_country=spq.hours_by_country,
        skip_trends=spq.skip_trends,
        treemap_artist_album=spq.treemap_artist_album,
        calendar_daily=spq.calendar_daily,
        bump_chart_artists=spq.bump_chart_artists,
        artist_hours_vs_skip=spq.artist_hours_vs_skip,
        kind_platform_sunburst=spq.kind_platform_sunburst,
        genre_treemap=spq.genre_treemap,
        decade_bars=spq.decade_bars,
        narrative_context=spq.narrative_context,
        narrate=narrate,
    )
    html = out._repr_html_()
    for needle in ("Milestones", "Rank movement", "Album depth", "Longest listening sessions"):
        assert needle in html, needle
    # Narration was not triggered (button not clicked) -> no LLM call.
    assert "Narrate this view" in html
    assert "### Narrative" not in html


def test_render_telegram_panel(tg_conn):
    bounds = tgq.data_bounds(tg_conn)
    controls = make_telegram_controls(mo, bounds)
    kwargs = dict(
        mo=mo,
        px=px,
        conn=tg_conn,
        bounds=bounds,
        people_chat_types=list(tgq.PEOPLE_CHAT_TYPES),
        dow_labels=TG_DOW,
        controls=controls,
        filter_from_widgets=tgq.filter_from_widgets,
        scoreboard=tgq.scoreboard,
        streak_stats=tgq.streak_stats,
        monthly_by_chat_type=tgq.monthly_by_chat_type,
        me_vs_them=tgq.me_vs_them,
        messages_by_chat=tgq.messages_by_chat,
        chat_reply_scatter=tgq.chat_reply_scatter,
        forgotten_chats=tgq.forgotten_chats,
        comeback_chats=tgq.comeback_chats,
        calendar_daily=tgq.calendar_daily,
        circadian_heatmap=tgq.circadian_heatmap,
        bump_chart_chats=tgq.bump_chart_chats,
        media_mix=tgq.media_mix,
        reaction_mix=tgq.reaction_mix,
        calls_by_year=tgq.calls_by_year,
    )
    html = render_telegram_panel(**kwargs)._repr_html_()
    for needle in ("Text — words, emoji, length", "People — lock a group chat", "Who talks"):
        assert needle in html, needle

    # Lock the one personal chat: per-sender title changes and Sankey path runs.
    controls.set_chat_name("Ada")
    html_locked = render_telegram_panel(**kwargs)._repr_html_()
    assert "Ada" in html_locked
