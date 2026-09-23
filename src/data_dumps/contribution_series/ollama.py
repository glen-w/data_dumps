"""Compare / Correlations series for ollama.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps import ollama_queries as olq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30


def _messages_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return olq.messages_monthly_total(conn, year_start, year_end)


def _messages_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return olq.messages_daily_total(conn, year_start, year_end)


def _messages_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_messages_monthly(conn, year_start, year_end))


def _chats_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return olq.chats_monthly_total(conn, year_start, year_end)


def _chats_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return olq.chats_daily_total(conn, year_start, year_end)


def _chats_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_chats_monthly(conn, year_start, year_end))


def _chat_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    return olq.chat_messages_monthly(conn, year_start, year_end, entity)


def _chat_options(
    conn: duckdb.DuckDBPyConnection, *_args: Any, **_kwargs: Any
) -> list[dict[str, str]]:
    return olq.chat_options(conn)[:ENTITY_OPTION_LIMIT]


OLLAMA_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="ollama_messages",
        label="Ollama · messages",
        source="ollama",
        schema="ollama",
        table="messages",
        unit="messages",
        value_col="messages",
        load_monthly=_messages_monthly,
    ),
    make_compare_total(
        id="ollama_chats",
        label="Ollama · chats",
        source="ollama",
        schema="ollama",
        table="chats",
        unit="chats",
        value_col="chats",
        load_monthly=_chats_monthly,
    ),
    make_compare_entity(
        id="ollama_chat",
        label="Ollama · chat",
        source="ollama",
        schema="ollama",
        table="messages",
        unit="messages",
        value_col="messages",
        load_monthly=_chat_monthly,
        entity_options=_chat_options,
    ),
)

OLLAMA_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="ollama_messages",
        label="Ollama · messages",
        source="ollama",
        schema="ollama",
        table="messages",
        unit="messages",
        supports_daily=True,
        supports_monthly=True,
        value_col="messages",
        load_daily=_messages_daily,
        load_monthly=_messages_corr_monthly,
    ),
    make_correlate_metric(
        id="ollama_chats",
        label="Ollama · chats",
        source="ollama",
        schema="ollama",
        table="chats",
        unit="chats",
        supports_daily=True,
        supports_monthly=True,
        value_col="chats",
        load_daily=_chats_daily,
        load_monthly=_chats_corr_monthly,
    ),
)
