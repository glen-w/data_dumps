"""Ring query smoke tests on the synthetic multipart zip."""

from __future__ import annotations

import duckdb
import pytest

from data_dumps import ring_queries as ringq
from data_dumps.sources.ring import RingSource

from .test_ring_ingest import make_mini_ring_zip


@pytest.fixture
def ring_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    RingSource().load(make_mini_ring_zip(tmp_path), conn)
    yield conn
    conn.close()


def test_ring_query_smoke(ring_conn):
    bounds = ringq.data_bounds(ring_conn)
    filters = ringq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    score = ringq.scoreboard(ring_conn, filters)
    assert not score.empty
    assert int(score.iloc[0]["devices"]) >= 1
    assert int(score.iloc[0]["device_events"]) >= 1

    daily = ringq.daily_offline_flips(ring_conn, filters)
    assert "day" in daily.columns or daily.empty
