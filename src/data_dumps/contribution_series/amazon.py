"""Compare / Correlations series for amazon.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import amazon_queries as amzq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_total,
    make_correlate_metric,
    ym_from_date_col,
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


def _amazon_searches_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(amzq.searches_monthly(conn, f), "month_start")


def _amazon_searches_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.searches_calendar(conn, f)


def _amazon_searches_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.searches_monthly(conn, f).rename(columns={"month_start": "time_key"})


def _amazon_audible_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(amzq.audible_monthly(conn, f), "month_start")


def _amazon_audible_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.audible_calendar(conn, f)


def _amazon_audible_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.audible_monthly(conn, f).rename(columns={"month_start": "time_key"})


def _amazon_video_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(amzq.video_monthly(conn, f), "month_start")


def _amazon_video_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.video_calendar(conn, f)


def _amazon_video_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.video_monthly(conn, f).rename(columns={"month_start": "time_key"})


def _amazon_music_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return ym_from_date_col(amzq.music_plays_monthly(conn, f), "month_start")


def _amazon_music_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.music_plays_calendar(conn, f)


def _amazon_music_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = amzq.FilterState(year_start=year_start, year_end=year_end)
    return amzq.music_plays_monthly(conn, f).rename(columns={"month_start": "time_key"})


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
        id="amazon_searches",
        label="Amazon · searches",
        source="amazon",
        schema="amazon",
        table="searches",
        unit="searches",
        value_col="searches",
        load_monthly=_amazon_searches_monthly,
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
    make_compare_total(
        id="amazon_audible",
        label="Amazon · Audible hours",
        source="amazon",
        schema="amazon",
        table="audible_listens",
        unit="hours",
        value_col="hours",
        load_monthly=_amazon_audible_monthly,
    ),
    make_compare_total(
        id="amazon_video",
        label="Amazon · Video sessions",
        source="amazon",
        schema="amazon",
        table="video_views",
        unit="sessions",
        value_col="sessions",
        load_monthly=_amazon_video_monthly,
    ),
    make_compare_total(
        id="amazon_music",
        label="Amazon · Music plays",
        source="amazon",
        schema="amazon",
        table="music_plays",
        unit="plays",
        value_col="plays",
        load_monthly=_amazon_music_monthly,
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
        id="amazon_searches",
        label="Amazon · searches",
        source="amazon",
        schema="amazon",
        table="searches",
        unit="searches",
        supports_daily=True,
        supports_monthly=True,
        value_col="searches",
        load_daily=_amazon_searches_daily,
        load_monthly=_amazon_searches_corr_monthly,
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
    make_correlate_metric(
        id="amazon_audible",
        label="Amazon · Audible hours",
        source="amazon",
        schema="amazon",
        table="audible_listens",
        unit="hours",
        supports_daily=True,
        supports_monthly=True,
        value_col="hours",
        load_daily=_amazon_audible_daily,
        load_monthly=_amazon_audible_corr_monthly,
    ),
    make_correlate_metric(
        id="amazon_video",
        label="Amazon · Video sessions",
        source="amazon",
        schema="amazon",
        table="video_views",
        unit="sessions",
        supports_daily=True,
        supports_monthly=True,
        value_col="sessions",
        load_daily=_amazon_video_daily,
        load_monthly=_amazon_video_corr_monthly,
    ),
    make_correlate_metric(
        id="amazon_music",
        label="Amazon · Music plays",
        source="amazon",
        schema="amazon",
        table="music_plays",
        unit="plays",
        supports_daily=True,
        supports_monthly=True,
        value_col="plays",
        load_daily=_amazon_music_daily,
        load_monthly=_amazon_music_corr_monthly,
    ),
)
