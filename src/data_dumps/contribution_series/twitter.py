"""Compare / Correlations series for twitter.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import twitter_queries as twq
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


def _twitter_dms_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = twq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_year_month(twq.dm_volume(conn, f))


def _twitter_dms_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = twq.FilterState(year_start=year_start, year_end=year_end)
    return twq.calendar_daily_dms(conn, f)


def _twitter_dms_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_twitter_dms_monthly(conn, year_start, year_end))


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
    make_compare_total(
        id="twitter_dms",
        label="Twitter · DMs",
        source="twitter",
        schema="twitter",
        table="dm_messages",
        unit="messages",
        value_col="messages",
        load_monthly=_twitter_dms_monthly,
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
    make_correlate_metric(
        id="twitter_dms",
        label="Twitter · DMs",
        source="twitter",
        schema="twitter",
        table="dm_messages",
        unit="messages",
        supports_daily=True,
        supports_monthly=True,
        value_col="messages",
        load_daily=_twitter_dms_daily,
        load_monthly=_twitter_dms_corr_monthly,
    ),
)
