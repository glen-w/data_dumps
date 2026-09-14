"""Cross-source monthly series for the Compare explorer tab.

Catalogs come from :mod:`data_dumps.contributions` (callable SeriesSpec fetch).
Values are normalized as % of that series' max.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps.contributions import COMPARE_SERIES, bounds_fns_for_series
from data_dumps.series_catalog import (
    COMPARE_OUT_COLS,
    SeriesSelection,
    SeriesSpec,
)

# Back-compat aliases used by panels / tests.
OUT_COLS = COMPARE_OUT_COLS
MAX_SERIES = 6
ENTITY_OPTION_LIMIT = 30

SERIES: tuple[SeriesSpec, ...] = COMPARE_SERIES
_SERIES_BY_ID: dict[str, SeriesSpec] = {s.id: s for s in SERIES}


def list_available_series(conn: duckdb.DuckDBPyConnection) -> list[SeriesSpec]:
    return [s for s in SERIES if s.available(conn)]


def series_by_id(series_id: str) -> SeriesSpec | None:
    return _SERIES_BY_ID.get(series_id)


def compare_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Union year / day span across available Compare sources."""
    available_sources = {s.source for s in list_available_series(conn)}
    min_years: list[int] = []
    max_years: list[int] = []
    first_days: list[Any] = []
    last_days: list[Any] = []
    for source, fn in bounds_fns_for_series():
        if source not in available_sources:
            continue
        try:
            b = fn(conn)
        except Exception:
            continue
        if b.get("min_year") is not None:
            min_years.append(int(b["min_year"]))
        if b.get("max_year") is not None:
            max_years.append(int(b["max_year"]))
        if b.get("first_day") is not None:
            first_days.append(b["first_day"])
        if b.get("last_day") is not None:
            last_days.append(b["last_day"])
    if not min_years or not max_years:
        return {
            "min_year": 2020,
            "max_year": 2025,
            "first_day": None,
            "last_day": None,
            "n_series": 0,
        }
    return {
        "min_year": min(min_years),
        "max_year": max(max_years),
        "first_day": min(first_days) if first_days else None,
        "last_day": max(last_days) if last_days else None,
        "n_series": len(list_available_series(conn)),
    }


def entity_options(
    conn: duckdb.DuckDBPyConnection,
    series_id: str,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    """Top entities for a series picker: ``[{value, label}, ...]``."""
    spec = _SERIES_BY_ID.get(series_id)
    if spec is None or not spec.requires_entity or not spec.available(conn):
        return []
    if spec.entity_options is None:
        return []
    return spec.entity_options(
        conn, year_start=year_start, year_end=year_end, limit=limit
    )


def fetch_monthly(
    conn: duckdb.DuckDBPyConnection,
    selections: list[SeriesSelection] | list[dict[str, Any]],
    *,
    year_start: int | None = None,
    year_end: int | None = None,
) -> pd.DataFrame:
    """Fetch monthly rows for up to ``MAX_SERIES`` selections.

    Each selection is a ``SeriesSelection`` or ``{series_id, entity?}``.
    Empty / unavailable / entity-missing series are skipped.
    """
    parsed: list[SeriesSelection] = []
    for sel in selections:
        if isinstance(sel, SeriesSelection):
            parsed.append(sel)
        else:
            parsed.append(
                SeriesSelection(
                    series_id=str(sel["series_id"]),
                    entity=sel.get("entity"),
                )
            )
    parsed = parsed[:MAX_SERIES]

    frames: list[pd.DataFrame] = []
    for sel in parsed:
        spec = _SERIES_BY_ID.get(sel.series_id)
        if spec is None or not spec.available(conn):
            continue
        if spec.requires_entity and not (sel.entity and str(sel.entity).strip()):
            continue
        frame = spec.fetch(
            conn,
            year_start,
            year_end,
            sel.entity.strip() if sel.entity else None,
        )
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=OUT_COLS)
    return pd.concat(frames, ignore_index=True)


