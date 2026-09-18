"""Airbnb explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import airbnb_queries as abq
from data_dumps.geo import attach_country_iso3

from . import charts as panel_charts


@dataclass
class AirbnbControls:
    year_start: Any
    year_end: Any
    role: Any
    status: Any
    place: Any
    compare: Any


def make_airbnb_controls(mo: Any, bounds: dict[str, Any]) -> AirbnbControls:
    roles = ["(all)", *list(bounds.get("roles") or [])]
    statuses = ["(all)", *list(bounds.get("statuses") or [])]
    places = ["(all)", *list(bounds.get("places") or [])]
    return AirbnbControls(
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
        role=mo.ui.dropdown(options=roles, value="(all)", label="Role"),
        status=mo.ui.dropdown(options=statuses, value="(all)", label="Status"),
        place=mo.ui.dropdown(options=places, value="(all)", label="Search place"),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
    )


def render_airbnb_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: AirbnbControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = abq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
        role=controls.role.value,
        status=controls.status.value,
        place=controls.place.value,
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = abq.scoreboard(
        conn, filters, compare_previous=bool(controls.compare.value)
    )
    streak_df = abq.streak_stats(conn, filters)
    monthly_df = abq.reservations_monthly(conn, filters)
    status_df = abq.status_breakdown(conn, filters)
    role_df = abq.role_breakdown(conn, filters)
    country_df = abq.nights_by_country(conn, filters)
    recent_df = abq.recent_stays(conn, filters)
    cal_df = abq.calendar_daily_starts(conn, filters)
    circ_df = abq.weekday_heatmap(conn, filters)
    search_monthly_df = abq.searches_monthly(conn, filters)
    search_places_df = abq.searches_by_place(conn, filters)
    search_map_df = abq.search_map_points(conn, filters)
    forgotten_df = abq.forgotten_search_places(conn, filters)
    comeback_df = abq.comeback_search_places(conn, filters)
    bump_df = abq.place_rank_bump(conn, filters)
    reviews_df = abq.reviews_summary(conn, filters)
    reviews_monthly_df = abq.reviews_monthly(conn, filters)
    wishlist_df = abq.wishlist_summary(conn)

    fig_monthly = (
        px.bar(
            monthly_df,
            x="year_month",
            y="reservations",
            title="Reservations by month",
        )
        if not monthly_df.empty
        else px.bar(title="No reservations in range")
    )
    fig_nights = (
        px.bar(
            monthly_df,
            x="year_month",
            y="nights",
            title="Accepted nights by month",
        )
        if not monthly_df.empty
        else px.bar(title="No nights in range")
    )
    fig_status = (
        px.pie(status_df, names="status", values="reservations", title="Status")
        if not status_df.empty
        else px.pie(title="No status data")
    )
    fig_role = (
        px.bar(
            role_df,
            x="reservations",
            y="role",
            orientation="h",
            title="Guest vs host",
        )
        if not role_df.empty
        else px.bar(title="No role data")
    )

    country_geo = attach_country_iso3(country_df, code_col="country")
    fig_country_map = panel_charts.country_choropleth(
        px,
        country_geo,
        color="nights",
        locations="iso3",
        hover_name="country",
        title="Guest nights by host VAT country",
        empty_title="No guest-country nights to map",
    )

    fig_search_map = panel_charts.geo_bubble_map(
        px,
        search_map_df,
        size="searches",
        hover_name="place",
        lat="lat",
        lon="lon",
        title="Search pins (export lat/lon, aggregated)",
        empty_title="No geocoded searches",
    )
    unmapped = int(search_map_df["lat"].isna().sum()) if not search_map_df.empty else 0

    fig_search_monthly = (
        px.bar(
            search_monthly_df,
            x="year_month",
            y="searches",
            title="Searches by month",
        )
        if not search_monthly_df.empty
        else px.bar(title="No searches in range")
    )
    fig_places = (
        px.bar(
            search_places_df.head(20),
            x="searches",
            y="place",
            orientation="h",
            title="Top search places",
        )
        if not search_places_df.empty
        else px.bar(title="No search places")
    )
    if not search_places_df.empty:
        fig_places.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_cal = panel_charts.iso_week_calendar(
        px,
        cal_df,
        z="events",
        title="Trip starts (weekday × ISO week)",
        empty_title="No trip calendar",
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circ_df,
        z="events",
        dow_labels=dow_labels,
        title="Reservation created (weekday × hour, Europe/Paris)",
        empty_title="No circadian data",
        xaxis_title="",
        yaxis_title="",
    )
    fig_bump = (
        px.line(
            bump_df,
            x="year",
            y="rank",
            color="place",
            markers=True,
            title="Search-place rank bump (lower is hotter)",
        )
        if not bump_df.empty
        else px.line(title="No place ranks")
    )
    if not bump_df.empty:
        fig_bump.update_yaxes(autorange="reversed", dtick=1)

    fig_reviews = (
        px.bar(
            reviews_monthly_df,
            x="year_month",
            y="reviews",
            title="Reviews by month",
        )
        if not reviews_monthly_df.empty
        else px.bar(title="No reviews in range")
    )

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    n_places = len(bounds.get("places") or [])
    map_note = (
        f"_Search map pins: {len(search_map_df)} clusters"
        + (f"; {unmapped} missing coords. " if unmapped else ". ")
        + f"Place selector: {n_places} options. "
        "Compare/Correlations: reservations, nights, searches, place entity._"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Airbnb\n"
                f"{span}. Guest + host reservations, searches, reviews, wishlists. "
                f"Profile contact fields, street addresses, IPs, phones, KYC, "
                f"payments, activity log, and messages are dropped at ingest."
            ),
            mo.hstack(
                [
                    controls.year_start,
                    controls.year_end,
                    controls.role,
                    controls.status,
                    controls.place,
                    controls.compare,
                ],
                justify="start",
                gap=1,
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.md("### Streaks"),
            mo.ui.table(streak_df),
            mo.md("### Reservations over time"),
            mo.vstack([mo.ui.plotly(fig_monthly), mo.ui.plotly(fig_nights)], gap=1),
            mo.md("### Role & status"),
            mo.ui.plotly(fig_role),
            mo.ui.plotly(fig_status),
            mo.md("### Maps"),
            mo.md(map_note),
            mo.ui.plotly(fig_search_map),
            mo.ui.plotly(fig_country_map),
            mo.md("### Rhythm"),
            mo.vstack([mo.ui.plotly(fig_cal), mo.ui.plotly(fig_circ)], gap=1),
            mo.md("### Searches"),
            mo.vstack(
                [mo.ui.plotly(fig_search_monthly), mo.ui.plotly(fig_places)],
                gap=1,
            ),
            mo.md("### Forgotten & comeback search places"),
            mo.md("Silent ≥2y"),
            mo.ui.table(forgotten_df),
            mo.md("Returned after gap"),
            mo.ui.table(comeback_df),
            mo.md("### Search-place rank movement"),
            mo.ui.plotly(fig_bump),
            mo.md("### Recent stays"),
            mo.ui.table(recent_df),
            mo.md("### Reviews & wishlists"),
            mo.ui.plotly(fig_reviews),
            mo.ui.table(reviews_df),
            mo.ui.table(wishlist_df),
        ],
        gap=0.5,
    )
