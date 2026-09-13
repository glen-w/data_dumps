"""Thunderbird query smoke tests on the synthetic Gloda profile."""

from __future__ import annotations

import duckdb
import pytest

from data_dumps import thunderbird_queries as tbq
from data_dumps.sources.thunderbird import ThunderbirdSource

from .test_thunderbird_ingest import make_mini_gloda_profile


@pytest.fixture
def tb_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "tb.duckdb"))
    ThunderbirdSource().load(make_mini_gloda_profile(tmp_path), conn)
    yield conn
    conn.close()


def test_thunderbird_query_smoke(tb_conn):
    bounds = tbq.data_bounds(tb_conn)
    filters = tbq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    score = tbq.scoreboard(tb_conn, filters)
    assert not score.empty
    assert int(score.iloc[0]["messages"]) >= 1

    cal = tbq.calendar_daily(tb_conn, filters)
    assert not cal.empty
    assert "day" in cal.columns

    circ = tbq.circadian_heatmap(tb_conn, filters)
    assert set(circ.columns) >= {"dow", "hour"}
