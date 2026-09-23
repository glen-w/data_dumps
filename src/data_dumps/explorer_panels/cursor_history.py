"""Cursor History explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import cursor_history_queries as chq
from data_dumps.llm_client import narrate as llm_narrate

from . import charts as panel_charts


@dataclass
class CursorHistoryControls:
    year_start: Any
    year_end: Any
    source_select: Any
    project_select: Any
    title_search: Any
    text_search: Any
    hide_subagents: Any
    subagents_only: Any
    compare: Any
    clear_session: Any
    narrate_btn: Any
    get_session: Any
    set_session: Any


def make_cursor_history_controls(
    mo: Any, bounds: dict[str, Any]
) -> CursorHistoryControls:
    get_session, set_session = mo.state(None)
    return CursorHistoryControls(
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
        source_select=mo.ui.multiselect(
            options=bounds.get("source_kinds") or [],
            value=[],
            label="Source kind",
        ),
        project_select=mo.ui.multiselect(
            options=bounds.get("project_slugs") or [],
            value=[],
            label="Project",
        ),
        title_search=mo.ui.text(label="Title search", placeholder="substring…"),
        text_search=mo.ui.text(
            label="Message text search", placeholder="ILIKE substring…"
        ),
        hide_subagents=mo.ui.checkbox(label="Hide subagents", value=True),
        subagents_only=mo.ui.checkbox(label="Subagents only", value=False),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        clear_session=mo.ui.run_button(label="Clear session lock"),
        narrate_btn=mo.ui.run_button(label="Narrate this view"),
        get_session=get_session,
        set_session=set_session,
    )


def render_cursor_history_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: CursorHistoryControls,
    dow_labels: dict[int, str],
) -> Any:
    c = controls
    if c.clear_session.value:
        c.set_session(None)

    filters = chq.filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        source_kinds=list(c.source_select.value),
        project_slugs=list(c.project_select.value),
        title_search=c.title_search.value or "",
        text_search=c.text_search.value or "",
        session_id=c.get_session(),
        subagents_only=bool(c.subagents_only.value),
        hide_subagents=bool(c.hide_subagents.value)
        and not bool(c.subagents_only.value),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = chq.scoreboard(conn, filters, compare_previous=bool(c.compare.value))
    streak_df = chq.streak_stats(conn, filters)
    monthly_df = chq.messages_monthly(conn, filters)
    source_df = chq.source_kind_mix(conn, filters)
    tool_df = chq.tool_name_mix(conn, filters)
    tool_fam_df = chq.tool_family_mix(conn, filters)
    tools_m_df = chq.tools_monthly(conn, filters)
    tool_bump_df = chq.tool_family_rank_bump(conn, filters)
    role_df = chq.role_mix(conn, filters)
    mode_df = chq.unified_mode_mix(conn, filters)
    subagent_df = chq.subagent_type_mix(conn, filters)
    circ_df = chq.weekday_heatmap(conn, filters)
    cal_df = chq.calendar_daily(conn, filters)
    top_df = chq.top_sessions(conn, filters)
    scatter_df = chq.session_scatter(conn, filters)
    forgotten_df = chq.forgotten_sessions(conn, filters)
    comeback_df = chq.comeback_sessions(conn, filters)
    project_df = chq.project_mix(conn, filters)
    length_df = chq.message_length_buckets(conn, filters)
    depth_df = chq.session_depth(conn, filters)
    density_df = chq.tool_density(conn, filters)
    latency_df = chq.reply_latency(conn, filters)
    search_df = chq.search_messages(conn, filters)
    thread_df = chq.session_messages(conn, filters)

    def _lock_session(selected: Any) -> None:
        if selected is not None and len(selected) == 1:
            c.set_session(selected.iloc[0]["session_id"])

    session_table = mo.ui.table(top_df, selection="single", on_change=_lock_session)
    search_table = (
        mo.ui.table(search_df, selection="single", on_change=_lock_session)
        if not search_df.empty
        else None
    )

    fig_monthly = (
        px.bar(monthly_df, x="year_month", y="messages", title="Messages by month")
        if not monthly_df.empty
        else px.bar(title="No messages in range")
    )
    fig_source = (
        px.pie(
            source_df,
            names="source_kind",
            values="sessions",
            title="Sessions by source",
        )
        if not source_df.empty
        else px.pie(title="No source mix")
    )
    fig_tools = (
        px.bar(
            tool_df.head(15),
            x="tool_calls",
            y="tool_name",
            orientation="h",
            title="Top tool calls",
        )
        if not tool_df.empty
        else px.bar(title="No tool calls")
    )
    if not tool_df.empty:
        fig_tools.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_tool_fam = (
        px.pie(
            tool_fam_df,
            names="tool_family",
            values="tool_calls",
            title="Tool family mix",
        )
        if not tool_fam_df.empty
        else px.pie(title="No tool families")
    )
    fig_tools_stack = (
        px.area(
            tools_m_df,
            x="year_month",
            y="tool_calls",
            color="tool_family",
            title="Tool family stack over time",
        )
        if not tools_m_df.empty
        else px.area(title="No tool timeline")
    )
    fig_tool_bump = (
        px.line(
            tool_bump_df,
            x="year",
            y="rank",
            color="tool_family",
            markers=True,
            title="Tool-family rank bump (lower is hotter)",
        )
        if not tool_bump_df.empty
        else px.line(title="No tool ranks")
    )
    if not tool_bump_df.empty:
        fig_tool_bump.update_yaxes(autorange="reversed", dtick=1)
    fig_roles = (
        px.bar(role_df, x="messages", y="role", orientation="h", title="Role mix")
        if not role_df.empty
        else px.bar(title="No roles")
    )
    fig_modes = (
        px.bar(
            mode_df,
            x="sessions",
            y="unified_mode",
            orientation="h",
            title="Unified mode mix",
        )
        if not mode_df.empty
        else px.bar(title="No modes")
    )
    if not mode_df.empty:
        fig_modes.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_projects = (
        px.bar(
            project_df.head(15),
            x="sessions",
            y="project_slug",
            orientation="h",
            title="Sessions by project",
        )
        if not project_df.empty
        else px.bar(title="No projects")
    )
    if not project_df.empty:
        fig_projects.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_length = (
        px.bar(length_df, x="bucket", y="messages", title="User prompt length")
        if not length_df.empty
        else px.bar(title="No length data")
    )
    fig_depth = (
        px.bar(depth_df, x="bucket", y="sessions", title="Session depth (messages)")
        if not depth_df.empty
        else px.bar(title="No depth data")
    )
    fig_density = (
        px.bar(
            density_df,
            x="bucket",
            y="sessions",
            title="Tool density (tools / message)",
        )
        if not density_df.empty
        else px.bar(title="No density data")
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circ_df,
        z="messages",
        dow_labels=dow_labels,
        title="Messages (weekday × hour, Europe/Paris)",
        empty_title="No circadian data",
        xaxis_title="",
        yaxis_title="",
    )
    fig_cal = panel_charts.iso_week_calendar(
        px,
        cal_df,
        z="events",
        title="Cursor calendar (weekday × ISO week)",
        empty_title="No calendar data",
    )
    fig_scatter = (
        px.scatter(
            scatter_df,
            x="n_messages",
            y="n_tools",
            size="span_days",
            color="source_kind",
            hover_name="title",
            hover_data=["session_id", "is_subagent"],
            title="Session scatter: messages × tool calls (size = span days)",
            log_x=True,
            log_y=True,
        )
        if not scatter_df.empty
        else px.scatter(title="No sessions to scatter")
    )

    narrative_block: list[Any] = []
    if c.narrate_btn.value:
        text, cached = llm_narrate(chq.narrative_context(conn, filters))
        suffix = " _(cached)_" if cached else ""
        narrative_block = [mo.md(f"### Narrative{suffix}"), mo.md(text)]

    sections: list[Any] = [
        mo.md("# Cursor History"),
        chip_row,
        mo.hstack(
            [
                c.year_start,
                c.year_end,
                c.source_select,
                c.project_select,
                c.title_search,
                c.text_search,
            ],
            wrap=True,
            gap=0.5,
        ),
        mo.hstack(
            [
                c.hide_subagents,
                c.subagents_only,
                c.compare,
                c.clear_session,
                c.narrate_btn,
            ],
            wrap=True,
            gap=0.5,
        ),
        mo.md("## Scoreboard"),
        mo.ui.table(score_df),
        mo.md("## Streaks"),
        mo.ui.table(streak_df),
        mo.md("## Volume"),
        mo.ui.plotly(fig_monthly),
        mo.ui.plotly(fig_source),
        mo.ui.plotly(fig_roles),
        mo.md("## Tools & projects"),
        mo.ui.plotly(fig_tools),
        mo.ui.plotly(fig_tool_fam),
        mo.ui.plotly(fig_tools_stack),
        mo.ui.plotly(fig_tool_bump),
        mo.ui.plotly(fig_projects),
        mo.ui.plotly(fig_modes),
        mo.md("## Depth & prompt quality"),
        mo.ui.plotly(fig_depth),
        mo.ui.plotly(fig_length),
        mo.ui.plotly(fig_density),
        mo.md("## Reply latency"),
        mo.ui.table(latency_df),
        mo.md("## Rhythm"),
        mo.ui.plotly(fig_circ),
        mo.ui.plotly(fig_cal),
    ]
    if not subagent_df.empty:
        sections.extend(
            [
                mo.md("## Subagent types"),
                mo.ui.table(subagent_df),
            ]
        )
    if search_table is not None:
        sections.extend(
            [
                mo.md("## Search hits"),
                mo.md("_Click a row to lock that session._"),
                search_table,
            ]
        )
    sections.extend(
        [
            mo.md("## Sessions"),
            mo.md("_Click a row to lock the transcript below._"),
            session_table,
            mo.ui.plotly(fig_scatter),
            mo.md("## Forgotten"),
            mo.ui.table(forgotten_df),
            mo.md("## Comebacks (long-span sessions)"),
            mo.ui.table(comeback_df),
        ]
    )
    if filters.session_id:
        sections.extend(
            [
                mo.md(f"## Transcript · `{filters.session_id[:8]}…`"),
                mo.ui.table(thread_df),
            ]
        )
    sections.extend(narrative_block)
    return mo.vstack(sections, gap=1.0)
