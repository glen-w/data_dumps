import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.llm_client import narrate
    from data_dumps.paths import warehouse_db
    from data_dumps.spotify_queries import (
        FilterState,
        artist_hours_vs_skip,
        bump_chart_artists,
        calendar_daily,
        comeback_artists,
        circadian_heatmap,
        data_bounds,
        decade_bars,
        discovery_vs_repeats,
        forgotten_artists,
        filter_from_widgets,
        genre_treemap,
        has_mb_data,
        hours_by_country,
        hours_by_kind,
        hours_by_platform,
        kind_platform_sunburst,
        monthly_hours,
        narrative_context,
        scoreboard,
        shuffle_intent,
        skip_trends,
        streak_stats,
        top_albums,
        top_artists,
        top_shows,
        top_tracks,
        treemap_artist_album,
    )

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run: uv run ingest my_spotify_data.zip"
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    bounds = data_bounds(conn)
    mb_ready = has_mb_data(conn)
    return (
        artist_hours_vs_skip,
        bump_chart_artists,
        calendar_daily,
        comeback_artists,
        circadian_heatmap,
        conn,
        decade_bars,
        discovery_vs_repeats,
        forgotten_artists,
        filter_from_widgets,
        genre_treemap,
        has_mb_data,
        hours_by_country,
        hours_by_kind,
        hours_by_platform,
        kind_platform_sunburst,
        mo,
        monthly_hours,
        narrative_context,
        px,
        scoreboard,
        shuffle_intent,
        skip_trends,
        streak_stats,
        top_albums,
        top_artists,
        top_shows,
        top_tracks,
        treemap_artist_album,
        bounds,
        mb_ready,
        FilterState,
        narrate,
    )


@app.cell
def _(bounds, mo):
    year_start_slider = mo.ui.slider(
        start=bounds["min_year"],
        stop=bounds["max_year"],
        value=bounds["min_year"],
        label="From year",
        show_value=True,
    )
    year_end_slider = mo.ui.slider(
        start=bounds["min_year"],
        stop=bounds["max_year"],
        value=bounds["max_year"],
        label="To year",
        show_value=True,
    )
    kind_select = mo.ui.multiselect(
        options=bounds["kinds"],
        value=[],
        label="Kind",
    )
    platform_select = mo.ui.multiselect(
        options=bounds["platforms"],
        value=[],
        label="Platform",
    )
    country_select = mo.ui.multiselect(
        options=bounds["countries"],
        value=[],
        label="Country",
    )
    artist_search = mo.ui.text(label="Artist search", placeholder="substring…")
    compare_toggle = mo.ui.checkbox(label="Compare vs previous equal window", value=False)
    clear_entity_btn = mo.ui.run_button(label="Clear artist lock")
    clear_kinds_btn = mo.ui.run_button(label="× kinds")
    clear_platform_btn = mo.ui.run_button(label="× platform")
    clear_country_btn = mo.ui.run_button(label="× countries")
    clear_search_btn = mo.ui.run_button(label="× search")
    narrate_btn = mo.ui.run_button(label="Narrate this view")
    get_artist, set_artist = mo.state(None)
    get_kind_override, set_kind_override = mo.state(None)
    get_platform_override, set_platform_override = mo.state(None)
    get_country_override, set_country_override = mo.state(None)

    mo.md(
        f"# Spotify Wrapped explorer\n"
        f"Data: {bounds['first_day']} → {bounds['last_day']} "
        f"(2017 gap is export data, not life)"
    )
    mo.hstack(
        [year_start_slider, year_end_slider, kind_select, platform_select, country_select],
        justify="start",
        gap=1,
    )
    mo.hstack(
        [
            artist_search,
            compare_toggle,
            clear_entity_btn,
            clear_kinds_btn,
            clear_platform_btn,
            clear_country_btn,
            clear_search_btn,
            narrate_btn,
        ],
        gap=1,
    )
    return (
        artist_search,
        clear_country_btn,
        clear_entity_btn,
        clear_kinds_btn,
        clear_platform_btn,
        clear_search_btn,
        compare_toggle,
        country_select,
        get_artist,
        get_country_override,
        get_kind_override,
        get_platform_override,
        kind_select,
        narrate_btn,
        platform_select,
        set_artist,
        set_country_override,
        set_kind_override,
        set_platform_override,
        year_end_slider,
        year_start_slider,
    )


