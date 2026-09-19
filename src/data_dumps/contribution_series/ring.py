"""Compare / Correlations series for ring.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import ring_queries as ringq
from data_dumps.series_catalog import (
    Grain,
    MetricSpec,
    SeriesSpec,
    make_compare_total,
    make_correlate_metric,
    monthly_from_daily,
    pack_compare,
    pack_correlate,
    ym_from_date_col,
    ym_string_to_ts,
)

# --- Ring --------------------------------------------------------------------


def _ring_events_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    f = ringq.FilterState(year_start=year_start, year_end=year_end)
    df = ym_from_date_col(ringq.monthly_events(conn, f), "month")
    return pack_compare(
        df,
        value_col="events",
        series_id="ring_events",
        series_label="Ring · events",
        unit="events",
    )


def _ring_events_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    f = ringq.FilterState(year_start=year_start, year_end=year_end)
    mid, label, unit = "ring_events", "Ring · events", "events"
    if grain == "daily":
        return pack_correlate(
            ringq.calendar_daily_events(conn, f),
            time_col="day",
            value_col="events",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )
    df = ringq.monthly_events(conn, f).rename(columns={"month": "time_key"})
    return pack_correlate(
        df,
        time_col="time_key",
        value_col="events",
        metric_id=mid,
        metric_label=label,
        unit=unit,
        grain=grain,
    )


def _ring_flips_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ringq.FilterState(year_start=year_start, year_end=year_end)
    return ringq.daily_offline_flips(conn, f)


def _ring_flips_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return monthly_from_daily(
        _ring_flips_daily(conn, year_start, year_end),
        value_col="flips",
        how="sum",
    )


def _ring_flips_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_ring_flips_monthly(conn, year_start, year_end))


def _ring_motion_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ringq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(ringq.monthly_motion_events(conn, f), "month")


def _ring_motion_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ringq.FilterState(year_start=year_start, year_end=year_end)
    return ringq.calendar_daily_motion(conn, f)


def _ring_motion_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ringq.FilterState(year_start=year_start, year_end=year_end)
    return ringq.monthly_motion_events(conn, f).rename(columns={"month": "time_key"})


def _ring_app_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ringq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(ringq.monthly_app_events(conn, f), "month")


def _ring_app_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ringq.FilterState(year_start=year_start, year_end=year_end)
    return ringq.calendar_daily_app_events(conn, f)


def _ring_app_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = ringq.FilterState(year_start=year_start, year_end=year_end)
    return ringq.monthly_app_events(conn, f).rename(columns={"month": "time_key"})


RING_COMPARE: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "ring_events",
        "Ring · events",
        "ring",
        "total",
        "events",
        False,
        "ring",
        "device_events",
        _ring_events_compare,
    ),
    make_compare_total(
        id="ring_motion",
        label="Ring · motion events",
        source="ring",
        schema="ring",
        table="events",
        unit="events",
        value_col="events",
        load_monthly=_ring_motion_monthly,
    ),
    make_compare_total(
        id="ring_app_events",
        label="Ring · app events",
        source="ring",
        schema="ring",
        table="app_events",
        unit="events",
        value_col="events",
        load_monthly=_ring_app_monthly,
    ),
    make_compare_total(
        id="ring_offline_flips",
        label="Ring · offline/online flips",
        source="ring",
        schema="ring",
        table="device_events",
        unit="flips",
        value_col="flips",
        load_monthly=_ring_flips_monthly,
    ),
)

RING_CORRELATE: tuple[MetricSpec, ...] = (
    MetricSpec(
        "ring_events",
        "Ring · events",
        "ring",
        "events",
        "ring",
        "device_events",
        True,
        True,
        _ring_events_correlate,
    ),
    make_correlate_metric(
        id="ring_motion",
        label="Ring · motion events",
        source="ring",
        schema="ring",
        table="events",
        unit="events",
        supports_daily=True,
        supports_monthly=True,
        value_col="events",
        load_daily=_ring_motion_daily,
        load_monthly=_ring_motion_corr_monthly,
    ),
    make_correlate_metric(
        id="ring_app_events",
        label="Ring · app events",
        source="ring",
        schema="ring",
        table="app_events",
        unit="events",
        supports_daily=True,
        supports_monthly=True,
        value_col="events",
        load_daily=_ring_app_daily,
        load_monthly=_ring_app_corr_monthly,
    ),
    make_correlate_metric(
        id="ring_offline_flips",
        label="Ring · offline/online flips",
        source="ring",
        schema="ring",
        table="device_events",
        unit="flips",
        supports_daily=True,
        supports_monthly=True,
        value_col="flips",
        load_daily=_ring_flips_daily,
        load_monthly=_ring_flips_corr_monthly,
    ),
)
