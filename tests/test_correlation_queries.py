"""Tests for cross-source Correlations query helpers."""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest

from data_dumps import correlation_queries as crq
from data_dumps.sources.sleep import SleepSource
from data_dumps.sources.telegram import TelegramSource

from .conftest import make_plays_conn
from .test_explorer_panels import _add_miband
from .test_sleep_queries import _make_zip as make_sleep_zip
from .test_telegram_ingest import make_mini_telegram_dir


@pytest.fixture
def corr_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn, _ = make_plays_conn(tmp_path)
    SleepSource().load(make_sleep_zip(tmp_path), conn)
    _add_miband(conn)
    TelegramSource().load(make_mini_telegram_dir(tmp_path), conn)
    yield conn
    conn.close()


def test_list_available_and_bounds(corr_conn):
    mets = crq.list_available_metrics(corr_conn)
    ids = {m.id for m in mets}
    assert "spotify_hours" in ids
    assert "sleep_hours" in ids
    assert "telegram_events" in ids
    assert "miband_bpm" in ids
    b = crq.correlate_bounds(corr_conn)
    assert b["n_metrics"] >= 4
    assert b["min_year"] <= b["max_year"]


def test_apply_presets(corr_conn):
    avail = crq.list_available_metrics(corr_conn)
    life, focus = crq.apply_preset(crq.PRESET_LIFE_RHYTHM, avail)
    assert "sleep_hours" in life
    assert "spotify_hours" in life
    assert focus is None or len(focus) == 2
    body, _ = crq.apply_preset(crq.PRESET_SLEEP_BODY, avail)
    assert "spotify_late_hours" in body or "miband_bpm" in body


def test_fetch_panel_daily(corr_conn):
    long_df = crq.fetch_panel(
        corr_conn,
        ["spotify_hours", "sleep_hours", "telegram_events"],
        grain="daily",
    )
    assert set(long_df.columns) == set(crq.LONG_COLS)
    assert not long_df.empty
    assert set(long_df["metric_id"]) <= {
        "spotify_hours",
        "sleep_hours",
        "telegram_events",
    }
    wide = crq.pivot_panel(long_df)
    assert wide.shape[1] >= 1


def test_correlation_matrix_and_min_n():
    idx = pd.date_range("2020-01-01", periods=40, freq="D")
    wide = pd.DataFrame(
        {
            "a": np.arange(40, dtype=float),
            "b": np.arange(40, dtype=float) * 2,
            "c": np.random.default_rng(0).normal(size=40),
        },
        index=idx,
    )
    mat = crq.correlation_matrix(wide, grain="daily", min_n=30)
    assert mat.loc["a", "b"] == pytest.approx(1.0)
    assert mat.loc["a", "a"] == 1.0

    short = wide.iloc[:10]
    mat_short = crq.correlation_matrix(short, grain="daily", min_n=30)
    assert pd.isna(mat_short.loc["a", "b"])


def test_rank_pairs_and_aligned():
    idx = pd.date_range("2020-01-01", periods=40, freq="D")
    wide = pd.DataFrame(
        {"x": np.linspace(0, 1, 40), "y": np.linspace(0, 1, 40)},
        index=idx,
    )
    pairs = crq.rank_pairs(wide, grain="daily", labels={"x": "X", "y": "Y"})
    assert not pairs.empty
    assert pairs.iloc[0]["abs_r"] == pytest.approx(1.0)
    scatter = crq.aligned_pair(wide, "x", "y")
    assert len(scatter) == 40
    assert {"day", "x", "y"} <= set(scatter.columns)


def test_lag_scan_peak_at_zero():
    idx = pd.date_range("2020-01-01", periods=60, freq="D")
    a = pd.Series(np.sin(np.linspace(0, 6, 60)), index=idx)
    b = a.copy()
    lag_df, best_lag, best_r = crq.lag_scan(a, b, max_lag=5, min_n=30)
    assert best_lag == 0
    assert best_r == pytest.approx(1.0, abs=1e-6)
    assert not lag_df.empty


