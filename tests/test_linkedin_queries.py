"""LinkedIn query smoke tests on the synthetic GDPR zip."""

from __future__ import annotations

import duckdb
import pytest

from data_dumps import linkedin_queries as liq
from data_dumps.sources.linkedin import LinkedInSource

from .test_linkedin_ingest import make_mini_linkedin_zip


@pytest.fixture
def li_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "li.duckdb"))
    LinkedInSource().load(make_mini_linkedin_zip(tmp_path), conn)
    yield conn
    conn.close()


def test_linkedin_query_smoke(li_conn):
    bounds = liq.data_bounds(li_conn)
    filters = liq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    score = liq.scoreboard(li_conn, filters)
    assert not score.empty
    assert int(score.iloc[0]["messages"]) >= 1

    cal = liq.calendar_daily(li_conn, filters)
    assert not cal.empty
    assert "day" in cal.columns

    circ = liq.circadian_heatmap(li_conn, filters)
    assert set(circ.columns) >= {"dow", "hour"}
