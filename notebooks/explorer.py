import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.llm_client import narrate
    from data_dumps.paths import warehouse_db
    from data_dumps.spotify_queries import (
        artist_hours_vs_skip,
        bump_chart_artists,
        calendar_daily as sp_calendar_daily,
        circadian_heatmap as sp_circadian_heatmap,
        comeback_artists,
        data_bounds as sp_data_bounds,
        decade_bars,
        discovery_vs_repeats,
        filter_from_widgets as sp_filter_from_widgets,
        forgotten_artists,
        genre_treemap,
        has_mb_data,
        hours_by_country,
        hours_by_kind,
        hours_by_platform,
        kind_platform_sunburst,
        monthly_hours,
        narrative_context,
        scoreboard as sp_scoreboard,
        shuffle_intent,
        skip_trends,
        streak_stats as sp_streak_stats,
        top_albums,
        top_artists,
        top_shows,
        top_tracks,
        treemap_artist_album,
    )
    from data_dumps.telegram_queries import (
        PEOPLE_CHAT_TYPES,
        bump_chart_chats,
        calendar_daily as tg_calendar_daily,
        calls_by_year,
        chat_reply_scatter,
        circadian_heatmap as tg_circadian_heatmap,
        comeback_chats,
        data_bounds as tg_data_bounds,
        filter_from_widgets as tg_filter_from_widgets,
        forgotten_chats,
        me_vs_them,
        media_mix,
        messages_by_chat,
        monthly_by_chat_type,
        reaction_mix,
        scoreboard as tg_scoreboard,
        streak_stats as tg_streak_stats,
    )

    def _has_table(conn, schema: str, table: str) -> bool:
        row = conn.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = ? AND table_name = ?
            """,
            [schema, table],
        ).fetchone()
        return row is not None and row[0] > 0

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run ingest, then reopen this notebook."
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    has_spotify = _has_table(conn, "spotify", "plays")
    has_telegram = _has_table(conn, "telegram", "messages")
    sp_bounds = sp_data_bounds(conn) if has_spotify else None
    tg_bounds = tg_data_bounds(conn) if has_telegram else None
    mb_ready = has_mb_data(conn) if has_spotify else False
    tg_dow = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    return (
        PEOPLE_CHAT_TYPES,
        artist_hours_vs_skip,
        bump_chart_artists,
        bump_chart_chats,
        calls_by_year,
        chat_reply_scatter,
        comeback_artists,
        comeback_chats,
        conn,
        decade_bars,
        discovery_vs_repeats,
        forgotten_artists,
        forgotten_chats,
        genre_treemap,
        has_spotify,
        has_telegram,
        hours_by_country,
        hours_by_kind,
        hours_by_platform,
        kind_platform_sunburst,
        mb_ready,
        me_vs_them,
        media_mix,
        messages_by_chat,
        mo,
        monthly_by_chat_type,
        monthly_hours,
        narrate,
        narrative_context,
        px,
        reaction_mix,
        shuffle_intent,
        skip_trends,
        sp_bounds,
        sp_calendar_daily,
        sp_circadian_heatmap,
        sp_filter_from_widgets,
        sp_scoreboard,
        sp_streak_stats,
        tg_bounds,
        tg_calendar_daily,
        tg_circadian_heatmap,
        tg_dow,
        tg_filter_from_widgets,
        tg_scoreboard,
        tg_streak_stats,
        top_albums,
        top_artists,
        top_shows,
        top_tracks,
        treemap_artist_album,
    )


@app.cell(hide_code=True)
def _(has_spotify, has_telegram, mo, sp_bounds, tg_bounds):
    default_tab = "Spotify" if has_spotify else "Telegram"
    sp_caption = (
        f"{sp_bounds['first_day']} → {sp_bounds['last_day']}"
        if sp_bounds
        else "Not ingested"
    )
    tg_caption = (
        f"{tg_bounds['first_day']} → {tg_bounds['last_day']} · {len(tg_bounds['chats'])} chats"
        if tg_bounds
        else "Not ingested"
    )
    source = mo.ui.tabs(
        {
            "Spotify": mo.md(f"_{sp_caption}_"),
            "Telegram": mo.md(f"_{tg_caption}_"),
        },
        value=default_tab if default_tab in ("Spotify", "Telegram") else "Spotify",
    )
    mo.vstack([mo.md("# data dumps"), source], gap=0.5)
    return (source,)


@app.cell(hide_code=True)
def _(has_spotify, mo, source):
    mo.stop(source.value != "Spotify")
    if not has_spotify:
        mo.stop(
            True,
            mo.md(
                "No `spotify.plays` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/spotify/my_spotify_data.zip`"
            ),
        )
    sp_on = True
    return (sp_on,)


@app.cell(hide_code=True)
def _(has_telegram, mo, source):
    mo.stop(source.value != "Telegram")
    if not has_telegram:
        mo.stop(
            True,
            mo.md(
                "No `telegram.messages` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/telegram/Telegram_Export_2026-09-03`"
            ),
        )
    tg_on = True
    return (tg_on,)


@app.cell(hide_code=True)
def _(mo, sp_bounds, sp_on):
    sp_on
    sp_year_start = mo.ui.slider(
        start=sp_bounds["min_year"],
        stop=sp_bounds["max_year"],
        value=sp_bounds["min_year"],
        label="From year",
        show_value=True,
    )
    sp_year_end = mo.ui.slider(
        start=sp_bounds["min_year"],
        stop=sp_bounds["max_year"],
        value=sp_bounds["max_year"],
        label="To year",
        show_value=True,
    )
    sp_kind = mo.ui.multiselect(options=sp_bounds["kinds"], value=[], label="Kind")
    sp_platform = mo.ui.multiselect(
        options=sp_bounds["platforms"], value=[], label="Platform"
    )
    sp_country = mo.ui.multiselect(
        options=sp_bounds["countries"], value=[], label="Country"
    )
    sp_artist_search = mo.ui.text(label="Artist search", placeholder="substring…")
    sp_compare = mo.ui.checkbox(label="Compare vs previous equal window", value=False)
    sp_clear_artist = mo.ui.run_button(label="Clear artist lock")
    sp_clear_kinds = mo.ui.run_button(label="× kinds")
    sp_clear_platform = mo.ui.run_button(label="× platform")
    sp_clear_country = mo.ui.run_button(label="× countries")
    sp_clear_search = mo.ui.run_button(label="× search")
    sp_narrate_btn = mo.ui.run_button(label="Narrate this view")
    get_artist, set_artist = mo.state(None)
    get_kind_override, set_kind_override = mo.state(None)
    get_platform_override, set_platform_override = mo.state(None)
    get_country_override, set_country_override = mo.state(None)
    mo.vstack(
        [
            mo.md(
                f"## Spotify Wrapped\n"
                f"Data: {sp_bounds['first_day']} → {sp_bounds['last_day']} "
                f"(2017 gap is export data, not life)"
            ),
            mo.hstack(
                [sp_year_start, sp_year_end, sp_kind, sp_platform, sp_country],
                justify="start",
                gap=1,
            ),
            mo.hstack(
                [
                    sp_artist_search,
                    sp_compare,
                    sp_clear_artist,
                    sp_clear_kinds,
                    sp_clear_platform,
                    sp_clear_country,
                    sp_clear_search,
                    sp_narrate_btn,
                ],
                gap=1,
            ),
        ],
        gap=0.5,
    )
    return (
        get_artist,
        get_country_override,
        get_kind_override,
        get_platform_override,
        set_artist,
        set_country_override,
        set_kind_override,
        set_platform_override,
        sp_artist_search,
        sp_clear_artist,
        sp_clear_country,
        sp_clear_kinds,
        sp_clear_platform,
        sp_clear_search,
        sp_compare,
        sp_country,
        sp_kind,
        sp_narrate_btn,
        sp_platform,
        sp_year_end,
        sp_year_start,
    )


@app.cell(hide_code=True)
def _(
    set_artist,
    set_country_override,
    set_kind_override,
    set_platform_override,
    sp_artist_search,
    sp_clear_artist,
    sp_clear_country,
    sp_clear_kinds,
    sp_clear_platform,
    sp_clear_search,
    sp_on,
):
    sp_on
    if sp_clear_artist.value:
        set_artist(None)
    if sp_clear_kinds.value:
        set_kind_override([])
    if sp_clear_platform.value:
        set_platform_override([])
    if sp_clear_country.value:
        set_country_override([])
    if sp_clear_search.value:
        sp_artist_search.value = ""
    return


@app.cell(hide_code=True)
def _(
    get_artist,
    get_country_override,
    get_kind_override,
    get_platform_override,
    mo,
    set_country_override,
    set_kind_override,
    set_platform_override,
    sp_artist_search,
    sp_bounds,
    sp_country,
    sp_filter_from_widgets,
    sp_kind,
    sp_on,
    sp_platform,
    sp_year_end,
    sp_year_start,
):
    sp_on
    sp_kinds = (
        get_kind_override() if get_kind_override() is not None else list(sp_kind.value)
    )
    sp_platforms = (
        get_platform_override()
        if get_platform_override() is not None
        else list(sp_platform.value)
    )
    sp_countries = (
        get_country_override()
        if get_country_override() is not None
        else list(sp_country.value)
    )
    if sp_kind.value and get_kind_override() is not None:
        set_kind_override(None)
    if sp_platform.value and get_platform_override() is not None:
        set_platform_override(None)
    if sp_country.value and get_country_override() is not None:
        set_country_override(None)
    sp_filters = sp_filter_from_widgets(
        sp_bounds,
        year_start=sp_year_start.value,
        year_end=sp_year_end.value,
        kinds=sp_kinds,
        platform_buckets=sp_platforms,
        conn_countries=sp_countries,
        artist_search=sp_artist_search.value or None,
        artist_name=get_artist(),
    )
    sp_chips = sp_filters.chip_labels()
    (
        mo.hstack([mo.md(f"**{label}**") for _, label in sp_chips], gap=0.5)
        if sp_chips
        else mo.md("_No extra filters active_")
    )
    return (sp_filters,)


@app.cell(hide_code=True)
def _(conn, mo, sp_filters, sp_on, top_artists):
    sp_on
    sp_top_artists_df = top_artists(conn, sp_filters, limit=20)
    sp_top_artists_table = mo.ui.table(sp_top_artists_df, selection="single")
    mo.vstack(
        [
            mo.md("### Top artists — select a row to filter"),
            sp_top_artists_table,
        ],
        gap=0.5,
    )
    return (sp_top_artists_table,)


@app.cell(hide_code=True)
def _(set_artist, sp_on, sp_top_artists_table):
    sp_on
    _sel = sp_top_artists_table.value
    if _sel is not None and len(_sel) == 1:
        set_artist(_sel.iloc[0]["artist_name"])
    return


@app.cell(hide_code=True)
def _(conn, mo, sp_compare, sp_filters, sp_on, sp_scoreboard, sp_streak_stats):
    sp_on
    sp_score_df = sp_scoreboard(conn, sp_filters, compare_previous=sp_compare.value)
    sp_streak_df = sp_streak_stats(conn, sp_filters)
    mo.vstack(
        [mo.md("### Scoreboard"), mo.ui.table(sp_score_df), mo.ui.table(sp_streak_df)],
        gap=0.5,
    )
    return


@app.cell(hide_code=True)
def _(conn, mo, px, sp_filters, sp_on, top_albums, top_artists, top_shows, top_tracks):
    sp_on
    artists_df = top_artists(conn, sp_filters, limit=15)
    tracks_df = top_tracks(conn, sp_filters, limit=15)
    albums_df = top_albums(conn, sp_filters, limit=15)
    shows_df = top_shows(conn, sp_filters, limit=15)
    mo.vstack(
        [
            mo.md("### Rankings"),
            mo.hstack(
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
        ],
        gap=0.5,
    )
    return


@app.cell(hide_code=True)
def _(
    conn,
    discovery_vs_repeats,
    mo,
    px,
    shuffle_intent,
    sp_circadian_heatmap,
    sp_filters,
    sp_on,
):
    sp_on
    discovery_df = discovery_vs_repeats(conn, sp_filters)
    shuffle_df = shuffle_intent(conn, sp_filters)
    circadian_df = sp_circadian_heatmap(conn, sp_filters)
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
    mo.vstack(
        [
            mo.md("### Discovery vs repeats · Shuffle intent · Circadian"),
            mo.hstack(
                [mo.ui.plotly(fig_disc), mo.ui.plotly(fig_shuffle), mo.ui.plotly(fig_circ)],
                gap=1,
            ),
        ],
        gap=0.5,
    )
    return


@app.cell(hide_code=True)
def _(comeback_artists, conn, forgotten_artists, mo, sp_filters, sp_on):
    sp_on
    forgotten_df = forgotten_artists(conn, sp_filters)
    comebacks_df = comeback_artists(conn, sp_filters)
    mo.vstack(
        [
            mo.md("### Forgotten · Comebacks"),
            mo.hstack(
                [
                    mo.vstack(
                        [mo.md("**Forgotten** (≥20h, silent >2y)"), mo.ui.table(forgotten_df)]
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
        ],
        gap=0.5,
    )
    return


@app.cell(hide_code=True)
def _(
    conn,
    hours_by_country,
    hours_by_kind,
    hours_by_platform,
    mo,
    monthly_hours,
    px,
    skip_trends,
    sp_filters,
    sp_on,
):
    sp_on
    monthly_df = monthly_hours(conn, sp_filters)
    kind_df = hours_by_kind(conn, sp_filters)
    platform_df = hours_by_platform(conn, sp_filters)
    country_df = hours_by_country(conn, sp_filters)
    skips_df = skip_trends(conn, sp_filters)
    if not monthly_df.empty:
        fig_monthly = px.bar(monthly_df, x="year_month", y="hours", title="Hours by month")
        fig_monthly.update_layout(xaxis_tickangle=-45)
    else:
        fig_monthly = px.bar(title="No monthly data")
    fig_kind = px.bar(
        kind_df, x="year", y="hours", color="kind", barmode="stack", title="Hours by kind"
    )
    fig_platform = px.pie(
        platform_df, names="platform_bucket", values="hours", title="Hours by platform"
    )
    sp_platform_plot = mo.ui.plotly(fig_platform)
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
    mo.vstack(
        [
            mo.md("### Longitudinal (filter-aware)"),
            mo.hstack([mo.ui.plotly(fig_monthly), mo.ui.plotly(fig_kind)], gap=1),
            mo.hstack([sp_platform_plot, mo.ui.plotly(fig_country)], gap=1),
            mo.ui.plotly(fig_skips),
        ],
        gap=1,
    )
    return (sp_platform_plot,)


@app.cell(hide_code=True)
def _(set_platform_override, sp_on, sp_platform_plot):
    sp_on
    if sp_platform_plot.value and sp_platform_plot.value.get("points"):
        _pt = sp_platform_plot.value["points"][0]
        _label = _pt.get("label")
        if _label:
            set_platform_override([_label])
    return


@app.cell(hide_code=True)
def _(
    artist_hours_vs_skip,
    bump_chart_artists,
    conn,
    kind_platform_sunburst,
    mo,
    px,
    sp_calendar_daily,
    sp_filters,
    sp_on,
    treemap_artist_album,
):
    sp_on
    treemap_df = treemap_artist_album(conn, sp_filters)
    calendar_df = sp_calendar_daily(conn, sp_filters)
    bump_df = bump_chart_artists(conn, sp_filters, top_n=10)
    sp_scatter_df = artist_hours_vs_skip(conn, sp_filters)
    sunburst_df = kind_platform_sunburst(conn, sp_filters)
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
            sp_scatter_df,
            x="hours",
            y="skip_pct",
            size="plays",
            hover_name="artist_name",
            title="Artist hours vs skip % (click to filter)",
        )
        if not sp_scatter_df.empty
        else px.scatter(title="No scatter data")
    )
    sp_scatter_plot = mo.ui.plotly(fig_scatter)
    fig_sun = (
        px.sunburst(
            sunburst_df, path=["kind", "platform_bucket"], values="hours", title="Kind → platform"
        )
        if not sunburst_df.empty
        else px.sunburst(title="No sunburst data")
    )
    mo.vstack(
        [
            mo.md("### Expanded views"),
            mo.hstack([mo.ui.plotly(fig_tree), mo.ui.plotly(fig_cal)], gap=1),
            mo.hstack([mo.ui.plotly(fig_bump), sp_scatter_plot], gap=1),
            mo.ui.plotly(fig_sun),
        ],
        gap=1,
    )
    return sp_scatter_df, sp_scatter_plot


@app.cell(hide_code=True)
def _(set_artist, sp_on, sp_scatter_df, sp_scatter_plot):
    sp_on
    if sp_scatter_plot.value and sp_scatter_plot.value.get("points") and not sp_scatter_df.empty:
        idx = sp_scatter_plot.value["points"][0].get("pointIndex", 0)
        set_artist(sp_scatter_df.iloc[idx]["artist_name"])
    return


@app.cell(hide_code=True)
def _(conn, decade_bars, genre_treemap, mb_ready, mo, px, sp_filters, sp_on):
    sp_on
    if mb_ready:
        genre_df = genre_treemap(conn, sp_filters)
        decade_df = decade_bars(conn, sp_filters)
        _mb = mo.vstack(
            [
                mo.md("### MusicBrainz enrichment"),
                mo.hstack(
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
                            px.bar(decade_df, x="decade", y="hours", title="Hours by release decade")
                            if not decade_df.empty
                            else px.bar(title="No decade data")
                        ),
                    ],
                    gap=1,
                ),
            ]
        )
    else:
        _mb = mo.md(
            "_Genre/decade charts need MusicBrainz enrichment. "
            "**Stop this notebook first**, then: `uv run enrich-musicbrainz` "
            "(defaults to the full library; `--artist-limit` / `--track-limit` "
            "are 0). See docs/WAREHOUSE.md. Restart the dashboard after enrichment._"
        )
    _mb
    return


@app.cell(hide_code=True)
def _(conn, mo, narrate, narrative_context, sp_filters, sp_narrate_btn, sp_on):
    sp_on
    narrative_out = mo.md("_Click **Narrate this view** to generate prose (aggregates only)._")
    if sp_narrate_btn.value:
        ctx = narrative_context(conn, sp_filters)
        text, cached = narrate(ctx)
        suffix = " _(cached)_" if cached else ""
        narrative_out = mo.md(f"### Narrative{suffix}\n\n{text}")
    narrative_out
    return


@app.cell(hide_code=True)
def _(mo, tg_bounds, tg_on):
    tg_on
    tg_year_start = mo.ui.slider(
        start=tg_bounds["min_year"],
        stop=tg_bounds["max_year"],
        value=tg_bounds["min_year"],
        label="From year",
        show_value=True,
    )
    tg_year_end = mo.ui.slider(
        start=tg_bounds["min_year"],
        stop=tg_bounds["max_year"],
        value=tg_bounds["max_year"],
        label="To year",
        show_value=True,
    )
    tg_chat_type = mo.ui.multiselect(
        options=tg_bounds["chat_types"], value=[], label="Chat type"
    )
    tg_event = mo.ui.multiselect(options=tg_bounds["event_types"], value=[], label="Event type")
    tg_media = mo.ui.multiselect(options=tg_bounds["media_kinds"], value=[], label="Media kind")
    tg_compare = mo.ui.checkbox(label="Compare vs previous equal window", value=False)
    tg_people_btn = mo.ui.run_button(label="People only")
    tg_clear_types = mo.ui.run_button(label="Clear types")
    tg_clear_chat = mo.ui.run_button(label="Clear chat lock")
    tg_clear_media = mo.ui.run_button(label="Clear media")
    get_chat_name, set_chat_name = mo.state(None)
    get_types_override, set_types_override = mo.state(None)
    get_media_override, set_media_override = mo.state(None)
    mo.vstack(
        [
            mo.md(
                f"## Telegram explorer\n"
                f"Data: {tg_bounds['first_day']} → {tg_bounds['last_day']} "
                f"({len(tg_bounds['chats'])} chats). Media files stay on disk; this view is counts only."
            ),
            mo.hstack([tg_year_start, tg_year_end], justify="start", gap=1),
            mo.hstack([tg_chat_type, tg_event, tg_media], justify="start", gap=1),
            mo.hstack(
                [tg_compare, tg_people_btn, tg_clear_types, tg_clear_chat, tg_clear_media],
                gap=1,
            ),
        ],
        gap=0.5,
    )
    return (
        get_chat_name,
        get_media_override,
        get_types_override,
        set_chat_name,
        set_media_override,
        set_types_override,
        tg_chat_type,
        tg_clear_chat,
        tg_clear_media,
        tg_clear_types,
        tg_compare,
        tg_event,
        tg_media,
        tg_people_btn,
        tg_year_end,
        tg_year_start,
    )


@app.cell(hide_code=True)
def _(
    PEOPLE_CHAT_TYPES,
    set_chat_name,
    set_media_override,
    set_types_override,
    tg_clear_chat,
    tg_clear_media,
    tg_clear_types,
    tg_on,
    tg_people_btn,
):
    tg_on
    if tg_people_btn.value:
        set_types_override(list(PEOPLE_CHAT_TYPES))
    if tg_clear_types.value:
        set_types_override([])
    if tg_clear_chat.value:
        set_chat_name(None)
    if tg_clear_media.value:
        set_media_override([])
    return


@app.cell(hide_code=True)
def _(
    get_chat_name,
    get_media_override,
    get_types_override,
    mo,
    set_media_override,
    set_types_override,
    tg_bounds,
    tg_chat_type,
    tg_event,
    tg_filter_from_widgets,
    tg_media,
    tg_on,
    tg_year_end,
    tg_year_start,
):
    tg_on
    chat_types = (
        get_types_override() if get_types_override() is not None else list(tg_chat_type.value)
    )
    media_kinds = (
        get_media_override() if get_media_override() is not None else list(tg_media.value)
    )
    if tg_chat_type.value and get_types_override() is not None:
        set_types_override(None)
    if tg_media.value and get_media_override() is not None:
        set_media_override(None)
    tg_filters = tg_filter_from_widgets(
        tg_bounds,
        year_start=tg_year_start.value,
        year_end=tg_year_end.value,
        chat_types=chat_types,
        event_types=list(tg_event.value),
        media_kinds=media_kinds,
        chat_name=get_chat_name(),
    )
    tg_chips = tg_filters.chip_labels()
    (
        mo.hstack([mo.md(f"**{label}**") for _, label in tg_chips], gap=0.5)
        if tg_chips
        else mo.md("_No extra filters active_")
    )
    return (tg_filters,)


@app.cell(hide_code=True)
def _(conn, mo, tg_compare, tg_filters, tg_on, tg_scoreboard, tg_streak_stats):
    tg_on
    tg_score_df = tg_scoreboard(conn, tg_filters, compare_previous=tg_compare.value)
    tg_streak_df = tg_streak_stats(conn, tg_filters)
    mo.vstack(
        [mo.md("### Scoreboard"), mo.ui.table(tg_score_df), mo.ui.table(tg_streak_df)],
        gap=0.5,
    )
    return


@app.cell(hide_code=True)
def _(conn, me_vs_them, mo, monthly_by_chat_type, px, tg_filters, tg_on):
    tg_on
    _monthly_df = monthly_by_chat_type(conn, tg_filters)
    _me_df = me_vs_them(conn, tg_filters)
    if _monthly_df.empty:
        fig_month = px.bar(title="No monthly data")
    else:
        fig_month = px.bar(
            _monthly_df,
            x="year_month",
            y="events",
            color="chat_type",
            barmode="stack",
            title="Events by month × chat type",
        )
        fig_month.update_layout(xaxis_title="Month", yaxis_title="Events")
    if _me_df.empty:
        fig_me = px.bar(title="No me/them data")
    else:
        me_long = _me_df.melt(
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
            title="Messages sent by you vs others",
        )
        fig_me.update_layout(xaxis_title="Year", yaxis_title="Messages")
    mo.vstack(
        [
            mo.md("### Longitudinal"),
            mo.hstack([mo.ui.plotly(fig_month), mo.ui.plotly(fig_me)], gap=1),
        ],
        gap=0.5,
    )
    return


@app.cell(hide_code=True)
def _(conn, messages_by_chat, mo, px, tg_filters, tg_on):
    tg_on
    chats_df = messages_by_chat(conn, tg_filters, limit=25)
    tg_chats_table = mo.ui.table(chats_df, selection="single")
    if chats_df.empty:
        tg_rank_plot = mo.ui.plotly(px.bar(title="No chats for this filter"))
    else:
        fig_rank = px.bar(
            chats_df.head(15),
            x="events",
            y="chat_name",
            orientation="h",
            title="Top chats by events",
        )
        fig_rank.update_layout(xaxis_title="Events", yaxis_title="Chat")
        tg_rank_plot = mo.ui.plotly(fig_rank)
    mo.vstack(
        [
            mo.md("### Chats — select a row or click the bar to filter"),
            mo.hstack([tg_chats_table, tg_rank_plot], gap=1),
        ],
        gap=0.5,
    )
    return tg_chats_table, tg_rank_plot


@app.cell(hide_code=True)
def _(set_chat_name, tg_chats_table, tg_on, tg_rank_plot):
    tg_on
    _selected = tg_chats_table.value
    if _selected is not None and len(_selected) == 1:
        set_chat_name(_selected.iloc[0]["chat_name"])
    if tg_rank_plot.value and tg_rank_plot.value.get("points"):
        _y = tg_rank_plot.value["points"][0].get("y")
        if _y:
            set_chat_name(_y)
    return


@app.cell(hide_code=True)
def _(chat_reply_scatter, comeback_chats, conn, forgotten_chats, mo, px, tg_filters, tg_on):
    tg_on
    _scatter_df = chat_reply_scatter(conn, tg_filters)
    _forgotten_df = forgotten_chats(conn, tg_filters)
    _comebacks_df = comeback_chats(conn, tg_filters)
    if _scatter_df.empty:
        tg_scatter_plot = mo.ui.plotly(px.scatter(title="No chat scatter"))
    else:
        fig_sc = px.scatter(
            _scatter_df,
            x="events",
            y="reply_pct",
            size="events",
            color="chat_type",
            hover_name="chat_name",
            title="Volume vs reply %",
        )
        fig_sc.update_layout(xaxis_title="Events", yaxis_title="Reply %")
        tg_scatter_plot = mo.ui.plotly(fig_sc)
    mo.vstack(
        [
            mo.md("### Relationships — click a point to lock that chat"),
            tg_scatter_plot,
            mo.hstack(
                [
                    mo.vstack(
                        [mo.md("**Forgotten** (≥50 events, silent >2y)"), mo.ui.table(_forgotten_df)]
                    ),
                    mo.vstack(
                        [
                            mo.md("**Comebacks** (return after ≥2y gap)"),
                            mo.ui.table(_comebacks_df),
                        ]
                    ),
                ],
                gap=1,
            ),
        ],
        gap=1,
    )
    return (tg_scatter_plot,)


@app.cell(hide_code=True)
def _(set_chat_name, tg_on, tg_scatter_plot):
    tg_on
    if tg_scatter_plot.value and tg_scatter_plot.value.get("points"):
        point = tg_scatter_plot.value["points"][0]
        name = point.get("hovertext") or point.get("customdata")
        if isinstance(name, list) and name:
            name = name[0]
        if name:
            set_chat_name(name)
    return


@app.cell(hide_code=True)
def _(
    bump_chart_chats,
    conn,
    mo,
    px,
    tg_calendar_daily,
    tg_circadian_heatmap,
    tg_dow,
    tg_filters,
    tg_on,
):
    tg_on
    _calendar_df = tg_calendar_daily(conn, tg_filters)
    _circadian_df = tg_circadian_heatmap(conn, tg_filters)
    _bump_df = bump_chart_chats(conn, tg_filters, top_n=8)
    if _calendar_df.empty:
        _fig_cal = px.density_heatmap(title="No calendar data")
    else:
        _cal = _calendar_df.copy()
        _cal["day"] = _cal["day"].astype("datetime64[ns]")
        _cal["week"] = _cal["day"].dt.isocalendar().week.astype(int)
        _cal["dow"] = _cal["day"].dt.dayofweek
        _fig_cal = px.density_heatmap(
            _cal,
            x="dow",
            y="week",
            z="events",
            title="Daily events (weekday × ISO week)",
            color_continuous_scale="Blues",
        )
        _fig_cal.update_layout(xaxis_title="Weekday (Mon=0)", yaxis_title="ISO week")
    if _circadian_df.empty:
        _fig_circ = px.density_heatmap(title="No circadian data")
    else:
        _circ = _circadian_df.copy()
        _circ["dow_label"] = _circ["dow"].map(tg_dow)
        _fig_circ = px.density_heatmap(
            _circ,
            x="hour",
            y="dow_label",
            z="events",
            title="Events by weekday × hour (Europe/Rome)",
            color_continuous_scale="Viridis",
        )
        _fig_circ.update_layout(xaxis_title="Hour", yaxis_title="Weekday")
    if _bump_df.empty:
        _fig_bump = px.line(title="No bump data")
    else:
        _fig_bump = px.line(
            _bump_df,
            x="year",
            y="rank",
            color="chat_name",
            markers=True,
            title="Top chat ranks by year",
        )
        _fig_bump.update_yaxes(autorange="reversed", title="Rank")
        _fig_bump.update_layout(xaxis_title="Year")
    mo.vstack(
        [
            mo.md("### Time"),
            mo.hstack([mo.ui.plotly(_fig_cal), mo.ui.plotly(_fig_circ)], gap=1),
            mo.ui.plotly(_fig_bump),
        ],
        gap=1,
    )
    return


@app.cell(hide_code=True)
def _(calls_by_year, conn, media_mix, mo, px, reaction_mix, tg_filters, tg_on):
    tg_on
    media_df = media_mix(conn, tg_filters, exclude_none=True)
    react_df = reaction_mix(conn, tg_filters)
    calls_df = calls_by_year(conn, tg_filters)
    fig_media = (
        px.pie(media_df, names="media_kind", values="events", title="Media mix (excluding none)")
        if not media_df.empty
        else px.pie(title="No media in this filter")
    )
    tg_media_plot = mo.ui.plotly(fig_media)
    fig_react = (
        px.bar(react_df, x="reactions", y="emoji", orientation="h", title="Reaction emoji")
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
    mo.vstack(
        [
            mo.md("### Media · reactions · calls"),
            mo.hstack(
                [tg_media_plot, mo.ui.plotly(fig_react), mo.ui.plotly(fig_calls)],
                gap=1,
            ),
        ],
        gap=0.5,
    )
    return (tg_media_plot,)


@app.cell(hide_code=True)
def _(set_media_override, tg_media_plot, tg_on):
    tg_on
    if tg_media_plot.value and tg_media_plot.value.get("points"):
        label = tg_media_plot.value["points"][0].get("label")
        if label:
            set_media_override([label])
    return


if __name__ == "__main__":
    app.run()
