"""Compare / Correlations series for browser.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import browser_queries as brq
from data_dumps.series_catalog import (
    Grain,
    MetricSpec,
    SeriesSpec,
    make_compare_total,
    make_correlate_metric,
    pack_compare,
    pack_correlate,
    ym_from_date_col,
    ym_string_to_ts,
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
