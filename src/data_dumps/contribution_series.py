"""Per-source Compare / Correlations series descriptors (callable fetch).

Assembled into catalogs via :mod:`data_dumps.contributions`. Keep grain and
aggregation choices here — do not auto-discover warehouse columns.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps import amazon_queries as amzq
from data_dumps import browser_queries as brq
from data_dumps import linkedin_queries as liq
from data_dumps import miband_queries as mbq
from data_dumps import ring_queries as ringq
from data_dumps import slack_queries as skq
from data_dumps import sleep_queries as slq
from data_dumps import spotify_queries as spq
from data_dumps import telegram_queries as tgq
from data_dumps import thunderbird_queries as tbq
from data_dumps import twitter_queries as twq
from data_dumps.series_catalog import (
    Grain,
    MetricSpec,
    SeriesSpec,
    empty_compare,
    empty_correlate,
    entity_label,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    monthly_from_daily,
    pack_compare,
    pack_correlate,
    ym_from_date_col,
    ym_from_year_month,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30


# --- Spotify -----------------------------------------------------------------


def _spotify_hours_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = spq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_year_month(spq.monthly_hours(conn, f))


def _spotify_hours_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = spq.FilterState(year_start=year_start, year_end=year_end)
    return spq.calendar_daily(conn, f)


def _spotify_hours_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    df = _spotify_hours_monthly(conn, year_start, year_end)
    return ym_string_to_ts(df)


def _spotify_artist_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    f = spq.FilterState(year_start=year_start, year_end=year_end)
    df = spq.top_artists(conn, f, limit=limit)
    return [
        {"value": str(r.artist_name), "label": str(r.artist_name)}
        for r in df.itertuples(index=False)
        if r.artist_name
    ]


def _spotify_artist_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    f = spq.FilterState(year_start=year_start, year_end=year_end, artist_name=entity)
    return ym_from_year_month(spq.monthly_hours(conn, f))


def _spotify_late_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    clauses = ["hour(played_at_local) >= 22", "played_at_local IS NOT NULL"]
    params: list[Any] = []
    if year_start is not None:
        clauses.append("year >= ?")
        params.append(year_start)
    if year_end is not None:
        clauses.append("year <= ?")
        params.append(year_end)
    where = " AND ".join(clauses)
    return conn.execute(
        f"""
        SELECT
            played_at_local::DATE AS day,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    ).df()


def _spotify_late_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    if grain != "daily":
        return empty_correlate()
    df = _spotify_late_daily(conn, year_start, year_end)
    return pack_correlate(
        df,
        time_col="day",
        value_col="hours",
        metric_id="spotify_late_hours",
        metric_label="Spotify · late hours (≥22)",
        unit="hours",
        grain="daily",
    )


SPOTIFY_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="spotify_hours",
        label="Spotify · listening hours",
        source="spotify",
        schema="spotify",
        table="plays",
        unit="hours",
        value_col="hours",
        load_monthly=_spotify_hours_monthly,
    ),
    make_compare_entity(
        id="spotify_artist",
        label="Spotify · artist",
        source="spotify",
        schema="spotify",
        table="plays",
        unit="hours",
        value_col="hours",
        load_monthly=_spotify_artist_monthly,
        entity_options=_spotify_artist_options,
    ),
)

SPOTIFY_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="spotify_hours",
        label="Spotify · hours",
        source="spotify",
        schema="spotify",
        table="plays",
        unit="hours",
        supports_daily=True,
        supports_monthly=True,
        value_col="hours",
        load_daily=_spotify_hours_daily,
        load_monthly=_spotify_hours_corr_monthly,
    ),
    MetricSpec(
        "spotify_late_hours",
        "Spotify · late hours (≥22)",
        "spotify",
        "hours",
        "spotify",
        "plays",
        True,
        False,
        _spotify_late_correlate,
    ),
)


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
)


# --- Twitter -----------------------------------------------------------------


def _twitter_tweets_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    f = twq.FilterState(year_start=year_start, year_end=year_end)
    df = ym_from_year_month(twq.monthly_volume(conn, f))
    return pack_compare(
        df,
        value_col="tweets",
        series_id="twitter_tweets",
        series_label="Twitter · tweets",
        unit="tweets",
    )


