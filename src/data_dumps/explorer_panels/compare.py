"""Cross-source Compare explorer tab: multiviewer overlay + correlations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

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
    ys = int(bounds.get("min_year") or 2020)
    ye = int(bounds.get("max_year") or ys)
    if ys > ye:
        ys, ye = ye, ys
    # Marimo sliders need stop > start; collapse single-year warehouses safely.
    stop = ye if ye > ys else ys + 1
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
    ms_kwargs: dict[str, Any] = {
        "options": options,
        "value": default_ids,
        "label": f"Series (max {cq.MAX_SERIES})",
    }
    try:
        series_select = mo.ui.multiselect(**ms_kwargs, max_selections=cq.MAX_SERIES)
    except TypeError:
        series_select = mo.ui.multiselect(**ms_kwargs)
    return CompareControls(
        year_start=mo.ui.slider(
            start=ys,
            stop=stop,
            value=ys,
            label="From year",
            show_value=True,
        ),
        year_end=mo.ui.slider(
            start=ys,
            stop=stop,
            value=ye,
            label="To year",
            show_value=True,
        ),
        series_select=series_select,
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
    # Clamp to warehouse span when slider stop was inflated for single-year data.
    ymin = int(bounds.get("min_year") or ys)
    ymax = int(bounds.get("max_year") or ye)
    ys = min(max(ys, ymin), ymax)
    ye = min(max(ye, ymin), ymax)
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
                selections.append(cq.SeriesSelection(series_id=sid, entity=None))
                continue
        selections.append(cq.SeriesSelection(series_id=sid, entity=entity))

    notes = cq.selection_notes(selections, conn)
    # Only fetch rows for selections that can succeed.
    fetch_sels = [
        s
        for s in selections
        if (spec := cq.series_by_id(s.series_id)) is not None
        and spec.available(conn)
        and (not spec.requires_entity or (s.entity and str(s.entity).strip()))
    ]

    chips: list[str] = [f"years {ys}–{ye}"]
    if len(list(controls.series_select.value or [])) > cq.MAX_SERIES:
        chips.append(f"capped at {cq.MAX_SERIES} series")
    for sel in fetch_sels:
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
    notes_block = (
        mo.md(" · ".join(f"_{n}_" for n in notes)) if notes else mo.md("")
    )

    raw = cq.fetch_monthly(conn, fetch_sels, year_start=ys, year_end=ye)
    norm = cq.normalize_pct_of_max(raw)
    fig = panel_charts.normalized_overlay(
        px,
        norm,
        title="Monthly activity (% of each series' max)",
        empty_title="Select up to 6 series (pick entities where required)",
    )

    corr = cq.correlation_matrix(norm)
    corr_fig = panel_charts.correlation_heatmap(
        px,
        corr,
        title="Series shape correlation (Pearson on % of max)",
        empty_title="Need ≥2 series with overlapping months",
    )
    corr_table = pd.DataFrame()
    if not corr.empty:
        corr_table = corr.reset_index().rename(columns={"index": "series"}).round(3)

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

    n_series = int(norm["series_label"].nunique()) if not norm.empty else 0
    corr_section: list[Any] = [
        mo.md("### Correlations"),
        mo.md(
            f"Pearson **r** on aligned monthly **% of max** shapes "
            f"(need ≥{cq.MIN_CORR_OVERLAP} overlapping months; "
            "constant series → blank)."
        ),
    ]
    if n_series >= 2 and not corr.empty:
        corr_section.extend(
            [
                mo.ui.plotly(corr_fig),
                mo.ui.table(corr_table) if not corr_table.empty else mo.md(""),
            ]
        )
    else:
        corr_section.append(
            mo.md("_Select at least two series with overlapping months._")
        )

    return mo.vstack(
        [
            mo.md("## Compare"),
            mo.md(
                "Multiviewer for monthly activity across sources and threads. "
                "Each series is scaled to **% of its own maximum** in the "
                "selected year window so different units line up; the "
                "correlation matrix measures how those shapes move together."
            ),
            filter_row,
            entity_block,
            chip_row,
            notes_block,
            mo.md("### Normalized overlay"),
            mo.ui.plotly(fig),
            *corr_section,
            mo.md("### Raw monthly values"),
            mo.ui.table(table_df) if not table_df.empty else mo.md("_No data_"),
        ],
        gap=0.5,
    )
