"""Ring explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import ring_queries as ringq
from data_dumps.geo import attach_city_coords

from . import charts as panel_charts


@dataclass
class RingControls:
    year_start: Any
    year_end: Any
    compare: Any


def make_ring_controls(mo: Any, bounds: dict[str, Any]) -> RingControls:
    return RingControls(
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


def render_ring_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: RingControls,
    dow_labels: dict[int, str],
) -> Any:
    del dow_labels  # reserved for future weekday heatmaps
    filters = ringq.filter_from_widgets(
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

    score_df = ringq.scoreboard(
        conn, filters, compare_previous=bool(controls.compare.value)
    )
    inv_df = ringq.inventory_summary(conn)
    devices_df = ringq.devices_table(conn)
    locations_df = ringq.locations_table(conn)
    loc_geo = attach_city_coords(locations_df, place_col="city")
    fig_loc_map = panel_charts.geo_bubble_map(
        px,
        loc_geo,
        size="sites",
        hover_name="location_name",
        color="country" if "country" in loc_geo.columns else None,
        title="Device locations (city centroids — street coords scrubbed)",
        empty_title="No geocoded device locations",
        size_max=24,
    )
    flips_df = ringq.daily_offline_flips(conn, filters)
    stretches_df = ringq.offline_stretches(conn, filters)
    motion_df = ringq.motion_timeline(conn, filters)
    motion_out_df = ringq.motion_duration_outliers(conn, filters)
    app_daily = ringq.app_daily_volume(conn, filters)
    app_top = ringq.app_top_events(conn, filters)
    app_busy = ringq.app_busiest_days(conn, filters)
    subs_df = ringq.subscription_ledger(conn)
    acct_df = ringq.accounting_ledger(conn)

    fig_flips = (
        px.bar(
            flips_df,
            x="day",
            y=["offline", "online"],
            title="Device online/offline flips by day",
            barmode="group",
        )
        if not flips_df.empty
        else px.bar(title="No device state events")
    )
    fig_app = (
        px.line(
            app_daily,
            x="day",
            y="events",
            title="App telemetry volume by day",
            markers=True,
        )
        if not app_daily.empty
        else px.line(title="No app events")
    )
    fig_app_launch = (
        px.bar(
            app_daily,
            x="day",
            y="launches",
            title="App launches by day",
        )
        if not app_daily.empty
        else px.bar(title="No launches")
    )
    fig_top = (
        px.bar(
            app_top,
            x="events",
            y="event",
            orientation="h",
            title="Top app event types",
        )
        if not app_top.empty
        else px.bar(title="No app event types")
    )
    if not app_top.empty:
        fig_top.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_motion = (
        px.scatter(
            motion_df,
            x="ts_local",
            y="duration_seconds",
            color="detection_type",
            title="Motion events (duration)",
            hover_data=["event_type", "status"],
        )
        if not motion_df.empty
        else px.scatter(title="No motion events in retention window")
    )

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Ring\n"
                f"{span}. Shallow view: footprint, online/offline, sparse motion, "
                f"app telemetry spikes, billing."
            ),
            mo.hstack(
                [controls.year_start, controls.year_end, controls.compare],
                justify="start",
                gap=1,
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.md("### Data footprint"),
            mo.ui.table(inv_df),
            mo.md("### Devices"),
            mo.ui.table(devices_df),
            mo.md("### Locations"),
            mo.ui.plotly(fig_loc_map),
            mo.ui.table(locations_df),
            mo.md("### Device online/offline"),
            mo.ui.plotly(fig_flips),
            mo.md("### Longest offline stretches"),
            mo.ui.table(stretches_df),
            mo.md("### Motion"),
            mo.ui.plotly(fig_motion),
            mo.ui.table(motion_out_df),
            mo.md("### App activity spikes"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_app),
                    mo.ui.plotly(fig_app_launch),
                    mo.ui.plotly(fig_top),
                ],
                gap=1,
            ),
            mo.md("### Busiest app days"),
            mo.ui.table(app_busy),
            mo.md("### Billing"),
            mo.ui.table(subs_df),
            mo.ui.table(acct_df),
        ],
        gap=0.5,
    )
