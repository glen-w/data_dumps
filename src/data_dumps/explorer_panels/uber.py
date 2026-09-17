"""Uber explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import uber_queries as ubq

from . import charts as panel_charts


@dataclass
class UberControls:
    year_start: Any
    year_end: Any
    city: Any
    compare: Any


def make_uber_controls(mo: Any, bounds: dict[str, Any]) -> UberControls:
    cities = ["(all)", *list(bounds.get("cities") or [])]
    return UberControls(
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
        city=mo.ui.dropdown(
            options=cities,
            value="(all)",
            label="City",
        ),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
    )


def render_uber_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: UberControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = ubq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
        city=controls.city.value,
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = ubq.scoreboard(
        conn, filters, compare_previous=bool(controls.compare.value)
    )
    streak_df = ubq.streak_stats(conn, filters)
    monthly_df = ubq.trips_monthly(conn, filters)
    by_city_df = ubq.trips_by_city(conn, filters)
    by_product_df = ubq.trips_by_product(conn, filters)
    status_df = ubq.status_breakdown(conn, filters)
    cal_df = ubq.calendar_daily_trips(conn, filters)
    circ_df = ubq.weekday_heatmap(conn, filters)
    forgotten_df = ubq.forgotten_cities(conn, filters)
    comeback_df = ubq.comeback_cities(conn, filters)
    bump_df = ubq.city_rank_bump(conn, filters)
    scatter_df = ubq.fare_vs_distance_scatter(conn, filters)
    eats_monthly_df = ubq.eats_monthly(conn, filters)
    eats_rest_df = ubq.eats_by_restaurant(conn, filters)
    ratings_df = ubq.ratings_summary(conn)
    support_df = ubq.support_summary(conn, filters)

    fig_monthly = (
        px.bar(
            monthly_df,
            x="year_month",
            y="trips",
            title="Trips by month",
        )
        if not monthly_df.empty
        else px.bar(title="No trips in range")
    )
    fig_city = (
        px.bar(
            by_city_df,
            x="trips",
            y="city",
            orientation="h",
            title="Trips by city",
        )
        if not by_city_df.empty
        else px.bar(title="No cities")
    )
    if not by_city_df.empty:
        fig_city.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_product = (
        px.bar(
            by_product_df,
            x="trips",
            y="product",
            orientation="h",
            title="Trips by product",
        )
        if not by_product_df.empty
        else px.bar(title="No products")
    )
    if not by_product_df.empty:
        fig_product.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_status = (
        px.pie(status_df, names="status", values="trips", title="Trip status")
        if not status_df.empty
        else px.pie(title="No status data")
    )

    fig_cal = panel_charts.iso_week_calendar(
        px,
        cal_df,
        z="events",
        title="Trips (weekday × ISO week)",
        empty_title="No trip calendar",
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circ_df,
        z="events",
        dow_labels=dow_labels,
        title="Trips by weekday × hour (Europe/Rome wall-clock)",
        empty_title="No circadian data",
        xaxis_title="",
        yaxis_title="",
    )

    fig_bump = (
        px.line(
            bump_df,
            x="year",
            y="rank",
            color="city",
            markers=True,
            title="City rank bump (lower is busier)",
        )
        if not bump_df.empty
        else px.line(title="No city ranks")
    )
    if not bump_df.empty:
        fig_bump.update_yaxes(autorange="reversed", dtick=1)

    fig_scatter = (
        px.scatter(
            scatter_df,
            x="miles",
            y="fare_usd",
            color="city",
            hover_data=["product", "request_ts_local"],
            title="Fare (USD) vs distance (miles)",
        )
        if not scatter_df.empty
        else px.scatter(title="No fare/distance pairs")
    )

    fig_eats = (
        px.bar(
            eats_monthly_df,
            x="year_month",
            y="orders",
            title="Eats orders by month",
        )
        if not eats_monthly_df.empty
        else px.bar(title="No Eats orders in range")
    )
    fig_rest = (
        px.bar(
            eats_rest_df,
            x="orders",
            y="restaurant",
            orientation="h",
            title="Top restaurants",
        )
        if not eats_rest_df.empty
        else px.bar(title="No restaurants")
    )
    if not eats_rest_df.empty:
        fig_rest.update_layout(yaxis={"categoryorder": "total ascending"})

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Uber\n"
                f"{span}. Rider trips + Uber Eats. Precise coords, addresses, "
                f"payment instruments, profile contact fields, and app GPS "
                f"analytics are dropped at ingest."
            ),
            mo.hstack(
                [
                    controls.year_start,
                    controls.year_end,
                    controls.city,
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
            mo.md("### Trips over time"),
            mo.ui.plotly(fig_monthly),
            mo.md("### Cities & products"),
            mo.vstack([mo.ui.plotly(fig_city), mo.ui.plotly(fig_product)], gap=1),
            mo.ui.plotly(fig_status),
            mo.md("### Rhythm"),
            mo.vstack([mo.ui.plotly(fig_cal), mo.ui.plotly(fig_circ)], gap=1),
            mo.md("### Forgotten & comeback cities"),
            mo.hstack(
                [
                    mo.vstack(
                        [mo.md("Silent ≥2y"), mo.ui.table(forgotten_df)], gap=0.25
                    ),
                    mo.vstack(
                        [mo.md("Returned after gap"), mo.ui.table(comeback_df)],
                        gap=0.25,
                    ),
                ],
                gap=1,
            ),
            mo.md("### Rank movement & fare scatter"),
            mo.vstack([mo.ui.plotly(fig_bump), mo.ui.plotly(fig_scatter)], gap=1),
            mo.md("### Uber Eats"),
            mo.vstack([mo.ui.plotly(fig_eats), mo.ui.plotly(fig_rest)], gap=1),
            mo.ui.table(eats_rest_df),
            mo.md("### Ratings & support"),
            mo.ui.table(ratings_df),
            mo.ui.table(support_df),
        ],
        gap=0.5,
    )
