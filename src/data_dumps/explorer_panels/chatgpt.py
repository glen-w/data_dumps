"""ChatGPT explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from data_dumps import chatgpt_queries as cgq
from data_dumps.llm_client import narrate as llm_narrate
from data_dumps.wordcloud_util import frequencies_from_frame, wordcloud_png

from . import charts as panel_charts


@dataclass
class ChatGPTControls:
    year_start: Any
    year_end: Any
    role_select: Any
    model_select: Any
    content_select: Any
    title_search: Any
    shared_only: Any
    compare: Any
    clear_conversation: Any
    narrate_btn: Any
    get_conversation: Any
    set_conversation: Any


def make_chatgpt_controls(mo: Any, bounds: dict[str, Any]) -> ChatGPTControls:
    get_conversation, set_conversation = mo.state(None)
    return ChatGPTControls(
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
        role_select=mo.ui.multiselect(
            options=bounds.get("roles") or [], value=[], label="Role"
        ),
        model_select=mo.ui.multiselect(
            options=bounds.get("model_families") or [],
            value=[],
            label="Model family",
        ),
        content_select=mo.ui.multiselect(
            options=bounds.get("content_types") or [],
            value=[],
            label="Content type",
        ),
        title_search=mo.ui.text(label="Title search", placeholder="substring…"),
        shared_only=mo.ui.checkbox(label="Shared only", value=False),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        clear_conversation=mo.ui.run_button(label="Clear conversation lock"),
        narrate_btn=mo.ui.run_button(label="Narrate this view"),
        get_conversation=get_conversation,
        set_conversation=set_conversation,
    )


def render_chatgpt_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: ChatGPTControls,
    dow_labels: dict[int, str],
) -> Any:
    c = controls
    if c.clear_conversation.value:
        c.set_conversation(None)

    filters = cgq.filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        roles=list(c.role_select.value),
        model_families=list(c.model_select.value),
        content_types=list(c.content_select.value),
        title_search=c.title_search.value or "",
        conversation_id=c.get_conversation(),
        shared_only=bool(c.shared_only.value),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = cgq.scoreboard(conn, filters, compare_previous=bool(c.compare.value))
    streak_df = cgq.streak_stats(conn, filters)
    monthly_df = cgq.messages_monthly(conn, filters)
    model_df = cgq.model_mix(conn, filters)
    model_monthly_df = cgq.model_family_monthly(conn, filters)
    content_df = cgq.content_type_mix(conn, filters)
    role_df = cgq.role_mix(conn, filters)
    circ_df = cgq.weekday_heatmap(conn, filters)
    cal_df = cgq.calendar_daily(conn, filters)
    top_df = cgq.top_conversations(conn, filters)
    scatter_df = cgq.conversation_scatter(conn, filters)
    forgotten_df = cgq.forgotten_conversations(conn, filters)
    comeback_df = cgq.comeback_conversations(conn, filters)
    bump_df = cgq.model_rank_bump(conn, filters)
    latency_df = cgq.reply_latency(conn, filters)
    latency_monthly_df = cgq.reply_latency_monthly(conn, filters)
    gizmo_df = cgq.gizmo_usage(conn, filters)
    assets_df = cgq.asset_extension_mix(conn)
    shared_df = cgq.shared_list(conn, filters)
    tokens_df = cgq.title_tokens(conn, filters)
    token_user = cgq.message_tokens(conn, filters, role="user")
    token_asst = cgq.message_tokens(conn, filters, role="assistant")
    token_all = cgq.message_tokens(conn, filters, role="all")
    bigram_df = cgq.user_bigrams(conn, filters)
    distinctive_df = cgq.distinctive_terms(conn, filters)
    thread_df = cgq.conversation_messages(conn, filters)

    fig_monthly = (
        px.bar(
            monthly_df,
            x="year_month",
            y="messages",
            title="Messages by month",
        )
        if not monthly_df.empty
        else px.bar(title="No messages in range")
    )
    fig_user_chars = (
        px.bar(
            monthly_df,
            x="year_month",
            y="user_chars",
            title="User characters by month",
        )
        if not monthly_df.empty
        else px.bar(title="No user chars")
    )
    fig_models = (
        px.bar(
            model_df.head(15),
            x="messages",
            y="model_slug",
            orientation="h",
            color="model_family",
            title="Assistant messages by model",
        )
        if not model_df.empty
        else px.bar(title="No model mix")
    )
    if not model_df.empty:
        fig_models.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_model_stack = (
        px.area(
            model_monthly_df,
            x="year_month",
            y="messages",
            color="model_family",
            title="Model family stack over time",
        )
        if not model_monthly_df.empty
        else px.area(title="No model timeline")
    )
    fig_content = (
        px.pie(
            content_df,
            names="content_type",
            values="messages",
            title="Content types",
        )
        if not content_df.empty
        else px.pie(title="No content types")
    )
    fig_roles = (
        px.bar(
            role_df,
            x="messages",
            y="role",
            orientation="h",
            title="Role mix",
        )
        if not role_df.empty
        else px.bar(title="No roles")
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
        title="Chat calendar (weekday × ISO week)",
        empty_title="No calendar data",
    )
    fig_scatter = (
        px.scatter(
            scatter_df,
            x="n_messages",
            y="user_chars",
            size="span_days",
            color="default_model_family",
            hover_name="title",
            hover_data=["conversation_id", "n_thoughts", "n_images", "is_shared"],
            title="Conversation scatter: depth × your words (size = span days)",
            log_x=True,
            log_y=True,
        )
        if not scatter_df.empty
        else px.scatter(title="No conversations to scatter")
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

    fig_latency = (
        px.line(
            latency_monthly_df,
            x="year_month",
            y="median_minutes",
            markers=True,
            title="Median user→assistant latency (minutes)",
        )
        if not latency_monthly_df.empty
        else px.line(title="No latency series")
    )
    fig_gizmo = (
        px.bar(
            gizmo_df.head(15),
            x="conversations",
            y="gizmo_id",
            orientation="h",
            title="Projects / GPTs (gizmo_id)",
        )
        if not gizmo_df.empty
        else px.bar(title="No project/GPT ids")
    )
    if not gizmo_df.empty:
        fig_gizmo.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_assets = (
        px.bar(
            assets_df.head(20),
            x="files",
            y="file_extension",
            color="source",
            orientation="h",
            title="Library / conversation assets by extension",
        )
        if not assets_df.empty
        else px.bar(title="No assets")
    )
    if not assets_df.empty:
        fig_assets.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_tokens = (
        px.bar(
            tokens_df.head(25),
            x="uses",
            y="token",
            orientation="h",
            title="Title tokens",
        )
        if not tokens_df.empty
        else px.bar(title="No title tokens")
    )
    if not tokens_df.empty:
        fig_tokens.update_layout(yaxis={"categoryorder": "total ascending"})

    def _cloud_block(png: bytes | None, caption: str) -> Any:
        if png is None:
            return mo.md(f"**{caption}**\n\n_Not enough words in this filter._")
        return mo.vstack(
            [mo.md(f"**{caption}**"), mo.image(src=png, alt=caption)],
            gap=0.25,
        )

    fig_distinctive = (
        px.bar(
            distinctive_df,
            x="score",
            y="term",
            orientation="h",
            title="Distinctive terms (positive = more you, negative = more assistant)",
            hover_data=["n_user", "n_assistant"],
        )
        if not distinctive_df.empty
        else px.bar(title="No distinctive terms")
    )
    if not distinctive_df.empty:
        fig_distinctive.update_layout(yaxis={"categoryorder": "total ascending"})

    def _lock_conversation(selected: Any) -> None:
        if selected is not None and len(selected) == 1:
            cid = selected.iloc[0].get("conversation_id")
            if cid:
                c.set_conversation(str(cid))

    top_table = mo.ui.table(top_df, selection="single", on_change=_lock_conversation)

    narrative_block: list[Any] = []
    if c.narrate_btn.value:
        text, cached = llm_narrate(cgq.narrative_context(conn, filters))
        suffix = " _(cached)_" if cached else ""
        narrative_block = [mo.md(f"### Narrative{suffix}"), mo.md(text)]

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    lock_note = (
        f"Locked conversation `{filters.conversation_id}`."
        if filters.conversation_id
        else "Select a row in Top conversations to drill into one thread."
    )

    sections: list[Any] = [
        mo.md(
            f"## ChatGPT\n"
            f"{span}. Conversations + messages (+ thinking/multimodal), model eras, "
            f"shared links, library assets. Email/phone dropped; ``.dat`` / chat.html "
            f"bytes left out of raw/. Message text kept."
        ),
        mo.hstack(
            [
                c.year_start,
                c.year_end,
                c.role_select,
                c.model_select,
                c.content_select,
            ],
            justify="start",
            gap=1,
        ),
        mo.hstack(
            [
                c.title_search,
                c.shared_only,
                c.compare,
                c.clear_conversation,
                c.narrate_btn,
            ],
            justify="start",
            gap=1,
        ),
        chip_row,
        mo.md("### Scoreboard"),
        mo.ui.table(score_df),
        mo.md("### Streaks"),
        mo.ui.table(streak_df),
        mo.md("### Volume over time"),
        mo.vstack([mo.ui.plotly(fig_monthly), mo.ui.plotly(fig_user_chars)], gap=1),
        mo.md("### Models"),
        mo.hstack([mo.ui.plotly(fig_models), mo.ui.plotly(fig_model_stack)], gap=1),
        mo.ui.plotly(fig_bump),
        mo.md("### Roles & content"),
        mo.hstack([mo.ui.plotly(fig_roles), mo.ui.plotly(fig_content)], gap=1),
        mo.md("### Rhythm"),
        mo.vstack([mo.ui.plotly(fig_circ), mo.ui.plotly(fig_cal)], gap=1),
        mo.md("### Conversation observatory"),
        mo.md(lock_note),
        top_table,
        mo.ui.plotly(fig_scatter),
        mo.md("### Forgotten & comebacks"),
        mo.hstack(
            [
                mo.vstack(
                    [mo.md("**Silent ≥2y (deep threads)**"), mo.ui.table(forgotten_df)],
                    gap=0.5,
                ),
                mo.vstack(
                    [mo.md("**Comebacks (≥90d gap)**"), mo.ui.table(comeback_df)],
                    gap=0.5,
                ),
            ],
            gap=1,
        ),
        mo.md("### Latency"),
        mo.ui.table(latency_df),
        mo.ui.plotly(fig_latency),
        mo.md("### Projects / GPTs"),
        mo.ui.plotly(fig_gizmo),
        mo.md("### Language"),
        mo.md(
            "Word clouds from message text (thoughts excluded). "
            "They follow the filters above."
        ),
        _cloud_block(wordcloud_png(frequencies_from_frame(token_all)), "All messages"),
        mo.hstack(
            [
                _cloud_block(wordcloud_png(frequencies_from_frame(token_user)), "You"),
                _cloud_block(
                    wordcloud_png(frequencies_from_frame(token_asst)), "Assistant"
                ),
            ],
            gap=1,
        ),
        _cloud_block(wordcloud_png(frequencies_from_frame(bigram_df)), "Your bigrams"),
        mo.ui.plotly(fig_distinctive),
        mo.md("### Shared + title tokens"),
        mo.hstack(
            [
                mo.vstack([mo.md("**Shared**"), mo.ui.table(shared_df)], gap=0.5),
                mo.ui.plotly(fig_tokens),
            ],
            gap=1,
        ),
        mo.md("### Assets (metadata only)"),
        mo.ui.plotly(fig_assets),
    ]

    if filters.conversation_id:
        sections.extend(
            [
                mo.md("### Locked thread"),
                mo.ui.table(thread_df),
            ]
        )
    sections.extend(narrative_block)

    return mo.vstack(sections, gap=1)
