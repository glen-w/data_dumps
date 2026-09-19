"""Compare / Correlations series for chatgpt.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps import chatgpt_queries as cgq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30

# --- ChatGPT -----------------------------------------------------------------


def _chatgpt_messages_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return cgq.messages_monthly_total(conn, year_start, year_end)


def _chatgpt_messages_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return cgq.messages_daily_total(conn, year_start, year_end)


def _chatgpt_messages_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_chatgpt_messages_monthly(conn, year_start, year_end))


def _chatgpt_conversations_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return cgq.conversations_monthly_total(conn, year_start, year_end)


def _chatgpt_conversations_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return cgq.conversations_daily_total(conn, year_start, year_end)


def _chatgpt_conversations_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_chatgpt_conversations_monthly(conn, year_start, year_end))


def _chatgpt_conversation_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    return cgq.conversation_messages_monthly(conn, year_start, year_end, entity)


def _chatgpt_conversation_options(
    conn: duckdb.DuckDBPyConnection, *_args: Any, **_kwargs: Any
) -> list[dict[str, str]]:
    return cgq.conversation_options(conn)[:ENTITY_OPTION_LIMIT]


CHATGPT_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="chatgpt_messages",
        label="ChatGPT · messages",
        source="chatgpt",
        schema="chatgpt",
        table="messages",
        unit="messages",
        value_col="messages",
        load_monthly=_chatgpt_messages_monthly,
    ),
    make_compare_total(
        id="chatgpt_conversations",
        label="ChatGPT · conversations",
        source="chatgpt",
        schema="chatgpt",
        table="conversations",
        unit="conversations",
        value_col="conversations",
        load_monthly=_chatgpt_conversations_monthly,
    ),
    make_compare_entity(
        id="chatgpt_conversation",
        label="ChatGPT · conversation",
        source="chatgpt",
        schema="chatgpt",
        table="messages",
        unit="messages",
        value_col="messages",
        load_monthly=_chatgpt_conversation_monthly,
        entity_options=_chatgpt_conversation_options,
    ),
)

CHATGPT_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="chatgpt_messages",
        label="ChatGPT · messages",
        source="chatgpt",
        schema="chatgpt",
        table="messages",
        unit="messages",
        supports_daily=True,
        supports_monthly=True,
        value_col="messages",
        load_daily=_chatgpt_messages_daily,
        load_monthly=_chatgpt_messages_corr_monthly,
    ),
    make_correlate_metric(
        id="chatgpt_conversations",
        label="ChatGPT · conversations",
        source="chatgpt",
        schema="chatgpt",
        table="conversations",
        unit="conversations",
        supports_daily=True,
        supports_monthly=True,
        value_col="conversations",
        load_daily=_chatgpt_conversations_daily,
        load_monthly=_chatgpt_conversations_corr_monthly,
    ),
)
