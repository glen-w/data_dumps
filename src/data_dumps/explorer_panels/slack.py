"""Slack explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import slack_queries as skq

from . import charts as panel_charts


@dataclass
class SlackControls:
    year_start: Any
    year_end: Any
    channel_select: Any
    people_select: Any
    person_select: Any
    include_bots: Any
    include_system: Any
    active_only: Any
    compare: Any
    clear_person: Any
    get_person: Any
    set_person: Any


def make_slack_controls(mo: Any, bounds: dict[str, Any]) -> SlackControls:
    get_person, set_person = mo.state(None)
    channel_options = {
        f"{ch['name']}{' (archived)' if ch['is_archived'] else ''}"
        f"{' [file]' if ch['kind'] == 'file_conversation' else ''}"
        f" · {ch['messages']:,}": ch["channel_id"]
        for ch in bounds.get("channels") or []
    }
    people_options = {
        f"{p['name']} (@{p['handle']}){' †' if p['deleted'] else ''}"
        f" · {p['messages']:,}": p["user_id"]
        for p in bounds.get("people") or []
    }
    return SlackControls(
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
        channel_select=mo.ui.multiselect(
            options=channel_options, value=[], label="Channels"
        ),
        people_select=mo.ui.multiselect(
            options=people_options, value=[], label="People (filter everything)"
        ),
        person_select=mo.ui.dropdown(
            options=people_options,
            value=None,
            allow_select_none=True,
            label="Person spotlight",
            searchable=True,
        ),
        include_bots=mo.ui.checkbox(label="Show bots", value=False),
        include_system=mo.ui.checkbox(label="Show system events", value=False),
        active_only=mo.ui.checkbox(label="Active channels only", value=False),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        clear_person=mo.ui.run_button(label="Clear spotlight"),
        get_person=get_person,
        set_person=set_person,
    )


def _slack_heatmap(
    px: Any, df: pd.DataFrame, dow_labels: dict[int, str], **kw: Any
) -> Any:
    title = kw.pop("title", "No data")
    z = kw.pop("z", "messages")
    return panel_charts.circadian_heatmap(
        px,
        df,
        z=z,
        dow_labels=dow_labels,
        title=title,
        colorscale="Blues",
        empty_title=title,
        xaxis_title="Hour (Paris)",
        yaxis_title="",
        histfunc="sum",
        ordered_dow=True,
    )


def _slack_calendar(px: Any, df: pd.DataFrame, title: str) -> Any:
    return panel_charts.iso_week_calendar(
        px,
        df,
        z="messages",
        title=title,
        colorscale="Greens",
        facet_by_year=True,
        histfunc="sum",
        reverse_y=True,
        height_per_year=120,
    )


def render_slack_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: SlackControls,
    dow_labels: dict[int, str],
) -> Any:
    c = controls
    if c.clear_person.value:
        c.set_person(None)

    filters = skq.filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        channel_ids=list(c.channel_select.value or []),
        user_ids=list(c.people_select.value or []),
        include_bots=bool(c.include_bots.value),
        include_system=bool(c.include_system.value),
        include_archived=not bool(c.active_only.value),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range · humans only_")
    )
    people_by_id = {p["user_id"]: p for p in bounds.get("people") or []}
    name_to_id = {p["name"]: p["user_id"] for p in bounds.get("people") or []}

    # ---------------------------------------------------------------- workspace
    score_df = skq.scoreboard(conn, filters, compare_previous=bool(c.compare.value))
    streak_df = skq.streak_stats(conn, filters)
    kind_df = skq.monthly_messages_by_kind(conn, filters)
    active_df = skq.active_people_monthly(conn, filters)
    channels_df = skq.messages_by_channel(conn, filters, limit=25)
    bump_ch_df = skq.bump_chart_channels(conn, filters, top_n=8)
    lifecycle_df = skq.channel_lifecycle(conn, filters, limit=40)
    births_df = skq.channels_created_archived_by_year(conn, filters)
    forgotten_df = skq.forgotten_channels(conn, filters)
    comeback_df = skq.comeback_channels(conn, filters)
    people_df = skq.top_people(conn, filters, limit=25)
    bump_people_df = skq.bump_chart_people(conn, filters, top_n=8)
    ratio_df = skq.people_reply_ratio(conn, filters, limit=20)
    depth_df = skq.thread_depth_distribution(conn, filters)
    latency_df = skq.reply_latency(conn, filters)
    latency_ch_df = skq.reply_latency_by_channel(conn, filters)
    threads_df = skq.busiest_threads(conn, filters)
    react_df = skq.reaction_mix(conn, filters)
    reacted_df = skq.most_reacted_messages(conn, filters)
    reactors_df = skq.top_reactors(conn, filters)
    mentioned_df = skq.top_mentioned(conn, filters)
    pairs_df = skq.mention_pairs(conn, filters)
    bots_df = skq.bots_by_name(conn, filters)
    heat_df = skq.circadian_heatmap(conn, filters)
    cal_df = skq.calendar_daily(conn, filters)

    fig_kind = (
        px.area(
            kind_df,
            x="year_month",
            y="messages",
            color="kind",
            title="Messages per month (human / bot / system)",
        )
        if not kind_df.empty
        else px.area(title="No messages")
    )
    fig_active = (
        px.line(
            active_df,
            x="year_month",
            y=["people", "channels"],
            title="Active people and channels per month",
        )
        if not active_df.empty
        else px.line(title="No activity")
    )

    if channels_df.empty:
        fig_channels = px.bar(title="No channels for this filter")
    else:
        fig_channels = px.bar(
            channels_df.head(20),
            x="messages",
            y="channel_name",
            orientation="h",
            color="reply_pct",
            hover_data=["people", "threads", "last_day"],
            title="Top channels (colour = % replies)",
        )
        fig_channels.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_bump_ch = (
        px.line(
            bump_ch_df,
            x="year",
            y="rank",
            color="channel_name",
            markers=True,
            title="Channel rank by year (top 8)",
        )
        if not bump_ch_df.empty
        else px.line(title="No ranking data")
    )
    if not bump_ch_df.empty:
        fig_bump_ch.update_yaxes(autorange="reversed", dtick=1)
    fig_births = (
        px.bar(
            births_df,
            x="year",
            y=["created", "archived"],
            barmode="group",
            title="Channels created vs archived",
        )
        if not births_df.empty
        else px.bar(title="No channel lifecycle data")
    )

    def _spotlight_from_people_plot(selection: Any) -> None:
        if selection and selection.get("points"):
            y = selection["points"][0].get("y")
            if y and y in name_to_id:
                c.set_person(name_to_id[y])

    if people_df.empty:
        fig_people = px.bar(title="No people for this filter")
    else:
        fig_people = px.bar(
            people_df.head(20),
            x="messages",
            y="name",
            orientation="h",
            color="reactions_received",
            hover_data=["threads_started", "replies", "channels", "active_days"],
            title="Top people (click a bar to spotlight)",
        )
        fig_people.update_layout(yaxis={"categoryorder": "total ascending"})
    people_plot = mo.ui.plotly(fig_people, on_change=_spotlight_from_people_plot)
    fig_bump_people = (
        px.line(
            bump_people_df,
            x="year",
            y="rank",
            color="name",
            markers=True,
            title="People rank by year (top 8)",
        )
        if not bump_people_df.empty
        else px.line(title="No ranking data")
    )
    if not bump_people_df.empty:
        fig_bump_people.update_yaxes(autorange="reversed", dtick=1)
    fig_ratio = (
        px.bar(
            ratio_df,
            x="name",
            y=["root_posts", "replies", "reactions_given"],
            barmode="stack",
            title="Root posts · replies · reactions given",
        )
        if not ratio_df.empty
        else px.bar(title="No people")
    )

    fig_depth = (
        px.bar(
            depth_df, x="depth", y="threads", title="Thread depth (replies per thread)"
        )
        if not depth_df.empty
        else px.bar(title="No threads")
    )
    if latency_ch_df.empty:
        fig_latency = px.bar(title="No reply-latency data")
    else:
        fig_latency = px.bar(
            latency_ch_df,
            x="median_min",
            y="channel_name",
            orientation="h",
            hover_data=["threads", "p90_min"],
            title="Median minutes to first reply, by channel",
        )
        fig_latency.update_layout(yaxis={"categoryorder": "total descending"})

    fig_react = (
        px.bar(
            react_df,
            x="reactions",
            y="emoji",
            orientation="h",
            title="Top reaction emoji",
        )
        if not react_df.empty
        else px.bar(title="No reactions")
    )
    if not react_df.empty:
        fig_react.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_mentioned = (
        px.bar(
            mentioned_df,
            x="mentions",
            y="name",
            orientation="h",
            hover_data=["mentioned_by_people"],
            title="Most mentioned",
        )
        if not mentioned_df.empty
        else px.bar(title="No mentions")
    )
    if not mentioned_df.empty:
        fig_mentioned.update_layout(yaxis={"categoryorder": "total ascending"})
    if pairs_df.empty:
        fig_pairs = px.bar(title="No mention pairs")
    else:
        pairs = pairs_df.copy()
        pairs["pair"] = pairs["from_name"] + " → " + pairs["to_name"]
        fig_pairs = px.bar(
            pairs, x="mentions", y="pair", orientation="h", title="Who mentions whom"
        )
        fig_pairs.update_layout(yaxis={"categoryorder": "total ascending"})

    fig_heat = _slack_heatmap(
        px, heat_df, dow_labels, title="Messages by weekday × hour"
    )
    fig_cal = _slack_calendar(px, cal_df, "Messages per day")
    fig_bots = (
        px.bar(bots_df, x="messages", y="bot", orientation="h", title="Bot volume")
        if not bots_df.empty
        else px.bar(title="No bot messages")
    )

    # ---------------------------------------------------------------- spotlight
    person_id = c.get_person() or c.person_select.value
    if person_id:
        pinfo = people_by_id.get(person_id) or {"name": person_id, "handle": "?"}
        ps_df = skq.person_scoreboard(conn, filters, person_id)
        pm_df = skq.person_monthly_activity(conn, filters, person_id)
        share_df = skq.person_share_of_team(conn, filters, person_id)
        pmix_df = skq.person_channel_mix(conn, filters, person_id)
        pheat_df = skq.person_circadian(conn, filters, person_id)
        pcal_df = skq.person_calendar_daily(conn, filters, person_id)
        collab_df = skq.person_collaborators(conn, filters, person_id)
        pemoji_df = skq.person_reaction_profile(conn, filters, person_id)
        ptext_df = skq.person_text_profile(conn, filters, person_id)
        ptop_df = skq.person_top_messages(conn, filters, person_id)
        pstreak_df = skq.person_streaks(conn, filters, person_id)

        fig_pm = (
            px.area(
                pm_df,
                x="year_month",
                y=["root_posts", "replies"],
                title="Monthly activity: root posts vs replies",
            )
            if not pm_df.empty
            else px.area(title="No messages in window")
        )
        if not pm_df.empty:
            fig_pm.add_scatter(
                x=pm_df["year_month"],
                y=pm_df["rolling_3m"],
                mode="lines",
                name="3-month mean",
                line={"dash": "dash"},
            )
        fig_share = (
            px.bar(
                share_df,
                x="year",
                y="share_pct",
                hover_data=["messages", "team_messages", "team_people", "rank"],
                title="Share of team messages by year (%)",
            )
            if not share_df.empty
            else px.bar(title="No team data")
        )
        fig_pmix = (
            px.treemap(
                pmix_df,
                path=["channel_name"],
                values="messages",
                color="share_pct",
                color_continuous_scale="Purples",
                hover_data=["channel_messages"],
                title="Channel mix (size = their messages, colour = % of channel)",
            )
            if not pmix_df.empty
            else px.treemap(title="No channel data")
        )
        person_heat = (
            pheat_df[pheat_df["who"] == "person"] if not pheat_df.empty else pheat_df
        )
        team_heat = (
            pheat_df[pheat_df["who"] == "team"] if not pheat_df.empty else pheat_df
        )
        fig_pheat = _slack_heatmap(
            px,
            person_heat,
            dow_labels,
            z="pct",
            title=f"{pinfo['name']} — % of own messages",
        )
        fig_theat = _slack_heatmap(
            px, team_heat, dow_labels, z="pct", title="Rest of team — % of own messages"
        )
        if not pheat_df.empty:
            zmax = float(pheat_df["pct"].max())
            fig_pheat.update_coloraxes(cmin=0, cmax=zmax)
            fig_theat.update_coloraxes(cmin=0, cmax=zmax)
        fig_pcal = _slack_calendar(px, pcal_df, f"{pinfo['name']} — messages per day")
        if collab_df.empty:
            fig_collab = px.bar(title="No interactions")
        else:
            fig_collab = px.bar(
                collab_df,
                x="n",
                y="other_name",
                color="kind",
                orientation="h",
                title="Collaborators (replies, mentions, reactions both ways)",
            )
            fig_collab.update_layout(
                yaxis={"categoryorder": "total ascending"},
                height=max(360, 28 * collab_df["other_name"].nunique() + 120),
            )
        fig_pemoji = (
            px.bar(
                pemoji_df,
                x="n",
                y="emoji",
                color="direction",
                barmode="group",
                orientation="h",
                title="Emoji given vs received",
            )
            if not pemoji_df.empty
            else px.bar(title="No reactions")
        )
        if not pemoji_df.empty:
            fig_pemoji.update_layout(yaxis={"categoryorder": "total ascending"})

        spotlight = mo.vstack(
            [
                mo.md(
                    f"### Person spotlight — {pinfo['name']} (@{pinfo.get('handle', '?')})\n"
                    "_Team baseline uses the same years / channels / bot settings "
                    "but ignores the people filter._"
                ),
                mo.ui.table(
                    ps_df.T.reset_index().rename(
                        columns={"index": "metric", 0: "value"}
                    )
                ),
                mo.vstack([mo.ui.plotly(fig_pm), mo.ui.plotly(fig_share)], gap=1),
                mo.ui.plotly(fig_pmix),
                mo.ui.plotly(fig_pheat),
                mo.ui.plotly(fig_theat),
                mo.ui.plotly(fig_pcal),
                mo.ui.plotly(fig_collab),
                mo.ui.plotly(fig_pemoji),
                mo.md("**Text profile vs team**"),
                mo.ui.table(ptext_df),
                mo.md("**Most engaged-with messages**"),
                mo.ui.table(ptop_df),
                mo.md("**Streaks**"),
                mo.ui.table(pstreak_df),
            ],
            gap=0.5,
        )
    else:
        spotlight = mo.md(
            "### Person spotlight\n"
            "_Pick a person in the spotlight dropdown or click a bar in “Top people”._"
        )

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Slack workspace\n"
                f"{span} · {len(bounds.get('channels') or [])} channels · "
                f"{len(bounds.get('people') or [])} people who posted. "
                "Names and text kept; emails and phones dropped at ingest."
            ),
            mo.hstack([c.year_start, c.year_end], justify="start", gap=1),
            mo.hstack([c.channel_select, c.people_select], justify="start", gap=1),
            mo.hstack([c.person_select, c.clear_person], justify="start", gap=1),
            mo.hstack(
                [c.include_bots, c.include_system, c.active_only, c.compare], gap=1
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md("### Longitudinal"),
            mo.vstack([mo.ui.plotly(fig_kind), mo.ui.plotly(fig_active)], gap=1),
            mo.md("### Channels"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_channels),
                    mo.ui.plotly(fig_bump_ch),
                    mo.ui.plotly(fig_births),
                ],
                gap=1,
            ),
            mo.md("**Channel lifecycle**"),
            mo.ui.table(lifecycle_df),
            mo.md(
                "**Forgotten channels** (≥50 messages, silent ≥2 years before export end)"
            ),
            mo.ui.table(forgotten_df),
            mo.md("**Comeback channels** (silent ≥1 year, then posted again)"),
            mo.ui.table(comeback_df),
            mo.md("### People"),
            mo.vstack(
                [people_plot, mo.ui.plotly(fig_bump_people), mo.ui.plotly(fig_ratio)],
                gap=1,
            ),
            spotlight,
            mo.md("### Threads & response"),
            mo.ui.table(latency_df),
            mo.vstack([mo.ui.plotly(fig_depth), mo.ui.plotly(fig_latency)], gap=1),
            mo.md("**Busiest threads**"),
            mo.ui.table(threads_df),
            mo.md("### Reactions & mentions"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_react),
                    mo.ui.plotly(fig_mentioned),
                    mo.ui.plotly(fig_pairs),
                ],
                gap=1,
            ),
            mo.md("**Most reacted messages**"),
            mo.ui.table(reacted_df),
            mo.md("**Top reactors**"),
            mo.ui.table(reactors_df),
            mo.md("### Rhythm"),
            mo.vstack([mo.ui.plotly(fig_heat), mo.ui.plotly(fig_cal)], gap=1),
            mo.md("### Bots"),
            mo.ui.plotly(fig_bots),
        ],
        gap=0.5,
    )
