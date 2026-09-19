"""Compare / Correlations series for duolingo.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import duolingo_queries as duoq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30

# --- Duolingo ----------------------------------------------------------------


def _duolingo_progress_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = duoq.FilterState(year_start=year_start, year_end=year_end)
    return duoq.progress_monthly(conn, f)


def _duolingo_progress_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = duoq.FilterState(year_start=year_start, year_end=year_end)
    return duoq.calendar_daily_progress(conn, f)


def _duolingo_progress_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_duolingo_progress_monthly(conn, year_start, year_end))


def _duolingo_inventory_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = duoq.FilterState(year_start=year_start, year_end=year_end)
    return duoq.inventory_monthly(conn, f)


def _duolingo_inventory_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = duoq.FilterState(year_start=year_start, year_end=year_end)
    return duoq.calendar_daily_inventory(conn, f)


def _duolingo_inventory_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_duolingo_inventory_monthly(conn, year_start, year_end))


def _duolingo_league_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = duoq.FilterState(year_start=year_start, year_end=year_end)
    return duoq.leaderboard_tier_monthly(conn, f)


def _duolingo_league_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = duoq.FilterState(year_start=year_start, year_end=year_end)
    return duoq.calendar_daily_league_tier(conn, f)


def _duolingo_league_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_duolingo_league_monthly(conn, year_start, year_end))


def _duolingo_language_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    f = duoq.FilterState(year_start=year_start, year_end=year_end)
    df = duoq.progress_by_language(conn, f).head(limit)
    return [
        {"value": str(r.language), "label": str(r.language)}
        for r in df.itertuples(index=False)
        if r.language
    ]


def _duolingo_language_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    f = duoq.FilterState(year_start=year_start, year_end=year_end)
    return duoq.progress_monthly_for_language(conn, f, entity)


DUOLINGO_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="duolingo_progress",
        label="Duolingo · progress events",
        source="duolingo",
        schema="duolingo",
        table="progress_events",
        unit="events",
        value_col="events",
        load_monthly=_duolingo_progress_monthly,
    ),
    make_compare_total(
        id="duolingo_inventory",
        label="Duolingo · inventory buys",
        source="duolingo",
        schema="duolingo",
        table="inventory",
        unit="buys",
        value_col="buys",
        load_monthly=_duolingo_inventory_monthly,
    ),
    make_compare_total(
        id="duolingo_league_tier",
        label="Duolingo · league max tier",
        source="duolingo",
        schema="duolingo",
        table="leaderboards",
        unit="tier",
        value_col="max_tier",
        load_monthly=_duolingo_league_monthly,
    ),
    make_compare_entity(
        id="duolingo_language",
        label="Duolingo · language",
        source="duolingo",
        schema="duolingo",
        table="progress_events",
        unit="events",
        value_col="events",
        load_monthly=_duolingo_language_monthly,
        entity_options=_duolingo_language_options,
    ),
)

DUOLINGO_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="duolingo_progress",
        label="Duolingo · progress events",
        source="duolingo",
        schema="duolingo",
        table="progress_events",
        unit="events",
        supports_daily=True,
        supports_monthly=True,
        value_col="events",
        load_daily=_duolingo_progress_daily,
        load_monthly=_duolingo_progress_corr_monthly,
    ),
    make_correlate_metric(
        id="duolingo_inventory",
        label="Duolingo · inventory buys",
        source="duolingo",
        schema="duolingo",
        table="inventory",
        unit="buys",
        supports_daily=True,
        supports_monthly=True,
        value_col="buys",
        load_daily=_duolingo_inventory_daily,
        load_monthly=_duolingo_inventory_corr_monthly,
    ),
    make_correlate_metric(
        id="duolingo_league_tier",
        label="Duolingo · league max tier",
        source="duolingo",
        schema="duolingo",
        table="leaderboards",
        unit="tier",
        supports_daily=True,
        supports_monthly=True,
        value_col="max_tier",
        load_daily=_duolingo_league_daily,
        load_monthly=_duolingo_league_corr_monthly,
    ),
)
