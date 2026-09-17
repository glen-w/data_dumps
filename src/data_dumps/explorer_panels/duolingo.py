"""Duolingo explorer tab controls and panel (light depth)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import duolingo_queries as duoq

from . import charts as panel_charts


@dataclass
class DuolingoControls:
    year_start: Any
    year_end: Any
    compare: Any


def make_duolingo_controls(mo: Any, bounds: dict[str, Any]) -> DuolingoControls:
    return DuolingoControls(
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


def render_duolingo_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: DuolingoControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = duoq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = duoq.scoreboard(
        conn, filters, compare_previous=bool(controls.compare.value)
    )
    acct_df = duoq.account_summary(conn)
    friends_df = duoq.friends_snapshot(conn)
    langs_df = duoq.languages_table(conn)
    tier_df = duoq.leaderboard_tier_timeline(conn, filters)
    monthly_df = duoq.progress_monthly(conn, filters)
    by_lang_df = duoq.progress_by_language(conn, filters)
    inv_df = duoq.inventory_by_type_monthly(conn, filters)
    cal_df = duoq.calendar_daily_progress(conn, filters)
    circ_df = duoq.weekday_heatmap(conn, filters)

    fig_points = (
        px.bar(
            langs_df,
            x="points",
            y="learning_language",
            orientation="h",
            title="Languages by XP (points)",
        )
        if not langs_df.empty
        else px.bar(title="No languages")
    )
    if not langs_df.empty:
        fig_points.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_tier = (
        px.line(
            tier_df,
            x="ts_local",
            y="tier",
            title="League tier over time",
            markers=True,
        )
        if not tier_df.empty
        else px.line(title="No leaderboard rows")
    )

    fig_monthly = (
        px.bar(
            monthly_df,
            x="year_month",
            y="events",
            title="Progress events by month",
        )
        if not monthly_df.empty
        else px.bar(title="No progress events in range")
    )

    fig_by_lang = (
        px.bar(
            by_lang_df,
            x="events",
            y="language",
            orientation="h",
            title="Progress events by language pair",
        )
        if not by_lang_df.empty
        else px.bar(title="No language breakdown")
    )
    if not by_lang_df.empty:
        fig_by_lang.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_inv = (
        px.bar(
            inv_df,
            x="year_month",
            y="buys",
            color="item_type",
            title="Inventory purchases by item type",
            barmode="stack",
        )
        if not inv_df.empty
        else px.bar(title="No inventory buys in range")
    )

    fig_cal = panel_charts.iso_week_calendar(
        px,
        cal_df,
        z="events",
        title="Progress events (weekday × ISO week)",
        empty_title="No progress calendar",
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circ_df,
        z="events",
        dow_labels=dow_labels,
        title="Progress events by weekday × hour (Europe/Rome)",
        empty_title="No circadian data",
        xaxis_title="",
        yaxis_title="",
    )

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Duolingo\n"
                f"{span}. Light view: XP snapshot, league tiers, tree progress "
                f"events, inventory buys. Tree events may be recent-only; "
                f"languages.csv columns are often sparse."
            ),
            mo.hstack(
                [controls.year_start, controls.year_end, controls.compare],
                justify="start",
                gap=1,
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.md("### Account / friends"),
            mo.ui.table(acct_df),
            mo.ui.table(friends_df),
            mo.md("### Languages (XP)"),
            mo.ui.plotly(fig_points),
            mo.ui.table(langs_df),
            mo.md("### League tier"),
            mo.ui.plotly(fig_tier),
            mo.md("### Progress events"),
            mo.vstack(
                [mo.ui.plotly(fig_monthly), mo.ui.plotly(fig_by_lang)],
                gap=1,
            ),
            mo.md("### Inventory"),
            mo.ui.plotly(fig_inv),
            mo.md("### Rhythm"),
            mo.vstack(
                [mo.ui.plotly(fig_cal), mo.ui.plotly(fig_circ)],
                gap=1,
            ),
        ],
        gap=0.5,
    )
