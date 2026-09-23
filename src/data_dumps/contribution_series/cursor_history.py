"""Compare / Correlations series for cursor_history.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps import cursor_history_queries as chq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30


def _ch_messages_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return chq.messages_monthly_total(conn, year_start, year_end)


def _ch_messages_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return chq.messages_daily_total(conn, year_start, year_end)


def _ch_messages_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_ch_messages_monthly(conn, year_start, year_end))


def _ch_sessions_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return chq.sessions_monthly_total(conn, year_start, year_end)


def _ch_sessions_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return chq.sessions_daily_total(conn, year_start, year_end)


def _ch_sessions_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_ch_sessions_monthly(conn, year_start, year_end))


def _ch_session_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    return chq.session_messages_monthly(conn, year_start, year_end, entity)


def _ch_session_options(
    conn: duckdb.DuckDBPyConnection, *_args: Any, **_kwargs: Any
) -> list[dict[str, str]]:
    return chq.session_options(conn)[:ENTITY_OPTION_LIMIT]


CURSOR_HISTORY_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="cursor_history_messages",
        label="Cursor · messages",
        source="cursor_history",
        schema="cursor_history",
        table="messages",
        unit="messages",
        value_col="messages",
        load_monthly=_ch_messages_monthly,
    ),
    make_compare_total(
        id="cursor_history_sessions",
        label="Cursor · sessions",
        source="cursor_history",
        schema="cursor_history",
        table="sessions",
        unit="sessions",
        value_col="sessions",
        load_monthly=_ch_sessions_monthly,
    ),
    make_compare_entity(
        id="cursor_history_session",
        label="Cursor · session",
        source="cursor_history",
        schema="cursor_history",
        table="messages",
        unit="messages",
        value_col="messages",
        load_monthly=_ch_session_monthly,
        entity_options=_ch_session_options,
    ),
)

CURSOR_HISTORY_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="cursor_history_messages",
        label="Cursor · messages",
        source="cursor_history",
        schema="cursor_history",
        table="messages",
        unit="messages",
        supports_daily=True,
        supports_monthly=True,
        value_col="messages",
        load_daily=_ch_messages_daily,
        load_monthly=_ch_messages_corr_monthly,
    ),
    make_correlate_metric(
        id="cursor_history_sessions",
        label="Cursor · sessions",
        source="cursor_history",
        schema="cursor_history",
        table="sessions",
        unit="sessions",
        supports_daily=True,
        supports_monthly=True,
        value_col="sessions",
        load_daily=_ch_sessions_daily,
        load_monthly=_ch_sessions_corr_monthly,
    ),
)
