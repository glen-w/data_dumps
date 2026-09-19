"""Compare / Correlations series for google.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps import google_queries as gq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30

# --- Google Takeout ----------------------------------------------------------


def _google_calendar_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return gq.calendar_events_monthly_total(conn, year_start, year_end)


def _google_calendar_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return gq.calendar_events_daily_total(conn, year_start, year_end)


def _google_calendar_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_google_calendar_monthly(conn, year_start, year_end))


def _google_photos_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return gq.photos_monthly_total(conn, year_start, year_end)


def _google_photos_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return gq.photos_daily_total(conn, year_start, year_end)


def _google_photos_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_google_photos_monthly(conn, year_start, year_end))


def _google_maps_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return gq.maps_saves_monthly_total(conn, year_start, year_end)


def _google_maps_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return gq.maps_saves_daily_total(conn, year_start, year_end)


def _google_maps_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_google_maps_monthly(conn, year_start, year_end))


def _google_play_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return gq.play_installs_monthly_total(conn, year_start, year_end)


def _google_cal_options(
    conn: duckdb.DuckDBPyConnection, *_args: Any, **_kwargs: Any
) -> list[dict[str, str]]:
    return gq.calendar_name_options(conn)[:ENTITY_OPTION_LIMIT]


def _google_cal_entity_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    return gq.calendar_for_name_monthly(conn, year_start, year_end, entity)


GOOGLE_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="google_calendar",
        label="Google · calendar events",
        source="google",
        schema="google",
        table="calendar_events",
        unit="events",
        value_col="events",
        load_monthly=_google_calendar_monthly,
    ),
    make_compare_total(
        id="google_photos",
        label="Google · photos",
        source="google",
        schema="google",
        table="photos",
        unit="photos",
        value_col="photos",
        load_monthly=_google_photos_monthly,
    ),
    make_compare_total(
        id="google_maps_saves",
        label="Google · map saves",
        source="google",
        schema="google",
        table="maps_saves",
        unit="saves",
        value_col="saves",
        load_monthly=_google_maps_monthly,
    ),
    make_compare_total(
        id="google_play_installs",
        label="Google · Play installs",
        source="google",
        schema="google",
        table="play_installs",
        unit="installs",
        value_col="installs",
        load_monthly=_google_play_monthly,
    ),
    make_compare_entity(
        id="google_calendar_name",
        label="Google · calendar",
        source="google",
        schema="google",
        table="calendar_events",
        unit="events",
        value_col="events",
        load_monthly=_google_cal_entity_monthly,
        entity_options=_google_cal_options,
    ),
)

GOOGLE_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="google_calendar",
        label="Google · calendar events",
        source="google",
        schema="google",
        table="calendar_events",
        unit="events",
        supports_daily=True,
        supports_monthly=True,
        value_col="events",
        load_daily=_google_calendar_daily,
        load_monthly=_google_calendar_corr_monthly,
    ),
    make_correlate_metric(
        id="google_photos",
        label="Google · photos",
        source="google",
        schema="google",
        table="photos",
        unit="photos",
        supports_daily=True,
        supports_monthly=True,
        value_col="photos",
        load_daily=_google_photos_daily,
        load_monthly=_google_photos_corr_monthly,
    ),
    make_correlate_metric(
        id="google_maps_saves",
        label="Google · map saves",
        source="google",
        schema="google",
        table="maps_saves",
        unit="saves",
        supports_daily=True,
        supports_monthly=True,
        value_col="saves",
        load_daily=_google_maps_daily,
        load_monthly=_google_maps_corr_monthly,
    ),
)
