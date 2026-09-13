"""Browser history explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import browser_queries as brq
from data_dumps.llm_client import BROWSER_SYSTEM
from data_dumps.llm_client import narrate as llm_narrate

from . import charts as panel_charts


@dataclass
class BrowserControls:
    year_start: Any
    year_end: Any
    category_select: Any
    scheme_select: Any
    source_select: Any
    include_private: Any
    text_search: Any
    compare: Any
    clear_search: Any
    clear_etld1: Any
    narrate_btn: Any
    get_etld1: Any
    set_etld1: Any


def make_browser_controls(mo: Any, bounds: dict[str, Any]) -> BrowserControls:
    get_etld1, set_etld1 = mo.state(None)
    return BrowserControls(
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
        category_select=mo.ui.multiselect(
            options=bounds.get("categories") or [], value=[], label="Category"
        ),
        scheme_select=mo.ui.multiselect(
            options=bounds.get("schemes") or [], value=[], label="Scheme"
        ),
        source_select=mo.ui.multiselect(
            options=bounds.get("sources") or [], value=[], label="Source"
        ),
        include_private=mo.ui.checkbox(label="Include private/LAN", value=True),
        text_search=mo.ui.text(
            label="Title / host / URL / query", placeholder="substring…"
        ),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        clear_search=mo.ui.run_button(label="× search"),
        clear_etld1=mo.ui.run_button(label="Clear domain lock"),
        narrate_btn=mo.ui.run_button(label="Narrate this view"),
        get_etld1=get_etld1,
        set_etld1=set_etld1,
    )


def _browser_calendar(px: Any, df: pd.DataFrame, title: str) -> Any:
    return panel_charts.iso_week_calendar(
        px,
        df,
        z="urls",
        title=title,
        colorscale="Teal",
        facet_by_year=True,
        yaxis_title="Mon=0 … Sun=6",
    )


def render_browser_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: BrowserControls,
) -> Any:
    c = controls
    if c.clear_search.value:
        c.text_search.value = ""
    if c.clear_etld1.value:
        c.set_etld1(None)

    filters = brq.filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        categories=list(c.category_select.value),
        schemes=list(c.scheme_select.value),
        sources=list(c.source_select.value),
        include_private=bool(c.include_private.value),
        text_search=c.text_search.value,
        etld1=c.get_etld1(),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full range · all sources_")
    )

    score_df = brq.scoreboard(conn, filters, compare=bool(c.compare.value))
    domains_df = brq.top_domains(conn, filters)
    hosts_df = brq.top_hosts(conn, filters)
    pages_df = brq.top_pages(conn, filters)
    cat_df = brq.category_mix(conn, filters)
    scheme_df = brq.scheme_mix(conn, filters)
    source_df = brq.source_mix(conn, filters)
    monthly_df = brq.monthly_last_visits(conn, filters)
    cal_df = brq.calendar_last_seen(conn, filters)
    engine_df = brq.search_engines(conn, filters)
    queries_df = brq.top_search_queries(conn, filters)
    search_monthly_df = brq.monthly_search_volume(conn, filters)
    forgotten_df = brq.forgotten_gems(conn, filters)
    routines_df = brq.routines(conn, filters)
    comeback_df = brq.comeback_domains(conn, filters)
    local_df = brq.local_hosts(conn, filters)

    locked = c.get_etld1()
    tree_df = brq.path_tree(conn, filters, etld1=locked) if locked else pd.DataFrame()

    def _lock_domain(value: Any) -> None:
        if isinstance(value, dict) and value.get("points"):
            pt = value["points"][0]
            label = pt.get("label") or pt.get("y") or pt.get("x")
            if label:
                c.set_etld1(str(label))

    fig_domains = (
        px.bar(
            domains_df.head(20),
            x="visits",
            y="domain",
            orientation="h",
            color="category",
            title="Top domains (eTLD+1) by visit count",
        )
        if not domains_df.empty
        else px.bar(title="No domains")
    )
    if not domains_df.empty:
        fig_domains.update_layout(yaxis={"categoryorder": "total ascending"})
        fig_domains = mo.ui.plotly(fig_domains, on_change=_lock_domain)
    else:
        fig_domains = mo.ui.plotly(fig_domains)

    fig_hosts = (
        px.bar(
            hosts_df.head(20),
            x="visits",
            y="host",
            orientation="h",
            title="Top hosts by visit count",
        )
        if not hosts_df.empty
        else px.bar(title="No hosts")
    )
    if not hosts_df.empty:
        fig_hosts.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_cat = (
        px.treemap(
            cat_df,
            path=["category"],
            values="visits",
            title="Category mix (visit-weighted)",
        )
        if not cat_df.empty
        else px.treemap(title="No categories")
    )
    fig_scheme = (
        px.pie(scheme_df, names="scheme", values="urls", title="Scheme mix (URLs)")
        if not scheme_df.empty
        else px.pie(title="No schemes")
    )
    fig_source = (
        px.bar(
            source_df,
            x="source_set",
            y="urls",
            title="Source attribution (URL count)",
        )
        if not source_df.empty
        else px.bar(title="No sources")
    )
    fig_monthly = (
        px.bar(
            monthly_df,
            x="month",
            y="urls_last_seen",
            title="URLs by last-seen month (not pageviews)",
        )
        if not monthly_df.empty
        else px.bar(title="No monthly data")
    )
    fig_cal = _browser_calendar(
        px, cal_df, "Last-seen calendar (URLs whose last visit fell on that day)"
    )
    fig_engines = (
        px.bar(engine_df, x="engine", y="urls", title="Search engine URLs")
        if not engine_df.empty
        else px.bar(title="No search engines")
    )
    fig_search_monthly = (
        px.bar(
            search_monthly_df,
            x="month",
            y="urls",
            color="engine",
            title="Search URLs by last-seen month",
        )
        if not search_monthly_df.empty
        else px.bar(title="No monthly search data")
    )
    fig_tree = (
        px.bar(
            tree_df,
            x="visits",
            y="path_prefix",
            color="host",
            orientation="h",
            title=f"Path prefixes under {locked}",
        )
        if locked and not tree_df.empty
        else None
    )

    narrate_block: Any = mo.md("")
    if c.narrate_btn.value:
        ctx = brq.narrative_context(conn, filters)
        try:
            text, cached = llm_narrate(ctx, system=BROWSER_SYSTEM)
            suffix = " _(cached)_" if cached else ""
            narrate_block = mo.md(f"### Narration{suffix}\n\n{text}")
        except Exception as exc:  # noqa: BLE001 — surface LLM errors in UI
            narrate_block = mo.md(f"### Narration\n\nNarration failed: {exc}")

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    sections: list[Any] = [
        mo.md(
            f"## Browser history\n"
            f"{span}. URL-level grain (last visit + visit count) from Firefox Sky "
            f"export, merged with legacy Chrome-style `history.json`. "
            f"Click a domain bar to lock path-tree focus."
        ),
        mo.hstack(
            [c.year_start, c.year_end, c.include_private, c.compare],
            justify="start",
            gap=1,
        ),
        mo.hstack(
            [c.category_select, c.scheme_select, c.source_select],
            justify="start",
            gap=1,
        ),
        mo.hstack(
            [c.text_search, c.clear_search, c.clear_etld1, c.narrate_btn],
            justify="start",
            gap=1,
        ),
        chip_row,
        narrate_block,
        mo.md("### Scoreboard"),
        mo.ui.table(score_df),
        mo.md("### Top domains & hosts"),
        mo.vstack([fig_domains, mo.ui.plotly(fig_hosts)], gap=1),
        mo.md("### Top pages"),
        mo.ui.table(pages_df),
        mo.md("### Categories · schemes · sources"),
        mo.vstack(
            [mo.ui.plotly(fig_cat), mo.ui.plotly(fig_scheme), mo.ui.plotly(fig_source)],
            gap=1,
        ),
        mo.md("### Longitudinal (last-seen)"),
        mo.vstack([mo.ui.plotly(fig_monthly), mo.ui.plotly(fig_cal)], gap=1),
        mo.md("### Search behavior"),
        mo.vstack(
            [
                mo.ui.plotly(fig_engines),
                mo.ui.plotly(fig_search_monthly),
                mo.ui.table(queries_df),
            ],
            gap=1,
        ),
        mo.md("### Forgotten gems · routines · comebacks"),
        mo.md("**High visit_count, stale last_visit**"),
        mo.ui.table(forgotten_df),
        mo.md("**Recent daily-driver hosts**"),
        mo.ui.table(routines_df),
        mo.md("**Domains in both legacy + Firefox exports**"),
        mo.ui.table(comeback_df),
        mo.md("### Local / self-host"),
        mo.ui.table(local_df),
    ]
    if fig_tree is not None:
        sections.extend(
            [
                mo.md(f"### Path tree · `{locked}`"),
                mo.ui.plotly(fig_tree),
                mo.ui.table(tree_df),
            ]
        )
    return mo.vstack(sections, gap=0.5)
