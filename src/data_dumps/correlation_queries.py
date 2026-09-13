"""Cross-source Correlations explorer: aligned panels, Pearson/Spearman, lag scan.

Explicit metric catalog (no plugin registry). Daily-first; monthly fallback.
Inner-join overlap only — no zero-fill.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import duckdb
import numpy as np
import pandas as pd

from data_dumps import amazon_queries as amzq
from data_dumps import linkedin_queries as liq
from data_dumps import miband_queries as mbq
from data_dumps import query_util
from data_dumps import slack_queries as skq
from data_dumps import sleep_queries as slq
from data_dumps import spotify_queries as spq
from data_dumps import telegram_queries as tgq
from data_dumps import thunderbird_queries as tbq
from data_dumps import twitter_queries as twq

MAX_METRICS = 10
MIN_N_DAILY = 30
MIN_N_MONTHLY = 12
MAX_LAG_DAILY = 7
MAX_LAG_MONTHLY = 3

LONG_COLS = ["time_key", "metric_id", "metric_label", "value", "unit", "grain"]
Grain = Literal["daily", "monthly"]

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

    def available(self, conn: duckdb.DuckDBPyConnection) -> bool:
        return query_util.has_table(conn, self.schema, self.table)


METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "spotify_hours",
        "Spotify · hours",
        "spotify",
        "hours",
        "spotify",
        "plays",
        True,
        True,
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
    ),
    MetricSpec(
        "telegram_events",
        "Telegram · events",
        "telegram",
        "events",
        "telegram",
        "messages",
        True,
        True,
    ),
    MetricSpec(
        "twitter_tweets",
        "Twitter · tweets",
        "twitter",
        "tweets",
        "twitter",
        "tweets",
        True,
        True,
    ),
    MetricSpec(
        "slack_messages",
        "Slack · messages",
        "slack",
        "messages",
        "slack",
        "messages",
        True,
        True,
    ),
    MetricSpec(
        "linkedin_events",
        "LinkedIn · events",
        "linkedin",
        "events",
        "linkedin",
        "messages",
        True,
        True,
    ),
    MetricSpec(
        "thunderbird_messages",
        "Thunderbird · messages",
        "thunderbird",
        "messages",
        "thunderbird",
        "messages",
        True,
        True,
    ),
    MetricSpec(
        "sleep_hours",
        "Sleep · hours",
        "sleep",
        "hours",
        "sleep",
        "sessions",
        True,
        True,
    ),
    MetricSpec(
        "amazon_orders",
        "Amazon · orders",
        "amazon",
        "orders",
        "amazon",
        "order_items",
        True,
        True,
    ),
    MetricSpec(
        "miband_readings",
        "Mi Band · readings",
        "miband",
        "readings",
        "miband",
        "heart_rate",
        True,
        True,
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
    ),
)

_METRICS_BY_ID: dict[str, MetricSpec] = {m.id: m for m in METRICS}

_PRESET_IDS: dict[str, tuple[str, ...]] = {
    PRESET_LIFE_RHYTHM: (
        "sleep_hours",
        "spotify_hours",
        "telegram_events",
        "slack_messages",
        "twitter_tweets",
    ),
    PRESET_COMMS: (
        "telegram_events",
        "slack_messages",
        "twitter_tweets",
        "linkedin_events",
        "thunderbird_messages",
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
    bounds_fns: list[tuple[str, Callable[[duckdb.DuckDBPyConnection], dict[str, Any]]]] = [
        ("spotify", spq.data_bounds),
        ("telegram", tgq.data_bounds),
        ("twitter", twq.data_bounds),
        ("slack", skq.data_bounds),
        ("linkedin", liq.data_bounds),
        ("thunderbird", tbq.data_bounds),
        ("sleep", slq.data_bounds),
        ("amazon", amzq.data_bounds),
        ("miband", mbq.data_bounds),
    ]
    available_sources = {m.source for m in list_available_metrics(conn)}
    min_years: list[int] = []
    max_years: list[int] = []
    first_days: list[Any] = []
    last_days: list[Any] = []
    for source, fn in bounds_fns:
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
        # Fall back to whatever is available.
        ids = [m.id for m in available][:MAX_METRICS]
    focus = (ids[0], ids[1]) if len(ids) >= 2 else None
    return ids, focus


def _pack(
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
        return pd.DataFrame(columns=LONG_COLS)
    out = df[[time_col, value_col]].copy()
    out = out.rename(columns={time_col: "time_key", value_col: "value"})
    out["time_key"] = pd.to_datetime(out["time_key"], errors="coerce")
    if grain == "monthly":
        # Normalize to month-start timestamps for alignment.
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
    return out[LONG_COLS].sort_values("time_key").reset_index(drop=True)


def _ym_string_to_ts(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "year_month" not in df.columns:
        return df
    out = df.copy()
    out["time_key"] = pd.to_datetime(out["year_month"] + "-01", errors="coerce")
    return out


def _spotify_late_daily(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    clauses = ["hour(played_at_local) >= 22", "played_at_local IS NOT NULL"]
    params: list[Any] = []
    if year_start is not None:
        clauses.append("year >= ?")
        params.append(year_start)
    if year_end is not None:
        clauses.append("year <= ?")
        params.append(year_end)
    where = " AND ".join(clauses)
    return conn.execute(
        f"""
        SELECT
            played_at_local::DATE AS day,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    ).df()


