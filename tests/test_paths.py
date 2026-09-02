"""Path helpers."""

from data_dumps.paths import data_root, inbox_dir, raw_dir, warehouse_db


def test_data_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    assert data_root() == tmp_path


def test_warehouse_db_env(monkeypatch, tmp_path):
    custom = tmp_path / "custom.duckdb"
    monkeypatch.setenv("DATA_DUMPS_WAREHOUSE", str(custom))
    assert warehouse_db() == custom


def test_warehouse_db_default_under_root():
    root = data_root()
    assert warehouse_db() == root / "warehouse" / "catalog.duckdb"


def test_raw_and_inbox_under_root():
    root = data_root()
    assert raw_dir("spotify") == root / "raw" / "spotify"
    assert inbox_dir() == root / "inbox"
