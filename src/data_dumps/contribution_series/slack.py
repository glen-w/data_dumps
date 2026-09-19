"""Compare / Correlations series for slack.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import slack_queries as skq
from data_dumps.series_catalog import (
    Grain,
    MetricSpec,
    SeriesSpec,
    empty_compare,
    empty_correlate,
    entity_label,
    make_compare_total,
    make_correlate_metric,
    pack_compare,
    pack_correlate,
    ym_from_year_month,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30

# --- Slack -------------------------------------------------------------------


def _slack_sum_monthly(
    conn: duckdb.DuckDBPyConnection, f: skq.FilterState
) -> pd.DataFrame:
    raw = skq.monthly_messages_by_kind(conn, f)
    if raw.empty:
        return pd.DataFrame(columns=["year_month", "messages"])
    summed = raw.groupby("year_month", as_index=False)["messages"].sum()
    return pd.DataFrame(summed).sort_values("year_month")


def _slack_messages_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    f = skq.FilterState(year_start=year_start, year_end=year_end)
    df = _slack_sum_monthly(conn, f)
    return pack_compare(
        df,
        value_col="messages",
        series_id="slack_messages",
        series_label="Slack · messages",
        unit="messages",
    )


def _slack_channel_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    del year_start, year_end
    bounds = skq.data_bounds(conn)
    channels = sorted(
        bounds.get("channels") or [],
        key=lambda c: (-int(c.get("messages") or 0), c.get("name") or ""),
    )[:limit]
    return [
        {
            "value": str(c["channel_id"]),
            "label": f"#{c.get('name') or c['channel_id']}",
        }
        for c in channels
    ]


def _slack_person_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    del year_start, year_end
    bounds = skq.data_bounds(conn)
    people = sorted(
        bounds.get("people") or [],
        key=lambda p: (-int(p.get("messages") or 0), p.get("name") or ""),
    )[:limit]
    return [
        {
            "value": str(p["user_id"]),
            "label": str(p.get("name") or p["user_id"]),
        }
        for p in people
    ]


def _slack_channel_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    if not entity:
        return empty_compare()
    f = skq.FilterState(year_start=year_start, year_end=year_end, channel_ids=[entity])
    df = _slack_sum_monthly(conn, f)
    label_entity = entity
    for opt in _slack_channel_options(conn, year_start=year_start, year_end=year_end):
        if opt["value"] == entity:
            label_entity = opt["label"]
            break
    return pack_compare(
        df,
        value_col="messages",
        series_id="slack_channel",
        series_label=entity_label("Slack · channel", label_entity),
        unit="messages",
    )


def _slack_person_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    if not entity:
        return empty_compare()
    f = skq.FilterState(year_start=year_start, year_end=year_end, user_ids=[entity])
    df = _slack_sum_monthly(conn, f)
    label_entity = entity
    for opt in _slack_person_options(conn, year_start=year_start, year_end=year_end):
        if opt["value"] == entity:
            label_entity = opt["label"]
            break
    return pack_compare(
        df,
        value_col="messages",
        series_id="slack_person",
        series_label=entity_label("Slack · person", label_entity),
        unit="messages",
    )


def _slack_messages_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    f = skq.FilterState(year_start=year_start, year_end=year_end)
    mid, label, unit = "slack_messages", "Slack · messages", "messages"
    if grain == "daily":
        return pack_correlate(
            skq.calendar_daily(conn, f),
            time_col="day",
            value_col="messages",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )
    raw = skq.monthly_messages_by_kind(conn, f)
    if raw.empty:
        return empty_correlate()
    df = pd.DataFrame(raw.groupby("year_month", as_index=False)["messages"].sum())
    df = ym_string_to_ts(df)
    return pack_correlate(
        df,
        time_col="time_key",
        value_col="messages",
        metric_id=mid,
        metric_label=label,
        unit=unit,
        grain=grain,
    )


def _slack_active_people_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = skq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_year_month(skq.active_people_monthly(conn, f))


def _slack_active_people_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_slack_active_people_monthly(conn, year_start, year_end))


SLACK_COMPARE: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "slack_messages",
        "Slack · messages",
        "slack",
        "total",
        "messages",
        False,
        "slack",
        "messages",
        _slack_messages_compare,
    ),
    make_compare_total(
        id="slack_active_people",
        label="Slack · active people",
        source="slack",
        schema="slack",
        table="messages",
        unit="people",
        value_col="people",
        load_monthly=_slack_active_people_monthly,
    ),
    SeriesSpec(
        "slack_channel",
        "Slack · channel",
        "slack",
        "entity",
        "messages",
        True,
        "slack",
        "messages",
        _slack_channel_compare,
        _slack_channel_options,
    ),
    SeriesSpec(
        "slack_person",
        "Slack · person",
        "slack",
        "entity",
        "messages",
        True,
        "slack",
        "messages",
        _slack_person_compare,
        _slack_person_options,
    ),
)

SLACK_CORRELATE: tuple[MetricSpec, ...] = (
    MetricSpec(
        "slack_messages",
        "Slack · messages",
        "slack",
        "messages",
        "slack",
        "messages",
        True,
        True,
        _slack_messages_correlate,
    ),
    make_correlate_metric(
        id="slack_active_people",
        label="Slack · active people",
        source="slack",
        schema="slack",
        table="messages",
        unit="people",
        supports_daily=False,
        supports_monthly=True,
        value_col="people",
        load_monthly=_slack_active_people_corr_monthly,
    ),
)
