"""Airbnb query / FilterState / Compare·Correlate series smoke (synthetic)."""

from __future__ import annotations

import duckdb
import pytest

from data_dumps import airbnb_queries as abq
from data_dumps.compare_queries import entity_options, list_available_series
from data_dumps.correlation_queries import (
    PRESET_LIFE_RHYTHM,
    apply_preset,
    list_available_metrics,
)
from data_dumps.sources.airbnb import AirbnbSource

from .test_airbnb_ingest import make_mini_airbnb_zip


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    db = duckdb.connect(str(tmp_path / "ab_q.duckdb"))
    AirbnbSource().load(make_mini_airbnb_zip(tmp_path), db)
    yield db
    db.close()


def test_bounds_selectors_populated(conn):
    b = abq.data_bounds(conn)
    assert b["min_year"] <= b["max_year"]
    assert b["first_day"] is not None
    assert "guest" in b["roles"]
    assert "accepted" in b["statuses"]
    assert "Paris" in b["places"]
    assert "London" in b["places"]


def test_place_filter_narrows_searches(conn):
    b = abq.data_bounds(conn)
    all_f = abq.filter_from_widgets(b, year_start=2023, year_end=2024)
    paris = abq.filter_from_widgets(b, year_start=2023, year_end=2024, place="Paris")
    assert ("place", "place: Paris") in paris.chip_labels()
    n_all = int(abq.searches_monthly(conn, all_f)["searches"].sum())
    n_paris = int(abq.searches_monthly(conn, paris)["searches"].sum())
    assert n_paris >= 1
    assert n_paris < n_all
    mp = abq.search_map_points(conn, paris)
    assert set(mp["place"]) == {"Paris"}


def test_nights_and_reservations_series(conn):
    nights_m = abq.nights_monthly_total(conn, 2022, 2024)
    assert list(nights_m.columns) == ["year_month", "nights"]
    assert int(nights_m["nights"].sum()) >= 3  # guest stay nights in fixture
    nights_d = abq.nights_daily_total(conn, 2022, 2024)
    assert "day" in nights_d.columns and "nights" in nights_d.columns
    res_m = abq.reservations_monthly_total(conn, 2022, 2024)
    assert int(res_m["reservations"].sum()) >= 2


def test_place_entity_options_and_monthly(conn):
    opts = abq.place_options(conn)
    assert any(o["value"] == "Paris" for o in opts)
    f = abq.FilterState(year_start=2023, year_end=2024)
    monthly = abq.searches_monthly_for_place(conn, f, "Paris")
    assert list(monthly.columns) == ["year_month", "searches"]
    assert int(monthly["searches"].sum()) >= 1


def test_scoreboard_compare_previous_and_recent(conn):
    b = abq.data_bounds(conn)
    f = abq.filter_from_widgets(b, year_start=2023, year_end=2024)
    sb = abq.scoreboard(conn, f, compare_previous=True)
    assert "reservations" in sb.columns
    assert "searches" in sb.columns
    recent = abq.recent_stays(conn, f)
    assert not recent.empty
    assert "confirmation_code" in recent.columns


def test_wrapped_helpers_smoke(conn):
    b = abq.data_bounds(conn)
    f = abq.filter_from_widgets(b, year_start=b["min_year"], year_end=b["max_year"])
    assert not abq.streak_stats(conn, f).empty
    assert not abq.weekday_heatmap(conn, f).empty
    assert not abq.calendar_daily_starts(conn, f).empty
    assert not abq.status_breakdown(conn, f).empty
    assert not abq.role_breakdown(conn, f).empty
    assert not abq.nights_by_country(conn, f).empty
    abq.forgotten_search_places(conn, f)
    abq.comeback_search_places(conn, f)
    abq.place_rank_bump(conn, f)
    assert not abq.reviews_summary(conn, f).empty
    assert not abq.reviews_monthly(conn, f).empty
    assert not abq.wishlist_summary(conn).empty


def test_compare_and_correlate_catalog(conn):
    series_ids = {s.id for s in list_available_series(conn)}
    assert {
        "airbnb_reservations",
        "airbnb_nights",
        "airbnb_searches",
        "airbnb_place",
    } <= series_ids
    opts = entity_options(conn, "airbnb_place")
    assert any(o["value"] == "Paris" for o in opts)

    metrics = list_available_metrics(conn)
    metric_ids = {m.id for m in metrics}
    assert {
        "airbnb_reservations",
        "airbnb_nights",
        "airbnb_searches",
    } <= metric_ids
    life, _focus = apply_preset(PRESET_LIFE_RHYTHM, metrics)
    assert "airbnb_searches" in life

    # Callable fetch returns long frames for correlate pack
    spec = next(m for m in metrics if m.id == "airbnb_searches")
    daily = spec.fetch(conn, 2023, 2024, "daily")
    assert not daily.empty
    assert "value" in daily.columns
