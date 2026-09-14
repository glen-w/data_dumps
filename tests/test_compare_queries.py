"""Tests for cross-source Compare query helpers."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from data_dumps import compare_queries as cq
from data_dumps.sources.amazon import AmazonSource
from data_dumps.sources.linkedin import LinkedInSource
from data_dumps.sources.slack import SlackSource
from data_dumps.sources.sleep import SleepSource
from data_dumps.sources.telegram import TelegramSource
from data_dumps.sources.thunderbird import ThunderbirdSource
from data_dumps.sources.twitter import TwitterSource

from .conftest import make_plays_conn
from .test_amazon_ingest import make_mini_amazon_dir
from .test_explorer_panels import _add_miband
from .test_linkedin_ingest import make_mini_linkedin_zip
from .test_slack_ingest import make_mini_slack_zip
from .test_sleep_queries import _make_zip as make_sleep_zip
from .test_telegram_ingest import make_mini_telegram_dir
from .test_thunderbird_ingest import make_mini_gloda_profile
from .test_twitter_ingest import make_mini_twitter_dir


@pytest.fixture
def cmp_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn, _ = make_plays_conn(tmp_path)
    SleepSource().load(make_sleep_zip(tmp_path), conn)
    _add_miband(conn)
    TelegramSource().load(make_mini_telegram_dir(tmp_path), conn)
    SlackSource().load(make_mini_slack_zip(tmp_path), conn)
    LinkedInSource().load(make_mini_linkedin_zip(tmp_path), conn)
    TwitterSource().load(make_mini_twitter_dir(tmp_path), conn)
    ThunderbirdSource().load(make_mini_gloda_profile(tmp_path), conn)
    AmazonSource().load(make_mini_amazon_dir(tmp_path), conn)
    yield conn
    conn.close()


def test_list_available_series_gates_on_tables(cmp_conn):
    ids = {s.id for s in cq.list_available_series(cmp_conn)}
    for expected in (
        "spotify_hours",
        "spotify_artist",
        "sleep_hours",
        "miband_bpm",
        "telegram_messages",
        "telegram_chat",
        "slack_messages",
        "slack_channel",
        "slack_person",
        "linkedin_messages",
        "linkedin_conversation",
        "twitter_tweets",
        "twitter_account",
        "thunderbird_messages",
        "thunderbird_contact",
        "amazon_orders",
    ):
        assert expected in ids
    # Browser / Ring are in the catalog but not loaded in this fixture.
    assert "browser_urls_last_seen" not in ids
    assert "ring_events" not in ids


def test_catalog_includes_browser_and_ring():
    ids = {s.id for s in cq.SERIES}
    assert "browser_urls_last_seen" in ids
    assert "ring_events" in ids


def test_compare_bounds_union(cmp_conn):
    b = cq.compare_bounds(cmp_conn)
    assert b["min_year"] <= b["max_year"]
    assert b["n_series"] >= 10


def test_normalize_pct_of_max():
    df = pd.DataFrame(
        {
            "year_month": ["2020-01", "2020-02", "2020-01", "2020-02"],
            "series_id": ["a", "a", "b", "b"],
            "series_label": ["A", "A", "B", "B"],
            "value": [10.0, 20.0, 0.0, 0.0],
            "unit": ["x", "x", "y", "y"],
        }
    )
    out = cq.normalize_pct_of_max(df)
    a = out[out["series_label"] == "A"].set_index("year_month")["pct_of_max"]
    assert a["2020-01"] == pytest.approx(50.0)
    assert a["2020-02"] == pytest.approx(100.0)
    b = out[out["series_label"] == "B"]["pct_of_max"]
    assert (b == 0.0).all()


def test_normalize_empty():
    out = cq.normalize_pct_of_max(pd.DataFrame(columns=cq.OUT_COLS))
    assert "pct_of_max" in out.columns
    assert out.empty


def test_correlation_matrix_perfect_and_sparse():
    df = pd.DataFrame(
        {
            "year_month": ["2020-01", "2020-02", "2020-03", "2020-01", "2020-02", "2020-03"],
            "series_label": ["A", "A", "A", "B", "B", "B"],
            "pct_of_max": [10.0, 20.0, 30.0, 5.0, 10.0, 15.0],
            "value": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
            "unit": ["x"] * 6,
            "series_id": ["a", "a", "a", "b", "b", "b"],
        }
    )
    mat = cq.correlation_matrix(df)
    assert mat.loc["A", "B"] == pytest.approx(1.0)
    assert mat.loc["A", "A"] == pytest.approx(1.0)

    short = df[df["year_month"].isin(["2020-01", "2020-02"])]
    sparse = cq.correlation_matrix(short, min_overlap=3)
    assert pd.isna(sparse.loc["A", "B"])


def test_correlation_matrix_constant_is_nan():
    df = pd.DataFrame(
        {
            "year_month": ["2020-01", "2020-02", "2020-03", "2020-01", "2020-02", "2020-03"],
            "series_label": ["A", "A", "A", "B", "B", "B"],
            "pct_of_max": [50.0, 50.0, 50.0, 10.0, 20.0, 30.0],
        }
    )
    mat = cq.correlation_matrix(df)
    assert pd.isna(mat.loc["A", "B"])


def test_selection_notes(cmp_conn):
    notes = cq.selection_notes(
        [
            cq.SeriesSelection("telegram_chat"),
            cq.SeriesSelection("spotify_hours"),
            cq.SeriesSelection("nope"),
        ],
        cmp_conn,
    )
    assert any("pick an entity" in n for n in notes)
    assert any("Unknown series" in n for n in notes)


def test_fetch_monthly_totals(cmp_conn):
    raw = cq.fetch_monthly(
        cmp_conn,
        [
            cq.SeriesSelection("spotify_hours"),
            cq.SeriesSelection("sleep_hours"),
            cq.SeriesSelection("telegram_messages"),
            cq.SeriesSelection("slack_messages"),
            cq.SeriesSelection("amazon_orders"),
            cq.SeriesSelection("thunderbird_messages"),
        ],
    )
    assert set(raw.columns) == set(cq.OUT_COLS)
    assert not raw.empty
    labels = set(raw["series_label"])
    assert any("Spotify" in L for L in labels)
    assert any("Sleep" in L for L in labels)
    assert any("Telegram" in L for L in labels)
    assert any("Slack" in L for L in labels)
    assert any("Amazon" in L for L in labels)
    assert raw["year_month"].str.match(r"^\d{4}-\d{2}$").all()
    norm = cq.normalize_pct_of_max(raw)
    assert "pct_of_max" in norm.columns
    assert norm.groupby("series_label")["pct_of_max"].max().ge(99.9).all()


def test_fetch_monthly_entity_and_skip_missing(cmp_conn):
    chats = cq.entity_options(cmp_conn, "telegram_chat")
    assert chats
    chat = chats[0]["value"]
    raw = cq.fetch_monthly(
        cmp_conn,
        [
            cq.SeriesSelection("telegram_chat", entity=chat),
            cq.SeriesSelection("telegram_chat"),  # missing entity → skip
            {"series_id": "spotify_hours"},  # dict form also accepted
        ],
    )
    assert not raw.empty
    assert set(raw["series_id"]) <= {"telegram_chat", "spotify_hours"}
    assert any(chat in L for L in raw["series_label"])


def test_fetch_monthly_caps_at_six(cmp_conn):
    sels = [
        cq.SeriesSelection("spotify_hours"),
        cq.SeriesSelection("sleep_hours"),
        cq.SeriesSelection("miband_bpm"),
        cq.SeriesSelection("telegram_messages"),
        cq.SeriesSelection("slack_messages"),
        cq.SeriesSelection("amazon_orders"),
        cq.SeriesSelection("twitter_tweets"),  # 7th — capped
    ]
    raw = cq.fetch_monthly(cmp_conn, sels)
    assert raw["series_id"].nunique() <= cq.MAX_SERIES
    assert "twitter_tweets" not in set(raw["series_id"])


def test_spotify_artist_entity(cmp_conn):
    artists = cq.entity_options(cmp_conn, "spotify_artist")
    assert artists
    name = artists[0]["value"]
    raw = cq.fetch_monthly(
        cmp_conn,
        [cq.SeriesSelection("spotify_artist", entity=name)],
    )
    assert not raw.empty
    assert name in raw["series_label"].iloc[0]


def test_slack_channel_and_person_entities(cmp_conn):
    channels = cq.entity_options(cmp_conn, "slack_channel")
    people = cq.entity_options(cmp_conn, "slack_person")
    assert channels and people
    raw = cq.fetch_monthly(
        cmp_conn,
        [
            cq.SeriesSelection("slack_channel", entity=channels[0]["value"]),
            cq.SeriesSelection("slack_person", entity=people[0]["value"]),
        ],
    )
    assert set(raw["series_id"]) == {"slack_channel", "slack_person"}


def test_linkedin_conversation_entity(cmp_conn):
    opts = cq.entity_options(cmp_conn, "linkedin_conversation")
    assert opts
    raw = cq.fetch_monthly(
        cmp_conn,
        [cq.SeriesSelection("linkedin_conversation", entity=opts[0]["value"])],
    )
    assert not raw.empty
    assert raw["series_id"].eq("linkedin_conversation").all()


def test_thunderbird_and_twitter_entities(cmp_conn):
    contacts = cq.entity_options(cmp_conn, "thunderbird_contact")
    accounts = cq.entity_options(cmp_conn, "twitter_account")
    assert contacts and accounts
    raw = cq.fetch_monthly(
        cmp_conn,
        [
            cq.SeriesSelection("thunderbird_contact", entity=contacts[0]["value"]),
            cq.SeriesSelection("twitter_account", entity=accounts[0]["value"]),
            cq.SeriesSelection("miband_bpm"),
        ],
    )
    assert {"thunderbird_contact", "twitter_account", "miband_bpm"} <= set(
        raw["series_id"]
    )
    corr = cq.correlation_matrix(cq.normalize_pct_of_max(raw))
    assert corr.shape[0] >= 2
    assert (corr.values.diagonal() == 1.0).all()


def test_year_window_filters_spotify(cmp_conn):
    full = cq.fetch_monthly(cmp_conn, [cq.SeriesSelection("spotify_hours")])
    assert not full.empty
    years = sorted({int(ym[:4]) for ym in full["year_month"]})
    only_first = cq.fetch_monthly(
        cmp_conn,
        [cq.SeriesSelection("spotify_hours")],
        year_start=years[0],
        year_end=years[0],
    )
    assert not only_first.empty
    assert {int(ym[:4]) for ym in only_first["year_month"]} == {years[0]}


def test_empty_warehouse_has_no_series(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "empty.duckdb"))
    try:
        assert cq.list_available_series(conn) == []
        b = cq.compare_bounds(conn)
        assert b["n_series"] == 0
        raw = cq.fetch_monthly(conn, [cq.SeriesSelection("spotify_hours")])
        assert raw.empty
    finally:
        conn.close()
