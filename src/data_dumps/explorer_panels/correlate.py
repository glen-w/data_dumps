"""Cross-source Correlations explorer tab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import correlation_queries as crq

from . import charts as panel_charts

_PRESET_LABELS = {
    crq.PRESET_LIFE_RHYTHM: "Life rhythm",
    crq.PRESET_COMMS: "Comms",
    crq.PRESET_SLEEP_BODY: "Sleep & body",
    crq.PRESET_CUSTOM: "Custom (all totals)",
}


@dataclass
class CorrelateControls:
    year_start: Any
    year_end: Any
    preset: Any
    metric_select: Any
    focus_a: Any
    focus_b: Any
    grain: Any


def make_correlate_controls(
    mo: Any,
    bounds: dict[str, Any],
    available_metrics: list[crq.MetricSpec],
) -> CorrelateControls:
    ys = int(bounds.get("min_year") or 2020)
    ye = int(bounds.get("max_year") or ys)
    if ys > ye:
        ys, ye = ye, ys
    stop = ye if ye > ys else ys + 1

    default_ids, focus = crq.apply_preset(crq.PRESET_LIFE_RHYTHM, available_metrics)
    default_preset = crq.PRESET_LIFE_RHYTHM
    if len(default_ids) < 2:
        default_ids, focus = crq.apply_preset(crq.PRESET_CUSTOM, available_metrics)
        default_preset = crq.PRESET_CUSTOM

    options = {m.id: m.label for m in available_metrics}
    focus_opts = {"": "(auto strongest)", **options}
    focus_a = focus[0] if focus else ""
    focus_b = focus[1] if focus else ""

    ms_kwargs: dict[str, Any] = {
        "options": options,
        "value": default_ids,
        "label": f"Metrics (max {crq.MAX_METRICS})",
    }
    try:
        metric_select = mo.ui.multiselect(**ms_kwargs, max_selections=crq.MAX_METRICS)
    except TypeError:
        metric_select = mo.ui.multiselect(**ms_kwargs)

    return CorrelateControls(
        year_start=mo.ui.slider(
            start=ys, stop=stop, value=ys, label="From year", show_value=True
        ),
        year_end=mo.ui.slider(
            start=ys, stop=stop, value=ye, label="To year", show_value=True
        ),
        preset=mo.ui.dropdown(
            options=_PRESET_LABELS,
            value=default_preset,
            label="Preset",
        ),
        metric_select=metric_select,
        focus_a=mo.ui.dropdown(
            options=focus_opts,
            value=focus_a if focus_a in focus_opts else "",
            label="Focus A",
        ),
        focus_b=mo.ui.dropdown(
            options=focus_opts,
            value=focus_b if focus_b in focus_opts else "",
            label="Focus B",
        ),
        grain=mo.ui.dropdown(
            options={"daily": "Daily (default)", "monthly": "Monthly"},
            value="daily",
            label="Grain",
        ),
    )


def render_correlate_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: CorrelateControls,
) -> Any:
    available = crq.list_available_metrics(conn)
    if len(available) < 2:
        return mo.md(
            "Need at least **two** ingested sources with daily/monthly activity "
            "to compute correlations. Ingest more dumps, then reopen."
        )

    ys = int(controls.year_start.value)
    ye = int(controls.year_end.value)
    ymin = int(bounds.get("min_year") or ys)
    ymax = int(bounds.get("max_year") or ye)
    ys = min(max(ys, ymin), ymax)
    ye = min(max(ye, ymin), ymax)
    if ys > ye:
        ys, ye = ye, ys

    grain = str(controls.grain.value or "daily")
    if grain not in ("daily", "monthly"):
        grain = "daily"

    preset = str(controls.preset.value or crq.PRESET_CUSTOM)
    # Dropdown may surface the display label depending on Marimo version.
    for key, label in _PRESET_LABELS.items():
        if preset == label:
            preset = key
            break
    avail_ids = {m.id for m in available}
    labels = crq.label_map(available)

    selected = list(controls.metric_select.value or [])
    # Widgets can return labels; map back to ids.
    label_to_id = {m.label: m.id for m in available}
    selected = [label_to_id.get(x, x) for x in selected]

    if len(selected) < 2:
        selected, _ = crq.apply_preset(preset, available)
    if len(selected) < 2:
        selected, _ = crq.apply_preset(crq.PRESET_CUSTOM, available)

    selected = [mid for mid in selected if mid in avail_ids][: crq.MAX_METRICS]
    # Drop metrics that don't support the chosen grain.
    selected = [
        mid
        for mid in selected
        if (spec := crq.metric_by_id(mid)) is not None
        and (
            (grain == "daily" and spec.supports_daily)
            or (grain == "monthly" and spec.supports_monthly)
        )
    ]
    if len(selected) < 2 and grain == "daily":
        # Last resort: any available daily metrics.
        selected = [
            m.id for m in available if m.supports_daily
        ][: crq.MAX_METRICS]

    if len(selected) < 2:
        return mo.vstack(
            [
                mo.md("## Correlations"),
                mo.hstack(
                    [
                        controls.year_start,
                        controls.year_end,
                        controls.preset,
                        controls.grain,
                        controls.metric_select,
                    ],
                    gap=1,
                    wrap=True,
                ),
                mo.md("_Select at least two metrics that support the chosen grain._"),
            ],
            gap=0.5,
        )

    long_df = crq.fetch_panel(
        conn, selected, year_start=ys, year_end=ye, grain=grain  # type: ignore[arg-type]
    )
    wide = crq.pivot_panel(long_df)
    # Relabel matrix axes for heatmap readability.
    label_cols = {mid: labels.get(mid, mid) for mid in wide.columns}

    mat = crq.correlation_matrix(wide, grain=grain)  # type: ignore[arg-type]
    mat_labeled = mat.rename(index=label_cols, columns=label_cols) if not mat.empty else mat

    pairs = crq.rank_pairs(wide, grain=grain, labels=labels)  # type: ignore[arg-type]

    # Focus pair: user override or top ranked.
    fa = str(controls.focus_a.value or "").strip()
    fb = str(controls.focus_b.value or "").strip()
    if fa and fb and fa in wide.columns and fb in wide.columns and fa != fb:
        focus_a, focus_b = fa, fb
    elif not pairs.empty:
        focus_a, focus_b = str(pairs.iloc[0]["a"]), str(pairs.iloc[0]["b"])
    elif len(selected) >= 2:
        focus_a, focus_b = selected[0], selected[1]
    else:
        focus_a = focus_b = ""

    scatter = (
        crq.aligned_pair(wide, focus_a, focus_b)
        if focus_a and focus_b
        else crq.aligned_pair(wide, "", "")
    )

    max_lag = crq.MAX_LAG_DAILY if grain == "daily" else crq.MAX_LAG_MONTHLY
    min_n = crq.MIN_N_DAILY if grain == "daily" else crq.MIN_N_MONTHLY
    lag_freq = "D" if grain == "daily" else "MS"
    best_lag = None
    best_r = None
    lag_df = None
    if focus_a and focus_b and focus_a in wide.columns and focus_b in wide.columns:
        lag_df, best_lag, best_r = crq.lag_scan(
            wide[focus_a],
            wide[focus_b],
            max_lag=max_lag,
            min_n=min_n,
            freq=lag_freq,
        )

    z_long = crq.zscore_long(
        long_df, [focus_a, focus_b] if focus_a and focus_b else selected[:2]
    )

    n_days = int(wide.shape[0]) if not wide.empty else 0
    strongest = ""
    if not pairs.empty:
        top = pairs.iloc[0]
        strongest = (
            f"Strongest: **{top['a_label']}** × **{top['b_label']}** "
            f"(r={top['r_pearson']:.2f}, n={int(top['n'])})"
        )

    fig_mat = panel_charts.corr_heatmap(
        px,
        mat_labeled,
        title="Pearson correlation matrix",
        empty_title="Insufficient overlap between metrics",
    )
    fig_scatter = panel_charts.scatter_pair(
        px,
        scatter,
        title=f"Focus: {labels.get(focus_a, focus_a)} vs {labels.get(focus_b, focus_b)}",
        x_title=labels.get(focus_a, focus_a),
        y_title=labels.get(focus_b, focus_b),
        empty_title="Pick two metrics with overlapping days",
    )
    fig_z = panel_charts.zscore_overlay(
        px,
        z_long,
        title="Focus pair (z-score)",
        empty_title="No focus series",
    )
    fig_lag = panel_charts.lag_bars(
        px,
        lag_df if lag_df is not None else pd.DataFrame(),
        title=f"Lag scan (±{max_lag} {'days' if grain == 'daily' else 'months'})",
        empty_title="Not enough overlap for lag scan",
    )

    lag_caption = (
        f"Best lag = **{best_lag}** ({'days' if grain == 'daily' else 'months'}), "
        f"r={best_r:.2f} (positive lag → B delayed vs A)."
        if best_lag is not None and best_r is not None
        else "_Lag scan: insufficient overlap._"
    )

    pairs_view = pairs.drop(columns=["abs_r"], errors="ignore")
    if not pairs_view.empty:
        pairs_view = pairs_view.round({"r_pearson": 3, "r_spearman": 3})

    filter_row = mo.hstack(
        [
            controls.year_start,
            controls.year_end,
            controls.preset,
            controls.grain,
            controls.metric_select,
        ],
        gap=1,
        wrap=True,
    )
    focus_row = mo.hstack(
        [controls.focus_a, controls.focus_b],
        gap=1,
        wrap=True,
    )

    return mo.vstack(
        [
            mo.md("## Correlations"),
            mo.md(
                "Do sources move together? Pearson **r** on **overlapping** "
                f"{'days' if grain == 'daily' else 'months'} "
                f"(min n={min_n}; no zero-fill). Spearman shown in the pairs table. "
                "Compare tab remains the place for % of max shape overlays."
            ),
            filter_row,
            focus_row,
            mo.md(
                f"**Window** {ys}–{ye} · **{len(selected)}** metrics · "
                f"**{n_days}** time keys · {strongest or '_no pairs above min n_'}"
            ),
            mo.md("### Correlation matrix"),
            mo.ui.plotly(fig_mat),
            mo.md("### Top pairs"),
            mo.ui.table(pairs_view)
            if not pairs_view.empty
            else mo.md("_No pairs meet the minimum overlap._"),
            mo.md("### Focus pair"),
            mo.ui.plotly(fig_scatter),
            mo.ui.plotly(fig_z),
            mo.md("### Lag scan"),
            mo.md(lag_caption),
            mo.ui.plotly(fig_lag),
            mo.md(
                "_Methods: inner join on time keys; diagonal r=1; "
                "blank cells = below min n or undefined._"
            ),
        ],
        gap=0.5,
    )
