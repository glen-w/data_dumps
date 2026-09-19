"""Warehouse homepage totals."""

from __future__ import annotations

import duckdb

from data_dumps.overview_queries import sources_frame, warehouse_overview

from .conftest import make_plays_conn


def test_warehouse_overview_empty() -> None:
    conn = duckdb.connect()
    try:
        overview = warehouse_overview(conn)
    finally:
        conn.close()
    assert overview.n_sources == 0
    assert overview.n_rows == 0
    assert overview.n_tables == 0
    assert overview.sources == ()
    assert overview.n_years is None
    assert sources_frame(overview).empty


def test_warehouse_overview_rolls_up_schema_and_span(tmp_path) -> None:
    conn, _ = make_plays_conn(tmp_path)
    try:
        # Same schema as plays: counts toward Spotify, not a second source.
        conn.execute("CREATE TABLE spotify.extra AS SELECT 1 AS n FROM range(3)")
        conn.execute("CREATE SCHEMA scratch")
        conn.execute("CREATE TABLE scratch.events AS SELECT 1 AS id FROM range(2)")
        plays = conn.execute("SELECT count(*) FROM spotify.plays").fetchone()
        assert plays is not None

        overview = warehouse_overview(conn)
        by_label = {source.label: source for source in overview.sources}
        assert set(by_label) == {"Spotify", "Scratch"}
        assert overview.n_sources == 2
        assert by_label["Spotify"].rows == int(plays[0]) + 3
        assert by_label["Spotify"].min_year == 2016
        assert by_label["Spotify"].max_year == 2020
        assert by_label["Spotify"].first_day is not None
        assert by_label["Scratch"].rows == 2
        assert by_label["Scratch"].min_year is None
        assert overview.n_rows == by_label["Spotify"].rows + 2
        assert overview.min_year == 2016
        assert overview.max_year == 2020
        assert overview.n_years == 5
        assert overview.first_day is not None
        assert overview.last_day is not None
        assert overview.first_day <= overview.last_day

        ranked = sorted(overview.sources, key=lambda s: (-s.rows, s.label.casefold()))
        frame = sources_frame(overview)
        assert list(frame["Source"]) == [s.label for s in ranked]
        assert frame.loc[frame["Source"] == "Spotify", "Years"].item() == "2016 → 2020"
    finally:
        conn.close()


def test_warehouse_overview_reuses_bounds(tmp_path) -> None:
    conn, _ = make_plays_conn(tmp_path)
    try:
        fresh = warehouse_overview(conn)
        reused = warehouse_overview(
            conn,
            bounds_by_slug={
                "spotify": {
                    "min_year": 2001,
                    "max_year": 2002,
                    "first_day": fresh.first_day,
                    "last_day": fresh.last_day,
                }
            },
        )
    finally:
        conn.close()
    assert reused.n_rows == fresh.n_rows
    assert reused.min_year == 2001
    assert reused.max_year == 2002
    assert reused.n_years == 2
    assert {s.label for s in reused.sources} == {"Spotify"}
