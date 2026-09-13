"""Telegram explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import plotly.graph_objects as go

from data_dumps import telegram_queries as tgq
from data_dumps.llm_client import TELEGRAM_SYSTEM
from data_dumps.llm_client import narrate as llm_narrate

from . import charts as panel_charts


@dataclass
class TelegramControls:
    year_start: Any
    year_end: Any
    chat_type: Any
    event_select: Any
    media_select: Any
    compare: Any
    include_bots: Any
    include_groups: Any
    people_btn: Any
    clear_types: Any
    clear_chat: Any
    clear_media: Any
    narrate_btn: Any
    get_chat_name: Any
    set_chat_name: Any
    get_types_override: Any
    set_types_override: Any
    get_media_override: Any
    set_media_override: Any


def make_telegram_controls(mo: Any, bounds: dict[str, Any]) -> TelegramControls:
    get_chat_name, set_chat_name = mo.state(None)
    get_types_override, set_types_override = mo.state(None)
    get_media_override, set_media_override = mo.state(None)
    return TelegramControls(
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
        chat_type=mo.ui.multiselect(
            options=bounds["chat_types"], value=[], label="Chat type"
        ),
        event_select=mo.ui.multiselect(
            options=bounds["event_types"], value=[], label="Event type"
        ),
        media_select=mo.ui.multiselect(
            options=bounds["media_kinds"], value=[], label="Media kind"
        ),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        include_bots=mo.ui.checkbox(label="Show bots", value=False),
        include_groups=mo.ui.checkbox(label="Show groups / channels", value=False),
        people_btn=mo.ui.run_button(label="People only"),
        clear_types=mo.ui.run_button(label="Clear types"),
        clear_chat=mo.ui.run_button(label="Clear chat lock"),
        clear_media=mo.ui.run_button(label="Clear media"),
        narrate_btn=mo.ui.run_button(label="Narrate this view"),
        get_chat_name=get_chat_name,
        set_chat_name=set_chat_name,
        get_types_override=get_types_override,
        set_types_override=set_types_override,
        get_media_override=get_media_override,
        set_media_override=set_media_override,
    )


def render_telegram_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    dow_labels: dict[int, str],
    controls: TelegramControls,
) -> Any:
    c = controls
    if c.people_btn.value:
        c.set_types_override(list(tgq.PEOPLE_CHAT_TYPES))
    if c.clear_types.value:
        c.set_types_override([])
    if c.clear_chat.value:
        c.set_chat_name(None)
    if c.clear_media.value:
        c.set_media_override([])

    chat_types = (
        c.get_types_override()
        if c.get_types_override() is not None
        else list(c.chat_type.value)
    )
    media_kinds = (
        c.get_media_override()
        if c.get_media_override() is not None
        else list(c.media_select.value)
    )
    if c.chat_type.value and c.get_types_override() is not None:
        c.set_types_override(None)
    if c.media_select.value and c.get_media_override() is not None:
        c.set_media_override(None)

    filters = tgq.filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        chat_types=chat_types,
        event_types=list(c.event_select.value),
        media_kinds=media_kinds,
        chat_name=c.get_chat_name(),
        include_bots=bool(c.include_bots.value),
        include_groups=bool(c.include_groups.value),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_No extra filters active_")
    )

    score_df = tgq.scoreboard(conn, filters, compare_previous=c.compare.value)
    streak_df = tgq.streak_stats(conn, filters)

    monthly_df = tgq.monthly_by_chat_type(conn, filters)
    me_df = tgq.me_vs_them(conn, filters)
    if monthly_df.empty:
        fig_month = px.bar(title="No monthly data")
    else:
        fig_month = px.bar(
            monthly_df,
            x="year_month",
            y="events",
            color="chat_type",
            barmode="stack",
            title="Events by month × chat type",
        )
        fig_month.update_layout(xaxis_title="Month", yaxis_title="Events")
    if me_df.empty:
        fig_me = px.bar(title="No me/them data")
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
        fig_me.update_layout(xaxis_title="Year", yaxis_title="Messages")

    chats_df = tgq.messages_by_chat(conn, filters, limit=25)

    def _lock_chat_from_table(selected: Any) -> None:
        if selected is not None and len(selected) == 1:
            c.set_chat_name(selected.iloc[0]["chat_name"])

    chats_table = mo.ui.table(
        chats_df, selection="single", on_change=_lock_chat_from_table
    )
    if chats_df.empty:
        rank_fig = px.bar(title="No chats for this filter")
    else:
        rank_fig = px.bar(
            chats_df.head(15),
            x="events",
            y="chat_name",
            orientation="h",
            title="Top chats by events",
        )
        rank_fig.update_layout(xaxis_title="Events", yaxis_title="Chat")

    def _lock_chat_from_rank(selection: Any) -> None:
        if selection and selection.get("points"):
            y = selection["points"][0].get("y")
            if y:
                c.set_chat_name(y)

    rank_plot = mo.ui.plotly(rank_fig, on_change=_lock_chat_from_rank)

    scatter_df = tgq.chat_reply_scatter(conn, filters)
    forgotten_df = tgq.forgotten_chats(conn, filters)
    comebacks_df = tgq.comeback_chats(conn, filters)
    if scatter_df.empty:
        scatter_fig = px.scatter(title="No chat scatter")
    else:
        scatter_fig = px.scatter(
            scatter_df,
            x="events",
            y="reply_pct",
            size="events",
            color="chat_type",
            hover_name="chat_name",
            title="Volume vs reply %",
        )
        scatter_fig.update_layout(xaxis_title="Events", yaxis_title="Reply %")

    def _lock_chat_from_scatter(selection: Any) -> None:
        if selection and selection.get("points"):
            point = selection["points"][0]
            name = point.get("hovertext") or point.get("customdata")
            if isinstance(name, list) and name:
                name = name[0]
            if name:
                c.set_chat_name(name)

    scatter_plot = mo.ui.plotly(scatter_fig, on_change=_lock_chat_from_scatter)

    calendar_df = tgq.calendar_daily(conn, filters)
    circadian_df = tgq.circadian_heatmap(conn, filters)
    bump_df = tgq.bump_chart_chats(conn, filters, top_n=8)
    fig_cal = panel_charts.iso_week_calendar(
        px,
        calendar_df,
        z="events",
        title="Daily events (weekday × ISO week)",
        empty_title="No calendar data",
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circadian_df,
        z="events",
        dow_labels=dow_labels,
        title="Events by weekday × hour (Europe/Rome)",
        empty_title="No circadian data",
    )
    if bump_df.empty:
        fig_bump = px.line(title="No bump data")
    else:
        fig_bump = px.line(
            bump_df,
            x="year",
            y="rank",
            color="chat_name",
            markers=True,
            title="Top chat ranks by year",
        )
        fig_bump.update_yaxes(autorange="reversed", title="Rank")
        fig_bump.update_layout(xaxis_title="Year")

    media_df = tgq.media_mix(conn, filters, exclude_none=True)
    react_df = tgq.reaction_mix(conn, filters)
    calls_df = tgq.calls_by_year(conn, filters)
    fig_media = (
        px.pie(
            media_df,
            names="media_kind",
            values="events",
            title="Media mix (excluding none)",
        )
        if not media_df.empty
        else px.pie(title="No media in this filter")
    )

    def _lock_media(selection: Any) -> None:
        if selection and selection.get("points"):
            label = selection["points"][0].get("label")
            if label:
                c.set_media_override([label])

    media_plot = mo.ui.plotly(fig_media, on_change=_lock_media)
    fig_react = (
        px.bar(
            react_df, x="reactions", y="emoji", orientation="h", title="Reaction emoji"
        )
        if not react_df.empty
        else px.bar(title="No reactions")
    )
    fig_react.update_layout(xaxis_title="Reactions", yaxis_title="Emoji")
    fig_calls = (
        px.bar(calls_df, x="year", y="calls", title="Call service events by year")
        if not calls_df.empty
        else px.bar(title="No calls in this filter")
    )
    fig_calls.update_layout(xaxis_title="Year", yaxis_title="Calls")

    # --- Text analytics -------------------------------------------------------
    text_df = tgq.text_stats(conn, filters)
    words_df = tgq.top_words(conn, filters, limit=30)
    emoji_df = tgq.emoji_in_text(conn, filters, limit=15)
    length_df = tgq.message_length_buckets(conn, filters)
    fig_words = (
        px.bar(
            words_df.head(25).iloc[::-1],
            x="uses",
            y="word",
            orientation="h",
            title="Top words (stopwords removed)",
        )
        if not words_df.empty
        else px.bar(title="No text in this filter")
    )
    fig_words.update_layout(xaxis_title="Uses", yaxis_title="Word")
    fig_emoji = (
        px.bar(
            emoji_df.iloc[::-1],
            x="uses",
            y="emoji",
            orientation="h",
            title="Emoji inside messages",
        )
        if not emoji_df.empty
        else px.bar(title="No emoji in text")
    )
    fig_emoji.update_layout(xaxis_title="Uses", yaxis_title="Emoji")
    fig_length = (
        px.bar(
            length_df,
            x="bucket",
            y="messages",
            color="who",
            barmode="group",
            title="Message length (characters): you vs others",
        )
        if not length_df.empty
        else px.bar(title="No text messages")
    )
    fig_length.update_layout(xaxis_title="Characters", yaxis_title="Messages")

    # --- Per-sender + reply network (most useful with one chat locked) --------
    senders_df = tgq.per_sender_breakdown(conn, filters, limit=20)
    edges_df = tgq.reply_edges(conn, filters, limit=40)
    locked = c.get_chat_name()
    people_title = (
        f"Who talks in “{locked}”" if locked else "Who talks (all chats in filter)"
    )
    fig_senders = (
        px.bar(
            senders_df.head(15).iloc[::-1],
            x="messages",
            y="sender",
            orientation="h",
            color="is_me",
            hover_data=["share_pct", "with_media", "replies", "avg_chars"],
            title=people_title,
        )
        if not senders_df.empty
        else px.bar(title="No senders in this filter")
    )
    fig_senders.update_layout(xaxis_title="Messages", yaxis_title="Sender")
    if edges_df.empty:
        fig_sankey = px.bar(title="No reply chains in this filter")
    else:
        sources = edges_df["source"].astype(str)
        targets = edges_df["target"].astype(str)
        nodes = list(dict.fromkeys([*sources.tolist(), *targets.tolist()]))
        idx = {n: i for i, n in enumerate(nodes)}
        # Sankey needs a left and a right column; suffix targets so self-replies
        # and mutual replies do not form cycles.
        right = {n: len(nodes) + i for i, n in enumerate(nodes)}
        fig_sankey = go.Figure(
            go.Sankey(
                node={"label": nodes + [f"→ {n}" for n in nodes], "pad": 12},
                link={
                    "source": [idx[s] for s in sources],
                    "target": [right[t] for t in targets],
                    "value": edges_df["replies"].tolist(),
                },
            )
        )
        fig_sankey.update_layout(
            title="Who replies to whom (replier → replied-to)",
            height=max(360, 22 * len(nodes)),
        )

    # --- Narrative (aggregates only) ------------------------------------------
    narrative_out = mo.md(
        "_Click **Narrate this view** to generate prose (counts and chat names only; "
        "no message text is sent)._"
    )
    if c.narrate_btn.value:
        ctx = tgq.narrative_context(conn, filters)
        text, cached = llm_narrate(ctx, system=TELEGRAM_SYSTEM)
        suffix = " _(cached)_" if cached else ""
        narrative_out = mo.md(f"### Narrative{suffix}\n\n{text}")

    return mo.vstack(
        [
            mo.md(
                f"## Telegram explorer\n"
                f"Data: {bounds['first_day']} → {bounds['last_day']} "
                f"({len(bounds['chats'])} chats). Media files stay on disk; this view is counts only."
            ),
            mo.hstack([c.include_bots, c.include_groups], gap=1),
            mo.hstack([c.year_start, c.year_end], justify="start", gap=1),
            mo.hstack(
                [c.chat_type, c.event_select, c.media_select], justify="start", gap=1
            ),
            mo.hstack(
                [
                    c.compare,
                    c.people_btn,
                    c.clear_types,
                    c.clear_chat,
                    c.clear_media,
                    c.narrate_btn,
                ],
                gap=1,
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md("### Longitudinal"),
            mo.vstack([mo.ui.plotly(fig_month), mo.ui.plotly(fig_me)], gap=1),
            mo.md("### Chats — select a row or click the bar to filter"),
            mo.vstack([chats_table, rank_plot], gap=1),
            mo.md("### Relationships — click a point to lock that chat"),
            scatter_plot,
            mo.vstack(
                [
                    mo.vstack(
                        [
                            mo.md("**Forgotten** (≥50 events, silent >2y)"),
                            mo.ui.table(forgotten_df),
                        ]
                    ),
                    mo.vstack(
                        [
                            mo.md("**Comebacks** (return after ≥2y gap)"),
                            mo.ui.table(comebacks_df),
                        ]
                    ),
                ],
                gap=1,
            ),
            mo.md("### Time"),
            mo.vstack([mo.ui.plotly(fig_cal), mo.ui.plotly(fig_circ)], gap=1),
            mo.ui.plotly(fig_bump),
            mo.md("### Media · reactions · calls"),
            mo.vstack(
                [media_plot, mo.ui.plotly(fig_react), mo.ui.plotly(fig_calls)], gap=1
            ),
            mo.md("### Text — words, emoji, length"),
            mo.ui.table(text_df),
            mo.vstack(
                [
                    mo.ui.plotly(fig_words),
                    mo.ui.plotly(fig_emoji),
                    mo.ui.plotly(fig_length),
                ],
                gap=1,
            ),
            mo.md(
                "### People — lock a group chat to see who talks and who replies to whom"
            ),
            mo.vstack([mo.ui.plotly(fig_senders), mo.ui.table(senders_df)], gap=1),
            mo.ui.plotly(fig_sankey),
            narrative_out,
        ],
        gap=0.5,
    )
