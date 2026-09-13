"""LinkedIn explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import linkedin_queries as liq

from . import charts as panel_charts


@dataclass
class LinkedInControls:
    year_start: Any
    year_end: Any
    compare: Any
    clear_conversation: Any
    get_conversation: Any
    set_conversation: Any


def make_linkedin_controls(mo: Any, bounds: dict[str, Any]) -> LinkedInControls:
    get_conversation, set_conversation = mo.state(None)
    return LinkedInControls(
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
        clear_conversation=mo.ui.button(label="Clear conversation lock"),
        get_conversation=get_conversation,
        set_conversation=set_conversation,
    )


def render_linkedin_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: LinkedInControls,
    dow_labels: dict[int, str],
) -> Any:
    c = controls
    if c.clear_conversation.value:
        c.set_conversation(None)

    filters = liq.filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        conversation=c.get_conversation(),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = liq.scoreboard(conn, filters, compare_previous=bool(c.compare.value))
    streak_df = liq.message_streaks(conn, filters)
    by_year = liq.connections_by_year(conn, filters)
    companies_df = liq.top_connection_companies(conn, filters)
    titles_df = liq.top_connection_titles(conn, filters)
    career_df = liq.career_timeline(conn)
    conv_df = liq.messages_by_conversation(conn, filters)
    me_df = liq.me_vs_them(conn, filters)
    monthly_df = liq.monthly_messages(conn, filters)
    calendar_df = liq.calendar_daily(conn, filters)
    circadian_df = liq.circadian_heatmap(conn, filters)
    mix_df = liq.activity_mix(conn, filters)
    follows_df = liq.company_follows(conn, filters)
    forgotten_df = liq.forgotten_conversations(conn, filters, min_messages=1)
    comeback_df = liq.comeback_conversations(conn, filters)
    scatter_df = liq.conversation_scatter(conn, filters)
    bump_df = liq.conversation_rank_bump(conn, filters)
    invite_df = liq.invitation_mix(conn, filters)
    endorse_df = liq.endorsement_counts(conn, filters)
    events_df = liq.events_summary(conn, filters)
    learning_df = liq.learning_summary(conn, filters)

    def _lock_conv_from_table(selected: Any) -> None:
        if selected is not None and len(selected) == 1:
            c.set_conversation(selected.iloc[0]["conversation"])

    conv_table = mo.ui.table(
        conv_df, selection="single", on_change=_lock_conv_from_table
    )

    fig_conn = (
        px.bar(by_year, x="year", y="connections", title="Connections added by year")
        if not by_year.empty
        else px.bar(title="No connections in this range")
    )
    fig_co = (
        px.bar(
            companies_df,
            x="connections",
            y="company",
            orientation="h",
            title="Top companies among connections",
        )
        if not companies_df.empty
        else px.bar(title="No company data")
    )
    fig_title = (
        px.bar(
            titles_df,
            x="connections",
            y="title",
            orientation="h",
            title="Top titles among connections",
        )
        if not titles_df.empty
        else px.bar(title="No title data")
    )
    if me_df.empty:
        fig_me = px.bar(title="No messages")
    else:
        me_long = me_df.melt(
            id_vars=["year"],
            value_vars=["me", "them"],
            var_name="who",
            value_name="messages",
        )
        fig_me = px.bar(
            me_long,
            x="year",
            y="messages",
            color="who",
            barmode="group",
            title="Messages: you vs others",
        )
    fig_monthly = (
        px.bar(
            monthly_df,
            x="year_month",
            y="messages",
            title="Monthly messages",
        )
        if not monthly_df.empty
        else px.bar(title="No monthly messages")
    )
    fig_cal = panel_charts.iso_week_calendar(
        px,
        calendar_df,
        z="events",
        title="Messages (weekday × ISO week)",
        empty_title="No message calendar",
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circadian_df,
        z="events",
        dow_labels=dow_labels,
        title="Messages by weekday × hour (Europe/Rome)",
        empty_title="No circadian data",
        xaxis_title="",
        yaxis_title="",
    )
    fig_mix = (
        px.bar(
            mix_df,
            x="year",
            y="events",
            color="kind",
            barmode="stack",
            title="Feed activity by year",
        )
        if not mix_df.empty
        else px.bar(title="No reactions/shares/comments")
    )
    fig_scatter = (
        px.scatter(
            scatter_df,
            x="messages",
            y="me_pct",
            hover_name="conversation",
            title="Conversations: volume × your share %",
        )
        if not scatter_df.empty
        else px.scatter(title="No conversation scatter")
    )

    def _lock_from_scatter(trace: Any) -> None:
        pts = getattr(trace, "points", None) or []
        if not pts:
            return
        idx = (
            pts[0].get("point_index")
            if isinstance(pts[0], dict)
            else getattr(pts[0], "point_index", None)
        )
        if idx is not None and not scatter_df.empty and idx < len(scatter_df):
            c.set_conversation(scatter_df.iloc[int(idx)]["conversation"])

    scatter_plot = mo.ui.plotly(fig_scatter, on_change=_lock_from_scatter)

    fig_bump = (
        px.line(
            bump_df,
            x="year",
            y="rank",
            color="conversation",
            markers=True,
            title="Conversation rank bump (lower is better)",
        )
        if not bump_df.empty
        else px.line(title="No bump data")
    )
    if not bump_df.empty:
        fig_bump.update_yaxes(autorange="reversed")

    career_chart = career_df.copy()
    if not career_chart.empty:
        career_chart["start_y"] = career_chart["start_year"].fillna(
            career_chart["end_year"]
        )
        career_chart["end_y"] = career_chart["end_year"].fillna(
            career_chart["start_year"]
        )
        career_chart = career_chart.dropna(subset=["start_y"])
        career_chart["end_y"] = career_chart["end_y"].fillna(
            career_chart["start_y"] + 1
        )
        career_chart["label"] = (
            career_chart["org"].fillna("?") + " · " + career_chart["detail"].fillna("")
        )
    fig_career = (
        px.timeline(
            career_chart.assign(
                start=pd.to_datetime(
                    career_chart["start_y"].astype(int).astype(str) + "-01-01"
                ),
                finish=pd.to_datetime(
                    career_chart["end_y"].astype(int).astype(str) + "-12-31"
                ),
            ),
            x_start="start",
            x_end="finish",
            y="label",
            color="kind",
            title="Career timeline",
        )
        if not career_chart.empty
        else px.bar(title="No career rows")
    )

    extra_sections: list[Any] = []
    if not invite_df.empty:
        fig_inv = px.bar(
            invite_df,
            x="year",
            y="invites",
            color="direction",
            barmode="stack",
            title="Invitations by year",
        )
        extra_sections.extend([mo.md("### Invitations"), mo.ui.plotly(fig_inv)])
    if not endorse_df.empty and int(endorse_df["count"].sum()) > 0:
        fig_end = px.bar(endorse_df, x="kind", y="count", title="Endorsements")
        extra_sections.extend([mo.md("### Endorsements"), mo.ui.plotly(fig_end)])
    if not events_df.empty:
        extra_sections.extend([mo.md("### Events"), mo.ui.table(events_df)])
    if not learning_df.empty:
        extra_sections.extend([mo.md("### Learning"), mo.ui.table(learning_df)])

    who = bounds.get("display_name") or "you"
    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## LinkedIn explorer\n"
                f"{span}. Viewing as **{who}**. "
                "IPs, emails, phones, ads, and identity documents were dropped at ingest."
            ),
            mo.hstack(
                [
                    c.year_start,
                    c.year_end,
                    c.compare,
                    c.clear_conversation,
                ],
                justify="start",
                gap=1,
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md("### Network"),
            mo.vstack([mo.ui.plotly(fig_conn), mo.ui.plotly(fig_co)], gap=1),
            mo.ui.plotly(fig_title),
            mo.md("### Career"),
            mo.ui.plotly(fig_career),
            mo.ui.table(career_df),
            mo.md("### Messages — select a row or click scatter to lock"),
            mo.vstack(
                [mo.ui.plotly(fig_me), mo.ui.plotly(fig_monthly), conv_table],
                gap=1,
            ),
            mo.vstack([mo.ui.plotly(fig_cal), mo.ui.plotly(fig_circ)], gap=1),
            mo.md("### Relationships · arcs"),
            mo.vstack(
                [
                    scatter_plot,
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
            mo.md("### Activity · company follows"),
            mo.vstack([mo.ui.plotly(fig_mix), mo.ui.table(follows_df)], gap=1),
            *extra_sections,
        ],
        gap=0.5,
    )