def _twitter_account_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    f = twq.FilterState(year_start=year_start, year_end=year_end)
    df = twq.top_mentions(conn, f, limit=limit)
    return [
        {"value": str(r.account), "label": f"@{r.account!s}"}
        for r in df.itertuples(index=False)
        if r.account
    ]


def _twitter_account_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    if not entity:
        return empty_compare()
    f = twq.FilterState(year_start=year_start, year_end=year_end, account_name=entity)
    df = ym_from_year_month(twq.monthly_volume(conn, f))
    return pack_compare(
        df,
        value_col="tweets",
        series_id="twitter_account",
        series_label=entity_label("Twitter · account", f"@{entity.lstrip('@')}"),
        unit="tweets",
    )


def _twitter_tweets_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    f = twq.FilterState(year_start=year_start, year_end=year_end)
    mid, label, unit = "twitter_tweets", "Twitter · tweets", "tweets"
    if grain == "daily":
        return pack_correlate(
            twq.calendar_daily(conn, f),
            time_col="day",
            value_col="tweets",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )
    df = ym_string_to_ts(twq.monthly_volume(conn, f))
    return pack_correlate(
        df,
        time_col="time_key",
        value_col="tweets",
        metric_id=mid,
        metric_label=label,
        unit=unit,
        grain=grain,
    )


TWITTER_COMPARE: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "twitter_tweets",
        "Twitter · tweets",
        "twitter",
        "total",
        "tweets",
        False,
        "twitter",
        "tweets",
        _twitter_tweets_compare,
    ),
    SeriesSpec(
        "twitter_account",
        "Twitter · account",
        "twitter",
        "entity",
        "tweets",
        True,
        "twitter",
        "tweets",
        _twitter_account_compare,
        _twitter_account_options,
    ),
)

TWITTER_CORRELATE: tuple[MetricSpec, ...] = (
    MetricSpec(
        "twitter_tweets",
        "Twitter · tweets",
        "twitter",
        "tweets",
        "twitter",
        "tweets",
        True,
        True,
        _twitter_tweets_correlate,
    ),
)


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
)


# --- Thunderbird -------------------------------------------------------------


def _thunderbird_sum_monthly(
    conn: duckdb.DuckDBPyConnection, f: tbq.FilterState
) -> pd.DataFrame:
    raw = ym_from_year_month(tbq.monthly_volume(conn, f))
    if raw.empty:
        return pd.DataFrame(columns=["year_month", "messages"])
    summed = raw.groupby("year_month", as_index=False)["messages"].sum()
    return pd.DataFrame(summed).sort_values("year_month")


def _thunderbird_messages_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    f = tbq.FilterState(year_start=year_start, year_end=year_end)
    df = _thunderbird_sum_monthly(conn, f)
    return pack_compare(
        df,
        value_col="messages",
        series_id="thunderbird_messages",
        series_label="Thunderbird · messages",
        unit="messages",
    )


def _thunderbird_contact_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    f = tbq.FilterState(year_start=year_start, year_end=year_end)
    df = tbq.top_senders(conn, f, limit=limit)
    return [
        {"value": str(r.contact), "label": str(r.contact)}
        for r in df.itertuples(index=False)
        if r.contact
    ]


def _thunderbird_contact_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    if not entity:
        return empty_compare()
    f = tbq.FilterState(year_start=year_start, year_end=year_end, contact_exact=entity)
    df = _thunderbird_sum_monthly(conn, f)
    return pack_compare(
        df,
        value_col="messages",
        series_id="thunderbird_contact",
        series_label=entity_label("Thunderbird · contact", entity),
        unit="messages",
    )


def _thunderbird_messages_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    f = tbq.FilterState(year_start=year_start, year_end=year_end)
    mid, label, unit = "thunderbird_messages", "Thunderbird · messages", "messages"
    if grain == "daily":
        return pack_correlate(
            tbq.calendar_daily(conn, f),
            time_col="day",
            value_col="messages",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )
    raw = tbq.monthly_volume(conn, f)
    if raw.empty:
        return empty_correlate()
    if "year_month" not in raw.columns and {"year", "month"} <= set(raw.columns):
        raw = raw.copy()
        raw["year_month"] = (
            raw["year"].astype(str) + "-" + raw["month"].astype(str).str.zfill(2)
        )
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


