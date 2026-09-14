"""Unit tests for Compare/Correlate series factories."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from data_dumps.series_catalog import (
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    monthly_from_daily,
)


def _monthly_load(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    del conn, year_start, year_end
    return pd.DataFrame({"year_month": ["2024-01", "2024-02"], "value": [1.0, 3.0]})


def _daily_load(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    del conn, year_start, year_end
    return pd.DataFrame(
        {
            "day": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-02-01"]),
            "value": [1.0, 2.0, 4.0],
        }
    )


def _entity_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    del conn, year_start, year_end
    return pd.DataFrame({"year_month": ["2024-01"], "value": [float(len(entity))]})


def test_make_compare_total_packs():
    spec = make_compare_total(
        id="toy_total",
        label="Toy · total",
        source="toy",
        schema="toy",
        table="t",
        unit="u",
        value_col="value",
        load_monthly=_monthly_load,
    )
    conn = duckdb.connect(":memory:")
    out = spec.fetch(conn, 2024, 2024, None)
    conn.close()
    assert list(out["series_id"]) == ["toy_total", "toy_total"]
    assert out["value"].tolist() == [1.0, 3.0]
    assert out["series_label"].iloc[0] == "Toy · total"


def test_make_compare_entity_requires_entity():
    spec = make_compare_entity(
        id="toy_entity",
        label="Toy · entity",
        source="toy",
        schema="toy",
        table="t",
        unit="u",
        value_col="value",
        load_monthly=_entity_monthly,
        entity_options=lambda *a, **k: [],
    )
    conn = duckdb.connect(":memory:")
    empty = spec.fetch(conn, None, None, None)
    filled = spec.fetch(conn, None, None, "abc")
    conn.close()
    assert empty.empty
    assert filled["value"].tolist() == [3.0]
    assert "abc" in filled["series_label"].iloc[0]


def test_make_correlate_metric_daily_and_monthly():
    spec = make_correlate_metric(
        id="toy_metric",
        label="Toy · metric",
        source="toy",
        schema="toy",
        table="t",
        unit="u",
        supports_daily=True,
        supports_monthly=True,
        value_col="value",
        load_daily=_daily_load,
        load_monthly=lambda c, ys, ye: _monthly_load(c, ys, ye).assign(
            time_key=pd.to_datetime(["2024-01-01", "2024-02-01"])
        ),
    )
    conn = duckdb.connect(":memory:")
    daily = spec.fetch(conn, None, None, "daily")
    monthly = spec.fetch(conn, None, None, "monthly")
    conn.close()
    assert len(daily) == 3
    assert len(monthly) == 2
    assert set(daily["grain"]) == {"daily"}
    assert set(monthly["grain"]) == {"monthly"}


def test_make_correlate_metric_monthly_only_rejects_daily():
    spec = make_correlate_metric(
        id="toy_monthly",
        label="Toy · monthly",
        source="toy",
        schema="toy",
        table="t",
        unit="u",
        supports_daily=False,
        supports_monthly=True,
        value_col="value",
        load_monthly=lambda c, ys, ye: _monthly_load(c, ys, ye).assign(
            time_key=pd.to_datetime(["2024-01-01", "2024-02-01"])
        ),
    )
    conn = duckdb.connect(":memory:")
    assert spec.fetch(conn, None, None, "daily").empty
    assert not spec.fetch(conn, None, None, "monthly").empty
    conn.close()


def test_make_correlate_metric_requires_loaders():
    with pytest.raises(ValueError, match="load_daily"):
        make_correlate_metric(
            id="bad",
            label="bad",
            source="toy",
            schema="toy",
            table="t",
            unit="u",
            supports_daily=True,
            supports_monthly=False,
            value_col="value",
        )


def test_monthly_from_daily_sum_and_mean():
    daily = _daily_load(duckdb.connect(":memory:"), None, None)
    summed = monthly_from_daily(daily, value_col="value", how="sum")
    meaned = monthly_from_daily(daily, value_col="value", how="mean")
    assert summed.set_index("year_month")["value"].to_dict() == {
        "2024-01": 3.0,
        "2024-02": 4.0,
    }
    assert meaned.set_index("year_month")["value"].to_dict() == {
        "2024-01": 1.5,
        "2024-02": 4.0,
    }
