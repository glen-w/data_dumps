"""Cross-source Correlations explorer: aligned panels, Pearson/Spearman, lag scan.

Catalogs come from :mod:`data_dumps.contributions` (callable MetricSpec fetch).
Daily-first; monthly fallback. Inner-join overlap only — no zero-fill.
"""

from __future__ import annotations

from typing import Any

import duckdb
import numpy as np
import pandas as pd

from data_dumps.contributions import CORRELATE_METRICS, bounds_fns_for_series
from data_dumps.series_catalog import CORRELATE_LONG_COLS, Grain, MetricSpec

MAX_METRICS = 10
MIN_N_DAILY = 30
MIN_N_MONTHLY = 12
MAX_LAG_DAILY = 7
MAX_LAG_MONTHLY = 3

LONG_COLS = CORRELATE_LONG_COLS

PRESET_LIFE_RHYTHM = "life_rhythm"
PRESET_COMMS = "comms"
PRESET_SLEEP_BODY = "sleep_body"
PRESET_CUSTOM = "custom"
PRESETS = (
    PRESET_LIFE_RHYTHM,
    PRESET_COMMS,
    PRESET_SLEEP_BODY,
    PRESET_CUSTOM,
)

METRICS: tuple[MetricSpec, ...] = CORRELATE_METRICS
_METRICS_BY_ID: dict[str, MetricSpec] = {m.id: m for m in METRICS}

_PRESET_IDS: dict[str, tuple[str, ...]] = {
    PRESET_LIFE_RHYTHM: (
        "sleep_hours",
        "spotify_hours",
        "telegram_events",
        "slack_messages",
        "twitter_tweets",
        "airbnb_searches",
        "uber_trips",
    ),
    PRESET_COMMS: (
        "telegram_events",
        "slack_messages",
        "twitter_tweets",
        "linkedin_events",
        "thunderbird_messages",
        "chatgpt_messages",
    ),
    PRESET_SLEEP_BODY: (
        "sleep_hours",
        "miband_bpm",
        "miband_readings",
        "spotify_late_hours",
    ),
}


def list_available_metrics(conn: duckdb.DuckDBPyConnection) -> list[MetricSpec]:
    return [m for m in METRICS if m.available(conn)]


def metric_by_id(metric_id: str) -> MetricSpec | None:
    return _METRICS_BY_ID.get(metric_id)


def correlate_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    available_sources = {m.source for m in list_available_metrics(conn)}
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
    n = len(list_available_metrics(conn))
    if not min_years or not max_years:
        return {
            "min_year": 2020,
            "max_year": 2025,
            "first_day": None,
            "last_day": None,
            "n_metrics": 0,
        }
    return {
        "min_year": min(min_years),
        "max_year": max(max_years),
        "first_day": min(first_days) if first_days else None,
        "last_day": max(last_days) if last_days else None,
        "n_metrics": n,
    }


def apply_preset(
    name: str, available: list[MetricSpec]
) -> tuple[list[str], tuple[str, str] | None]:
    """Return (metric_ids ≤ MAX_METRICS, optional suggested focus pair)."""
    avail_ids = {m.id for m in available}
    if name == PRESET_CUSTOM or name not in _PRESET_IDS:
        ids = [m.id for m in available if m.supports_daily or m.supports_monthly][
            :MAX_METRICS
        ]
        focus = (ids[0], ids[1]) if len(ids) >= 2 else None
        return ids, focus
    ids = [mid for mid in _PRESET_IDS[name] if mid in avail_ids][:MAX_METRICS]
    if len(ids) < 2:
        ids = [m.id for m in available][:MAX_METRICS]
    focus = (ids[0], ids[1]) if len(ids) >= 2 else None
    return ids, focus


def fetch_panel(
    conn: duckdb.DuckDBPyConnection,
    metric_ids: list[str],
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    grain: Grain = "daily",
) -> pd.DataFrame:
    ids = list(dict.fromkeys(metric_ids))[:MAX_METRICS]
    frames: list[pd.DataFrame] = []
    for mid in ids:
        spec = _METRICS_BY_ID.get(mid)
        if spec is None or not spec.available(conn):
            continue
        if grain == "daily" and not spec.supports_daily:
            continue
        if grain == "monthly" and not spec.supports_monthly:
            continue
        frame = spec.fetch(conn, year_start, year_end, grain)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=LONG_COLS)
    return pd.concat(frames, ignore_index=True)


def pivot_panel(long_df: pd.DataFrame) -> pd.DataFrame:
    """Wide frame: index=time_key, columns=metric_id."""
    if long_df.empty:
        return pd.DataFrame()
    wide = long_df.pivot_table(
        index="time_key",
        columns="metric_id",
        values="value",
        aggfunc="sum",
    )
    return wide.sort_index()


def _min_n(grain: Grain) -> int:
    return MIN_N_DAILY if grain == "daily" else MIN_N_MONTHLY