def _fetch_one(
    conn: duckdb.DuckDBPyConnection,
    spec: MetricSpec,
    *,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    ys, ye = year_start, year_end
    mid, label, unit = spec.id, spec.label, spec.unit

    if grain == "daily" and not spec.supports_daily:
        return pd.DataFrame(columns=LONG_COLS)
    if grain == "monthly" and not spec.supports_monthly:
        return pd.DataFrame(columns=LONG_COLS)

    if mid == "spotify_hours":
        f = spq.FilterState(year_start=ys, year_end=ye)
        if grain == "daily":
            return _pack(
                spq.calendar_daily(conn, f),
                time_col="day",
                value_col="hours",
                metric_id=mid,
                metric_label=label,
                unit=unit,
                grain=grain,
            )
        df = spq.monthly_hours(conn, f)
        df = _ym_string_to_ts(df) if "year_month" in df.columns else df
        if "time_key" not in df.columns and {"year", "month"} <= set(df.columns):
            df = df.copy()
            df["time_key"] = pd.to_datetime(
                df["year"].astype(str)
                + "-"
                + df["month"].astype(str).str.zfill(2)
                + "-01",
                errors="coerce",
            )
        return _pack(
            df,
            time_col="time_key",
            value_col="hours",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )

    if mid == "spotify_late_hours":
        df = _spotify_late_daily(conn, ys, ye)
        return _pack(
            df,
            time_col="day",
            value_col="hours",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain="daily",
        )

    if mid == "telegram_events":
        f = tgq.FilterState(year_start=ys, year_end=ye)
        if grain == "daily":
            return _pack(
                tgq.calendar_daily(conn, f),
                time_col="day",
                value_col="events",
                metric_id=mid,
                metric_label=label,
                unit=unit,
                grain=grain,
            )
        df = tgq.monthly_messages(conn, f)
        df = _ym_string_to_ts(df)
        return _pack(
            df,
            time_col="time_key",
            value_col="events",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )

    if mid == "twitter_tweets":
        f = twq.FilterState(year_start=ys, year_end=ye)
        if grain == "daily":
            return _pack(
                twq.calendar_daily(conn, f),
                time_col="day",
                value_col="tweets",
                metric_id=mid,
                metric_label=label,
                unit=unit,
                grain=grain,
            )
        df = _ym_string_to_ts(twq.monthly_volume(conn, f))
        return _pack(
            df,
            time_col="time_key",
            value_col="tweets",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )

    if mid == "slack_messages":
        f = skq.FilterState(year_start=ys, year_end=ye)
        if grain == "daily":
            return _pack(
                skq.calendar_daily(conn, f),
                time_col="day",
                value_col="messages",
                metric_id=mid,
                metric_label=label,
                unit=unit,
                grain=grain,
            )
        raw = skq.monthly_messages_by_kind(conn, f)
        if raw.empty:
            return pd.DataFrame(columns=LONG_COLS)
        df = raw.groupby("year_month", as_index=False)["messages"].sum()
        df = _ym_string_to_ts(df)
        return _pack(
            df,
            time_col="time_key",
            value_col="messages",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )

    if mid == "linkedin_events":
        f = liq.FilterState(year_start=ys, year_end=ye)
        if grain == "daily":
            return _pack(
                liq.calendar_daily(conn, f),
                time_col="day",
                value_col="events",
                metric_id=mid,
                metric_label=label,
                unit=unit,
                grain=grain,
            )
        df = _ym_string_to_ts(liq.monthly_messages(conn, f))
        return _pack(
            df,
            time_col="time_key",
            value_col="messages",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )

    if mid == "thunderbird_messages":
        f = tbq.FilterState(year_start=ys, year_end=ye)
        if grain == "daily":
            return _pack(
                tbq.calendar_daily(conn, f),
                time_col="day",
                value_col="messages",
                metric_id=mid,
                metric_label=label,
                unit=unit,
                grain=grain,
            )
        raw = tbq.monthly_volume(conn, f)
        if raw.empty:
            return pd.DataFrame(columns=LONG_COLS)
        if "year_month" not in raw.columns and {"year", "month"} <= set(raw.columns):
            raw = raw.copy()
            raw["year_month"] = (
                raw["year"].astype(str)
                + "-"
                + raw["month"].astype(str).str.zfill(2)
            )
        df = raw.groupby("year_month", as_index=False)["messages"].sum()
        df = _ym_string_to_ts(df)
        return _pack(
            df,
            time_col="time_key",
            value_col="messages",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )

    if mid == "sleep_hours":
        f = slq.FilterState(year_start=ys, year_end=ye)
        if grain == "daily":
            return _pack(
                slq.calendar_daily(conn, f),
                time_col="day",
                value_col="hours",
                metric_id=mid,
                metric_label=label,
                unit=unit,
                grain=grain,
            )
        df = slq.monthly_hours(conn, f).rename(columns={"month": "time_key"})
        return _pack(
            df,
            time_col="time_key",
            value_col="avg_hours",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )

    if mid == "amazon_orders":
        f = amzq.FilterState(year_start=ys, year_end=ye)
        if grain == "daily":
            return _pack(
                amzq.order_calendar(conn, f),
                time_col="day",
                value_col="orders",
                metric_id=mid,
                metric_label=label,
                unit=unit,
                grain=grain,
            )
        df = amzq.monthly_orders(conn, f).rename(columns={"month_start": "time_key"})
        return _pack(
            df,
            time_col="time_key",
            value_col="orders",
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )

    if mid in ("miband_readings", "miband_bpm"):
        f = mbq.FilterState(year_start=ys, year_end=ye)
        value_col = "readings" if mid == "miband_readings" else "avg_bpm"
        if grain == "daily":
            return _pack(
                mbq.calendar_daily(conn, f),
                time_col="day",
                value_col=value_col,
                metric_id=mid,
                metric_label=label,
                unit=unit,
                grain=grain,
            )
        df = mbq.monthly_avg(conn, f)
        df = _ym_string_to_ts(df)
        return _pack(
            df,
            time_col="time_key",
            value_col=value_col,
            metric_id=mid,
            metric_label=label,
            unit=unit,
            grain=grain,
        )

    return pd.DataFrame(columns=LONG_COLS)


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
        frame = _fetch_one(
            conn, spec, year_start=year_start, year_end=year_end, grain=grain
        )
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
            r = pair[a].corr(pair[b], method=method)
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
    label_map = labels or {}
    rows: list[dict[str, Any]] = []
    metrics = list(wide.columns)
    for i, a in enumerate(metrics):
        for b in metrics[i + 1 :]:
            pair = wide[[a, b]].dropna()
            n = len(pair)
            if n < threshold:
                continue
            rp = float(pair[a].corr(pair[b], method="pearson"))
            # Rank-Pearson avoids a scipy dependency for Spearman.
            rs = float(pair[a].rank().corr(pair[b].rank(), method="pearson"))
            if pd.isna(rp):
                continue
            rows.append(
                {
                    "a": a,
                    "b": b,
                    "a_label": label_map.get(a, a),
                    "b_label": label_map.get(b, b),
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


def aligned_pair(
    wide: pd.DataFrame, a: str, b: str
) -> pd.DataFrame:
    """Inner-joined scatter frame with columns day, x, y."""
    if wide.empty or a not in wide.columns or b not in wide.columns:
        return pd.DataFrame(columns=["day", "x", "y"])
    pair = wide[[a, b]].dropna().copy()
    pair = pair.reset_index()
    # Index name may be time_key, day, or the default "index".
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
    return lag_df, int(best["lag"]), float(best["r"])


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
