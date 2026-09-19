"""Compare / Correlations series for airbnb.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps import airbnb_queries as abq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30

# --- Airbnb ------------------------------------------------------------------


def _airbnb_reservations_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return abq.reservations_monthly_total(conn, year_start, year_end)


def _airbnb_reservations_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return abq.reservations_daily_total(conn, year_start, year_end)


def _airbnb_reservations_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_airbnb_reservations_monthly(conn, year_start, year_end))


def _airbnb_nights_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return abq.nights_monthly_total(conn, year_start, year_end)


def _airbnb_nights_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return abq.nights_daily_total(conn, year_start, year_end)


def _airbnb_nights_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_airbnb_nights_monthly(conn, year_start, year_end))


def _airbnb_searches_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return abq.searches_monthly_total(conn, year_start, year_end)


def _airbnb_searches_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return abq.searches_daily_total(conn, year_start, year_end)


def _airbnb_searches_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_airbnb_searches_monthly(conn, year_start, year_end))


def _airbnb_place_options(
    conn: duckdb.DuckDBPyConnection, *_args: Any, **_kwargs: Any
) -> list[dict[str, str]]:
    return abq.place_options(conn)[:ENTITY_OPTION_LIMIT]


def _airbnb_place_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    f = abq.FilterState(year_start=year_start, year_end=year_end)
    return abq.searches_monthly_for_place(conn, f, entity)


AIRBNB_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="airbnb_reservations",
        label="Airbnb · reservations",
        source="airbnb",
        schema="airbnb",
        table="reservations",
        unit="reservations",
        value_col="reservations",
        load_monthly=_airbnb_reservations_monthly,
    ),
    make_compare_total(
        id="airbnb_nights",
        label="Airbnb · accepted nights",
        source="airbnb",
        schema="airbnb",
        table="reservations",
        unit="nights",
        value_col="nights",
        load_monthly=_airbnb_nights_monthly,
    ),
    make_compare_total(
        id="airbnb_searches",
        label="Airbnb · searches",
        source="airbnb",
        schema="airbnb",
        table="searches",
        unit="searches",
        value_col="searches",
        load_monthly=_airbnb_searches_monthly,
    ),
    make_compare_entity(
        id="airbnb_place",
        label="Airbnb · search place",
        source="airbnb",
        schema="airbnb",
        table="searches",
        unit="searches",
        value_col="searches",
        load_monthly=_airbnb_place_monthly,
        entity_options=_airbnb_place_options,
    ),
)

AIRBNB_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="airbnb_reservations",
        label="Airbnb · reservations",
        source="airbnb",
        schema="airbnb",
        table="reservations",
        unit="reservations",
        supports_daily=True,
        supports_monthly=True,
        value_col="reservations",
        load_daily=_airbnb_reservations_daily,
        load_monthly=_airbnb_reservations_corr_monthly,
    ),
    make_correlate_metric(
        id="airbnb_nights",
        label="Airbnb · accepted nights",
        source="airbnb",
        schema="airbnb",
        table="reservations",
        unit="nights",
        supports_daily=True,
        supports_monthly=True,
        value_col="nights",
        load_daily=_airbnb_nights_daily,
        load_monthly=_airbnb_nights_corr_monthly,
    ),
    make_correlate_metric(
        id="airbnb_searches",
        label="Airbnb · searches",
        source="airbnb",
        schema="airbnb",
        table="searches",
        unit="searches",
        supports_daily=True,
        supports_monthly=True,
        value_col="searches",
        load_daily=_airbnb_searches_daily,
        load_monthly=_airbnb_searches_corr_monthly,
    ),
)
