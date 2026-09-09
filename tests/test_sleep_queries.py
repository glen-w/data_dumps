"""Sleep as Android query tests on a synthetic warehouse (incl. Mi Band / Spotify joins)."""

import json
import zipfile
from pathlib import Path

import duckdb
import pytest

from data_dumps.sleep_queries import (
    FilterState,
    alarm_summary,
    alarm_vs_wake,
    circadian_heatmap,
    has_alarms,
    has_miband_hr,
    has_spotify_plays,
    late_night_spotify_buckets,
    late_night_spotify_vs_sleep,
    nightly_heart_rate,
    regularity_stats,
    sample_actigraphy,
    scoreboard,
    session_heart_rate,
    snore_noise_monthly,
)
from data_dumps.sources.sleep import SleepSource

from .conftest import _insert_play, make_plays_conn

# Six nights spanning two years; two weekend nights (Fri 2019-12-27, Sat 2020-01-04)
# with later bedtimes so social jet lag is positive.
CSV = """Id,Tz,From,To,Sched,Hours,Rating,Comment,Framerate,Snore,Noise,Cycles,DeepSleep,LenAdjust,Geo,23:00,23:05,Event
"1","Europe/Rome","02. 12. 2019 23:00","03. 12. 2019 7:00","03. 12. 2019 7:00","8.0","4.0"," #home","10000","0","0.1","5","0.4","0","","10.0","8.0","DEEP_START-1575327600000"
"2","Europe/Rome","27. 12. 2019 1:30","27. 12. 2019 9:30","27. 12. 2019 9:00","8.0","3.0"," #home","10000","3","0.2","4","0.3","0","","9.0","7.0","LIGHT_START-1577406600000"
"3","Europe/Rome","02. 01. 2020 23:00","03. 01. 2020 6:30","03. 01. 2020 7:00","7.5","3.5"," #home","10000","0","0.1","5","0.4","0","","10.0","8.0","DEEP_START-1578006000000"
"4","Europe/Rome","04. 01. 2020 1:00","04. 01. 2020 9:00","04. 01. 2020 9:00","8.0","4.5"," #home #party","10000","5","0.3","4","0.3","0","","9.0","7.0","REM_START-1578096000000"
"5","Europe/Rome","06. 01. 2020 23:00","07. 01. 2020 6:00","07. 01. 2020 6:30","7.0","2.5"," #home","10000","0","0.1","5","0.4","0","","10.0","8.0","AWAKE_START-1578351600000"
"6","Europe/Rome","07. 01. 2020 22:30","08. 01. 2020 6:30","","8.0","4.0"," #home","10000","0","0.1","5","0.4","0","","10.0","8.0","DEEP_START-1578436200000"
"""

ALARMS = [
    {
        "id": 1,
        "hour": 7,
        "minutes": 0,
        "enabled": True,
        "daysOfWeek": {"days": 31},
        "nonDeepsleepWakeupWindow": 25,
        "time": 1578376800000,
    },
    {
        "id": 2,
        "hour": 9,
        "minutes": 30,
        "enabled": False,
        "daysOfWeek": {"days": 96},
        "nonDeepsleepWakeupWindow": 0,
        "time": 0,
    },
]


def _make_zip(path: Path, *, with_alarms: bool = True) -> Path:
    zip_path = path / "sleep-export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sleep-export.csv", CSV)
        zf.writestr("prefs.xml", "<map/>")
        if with_alarms:
            zf.writestr("alarms.json", json.dumps(ALARMS))
    return zip_path


@pytest.fixture
def sleep_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    SleepSource().load(_make_zip(tmp_path), conn)
    yield conn
    conn.close()


def test_scoreboard_compare_previous(sleep_conn):
    f = FilterState(year_start=2020, year_end=2020)
    plain = scoreboard(sleep_conn, f)
    assert list(plain["window"]) == ["current"]
    assert int(plain.iloc[0]["nights"]) == 4

    compared = scoreboard(sleep_conn, f, compare_previous=True)
    assert len(compared) == 2
    assert compared.iloc[1]["window"].startswith("previous (2019")
    assert int(compared.iloc[1]["nights"]) == 2

    predates = scoreboard(
        sleep_conn, FilterState(year_start=2019, year_end=2019), compare_previous=True
    )
    assert len(predates) == 1
    assert "compare_note" in predates.columns


def test_regularity_and_social_jetlag(sleep_conn):
    reg = regularity_stats(sleep_conn, FilterState())
    row = reg.iloc[0]
    assert int(row["nights"]) == 6
    # Weekend nights (Fri 27 Dec 01:30, Sat 4 Jan 01:00) go to bed later than weeknights.
    assert float(row["social_jetlag_bed_h"]) > 1.5
    assert float(row["social_jetlag_wake_h"]) > 1.5
    assert float(row["bedtime_stddev_h"]) > 0
    assert float(row["nights_7h_pct"]) == 100.0