THUNDERBIRD_COMPARE: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "thunderbird_messages",
        "Thunderbird · messages",
        "thunderbird",
        "total",
        "messages",
        False,
        "thunderbird",
        "messages",
        _thunderbird_messages_compare,
    ),
    SeriesSpec(
        "thunderbird_contact",
        "Thunderbird · contact",
        "thunderbird",
        "entity",
        "messages",
        True,
        "thunderbird",
        "messages",
        _thunderbird_contact_compare,
        _thunderbird_contact_options,
    ),
)

THUNDERBIRD_CORRELATE: tuple[MetricSpec, ...] = (
    MetricSpec(
        "thunderbird_messages",
        "Thunderbird · messages",
        "thunderbird",
        "messages",
        "thunderbird",
        "messages",
        True,
        True,
        _thunderbird_messages_correlate,
    ),
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


# --- Amazon ------------------------------------------------------------------


def _amazon_orders_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(amzq.monthly_orders(conn, f), "month_start")


def _amazon_orders_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.order_calendar(conn, f)


def _amazon_orders_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.monthly_orders(conn, f).rename(columns={"month_start": "time_key"})


def _amazon_alexa_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(amzq.alexa_monthly(conn, f), "month_start")


def _amazon_alexa_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.alexa_monthly(conn, f).rename(columns={"month_start": "time_key"})


def _amazon_kindle_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(amzq.kindle_monthly(conn, f), "month_start")


def _amazon_kindle_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.kindle_monthly(conn, f).rename(columns={"month_start": "time_key"})


AMAZON_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="amazon_orders",
        label="Amazon · orders",
        source="amazon",
        schema="amazon",
        table="order_items",
        unit="orders",
        value_col="orders",
        load_monthly=_amazon_orders_monthly,
    ),
    make_compare_total(
        id="amazon_alexa",
        label="Amazon · Alexa utterances",
        source="amazon",
        schema="amazon",
        table="alexa_intents",
        unit="utterances",
        value_col="utterances",
        load_monthly=_amazon_alexa_monthly,
    ),
    make_compare_total(
        id="amazon_kindle",
        label="Amazon · Kindle sessions",
        source="amazon",
        schema="amazon",
        table="kindle_sessions",
        unit="sessions",
        value_col="sessions",
        load_monthly=_amazon_kindle_monthly,
    ),
)

AMAZON_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="amazon_orders",
        label="Amazon · orders",
        source="amazon",
        schema="amazon",
        table="order_items",
        unit="orders",
        supports_daily=True,
        supports_monthly=True,
        value_col="orders",
        load_daily=_amazon_orders_daily,
        load_monthly=_amazon_orders_corr_monthly,
    ),
    make_correlate_metric(
        id="amazon_alexa",
        label="Amazon · Alexa utterances",
        source="amazon",
        schema="amazon",
        table="alexa_intents",
        unit="utterances",
        supports_daily=False,
        supports_monthly=True,
        value_col="utterances",
        load_monthly=_amazon_alexa_corr_monthly,
    ),
    make_correlate_metric(
        id="amazon_kindle",
        label="Amazon · Kindle sessions",
        source="amazon",
        schema="amazon",
        table="kindle_sessions",
        unit="sessions",
        supports_daily=False,
        supports_monthly=True,
        value_col="sessions",
        load_monthly=_amazon_kindle_corr_monthly,
    ),
)


# --- Mi Band (frozen — no new metrics beyond shipped) ------------------------


def _miband_bpm_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    f = mbq.FilterState(year_start=year_start, year_end=year_end)
    df = ym_from_year_month(mbq.monthly_avg(conn, f))
    return pack_compare(
        df,
        value_col="avg_bpm",
        series_id="miband_bpm",
        series_label="Mi Band · avg BPM",
        unit="bpm",
    )


