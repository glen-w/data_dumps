"""UI builders for the combined Marimo explorer tabs.

Marimo forbids reading ``widget.value`` in the cell that created the widget.
Each tab therefore uses two cells:

1. ``make_*_controls`` — create widgets/state (always runs; no display)
2. ``render_*_panel`` — read values, query, return one ``mo.vstack`` (leaf cell;
   gate with ``mo.stop`` so the inactive tab has no descendant banners)

Interactive picks created inside the render cell use ``on_change`` instead of
``.value`` so they stay legal in that same leaf cell.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd
import plotly.graph_objects as go

from data_dumps import amazon_queries as amzq
from data_dumps import browser_queries as brq
from data_dumps import linkedin_queries as liq
from data_dumps import miband_queries as mbq
from data_dumps import slack_queries as skq
from data_dumps import sleep_queries as slq
from data_dumps import telegram_queries as tgq
from data_dumps import thunderbird_queries as tbq
from data_dumps.llm_client import TELEGRAM_SYSTEM
from data_dumps.llm_client import narrate as llm_narrate
from data_dumps.spotify_queries import (
    album_depth,
    artist_monthly_timeline,
    artist_rank_movement,
    has_account_data,
    library_counts,
    library_never_played,
    library_overlap,
    listening_sessions,
    milestones,
    offline_vs_online,
    playlist_sizes,
    search_volume,
    searched_but_rarely_played,
    top_searches,
)


@dataclass
class SpotifyControls:
    year_start: Any
    year_end: Any
    kind_select: Any
    platform_select: Any
    country_select: Any
    artist_search: Any
    compare: Any
    clear_artist: Any
    clear_kinds: Any
    clear_platform: Any
    clear_country: Any
    clear_search: Any
    narrate_btn: Any
    get_artist: Any
    set_artist: Any
    get_kind_override: Any
    set_kind_override: Any
    get_platform_override: Any
    set_platform_override: Any
    get_country_override: Any
    set_country_override: Any


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


@dataclass
class LinkedInControls:
    year_start: Any
    year_end: Any


@dataclass
class AmazonControls:
    year_start: Any
    year_end: Any
    marketplace_select: Any
    currency_select: Any
    dept_select: Any
    include_cancelled: Any


@dataclass
class SleepControls:
    year_start: Any
    year_end: Any
    tag_select: Any
    min_rating: Any
    compare: Any
    act_nights: Any


@dataclass
class MiBandControls:
    year_start: Any
    year_end: Any


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


def make_spotify_controls(mo: Any, bounds: dict[str, Any]) -> SpotifyControls:
    get_artist, set_artist = mo.state(None)
    get_kind_override, set_kind_override = mo.state(None)
    get_platform_override, set_platform_override = mo.state(None)
    get_country_override, set_country_override = mo.state(None)
    return SpotifyControls(
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
        kind_select=mo.ui.multiselect(options=bounds["kinds"], value=[], label="Kind"),
        platform_select=mo.ui.multiselect(
            options=bounds["platforms"], value=[], label="Platform"
        ),
        country_select=mo.ui.multiselect(
            options=bounds["countries"], value=[], label="Country"
        ),
        artist_search=mo.ui.text(label="Artist search", placeholder="substring…"),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        clear_artist=mo.ui.run_button(label="Clear artist lock"),
        clear_kinds=mo.ui.run_button(label="× kinds"),
        clear_platform=mo.ui.run_button(label="× platform"),
        clear_country=mo.ui.run_button(label="× countries"),
        clear_search=mo.ui.run_button(label="× search"),
        narrate_btn=mo.ui.run_button(label="Narrate this view"),
        get_artist=get_artist,
        set_artist=set_artist,
        get_kind_override=get_kind_override,
        set_kind_override=set_kind_override,
        get_platform_override=get_platform_override,
        set_platform_override=set_platform_override,
        get_country_override=get_country_override,
        set_country_override=set_country_override,
    )


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


def make_linkedin_controls(mo: Any, bounds: dict[str, Any]) -> LinkedInControls:
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
    )


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


def make_sleep_controls(mo: Any, bounds: dict[str, Any]) -> SleepControls:
    return SleepControls(
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
        tag_select=mo.ui.multiselect(
            options=bounds.get("tags") or [], value=[], label="Tags"
        ),
        min_rating=mo.ui.slider(
            start=0.0,
            stop=5.0,
            step=0.5,
            value=0.0,
            label="Min rating",
            show_value=True,
        ),
        compare=mo.ui.checkbox(label="Compare vs previous equal window", value=False),
        act_nights=mo.ui.slider(
            start=1,
            stop=10,
            step=1,
            value=5,
            label="Actigraphy nights",
            show_value=True,
        ),
    )


def make_miband_controls(mo: Any, bounds: dict[str, Any]) -> MiBandControls:
    return MiBandControls(
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
    )


def make_thunderbird_controls(mo: Any, bounds: dict[str, Any]) -> ThunderbirdControls:
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
    )


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


def render_spotify_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    mb_ready: bool,
    controls: SpotifyControls,
    filter_from_widgets: Callable[..., Any],
    scoreboard: Callable[..., Any],
    streak_stats: Callable[..., Any],
    top_artists: Callable[..., Any],
    top_tracks: Callable[..., Any],
    top_albums: Callable[..., Any],
    top_shows: Callable[..., Any],
    discovery_vs_repeats: Callable[..., Any],
    shuffle_intent: Callable[..., Any],
    circadian_heatmap: Callable[..., Any],
    forgotten_artists: Callable[..., Any],
    comeback_artists: Callable[..., Any],
    monthly_hours: Callable[..., Any],
    hours_by_kind: Callable[..., Any],
    hours_by_platform: Callable[..., Any],
    hours_by_country: Callable[..., Any],
    skip_trends: Callable[..., Any],
    treemap_artist_album: Callable[..., Any],
    calendar_daily: Callable[..., Any],
    bump_chart_artists: Callable[..., Any],
    artist_hours_vs_skip: Callable[..., Any],
    kind_platform_sunburst: Callable[..., Any],
    genre_treemap: Callable[..., Any],
    decade_bars: Callable[..., Any],
    narrative_context: Callable[..., Any],
    narrate: Callable[..., Any],
) -> Any:
    c = controls
    if c.clear_artist.value:
        c.set_artist(None)
    if c.clear_kinds.value:
        c.set_kind_override([])
    if c.clear_platform.value:
        c.set_platform_override([])
    if c.clear_country.value:
        c.set_country_override([])
    if c.clear_search.value:
        c.artist_search.value = ""

    kinds = (
        c.get_kind_override()
        if c.get_kind_override() is not None
        else list(c.kind_select.value)
    )
    platforms = (
        c.get_platform_override()
        if c.get_platform_override() is not None
        else list(c.platform_select.value)
    )
    countries = (
        c.get_country_override()
        if c.get_country_override() is not None
        else list(c.country_select.value)
    )
    if c.kind_select.value and c.get_kind_override() is not None:
        c.set_kind_override(None)
    if c.platform_select.value and c.get_platform_override() is not None:
        c.set_platform_override(None)
    if c.country_select.value and c.get_country_override() is not None:
        c.set_country_override(None)

    filters = filter_from_widgets(
        bounds,
        year_start=c.year_start.value,
        year_end=c.year_end.value,
        kinds=kinds,
        platform_buckets=platforms,
        conn_countries=countries,
        artist_search=c.artist_search.value or None,
        artist_name=c.get_artist(),
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_No extra filters active_")
    )

    def _lock_artist_from_table(selected: Any) -> None:
        if selected is not None and len(selected) == 1:
            c.set_artist(selected.iloc[0]["artist_name"])

    top_artists_df = top_artists(conn, filters, limit=20)
    top_artists_table = mo.ui.table(
        top_artists_df, selection="single", on_change=_lock_artist_from_table
    )

    score_df = scoreboard(conn, filters, compare_previous=c.compare.value)
    streak_df = streak_stats(conn, filters)
    milestones_df = milestones(conn, filters)
    offline_df = offline_vs_online(conn, filters)
    depth_df = album_depth(conn, filters, limit=15)
    sessions_df = listening_sessions(conn, filters, limit=15)
    movement_df = artist_rank_movement(conn, filters, limit=15)
    timeline_df = artist_monthly_timeline(conn, filters)

    fig_offline = (
        px.pie(
            offline_df,
            names="mode",
            values="hours",
            title="Hours offline vs online",
        )
        if not offline_df.empty
        else px.pie(title="No offline/online data")
    )
    fig_depth = (
        px.bar(
            depth_df,
            x="depth_score",
            y="album_name",
            orientation="h",
            color="unique_tracks",
            hover_data=["artist_name", "plays", "plays_per_track", "top_track"],
            title="Album depth (distinct tracks × log revisit rate)",
        )
        if not depth_df.empty
        else px.bar(title="No albums with ≥10 plays in this filter")
    )
    if not depth_df.empty:
        fig_depth.update_yaxes(autorange="reversed")
    if movement_df.empty:
        note = movement_df.attrs.get("compare_note") or "no artists in window"
        fig_movement = px.bar(title=f"Rank movement: {note}")
    else:
        fig_movement = px.bar(
            movement_df,
            x="rank_delta",
            y="artist_name",
            orientation="h",
            color="status",
            hover_data=["hours", "rank", "prev_rank", "prev_hours"],
            title="Top artists — rank change vs previous equal window",
        )
        fig_movement.update_yaxes(autorange="reversed")
        fig_movement.update_layout(xaxis_title="Places climbed (+) / dropped (−)")
    if timeline_df.empty:
        fig_timeline = px.line(title="No artist timeline")
    else:
        fig_timeline = px.line(
            timeline_df,
            x="year_month",
            y="hours",
            color="artist_name",
            markers=True,
            title="Monthly hours — locked artist or current top 3",
        )
        fig_timeline.update_layout(xaxis_tickangle=-45)

    artists_df = top_artists(conn, filters, limit=15)
    tracks_df = top_tracks(conn, filters, limit=15)
    albums_df = top_albums(conn, filters, limit=15)
    shows_df = top_shows(conn, filters, limit=15)

    discovery_df = discovery_vs_repeats(conn, filters)
    shuffle_df = shuffle_intent(conn, filters)
    circadian_df = circadian_heatmap(conn, filters)
    fig_disc = px.pie(
        discovery_df,
        names="play_type",
        values="plays",
        title="Discovery vs repeat plays (tracks)",
    )
    fig_shuffle = px.bar(
        shuffle_df.head(12),
        x="reason_start",
        y="hours",
        color="shuffle_mode",
        title="Hours by reason_start × shuffle",
    )
    fig_shuffle.update_layout(xaxis_tickangle=-45)
    if not circadian_df.empty:
        circ = circadian_df.copy()
        circ["dow_label"] = circ["dow"].map(
            {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
        )
        fig_circ = px.density_heatmap(
            circ,
            x="hour",
            y="dow_label",
            z="hours",
            title="Hours by weekday × hour (local)",
            color_continuous_scale="Viridis",
        )
    else:
        fig_circ = px.imshow([[0]], title="No circadian data for filter")

    forgotten_df = forgotten_artists(conn, filters)
    comebacks_df = comeback_artists(conn, filters)

    monthly_df = monthly_hours(conn, filters)
    kind_df = hours_by_kind(conn, filters)
    platform_df = hours_by_platform(conn, filters)
    country_df = hours_by_country(conn, filters)
    skips_df = skip_trends(conn, filters)
    if not monthly_df.empty:
        fig_monthly = px.bar(
            monthly_df, x="year_month", y="hours", title="Hours by month"
        )
        fig_monthly.update_layout(xaxis_tickangle=-45)
    else:
        fig_monthly = px.bar(title="No monthly data")
    fig_kind = px.bar(
        kind_df,
        x="year",
        y="hours",
        color="kind",
        barmode="stack",
        title="Hours by kind",
    )
    fig_platform = px.pie(
        platform_df, names="platform_bucket", values="hours", title="Hours by platform"
    )

    def _lock_platform(selection: Any) -> None:
        if selection and selection.get("points"):
            label = selection["points"][0].get("label")
            if label:
                c.set_platform_override([label])

    platform_plot = mo.ui.plotly(fig_platform, on_change=_lock_platform)
    if not country_df.empty:
        fig_country = px.area(
            country_df,
            x="month",
            y="hours",
            color="conn_country",
            title="Hours by country (>5h/month)",
        )
        fig_country.update_layout(xaxis_tickangle=-45)
    else:
        fig_country = px.area(title="No country data")
    fig_skips = px.line(
        skips_df,
        x="year",
        y=["skip_pct", "full_play_pct", "under_30s_pct"],
        title="Track playback signals by year",
        labels={"value": "percent", "variable": "metric"},
    )

    treemap_df = treemap_artist_album(conn, filters)
    calendar_df = calendar_daily(conn, filters)
    bump_df = bump_chart_artists(conn, filters, top_n=10)
    scatter_df = artist_hours_vs_skip(conn, filters)
    sunburst_df = kind_platform_sunburst(conn, filters)
    fig_tree = (
        px.treemap(
            treemap_df,
            path=["artist_name", "album_name"],
            values="hours",
            title="Artist → album hours",
        )
        if not treemap_df.empty
        else px.treemap(title="No treemap data")
    )
    if not calendar_df.empty:
        cal = calendar_df.copy()
        cal["week"] = cal["day"].dt.isocalendar().week.astype(int)
        cal["dow"] = cal["day"].dt.dayofweek
        fig_cal = px.bar(
            cal,
            x="dow",
            y="week",
            color="hours",
            title="Daily hours (week × weekday)",
            color_continuous_scale="Blues",
        )
    else:
        fig_cal = px.bar(title="No calendar data")
    if not bump_df.empty:
        fig_bump = px.line(
            bump_df,
            x="year",
            y="rank",
            color="artist_name",
            markers=True,
            title="Top artist ranks by year (bump)",
        )
        fig_bump.update_yaxes(autorange="reversed")
    else:
        fig_bump = px.line(title="No bump data")
    fig_scatter = (
        px.scatter(
            scatter_df,
            x="hours",
            y="skip_pct",
            size="plays",
            hover_name="artist_name",
            title="Artist hours vs skip % (click to filter)",
        )
        if not scatter_df.empty
        else px.scatter(title="No scatter data")
    )

    def _lock_artist_from_scatter(selection: Any) -> None:
        if selection and selection.get("points") and not scatter_df.empty:
            idx = selection["points"][0].get("pointIndex", 0)
            c.set_artist(scatter_df.iloc[idx]["artist_name"])

    scatter_plot = mo.ui.plotly(fig_scatter, on_change=_lock_artist_from_scatter)
    fig_sun = (
        px.sunburst(
            sunburst_df,
            path=["kind", "platform_bucket"],
            values="hours",
            title="Kind → platform",
        )
        if not sunburst_df.empty
        else px.sunburst(title="No sunburst data")
    )

    if mb_ready:
        genre_df = genre_treemap(conn, filters)
        decade_df = decade_bars(conn, filters)
        mb_block = mo.vstack(
            [
                mo.md("### MusicBrainz enrichment"),
                mo.vstack(
                    [
                        mo.ui.plotly(
                            px.treemap(
                                genre_df,
                                path=["genre", "artist_name"],
                                values="hours",
                                title="Genre → artist (MusicBrainz tags)",
                            )
                            if not genre_df.empty
                            else px.treemap(title="No genre data")
                        ),
                        mo.ui.plotly(
                            px.bar(
                                decade_df,
                                x="decade",
                                y="hours",
                                title="Hours by release decade",
                            )
                            if not decade_df.empty
                            else px.bar(title="No decade data")
                        ),
                    ],
                    gap=1,
                ),
            ]
        )
    else:
        mb_block = mo.md(
            "_Genre/decade charts need MusicBrainz enrichment. "
            "**Stop this notebook first**, then: `uv run enrich-musicbrainz`. "
            "See docs/WAREHOUSE.md._"
        )

    if has_account_data(conn):
        lib_counts = library_counts(conn)
        overlap_df = library_overlap(conn, limit=15)
        never_df = library_never_played(conn, limit=15)
        playlists_df = playlist_sizes(conn, limit=20)
        search_df = search_volume(conn)
        top_q = top_searches(conn, limit=15)
        rarely_df = searched_but_rarely_played(conn, limit=15)
        fig_lib = (
            px.bar(
                lib_counts,
                x="n",
                y="item_kind",
                orientation="h",
                title="Saved library by kind",
            )
            if not lib_counts.empty
            else px.bar(title="No library items")
        )
        fig_search = (
            px.bar(
                search_df, x="year_month", y="searches", title="Search queries by month"
            )
            if not search_df.empty
            else px.bar(title="No search queries")
        )
        if not search_df.empty:
            fig_search.update_layout(xaxis_tickangle=-45)
        fig_pl = (
            px.bar(
                playlists_df,
                x="n_items",
                y="playlist_name",
                orientation="h",
                title="Playlists by size",
            )
            if not playlists_df.empty
            else px.bar(title="No playlists")
        )
        library_block = mo.vstack(
            [
                mo.md(
                    "### Library & playlists (Account Data)\n"
                    "_Saved items and playlists from the Account Data dump. "
                    "`account_plays` is a 1-year slice and is **not** merged into Extended History._"
                ),
                mo.vstack([mo.ui.plotly(fig_lib), mo.ui.plotly(fig_pl)], gap=1),
                mo.vstack(
                    [
                        mo.vstack(
                            [
                                mo.md(
                                    "**Saved tracks with the most Extended History hours**"
                                ),
                                mo.ui.table(overlap_df),
                            ]
                        ),
                        mo.vstack(
                            [
                                mo.md("**Saved but never in Extended History**"),
                                mo.ui.table(never_df),
                            ]
                        ),
                    ],
                    gap=1,
                ),
                mo.vstack(
                    [
                        mo.ui.plotly(fig_search),
                        mo.vstack(
                            [mo.md("**Top search queries**"), mo.ui.table(top_q)]
                        ),
                    ],
                    gap=1,
                ),
                mo.vstack(
                    [
                        mo.md(
                            "**Searched for, barely played** — queries matching an "
                            "artist/track name with ≤3 plays in Extended History"
                        ),
                        mo.ui.table(rarely_df),
                    ]
                ),
            ],
            gap=0.5,
        )
    else:
        library_block = mo.md(
            "_Library/playlists need the Spotify Account Data dump. "
            "Stop this notebook, then: "
            "`uv run ingest ~/Documents/data_dumps_raw/spotify/my_spotify_account_data_2026-09-06.zip`_"
        )

    narrative_out = mo.md(
        "_Click **Narrate this view** to generate prose (aggregates only)._"
    )
    if c.narrate_btn.value:
        ctx = narrative_context(conn, filters)
        text, cached = narrate(ctx)
        suffix = " _(cached)_" if cached else ""
        narrative_out = mo.md(f"### Narrative{suffix}\n\n{text}")

    return mo.vstack(
        [
            mo.md(
                f"## Spotify Wrapped\n"
                f"Data: {bounds['first_day']} → {bounds['last_day']} "
                f"(2017 gap is export data, not life)"
            ),
            mo.hstack(
                [
                    c.year_start,
                    c.year_end,
                    c.kind_select,
                    c.platform_select,
                    c.country_select,
                ],
                justify="start",
                gap=1,
            ),
            mo.hstack(
                [
                    c.artist_search,
                    c.compare,
                    c.clear_artist,
                    c.clear_kinds,
                    c.clear_platform,
                    c.clear_country,
                    c.clear_search,
                    c.narrate_btn,
                ],
                gap=1,
            ),
            chip_row,
            mo.md("### Top artists — select a row to filter"),
            top_artists_table,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md("**Milestones**"),
            mo.ui.table(milestones_df),
            mo.md("### Rank movement · artist timeline"),
            mo.vstack([mo.ui.plotly(fig_movement), mo.ui.plotly(fig_timeline)], gap=1),
            mo.md("### Rankings"),
            mo.vstack(
                [
                    mo.vstack(
                        [
                            mo.md("**Artists**"),
                            mo.ui.plotly(
                                px.bar(
                                    artists_df,
                                    x="hours",
                                    y="artist_name",
                                    orientation="h",
                                    title="Top artists",
                                )
                            ),
                        ]
                    ),
                    mo.vstack(
                        [
                            mo.md("**Tracks**"),
                            mo.ui.plotly(
                                px.bar(
                                    tracks_df,
                                    x="hours",
                                    y="track_name",
                                    orientation="h",
                                    title="Top tracks",
                                )
                            ),
                        ]
                    ),
                    mo.vstack(
                        [
                            mo.md("**Albums**"),
                            mo.ui.plotly(
                                px.bar(
                                    albums_df,
                                    x="hours",
                                    y="album_name",
                                    orientation="h",
                                    title="Top albums",
                                )
                            ),
                        ]
                    ),
                    mo.vstack(
                        [
                            mo.md("**Podcast shows**"),
                            mo.ui.plotly(
                                px.bar(
                                    shows_df,
                                    x="hours",
                                    y="episode_show_name",
                                    orientation="h",
                                    title="Top shows",
                                )
                            ),
                        ]
                    ),
                ],
                gap=1,
            ),
            mo.md("### Discovery vs repeats · Shuffle intent · Circadian"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_disc),
                    mo.ui.plotly(fig_shuffle),
                    mo.ui.plotly(fig_circ),
                ],
                gap=1,
            ),
            mo.md("### Album depth · Offline · Longest sessions"),
            mo.vstack([mo.ui.plotly(fig_depth), mo.ui.plotly(fig_offline)], gap=1),
            mo.md(
                "**Longest listening sessions** (new session after a 30-minute gap)"
            ),
            mo.ui.table(sessions_df),
            mo.md("### Forgotten · Comebacks"),
            mo.vstack(
                [
                    mo.vstack(
                        [
                            mo.md("**Forgotten** (≥20h, silent >2y)"),
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
            mo.md("### Longitudinal (filter-aware)"),
            mo.vstack([mo.ui.plotly(fig_monthly), mo.ui.plotly(fig_kind)], gap=1),
            mo.vstack([platform_plot, mo.ui.plotly(fig_country)], gap=1),
            mo.ui.plotly(fig_skips),
            mo.md("### Expanded views"),
            mo.vstack([mo.ui.plotly(fig_tree), mo.ui.plotly(fig_cal)], gap=1),
            mo.vstack([mo.ui.plotly(fig_bump), scatter_plot], gap=1),
            mo.ui.plotly(fig_sun),
            mb_block,
            library_block,
            narrative_out,
        ],
        gap=0.5,
    )


def render_telegram_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    people_chat_types: list[str],
    dow_labels: dict[int, str],
    controls: TelegramControls,
    filter_from_widgets: Callable[..., Any],
    scoreboard: Callable[..., Any],
    streak_stats: Callable[..., Any],
    monthly_by_chat_type: Callable[..., Any],
    me_vs_them: Callable[..., Any],
    messages_by_chat: Callable[..., Any],
    chat_reply_scatter: Callable[..., Any],
    forgotten_chats: Callable[..., Any],
    comeback_chats: Callable[..., Any],
    calendar_daily: Callable[..., Any],
    circadian_heatmap: Callable[..., Any],
    bump_chart_chats: Callable[..., Any],
    media_mix: Callable[..., Any],
    reaction_mix: Callable[..., Any],
    calls_by_year: Callable[..., Any],
) -> Any:
    c = controls
    if c.people_btn.value:
        c.set_types_override(list(people_chat_types))
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

    filters = filter_from_widgets(
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

    score_df = scoreboard(conn, filters, compare_previous=c.compare.value)
    streak_df = streak_stats(conn, filters)

    monthly_df = monthly_by_chat_type(conn, filters)
    me_df = me_vs_them(conn, filters)
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

    chats_df = messages_by_chat(conn, filters, limit=25)

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

    scatter_df = chat_reply_scatter(conn, filters)
    forgotten_df = forgotten_chats(conn, filters)
    comebacks_df = comeback_chats(conn, filters)
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

    calendar_df = calendar_daily(conn, filters)
    circadian_df = circadian_heatmap(conn, filters)
    bump_df = bump_chart_chats(conn, filters, top_n=8)
    if calendar_df.empty:
        fig_cal = px.density_heatmap(title="No calendar data")
    else:
        cal = calendar_df.copy()
        cal["day"] = cal["day"].astype("datetime64[ns]")
        cal["week"] = cal["day"].dt.isocalendar().week.astype(int)
        cal["dow"] = cal["day"].dt.dayofweek
        fig_cal = px.density_heatmap(
            cal,
            x="dow",
            y="week",
            z="events",
            title="Daily events (weekday × ISO week)",
            color_continuous_scale="Blues",
        )
        fig_cal.update_layout(xaxis_title="Weekday (Mon=0)", yaxis_title="ISO week")
    if circadian_df.empty:
        fig_circ = px.density_heatmap(title="No circadian data")
    else:
        circ = circadian_df.copy()
        circ["dow_label"] = circ["dow"].map(dow_labels)
        fig_circ = px.density_heatmap(
            circ,
            x="hour",
            y="dow_label",
            z="events",
            title="Events by weekday × hour (Europe/Rome)",
            color_continuous_scale="Viridis",
        )
        fig_circ.update_layout(xaxis_title="Hour", yaxis_title="Weekday")
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

    media_df = media_mix(conn, filters, exclude_none=True)
    react_df = reaction_mix(conn, filters)
    calls_df = calls_by_year(conn, filters)
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
    people_title = f"Who talks in “{locked}”" if locked else "Who talks (all chats in filter)"
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
                [mo.ui.plotly(fig_words), mo.ui.plotly(fig_emoji), mo.ui.plotly(fig_length)],
                gap=1,
            ),
            mo.md("### People — lock a group chat to see who talks and who replies to whom"),
            mo.vstack([mo.ui.plotly(fig_senders), mo.ui.table(senders_df)], gap=1),
            mo.ui.plotly(fig_sankey),
            narrative_out,
        ],
        gap=0.5,
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
    filters = liq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = liq.scoreboard(conn, filters)
    by_year = liq.connections_by_year(conn, filters)
    companies_df = liq.top_connection_companies(conn, filters)
    titles_df = liq.top_connection_titles(conn, filters)
    career_df = liq.career_timeline(conn)
    conv_df = liq.messages_by_conversation(conn, filters)
    me_df = liq.me_vs_them(conn, filters)
    calendar_df = liq.calendar_daily(conn, filters)
    circadian_df = liq.circadian_heatmap(conn, filters)
    mix_df = liq.activity_mix(conn, filters)
    follows_df = liq.company_follows(conn, filters)

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
    if calendar_df.empty:
        fig_cal = px.density_heatmap(title="No message calendar")
    else:
        cal = calendar_df.copy()
        cal["day"] = cal["day"].astype("datetime64[ns]")
        cal["week"] = cal["day"].dt.isocalendar().week.astype(int)
        cal["dow"] = cal["day"].dt.dayofweek
        fig_cal = px.density_heatmap(
            cal,
            x="dow",
            y="week",
            z="events",
            title="Messages (weekday × ISO week)",
            color_continuous_scale="Blues",
        )
        fig_cal.update_layout(xaxis_title="Weekday (Mon=0)", yaxis_title="ISO week")
    if circadian_df.empty:
        fig_circ = px.density_heatmap(title="No circadian data")
    else:
        circ = circadian_df.copy()
        circ["dow_label"] = circ["dow"].map(dow_labels)
        fig_circ = px.density_heatmap(
            circ,
            x="hour",
            y="dow_label",
            z="events",
            title="Messages by weekday × hour (Europe/Rome)",
            color_continuous_scale="Viridis",
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
            mo.hstack([controls.year_start, controls.year_end], justify="start", gap=1),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.md("### Network"),
            mo.vstack([mo.ui.plotly(fig_conn), mo.ui.plotly(fig_co)], gap=1),
            mo.ui.plotly(fig_title),
            mo.md("### Career"),
            mo.ui.table(career_df),
            mo.md("### Messages"),
            mo.vstack([mo.ui.plotly(fig_me), mo.ui.table(conv_df)], gap=1),
            mo.vstack([mo.ui.plotly(fig_cal), mo.ui.plotly(fig_circ)], gap=1),
            mo.md("### Activity · company follows"),
            mo.vstack([mo.ui.plotly(fig_mix), mo.ui.table(follows_df)], gap=1),
        ],
        gap=0.5,
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
            foot_zip.groupby("zip_part", as_index=False)["bytes"].sum().sort_values(
                "bytes", ascending=False
            ),
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
    if circ.empty:
        fig_circ = px.density_heatmap(title="No order circadian")
    else:
        c = circ.copy()
        c["dow_label"] = c["dow"].map(dow_labels)
        fig_circ = px.density_heatmap(
            c,
            x="hour",
            y="dow_label",
            z="events",
            title="Orders by weekday × hour (Europe/Rome)",
            color_continuous_scale="Oranges",
        )
    if cal.empty:
        fig_cal = px.density_heatmap(title="No order calendar")
    else:
        cal2 = cal.copy()
        cal2["day"] = pd.to_datetime(cal2["day"])
        cal2["week"] = cal2["day"].dt.isocalendar().week.astype(int)
        cal2["dow"] = cal2["day"].dt.dayofweek
        fig_cal = px.density_heatmap(
            cal2,
            x="dow",
            y="week",
            z="orders",
            title="Order calendar (weekday × ISO week)",
            color_continuous_scale="YlOrRd",
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
        mo.md("### Spend scoreboard"),
        mo.ui.table(score),
        mo.vstack([mo.ui.plotly(fig_fx), mo.ui.plotly(fig_aov)], gap=1),
        mo.md("### Life chapters & rhythm"),
        mo.vstack([mo.ui.plotly(fig_chapters), mo.ui.plotly(fig_chapters_spend)], gap=1),
        mo.vstack([mo.ui.plotly(fig_month), mo.ui.plotly(fig_month_fx)], gap=1),
        mo.vstack([mo.ui.plotly(fig_cancel), mo.ui.plotly(fig_basket)], gap=1),
        mo.vstack([mo.ui.plotly(fig_circ), mo.ui.plotly(fig_cal)], gap=1),
        mo.md("### What you buy"),
        mo.vstack([mo.ui.plotly(fig_tree), mo.ui.plotly(fig_sun)], gap=1),
        mo.ui.plotly(fig_digi),
        mo.ui.table(products),
        mo.md("### How you shop — search funnel"),
        mo.vstack([mo.ui.plotly(fig_funnel), mo.ui.table(funnel)], gap=1),
        mo.ui.plotly(fig_kw),
        mo.md("### Returns & loyalty"),
        mo.vstack([mo.ui.plotly(fig_returns), mo.ui.plotly(fig_comeback)], gap=1),
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
            px.bar(a_tags, x="n", y="tag", orientation="h", title="Alexa utterance tags")
            if not a_tags.empty
            else px.bar(title="No Alexa tags")
        )
        fig_a_month = (
            px.bar(a_month, x="month_start", y="utterances", title="Alexa utterances / month")
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
        if a_circ.empty:
            fig_a_circ = px.density_heatmap(title="No Alexa circadian")
        else:
            ac = a_circ.copy()
            ac["dow_label"] = ac["dow"].map(dow_labels)
            fig_a_circ = px.density_heatmap(
                ac,
                x="hour",
                y="dow_label",
                z="events",
                title="Alexa by weekday × hour",
                color_continuous_scale="Purples",
            )
        fig_dev = (
            px.pie(a_dev, names="device_type", values="events", title="Alexa device sessions")
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


def render_twitter_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    dow_labels: dict[int, str],
    controls: TwitterControls,
    filter_from_widgets: Callable[..., Any],
    scoreboard: Callable[..., Any],
    streak_stats: Callable[..., Any],
    top_mentions: Callable[..., Any],
    top_replied_to: Callable[..., Any],
    top_hashtags: Callable[..., Any],
    top_liked_accounts: Callable[..., Any],
    tweet_type_mix: Callable[..., Any],
    client_mix: Callable[..., Any],
    media_mix: Callable[..., Any],
    discovery_vs_repeats: Callable[..., Any],
    monthly_volume: Callable[..., Any],
    monthly_by_type: Callable[..., Any],
    likes_by_year: Callable[..., Any],
    language_mix: Callable[..., Any],
    circadian_heatmap: Callable[..., Any],
    calendar_daily: Callable[..., Any],
    bump_chart_accounts: Callable[..., Any],
    account_reply_scatter: Callable[..., Any],
    forgotten_accounts: Callable[..., Any],
    comeback_accounts: Callable[..., Any],
    hashtag_account_treemap: Callable[..., Any],
    dm_volume: Callable[..., Any],
    top_dm_conversations: Callable[..., Any],
    network_snapshot: Callable[..., Any],
    narrative_context: Callable[..., Any],
    narrate: Callable[..., Any],
    has_table: Callable[..., Any],
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

    filters = filter_from_widgets(
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

    score_df = scoreboard(conn, filters, compare_previous=c.compare.value)
    streak_df = streak_stats(conn, filters)
    mentions_df = top_mentions(conn, filters)
    replied_df = top_replied_to(conn, filters)
    hashtags_df = top_hashtags(conn, filters)
    liked_accounts_df = top_liked_accounts(conn, filters)
    type_df = tweet_type_mix(conn, filters)
    client_df = client_mix(conn, filters)
    media_df = media_mix(conn, filters, exclude_none=True)
    discovery_df = discovery_vs_repeats(conn, filters)
    monthly_df = monthly_volume(conn, filters)
    monthly_type_df = monthly_by_type(conn, filters)
    likes_df = likes_by_year(conn, filters)
    lang_df = language_mix(conn, filters)
    calendar_df = calendar_daily(conn, filters)
    circadian_df = circadian_heatmap(conn, filters)
    bump_df = bump_chart_accounts(conn, filters, top_n=8)
    scatter_df = account_reply_scatter(conn, filters)
    forgotten_df = forgotten_accounts(conn, filters)
    comebacks_df = comeback_accounts(conn, filters)
    treemap_df = hashtag_account_treemap(conn, filters)
    network_df = network_snapshot(conn)

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

    if calendar_df.empty:
        fig_cal = px.density_heatmap(title="No calendar data")
    else:
        cal = calendar_df.copy()
        cal["day"] = cal["day"].astype("datetime64[ns]")
        cal["week"] = cal["day"].dt.isocalendar().week.astype(int)
        cal["dow"] = cal["day"].dt.dayofweek
        fig_cal = px.density_heatmap(
            cal,
            x="dow",
            y="week",
            z="tweets",
            title="Daily tweets (weekday × ISO week)",
            color_continuous_scale="Blues",
        )
        fig_cal.update_layout(xaxis_title="Weekday (Mon=0)", yaxis_title="ISO week")

    if circadian_df.empty:
        fig_circ = px.density_heatmap(title="No circadian data")
    else:
        circ = circadian_df.copy()
        circ["dow_label"] = circ["dow"].map(dow_labels)
        fig_circ = px.density_heatmap(
            circ,
            x="hour",
            y="dow_label",
            z="tweets",
            title="Tweets by weekday × hour (Europe/Rome)",
            color_continuous_scale="Viridis",
        )
        fig_circ.update_layout(xaxis_title="Hour", yaxis_title="Weekday")

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
    if has_table(conn, "dm_messages"):
        dm_df = dm_volume(conn, filters)
        top_dm = top_dm_conversations(conn, filters)
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
        ctx = narrative_context(conn, filters)
        narrative_block = [mo.md("### Narrative"), mo.md(narrate(ctx))]

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


def render_sleep_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: SleepControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = slq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
        tags=controls.tag_select.value or None,
        min_rating=controls.min_rating.value,
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = slq.scoreboard(conn, filters, compare_previous=bool(controls.compare.value))
    streak_df = slq.streak_stats(conn, filters)
    regular_df = slq.regularity_stats(conn, filters)
    monthly_df = slq.monthly_hours(conn, filters)
    hours_df = slq.hours_over_time(conn, filters)
    snore_df = slq.snore_noise_monthly(conn, filters)
    bed_df = slq.bedtime_distribution(conn, filters)
    wake_df = slq.wake_distribution(conn, filters)
    weekday_df = slq.weekday_hours(conn, filters)
    circ_df = slq.circadian_heatmap(conn, filters)
    cal_df = slq.calendar_daily(conn, filters)
    events_df = slq.event_type_counts(conn, filters)
    stages_df = slq.stage_event_mix(conn, filters)
    tags_df = slq.tag_breakdown(conn, filters)
    best_df, worst_df = slq.best_worst_nights(conn, filters)
    n_act = int(controls.act_nights.value or 1)
    act_df = slq.sample_actigraphy(conn, filters, limit_sessions=n_act)
    hr_df = slq.session_heart_rate(conn, filters, limit_sessions=n_act)
    nightly_hr_df = slq.nightly_heart_rate(conn, filters)
    alarm_df = slq.alarm_vs_wake(conn, filters)
    alarm_cfg_df = slq.alarm_summary(conn)
    late_df = slq.late_night_spotify_vs_sleep(conn, filters)
    late_bucket_df = slq.late_night_spotify_buckets(conn, filters)

    if snore_df.empty:
        fig_snore = px.line(title="No snore / noise data")
    else:
        fig_snore = px.line(
            snore_df,
            x="month",
            y=["avg_snore", "snore_nights_pct"],
            title="Monthly snore (avg) and % nights with snoring",
            labels={"value": "value", "variable": "metric"},
        )
    fig_noise = (
        px.line(snore_df, x="month", y="avg_noise", title="Monthly average noise")
        if not snore_df.empty
        else px.line(title="No noise data")
    )
    if circ_df.empty:
        fig_circ = px.density_heatmap(title="No bedtime heatmap")
    else:
        circ = circ_df.copy()
        circ["dow_label"] = circ["dow"].map(dow_labels)
        fig_circ = px.density_heatmap(
            circ,
            x="hour",
            y="dow_label",
            z="nights",
            title="Nights by weekday × bedtime hour",
            color_continuous_scale="Viridis",
        )
        fig_circ.update_layout(xaxis_title="Bedtime hour", yaxis_title="Weekday")

    fig_month = (
        px.line(
            monthly_df,
            x="month",
            y=["avg_hours", "avg_deep_hours"],
            title="Monthly average hours / deep hours",
        )
        if not monthly_df.empty
        else px.line(title="No monthly sleep data")
    )
    fig_rating = (
        px.line(monthly_df, x="month", y="avg_rating", title="Monthly average rating")
        if not monthly_df.empty
        else px.line(title="No ratings")
    )
    fig_hours = (
        px.scatter(
            hours_df,
            x="day",
            y="hours",
            color="rating",
            title="Hours slept per night",
            opacity=0.7,
        )
        if not hours_df.empty
        else px.scatter(title="No nights")
    )
    fig_bed = (
        px.bar(bed_df, x="hour", y="nights", title="Bedtime hour distribution")
        if not bed_df.empty
        else px.bar(title="No bedtime data")
    )
    fig_wake = (
        px.bar(wake_df, x="hour", y="nights", title="Wake hour distribution")
        if not wake_df.empty
        else px.bar(title="No wake data")
    )
    if weekday_df.empty:
        fig_dow = px.bar(title="No weekday data")
    else:
        dow = weekday_df.copy()
        dow["dow_label"] = dow["dow"].map(dow_labels)
        fig_dow = px.bar(
            dow, x="dow_label", y="avg_hours", title="Average hours by weekday"
        )
    if cal_df.empty:
        fig_cal = px.density_heatmap(title="No sleep calendar")
    else:
        cal = cal_df.copy()
        cal["day"] = cal["day"].astype("datetime64[ns]")
        cal["week"] = cal["day"].dt.isocalendar().week.astype(int)
        cal["dow"] = cal["day"].dt.dayofweek
        fig_cal = px.density_heatmap(
            cal,
            x="dow",
            y="week",
            z="hours",
            title="Hours slept (weekday × ISO week)",
            color_continuous_scale="Blues",
        )
        fig_cal.update_layout(xaxis_title="Weekday (Mon=0)", yaxis_title="ISO week")
    fig_events = (
        px.bar(
            events_df,
            x="events",
            y="event_type",
            orientation="h",
            title="Top sleep events",
        )
        if not events_df.empty
        else px.bar(title="No events")
    )
    fig_stages = (
        px.bar(
            stages_df,
            x="year",
            y="events",
            color="event_type",
            barmode="stack",
            title="Stage events by year",
        )
        if not stages_df.empty
        else px.bar(title="No stage events")
    )
    fig_tags = (
        px.bar(tags_df, x="nights", y="tag", orientation="h", title="Nights by tag")
        if not tags_df.empty
        else px.bar(title="No tags")
    )
    if act_df.empty:
        fig_act = px.line(title="No actigraphy for the selected nights")
    else:
        act = act_df.copy()
        act["day"] = act["day"].astype(str)
        fig_act = px.line(
            act,
            x="bucket_label",
            y="value",
            facet_row="day",
            title=f"Actigraphy — latest {act['day'].nunique()} night(s) in range",
        )
        fig_act.update_layout(
            xaxis_title="Time bucket",
            height=max(320, 180 * act["day"].nunique()),
        )
        fig_act.update_yaxes(matches=None, title="Intensity")
        fig_act.for_each_annotation(
            lambda a: a.update(text=a.text.split("=")[-1])
        )

    # Mi Band HR overlay: same nights, minutes since bedtime.
    if slq.has_miband_hr(conn):
        if hr_df.empty:
            fig_hr = px.line(title="No Mi Band readings inside the selected nights")
        else:
            hr = hr_df.copy()
            hr["day"] = hr["day"].astype(str)
            fig_hr = px.line(
                hr,
                x="minutes_in",
                y="rate",
                color="day",
                title="Heart rate during the same nights (Mi Band)",
            )
            fig_hr.update_layout(
                xaxis_title="Minutes since bedtime", yaxis_title="bpm"
            )
        if nightly_hr_df.empty:
            fig_night_hr = px.scatter(title="No nights with ≥5 HR readings")
        else:
            fig_night_hr = px.scatter(
                nightly_hr_df,
                x="avg_bpm",
                y="hours",
                color="rating",
                hover_data=["day", "min_bpm", "readings"],
                title="Nightly avg HR vs hours slept",
            )
            fig_night_hr.update_layout(xaxis_title="Avg bpm", yaxis_title="Hours")
        hr_block = mo.vstack(
            [
                mo.md("### Heart rate overlay (Mi Band)"),
                mo.vstack([mo.ui.plotly(fig_hr), mo.ui.plotly(fig_night_hr)], gap=1),
            ],
            gap=0.5,
        )
    else:
        hr_block = mo.md(
            "_HR overlay needs `miband.heart_rate`. Stop this notebook, then: "
            "`uv run ingest ~/Documents/data_dumps_raw/miband_hr/heart_rate.csv`_"
        )

    # Alarms: scheduled vs actual wake.
    if alarm_df.empty:
        fig_alarm = px.histogram(title="No scheduled-alarm nights in range")
    else:
        fig_alarm = px.histogram(
            alarm_df,
            x="wake_minus_alarm_min",
            nbins=40,
            title="Wake time minus alarm (minutes; negative = woke early)",
        )
        fig_alarm.update_layout(xaxis_title="Minutes", yaxis_title="Nights")
    alarm_children: list[Any] = [
        mo.md("### Alarms"),
        mo.ui.plotly(fig_alarm),
    ]
    if not alarm_cfg_df.empty:
        alarm_children.append(
            mo.vstack(
                [mo.md("**Configured alarms (alarms.json)**"), mo.ui.table(alarm_cfg_df)]
            )
        )
    alarm_block = mo.vstack(alarm_children, gap=0.5)

    # Cross-source: late-evening Spotify vs sleep quality.
    if slq.has_spotify_plays(conn):
        if late_df.empty:
            fig_late = px.scatter(title="No overlapping Spotify / sleep nights")
        else:
            fig_late = px.scatter(
                late_df,
                x="late_spotify_hours",
                y="hours",
                color="rating",
                hover_data=["day", "deep_hours"],
                opacity=0.6,
                title="Spotify after 22:00 (same evening) vs hours slept",
            )
            fig_late.update_layout(
                xaxis_title="Late-evening listening (h)", yaxis_title="Hours slept"
            )
        if late_bucket_df.empty:
            fig_late_bucket = px.bar(title="No late-listening buckets")
        else:
            fig_late_bucket = px.bar(
                late_bucket_df,
                x="bucket",
                y="avg_rating",
                hover_data=["nights", "avg_hours", "avg_deep_hours"],
                title="Average sleep rating by late-evening listening",
            )
            fig_late_bucket.update_layout(xaxis_title="Listening after 22:00", yaxis_title="Avg rating")
        late_block = mo.vstack(
            [
                mo.md("### Late-night Spotify × sleep"),
                mo.vstack([mo.ui.plotly(fig_late), mo.ui.plotly(fig_late_bucket)], gap=1),
                mo.ui.table(late_bucket_df),
            ],
            gap=0.5,
        )
    else:
        late_block = mo.md(
            "_Late-night listening chart needs `spotify.plays` in the same warehouse._"
        )

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Sleep as Android\n"
                f"{span}. Sessions, stage events, and actigraphy from merged exports."
            ),
            mo.hstack(
                [
                    controls.year_start,
                    controls.year_end,
                    controls.tag_select,
                    controls.min_rating,
                ],
                justify="start",
                gap=1,
            ),
            mo.hstack([controls.compare, controls.act_nights], justify="start", gap=1),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md(
                "**Regularity** — bedtime/wake spread (stddev, hours) and social jet lag "
                "(Fri/Sat nights minus weeknights)."
            ),
            mo.ui.table(regular_df),
            mo.md("### Longitudinal"),
            mo.vstack(
                [mo.ui.plotly(fig_month), mo.ui.plotly(fig_rating), mo.ui.plotly(fig_hours)],
                gap=1,
            ),
            mo.vstack([mo.ui.plotly(fig_snore), mo.ui.plotly(fig_noise)], gap=1),
            mo.md("### Circadian"),
            mo.vstack(
                [mo.ui.plotly(fig_bed), mo.ui.plotly(fig_wake), mo.ui.plotly(fig_dow)],
                gap=1,
            ),
            mo.ui.plotly(fig_circ),
            mo.md("### Calendar"),
            mo.ui.plotly(fig_cal),
            mo.md("### Events · stages · tags"),
            mo.vstack(
                [mo.ui.plotly(fig_events), mo.ui.plotly(fig_stages), mo.ui.plotly(fig_tags)],
                gap=1,
            ),
            mo.md("### Actigraphy"),
            mo.ui.plotly(fig_act),
            hr_block,
            alarm_block,
            late_block,
            mo.md("### Best / shortest nights"),
            mo.vstack([mo.ui.table(best_df), mo.ui.table(worst_df)], gap=1),
        ],
        gap=0.5,
    )


def render_miband_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: MiBandControls,
    dow_labels: dict[int, str],
) -> Any:
    filters = mbq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = mbq.scoreboard(conn, filters)
    daily_df = mbq.daily_avg(conn, filters)
    hour_df = mbq.hour_of_day(conn, filters)
    heat_df = mbq.weekday_hour_heatmap(conn, filters)
    zone_df = mbq.zone_mix(conn, filters)
    ext_df = mbq.extremes(conn, filters)

    fig_daily = (
        px.line(daily_df, x="day", y="avg_bpm", title="Daily average heart rate")
        if not daily_df.empty
        else px.line(title="No HR readings")
    )
    fig_hour = (
        px.bar(hour_df, x="hour", y="avg_bpm", title="Average BPM by hour of day")
        if not hour_df.empty
        else px.bar(title="No hourly data")
    )
    if heat_df.empty:
        fig_heat = px.density_heatmap(title="No heatmap data")
    else:
        heat = heat_df.copy()
        heat["dow_label"] = heat["dow"].map(dow_labels)
        fig_heat = px.density_heatmap(
            heat,
            x="hour",
            y="dow_label",
            z="avg_bpm",
            title="Average BPM by weekday × hour",
            color_continuous_scale="Reds",
        )
    fig_zone = (
        px.pie(zone_df, names="rate_zone", values="readings", title="Rate zone mix")
        if not zone_df.empty
        else px.pie(title="No zone data")
    )

    span = (
        f"{bounds['first_day']} → {bounds['last_day']}"
        if bounds.get("first_day")
        else "no dated rows"
    )
    return mo.vstack(
        [
            mo.md(
                f"## Mi Band heart rate\n"
                f"{span}. One-off Mi Fit export (`dateTime, rate, rateZone`)."
            ),
            mo.hstack([controls.year_start, controls.year_end], justify="start", gap=1),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.md("### Time series"),
            mo.vstack([mo.ui.plotly(fig_daily), mo.ui.plotly(fig_hour)], gap=1),
            mo.md("### Heatmap · zones"),
            mo.vstack([mo.ui.plotly(fig_heat), mo.ui.plotly(fig_zone)], gap=1),
            mo.md("### Extremes"),
            mo.ui.table(ext_df),
        ],
        gap=0.5,
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
    filters = tbq.filter_from_widgets(
        bounds,
        year_start=controls.year_start.value,
        year_end=controls.year_end.value,
        account_keys=list(controls.account_select.value or []),
        folder_ids=[int(x) for x in (controls.folder_select.value or [])],
        directions=list(controls.direction_select.value or []),
        signal_kinds=list(controls.signal_select.value or []),
        contact_substr=controls.contact_search.value or None,
    )
    chips = filters.chip_labels()
    chip_row = (
        mo.hstack([mo.md(f"**{label}**") for _, label in chips], gap=0.5)
        if chips
        else mo.md("_Full date range_")
    )

    score_df = tbq.scoreboard(
        conn, filters, compare_previous=bool(controls.compare.value)
    )
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
    threads_df = tbq.thread_sizes(conn, filters)
    att_df = tbq.attachment_extensions(conn, filters)
    sig_df = tbq.signal_mix(conn, filters)
    sig_m_df = tbq.signal_monthly(conn, filters)

    if controls.mask_addrs.value:
        if not senders_df.empty and "contact" in senders_df.columns:
            senders_df = senders_df.copy()
            senders_df["contact"] = senders_df["contact"].map(tbq.mask_addr)
        if not recipients_df.empty and "contact" in recipients_df.columns:
            recipients_df = recipients_df.copy()
            recipients_df["contact"] = recipients_df["contact"].map(tbq.mask_addr)

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
    if heat_df.empty:
        fig_heat = px.density_heatmap(title="No circadian data")
    else:
        heat = heat_df.copy()
        heat["dow_label"] = heat["dow"].map(dow_labels)
        fig_heat = px.density_heatmap(
            heat,
            x="hour",
            y="dow_label",
            z="messages",
            title="Messages by weekday × hour (Rome)",
            color_continuous_scale="Blues",
            histfunc="sum",
        )
    cal = cal_df.copy()
    if not cal.empty:
        cal["day"] = pd.to_datetime(cal["day"], errors="coerce")
        cal = cal.dropna(subset=["day"])
    if cal.empty:
        fig_cal = px.density_heatmap(title="No calendar data")
    else:
        iso = cal["day"].dt.isocalendar()
        cal["week"] = iso["week"].astype(int)
        cal["dow"] = cal["day"].dt.dayofweek
        cal["year"] = iso["year"].astype(int)
        fig_cal = px.density_heatmap(
            cal,
            x="week",
            y="dow",
            z="messages",
            facet_row="year",
            histfunc="sum",
            title="Daily volume calendar",
            color_continuous_scale="Greens",
        )
    fig_domains = (
        px.bar(domains_df, x="messages", y="domain", orientation="h", title="Top domains")
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
                [controls.year_start, controls.year_end, controls.compare, controls.mask_addrs],
                justify="start",
                gap=1,
            ),
            mo.hstack(
                [
                    controls.account_select,
                    controls.folder_select,
                    controls.direction_select,
                    controls.signal_select,
                    controls.contact_search,
                ],
                justify="start",
                gap=1,
            ),
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.md("### Volume"),
            mo.vstack([mo.ui.plotly(fig_monthly), mo.ui.plotly(fig_yearly)], gap=1),
            mo.md("### Circadian · calendar"),
            mo.vstack([mo.ui.plotly(fig_heat), mo.ui.plotly(fig_cal)], gap=1),
            mo.md("### People"),
            mo.hstack(
                [
                    mo.vstack([mo.md("**Top senders (received)**"), mo.ui.table(senders_df)]),
                    mo.vstack(
                        [mo.md("**Top recipients (sent)**"), mo.ui.table(recipients_df)]
                    ),
                ],
                gap=1,
            ),
            mo.md("### Domains"),
            mo.vstack([mo.ui.plotly(fig_domains), mo.ui.plotly(fig_sun)], gap=1),
            mo.md("### Folders · accounts"),
            mo.vstack([mo.ui.plotly(fig_folders), mo.ui.plotly(fig_accounts)], gap=1),
            mo.md("### Threads"),
            mo.ui.table(threads_df),
            mo.md("### Attachments · signals"),
            mo.vstack(
                [
                    mo.ui.plotly(fig_att),
                    mo.ui.plotly(fig_sig),
                    mo.ui.plotly(fig_sig_m),
                ],
                gap=1,
            ),
        ],
        gap=0.5,
    )


def _slack_heatmap(
    px: Any, df: pd.DataFrame, dow_labels: dict[int, str], **kw: Any
) -> Any:
    if df.empty:
        return px.density_heatmap(title=kw.get("title", "No data"))
    heat = df.copy()
    heat["dow_label"] = heat["dow"].map(dow_labels)
    z = kw.pop("z", "messages")
    fig = px.density_heatmap(
        heat,
        x="hour",
        y="dow_label",
        z=z,
        histfunc="sum",
        color_continuous_scale="Blues",
        category_orders={"dow_label": [dow_labels[i] for i in sorted(dow_labels)]},
        **kw,
    )
    fig.update_layout(xaxis_title="Hour (Paris)", yaxis_title="")
    return fig


def _slack_calendar(px: Any, df: pd.DataFrame, title: str) -> Any:
    if df.empty:
        return px.density_heatmap(title=title)
    cal = df.copy()
    cal["day"] = pd.to_datetime(cal["day"])
    iso = cal["day"].dt.isocalendar()
    cal["year"] = iso["year"].astype(int)
    cal["week"] = iso["week"].astype(int)
    cal["dow"] = cal["day"].dt.dayofweek
    fig = px.density_heatmap(
        cal,
        x="week",
        y="dow",
        z="messages",
        facet_row="year",
        histfunc="sum",
        color_continuous_scale="Greens",
        title=title,
    )
    fig.update_layout(height=max(320, 120 * cal["year"].nunique()))
    fig.update_yaxes(matches=None, autorange="reversed", title="")
    fig.update_xaxes(title="ISO week")
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    return fig


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
                mo.hstack(
                    [mo.ui.plotly(fig_pheat), mo.ui.plotly(fig_theat)], widths="equal"
                ),
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


def _browser_calendar(px: Any, df: pd.DataFrame, title: str) -> Any:
    if df.empty:
        return px.density_heatmap(title=title)
    cal = df.copy()
    cal["day"] = pd.to_datetime(cal["day"])
    iso = cal["day"].dt.isocalendar()
    cal["year"] = iso["year"].astype(int)
    cal["week"] = iso["week"].astype(int)
    cal["dow"] = cal["day"].dt.dayofweek
    fig = px.density_heatmap(
        cal,
        x="week",
        y="dow",
        z="urls",
        facet_row="year",
        title=title,
        color_continuous_scale="Teal",
    )
    fig.update_layout(yaxis_title="Mon=0 … Sun=6")
    return fig


def render_browser_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    controls: BrowserControls,
    narrate: Callable[..., Any] | None = None,
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
    tree_df = (
        brq.path_tree(conn, filters, etld1=locked)
        if locked
        else pd.DataFrame()
    )

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
    if narrate is not None and c.narrate_btn.value:
        ctx = brq.narrative_context(conn, filters)
        try:
            text, _cached = narrate(
                ctx,
                system="Summarize this browsing-history view from aggregates only.",
            )
        except Exception as exc:  # noqa: BLE001 — surface LLM errors in UI
            text = f"Narration failed: {exc}"
        narrate_block = mo.md(f"### Narration\n\n{text}")

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
