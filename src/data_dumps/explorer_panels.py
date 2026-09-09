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

from data_dumps import linkedin_queries as liq
from data_dumps import miband_queries as mbq
from data_dumps import sleep_queries as slq
from data_dumps.spotify_queries import (
    has_account_data,
    library_counts,
    library_never_played,
    library_overlap,
    playlist_sizes,
    search_volume,
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
class SleepControls:
    year_start: Any
    year_end: Any
    tag_select: Any
    min_rating: Any


@dataclass
class MiBandControls:
    year_start: Any
    year_end: Any


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
                [c.compare, c.people_btn, c.clear_types, c.clear_chat, c.clear_media],
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

    score_df = slq.scoreboard(conn, filters)
    streak_df = slq.streak_stats(conn, filters)
    monthly_df = slq.monthly_hours(conn, filters)
    hours_df = slq.hours_over_time(conn, filters)
    bed_df = slq.bedtime_distribution(conn, filters)
    wake_df = slq.wake_distribution(conn, filters)
    weekday_df = slq.weekday_hours(conn, filters)
    cal_df = slq.calendar_daily(conn, filters)
    events_df = slq.event_type_counts(conn, filters)
    stages_df = slq.stage_event_mix(conn, filters)
    tags_df = slq.tag_breakdown(conn, filters)
    best_df, worst_df = slq.best_worst_nights(conn, filters)
    act_df = slq.sample_actigraphy(conn, filters)

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
        fig_act = px.line(title="No actigraphy for latest night")
    else:
        fig_act = px.line(
            act_df,
            x="bucket_label",
            y="value",
            color="day",
            title="Actigraphy (latest night in range)",
        )
        fig_act.update_layout(xaxis_title="Time bucket", yaxis_title="Intensity")

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
            chip_row,
            mo.md("### Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
            mo.md("### Longitudinal"),
            mo.vstack(
                [mo.ui.plotly(fig_month), mo.ui.plotly(fig_rating), mo.ui.plotly(fig_hours)],
                gap=1,
            ),
            mo.md("### Circadian"),
            mo.vstack(
                [mo.ui.plotly(fig_bed), mo.ui.plotly(fig_wake), mo.ui.plotly(fig_dow)],
                gap=1,
            ),
            mo.md("### Calendar"),
            mo.ui.plotly(fig_cal),
            mo.md("### Events · stages · tags"),
            mo.vstack(
                [mo.ui.plotly(fig_events), mo.ui.plotly(fig_stages), mo.ui.plotly(fig_tags)],
                gap=1,
            ),
            mo.md("### Actigraphy sample"),
            mo.ui.plotly(fig_act),
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