@app.cell
def _(
    artist_search,
    clear_country_btn,
    clear_entity_btn,
    clear_kinds_btn,
    clear_platform_btn,
    clear_search_btn,
    set_artist,
    set_country_override,
    set_kind_override,
    set_platform_override,
):
    if clear_entity_btn.value:
        set_artist(None)
    if clear_kinds_btn.value:
        set_kind_override([])
    if clear_platform_btn.value:
        set_platform_override([])
    if clear_country_btn.value:
        set_country_override([])
    if clear_search_btn.value:
        artist_search.value = ""
    return


@app.cell
def _(
    artist_search,
    bounds,
    country_select,
    filter_from_widgets,
    get_artist,
    get_country_override,
    get_kind_override,
    get_platform_override,
    kind_select,
    mo,
    platform_select,
    set_kind_override,
    set_platform_override,
    set_country_override,
    year_end_slider,
    year_start_slider,
):
    kinds = (
        get_kind_override()
        if get_kind_override() is not None
        else list(kind_select.value)
    )
    platforms = (
        get_platform_override()
        if get_platform_override() is not None
        else list(platform_select.value)
    )
    countries = (
        get_country_override()
        if get_country_override() is not None
        else list(country_select.value)
    )
    if kind_select.value and get_kind_override() is not None:
        set_kind_override(None)
    if platform_select.value and get_platform_override() is not None:
        set_platform_override(None)
    if country_select.value and get_country_override() is not None:
        set_country_override(None)

    filters = filter_from_widgets(
        bounds,
        year_start=year_start_slider.value,
        year_end=year_end_slider.value,
        kinds=kinds,
        platform_buckets=platforms,
        conn_countries=countries,
        artist_search=artist_search.value or None,
        artist_name=get_artist(),
    )
    chip_items = filters.chip_labels()
    if chip_items:
        _chip = mo.hstack([mo.md(f"**{label}**") for _, label in chip_items], gap=0.5)
    else:
        _chip = mo.md("_No extra filters active_")
    _chip
    return filters


@app.cell
def _(conn, filters, mo, top_artists):
    top_artists_df = top_artists(conn, filters, limit=20)
    mo.md("## Top artists — select a row to filter")
    top_artists_table = mo.ui.table(top_artists_df, selection="single")
    top_artists_table
    return top_artists_df, top_artists_table


@app.cell
def _(set_artist, top_artists_df, top_artists_table):
    if top_artists_table.value is not None and len(top_artists_table.value) > 0:
        set_artist(top_artists_df.iloc[top_artists_table.value[0]]["artist_name"])
    return


@app.cell
def _(conn, compare_toggle, filters, mo, scoreboard, streak_stats):
    score_df = scoreboard(conn, filters, compare_previous=compare_toggle.value)
    streak_df = streak_stats(conn, filters)
    mo.md("## Scoreboard")
    mo.ui.table(score_df)
    mo.ui.table(streak_df)
    return


@app.cell
def _(conn, filters, mo, px, top_albums, top_artists, top_shows, top_tracks):
    artists_df = top_artists(conn, filters, limit=15)
    tracks_df = top_tracks(conn, filters, limit=15)
    albums_df = top_albums(conn, filters, limit=15)
    shows_df = top_shows(conn, filters, limit=15)
    mo.md("## Rankings")
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
    )
    return


@app.cell
def _(
    conn,
    circadian_heatmap,
    discovery_vs_repeats,
    filters,
    mo,
    px,
    shuffle_intent,
):
    discovery_df = discovery_vs_repeats(conn, filters)
    shuffle_df = shuffle_intent(conn, filters)
    circadian_df = circadian_heatmap(conn, filters)

    mo.md("## Discovery vs repeats · Shuffle intent · Circadian")
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

    mo.hstack(
        [mo.ui.plotly(fig_disc), mo.ui.plotly(fig_shuffle), mo.ui.plotly(fig_circ)],
        gap=1,
    )
    return


