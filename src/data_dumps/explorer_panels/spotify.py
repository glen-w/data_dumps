"""Spotify explorer tab controls and panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

import data_dumps.spotify_queries as spq
from data_dumps.llm_client import narrate as llm_narrate

from . import charts as panel_charts


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


def render_spotify_panel(
    *,
    mo: Any,
    px: Any,
    conn: duckdb.DuckDBPyConnection,
    bounds: dict[str, Any],
    mb_ready: bool,
    controls: SpotifyControls,
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

    filters = spq.filter_from_widgets(
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

    top_artists_df = spq.top_artists(conn, filters, limit=20)
    top_artists_table = mo.ui.table(
        top_artists_df, selection="single", on_change=_lock_artist_from_table
    )

    score_df = spq.scoreboard(conn, filters, compare_previous=c.compare.value)
    streak_df = spq.streak_stats(conn, filters)
    milestones_df = spq.milestones(conn, filters)
    offline_df = spq.offline_vs_online(conn, filters)
    depth_df = spq.album_depth(conn, filters, limit=15)
    sessions_df = spq.listening_sessions(conn, filters, limit=15)
    movement_df = spq.artist_rank_movement(conn, filters, limit=15)
    timeline_df = spq.artist_monthly_timeline(conn, filters)

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

    artists_df = spq.top_artists(conn, filters, limit=15)
    tracks_df = spq.top_tracks(conn, filters, limit=15)
    albums_df = spq.top_albums(conn, filters, limit=15)
    shows_df = spq.top_shows(conn, filters, limit=15)

    discovery_df = spq.discovery_vs_repeats(conn, filters)
    shuffle_df = spq.shuffle_intent(conn, filters)
    circadian_df = spq.circadian_heatmap(conn, filters)
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
    fig_circ = panel_charts.circadian_heatmap(
        px,
        circadian_df,
        z="hours",
        dow_labels={
            1: "Sun",
            2: "Mon",
            3: "Tue",
            4: "Wed",
            5: "Thu",
            6: "Fri",
            7: "Sat",
        },
        title="Hours by weekday × hour (local)",
        empty_title="No circadian data for filter",
    )

    forgotten_df = spq.forgotten_artists(conn, filters)
    comebacks_df = spq.comeback_artists(conn, filters)

    monthly_df = spq.monthly_hours(conn, filters)
    kind_df = spq.hours_by_kind(conn, filters)
    platform_df = spq.hours_by_platform(conn, filters)
    country_df = spq.hours_by_country(conn, filters)
    skips_df = spq.skip_trends(conn, filters)
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

    treemap_df = spq.treemap_artist_album(conn, filters)
    calendar_df = spq.calendar_daily(conn, filters)
    bump_df = spq.bump_chart_artists(conn, filters, top_n=10)
    scatter_df = spq.artist_hours_vs_skip(conn, filters)
    sunburst_df = spq.kind_platform_sunburst(conn, filters)
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
        genre_df = spq.genre_treemap(conn, filters)
        decade_df = spq.decade_bars(conn, filters)
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

    if spq.has_account_data(conn):
        lib_counts = spq.library_counts(conn)
        overlap_df = spq.library_overlap(conn, limit=15)
        never_df = spq.library_never_played(conn, limit=15)
        playlists_df = spq.playlist_sizes(conn, limit=20)
        search_df = spq.search_volume(conn)
        top_q = spq.top_searches(conn, limit=15)
        rarely_df = spq.searched_but_rarely_played(conn, limit=15)
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
        ctx = spq.narrative_context(conn, filters)
        text, cached = llm_narrate(ctx)
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
            mo.md("**Longest listening sessions** (new session after a 30-minute gap)"),
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
