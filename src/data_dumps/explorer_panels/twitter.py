"""Twitter explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

import data_dumps.twitter_queries as twq
from data_dumps.llm_client import narrate as llm_narrate

from . import charts as panel_charts


@dataclass
class TwitterControls:
    year_start: Any
    year_end: Any
    type_select: Any
    media_select: Any
    lang_select: Any
    account_search: Any
    compare: Any
    clear_types: Any
    clear_media: Any
    clear_langs: Any
    clear_search: Any
    clear_account: Any
    clear_hashtag: Any
    narrate_btn: Any
    get_account: Any
    set_account: Any
    get_hashtag: Any
    set_hashtag: Any
    get_type_override: Any
    set_type_override: Any
    get_media_override: Any
    set_media_override: Any


def make_twitter_controls(mo: Any, bounds: dict[str, Any]) -> TwitterControls:
    get_account, set_account = mo.state(None)
    get_hashtag, set_hashtag = mo.state(None)
    get_type_override, set_type_override = mo.state(None)
    get_media_override, set_media_override = mo.state(None)
    return TwitterControls(
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
        type_select=mo.ui.multiselect(
            options=bounds["tweet_types"], value=[], label="Tweet type"
        ),
        media_select=mo.ui.multiselect(
            options=bounds["media_kinds"], value=[], label="Media kind"
        ),
        lang_select=mo.ui.multiselect(
            options=bounds["langs"], value=[], label="Language"
        ),
        account_search=mo.ui.text(
            label="Account / text search", placeholder="substring…"
        ),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        clear_types=mo.ui.run_button(label="× types"),
        clear_media=mo.ui.run_button(label="× media"),
        clear_langs=mo.ui.run_button(label="× langs"),
        clear_search=mo.ui.run_button(label="× search"),
        clear_account=mo.ui.run_button(label="Clear account lock"),
        clear_hashtag=mo.ui.run_button(label="Clear hashtag lock"),
        narrate_btn=mo.ui.run_button(label="Narrate this view"),
        get_account=get_account,
        set_account=set_account,
        get_hashtag=get_hashtag,
        set_hashtag=set_hashtag,
        get_type_override=get_type_override,
        set_type_override=set_type_override,
        get_media_override=get_media_override,
        set_media_override=set_media_override,
    )


def render_twitter_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    dow_labels: dict[int, str],
    controls: TwitterControls,
) -> Any:
    c = controls
    if c.clear_types.value:
        c.set_type_override([])
    if c.clear_media.value:
        c.set_media_override([])
    if c.clear_langs.value:
        pass
    if c.clear_search.value:
        pass
    if c.clear_account.value:
        c.set_account(None)
    if c.clear_hashtag.value:
        c.set_hashtag(None)

    tweet_types = (
        c.get_type_override()
        if c.get_type_override() is not None
        else list(c.type_select.value)
    )
    media_kinds = (
        c.get_media_override()
        if c.get_media_override() is not None
        else list(c.media_select.value)
    )
    if c.type_select.value and c.get_type_override() is not None:
        c.set_type_override(None)
    if c.media_select.value and c.get_media_override() is not None:
        c.set_media_override(None)

    filters = twq.filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        tweet_types=tweet_types,
        media_kinds=media_kinds,
        langs=list(c.lang_select.value),
        account_search=c.account_search.value or "",
        account_name=c.get_account(),
        hashtag=c.get_hashtag(),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_No extra filters active_")
    )

    score_df = twq.scoreboard(conn, filters, compare_previous=c.compare.value)
    streak_df = twq.streak_stats(conn, filters)
    mentions_df = twq.top_mentions(conn, filters)
    replied_df = twq.top_replied_to(conn, filters)
    hashtags_df = twq.top_hashtags(conn, filters)
    liked_accounts_df = twq.top_liked_accounts(conn, filters)
    type_df = twq.tweet_type_mix(conn, filters)
    client_df = twq.client_mix(conn, filters)
    media_df = twq.media_mix(conn, filters, exclude_none=True)
    discovery_df = twq.discovery_vs_repeats(conn, filters)
    monthly_df = twq.monthly_volume(conn, filters)
    monthly_type_df = twq.monthly_by_type(conn, filters)
    likes_df = twq.likes_by_year(conn, filters)
    lang_df = twq.language_mix(conn, filters)
    calendar_df = twq.calendar_daily(conn, filters)
    circadian_df = twq.circadian_heatmap(conn, filters)
    bump_df = twq.bump_chart_accounts(conn, filters, top_n=8)
    scatter_df = twq.account_reply_scatter(conn, filters)
    forgotten_df = twq.forgotten_accounts(conn, filters)
    comebacks_df = twq.comeback_accounts(conn, filters)
    treemap_df = twq.hashtag_account_treemap(conn, filters)
    network_df = twq.network_snapshot(conn)

    def _lock_account(name: str | None) -> None:
        if name:
            c.set_account(name.lower().lstrip("@"))

    def _lock_hashtag(tag: str | None) -> None:
        if tag:
            c.set_hashtag(tag.lower().lstrip("#"))

    def _lock_account_from_table(selected: Any) -> None:
        if selected is not None and len(selected) == 1:
            _lock_account(selected.iloc[0].get("account"))

    mentions_table = mo.ui.table(
        mentions_df, selection="single", on_change=_lock_account_from_table
    )
    fig_mentions = (
        px.bar(
            mentions_df.head(15),
            x="mentions",
            y="account",
            orientation="h",
            title="Top mentioned accounts",
        )
        if not mentions_df.empty
        else px.bar(title="No mentions")
    )

    def _lock_from_mentions_plot(selection: Any) -> None:
        if selection and selection.get("points"):
            y = selection["points"][0].get("y")
            if y:
                _lock_account(y)

    mentions_plot = mo.ui.plotly(fig_mentions, on_change=_lock_from_mentions_plot)

    fig_replied = (
        px.bar(
            replied_df.head(15),
            x="replies",
            y="account",
            orientation="h",
            title="Top replied-to accounts",
        )
        if not replied_df.empty
        else px.bar(title="No replies")
    )
    fig_hashtags = (
        px.bar(
            hashtags_df.head(15),
            x="uses",
            y="hashtag",
            orientation="h",
            title="Top hashtags",
        )
        if not hashtags_df.empty
        else px.bar(title="No hashtags")
    )

    def _lock_from_hashtag_plot(selection: Any) -> None:
        if selection and selection.get("points"):
            y = selection["points"][0].get("y")
            if y:
                _lock_hashtag(y)

    hashtags_plot = mo.ui.plotly(fig_hashtags, on_change=_lock_from_hashtag_plot)

    fig_liked_accounts = (
        px.bar(
            liked_accounts_df.head(15),
            x="likes",
            y="account",
            orientation="h",
            title="Top liked accounts (from URLs/text snippets)",
        )
        if not liked_accounts_df.empty
        else px.bar(title="No liked-account data")
    )

    liked_plot = mo.ui.plotly(fig_liked_accounts, on_change=_lock_from_mentions_plot)

    fig_type = (
        px.pie(type_df, names="tweet_type", values="tweets", title="Tweet type mix")
        if not type_df.empty
        else px.pie(title="No tweets")
    )
    fig_client = (
        px.bar(client_df, x="tweets", y="client", orientation="h", title="Clients")
        if not client_df.empty
        else px.bar(title="No client data")
    )
    if not discovery_df.empty and int(discovery_df.iloc[0].sum()) > 0:
        fig_discovery = px.pie(
            pd.DataFrame(
                {
                    "kind": ["new", "repeat"],
                    "accounts": [
                        int(discovery_df.iloc[0]["new_accounts"]),
                        int(discovery_df.iloc[0]["repeat_accounts"]),
                    ],
                }
            ),
            names="kind",
            values="accounts",
            title="New vs repeat engaged accounts",
        )
    else:
        fig_discovery = px.pie(title="No engagement mix")

    if monthly_df.empty:
        fig_month = px.bar(title="No monthly data")
    else:
        fig_month = px.bar(
            monthly_df,
            x="year_month",
            y="tweets",
            title="Tweets by month",
        )
        fig_month.update_layout(xaxis_title="Month", yaxis_title="Tweets")

    if monthly_type_df.empty:
        fig_month_type = px.bar(title="No monthly type data")
    else:
        fig_month_type = px.bar(
            monthly_type_df,
            x="year_month",
            y="tweets",
            color="tweet_type",
            barmode="stack",
            title="Tweets by month × type",
        )
        fig_month_type.update_layout(xaxis_title="Month", yaxis_title="Tweets")

    fig_likes = (
        px.bar(likes_df, x="year", y="likes", title="Likes given by year")
        if not likes_df.empty
        else px.bar(title="No likes with year metadata")
    )
    fig_lang = (
        px.area(lang_df, x="lang", y="tweets", title="Language mix")
        if not lang_df.empty
        else px.area(title="No language data")
    )

    fig_cal = panel_charts.iso_week_calendar(
        px,
        calendar_df,
        z="tweets",
        title="Daily tweets (weekday × ISO week)",
        empty_title="No calendar data",
    )
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circadian_df,
        z="tweets",
        dow_labels=dow_labels,
        title="Tweets by weekday × hour (Europe/Rome)",
        empty_title="No circadian data",
    )

    if bump_df.empty:
        fig_bump = px.line(title="No bump data")
    else:
        fig_bump = px.line(
            bump_df,
            x="year",
            y="rank",
            color="account",
            markers=True,
            title="Top mention ranks by year",
        )
        fig_bump.update_yaxes(autorange="reversed", title="Rank")
        fig_bump.update_layout(xaxis_title="Year")

    if scatter_df.empty:
        scatter_fig = px.scatter(title="No reply scatter")
    else:
        scatter_fig = px.scatter(
            scatter_df,
            x="tweets",
            y="reply_pct",
            size="tweets",
            hover_name="account",
            title="Reply volume vs reply %",
        )
        scatter_fig.update_layout(xaxis_title="Tweets", yaxis_title="Reply %")

    def _lock_from_scatter(selection: Any) -> None:
        if selection and selection.get("points"):
            name = selection["points"][0].get("hovertext")
            if isinstance(name, list) and name:
                name = name[0]
            if name:
                _lock_account(name)

    scatter_plot = mo.ui.plotly(scatter_fig, on_change=_lock_from_scatter)

    fig_media = (
        px.pie(
            media_df,
            names="media_kind",
            values="tweets",
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

    fig_treemap = (
        px.treemap(
            treemap_df,
            path=["hashtag", "account"],
            values="tweets",
            title="Hashtag → account treemap",
        )
        if not treemap_df.empty
        else px.treemap(title="No hashtag/account treemap data")
    )

    dm_section: list[Any] = []
    if twq.has_table(conn, "dm_messages"):
        dm_df = twq.dm_volume(conn, filters)
        top_dm = twq.top_dm_conversations(conn, filters)
        fig_dm = (
            px.bar(dm_df, x="year_month", y="messages", title="DM volume by month")
            if not dm_df.empty
            else px.bar(title="No DMs in this filter")
        )
        dm_section = [
            mo.md("### DMs"),
            mo.vstack([mo.ui.plotly(fig_dm), mo.ui.table(top_dm)], gap=1),
        ]

    narrative_block: list[Any] = []
    if c.narrate_btn.value:
        ctx = twq.narrative_context(conn, filters)
        text, cached = llm_narrate(ctx)
        suffix = " _(cached)_" if cached else ""
        narrative_block = [mo.md(f"### Narrative{suffix}"), mo.md(text)]

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Twitter explorer\n"
                f"{span}. Classic YTD archive; newer X exports may need schema updates. "
                "Media stays on disk; counts only here."
            ),
            mo.hstack([c.year_start, c.year_end], justify="start", gap=1),
            mo.hstack(
                [c.type_select, c.media_select, c.lang_select], justify="start", gap=1
            ),
            mo.hstack(
                [
                    c.account_search,
                    c.compare,
                    c.clear_types,
                    c.clear_media,
                    c.clear_langs,
                    c.clear_search,
                    c.clear_account,
                    c.clear_hashtag,
                    c.narrate_btn,
                ],
                gap=1,
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md("### Rankings — click a bar to lock account/hashtag"),
            mo.vstack(
                [mentions_table, mentions_plot, mo.ui.plotly(fig_replied), liked_plot],
                gap=1,
            ),
            hashtags_plot,
            mo.md("### Behavior"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_type),
                    mo.ui.plotly(fig_client),
                    mo.ui.plotly(fig_discovery),
                    mo.ui.plotly(fig_circ),
                ],
                gap=1,
            ),
            media_plot,
            mo.md("### Narrative arcs"),
            mo.vstack(
                [
                    mo.vstack(
                        [
                            mo.md("**Forgotten** (≥20 engagements, silent >2y)"),
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
            mo.md("### Longitudinal"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_month),
                    mo.ui.plotly(fig_month_type),
                    mo.ui.plotly(fig_likes),
                    mo.ui.plotly(fig_lang),
                ],
                gap=1,
            ),
            mo.md("### Time · scatter"),
            mo.vstack(
                [mo.ui.plotly(fig_cal), scatter_plot, mo.ui.plotly(fig_bump)], gap=1
            ),
            mo.md("### Expanded"),
            mo.ui.plotly(fig_treemap),
            mo.md("### Network (snapshot from export, not time series)"),
            mo.ui.table(network_df),
            *dm_section,
            *narrative_block,
        ],
        gap=0.5,
    )