@app.cell
def _(conn, comeback_artists, forgotten_artists, filters, mo):
    forgotten_df = forgotten_artists(conn, filters)
    comebacks_df = comeback_artists(conn, filters)
    mo.md("## Forgotten · Comebacks")
    mo.hstack(
        [
            mo.vstack([mo.md("**Forgotten** (≥20h, silent >2y)"), mo.ui.table(forgotten_df)]),
            mo.vstack([mo.md("**Comebacks** (return after ≥2y gap)"), mo.ui.table(comebacks_df)]),
        ],
        gap=1,
    )
    return


@app.cell
def _(
    conn,
    filters,
    hours_by_country,
    hours_by_kind,
    hours_by_platform,
    monthly_hours,
    mo,
    px,
    skip_trends,
):
    monthly_df = monthly_hours(conn, filters)
    kind_df = hours_by_kind(conn, filters)
    platform_df = hours_by_platform(conn, filters)
    country_df = hours_by_country(conn, filters)
    skips_df = skip_trends(conn, filters)

    mo.md("## Longitudinal (filter-aware)")
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
    platform_plot = mo.ui.plotly(fig_platform)
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
            mo.hstack([mo.ui.plotly(fig_monthly), mo.ui.plotly(fig_kind)], gap=1),
            mo.hstack([platform_plot, mo.ui.plotly(fig_country)], gap=1),
            mo.ui.plotly(fig_skips),
        ],
        gap=1,
    )
    return (platform_plot,)


@app.cell
def _(platform_plot, set_platform_override):
    if platform_plot.value and platform_plot.value.get("points"):
        point = platform_plot.value["points"][0]
        label = point.get("label")
        if label:
            set_platform_override([label])
    return


@app.cell
def _(
    artist_hours_vs_skip,
    bump_chart_artists,
    calendar_daily,
    conn,
    filters,
    kind_platform_sunburst,
    mo,
    px,
    treemap_artist_album,
):
    treemap_df = treemap_artist_album(conn, filters)
    calendar_df = calendar_daily(conn, filters)
    bump_df = bump_chart_artists(conn, filters, top_n=10)
    scatter_df = artist_hours_vs_skip(conn, filters)
    sunburst_df = kind_platform_sunburst(conn, filters)

    mo.md("## Expanded views")

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
    scatter_plot = mo.ui.plotly(fig_scatter)

    fig_sun = (
        px.sunburst(
            sunburst_df, path=["kind", "platform_bucket"], values="hours", title="Kind → platform"
        )
        if not sunburst_df.empty
        else px.sunburst(title="No sunburst data")
    )

    mo.vstack(
        [
            mo.hstack([mo.ui.plotly(fig_tree), mo.ui.plotly(fig_cal)], gap=1),
            mo.hstack([mo.ui.plotly(fig_bump), scatter_plot], gap=1),
            mo.ui.plotly(fig_sun),
        ],
        gap=1,
    )
    return scatter_df, scatter_plot


@app.cell
def _(scatter_df, scatter_plot, set_artist):
    if scatter_plot.value and scatter_plot.value.get("points") and not scatter_df.empty:
        idx = scatter_plot.value["points"][0].get("pointIndex", 0)
        set_artist(scatter_df.iloc[idx]["artist_name"])
    return


@app.cell
def _(conn, decade_bars, filters, genre_treemap, mb_ready, mo, px):
    if mb_ready:
        genre_df = genre_treemap(conn, filters)
        decade_df = decade_bars(conn, filters)
        _mb = mo.vstack(
            [
                mo.md("## MusicBrainz enrichment"),
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
            "(see docs/WAREHOUSE.md). Restart the dashboard after enrichment._"
        )
    _mb
    return


@app.cell
def _(conn, filters, mo, narrate, narrate_btn, narrative_context):
    narrative_out = mo.md("_Click **Narrate this view** to generate prose (aggregates only)._")
    if narrate_btn.value:
        ctx = narrative_context(conn, filters)
        text, cached = narrate(ctx)
        suffix = " _(cached)_" if cached else ""
        narrative_out = mo.md(f"## Narrative{suffix}\n\n{text}")
    narrative_out
    return


if __name__ == "__main__":
    app.run()
