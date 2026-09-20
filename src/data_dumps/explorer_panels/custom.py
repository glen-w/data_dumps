"""Custom (manifest) explorer tab: one picker, Wrapped-style charts per source."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import custom_queries as cq

from . import charts as panel_charts


@dataclass
class CustomControls:
    source: Any
    year_start: Any
    year_end: Any
    compare: Any


def make_custom_controls(mo: Any, bounds: dict[str, Any]) -> CustomControls:
    labels = list(bounds.get("source_by_label") or [])
    if not labels:
        labels = ["(none)"]
    return CustomControls(
        source=mo.ui.dropdown(
            options=labels,
            value=labels[0],
            label="Source",
        ),
        year_start=mo.ui.slider(
            start=bounds["min_year"],
            stop=bounds["max_year"],
            value=bounds["min_year"],
            label="From year",
            show_value=True,
        ),
        year_end=mo.ui.slider(
            start=bounds["min_year"],
            stop=bounds["max_year"],
            value=bounds["max_year"],
            label="To year",
            show_value=True,
        ),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
    )


def render_custom_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: CustomControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = cq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
        source_label=str(controls.source.value or ""),
    )
    meta = cq.source_meta(bounds, filters.source_slug)
    if meta is None:
        return mo.md(
            "No custom sources in the warehouse. Stop this notebook, then ingest a "
            "folder that contains `data_dumps.json`."
        )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )
    score_df = cq.scoreboard(
        conn, filters, compare_previous=bool(controls.compare.value)
    )
    monthly_df = cq.events_monthly(conn, filters)
    daily_df = cq.events_daily(conn, filters)
    heat_df = cq.weekday_heatmap(conn, filters)
    streaks_df = cq.streak_table(conn, filters)
    title = meta["label"]
    tz = meta["timezone"]
    fig_monthly = (
        px.bar(monthly_df, x="year_month", y="events", title=f"{title} events by month")
        if not monthly_df.empty
        else px.bar(title="No events in range")
    )
    fig_cal = panel_charts.iso_week_calendar(
        px,
        daily_df,
        z="events",
        title=f"{title} events (weekday × ISO week)",
        empty_title="No calendar",
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        heat_df,
        z="events",
        dow_labels=dow_labels,
        title=f"{title} by weekday × hour ({tz})",
        empty_title="No circadian data",
    )
    blocks: list[Any] = [
        mo.md(
            f"## {title}\n"
            f"{meta['grain']}. Times are {tz}. "
            "Only the time column, and optional entity / value columns, are stored. "
            "Email, IP, and phone columns are dropped."
        ),
        mo.hstack(
            [
                controls.source,
                controls.year_start,
                controls.year_end,
                controls.compare,
            ],
            justify="start",
            gap=1,
        ),
        chip_row,
        mo.md("### Scoreboard"),
        mo.ui.table(score_df),
        mo.md("### Monthly"),
        mo.ui.plotly(fig_monthly),
    ]
    if meta["has_value"] and not monthly_df.empty:
        blocks.append(
            mo.ui.plotly(
                px.bar(
                    monthly_df,
                    x="year_month",
                    y="value",
                    title=f"{title} value by month",
                )
            )
        )
    if meta["has_entity"]:
        entity_df = cq.events_by_entity(conn, filters)
        forgotten_df = cq.forgotten_entities(conn, filters)
        comeback_df = cq.comeback_entities(conn, filters)
        fig_entity = (
            px.bar(
                entity_df,
                x="events",
                y="entity",
                orientation="h",
                title=f"{title} by entity",
            )
            if not entity_df.empty
            else px.bar(title="No entities")
        )
        if not entity_df.empty:
            fig_entity.update_layout(yaxis={"categoryorder": "total ascending"})
        blocks.extend(
            [
                mo.md("### Entities"),
                mo.ui.plotly(fig_entity),
                mo.ui.table(entity_df),
                mo.md("### Forgotten (silent ≥ 2 years)"),
                mo.ui.table(forgotten_df),
                mo.md("### Comebacks (gap ≥ 2 years)"),
                mo.ui.table(comeback_df),
            ]
        )
    blocks.extend(
        [
            mo.md("### Rhythm"),
            mo.ui.plotly(fig_cal),
            mo.ui.plotly(fig_circ),
            mo.md("### Streaks"),
            mo.ui.table(streaks_df),
        ]
    )
    return mo.vstack(blocks, gap=0.5)