def test_circadian_and_snore(sleep_conn):
    circ = circadian_heatmap(sleep_conn, FilterState())
    assert set(circ.columns) == {"dow", "hour", "nights"}
    assert int(circ["nights"].sum()) == 6
    # Bedtime hour 1 appears twice (two after-midnight nights).
    assert int(circ.loc[circ["hour"] == 1, "nights"].sum()) == 2

    snore = snore_noise_monthly(sleep_conn, FilterState())
    assert set(snore.columns) >= {"month", "avg_snore", "avg_noise", "snore_nights_pct"}
    jan = snore.iloc[-1]
    assert float(jan["snore_nights_pct"]) == 25.0


def test_multi_night_actigraphy(sleep_conn):
    one = sample_actigraphy(sleep_conn, FilterState(), limit_sessions=1)
    assert one["day"].nunique() == 1
    three = sample_actigraphy(sleep_conn, FilterState(), limit_sessions=3)
    assert three["day"].nunique() == 3
    assert str(three["day"].max()).startswith("2020-01-07")


def test_alarms_ingested_and_queries(sleep_conn):
    assert has_alarms(sleep_conn)
    cfg = alarm_summary(sleep_conn)
    assert len(cfg) == 2
    enabled = cfg.loc[cfg["enabled"]].iloc[0]
    assert int(enabled["hour"]) == 7
    days = sleep_conn.execute(
        "SELECT days FROM sleep.alarms ORDER BY id"
    ).fetchall()
    assert days[0][0] == "Mon Tue Wed Thu Fri"
    assert days[1][0] == "Sat Sun"

    vs = alarm_vs_wake(sleep_conn, FilterState())
    # Session 6 has no Sched, so five rows.
    assert len(vs) == 5
    early = vs.loc[vs["day"].astype(str).str.startswith("2020-01-02")].iloc[0]
    assert float(early["wake_minus_alarm_min"]) == -30.0


def test_alarms_optional(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "noalarm.duckdb"))
    SleepSource().load(_make_zip(tmp_path, with_alarms=False), conn)
    assert has_alarms(conn)  # table always exists
    assert alarm_summary(conn).empty
    conn.close()


def test_hr_overlay_without_miband(sleep_conn):
    assert not has_miband_hr(sleep_conn)
    assert session_heart_rate(sleep_conn, FilterState()).empty
    assert nightly_heart_rate(sleep_conn, FilterState()).empty


def test_hr_overlay_with_miband(sleep_conn):
    sleep_conn.execute("CREATE SCHEMA miband")
    sleep_conn.execute("""
        CREATE TABLE miband.heart_rate AS
        SELECT
            ts_local,
            ts_local AS ts_utc,
            rate,
            NULL::VARCHAR AS rate_zone,
            ts_local::DATE AS local_date,
            year(ts_local) AS year,
            isodow(ts_local) AS weekday,
            hour(ts_local) AS hour
        FROM (
            SELECT
                TIMESTAMP '2020-01-07 22:30:00' + INTERVAL (i * 10) MINUTE AS ts_local,
                55 + (i % 7) AS rate
            FROM range(0, 48) t(i)
        )
        """)
    assert has_miband_hr(sleep_conn)
    hr = session_heart_rate(sleep_conn, FilterState(), limit_sessions=1)
    assert not hr.empty
    assert str(hr["day"].iloc[0]).startswith("2020-01-07")
    assert float(hr["minutes_in"].min()) == 0.0
    assert float(hr["minutes_in"].max()) <= 8 * 60

    nightly = nightly_heart_rate(sleep_conn, FilterState())
    assert len(nightly) == 1
    assert 55 <= float(nightly.iloc[0]["avg_bpm"]) <= 62


def test_late_night_spotify_without_plays(sleep_conn):
    assert not has_spotify_plays(sleep_conn)
    assert late_night_spotify_vs_sleep(sleep_conn, FilterState()).empty
    assert late_night_spotify_buckets(sleep_conn, FilterState()).empty


def test_late_night_spotify_with_plays(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn, _ = make_plays_conn(tmp_path)
    SleepSource().load(_make_zip(tmp_path), conn)
    # 1.5 h of late listening on the evening of 2020-01-06 (bedtime 23:00 same day)
    # and 0.5 h on 2020-01-03 evening (bedtime 04 Jan 01:00 -> prior evening).
    _insert_play(
        conn, played_at="2020-01-06T22:10:00", artist="Night", track="A",
        track_id="n1", hours=1.5,
    )
    _insert_play(
        conn, played_at="2020-01-03T23:00:00", artist="Night", track="B",
        track_id="n2", hours=0.5,
    )
    df = late_night_spotify_vs_sleep(conn, FilterState())
    assert len(df) == 6
    by_day = df.set_index(df["day"].astype(str).str[:10])["late_spotify_hours"]
    assert float(by_day["2020-01-06"]) == 1.5
    assert float(by_day["2020-01-04"]) == 0.5
    assert float(by_day["2019-12-02"]) == 0.0

    buckets = late_night_spotify_buckets(conn, FilterState())
    assert "none" in set(buckets["bucket"])
    assert int(buckets["nights"].sum()) == 6
    conn.close()
