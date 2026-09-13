"""Mi Band explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import miband_queries as mbq

from . import charts as panel_charts


@dataclass
class MiBandControls:
    year_start: Any
    year_end: Any
    compare: Any


def make_miband_controls(mo: Any, bounds: dict[str, Any]) -> MiBandControls:
    return MiBandControls(
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


def render_miband_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: MiBandControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = mbq.filter_from_widgets(
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

    score_df = mbq.scoreboard(
        conn, filters, compare_previous=bool(controls.compare.value)
    )
    daily_df = mbq.daily_avg(conn, filters)
    monthly_df = mbq.monthly_avg(conn, filters)
    hour_df = mbq.hour_of_day(conn, filters)
    heat_df = mbq.weekday_hour_heatmap(conn, filters)
    cal_df = mbq.calendar_daily(conn, filters)
    zone_df = mbq.zone_mix(conn, filters)
    zone_m_df = mbq.zone_monthly(conn, filters)
    rest_d = mbq.resting_hr_daily(conn, filters)
    rest_m = mbq.resting_hr_monthly(conn, filters)
    streak_df = mbq.high_hr_day_streaks(conn, filters)
    anom_df = mbq.anomalous_days(conn, filters)
    ext_df = mbq.extremes(conn, filters)
    sleep_ov = mbq.sleep_nightly_overlay(conn, filters)

    fig_daily = (
        px.line(daily_df, x="day", y="avg_bpm", title="Daily average heart rate")
        if not daily_df.empty
        else px.line(title="No HR readings")
    )
    fig_monthly = (
        px.line(
            monthly_df,
            x="year_month",
            y="avg_bpm",
            title="Monthly average heart rate",
            markers=True,
        )
        if not monthly_df.empty
        else px.line(title="No monthly data")
    )
    fig_hour = (
        px.bar(hour_df, x="hour", y="avg_bpm", title="Average BPM by hour of day")
        if not hour_df.empty
        else px.bar(title="No hourly data")
    )
    fig_heat = panel_charts.circadian_heatmap(
        px,
        heat_df,
        z="avg_bpm",
        dow_labels=dow_labels,
        title="Average BPM by weekday × hour",
        colorscale="Reds",
        empty_title="No heatmap data",
        xaxis_title="",
        yaxis_title="",
    )
    fig_cal = panel_charts.iso_week_calendar(
        px,
        cal_df,
        z="avg_bpm",
        title="Daily average BPM calendar",
        colorscale="Reds",
        empty_title="No calendar data",
        facet_by_year=True,
    )
    fig_zone = (
        px.pie(zone_df, names="rate_zone", values="readings", title="Rate zone mix")
        if not zone_df.empty
        else px.pie(title="No zone data")
    )
    fig_zone_m = (
        px.bar(
            zone_m_df,
            x="year_month",
            y="readings",
            color="rate_zone",
            title="Zone mix over time",
            barmode="stack",
        )
        if not zone_m_df.empty
        else px.bar(title="No zone timeline")
    )
    fig_rest_d = (
        px.line(
            rest_d,
            x="day",
            y="resting_bpm",
            title="Resting HR (hours 0–5)",
            markers=True,
        )
        if not rest_d.empty
        else px.line(title="No night-hour readings")
    )
    fig_rest_m = (
        px.line(
            rest_m,
            x="year_month",
            y="resting_bpm",
            title="Monthly resting HR",
            markers=True,
        )
        if not rest_m.empty
        else px.line(title="No monthly resting HR")
    )
    sleep_sections: list[Any] = []
    if not sleep_ov.empty:
        fig_sleep = px.scatter(
            sleep_ov,
            x="hours",
            y="avg_bpm",
            color="rating",
            title="Sleep hours × overnight avg BPM",
            hover_data=["day", "readings"],
        )
        sleep_sections = [
            mo.md("### Sleep overlay"),
            mo.ui.plotly(fig_sleep),
        ]

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Mi Band heart rate\n"
                f"{span}. One-off Mi Fit export (`dateTime, rate, rateZone`)."
            ),
            mo.hstack(
                [controls.year_start, controls.year_end, controls.compare],
                justify="start",
                gap=1,
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md("### Longitudinal"),
            mo.vstack([mo.ui.plotly(fig_daily), mo.ui.plotly(fig_monthly)], gap=1),
            mo.md("### Circadian · calendar"),
            mo.vstack(
                [mo.ui.plotly(fig_hour), mo.ui.plotly(fig_heat), mo.ui.plotly(fig_cal)],
                gap=1,
            ),
            mo.md("### Resting HR"),
            mo.vstack([mo.ui.plotly(fig_rest_d), mo.ui.plotly(fig_rest_m)], gap=1),
            mo.md("### Zones"),
            mo.vstack([mo.ui.plotly(fig_zone), mo.ui.plotly(fig_zone_m)], gap=1),
            mo.md("### Anomalies · streaks"),
            mo.ui.table(anom_df),
            *sleep_sections,
            mo.md("### Extremes"),
            mo.ui.table(ext_df),
        ],
        gap=0.5,
    )
