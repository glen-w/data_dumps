"""Compare / Correlations series for telegram.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import telegram_queries as tgq
from data_dumps.series_catalog import (
    Grain,
    MetricSpec,
    SeriesSpec,
    empty_compare,
    entity_label,
    make_compare_total,
    make_correlate_metric,
    pack_compare,
    pack_correlate,
    ym_from_year_month,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30

# --- Telegram ----------------------------------------------------------------


def _telegram_messages_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    f = tgq.FilterState(year_start=year_start, year_end=year_end)
    df = ym_from_year_month(tgq.monthly_messages(conn, f))
    return pack_compare(
        df,
        value_col="events",
        series_id="telegram_messages",
        series_label="Telegram · messages",
        unit="events",
    )


def _telegram_chat_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    f = tgq.FilterState(
        year_start=year_start, year_end=year_end, include_groups=True, include_bots=True
    )
    df = tgq.messages_by_chat(conn, f, limit=limit)
    return [
        {"value": str(r.chat_name), "label": f"{r.chat_name!s} ({r.chat_type!s})"}
        for r in df.itertuples(index=False)
        if r.chat_name
    ]


def _telegram_chat_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    if not entity:
        return empty_compare()
    f = tgq.FilterState(
        year_start=year_start,
        year_end=year_end,
        chat_name=entity,
        include_groups=True,
        include_bots=True,
    )
    df = ym_from_year_month(tgq.monthly_messages(conn, f))
    return pack_compare(
        df,
        value_col="events",
        series_id="telegram_chat",
        series_label=entity_label("Telegram · chat", entity),
        unit="events",
    )


def _telegram_events_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    f = tgq.FilterState(year_start=year_start, year_end=year_end)
    mid, label, unit = "telegram_events", "Telegram · events", "events"
    if grain == "daily":
        return pack_correlate(
            tgq.calendar_daily(conn, f),
            time_col="day",
            value_col="events",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )
    df = ym_string_to_ts(tgq.monthly_messages(conn, f))
    return pack_correlate(
        df,
        time_col="time_key",
        value_col="events",
        metric_id=mid,
        metric_label=label,
        unit=unit,
        grain=grain,
    )


def _telegram_reactions_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = tgq.FilterState(year_start=year_start, year_end=year_end)
    return tgq.reactions_monthly(conn, f)


def _telegram_reactions_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = tgq.FilterState(year_start=year_start, year_end=year_end)
    return tgq.calendar_daily_reactions(conn, f)


def _telegram_reactions_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_telegram_reactions_monthly(conn, year_start, year_end))


TELEGRAM_COMPARE: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "telegram_messages",
        "Telegram · messages",
        "telegram",
        "total",
        "events",
        False,
        "telegram",
        "messages",
        _telegram_messages_compare,
    ),
    make_compare_total(
        id="telegram_reactions",
        label="Telegram · reactions",
        source="telegram",
        schema="telegram",
        table="reactions",
        unit="reactions",
        value_col="reactions",
        load_monthly=_telegram_reactions_monthly,
    ),
    SeriesSpec(
        "telegram_chat",
        "Telegram · chat",
        "telegram",
        "entity",
        "events",
        True,
        "telegram",
        "messages",
        _telegram_chat_compare,
        _telegram_chat_options,
    ),
)

TELEGRAM_CORRELATE: tuple[MetricSpec, ...] = (
    MetricSpec(
        "telegram_events",
        "Telegram · events",
        "telegram",
        "events",
        "telegram",
        "messages",
        True,
        True,
        _telegram_events_correlate,
    ),
    make_correlate_metric(
        id="telegram_reactions",
        label="Telegram · reactions",
        source="telegram",
        schema="telegram",
        table="reactions",
        unit="reactions",
        supports_daily=True,
        supports_monthly=True,
        value_col="reactions",
        load_daily=_telegram_reactions_daily,
        load_monthly=_telegram_reactions_corr_monthly,
    ),
)
