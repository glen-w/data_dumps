"""Google Takeout explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import google_queries as gq
from data_dumps.geo import attach_country_iso3

from . import charts as panel_charts


@dataclass
class GoogleControls:
    year_start: Any
    year_end: Any
    calendar: Any
    exclude_noise: Any
    compare: Any


def make_google_controls(mo: Any, bounds: dict[str, Any]) -> GoogleControls:
    calendars = ["(all)", *list(bounds.get("calendars") or [])]
    return GoogleControls(
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
        calendar=mo.ui.dropdown(
            options=calendars,
            value="(all)",
            label="Calendar",
        ),
        exclude_noise=mo.ui.checkbox(
            label="Hide noise calendars (Sleep / NBA / Daily briefing)",
            value=True,
        ),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
    )


def render_google_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: GoogleControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = gq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
        calendar=controls.calendar.value,
        exclude_noise=bool(controls.exclude_noise.value),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = gq.scoreboard(
        conn, filters, compare_previous=bool(controls.compare.value)
    )
    streak_df = gq.streak_stats(conn, filters)
    surfaces = gq.surfaces_monthly(conn, filters)
    cal_hours = gq.calendar_hours_monthly(conn, filters)
    cal_stack = gq.calendar_stacked_monthly(conn, filters)
    cal_monthly = gq.calendar_monthly(conn, filters)
    cal_by_name = gq.calendar_by_name(conn, filters)
    cal_top = gq.calendar_top_summaries(conn, filters)
    cal_kind = gq.calendar_kind_mix(conn, filters)
    scatter_df = gq.duration_vs_hour_scatter(conn, filters)
    summary_bump = gq.summary_rank_bump(conn, filters)
    circ_df = gq.weekday_heatmap(conn, filters)
    cal_daily = gq.calendar_daily(conn, filters)
    photos_m = gq.photos_monthly(conn, filters)
    photos_alb = gq.photos_by_album(conn, filters)
    photos_d = gq.photos_daily(conn, filters)
    photos_circ = gq.photos_weekday_heatmap(conn, filters)
    maps_country = gq.maps_by_country(conn, filters)
    maps_m = gq.maps_monthly(conn, filters)
    maps_reviews = gq.maps_reviews_table(conn, filters)
    maps_ratings = gq.maps_rating_mix(conn, filters)
    maps_reviews_m = gq.maps_reviews_monthly(conn, filters)
    forgotten = gq.forgotten_places(conn, filters)
    comebacks = gq.comeback_places(conn, filters)
    bump_df = gq.country_rank_bump(conn, filters)
    play_m = gq.play_installs_monthly(conn, filters)
    play_apps = gq.play_top_apps(conn, filters)
    play_dev = gq.play_by_device(conn, filters)
    forgotten_apps = gq.forgotten_apps(conn, filters)
    play_purchases_m = gq.play_purchases_monthly(conn, filters)
    play_totals = gq.play_purchase_totals(conn, filters)
    play_lib_m = gq.play_library_monthly(conn, filters)
    play_lib_top = gq.play_library_top(conn, filters)
    play_sub_states = gq.play_subscription_states(conn, filters)
    play_subs = gq.play_subscriptions_table(conn, filters)
    act_prod = gq.activity_by_product(conn, filters)
    act_m = gq.activity_monthly(conn, filters)
    act_action = gq.activity_by_action(conn, filters)
    act_stack = gq.activity_product_monthly(conn, filters)
    act_titles = gq.activity_top_titles(conn, filters)
    act_circ = gq.activity_weekday_heatmap(conn, filters)
    tasks_tl = gq.tasks_timeline(conn, filters)
    footprint = gq.footprint_by_category(conn)
    saved = gq.saved_lists_summary(conn)
    saved_titles = gq.saved_place_titles(conn)
    tasks = gq.tasks_summary(conn)

    fig_surfaces = (
        px.area(
            surfaces,
            x="year_month",
            y="events",
            color="surface",
            title="Life chapters — events by surface",
        )
        if not surfaces.empty
        else px.area(title="No surface activity")
    )
    fig_hours = (
        px.bar(
            cal_hours,
            x="year_month",
            y="hours",
            title="Calendar hours by month (timed events, ≤24h)",
        )
        if not cal_hours.empty
        else px.bar(title="No timed hours")
    )
    fig_stack = (
        px.area(
            cal_stack,
            x="year_month",
            y="events",
            color="calendar",
            title="Calendar stacked by name",
        )
        if not cal_stack.empty
        else px.area(title="No calendar stack")
    )
    fig_cal_m = (
        px.bar(
            cal_monthly, x="year_month", y="events", title="Calendar events by month"
        )
        if not cal_monthly.empty
        else px.bar(title="No calendar events")
    )
    fig_cal_name = (
        px.bar(
            cal_by_name,
            x="events",
            y="calendar",
            orientation="h",
            title="Events by calendar",
        )
        if not cal_by_name.empty
        else px.bar(title="No calendars")
    )
    if not cal_by_name.empty:
        fig_cal_name.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_top = (
        px.bar(
            cal_top.head(15),
            x="events",
            y="summary",
            orientation="h",
            title="Top event titles",
        )
        if not cal_top.empty
        else px.bar(title="No titles")
    )
    if not cal_top.empty:
        fig_top.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_kind = (
        px.pie(cal_kind, names="kind", values="events", title="Timed vs all-day")
        if not cal_kind.empty
        else px.pie(title="No calendar kinds")
    )

    fig_scatter = (
        px.scatter(
            scatter_df,
            x="hour",
            y="duration_hours",
            color="calendar_name",
            hover_data=["summary"],
            title="Duration × hour scatter (timed, ≤12h)",
        )
        if not scatter_df.empty
        else px.scatter(title="No duration pairs")
    )
    fig_summary_bump = (
        px.line(
            summary_bump,
            x="year",
            y="rnk",
            color="summary",
            markers=True,
            title="Summary title rank bump",
        )
        if not summary_bump.empty
        else px.line(title="No summary ranks")
    )
    if not summary_bump.empty:
        fig_summary_bump.update_yaxes(autorange="reversed", title="rank")

    fig_circ = panel_charts.circadian_heatmap(
        px,
        circ_df,
        z="events",
        dow_labels=dow_labels,
        title="Calendar rhythm (weekday × hour, Europe/Paris)",
        empty_title="No circadian data",
        xaxis_title="",
        yaxis_title="",
    )
    fig_cal = panel_charts.iso_week_calendar(
        px,
        cal_daily,
        z="events",
        title="Calendar events (weekday × ISO week)",
        empty_title="No calendar days",
    )

    fig_photos = (
        px.bar(photos_m, x="year_month", y="photos", title="Photos taken by month")
        if not photos_m.empty
        else px.bar(title="No photo metadata")
    )
    fig_alb = (
        px.bar(
            photos_alb,
            x="photos",
            y="album",
            orientation="h",
            title="Photos by album",
        )
        if not photos_alb.empty
        else px.bar(title="No albums")
    )
    if not photos_alb.empty:
        fig_alb.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_photos_cal = panel_charts.iso_week_calendar(
        px,
        (
            photos_d.rename(columns={"photos": "events"})
            if not photos_d.empty
            else photos_d
        ),
        z="events",
        title="Photos (weekday × ISO week)",
        empty_title="No photo days",
    )
    fig_photos_circ = panel_charts.circadian_heatmap(
        px,
        (
            photos_circ.rename(columns={"photos": "events"})
            if not photos_circ.empty
            else photos_circ
        ),
        z="events",
        dow_labels=dow_labels,
        title="Photo circadian (weekday × hour)",
        empty_title="No photo times",
        xaxis_title="",
        yaxis_title="",
    )

    fig_ratings = (
        px.bar(
            maps_ratings,
            x="rating",
            y="reviews",
            title="Maps review ratings",
        )
        if not maps_ratings.empty
        else px.bar(title="No ratings")
    )
    fig_reviews_m = (
        px.bar(
            maps_reviews_m,
            x="year_month",
            y="reviews",
            title="Maps reviews by month",
            hover_data=["avg_rating"],
        )
        if not maps_reviews_m.empty
        else px.bar(title="No review months")
    )
    fig_maps_m = (
        px.bar(maps_m, x="year_month", y="saves", title="Map saves by month")
        if not maps_m.empty
        else px.bar(title="No map saves")
    )
    maps_geo = attach_country_iso3(maps_country, code_col="country_code")
    fig_country = panel_charts.country_choropleth(
        px,
        maps_geo,
        color="saves",
        hover_name="country_code",
        title="Saved places by country",
        empty_title="No country codes to map",
    )
    fig_bump = (
        px.line(
            bump_df,
            x="year",
            y="rnk",
            color="country_code",
            markers=True,
            title="Country rank bump (map saves)",
        )
        if not bump_df.empty
        else px.line(title="No country ranks")
    )
    if not bump_df.empty:
        fig_bump.update_yaxes(autorange="reversed", title="rank")

    fig_play = (
        px.bar(play_m, x="year_month", y="installs", title="Play installs by month")
        if not play_m.empty
        else px.bar(title="No installs")
    )
    fig_apps = (
        px.bar(
            play_apps.head(15),
            x="installs",
            y="app",
            orientation="h",
            title="Top Play apps (by install rows)",
        )
        if not play_apps.empty
        else px.bar(title="No apps")
    )
    if not play_apps.empty:
        fig_apps.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_dev = (
        px.pie(play_dev, names="device", values="installs", title="Installs by device")
        if not play_dev.empty
        else px.pie(title="No devices")
    )
    fig_lib = (
        px.area(
            play_lib_m,
            x="year_month",
            y="items",
            color="document_type",
            title="Play library acquisitions",
        )
        if not play_lib_m.empty
        else px.area(title="No library items")
    )
    fig_lib_top = (
        px.bar(
            play_lib_top.head(15),
            x="items",
            y="title",
            color="document_type",
            orientation="h",
            title="Play library titles",
        )
        if not play_lib_top.empty
        else px.bar(title="No library titles")
    )
    if not play_lib_top.empty:
        fig_lib_top.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_subs = (
        px.pie(
            play_sub_states,
            names="state",
            values="subscriptions",
            title="Play subscription states",
        )
        if not play_sub_states.empty
        else px.pie(title="No subscriptions")
    )
    fig_purchases = (
        px.bar(
            play_purchases_m,
            x="year_month",
            y="purchases",
            title="Play purchases by month",
        )
        if not play_purchases_m.empty
        else px.bar(title="No purchases")
    )

    fig_act = (
        px.bar(act_m, x="year_month", y="events", title="My Activity by month")
        if not act_m.empty
        else px.bar(title="No activity")
    )
    fig_act_prod = (
        px.bar(
            act_prod,
            x="events",
            y="product",
            orientation="h",
            title="My Activity by product",
        )
        if not act_prod.empty
        else px.bar(title="No products")
    )
    if not act_prod.empty:
        fig_act_prod.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_act_action = (
        px.bar(
            act_action.head(20),
            x="events",
            y="action",
            color="product",
            orientation="h",
            title="My Activity by action",
        )
        if not act_action.empty
        else px.bar(title="No actions")
    )
    if not act_action.empty:
        fig_act_action.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_act_stack = (
        px.area(
            act_stack,
            x="year_month",
            y="events",
            color="product",
            title="My Activity stacked by product",
        )
        if not act_stack.empty
        else px.area(title="No activity stack")
    )
    fig_act_circ = panel_charts.circadian_heatmap(
        px,
        act_circ,
        z="events",
        dow_labels=dow_labels,
        title="Activity circadian (weekday × hour)",
        empty_title="No activity times",
        xaxis_title="",
        yaxis_title="",
    )

    fig_tasks_tl = None
    if not tasks_tl.empty:
        tasks_long = tasks_tl.melt(
            id_vars=["year_month"],
            value_vars=["completed", "open"],
            var_name="status",
            value_name="tasks",
        )
        fig_tasks_tl = px.bar(
            tasks_long,
            x="year_month",
            y="tasks",
            color="status",
            barmode="stack",
            title="Tasks timeline (completed vs open)",
        )

    footprint_plot = footprint.copy()
    if not footprint_plot.empty:
        footprint_plot["gib"] = footprint_plot["bytes"] / (1024**3)
    fig_foot = (
        px.bar(
            footprint_plot,
            x="gib",
            y="category",
            orientation="h",
            title="Takeout footprint (GiB by category)",
            hover_data=["files", "ingested_files"],
        )
        if not footprint_plot.empty
        else px.bar(title="No inventory")
    )
    if not footprint_plot.empty:
        fig_foot.update_layout(yaxis={"categoryorder": "total ascending"})

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    sections: list[Any] = [
        mo.md(
            f"# Google Takeout\n"
            f"{span}. Calendar, Photos, Maps, Play, Activity, Tasks. "
            f"GPS, emails, payment instruments, and access logs stay out of the warehouse."
        ),
        mo.hstack(
            [
                controls.year_start,
                controls.year_end,
                controls.calendar,
                controls.exclude_noise,
                controls.compare,
            ],
            justify="start",
            gap=1,
        ),
        chip_row,
        mo.md("## Scoreboard"),
        mo.ui.table(score_df),
        mo.md("## Streaks"),
        mo.ui.table(streak_df),
        mo.md("## Life chapters"),
        mo.ui.plotly(fig_surfaces),
        mo.md("## Calendar"),
        mo.md("### Hours"),
        mo.ui.plotly(fig_hours),
        mo.ui.plotly(fig_stack),
        mo.vstack([mo.ui.plotly(fig_cal_m), mo.ui.plotly(fig_cal_name)], gap=1),
        mo.ui.plotly(fig_top),
        mo.ui.plotly(fig_kind),
        mo.md("### Scatter"),
        mo.ui.plotly(fig_scatter),
        mo.ui.plotly(fig_summary_bump),
        mo.vstack([mo.ui.plotly(fig_circ), mo.ui.plotly(fig_cal)], gap=1),
        mo.md("## Photos"),
        mo.vstack([mo.ui.plotly(fig_photos), mo.ui.plotly(fig_alb)], gap=1),
        mo.ui.plotly(fig_photos_cal),
    ]
    if not photos_circ.empty:
        sections.append(mo.ui.plotly(fig_photos_circ))
    sections.extend(
        [
            mo.md("## Maps & saved places"),
            mo.vstack([mo.ui.plotly(fig_maps_m), mo.ui.plotly(fig_country)], gap=1),
            mo.ui.plotly(fig_bump),
            mo.md("### Ratings"),
            mo.vstack([mo.ui.plotly(fig_ratings), mo.ui.plotly(fig_reviews_m)], gap=1),
            mo.md("### Reviews"),
            (
                mo.ui.table(maps_reviews)
                if not maps_reviews.empty
                else mo.md("_No reviews_")
            ),
            mo.md("### Forgotten places (≥2y silent)"),
            mo.ui.table(forgotten) if not forgotten.empty else mo.md("_None_"),
            mo.md("### Comebacks"),
            mo.ui.table(comebacks) if not comebacks.empty else mo.md("_None_"),
            mo.md("## Play Store"),
            mo.vstack([mo.ui.plotly(fig_play), mo.ui.plotly(fig_dev)], gap=1),
            mo.ui.plotly(fig_apps),
            mo.ui.plotly(fig_purchases),
            mo.md("### Play library"),
            mo.vstack([mo.ui.plotly(fig_lib), mo.ui.plotly(fig_lib_top)], gap=1),
            mo.md("### Subscriptions"),
            mo.ui.plotly(fig_subs),
            (
                mo.ui.table(play_subs)
                if not play_subs.empty
                else mo.md("_No subscriptions_")
            ),
            (
                mo.ui.table(play_totals)
                if not play_totals.empty
                else mo.md("_No purchase totals_")
            ),
            mo.md("### Forgotten apps (≥2y silent)"),
            (
                mo.ui.table(forgotten_apps)
                if not forgotten_apps.empty
                else mo.md("_None_")
            ),
            mo.md("## My Activity"),
            mo.vstack([mo.ui.plotly(fig_act), mo.ui.plotly(fig_act_prod)], gap=1),
            mo.ui.plotly(fig_act_stack),
            mo.ui.plotly(fig_act_action),
            mo.md("### Titles"),
            mo.ui.table(act_titles) if not act_titles.empty else mo.md("_No titles_"),
            mo.ui.plotly(fig_act_circ),
        ]
    )
    if fig_tasks_tl is not None:
        sections.extend(
            [
                mo.md("## Tasks timeline"),
                mo.ui.plotly(fig_tasks_tl),
            ]
        )
    sections.extend(
        [
            mo.md("## Saved lists & tasks"),
            (
                mo.ui.table(saved_titles)
                if not saved_titles.empty
                else mo.md("_No saved titles_")
            ),
            (mo.ui.table(saved) if not saved.empty else mo.md("_No saved lists_")),
            mo.ui.table(tasks) if not tasks.empty else mo.md("_No tasks_"),
            mo.md("## Data footprint"),
            mo.ui.plotly(fig_foot),
            mo.ui.table(footprint) if not footprint.empty else mo.md("_No inventory_"),
        ]
    )
    return mo.vstack(sections, gap=0.5)
