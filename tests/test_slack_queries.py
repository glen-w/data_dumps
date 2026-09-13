"""Slack query smoke tests on the synthetic workspace fixture."""

from __future__ import annotations

import duckdb
import pytest

from data_dumps import slack_queries as skq
from data_dumps.sources.slack import SlackSource

from .test_slack_ingest import make_mini_slack_zip


@pytest.fixture
def slack_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    SlackSource().load(make_mini_slack_zip(tmp_path), conn)
    yield conn
    conn.close()


def test_slack_query_smoke(slack_conn):
    bounds = skq.data_bounds(slack_conn)
    filters = skq.filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
    )
    score = skq.scoreboard(slack_conn, filters)
    assert not score.empty
    assert int(score.iloc[0]["messages"]) >= 1

    cal = skq.calendar_daily(slack_conn, filters)
    assert not cal.empty
    assert "day" in cal.columns

    circ = skq.circadian_heatmap(slack_conn, filters)
    assert set(circ.columns) >= {"dow", "hour"}
