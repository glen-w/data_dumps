"""Sleep as Android explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import sleep_queries as slq

from . import charts as panel_charts


@dataclass
class SleepControls:
    year_start: Any
    year_end: Any
    tag_select: Any
    min_rating: Any
    compare: Any
    act_nights: Any


def make_sleep_controls(mo: Any, bounds: dict[str, Any]) -> SleepControls:
    return SleepControls(
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
        tag_select=mo.ui.multiselect(
            options=bounds.get("tags") or [], value=[], label="Tags"
        ),
        min_rating=mo.ui.slider(
            start=0.0,
            stop=5.0,
            step=0.5,
            value=0.0,
            label="Min rating",
            show_value=True,
        ),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        act_nights=mo.ui.slider(
            start=1,
            stop=10,
            step=1,
            value=5,
            label="Actigraphy nights",
            show_value=True,
        ),
    )


def render_sleep_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: SleepControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = slq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
        tags=controls.tag_select.value or None,
        min_rating=controls.min_rating.value,
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = slq.scoreboard(
        conn, filters, compare_previous=bool(controls.compare.value)
    )
    streak_df = slq.streak_stats(conn, filters)
    regular_df = slq.regularity_stats(conn, filters)
    monthly_df = slq.monthly_hours(conn, filters)
    hours_df = slq.hours_over_time(conn, filters)
    snore_df = slq.snore_noise_monthly(conn, filters)
    bed_df = slq.bedtime_distribution(conn, filters)
    wake_df = slq.wake_distribution(conn, filters)
    weekday_df = slq.weekday_hours(conn, filters)
    circ_df = slq.circadian_heatmap(conn, filters)
    cal_df = slq.calendar_daily(conn, filters)
    events_df = slq.event_type_counts(conn, filters)
    stages_df = slq.stage_event_mix(conn, filters)
    tags_df = slq.tag_breakdown(conn, filters)
    best_df, worst_df = slq.best_worst_nights(conn, filters)
    n_act = int(controls.act_nights.value or 1)
    act_df = slq.sample_actigraphy(conn, filters, limit_sessions=n_act)
    hr_df = slq.session_heart_rate(conn, filters, limit_sessions=n_act)
    nightly_hr_df = slq.nightly_heart_rate(conn, filters)
    alarm_df = slq.alarm_vs_wake(conn, filters)
    alarm_cfg_df = slq.alarm_summary(conn)
    late_df = slq.late_night_spotify_vs_sleep(conn, filters)
    late_bucket_df = slq.late_night_spotify_buckets(conn, filters)

    if snore_df.empty:
        fig_snore = px.line(title="No snore / noise data")
    else:
        fig_snore = px.line(
            snore_df,
            x="month",
            y=["avg_snore", "snore_nights_pct"],
            title="Monthly snore (avg) and % nights with snoring",
            labels={"value": "value", "variable": "metric"},
        )
    fig_noise = (
        px.line(snore_df, x="month", y="avg_noise", title="Monthly average noise")
        if not snore_df.empty
        else px.line(title="No noise data")
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circ_df,
        z="nights",
        dow_labels=dow_labels,
        title="Nights by weekday × bedtime hour",
        empty_title="No bedtime heatmap",
        xaxis_title="Bedtime hour",
    )

    fig_month = (
        px.line(
            monthly_df,
            x="month",
            y=["avg_hours", "avg_deep_hours"],
            title="Monthly average hours / deep hours",
        )
        if not monthly_df.empty
        else px.line(title="No monthly sleep data")
    )
    fig_rating = (
        px.line(monthly_df, x="month", y="avg_rating", title="Monthly average rating")
        if not monthly_df.empty
        else px.line(title="No ratings")
    )
    fig_hours = (
        px.scatter(
            hours_df,
            x="day",
            y="hours",
            color="rating",
            title="Hours slept per night",
            opacity=0.7,
        )
        if not hours_df.empty
        else px.scatter(title="No nights")
    )
    fig_bed = (
        px.bar(bed_df, x="hour", y="nights", title="Bedtime hour distribution")
        if not bed_df.empty
        else px.bar(title="No bedtime data")
    )
    fig_wake = (
        px.bar(wake_df, x="hour", y="nights", title="Wake hour distribution")
        if not wake_df.empty
        else px.bar(title="No wake data")
    )
    if weekday_df.empty:
        fig_dow = px.bar(title="No weekday data")
    else:
        dow = weekday_df.copy()
        dow["dow_label"] = dow["dow"].map(dow_labels)
        fig_dow = px.bar(
            dow, x="dow_label", y="avg_hours", title="Average hours by weekday"
        )
    fig_cal = panel_charts.iso_week_calendar(
        px,
        cal_df,
        z="hours",
        title="Hours slept (weekday × ISO week)",
        empty_title="No sleep calendar",
    )
    fig_events = (
        px.bar(
            events_df,
            x="events",
            y="event_type",
            orientation="h",
            title="Top sleep events",
        )
        if not events_df.empty
        else px.bar(title="No events")
    )
    fig_stages = (
        px.bar(
            stages_df,
            x="year",
            y="events",
            color="event_type",
            barmode="stack",
            title="Stage events by year",
        )
        if not stages_df.empty
        else px.bar(title="No stage events")
    )
    fig_tags = (
        px.bar(tags_df, x="nights", y="tag", orientation="h", title="Nights by tag")
        if not tags_df.empty
        else px.bar(title="No tags")
    )
    if act_df.empty:
        fig_act = px.line(title="No actigraphy for the selected nights")
    else:
        act = act_df.copy()
        act["day"] = act["day"].astype(str)
        fig_act = px.line(
            act,
            x="bucket_label",
            y="value",
            facet_row="day",
            title=f"Actigraphy — latest {act['day'].nunique()} night(s) in range",
        )
        fig_act.update_layout(
            xaxis_title="Time bucket",
            height=max(320, 180 * act["day"].nunique()),
        )
        fig_act.update_yaxes(matches=None, title="Intensity")
        fig_act.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

    # Mi Band HR overlay: same nights, minutes since bedtime.
    if slq.has_miband_hr(conn):
        if hr_df.empty:
            fig_hr = px.line(title="No Mi Band readings inside the selected nights")
        else:
            hr = hr_df.copy()
            hr["day"] = hr["day"].astype(str)
            fig_hr = px.line(
                hr,
                x="minutes_in",
                y="rate",
                color="day",
                title="Heart rate during the same nights (Mi Band)",
            )
            fig_hr.update_layout(xaxis_title="Minutes since bedtime", yaxis_title="bpm")
        if nightly_hr_df.empty:
            fig_night_hr = px.scatter(title="No nights with ≥5 HR readings")
        else:
            fig_night_hr = px.scatter(
                nightly_hr_df,
                x="avg_bpm",
                y="hours",
                color="rating",
                hover_data=["day", "min_bpm", "readings"],
                title="Nightly avg HR vs hours slept",
            )
            fig_night_hr.update_layout(xaxis_title="Avg bpm", yaxis_title="Hours")
        hr_block = mo.vstack(
            [
                mo.md("### Heart rate overlay (Mi Band)"),
                mo.vstack([mo.ui.plotly(fig_hr), mo.ui.plotly(fig_night_hr)], gap=1),
            ],
            gap=0.5,
        )
    else:
        hr_block = mo.md(
            "_HR overlay needs `miband.heart_rate`. Stop this notebook, then: "
            "`uv run ingest ~/Documents/data_dumps_raw/miband_hr/heart_rate.csv`_"
        )

    # Alarms: scheduled vs actual wake.
    if alarm_df.empty:
        fig_alarm = px.histogram(title="No scheduled-alarm nights in range")
    else:
        fig_alarm = px.histogram(
            alarm_df,
            x="wake_minus_alarm_min",
            nbins=40,
            title="Wake time minus alarm (minutes; negative = woke early)",
        )
        fig_alarm.update_layout(xaxis_title="Minutes", yaxis_title="Nights")
    alarm_children: list[Any] = [
        mo.md("### Alarms"),
        mo.ui.plotly(fig_alarm),
    ]
    if not alarm_cfg_df.empty:
        alarm_children.append(
            mo.vstack(
                [
                    mo.md("**Configured alarms (alarms.json)**"),
                    mo.ui.table(alarm_cfg_df),
                ]
            )
        )
    alarm_block = mo.vstack(alarm_children, gap=0.5)

    # Cross-source: late-evening Spotify vs sleep quality.
    if slq.has_spotify_plays(conn):
        if late_df.empty:
            fig_late = px.scatter(title="No overlapping Spotify / sleep nights")
        else:
            fig_late = px.scatter(
                late_df,
                x="late_spotify_hours",
                y="hours",
                color="rating",
                hover_data=["day", "deep_hours"],
                opacity=0.6,
                title="Spotify after 22:00 (same evening) vs hours slept",
            )
            fig_late.update_layout(
                xaxis_title="Late-evening listening (h)", yaxis_title="Hours slept"
            )
        if late_bucket_df.empty:
            fig_late_bucket = px.bar(title="No late-listening buckets")
        else:
            fig_late_bucket = px.bar(
                late_bucket_df,
                x="bucket",
                y="avg_rating",
                hover_data=["nights", "avg_hours", "avg_deep_hours"],
                title="Average sleep rating by late-evening listening",
            )
            fig_late_bucket.update_layout(
                xaxis_title="Listening after 22:00", yaxis_title="Avg rating"
            )
        late_block = mo.vstack(
            [
                mo.md("### Late-night Spotify × sleep"),
                mo.vstack(
                    [mo.ui.plotly(fig_late), mo.ui.plotly(fig_late_bucket)], gap=1
                ),
                mo.ui.table(late_bucket_df),
            ],
            gap=0.5,
        )
    else:
        late_block = mo.md(
            "_Late-night listening chart needs `spotify.plays` in the same warehouse._"
        )

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Sleep as Android\n"
                f"{span}. Sessions, stage events, and actigraphy from merged exports."
            ),
            mo.hstack(
                [
                    controls.year_start,
                    controls.year_end,
                    controls.tag_select,
                    controls.min_rating,
                ],
                justify="start",
                gap=1,
            ),
            mo.hstack([controls.compare, controls.act_nights], justify="start", gap=1),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md(
                "**Regularity** — bedtime/wake spread (stddev, hours) and social jet lag "
                "(Fri/Sat nights minus weeknights)."
            ),
            mo.ui.table(regular_df),
            mo.md("### Longitudinal"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_month),
                    mo.ui.plotly(fig_rating),
                    mo.ui.plotly(fig_hours),
                ],
                gap=1,
            ),
            mo.vstack([mo.ui.plotly(fig_snore), mo.ui.plotly(fig_noise)], gap=1),
            mo.md("### Circadian"),
            mo.vstack(
                [mo.ui.plotly(fig_bed), mo.ui.plotly(fig_wake), mo.ui.plotly(fig_dow)],
                gap=1,
            ),
            mo.ui.plotly(fig_circ),
            mo.md("### Calendar"),
            mo.ui.plotly(fig_cal),
            mo.md("### Events · stages · tags"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_events),
                    mo.ui.plotly(fig_stages),
                    mo.ui.plotly(fig_tags),
                ],
                gap=1,
            ),
            mo.md("### Actigraphy"),
            mo.ui.plotly(fig_act),
            hr_block,
            alarm_block,
            late_block,
            mo.md("### Best / shortest nights"),
            mo.vstack([mo.ui.table(best_df), mo.ui.table(worst_df)], gap=1),
        ],
        gap=0.5,
    )
