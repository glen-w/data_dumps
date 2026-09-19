"""Compare / Correlations series for uber.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps import uber_queries as ubq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30

# --- Uber --------------------------------------------------------------------


def _uber_trips_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ubq.FilterState(year_start=year_start, year_end=year_end)
    return ubq.trips_monthly(conn, f).rename(columns={"trips": "trips"})


def _uber_trips_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ubq.FilterState(year_start=year_start, year_end=year_end)
    return ubq.trips_daily_total(conn, f)


def _uber_trips_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_uber_trips_monthly(conn, year_start, year_end))


def _uber_eats_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ubq.FilterState(year_start=year_start, year_end=year_end)
    return ubq.eats_orders_monthly(conn, f)


def _uber_eats_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ubq.FilterState(year_start=year_start, year_end=year_end)
    return ubq.eats_orders_daily(conn, f)


def _uber_eats_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_uber_eats_monthly(conn, year_start, year_end))


def _uber_city_options(
    conn: duckdb.DuckDBPyConnection, *_args: Any, **_kwargs: Any
) -> list[dict[str, str]]:
    return ubq.city_options(conn)[:ENTITY_OPTION_LIMIT]


def _uber_city_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    f = ubq.FilterState(year_start=year_start, year_end=year_end)
    return ubq.trips_monthly_for_city(conn, f, entity)


UBER_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="uber_trips",
        label="Uber · trips",
        source="uber",
        schema="uber",
        table="trips",
        unit="trips",
        value_col="trips",
        load_monthly=_uber_trips_monthly,
    ),
    make_compare_total(
        id="uber_eats_orders",
        label="Uber · Eats orders",
        source="uber",
        schema="uber",
        table="order_items",
        unit="orders",
        value_col="orders",
        load_monthly=_uber_eats_monthly,
    ),
    make_compare_entity(
        id="uber_city",
        label="Uber · city",
        source="uber",
        schema="uber",
        table="trips",
        unit="trips",
        value_col="trips",
        load_monthly=_uber_city_monthly,
        entity_options=_uber_city_options,
    ),
)

UBER_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="uber_trips",
        label="Uber · trips",
        source="uber",
        schema="uber",
        table="trips",
        unit="trips",
        supports_daily=True,
        supports_monthly=True,
        value_col="trips",
        load_daily=_uber_trips_daily,
        load_monthly=_uber_trips_corr_monthly,
    ),
    make_correlate_metric(
        id="uber_eats_orders",
        label="Uber · Eats orders",
        source="uber",
        schema="uber",
        table="order_items",
        unit="orders",
        supports_daily=True,
        supports_monthly=True,
        value_col="orders",
        load_daily=_uber_eats_daily,
        load_monthly=_uber_eats_corr_monthly,
    ),
)