def _miband_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
    *,
    mid: str,
    label: str,
    unit: str,
    value_col: str,
) -> pd.DataFrame:
    f = mbq.FilterState(year_start=year_start, year_end=year_end)
    if grain == "daily":
        return pack_correlate(
            mbq.calendar_daily(conn, f),
            time_col="day",
            value_col=value_col,
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )
    df = ym_string_to_ts(mbq.monthly_avg(conn, f))
    return pack_correlate(
        df,
        time_col="time_key",
        value_col=value_col,
        metric_id=mid,
        metric_label=label,
        unit=unit,
        grain=grain,
    )


def _miband_readings_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    return _miband_correlate(
        conn,
        year_start,
        year_end,
        grain,
        mid="miband_readings",
        label="Mi Band · readings",
        unit="readings",
        value_col="readings",
    )


def _miband_bpm_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    return _miband_correlate(
        conn,
        year_start,
        year_end,
        grain,
        mid="miband_bpm",
        label="Mi Band · avg BPM",
        unit="bpm",
        value_col="avg_bpm",
    )


MIBAND_COMPARE: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "miband_bpm",
        "Mi Band · avg BPM",
        "miband",
        "total",
        "bpm",
        False,
        "miband",
        "heart_rate",
        _miband_bpm_compare,
    ),
)

MIBAND_CORRELATE: tuple[MetricSpec, ...] = (
    MetricSpec(
        "miband_readings",
        "Mi Band · readings",
        "miband",
        "readings",
        "miband",
        "heart_rate",
        True,
        True,
        _miband_readings_correlate,
    ),
    MetricSpec(
        "miband_bpm",
        "Mi Band · avg BPM",
        "miband",
        "bpm",
        "miband",
        "heart_rate",
        True,
        True,
        _miband_bpm_correlate,
    ),
)


# --- Browser (last-seen grain — not visit volume) ----------------------------


def _browser_urls_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    f = brq.FilterState(year_start=year_start, year_end=year_end)
    df = ym_from_date_col(brq.monthly_last_visits(conn, f), "month")
    return pack_compare(
        df,
        value_col="urls_last_seen",
        series_id="browser_urls_last_seen",
        series_label="Browser · URLs last seen",
        unit="urls",
    )


def _browser_urls_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    f = brq.FilterState(year_start=year_start, year_end=year_end)
    mid = "browser_urls_last_seen"
    label = "Browser · URLs last seen"
    unit = "urls"
    if grain == "daily":
        return pack_correlate(
            brq.calendar_last_seen(conn, f),
            time_col="day",
            value_col="urls",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )
    df = brq.monthly_last_visits(conn, f).rename(columns={"month": "time_key"})
    return pack_correlate(
        df,
        time_col="time_key",
        value_col="urls_last_seen",
        metric_id=mid,
        metric_label=label,
        unit=unit,
        grain=grain,
    )


def _browser_search_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = brq.FilterState(year_start=year_start, year_end=year_end)
    raw = brq.monthly_search_volume(conn, f)
    if raw.empty:
        return pd.DataFrame(columns=["year_month", "urls"])
    df = ym_from_date_col(raw, "month")
    return pd.DataFrame(df.groupby("year_month", as_index=False)["urls"].sum())


def _browser_search_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_browser_search_monthly(conn, year_start, year_end))


BROWSER_COMPARE: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "browser_urls_last_seen",
        "Browser · URLs last seen",
        "browser",
        "total",
        "urls",
        False,
        "browser",
        "pages",
        _browser_urls_compare,
    ),
    make_compare_total(
        id="browser_search_urls",
        label="Browser · search URLs",
        source="browser",
        schema="browser",
        table="pages",
        unit="urls",
        value_col="urls",
        load_monthly=_browser_search_monthly,
    ),
)

BROWSER_CORRELATE: tuple[MetricSpec, ...] = (
    MetricSpec(
        "browser_urls_last_seen",
        "Browser · URLs last seen",
        "browser",
        "urls",
        "browser",
        "pages",
        True,
        True,
        _browser_urls_correlate,
    ),
    make_correlate_metric(
        id="browser_search_urls",
        label="Browser · search URLs",
        source="browser",
        schema="browser",
        table="pages",
        unit="urls",
        supports_daily=False,
        supports_monthly=True,
        value_col="urls",
        load_monthly=_browser_search_corr_monthly,
    ),
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