def normalize_pct_of_max(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``pct_of_max`` (0–100) per ``series_label``.

    When a series max is 0, all its ``pct_of_max`` values are 0.
    Empty input returns an empty frame that still has ``pct_of_max``.
    """
    if df.empty:
        out = (
            df.copy()
            if isinstance(df, pd.DataFrame)
            else pd.DataFrame(columns=OUT_COLS)
        )
        if "pct_of_max" not in out.columns:
            out["pct_of_max"] = pd.Series(dtype=float)
        return out

    out = df.copy()
    out["value"] = pd.to_numeric(out["value"], errors="coerce").fillna(0.0)
    maxima = out.groupby("series_label")["value"].transform("max")
    out["pct_of_max"] = 0.0
    nonzero = maxima > 0
    out.loc[nonzero, "pct_of_max"] = out.loc[nonzero, "value"] / maxima[nonzero] * 100.0
    return out.reset_index(drop=True)


MIN_CORR_OVERLAP = 3


def correlation_matrix(
    df: pd.DataFrame,
    *,
    value_col: str = "pct_of_max",
    min_overlap: int = MIN_CORR_OVERLAP,
) -> pd.DataFrame:
    """Pairwise Pearson correlation of monthly series shapes.

    Pivots on ``year_month`` × ``series_label`` using ``value_col`` (default
    ``pct_of_max`` so different units compare as activity shapes). Pairs with
    fewer than ``min_overlap`` shared months get NaN (diagonal stays 1.0 when
    a series has any rows).
    """
    need = {"year_month", "series_label", value_col}
    if df.empty or not need <= set(df.columns):
        return pd.DataFrame()

    wide = df.pivot_table(
        index="year_month",
        columns="series_label",
        values=value_col,
        aggfunc="mean",
    ).sort_index()
    if wide.shape[1] == 0:
        return pd.DataFrame()
    if wide.shape[1] == 1:
        label = wide.columns[0]
        return pd.DataFrame([[1.0]], index=[label], columns=[label])

    labels = list(wide.columns)
    mat = pd.DataFrame(index=labels, columns=labels, dtype=float)
    for i, a in enumerate(labels):
        for j, b in enumerate(labels):
            if i == j:
                mat.loc[a, b] = 1.0
                continue
            pair = wide[[a, b]].dropna()
            if len(pair) < min_overlap:
                mat.loc[a, b] = float("nan")
                continue
            if pair[a].nunique(dropna=True) < 2 or pair[b].nunique(dropna=True) < 2:
                mat.loc[a, b] = float("nan")
                continue
            mat.loc[a, b] = float(pair[a].corr(pair[b], method="pearson"))
    return mat


def selection_notes(
    selections: list[SeriesSelection] | list[dict[str, Any]],
    conn: duckdb.DuckDBPyConnection,
) -> list[str]:
    """Human-readable reasons a selection will not contribute rows."""
    notes: list[str] = []
    parsed: list[SeriesSelection] = []
    for sel in selections:
        if isinstance(sel, SeriesSelection):
            parsed.append(sel)
        else:
            parsed.append(
                SeriesSelection(
                    series_id=str(sel["series_id"]),
                    entity=sel.get("entity"),
                )
            )
    if len(parsed) > MAX_SERIES:
        notes.append(f"Only the first {MAX_SERIES} series are used")
        parsed = parsed[:MAX_SERIES]
    for sel in parsed:
        spec = _SERIES_BY_ID.get(sel.series_id)
        if spec is None:
            notes.append(f"Unknown series id: {sel.series_id}")
            continue
        if not spec.available(conn):
            notes.append(f"{spec.label}: source not in warehouse")
            continue
        if spec.requires_entity and not (sel.entity and str(sel.entity).strip()):
            notes.append(f"{spec.label}: pick an entity")
    return notes
