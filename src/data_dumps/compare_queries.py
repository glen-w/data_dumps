"""Cross-source monthly series for the Compare explorer tab.

Explicit flat catalog (no plugin registry). Each series reuses existing
per-source monthly queries; values are normalized as % of that series' max.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import duckdb
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

MAX_SERIES = 6
ENTITY_OPTION_LIMIT = 30

OUT_COLS = ["year_month", "series_id", "series_label", "value", "unit"]


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

    def available(self, conn: duckdb.DuckDBPyConnection) -> bool:
        return query_util.has_table(conn, self.schema, self.table)


@dataclass(frozen=True)
class SeriesSelection:
    series_id: str
    entity: str | None = None


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "spotify_hours",
        "Spotify · listening hours",
        "spotify",
        "total",
        "hours",
        False,
        "spotify",
        "plays",
    ),
    SeriesSpec(
        "spotify_artist",
        "Spotify · artist",
        "spotify",
        "entity",
        "hours",
        True,
        "spotify",
        "plays",
    ),
    SeriesSpec(
        "telegram_messages",
        "Telegram · messages",
        "telegram",
        "total",
        "events",
        False,
        "telegram",
        "messages",
    ),
    SeriesSpec(
        "telegram_chat",
        "Telegram · chat",
        "telegram",
        "entity",
        "events",
        True,
        "telegram",
        "messages",
    ),
    SeriesSpec(
        "twitter_tweets",
        "Twitter · tweets",
        "twitter",
        "total",
        "tweets",
        False,
        "twitter",
        "tweets",
    ),
    SeriesSpec(
        "twitter_account",
        "Twitter · account",
        "twitter",
        "entity",
        "tweets",
        True,
        "twitter",
        "tweets",
    ),
    SeriesSpec(
        "slack_messages",
        "Slack · messages",
        "slack",
        "total",
        "messages",
        False,
        "slack",
        "messages",
    ),
    SeriesSpec(
        "slack_channel",
        "Slack · channel",
        "slack",
        "entity",
        "messages",
        True,
        "slack",
        "messages",
    ),
    SeriesSpec(
        "slack_person",
        "Slack · person",
        "slack",
        "entity",
        "messages",
        True,
        "slack",
        "messages",
    ),
    SeriesSpec(
        "linkedin_messages",
        "LinkedIn · messages",
        "linkedin",
        "total",
        "messages",
        False,
        "linkedin",
        "messages",
    ),
    SeriesSpec(
        "linkedin_conversation",
        "LinkedIn · conversation",
        "linkedin",
        "entity",
        "messages",
        True,
        "linkedin",
        "messages",
    ),
    SeriesSpec(
        "thunderbird_messages",
        "Thunderbird · messages",
        "thunderbird",
        "total",
        "messages",
        False,
        "thunderbird",
        "messages",
    ),
    SeriesSpec(
        "thunderbird_contact",
        "Thunderbird · contact",
        "thunderbird",
        "entity",
        "messages",
        True,
        "thunderbird",
        "messages",
    ),
    SeriesSpec(
        "sleep_hours",
        "Sleep · avg hours",
        "sleep",
        "total",
        "hours",
        False,
        "sleep",
        "sessions",
    ),
    SeriesSpec(
        "amazon_orders",
        "Amazon · orders",
        "amazon",
        "total",
        "orders",
        False,
        "amazon",
        "order_items",
    ),
    SeriesSpec(
        "miband_bpm",
        "Mi Band · avg BPM",
        "miband",
        "total",
        "bpm",
        False,
        "miband",
        "heart_rate",
    ),
)

_SERIES_BY_ID: dict[str, SeriesSpec] = {s.id: s for s in SERIES}


def list_available_series(conn: duckdb.DuckDBPyConnection) -> list[SeriesSpec]:
    return [s for s in SERIES if s.available(conn)]


def series_by_id(series_id: str) -> SeriesSpec | None:
    return _SERIES_BY_ID.get(series_id)


def compare_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Union year / day span across available Compare sources."""
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
    available_sources = {s.source for s in list_available_series(conn)}
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


