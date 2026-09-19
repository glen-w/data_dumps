"""Compare / Correlations series for thunderbird.

Grain and aggregation stay explicit. Do not scan warehouse columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps import thunderbird_queries as tbq
from data_dumps.series_catalog import (
    Grain,
    MetricSpec,
    SeriesSpec,
    empty_compare,
    empty_correlate,
    entity_label,
    make_compare_total,
    make_correlate_metric,
    pack_compare,
    pack_correlate,
    ym_from_year_month,
    ym_string_to_ts,
)

ENTITY_OPTION_LIMIT = 30

# --- Thunderbird -------------------------------------------------------------


def _thunderbird_sum_monthly(
    conn: duckdb.DuckDBPyConnection, f: tbq.FilterState
) -> pd.DataFrame:
    raw = ym_from_year_month(tbq.monthly_volume(conn, f))
    if raw.empty:
        return pd.DataFrame(columns=["year_month", "messages"])
    summed = raw.groupby("year_month", as_index=False)["messages"].sum()
    return pd.DataFrame(summed).sort_values("year_month")


def _thunderbird_messages_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    f = tbq.FilterState(year_start=year_start, year_end=year_end)
    df = _thunderbird_sum_monthly(conn, f)
    return pack_compare(
        df,
        value_col="messages",
        series_id="thunderbird_messages",
        series_label="Thunderbird · messages",
        unit="messages",
    )


def _thunderbird_contact_options(
    conn: duckdb.DuckDBPyConnection,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = ENTITY_OPTION_LIMIT,
) -> list[dict[str, str]]:
    f = tbq.FilterState(year_start=year_start, year_end=year_end)
    df = tbq.top_senders(conn, f, limit=limit)
    return [
        {"value": str(r.contact), "label": str(r.contact)}
        for r in df.itertuples(index=False)
        if r.contact
    ]


def _thunderbird_contact_compare(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    entity: str | None,
) -> pd.DataFrame:
    if not entity:
        return empty_compare()
    f = tbq.FilterState(year_start=year_start, year_end=year_end, contact_exact=entity)
    df = _thunderbird_sum_monthly(conn, f)
    return pack_compare(
        df,
        value_col="messages",
        series_id="thunderbird_contact",
        series_label=entity_label("Thunderbird · contact", entity),
        unit="messages",
    )


def _thunderbird_messages_correlate(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    grain: Grain,
) -> pd.DataFrame:
    f = tbq.FilterState(year_start=year_start, year_end=year_end)
    mid, label, unit = "thunderbird_messages", "Thunderbird · messages", "messages"
    if grain == "daily":
        return pack_correlate(
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
        return empty_correlate()
    if "year_month" not in raw.columns and {"year", "month"} <= set(raw.columns):
        raw = raw.copy()
        raw["year_month"] = (
            raw["year"].astype(str) + "-" + raw["month"].astype(str).str.zfill(2)
        )
    df = pd.DataFrame(raw.groupby("year_month", as_index=False)["messages"].sum())
    df = ym_string_to_ts(df)
    return pack_correlate(
        df,
        time_col="time_key",
        value_col="messages",
        metric_id=mid,
        metric_label=label,
        unit=unit,
        grain=grain,
    )


def _thunderbird_signals_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = tbq.FilterState(year_start=year_start, year_end=year_end)
    return tbq.signals_total_monthly(conn, f)


def _thunderbird_signals_corr_monthly(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    return ym_string_to_ts(_thunderbird_signals_monthly(conn, year_start, year_end))


THUNDERBIRD_COMPARE: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "thunderbird_messages",
        "Thunderbird · messages",
        "thunderbird",
        "total",
        "messages",
        False,
        "thunderbird",
        "messages",
        _thunderbird_messages_compare,
    ),
    make_compare_total(
        id="thunderbird_signals",
        label="Thunderbird · signals",
        source="thunderbird",
        schema="thunderbird",
        table="signals",
        unit="messages",
        value_col="messages",
        load_monthly=_thunderbird_signals_monthly,
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
        _thunderbird_contact_compare,
        _thunderbird_contact_options,
    ),
)

THUNDERBIRD_CORRELATE: tuple[MetricSpec, ...] = (
    MetricSpec(
        "thunderbird_messages",
        "Thunderbird · messages",
        "thunderbird",
        "messages",
        "thunderbird",
        "messages",
        True,
        True,
        _thunderbird_messages_correlate,
    ),
    make_correlate_metric(
        id="thunderbird_signals",
        label="Thunderbird · signals",
        source="thunderbird",
        schema="thunderbird",
        table="signals",
        unit="messages",
        supports_daily=False,
        supports_monthly=True,
        value_col="messages",
        load_monthly=_thunderbird_signals_corr_monthly,
    ),
)
