"""Compare / Correlations series for manifest sources.

Grain is event counts (and, for Compare, one series per ingested slug).
Not a warehouse column scan.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import custom_queries as cq
from data_dumps.series_catalog import (
    MetricSpec,
    SeriesSpec,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30


def _monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return cq.events_monthly(
        conn, cq.FilterState(year_start=year_start, year_end=year_end)
    )


def _daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return cq.events_daily(
        conn, cq.FilterState(year_start=year_start, year_end=year_end)
    )


def _corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_monthly(conn, year_start, year_end))


def _source_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    del year_start, year_end
    return [
        {"value": source["slug"], "label": source["label"]}
        for source in cq.list_sources(conn)[:limit]
    ]


def _monthly_for_source(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str,
) -> pd.DataFrame:
    return cq.events_monthly(
        conn,
        cq.FilterState(source_slug=entity, year_start=year_start, year_end=year_end),
    )


CUSTOM_COMPARE: tuple[SeriesSpec, ...] = (
    make_compare_total(
        id="custom_events",
        label="Custom · events",
        source="custom",
        schema="custom",
        table="events",
        unit="events",
        value_col="events",
        load_monthly=_monthly,
    ),
    make_compare_entity(
        id="custom_source",
        label="Custom · source",
        source="custom",
        schema="custom",
        table="events",
        unit="events",
        value_col="events",
        load_monthly=_monthly_for_source,
        entity_options=_source_options,
    ),
)

CUSTOM_CORRELATE: tuple[MetricSpec, ...] = (
    make_correlate_metric(
        id="custom_events",
        label="Custom events",
        source="custom",
        schema="custom",
        table="events",
        unit="events",
        supports_daily=True,
        supports_monthly=True,
        value_col="events",
        load_daily=_daily,
        load_monthly=_corr_monthly,
        daily_time_col="day",
        monthly_time_col="time_key",
    ),
)
