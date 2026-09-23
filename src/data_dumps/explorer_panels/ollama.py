"""Ollama explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import ollama_queries as olq
from data_dumps.llm_client import narrate as llm_narrate
from data_dumps.wordcloud_util import frequencies_from_frame, wordcloud_png

from . import charts as panel_charts


@dataclass
class OllamaControls:
    year_start: Any
    year_end: Any
    model_select: Any
    title_search: Any
    compare: Any
    clear_chat: Any
    narrate_btn: Any
    get_chat: Any
    set_chat: Any


def make_ollama_controls(mo: Any, bounds: dict[str, Any]) -> OllamaControls:
    get_chat, set_chat = mo.state(None)
    return OllamaControls(
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
        model_select=mo.ui.multiselect(
            options=bounds.get("models") or [],
            value=[],
            label="Model",
        ),
        title_search=mo.ui.text(label="Title search", placeholder="substring…"),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        clear_chat=mo.ui.run_button(label="Clear chat lock"),
        narrate_btn=mo.ui.run_button(label="Narrate this view"),
        get_chat=get_chat,
        set_chat=set_chat,
    )


def render_ollama_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: OllamaControls,
    dow_labels: dict[int, str],
) -> Any:
    c = controls
    if c.clear_chat.value:
        c.set_chat(None)

    filters = olq.filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        models=list(c.model_select.value),
        title_search=c.title_search.value or "",
        chat_id=c.get_chat(),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = olq.scoreboard(conn, filters, compare_previous=bool(c.compare.value))
    streak_df = olq.streak_stats(conn, filters)
    monthly_df = olq.messages_monthly(conn, filters)
    model_df = olq.model_mix(conn, filters)
    stack_df = olq.model_stack(conn, filters)
    bump_df = olq.model_rank_bump(conn, filters)
    thinking_df = olq.thinking_by_model(conn, filters)
    tool_df = olq.tool_name_mix(conn, filters)
    role_df = olq.role_mix(conn, filters)
    length_df = olq.message_length_buckets(conn, filters)
    depth_df = olq.chat_depth(conn, filters)
    circ_df = olq.weekday_heatmap(conn, filters)
    cal_df = olq.calendar_daily(conn, filters)
    top_df = olq.top_chats(conn, filters)
    scatter_df = olq.chat_scatter(conn, filters)
    forgotten_df = olq.forgotten_chats(conn, filters)
    comeback_df = olq.comeback_chats(conn, filters)
    latency_df = olq.reply_latency(conn, filters)
    attach_df = olq.attachment_mix(conn, filters)
    attach_m_df = olq.attachments_monthly(conn, filters)
    thread_df = olq.chat_messages(conn, filters)
    token_user = olq.message_tokens(conn, filters, role="user")
    token_asst = olq.message_tokens(conn, filters, role="assistant")
    bigram_df = olq.user_bigrams(conn, filters)

    def _lock_chat(selected: Any) -> None:
        if selected is not None and len(selected) == 1:
            c.set_chat(selected.iloc[0]["chat_id"])

    chat_table = mo.ui.table(top_df, selection="single", on_change=_lock_chat)

    fig_monthly = (
        px.bar(monthly_df, x="year_month", y="messages", title="Messages by month")
        if not monthly_df.empty
        else px.bar(title="No messages in range")
    )
    fig_models = (
        px.bar(
            model_df.head(15),
            x="messages",
            y="model_name",
            orientation="h",
            title="Assistant messages by model",
        )
        if not model_df.empty
        else px.bar(title="No models")
    )
    if not model_df.empty:
        fig_models.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_stack = (
        px.area(
            stack_df,
            x="year_month",
            y="messages",
            color="model_family",
            title="Model family stack",
        )
        if not stack_df.empty
        else px.area(title="No model stack")
    )
    fig_bump = (
        px.line(
            bump_df,
            x="year",
            y="rank",
            color="model_family",
            markers=True,
            title="Model-family rank bump (lower is hotter)",
        )
        if not bump_df.empty
        else px.line(title="No model ranks")
    )
    if not bump_df.empty:
        fig_bump.update_yaxes(autorange="reversed", dtick=1)
    fig_thinking = (
        px.bar(
            thinking_df,
            x="thinking_chars",
            y="model_name",
            orientation="h",
            title="Thinking characters by model",
        )
        if not thinking_df.empty
        else px.bar(title="No thinking text")
    )
    if not thinking_df.empty:
        fig_thinking.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_tools = (
        px.bar(
            tool_df.head(15),
            x="tool_calls",
            y="tool_name",
            orientation="h",
            title="Tool calls",
        )
        if not tool_df.empty
        else px.bar(title="No tool calls")
    )
    if not tool_df.empty:
        fig_tools.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_roles = (
        px.bar(role_df, x="messages", y="role", orientation="h", title="Role mix")
        if not role_df.empty
        else px.bar(title="No roles")
    )
    fig_length = (
        px.bar(length_df, x="bucket", y="messages", title="User prompt length")
        if not length_df.empty
        else px.bar(title="No length data")
    )
    fig_depth = (
        px.bar(depth_df, x="bucket", y="chats", title="Chat depth (messages)")
        if not depth_df.empty
        else px.bar(title="No depth data")
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
        title="Ollama calendar (weekday × ISO week)",
        empty_title="No calendar data",
    )
    fig_scatter = (
        px.scatter(
            scatter_df,
            x="n_messages",
            y="n_chars",
            size="span_days",
            color="model_family",
            hover_name="title",
            hover_data=["chat_id"],
            title="Chat scatter: messages × characters (size = span days)",
        )
        if not scatter_df.empty
        else px.scatter(title="No chats to scatter")
    )
    fig_attach = (
        px.bar(
            attach_df,
            x="attachments",
            y="extension",
            orientation="h",
            title="Attachments by extension",
        )
        if not attach_df.empty
        else px.bar(title="No attachments")
    )
    if not attach_df.empty:
        fig_attach.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_attach_m = (
        px.bar(
            attach_m_df,
            x="year_month",
            y="bytes",
            title="Attachment bytes by month",
        )
        if not attach_m_df.empty
        else px.bar(title="No attachment timeline")
    )

    def _cloud_block(png: bytes | None, caption: str) -> Any:
        if png is None:
            return mo.md(f"**{caption}**\n\n_Not enough words in this filter._")
        return mo.vstack(
            [mo.md(f"**{caption}**"), mo.image(src=png, alt=caption)],
            gap=0.25,
        )

    narrative_block: list[Any] = []
    if c.narrate_btn.value:
        text, cached = llm_narrate(olq.narrative_context(conn, filters))
        suffix = " _(cached)_" if cached else ""
        narrative_block = [mo.md(f"### Narrative{suffix}"), mo.md(text)]

    sections: list[Any] = [
        mo.md("# Ollama"),
        chip_row,
        mo.hstack(
            [c.year_start, c.year_end, c.model_select, c.title_search],
            wrap=True,
            gap=0.5,
        ),
        mo.hstack(
            [c.compare, c.clear_chat, c.narrate_btn],
            wrap=True,
            gap=0.5,
        ),
        mo.md("## Scoreboard"),
        mo.ui.table(score_df),
        mo.md("## Streaks"),
        mo.ui.table(streak_df),
        mo.md("## Volume"),
        mo.ui.plotly(fig_monthly),
        mo.ui.plotly(fig_roles),
        mo.md("## Models"),
        mo.ui.plotly(fig_models),
        mo.ui.plotly(fig_stack),
        mo.ui.plotly(fig_bump),
        mo.ui.plotly(fig_thinking),
        mo.md("## Depth"),
        mo.ui.plotly(fig_depth),
        mo.ui.plotly(fig_length),
        mo.md("## Reply latency"),
        mo.ui.table(latency_df),
        mo.md("## Tools"),
        mo.ui.plotly(fig_tools),
        mo.md("## Attachments"),
        mo.ui.plotly(fig_attach),
        mo.ui.plotly(fig_attach_m),
        mo.md("## Rhythm"),
        mo.ui.plotly(fig_circ),
        mo.ui.plotly(fig_cal),
        mo.md("## Chats"),
        mo.md("_Click a row to lock the transcript below._"),
        chat_table,
        mo.ui.plotly(fig_scatter),
        mo.md("## Forgotten"),
        mo.ui.table(forgotten_df),
        mo.md("## Comebacks (long-span chats)"),
        mo.ui.table(comeback_df),
        mo.md("## Language"),
        mo.md("Word clouds from message text. They follow the filters above."),
        _cloud_block(wordcloud_png(frequencies_from_frame(token_user)), "You"),
        _cloud_block(wordcloud_png(frequencies_from_frame(token_asst)), "Assistant"),
        _cloud_block(wordcloud_png(frequencies_from_frame(bigram_df)), "Your bigrams"),
    ]
    if filters.chat_id:
        sections.extend(
            [
                mo.md(f"## Transcript · `{filters.chat_id[:8]}…`"),
                mo.ui.table(thread_df),
            ]
        )
    sections.extend(narrative_block)
    return mo.vstack(sections, gap=1.0)