def _year_filters(
    year_start: int | None, year_end: int | None
) -> tuple[int | None, int | None]:
    return year_start, year_end


def _ym_from_year_month(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "year_month" not in out.columns and {"year", "month"} <= set(out.columns):
        out["year_month"] = (
            out["year"].astype(str) + "-" + out["month"].astype(str).str.zfill(2)
        )
    return out


def _ym_from_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    dt = pd.to_datetime(out[col], errors="coerce")
    out["year_month"] = dt.dt.strftime("%Y-%m")
    return out.dropna(subset=["year_month"])


def _pack(
    df: pd.DataFrame,
    *,
    value_col: str,
    series_id: str,
    series_label: str,
    unit: str,
) -> pd.DataFrame:
    if df.empty or value_col not in df.columns or "year_month" not in df.columns:
        return pd.DataFrame(columns=OUT_COLS)
    out = df[["year_month", value_col]].copy()
    out = out.rename(columns={value_col: "value"})
    out["value"] = pd.to_numeric(out["value"], errors="coerce").fillna(0.0)
    out["series_id"] = series_id
    out["series_label"] = series_label
    out["unit"] = unit
    return out[OUT_COLS].sort_values("year_month").reset_index(drop=True)


def _entity_label(spec: SeriesSpec, entity: str) -> str:
    return f"{spec.label}: {entity}"


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
    ys, ye = _year_filters(year_start, year_end)

    if series_id == "spotify_artist":
        f = spq.FilterState(year_start=ys, year_end=ye)
        df = spq.top_artists(conn, f, limit=limit)
        return [
            {"value": str(r.artist_name), "label": str(r.artist_name)}
            for r in df.itertuples(index=False)
            if r.artist_name
        ]

    if series_id == "telegram_chat":
        f = tgq.FilterState(
            year_start=ys, year_end=ye, include_groups=True, include_bots=True
        )
        df = tgq.messages_by_chat(conn, f, limit=limit)
        return [
            {"value": str(r.chat_name), "label": f"{r.chat_name} ({r.chat_type})"}
            for r in df.itertuples(index=False)
            if r.chat_name
        ]

    if series_id == "twitter_account":
        f = twq.FilterState(year_start=ys, year_end=ye)
        df = twq.top_mentions(conn, f, limit=limit)
        return [
            {"value": str(r.account), "label": f"@{r.account}"}
            for r in df.itertuples(index=False)
            if r.account
        ]

    if series_id == "slack_channel":
        bounds = skq.data_bounds(conn)
        channels = sorted(
            bounds.get("channels") or [],
            key=lambda c: (-int(c.get("messages") or 0), c.get("name") or ""),
        )[:limit]
        return [
            {
                "value": str(c["channel_id"]),
                "label": f"#{c.get('name') or c['channel_id']}",
            }
            for c in channels
        ]

    if series_id == "slack_person":
        bounds = skq.data_bounds(conn)
        people = sorted(
            bounds.get("people") or [],
            key=lambda p: (-int(p.get("messages") or 0), p.get("name") or ""),
        )[:limit]
        return [
            {
                "value": str(p["user_id"]),
                "label": str(p.get("name") or p["user_id"]),
            }
            for p in people
        ]

    if series_id == "linkedin_conversation":
        f = liq.FilterState(year_start=ys, year_end=ye)
        df = liq.messages_by_conversation(conn, f, limit=limit)
        return [
            {"value": str(r.conversation), "label": str(r.conversation)}
            for r in df.itertuples(index=False)
            if r.conversation
        ]

    if series_id == "thunderbird_contact":
        f = tbq.FilterState(year_start=ys, year_end=ye)
        df = tbq.top_senders(conn, f, limit=limit)
        return [
            {"value": str(r.contact), "label": str(r.contact)}
            for r in df.itertuples(index=False)
            if r.contact
        ]

    return []


def _fetch_one(
    conn: duckdb.DuckDBPyConnection,
    spec: SeriesSpec,
    *,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    ys, ye = _year_filters(year_start, year_end)
    sid = spec.id
    unit = spec.unit

    if sid == "spotify_hours":
        f = spq.FilterState(year_start=ys, year_end=ye)
        df = _ym_from_year_month(spq.monthly_hours(conn, f))
        return _pack(df, value_col="hours", series_id=sid, series_label=spec.label, unit=unit)

    if sid == "spotify_artist":
        if not entity:
            return pd.DataFrame(columns=OUT_COLS)
        f = spq.FilterState(year_start=ys, year_end=ye, artist_name=entity)
        df = _ym_from_year_month(spq.monthly_hours(conn, f))
        return _pack(
            df,
            value_col="hours",
            series_id=sid,
            series_label=_entity_label(spec, entity),
            unit=unit,
        )

    if sid == "telegram_messages":
        f = tgq.FilterState(year_start=ys, year_end=ye)
        df = _ym_from_year_month(tgq.monthly_messages(conn, f))
        return _pack(df, value_col="events", series_id=sid, series_label=spec.label, unit=unit)

    if sid == "telegram_chat":
        if not entity:
            return pd.DataFrame(columns=OUT_COLS)
        f = tgq.FilterState(
            year_start=ys,
            year_end=ye,
            chat_name=entity,
            include_groups=True,
            include_bots=True,
        )
        df = _ym_from_year_month(tgq.monthly_messages(conn, f))
        return _pack(
            df,
            value_col="events",
            series_id=sid,
            series_label=_entity_label(spec, entity),
            unit=unit,
        )

    if sid == "twitter_tweets":
        f = twq.FilterState(year_start=ys, year_end=ye)
        df = _ym_from_year_month(twq.monthly_volume(conn, f))
        return _pack(df, value_col="tweets", series_id=sid, series_label=spec.label, unit=unit)

    if sid == "twitter_account":
        if not entity:
            return pd.DataFrame(columns=OUT_COLS)
        f = twq.FilterState(year_start=ys, year_end=ye, account_name=entity)
        df = _ym_from_year_month(twq.monthly_volume(conn, f))
        return _pack(
            df,
            value_col="tweets",
            series_id=sid,
            series_label=_entity_label(spec, f"@{entity.lstrip('@')}"),
            unit=unit,
        )

    if sid == "slack_messages":
        f = skq.FilterState(year_start=ys, year_end=ye)
        raw = skq.monthly_messages_by_kind(conn, f)
        if raw.empty:
            return pd.DataFrame(columns=OUT_COLS)
        df = (
            raw.groupby("year_month", as_index=False)["messages"]
            .sum()
            .sort_values("year_month")
        )
        return _pack(df, value_col="messages", series_id=sid, series_label=spec.label, unit=unit)

    if sid == "slack_channel":
        if not entity:
            return pd.DataFrame(columns=OUT_COLS)
        f = skq.FilterState(year_start=ys, year_end=ye, channel_ids=[entity])
        raw = skq.monthly_messages_by_kind(conn, f)
        if raw.empty:
            return pd.DataFrame(columns=OUT_COLS)
        df = (
            raw.groupby("year_month", as_index=False)["messages"]
            .sum()
            .sort_values("year_month")
        )
        label_entity = entity
        for opt in entity_options(conn, sid, year_start=ys, year_end=ye):
            if opt["value"] == entity:
                label_entity = opt["label"]
                break
        return _pack(
            df,
            value_col="messages",
            series_id=sid,
            series_label=_entity_label(spec, label_entity),
            unit=unit,
        )

    if sid == "slack_person":
        if not entity:
            return pd.DataFrame(columns=OUT_COLS)
        f = skq.FilterState(year_start=ys, year_end=ye, user_ids=[entity])
        raw = skq.monthly_messages_by_kind(conn, f)
        if raw.empty:
            return pd.DataFrame(columns=OUT_COLS)
        df = (
            raw.groupby("year_month", as_index=False)["messages"]
            .sum()
            .sort_values("year_month")
        )
        label_entity = entity
        for opt in entity_options(conn, sid, year_start=ys, year_end=ye):
            if opt["value"] == entity:
                label_entity = opt["label"]
                break
        return _pack(
            df,
            value_col="messages",
            series_id=sid,
            series_label=_entity_label(spec, label_entity),
            unit=unit,
        )

    if sid == "linkedin_messages":
        f = liq.FilterState(year_start=ys, year_end=ye)
        df = _ym_from_year_month(liq.monthly_messages(conn, f))
        return _pack(df, value_col="messages", series_id=sid, series_label=spec.label, unit=unit)

    if sid == "linkedin_conversation":
        if not entity:
            return pd.DataFrame(columns=OUT_COLS)
        f = liq.FilterState(year_start=ys, year_end=ye, conversation=entity)
        df = _ym_from_year_month(liq.monthly_messages(conn, f))
        return _pack(
            df,
            value_col="messages",
            series_id=sid,
            series_label=_entity_label(spec, entity),
            unit=unit,
        )

    if sid == "thunderbird_messages":
        f = tbq.FilterState(year_start=ys, year_end=ye)
        raw = _ym_from_year_month(tbq.monthly_volume(conn, f))
        if raw.empty:
            return pd.DataFrame(columns=OUT_COLS)
        df = (
            raw.groupby("year_month", as_index=False)["messages"]
            .sum()
            .sort_values("year_month")
        )
        return _pack(df, value_col="messages", series_id=sid, series_label=spec.label, unit=unit)

    if sid == "thunderbird_contact":
        if not entity:
            return pd.DataFrame(columns=OUT_COLS)
        f = tbq.FilterState(year_start=ys, year_end=ye, contact_exact=entity)
        raw = _ym_from_year_month(tbq.monthly_volume(conn, f))
        if raw.empty:
            return pd.DataFrame(columns=OUT_COLS)
        df = (
            raw.groupby("year_month", as_index=False)["messages"]
            .sum()
            .sort_values("year_month")
        )
        return _pack(
            df,
            value_col="messages",
            series_id=sid,
            series_label=_entity_label(spec, entity),
            unit=unit,
        )

    if sid == "sleep_hours":
        f = slq.FilterState(year_start=ys, year_end=ye)
        df = _ym_from_date_col(slq.monthly_hours(conn, f), "month")
        return _pack(
            df, value_col="avg_hours", series_id=sid, series_label=spec.label, unit=unit
        )

    if sid == "amazon_orders":
        f = amzq.FilterState(year_start=ys, year_end=ye)
        df = _ym_from_date_col(amzq.monthly_orders(conn, f), "month_start")
        return _pack(df, value_col="orders", series_id=sid, series_label=spec.label, unit=unit)

    if sid == "miband_bpm":
        f = mbq.FilterState(year_start=ys, year_end=ye)
        df = _ym_from_year_month(mbq.monthly_avg(conn, f))
        return _pack(df, value_col="avg_bpm", series_id=sid, series_label=spec.label, unit=unit)

    return pd.DataFrame(columns=OUT_COLS)


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
        frame = _fetch_one(
            conn,
            spec,
            year_start=year_start,
            year_end=year_end,
            entity=(sel.entity.strip() if sel.entity else None),
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
        out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=OUT_COLS)
        if "pct_of_max" not in out.columns:
            out["pct_of_max"] = pd.Series(dtype=float)
        return out

    out = df.copy()
    out["value"] = pd.to_numeric(out["value"], errors="coerce").fillna(0.0)
    maxima = out.groupby("series_label")["value"].transform("max")
    out["pct_of_max"] = 0.0
    nonzero = maxima > 0
    out.loc[nonzero, "pct_of_max"] = (
        out.loc[nonzero, "value"] / maxima[nonzero] * 100.0
    )
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

    wide = (
        df.pivot_table(
            index="year_month",
            columns="series_label",
            values=value_col,
            aggfunc="mean",
        )
        .sort_index()
    )
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
            # Constant series → undefined Pearson; treat as NaN.
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
