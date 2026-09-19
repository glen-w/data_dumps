"""Compare / Correlations series for sleep.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import sleep_queries as slq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_total,
    make_correlate_metric,
    ym_from_date_col,
)

# --- Sleep -------------------------------------------------------------------


def _sleep_hours_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = slq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(slq.monthly_hours(conn, f), "month")


def _sleep_hours_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = slq.FilterState(year_start=year_start, year_end=year_end)
    return slq.calendar_daily(conn, f)


def _sleep_hours_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = slq.FilterState(year_start=year_start, year_end=year_end)
    return slq.monthly_hours(conn, f).rename(columns={"month": "time_key"})


def _sleep_snore_noise_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = slq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(slq.snore_noise_monthly(conn, f), "month")


def _sleep_snore_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = slq.FilterState(year_start=year_start, year_end=year_end)
    return slq.snore_noise_monthly(conn, f).rename(columns={"month": "time_key"})


SLEEP_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="sleep_hours",
        label="Sleep · avg hours",
        source="sleep",
        schema="sleep",
        table="sessions",
        unit="hours",
        value_col="avg_hours",
        load_monthly=_sleep_hours_monthly,
    ),
    make_compare_total(
        id="sleep_snore",
        label="Sleep · avg snore",
        source="sleep",
        schema="sleep",
        table="sessions",
        unit="snore",
        value_col="avg_snore",
        load_monthly=_sleep_snore_noise_monthly,
    ),
    make_compare_total(
        id="sleep_noise",
        label="Sleep · avg noise",
        source="sleep",
        schema="sleep",
        table="sessions",
        unit="noise",
        value_col="avg_noise",
        load_monthly=_sleep_snore_noise_monthly,
    ),
)

SLEEP_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="sleep_hours",
        label="Sleep · hours",
        source="sleep",
        schema="sleep",
        table="sessions",
        unit="hours",
        supports_daily=True,
        supports_monthly=True,
        value_col="hours",
        load_daily=_sleep_hours_daily,
        load_monthly=_sleep_hours_corr_monthly,
        monthly_value_col="avg_hours",
    ),
    make_correlate_metric(
        id="sleep_snore",
        label="Sleep · avg snore",
        source="sleep",
        schema="sleep",
        table="sessions",
        unit="snore",
        supports_daily=False,
        supports_monthly=True,
        value_col="avg_snore",
        load_monthly=_sleep_snore_corr_monthly,
    ),
    make_correlate_metric(
        id="sleep_noise",
        label="Sleep · avg noise",
        source="sleep",
        schema="sleep",
        table="sessions",
        unit="noise",
        supports_daily=False,
        supports_monthly=True,
        value_col="avg_noise",
        load_monthly=_sleep_snore_corr_monthly,
    ),
)
