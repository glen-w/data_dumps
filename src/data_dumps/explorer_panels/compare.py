"""Cross-source Compare explorer tab: pick series, overlay % of max."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import compare_queries as cq

from . import charts as panel_charts


@dataclass
class CompareControls:
    year_start: Any
    year_end: Any
    series_select: Any
    entity_widgets: dict[str, Any]


def make_compare_controls(
    mo: Any,
    bounds: dict[str, Any],
    available_series: list[cq.SeriesSpec],
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> CompareControls:
    options = {s.id: s.label for s in available_series}
    default_ids = [s.id for s in available_series if s.kind == "total"][:2]
    ys = bounds.get("min_year")
    ye = bounds.get("max_year")
    entity_widgets: dict[str, Any] = {}
    for spec in available_series:
        if not spec.requires_entity:
            continue
        opt_map: dict[str, str] = {"": "(pick entity)"}
        if conn is not None:
            for o in cq.entity_options(
                conn, spec.id, year_start=ys, year_end=ye
            ):
                opt_map[o["value"]] = o["label"]
        entity_widgets[spec.id] = mo.ui.dropdown(
            options=opt_map,
            value="",
            label=spec.label,
        )
    return CompareControls(
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
        series_select=mo.ui.multiselect(
            options=options,
            value=default_ids,
            label=f"Series (max {cq.MAX_SERIES})",
        ),
        entity_widgets=entity_widgets,
    )


def render_compare_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: CompareControls,
) -> Any:
    available = cq.list_available_series(conn)
    if not available:
        return mo.md(
            "No comparable sources in the warehouse yet. Ingest at least one dump "
            "with monthly activity (Spotify, Telegram, Slack, …)."
        )

    ys = int(controls.year_start.value)
    ye = int(controls.year_end.value)
    if ys > ye:
        ys, ye = ye, ys

    selected_ids = list(controls.series_select.value or [])[: cq.MAX_SERIES]
    available_ids = {s.id for s in available}
    selected_ids = [sid for sid in selected_ids if sid in available_ids]

    entity_rows: list[Any] = []
    selections: list[cq.SeriesSelection] = []
    for sid in selected_ids:
        spec = cq.series_by_id(sid)
        if spec is None:
            continue
        entity: str | None = None
        if spec.requires_entity:
            widget = controls.entity_widgets.get(sid)
            if widget is not None:
                entity_rows.append(widget)
                entity = str(widget.value or "").strip() or None
            if not entity:
                continue
        selections.append(cq.SeriesSelection(series_id=sid, entity=entity))

    chips: list[str] = [f"years {ys}–{ye}"]
    if len(list(controls.series_select.value or [])) > cq.MAX_SERIES:
        chips.append(f"capped at {cq.MAX_SERIES} series")
    for sel in selections:
        spec = cq.series_by_id(sel.series_id)
        if spec is None:
            continue
        if sel.entity:
            chips.append(f"{spec.label}: {sel.entity}")
        else:
            chips.append(spec.label)
    chip_row = (
        mo.hstack([mo.md(f"**{c}**") for c in chips], gap=0.5)
        if chips
        else mo.md("_No series selected_")
    )

    raw = cq.fetch_monthly(conn, selections, year_start=ys, year_end=ye)
    norm = cq.normalize_pct_of_max(raw)
    fig = panel_charts.normalized_overlay(
        px,
        norm,
        title="Monthly activity (% of each series' max)",
        empty_title="Select up to 6 series (pick entities where required)",
    )

    table_df = raw.copy()
    if not table_df.empty:
        table_df = table_df.sort_values(["year_month", "series_label"]).reset_index(
            drop=True
        )

    filter_row = mo.hstack(
        [controls.year_start, controls.year_end, controls.series_select],
        gap=1,
        wrap=True,
    )
    entity_block = (
        mo.hstack(entity_rows, gap=1, wrap=True)
        if entity_rows
        else mo.md("_No entity series selected_")
    )

    return mo.vstack(
        [
            mo.md("## Compare"),
            mo.md(
                "Overlay monthly activity across sources and threads. "
                "Each series is scaled to **% of its own maximum** in the "
                "selected year window so different units line up."
            ),
            filter_row,
            entity_block,
            chip_row,
            mo.md("### Normalized overlay"),
            mo.ui.plotly(fig),
            mo.md("### Raw monthly values"),
            mo.ui.table(table_df) if not table_df.empty else mo.md("_No data_"),
        ],
        gap=0.5,
    )
