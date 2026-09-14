"""Shared Compare / Correlations series types and pack helpers.

Callable-bearing specs replace id-dispatch fetch ladders. Catalogs are assembled
from :mod:`data_dumps.contributions` (thin explicit registry).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import duckdb
import pandas as pd

from data_dumps import query_util

Grain = Literal["daily", "monthly"]

COMPARE_OUT_COLS = ["year_month", "series_id", "series_label", "value", "unit"]
CORRELATE_LONG_COLS = [
    "time_key",
    "metric_id",
    "metric_label",
    "value",
    "unit",
    "grain",
]

CompareFetchFn = Callable[
    [duckdb.DuckDBPyConnection, int | None, int | None, str | None],
    pd.DataFrame,
]
EntityOptionsFn = Callable[..., list[dict[str, str]]]
CorrelateFetchFn = Callable[
    [duckdb.DuckDBPyConnection, int | None, int | None, Grain],
    pd.DataFrame,
]


@dataclass(frozen=True)
class SeriesSpec:
    id: str
    label: str
    source: str
    kind: str  # "total" | "entity"
    unit: str
    requires_entity: bool
    schema: str
    table: str
    fetch: CompareFetchFn
    entity_options: EntityOptionsFn | None = None

    def available(self, conn: duckdb.DuckDBPyConnection) -> bool:
        return query_util.has_table(conn, self.schema, self.table)


@dataclass(frozen=True)
class SeriesSelection:
    series_id: str
    entity: str | None = None


@dataclass(frozen=True)
class MetricSpec:
    id: str
    label: str
    source: str
    unit: str
    schema: str
    table: str
    supports_daily: bool
    supports_monthly: bool
    fetch: CorrelateFetchFn

    def available(self, conn: duckdb.DuckDBPyConnection) -> bool:
        return query_util.has_table(conn, self.schema, self.table)


def ym_from_year_month(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "year_month" not in out.columns and {"year", "month"} <= set(out.columns):
        out["year_month"] = (
            out["year"].astype(str) + "-" + out["month"].astype(str).str.zfill(2)
        )
    return out


def ym_from_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    dt = pd.to_datetime(out[col], errors="coerce")
    out["year_month"] = dt.dt.strftime("%Y-%m")
    return out.dropna(subset=["year_month"])


def pack_compare(
    df: pd.DataFrame,
    *,
    value_col: str,
    series_id: str,
    series_label: str,
    unit: str,
) -> pd.DataFrame:
    if df.empty or value_col not in df.columns or "year_month" not in df.columns:
        return pd.DataFrame(columns=COMPARE_OUT_COLS)
    out = df[["year_month", value_col]].copy()
    out = out.rename(columns={value_col: "value"})
    out["value"] = pd.to_numeric(out["value"], errors="coerce").fillna(0.0)
    out["series_id"] = series_id
    out["series_label"] = series_label
    out["unit"] = unit
    return out[COMPARE_OUT_COLS].sort_values("year_month").reset_index(drop=True)


def entity_label(spec_label: str, entity: str) -> str:
    return f"{spec_label}: {entity}"


def ym_string_to_ts(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "year_month" not in df.columns:
        return df
    out = df.copy()
    out["time_key"] = pd.to_datetime(out["year_month"] + "-01", errors="coerce")
    return out


def pack_correlate(
    df: pd.DataFrame,
    *,
    time_col: str,
    value_col: str,
    metric_id: str,
    metric_label: str,
    unit: str,
    grain: Grain,
) -> pd.DataFrame:
    if df.empty or value_col not in df.columns or time_col not in df.columns:
        return pd.DataFrame(columns=CORRELATE_LONG_COLS)
    out = df[[time_col, value_col]].copy()
    out = out.rename(columns={time_col: "time_key", value_col: "value"})
    out["time_key"] = pd.to_datetime(out["time_key"], errors="coerce")
    if grain == "monthly":
        out["time_key"] = out["time_key"].dt.to_period("M").dt.to_timestamp()
    else:
        out["time_key"] = out["time_key"].dt.normalize()
    out = out.dropna(subset=["time_key"])
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["value"])
    out["metric_id"] = metric_id
    out["metric_label"] = metric_label
    out["unit"] = unit
    out["grain"] = grain
    return out[CORRELATE_LONG_COLS].sort_values("time_key").reset_index(drop=True)


def empty_compare() -> pd.DataFrame:
    return pd.DataFrame(columns=COMPARE_OUT_COLS)


def empty_correlate() -> pd.DataFrame:
    return pd.DataFrame(columns=CORRELATE_LONG_COLS)
