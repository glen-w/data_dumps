"""Compare / Correlations series for linkedin.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import linkedin_queries as liq
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

# --- LinkedIn ----------------------------------------------------------------


def _linkedin_messages_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    f = liq.FilterState(year_start=year_start, year_end=year_end)
    df = ym_from_year_month(liq.monthly_messages(conn, f))
    return pack_compare(
        df,
        value_col="messages",
        series_id="linkedin_messages",
        series_label="LinkedIn · messages",
        unit="messages",
    )


def _linkedin_conversation_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    f = liq.FilterState(year_start=year_start, year_end=year_end)
    df = liq.messages_by_conversation(conn, f, limit=limit)
    return [
        {"value": str(r.conversation), "label": str(r.conversation)}
        for r in df.itertuples(index=False)
        if r.conversation
    ]


def _linkedin_conversation_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    if not entity:
        return empty_compare()
    f = liq.FilterState(year_start=year_start, year_end=year_end, conversation=entity)
    df = ym_from_year_month(liq.monthly_messages(conn, f))
    return pack_compare(
        df,
        value_col="messages",
        series_id="linkedin_conversation",
        series_label=entity_label("LinkedIn · conversation", entity),
        unit="messages",
    )


def _linkedin_events_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    f = liq.FilterState(year_start=year_start, year_end=year_end)
    mid, label, unit = "linkedin_events", "LinkedIn · events", "events"
    if grain == "daily":
        return pack_correlate(
            liq.calendar_daily(conn, f),
            time_col="day",
            value_col="events",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )
    df = ym_string_to_ts(liq.monthly_messages(conn, f))
    return pack_correlate(
        df,
        time_col="time_key",
        value_col="messages",
        metric_id=mid,
        metric_label=label,
        unit=unit,
        grain=grain,
    )


def _linkedin_connections_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = liq.FilterState(year_start=year_start, year_end=year_end)
    return liq.connections_monthly(conn, f)


def _linkedin_connections_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = liq.FilterState(year_start=year_start, year_end=year_end)
    return liq.calendar_daily_connections(conn, f)


def _linkedin_connections_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_linkedin_connections_monthly(conn, year_start, year_end))


def _linkedin_reactions_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = liq.FilterState(year_start=year_start, year_end=year_end)
    return liq.reactions_monthly(conn, f)


def _linkedin_reactions_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = liq.FilterState(year_start=year_start, year_end=year_end)
    return liq.calendar_daily_reactions(conn, f)


def _linkedin_reactions_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_linkedin_reactions_monthly(conn, year_start, year_end))


def _linkedin_shares_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = liq.FilterState(year_start=year_start, year_end=year_end)
    return liq.shares_monthly(conn, f)


def _linkedin_shares_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = liq.FilterState(year_start=year_start, year_end=year_end)
    return liq.calendar_daily_shares(conn, f)


def _linkedin_shares_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_linkedin_shares_monthly(conn, year_start, year_end))


LINKEDIN_COMPARE: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "linkedin_messages",
        "LinkedIn · messages",
        "linkedin",
        "total",
        "messages",
        False,
        "linkedin",
        "messages",
        _linkedin_messages_compare,
    ),
    make_compare_total(
        id="linkedin_connections",
        label="LinkedIn · connections",
        source="linkedin",
        schema="linkedin",
        table="connections",
        unit="connections",
        value_col="connections",
        load_monthly=_linkedin_connections_monthly,
    ),
    make_compare_total(
        id="linkedin_reactions",
        label="LinkedIn · reactions",
        source="linkedin",
        schema="linkedin",
        table="reactions",
        unit="reactions",
        value_col="reactions",
        load_monthly=_linkedin_reactions_monthly,
    ),
    make_compare_total(
        id="linkedin_shares",
        label="LinkedIn · shares",
        source="linkedin",
        schema="linkedin",
        table="shares",
        unit="shares",
        value_col="shares",
        load_monthly=_linkedin_shares_monthly,
    ),
    SeriesSpec(
        "linkedin_conversation",
        "LinkedIn · conversation",
        "linkedin",
        "entity",
        "messages",
        True,
        "linkedin",
        "messages",
        _linkedin_conversation_compare,
        _linkedin_conversation_options,
    ),
)

LINKEDIN_CORRELATE: tuple[MetricSpec, ...] = (
    MetricSpec(
        "linkedin_events",
        "LinkedIn · events",
        "linkedin",
        "events",
        "linkedin",
        "messages",
        True,
        True,
        _linkedin_events_correlate,
    ),
    make_correlate_metric(
        id="linkedin_connections",
        label="LinkedIn · connections",
        source="linkedin",
        schema="linkedin",
        table="connections",
        unit="connections",
        supports_daily=True,
        supports_monthly=True,
        value_col="connections",
        load_daily=_linkedin_connections_daily,
        load_monthly=_linkedin_connections_corr_monthly,
    ),
    make_correlate_metric(
        id="linkedin_reactions",
        label="LinkedIn · reactions",
        source="linkedin",
        schema="linkedin",
        table="reactions",
        unit="reactions",
        supports_daily=True,
        supports_monthly=True,
        value_col="reactions",
        load_daily=_linkedin_reactions_daily,
        load_monthly=_linkedin_reactions_corr_monthly,
    ),
    make_correlate_metric(
        id="linkedin_shares",
        label="LinkedIn · shares",
        source="linkedin",
        schema="linkedin",
        table="shares",
        unit="shares",
        supports_daily=True,
        supports_monthly=True,
        value_col="shares",
        load_daily=_linkedin_shares_daily,
        load_monthly=_linkedin_shares_corr_monthly,
    ),
)
