"""Compare / Correlations series for miband.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import miband_queries as mbq
from data_dumps.series_catalog import (
    Grain,
    MetricSpec,
    SeriesSpec,
    pack_compare,
    pack_correlate,
    ym_from_year_month,
    ym_string_to_ts,
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
