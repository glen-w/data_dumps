"""Thunderbird explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import thunderbird_queries as tbq
from data_dumps.llm_client import THUNDERBIRD_SYSTEM
from data_dumps.llm_client import narrate as llm_narrate

from . import charts as panel_charts


@dataclass
class ThunderbirdControls:
    year_start: Any
    year_end: Any
    account_select: Any
    folder_select: Any
    direction_select: Any
    signal_select: Any
    contact_search: Any
    compare: Any
    mask_addrs: Any
    clear_contact: Any
    narrate_btn: Any
    get_contact: Any
    set_contact: Any


def make_thunderbird_controls(mo: Any, bounds: dict[str, Any]) -> ThunderbirdControls:
    get_contact, set_contact = mo.state(None)
    account_options = {
        f"{a['account_key']} · {a['folders']} folders": a["account_key"]
        for a in bounds.get("accounts") or []
        if a.get("account_key")
    }
    folder_options = {
        f"{fo['name']} ({fo['account_key']}) · {fo['messages']:,}": fo["folder_id"]
        for fo in bounds.get("folders") or []
    }
    signal_options = {
        f"{s['kind']} · {s['messages']:,}": s["kind"]
        for s in bounds.get("signal_kinds") or []
    }
    return ThunderbirdControls(
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
        account_select=mo.ui.multiselect(
            options=account_options, value=[], label="Accounts"
        ),
        folder_select=mo.ui.multiselect(
            options=folder_options, value=[], label="Folders"
        ),
        direction_select=mo.ui.multiselect(
            options={"sent": "sent", "received": "received", "unknown": "unknown"},
            value=[],
            label="Direction",
        ),
        signal_select=mo.ui.multiselect(
            options=signal_options, value=[], label="Signals"
        ),
        contact_search=mo.ui.text(value="", label="Contact contains"),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        mask_addrs=mo.ui.checkbox(label="Mask addresses", value=True),
        clear_contact=mo.ui.button(label="Clear contact lock"),
        narrate_btn=mo.ui.button(label="Narrate this view"),
        get_contact=get_contact,
        set_contact=set_contact,
    )


def render_thunderbird_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: ThunderbirdControls,
    dow_labels: dict[int, str],
) -> Any:
    c = controls
    if c.clear_contact.value:
        c.set_contact(None)

    filters = tbq.filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        account_keys=list(c.account_select.value or []),
        folder_ids=[int(x) for x in (c.folder_select.value or [])],
        directions=list(c.direction_select.value or []),
        signal_kinds=list(c.signal_select.value or []),
        contact_substr=c.contact_search.value or None,
        contact_exact=c.get_contact(),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = tbq.scoreboard(conn, filters, compare_previous=bool(c.compare.value))
    streak_df = tbq.message_streaks(conn, filters)
    monthly_df = tbq.monthly_volume(conn, filters)
    yearly_df = tbq.yearly_volume(conn, filters)
    heat_df = tbq.circadian_heatmap(conn, filters)
    cal_df = tbq.calendar_daily(conn, filters)
    senders_df = tbq.top_senders(conn, filters)
    recipients_df = tbq.top_recipients(conn, filters)
    domains_df = tbq.top_domains(conn, filters)
    sun_df = tbq.domain_sunburst(conn, filters)
    folders_df = tbq.folder_mix(conn, filters)
    accounts_df = tbq.account_mix(conn, filters)
    threads_df = tbq.thread_latency(conn, filters)
    att_df = tbq.attachment_extensions(conn, filters)
    sig_df = tbq.signal_mix(conn, filters)
    sig_m_df = tbq.signal_monthly(conn, filters)
    forgotten_df = tbq.forgotten_contacts(conn, filters, min_messages=1)
    comeback_df = tbq.comeback_contacts(conn, filters)
    bump_df = tbq.sender_rank_bump(conn, filters)
    scatter_df = tbq.contact_scatter(conn, filters)

    senders_for_lock = senders_df.copy()
    if c.mask_addrs.value:
        if not senders_df.empty and "contact" in senders_df.columns:
            senders_df = senders_df.copy()
            senders_df["contact"] = senders_df["contact"].map(tbq.mask_addr)
        if not recipients_df.empty and "contact" in recipients_df.columns:
            recipients_df = recipients_df.copy()
            recipients_df["contact"] = recipients_df["contact"].map(tbq.mask_addr)
        if not forgotten_df.empty and "contact" in forgotten_df.columns:
            forgotten_df = forgotten_df.copy()
            forgotten_df["contact"] = forgotten_df["contact"].map(tbq.mask_addr)
        if not comeback_df.empty and "contact" in comeback_df.columns:
            comeback_df = comeback_df.copy()
            comeback_df["contact"] = comeback_df["contact"].map(tbq.mask_addr)
        if not bump_df.empty and "contact" in bump_df.columns:
            bump_df = bump_df.copy()
            bump_df["contact"] = bump_df["contact"].map(tbq.mask_addr)
        if not scatter_df.empty and "contact" in scatter_df.columns:
            scatter_df = scatter_df.copy()
            scatter_df["contact"] = scatter_df["contact"].map(tbq.mask_addr)

    def _lock_sender(selected: Any) -> None:
        if selected is not None and len(selected) == 1:
            idx = selected.index[0]
            raw = senders_for_lock.loc[idx, "contact"]
            c.set_contact(str(raw))

    senders_table = mo.ui.table(senders_df, selection="single", on_change=_lock_sender)

    fig_monthly = (
        px.bar(
            monthly_df,
            x="year_month",
            y="messages",
            color="direction",
            title="Monthly volume by direction",
            barmode="stack",
        )
        if not monthly_df.empty
        else px.bar(title="No monthly data")
    )
    fig_yearly = (
        px.bar(
            yearly_df,
            x="year",
            y="messages",
            color="direction",
            title="Yearly volume",
            barmode="stack",
        )
        if not yearly_df.empty
        else px.bar(title="No yearly data")
    )
    fig_heat = panel_charts.circadian_heatmap(
        px,
        heat_df,
        z="messages",
        dow_labels=dow_labels,
        title="Messages by weekday × hour (Rome)",
        colorscale="Blues",
        empty_title="No circadian data",
        histfunc="sum",
        xaxis_title="",
        yaxis_title="",
    )
    fig_cal = panel_charts.iso_week_calendar(
        px,
        cal_df,
        z="messages",
        title="Daily volume calendar",
        colorscale="Greens",
        empty_title="No calendar data",
        facet_by_year=True,
        histfunc="sum",
    )
    fig_domains = (
        px.bar(
            domains_df, x="messages", y="domain", orientation="h", title="Top domains"
        )
        if not domains_df.empty
        else px.bar(title="No domains")
    )
    fig_sun = (
        px.sunburst(
            sun_df,
            path=["year", "month", "domain"],
            values="messages",
            title="Year → month → domain",
        )
        if not sun_df.empty
        else px.sunburst(title="No sunburst data")
    )
    fig_folders = (
        px.treemap(
            folders_df,
            path=["account_key", "folder"],
            values="messages",
            title="Folders",
        )
        if not folders_df.empty
        else px.treemap(title="No folders")
    )
    fig_accounts = (
        px.pie(accounts_df, names="account_key", values="messages", title="Accounts")
        if not accounts_df.empty
        else px.pie(title="No accounts")
    )
    fig_att = (
        px.bar(att_df, x="extension", y="files", title="Attachment extensions")
        if not att_df.empty
        else px.bar(title="No attachments")
    )
    fig_sig = (
        px.pie(sig_df, names="kind", values="messages", title="Signal mix")
        if not sig_df.empty
        else px.pie(title="No signals")
    )
    fig_sig_m = (
        px.bar(
            sig_m_df,
            x="year_month",
            y="messages",
            color="kind",
            title="Signals over time",
            barmode="stack",
        )
        if not sig_m_df.empty
        else px.bar(title="No signal timeline")
    )
    fig_bump = (
        px.line(
            bump_df,
            x="year",
            y="rank",
            color="contact",
            markers=True,
            title="Sender rank bump (lower is better)",
        )
        if not bump_df.empty
        else px.line(title="No bump data")
    )
    if not bump_df.empty:
        fig_bump.update_yaxes(autorange="reversed")
    fig_scatter = (
        px.scatter(
            scatter_df,
            x="received",
            y="sent",
            hover_name="contact",
            title="Contacts: received × sent",
        )
        if not scatter_df.empty
        else px.scatter(title="No contact scatter")
    )
    fig_thread = (
        px.scatter(
            threads_df,
            x="messages",
            y="span_hours",
            hover_name="sample_subject",
            title="Threads: depth × span (hours)",
        )
        if not threads_df.empty
        else px.scatter(title="No thread latency")
    )

    narrative_out = mo.md("")
    if c.narrate_btn.value:
        ctx = tbq.narrative_context(conn, filters)
        text, cached = llm_narrate(ctx, system=THUNDERBIRD_SYSTEM)
        suffix = " _(cached)_" if cached else ""
        narrative_out = mo.md(f"### Narrative{suffix}\n\n{text}")

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Thunderbird mail\n"
                f"{span}. Gloda metadata only (no bodies). "
                f"Identities via prefs.js / `--identity` / "
                f"`DATA_DUMPS_TB_IDENTITIES`."
            ),
            mo.hstack(
                [
                    c.year_start,
                    c.year_end,
                    c.compare,
                    c.mask_addrs,
                    c.clear_contact,
                    c.narrate_btn,
                ],
                justify="start",
                gap=1,
            ),
            mo.hstack(
                [
                    c.account_select,
                    c.folder_select,
                    c.direction_select,
                    c.signal_select,
                    c.contact_search,
                ],
                justify="start",
                gap=1,
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md("### Volume"),
            mo.vstack([mo.ui.plotly(fig_monthly), mo.ui.plotly(fig_yearly)], gap=1),
            mo.md("### Circadian · calendar"),
            mo.vstack([mo.ui.plotly(fig_heat), mo.ui.plotly(fig_cal)], gap=1),
            mo.md("### People — select a sender to lock"),
            mo.hstack(
                [
                    mo.vstack([mo.md("**Top senders (received)**"), senders_table]),
                    mo.vstack(
                        [mo.md("**Top recipients (sent)**"), mo.ui.table(recipients_df)]
                    ),
                ],
                gap=1,
            ),
            mo.md("### Relationships · arcs"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_scatter),
                    mo.ui.plotly(fig_bump),
                    mo.hstack(
                        [
                            mo.vstack(
                                [mo.md("**Forgotten**"), mo.ui.table(forgotten_df)]
                            ),
                            mo.vstack(
                                [mo.md("**Comebacks**"), mo.ui.table(comeback_df)]
                            ),
                        ],
                        gap=1,
                    ),
                ],
                gap=1,
            ),
            mo.md("### Domains"),
            mo.vstack([mo.ui.plotly(fig_domains), mo.ui.plotly(fig_sun)], gap=1),
            mo.md("### Folders · accounts"),
            mo.vstack([mo.ui.plotly(fig_folders), mo.ui.plotly(fig_accounts)], gap=1),
            mo.md("### Threads"),
            mo.vstack([mo.ui.plotly(fig_thread), mo.ui.table(threads_df)], gap=1),
            mo.md("### Attachments · signals"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_att),
                    mo.ui.plotly(fig_sig),
                    mo.ui.plotly(fig_sig_m),
                ],
                gap=1,
            ),
            narrative_out,
        ],
        gap=0.5,
    )
