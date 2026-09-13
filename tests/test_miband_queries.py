"""Mi Band HR query coverage beyond ingest smoke."""

from __future__ import annotations

import duckdb
import pytest

from data_dumps import miband_queries as mbq
from data_dumps.sources.miband import MiBandSource

# Multi-day fixture: daytime + night hours across a short span for streaks/resting.
MINI_CSV = """dateTime,rate,rateZone
01.02.2018 03:00:00,58,35%
01.02.2018 04:00:00,56,34%
01.02.2018 05:00:00,55,33%
01.02.2018 12:00:00,72,40%
01.02.2018 18:00:00,110,70%
02.02.2018 03:00:00,57,34%
02.02.2018 04:00:00,54,32%
02.02.2018 12:00:00,95,55%
02.02.2018 18:00:00,100,60%
03.02.2018 03:00:00,56,34%
03.02.2018 12:00:00,98,58%
03.02.2018 18:00:00,105,65%
04.02.2018 03:00:00,55,33%
04.02.2018 12:00:00,70,40%
15.03.2018 04:00:00,52,30%
15.03.2018 14:00:00,80,45%
"""


@pytest.fixture
def mb_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    csv_path = tmp_path / "heart_rate.csv"
    csv_path.write_text(MINI_CSV)
    conn = duckdb.connect(str(tmp_path / "mb.duckdb"))
    MiBandSource().load(csv_path, conn)
    yield conn
    conn.close()


def test_scoreboard_compare_and_longitudinal(mb_conn):
    bounds = mbq.data_bounds(mb_conn)
    filters = mbq.filter_from_widgets(bounds, year_start=2018, year_end=2018)
    # Restricted window so compare has a previous span (even if empty).
    filters = mbq.FilterState(year_start=2018, year_end=2018)
    score = mbq.scoreboard(mb_conn, filters, compare_previous=True)
    assert "readings" in score.columns
    assert int(score.iloc[0]["readings"]) >= 10

    monthly = mbq.monthly_avg(mb_conn, filters)
    assert not monthly.empty
    assert "year_month" in monthly.columns

    cal = mbq.calendar_daily(mb_conn, filters)
    assert len(cal) >= 3

    rest = mbq.resting_hr_daily(mb_conn, filters)
    assert not rest.empty
    assert rest["resting_bpm"].max() < 90

    zones = mbq.zone_monthly(mb_conn, filters)
    assert not zones.empty

    streaks = mbq.high_hr_day_streaks(mb_conn, filters, bpm_threshold=85.0)
    assert int(streaks.iloc[0]["longest_high_hr_streak"]) >= 1

    anom = mbq.anomalous_days(mb_conn, filters, window=3, z_threshold=0.5)
    assert "z_score" in anom.columns

    assert mbq.sleep_nightly_overlay(mb_conn, filters).empty


def test_previous_window():
    f = mbq.FilterState(year_start=2020, year_end=2021)
    prev = mbq.previous_window(f)
    assert prev is not None
    assert prev.year_start == 2018
    assert prev.year_end == 2019
    assert mbq.previous_window(mbq.FilterState()) is None
