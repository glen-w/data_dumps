"""Amazon explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import amazon_queries as amzq
from data_dumps.geo import attach_country_iso3

from . import charts as panel_charts


@dataclass
class AmazonControls:
    year_start: Any
    year_end: Any
    marketplace_select: Any
    currency_select: Any
    dept_select: Any
    include_cancelled: Any


def make_amazon_controls(mo: Any, bounds: dict[str, Any]) -> AmazonControls:
    return AmazonControls(
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
        marketplace_select=mo.ui.multiselect(
            options=bounds.get("marketplaces") or [],
            value=[],
            label="Marketplaces",
        ),
        currency_select=mo.ui.multiselect(
            options=bounds.get("currencies") or [],
            value=[],
            label="Currencies",
        ),
        dept_select=mo.ui.multiselect(
            options=bounds.get("dept_families") or [],
            value=[],
            label="Product types",
        ),
        include_cancelled=mo.ui.checkbox(label="Include cancelled lines", value=False),
    )


def render_amazon_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: AmazonControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = amzq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
        marketplaces=list(controls.marketplace_select.value or []),
        currencies=list(controls.currency_select.value or []),
        dept_families=list(controls.dept_select.value or []),
        include_cancelled=bool(controls.include_cancelled.value),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range · cancelled hidden_")
    )

    foot = amzq.footprint_scoreboard(conn)
    foot_cat = amzq.footprint_by_category(conn)
    foot_zip = amzq.footprint_by_zip(conn)
    surfaces = amzq.surface_counts(conn)
    score = amzq.scoreboard(conn, filters)
    by_fx = amzq.spend_by_currency(conn, filters)
    aov = amzq.aov_by_marketplace(conn, filters)
    chapters = amzq.life_chapters(conn, filters)
    monthly = amzq.monthly_orders(conn, filters)
    monthly_fx = amzq.monthly_spend_by_currency(conn, filters)
    cancelled = amzq.cancelled_by_year(conn, filters)
    baskets = amzq.basket_sizes(conn, filters)
    treemap = amzq.dept_treemap(conn, filters)
    sun = amzq.spend_sunburst(conn, filters)
    products = amzq.top_products(conn, filters)
    funnel = amzq.search_funnel(conn, filters)
    funnel_stages = amzq.search_funnel_stages(conn, filters)
    keywords = amzq.top_search_keywords(conn, filters)
    returns = amzq.returns_summary(conn, filters)
    circ = amzq.order_circadian(conn, filters)
    cal = amzq.order_calendar(conn, filters)
    forgotten = amzq.forgotten_asins(conn, filters)
    comebacks = amzq.comeback_asins(conn, filters)
    digi = amzq.digital_vs_retail_yearly(conn, filters)
    impulse = amzq.impulse_index_by_family(conn, filters)
    cart = amzq.cart_vs_ordered(conn, filters)
    ret_fam = amzq.returns_by_family(conn, filters)

    voice_gb = 0.0
    if not foot.empty:
        voice_gb = float(foot.iloc[0]["voice_bytes"] or 0) / 1e9
        total_gb = float(foot.iloc[0]["total_bytes"] or 0) / 1e9
        n_files = int(foot.iloc[0]["files"] or 0)
        voice_n = int(foot.iloc[0]["voice_files"] or 0)
    else:
        total_gb = 0.0
        n_files = 0
        voice_n = 0

    fig_foot = (
        px.treemap(
            foot_cat,
            path=["category"],
            values="bytes",
            title="Dump footprint by category (bytes on disk)",
        )
        if not foot_cat.empty
        else px.bar(title="No inventory")
    )
    fig_foot_zip = (
        px.bar(
            foot_zip.groupby("zip_part", as_index=False)["bytes"]
            .sum()
            .sort_values("bytes", ascending=False),  # type: ignore[call-overload]
            x="zip_part",
            y="bytes",
            title="Dump bytes by zip part",
        )
        if not foot_zip.empty
        else px.bar(title="No zip parts")
    )
    fig_surf = (
        px.bar(
            surfaces,
            x="n",
            y="surface",
            orientation="h",
            title="Warehouse row counts by surface",
        )
        if not surfaces.empty
        else px.bar(title="No surfaces")
    )
    country_act = amzq.activity_by_country(conn, filters)
    country_geo = attach_country_iso3(country_act, code_col="country")
    fig_country_map = panel_charts.country_choropleth(
        px,
        country_geo,
        color="events",
        hover_name="country",
        title="Video + product impressions by country_code",
        empty_title="No marketplace country codes to map",
    )
    fig_fx = (
        px.bar(by_fx, x="currency", y="spend", title="Spend by currency (no FX merge)")
        if not by_fx.empty
        else px.bar(title="No spend")
    )
    fig_aov = (
        px.scatter(
            aov,
            x="orders",
            y="aov",
            color="marketplace",
            size="spend",
            hover_data=["currency"],
            title="Average order value by marketplace (bubble = spend)",
        )
        if not aov.empty
        else px.scatter(title="No AOV")
    )
    fig_chapters = (
        px.area(
            chapters,
            x="year",
            y="lines",
            color="marketplace",
            title="Life chapters — order lines by year × marketplace",
        )
        if not chapters.empty
        else px.bar(title="No chapters")
    )
    fig_chapters_spend = (
        px.bar(
            chapters,
            x="year",
            y="spend",
            color="marketplace",
            barmode="stack",
            title="Spend by year × marketplace (mixed currencies — compare within mkt)",
        )
        if not chapters.empty
        else px.bar(title="No spend chapters")
    )
    fig_month = (
        px.bar(monthly, x="month_start", y="orders", title="Orders per month")
        if not monthly.empty
        else px.bar(title="No monthly data")
    )
    fig_month_fx = (
        px.line(
            monthly_fx,
            x="month_start",
            y="spend",
            color="currency",
            title="Monthly spend by currency",
        )
        if not monthly_fx.empty
        else px.line(title="No monthly spend")
    )
    if cancelled.empty:
        fig_cancel = px.bar(title="No cancel data")
    else:
        cancel_long = cancelled.melt(
            id_vars=["year"],
            value_vars=["kept", "cancelled"],
            var_name="status",
            value_name="lines",
        )
        fig_cancel = px.bar(
            cancel_long,
            x="year",
            y="lines",
            color="status",
            barmode="stack",
            title="Kept vs cancelled order lines by year",
        )
    fig_basket = (
        px.bar(baskets, x="n_items", y="orders", title="Basket size (lines per order)")
        if not baskets.empty
        else px.bar(title="No baskets")
    )
    fig_tree = (
        px.treemap(
            treemap,
            path=["dept_family", "department"],
            values="lines",
            title="What you buy — type → department (by lines)",
        )
        if not treemap.empty
        else px.bar(title="No departments")
    )
    fig_sun = (
        px.sunburst(
            sun,
            path=["dept_family", "department"],
            values="spend",
            title="Spend sunburst — type → department",
        )
        if not sun.empty
        else px.sunburst(title="No spend sunburst")
    )
    fig_digi = (
        px.bar(
            digi,
            x="year",
            y="lines",
            color="surface",
            barmode="group",
            title="Retail vs digital lines by year",
        )
        if not digi.empty
        else px.bar(title="No digital/retail")
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circ,
        z="events",
        dow_labels=dow_labels,
        title="Orders by weekday × hour (Europe/Rome)",
        colorscale="Oranges",
        empty_title="No order circadian",
        xaxis_title="",
        yaxis_title="",
    )
    fig_cal = panel_charts.iso_week_calendar(
        px,
        cal,
        z="orders",
        title="Order calendar (weekday × ISO week)",
        colorscale="YlOrRd",
        empty_title="No order calendar",
        xaxis_title="",
        yaxis_title="",
    )
    fig_funnel = (
        px.funnel(funnel_stages, x="n", y="stage", title="Search → purchase funnel")
        if not funnel_stages.empty and int(funnel_stages["n"].sum()) > 0
        else px.bar(title="No search funnel")
    )
    fig_kw = (
        px.bar(
            keywords.head(20),
            x="searches",
            y="keywords",
            orientation="h",
            title="Top search keywords",
        )
        if not keywords.empty
        else px.bar(title="No keywords")
    )
    if not keywords.empty:
        fig_kw.update_yaxes(autorange="reversed")
    fig_returns = (
        px.bar(
            returns.head(15),
            x="n",
            y="return_reason",
            orientation="h",
            title="Return reasons",
        )
        if not returns.empty
        else px.bar(title="No returns")
    )
    if not returns.empty:
        fig_returns.update_yaxes(autorange="reversed")
    fig_comeback = (
        px.scatter(
            comebacks,
            x="gap_days",
            y="times",
            hover_data=["product_name", "asin"],
            title="Repurchased ASINs — gap days vs times ordered",
        )
        if not comebacks.empty
        else px.scatter(title="No repurchases")
    )

    # Impulse vs planned: 100% stacked share of lines per product family.
    if impulse.empty:
        fig_impulse = px.bar(title="No impulse/planned data")
    else:
        imp = impulse.copy()
        imp["family_share"] = imp.groupby("dept_family", observed=True)[
            "lines"
        ].transform(lambda s: s / s.sum())
        fig_impulse = px.bar(
            imp,
            x="family_share",
            y="dept_family",
            color="basket_kind",
            orientation="h",
            title="Impulse vs planned baskets — share of lines by family "
            "(impulse = single-line order)",
            labels={
                "family_share": "share of lines",
                "dept_family": "family",
                "basket_kind": "basket",
            },
        )
        fig_impulse.update_xaxes(range=[0, 1])
        fig_impulse.update_yaxes(autorange="reversed")

    # Cart vs ordered: conversion of add-to-cart ASINs into orders.
    if cart.empty:
        fig_cart = px.bar(title="No cart data")
    else:
        n_cart_asin = int(cart["asin"].nunique())
        n_cart_adds = int(cart["cart_adds"].sum())
        n_ordered_asin = int(cart.loc[cart["outcome"] == "ordered", "asin"].nunique())
        n_abandoned_asin = int(
            cart.loc[cart["outcome"] == "abandoned", "asin"].nunique()
        )
        conv = 100.0 * n_ordered_asin / n_cart_asin if n_cart_asin else 0.0
        cart_long = pd.DataFrame(
            {
                "outcome": ["ordered", "abandoned"],
                "asin": [n_ordered_asin, n_abandoned_asin],
            }
        )
        fig_cart = px.bar(
            cart_long,
            x="asin",
            y="outcome",
            orientation="h",
            title=f"Cart → order — {n_cart_asin} carted ASINs "
            f"({n_cart_adds} adds) → {n_ordered_asin} ordered ({conv:.0f}%), "
            f"{n_abandoned_asin} never bought",
            labels={"asin": "distinct ASINs", "outcome": "outcome"},
        )
        fig_cart.update_yaxes(autorange="reversed")

    # Returns by family: refund burden as a horizontal bar.
    if ret_fam.empty:
        fig_ret_fam = px.bar(title="No return data for families")
    else:
        rf = ret_fam.copy()
        rf["label"] = (
            rf["dept_family"]
            + " — "
            + rf["return_orders"].astype(int).astype(str)
            + " orders"
        )
        fig_ret_fam = px.bar(
            rf,
            x="refund_sum",
            y="label",
            orientation="h",
            title="Refund burden by product family (refunds joined via order_id)",
            hover_data=["dept_family", "return_orders", "return_lines", "refund_sum"],
            labels={"refund_sum": "refunded amount (mixed ccy)", "label": "family"},
        )
        fig_ret_fam.update_yaxes(autorange="reversed")
        fig_ret_fam.update_xaxes(range=[0, (rf["refund_sum"].max() * 1.15) or 1])

    sections: list[Any] = [
        mo.md(
            f"## Amazon explorer\n"
            f"Dump footprint: **{n_files:,}** files · **{total_gb:.1f} GB** "
            f"({voice_n:,} voice files / **{voice_gb:.1f} GB** shadowed — not loaded). "
            "Addresses, cards, IPs, and geolocation dropped at ingest."
        ),
        mo.hstack(
            [
                controls.year_start,
                controls.year_end,
                controls.include_cancelled,
            ],
            justify="start",
            gap=1,
        ),
        mo.hstack(
            [
                controls.marketplace_select,
                controls.currency_select,
                controls.dept_select,
            ],
            justify="start",
            gap=1,
        ),
        chip_row,
        mo.md("### Data footprint"),
        mo.vstack([mo.ui.plotly(fig_foot), mo.ui.plotly(fig_foot_zip)], gap=1),
        mo.ui.plotly(fig_surf),
        mo.md("### Marketplace map"),
        mo.ui.plotly(fig_country_map),
        mo.md("### Spend scoreboard"),
        mo.ui.table(score),
        mo.vstack([mo.ui.plotly(fig_fx), mo.ui.plotly(fig_aov)], gap=1),
        mo.md("### Life chapters & rhythm"),
        mo.vstack(
            [mo.ui.plotly(fig_chapters), mo.ui.plotly(fig_chapters_spend)], gap=1
        ),
        mo.vstack([mo.ui.plotly(fig_month), mo.ui.plotly(fig_month_fx)], gap=1),
        mo.vstack([mo.ui.plotly(fig_cancel), mo.ui.plotly(fig_basket)], gap=1),
        mo.vstack([mo.ui.plotly(fig_circ), mo.ui.plotly(fig_cal)], gap=1),
        mo.md("### What you buy"),
        mo.vstack([mo.ui.plotly(fig_tree), mo.ui.plotly(fig_sun)], gap=1),
        mo.ui.plotly(fig_digi),
        mo.ui.plotly(fig_impulse),
        mo.ui.table(products),
        mo.md("### How you shop — search funnel & cart"),
        mo.vstack([mo.ui.plotly(fig_funnel), mo.ui.table(funnel)], gap=1),
        mo.ui.plotly(fig_kw),
        mo.ui.plotly(fig_cart),
        mo.md("### Returns & loyalty"),
        mo.vstack(
            [
                mo.ui.plotly(fig_returns),
                mo.ui.plotly(fig_ret_fam),
                mo.ui.plotly(fig_comeback),
            ],
            gap=1,
        ),
        mo.ui.table(returns),
        mo.md("### One-and-done ASINs (oldest last order)"),
        mo.ui.table(forgotten),
        mo.md("### Repurchased ASINs"),
        mo.ui.table(comebacks),
    ]

    if amzq.has_table(conn, "alexa_intents"):
        a_score = amzq.alexa_scoreboard(conn, filters)
        a_tags = amzq.alexa_tags(conn, filters)
        a_month = amzq.alexa_monthly(conn, filters)
        a_tag_m = amzq.alexa_tag_monthly(conn, filters)
        a_circ = amzq.alexa_circadian(conn, filters)
        a_dev = amzq.alexa_devices(conn, filters)
        a_show = amzq.alexa_show_engagement(conn, filters)
        a_skills = amzq.alexa_skills(conn)
        a_utt = amzq.alexa_top_utterances(conn, filters)
        fig_tags = (
            px.bar(
                a_tags, x="n", y="tag", orientation="h", title="Alexa utterance tags"
            )
            if not a_tags.empty
            else px.bar(title="No Alexa tags")
        )
        fig_a_month = (
            px.bar(
                a_month,
                x="month_start",
                y="utterances",
                title="Alexa utterances / month",
            )
            if not a_month.empty
            else px.bar(title="No Alexa monthly")
        )
        fig_tag_m = (
            px.area(
                a_tag_m,
                x="month_start",
                y="n",
                color="tag",
                title="Alexa tag mix over time",
            )
            if not a_tag_m.empty
            else px.area(title="No tag timeline")
        )
        fig_a_circ = panel_charts.circadian_heatmap(
            px,
            a_circ,
            z="events",
            dow_labels=dow_labels,
            title="Alexa by weekday × hour",
            colorscale="Purples",
            empty_title="No Alexa circadian",
            xaxis_title="",
            yaxis_title="",
        )
        fig_dev = (
            px.pie(
                a_dev,
                names="device_type",
                values="events",
                title="Alexa device sessions",
            )
            if not a_dev.empty
            else px.bar(title="No device sessions")
        )
        if a_show.empty:
            fig_show = px.bar(title="No Echo Show engagement")
        else:
            show_long = a_show.melt(
                id_vars=["month_start"],
                value_vars=["voice", "touch", "impressions"],
                var_name="kind",
                value_name="count",
            )
            fig_show = px.line(
                show_long,
                x="month_start",
                y="count",
                color="kind",
                title="Echo Show voice / touch / impressions",
            )
        fig_utt = (
            px.bar(
                a_utt.head(20),
                x="n",
                y="utterance",
                color="tag",
                orientation="h",
                title="Most repeated Alexa utterances",
            )
            if not a_utt.empty
            else px.bar(title="No utterances")
        )
        if not a_utt.empty:
            fig_utt.update_yaxes(autorange="reversed")
        sections.extend(
            [
                mo.md("### Alexa in the house"),
                mo.ui.table(a_score),
                mo.vstack([mo.ui.plotly(fig_tags), mo.ui.plotly(fig_a_month)], gap=1),
                mo.ui.plotly(fig_tag_m),
                mo.vstack([mo.ui.plotly(fig_a_circ), mo.ui.plotly(fig_dev)], gap=1),
                mo.ui.plotly(fig_show),
                mo.ui.plotly(fig_utt),
                mo.ui.table(a_skills),
            ]
        )

    if amzq.has_table(conn, "audible_listens"):
        aud = amzq.audible_hours(conn, filters)
        if not aud.empty:
            sections.extend(
                [
                    mo.md("### Audible"),
                    mo.ui.plotly(
                        px.bar(
                            aud,
                            x="hours",
                            y="title",
                            orientation="h",
                            title="Audible hours by title",
                        )
                    ),
                ]
            )

    if amzq.has_table(conn, "video_views"):
        vid = amzq.video_titles(conn, filters)
        if not vid.empty:
            fig_vid = px.bar(
                vid,
                x="minutes",
                y="title",
                orientation="h",
                title="Prime Video minutes by title",
            )
            fig_vid.update_yaxes(autorange="reversed")
            sections.extend(
                [
                    mo.md("### Prime Video"),
                    mo.ui.plotly(fig_vid),
                    mo.ui.table(vid),
                ]
            )

    if amzq.has_table(conn, "kindle_sessions"):
        kdf = amzq.kindle_monthly(conn, filters)
        if not kdf.empty:
            sections.extend(
                [
                    mo.md("### Kindle"),
                    mo.ui.plotly(
                        px.bar(
                            kdf,
                            x="month_start",
                            y="hours",
                            title="Kindle reading hours by month",
                        )
                    ),
                ]
            )

    if amzq.has_table(conn, "music_searches"):
        msearch = amzq.music_top_searches(conn, filters)
        if not msearch.empty:
            fig_ms = px.bar(
                msearch,
                x="n",
                y="query",
                orientation="h",
                title="Amazon Music search queries",
            )
            fig_ms.update_yaxes(autorange="reversed")
            sections.extend([mo.md("### Amazon Music searches"), mo.ui.plotly(fig_ms)])

    if amzq.has_table(conn, "product_impressions"):
        imps = amzq.impression_mix(conn, filters)
        itop = amzq.impression_top(conn, filters)
        if not imps.empty:
            sections.extend(
                [
                    mo.md("### Product impressions (geo stripped)"),
                    mo.ui.plotly(
                        px.bar(
                            imps,
                            x="kind",
                            y="n",
                            title="Detail-page vs buy-again impressions",
                        )
                    ),
                    mo.ui.table(itop),
                ]
            )

    if amzq.has_table(conn, "rufus_queries"):
        ruf = amzq.rufus_top(conn, filters)
        if not ruf.empty:
            fig_ruf = px.bar(
                ruf, x="n", y="query", orientation="h", title="Rufus shopping queries"
            )
            fig_ruf.update_yaxes(autorange="reversed")
            sections.extend([mo.md("### Rufus"), mo.ui.plotly(fig_ruf)])

    return mo.vstack(sections, gap=0.5)
