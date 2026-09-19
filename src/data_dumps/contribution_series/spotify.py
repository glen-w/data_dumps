"""Compare / Correlations series for spotify.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import spotify_queries as spq
from data_dumps.series_catalog import (
    Grain,
    MetricSpec,
    SeriesSpec,
    empty_correlate,
    make_compare_entity,
    make_compare_total,
    make_correlate_metric,
    pack_correlate,
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
    return spq.late_hours_daily(conn, year_start, year_end)


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


def _spotify_searches_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return spq.search_volume_filtered(conn, year_start=year_start, year_end=year_end)


def _spotify_searches_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return spq.calendar_daily_searches(conn, year_start=year_start, year_end=year_end)


def _spotify_searches_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_spotify_searches_monthly(conn, year_start, year_end))


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
    make_compare_total(
        id="spotify_searches",
        label="Spotify · searches",
        source="spotify",
        schema="spotify",
        table="searches",
        unit="searches",
        value_col="searches",
        load_monthly=_spotify_searches_monthly,
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
    make_correlate_metric(
        id="spotify_searches",
        label="Spotify · searches",
        source="spotify",
        schema="spotify",
        table="searches",
        unit="searches",
        supports_daily=True,
        supports_monthly=True,
        value_col="searches",
        load_daily=_spotify_searches_daily,
        load_monthly=_spotify_searches_corr_monthly,
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
