"""Sleep as Android ingest smoke tests."""

import zipfile
from pathlib import Path

import duckdb

from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.sleep_queries import data_bounds, filter_from_widgets, scoreboard
from data_dumps.sources.base import Source
from data_dumps.sources.sleep import SleepSource

MINI_CSV = """Id,Tz,From,To,Sched,Hours,Rating,Comment,Framerate,Snore,Noise,Cycles,DeepSleep,LenAdjust,Geo,23:00,23:05,Event,Event
"100","Europe/Paris","01. 01. 2020 23:00","02. 01. 2020 7:00","02. 01. 2020 7:30","8.0","3.5"," #watch #home","10000","1","0.1","5","0.4","0","","10.0","8.0","DEEP_START-1577919600000","LIGHT_START-1577923200000"
"101","Europe/Paris","02. 01. 2020 23:30","03. 01. 2020 6:30","03. 01. 2020 7:00","7.0","2.0"," #watch","10000","0","0.0","4","0.3","0","","9.0","7.0","AWAKE_START-1578006000000",""
"""


def make_mini_sleep_zip(path: Path) -> Path:
    zip_path = path / "sleep-export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sleep-export.csv", MINI_CSV)
        zf.writestr("prefs.xml", "<map/>")
    return zip_path


def test_detect_zip(tmp_path):
    zip_path = make_mini_sleep_zip(tmp_path)
    source = SleepSource()
    assert source.detect(zip_path)
    assert isinstance(source, Source)


def test_detect_csv(tmp_path):
    csv_path = tmp_path / "sleep-export.csv"
    csv_path.write_text(MINI_CSV)
    assert SleepSource().detect(csv_path)


def test_pick_source(tmp_path):
    zip_path = make_mini_sleep_zip(tmp_path)
    source = pick_source(zip_path)
    assert source is not None
    assert source.name == "sleep"


def test_load_and_queries(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = make_mini_sleep_zip(tmp_path)
    db_path = tmp_path / "w.duckdb"
    conn = duckdb.connect(str(db_path))
    source = SleepSource()
    source.load(zip_path, conn)
    inv = source.inventory(conn)
    assert inv["n_sessions"] == 2
    assert inv["n_events"] >= 2
    assert inv["n_actigraphy"] >= 2
    assert "sleep.sessions" in inv["summary"]
    assert (raw_dir("sleep") / "sleep-export.csv").exists()

    bounds = data_bounds(conn)
    assert bounds["min_year"] == 2020
    filters = filter_from_widgets(
        bounds, year_start=2020, year_end=2020, tags=["#watch"]
    )
    score = scoreboard(conn, filters)
    assert int(score.iloc[0]["nights"]) == 2
    conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("DATA_DUMPS_WAREHOUSE", str(tmp_path / "catalog.duckdb"))
    zip_path = make_mini_sleep_zip(tmp_path)
    assert main([str(zip_path), "--db", str(tmp_path / "catalog.duckdb")]) == 0
