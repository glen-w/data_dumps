"""Mi Band HR ingest smoke tests."""

import duckdb

from data_dumps.ingest import main, pick_source
from data_dumps.miband_queries import data_bounds, filter_from_widgets, scoreboard
from data_dumps.sources.base import Source
from data_dumps.sources.miband import MiBandSource

MINI_CSV = """dateTime,rate,rateZone
01.02.2018 12:00:00,72,40%
01.02.2018 12:01:00,75,42%
01.02.2018 18:00:00,110,70%
"""


def test_detect_csv(tmp_path):
    csv_path = tmp_path / "heart_rate.csv"
    csv_path.write_text(MINI_CSV)
    source = MiBandSource()
    assert source.detect(csv_path)
    assert isinstance(source, Source)


def test_detect_folder(tmp_path):
    folder = tmp_path / "miband_hr"
    folder.mkdir()
    (folder / "heart_rate.csv").write_text(MINI_CSV)
    assert MiBandSource().detect(folder)


def test_pick_source(tmp_path):
    csv_path = tmp_path / "heart_rate.csv"
    csv_path.write_text(MINI_CSV)
    source = pick_source(csv_path)
    assert source is not None
    assert source.name == "miband"


def test_load_and_queries(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    csv_path = tmp_path / "heart_rate.csv"
    csv_path.write_text(MINI_CSV)
    db_path = tmp_path / "w.duckdb"
    conn = duckdb.connect(str(db_path))
    source = MiBandSource()
    source.load(csv_path, conn)
    inv = source.inventory(conn)
    assert inv["n_readings"] == 3
    assert "miband.heart_rate" in inv["summary"]
    bounds = data_bounds(conn)
    filters = filter_from_widgets(bounds, year_start=2018, year_end=2018)
    score = scoreboard(conn, filters)
    assert int(score.iloc[0]["readings"]) == 3
    conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    csv_path = tmp_path / "heart_rate.csv"
    csv_path.write_text(MINI_CSV)
    assert main([str(csv_path), "--db", str(tmp_path / "catalog.duckdb")]) == 0