def correlation_matrix(
    wide: pd.DataFrame,
    *,
    method: str = "pearson",
    min_n: int | None = None,
    grain: Grain = "daily",
) -> pd.DataFrame:
    """Square r matrix; cells with overlap < min_n become NaN."""
    if wide.empty or wide.shape[1] < 2:
        return pd.DataFrame()
    threshold = _min_n(grain) if min_n is None else min_n
    cols = list(wide.columns)
    mat = pd.DataFrame(np.nan, index=cols, columns=cols, dtype=float)
    for i, a in enumerate(cols):
        mat.loc[a, a] = 1.0
        for b in cols[i + 1 :]:
            pair = wide[[a, b]].dropna()
            n = len(pair)
            if n < threshold:
                continue
            r = pair[a].corr(pair[b], method=method)  # type: ignore[arg-type]
            mat.loc[a, b] = r
            mat.loc[b, a] = r
    return mat


def rank_pairs(
    wide: pd.DataFrame,
    *,
    grain: Grain = "daily",
    min_n: int | None = None,
    labels: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Ranked unique pairs with Pearson + Spearman r and overlap n."""
    cols = [
        "a",
        "b",
        "a_label",
        "b_label",
        "r_pearson",
        "r_spearman",
        "n",
        "grain",
        "abs_r",
    ]
    if wide.empty or wide.shape[1] < 2:
        return pd.DataFrame(columns=cols)
    threshold = _min_n(grain) if min_n is None else min_n
    label_map_ = labels or {}
    rows: list[dict[str, Any]] = []
    metrics = list(wide.columns)
    for i, a in enumerate(metrics):
        for b in metrics[i + 1 :]:
            pair = wide[[a, b]].dropna()
            n = len(pair)
            if n < threshold:
                continue
            rp = float(pair[a].corr(pair[b], method="pearson"))
            rs = float(pair[a].rank().corr(pair[b].rank(), method="pearson"))
            if pd.isna(rp):
                continue
            rows.append(
                {
                    "a": a,
                    "b": b,
                    "a_label": label_map_.get(a, a),
                    "b_label": label_map_.get(b, b),
                    "r_pearson": rp,
                    "r_spearman": rs,
                    "n": n,
                    "grain": grain,
                    "abs_r": abs(rp),
                }
            )
    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)
    return out.sort_values("abs_r", ascending=False).reset_index(drop=True)


def aligned_pair(wide: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    """Inner-joined scatter frame with columns day, x, y."""
    if wide.empty or a not in wide.columns or b not in wide.columns:
        return pd.DataFrame(columns=["day", "x", "y"])
    pair = wide[[a, b]].dropna().copy()
    pair = pair.reset_index()
    time_col = "time_key" if "time_key" in pair.columns else pair.columns[0]
    pair = pair.rename(columns={time_col: "day", a: "x", b: "y"})
    return pair[["day", "x", "y"]]


def lag_scan(
    series_a: pd.Series,
    series_b: pd.Series,
    *,
    max_lag: int = MAX_LAG_DAILY,
    min_n: int = MIN_N_DAILY,
    freq: str = "D",
) -> tuple[pd.DataFrame, int | None, float | None]:
    """Scan lags of B relative to A: positive lag = B delayed.

    Returns (lag_df with lag/r/n, best_lag, best_r).
    ``freq`` is a pandas offset alias (``D`` daily, ``MS`` monthly).
    """
    cols = ["lag", "r", "n"]
    if series_a.empty or series_b.empty:
        return pd.DataFrame(columns=cols), None, None
    a = series_a.dropna().sort_index()
    b = series_b.dropna().sort_index()
    rows: list[dict[str, Any]] = []
    for lag in range(-max_lag, max_lag + 1):
        if lag == 0:
            b_shift = b
        elif isinstance(b.index, pd.DatetimeIndex):
            b_shift = b.shift(lag, freq=freq)
        else:
            b_shift = b.shift(lag)
        joined = pd.concat(
            [a.rename("a"), b_shift.rename("b")], axis=1, sort=False
        ).dropna()
        n = len(joined)
        if n < min_n:
            rows.append({"lag": lag, "r": np.nan, "n": n})
            continue
        r = float(joined["a"].corr(joined["b"], method="pearson"))
        rows.append({"lag": lag, "r": r, "n": n})
    lag_df = pd.DataFrame(rows)
    valid = lag_df.dropna(subset=["r"])
    if valid.empty:
        return lag_df, None, None
    best_i = valid["r"].abs().idxmax()
    best = valid.loc[best_i]
    return lag_df, int(best["lag"]), float(best["r"])  # type: ignore[arg-type]


def label_map(available: list[MetricSpec] | None = None) -> dict[str, str]:
    specs = available if available is not None else list(METRICS)
    return {m.id: m.label for m in specs}


def zscore_long(long_df: pd.DataFrame, metric_ids: list[str]) -> pd.DataFrame:
    """Per-metric z-score for overlay charts."""
    if long_df.empty:
        return long_df.copy()
    frames: list[pd.DataFrame] = []
    for mid in metric_ids:
        part = long_df[long_df["metric_id"] == mid].copy()
        if part.empty:
            continue
        mu = part["value"].mean()
        sigma = part["value"].std(ddof=0)
        if sigma and sigma > 0:
            part["z"] = (part["value"] - mu) / sigma
        else:
            part["z"] = 0.0
        frames.append(part)
    if not frames:
        return pd.DataFrame(columns=[*LONG_COLS, "z"])
    return pd.concat(frames, ignore_index=True)