def test_lag_scan_shifted():
    idx = pd.date_range("2020-01-01", periods=80, freq="D")
    a = pd.Series(np.sin(np.linspace(0, 8, 80)), index=idx)
    # B is A delayed by 3 days → best lag is -3 under shift(freq) convention
    # (positive shift moves B later; negative lag pulls delayed B back onto A).
    b = a.shift(3, freq="D")
    _, best_lag, best_r = crq.lag_scan(a, b, max_lag=7, min_n=30)
    assert best_lag == -3
    assert best_r is not None and best_r > 0.9


def test_max_metrics_cap(corr_conn):
    ids = [m.id for m in crq.list_available_metrics(corr_conn)] * 3
    long_df = crq.fetch_panel(corr_conn, ids, grain="daily")
    assert long_df["metric_id"].nunique() <= crq.MAX_METRICS


def test_empty_warehouse(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "empty.duckdb"))
    try:
        assert crq.list_available_metrics(conn) == []
        assert crq.correlate_bounds(conn)["n_metrics"] == 0
        assert crq.fetch_panel(conn, ["spotify_hours"]).empty
    finally:
        conn.close()


def test_zscore_long():
    df = pd.DataFrame(
        {
            "time_key": pd.date_range("2020-01-01", periods=4, freq="D").tolist() * 1,
            "metric_id": ["a"] * 4,
            "metric_label": ["A"] * 4,
            "value": [0.0, 10.0, 20.0, 30.0],
            "unit": ["x"] * 4,
            "grain": ["daily"] * 4,
        }
    )
    out = crq.zscore_long(df, ["a"])
    assert "z" in out.columns
    assert out["z"].mean() == pytest.approx(0.0, abs=1e-9)


def test_fetch_panel_monthly_and_late_hours(corr_conn):
    monthly = crq.fetch_panel(
        corr_conn,
        ["spotify_hours", "telegram_events", "sleep_hours"],
        grain="monthly",
    )
    assert not monthly.empty
    assert (monthly["grain"] == "monthly").all()
    late = crq.fetch_panel(corr_conn, ["spotify_late_hours"], grain="daily")
    # Mini Spotify fixture may or may not have hour>=22 plays.
    assert set(late.columns) == set(crq.LONG_COLS)


def test_monthly_matrix_min_n():
    idx = pd.date_range("2018-01-01", periods=14, freq="MS")
    wide = pd.DataFrame(
        {"a": np.arange(14, dtype=float), "b": np.arange(14, dtype=float)[::-1]},
        index=idx,
    )
    mat = crq.correlation_matrix(wide, grain="monthly", min_n=12)
    assert not pd.isna(mat.loc["a", "b"])
    mat_short = crq.correlation_matrix(wide.iloc[:5], grain="monthly")
    assert pd.isna(mat_short.loc["a", "b"])


def test_amazon_orders_metric(tmp_path, monkeypatch):
    from data_dumps.sources.amazon import AmazonSource

    from .test_amazon_ingest import make_mini_amazon_dir

    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "amz.duckdb"))
    try:
        AmazonSource().load(make_mini_amazon_dir(tmp_path), conn)
        ids = {m.id for m in crq.list_available_metrics(conn)}
        assert "amazon_orders" in ids
        daily = crq.fetch_panel(conn, ["amazon_orders"], grain="daily")
        monthly = crq.fetch_panel(conn, ["amazon_orders"], grain="monthly")
        assert not daily.empty or not monthly.empty
    finally:
        conn.close()


def test_no_browser_or_ring_in_catalog():
    ids = {m.id for m in crq.METRICS}
    assert not any("browser" in i for i in ids)
    assert not any(i.startswith("ring") for i in ids)


def test_spearman_without_scipy():
    idx = pd.date_range("2020-01-01", periods=40, freq="D")
    wide = pd.DataFrame(
        {"x": np.linspace(0, 1, 40), "y": np.linspace(1, 0, 40)},
        index=idx,
    )
    pairs = crq.rank_pairs(wide, grain="daily")
    assert not pairs.empty
    assert pairs.iloc[0]["r_spearman"] == pytest.approx(-1.0)
