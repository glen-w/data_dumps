"""Amazon query smoke tests on the synthetic multipart fixture."""

from __future__ import annotations

import duckdb
import pytest

from data_dumps import amazon_queries as amzq
from data_dumps.sources.amazon import AmazonSource

from .test_amazon_ingest import make_mini_amazon_dir


@pytest.fixture
def amz_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "amz.duckdb"))
    AmazonSource().load(make_mini_amazon_dir(tmp_path), conn)
    yield conn
    conn.close()


def test_amazon_query_smoke(amz_conn):
    bounds = amzq.data_bounds(amz_conn)
    filters = amzq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    score = amzq.scoreboard(amz_conn, filters)
    assert not score.empty
    assert int(score.iloc[0]["order_lines"]) >= 1

    cal = amzq.order_calendar(amz_conn, filters)
    assert not cal.empty
    assert "day" in cal.columns

    circ = amzq.order_circadian(amz_conn, filters)
    assert set(circ.columns) >= {"dow", "hour"}
