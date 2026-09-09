import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import (
        make_linkedin_controls,
        make_miband_controls,
        make_sleep_controls,
        make_spotify_controls,
        make_telegram_controls,
        make_twitter_controls,
        render_linkedin_panel,
        render_miband_panel,
        render_sleep_panel,
        render_spotify_panel,
        render_telegram_panel,
        render_twitter_panel,
    )
    from data_dumps.llm_client import narrate
    from data_dumps.paths import warehouse_db
    from data_dumps.spotify_queries import (
        artist_hours_vs_skip,
        bump_chart_artists,
        comeback_artists,
        decade_bars,
        discovery_vs_repeats,
        forgotten_artists,
        genre_treemap,
        has_mb_data,
        hours_by_country,
        hours_by_kind,
        hours_by_platform,
        kind_platform_sunburst,
        monthly_hours,
        narrative_context,
        shuffle_intent,
        skip_trends,
        top_albums,
        top_artists,
        top_shows,
        top_tracks,
        treemap_artist_album,
    )
    from data_dumps.spotify_queries import (
        calendar_daily as sp_calendar_daily,
    )
    from data_dumps.spotify_queries import (
        circadian_heatmap as sp_circadian_heatmap,
    )
    from data_dumps.spotify_queries import (
        data_bounds as sp_data_bounds,
    )
    from data_dumps.spotify_queries import (
        filter_from_widgets as sp_filter_from_widgets,
    )
    from data_dumps.spotify_queries import (
        scoreboard as sp_scoreboard,
    )
    from data_dumps.spotify_queries import (
        streak_stats as sp_streak_stats,
    )
    from data_dumps.telegram_queries import (
        PEOPLE_CHAT_TYPES,
        bump_chart_chats,
        calls_by_year,
        chat_reply_scatter,
        comeback_chats,
        forgotten_chats,
        me_vs_them,
        media_mix,
        messages_by_chat,
        monthly_by_chat_type,
        reaction_mix,
    )
    from data_dumps.telegram_queries import (
        calendar_daily as tg_calendar_daily,
    )
    from data_dumps.telegram_queries import (
        circadian_heatmap as tg_circadian_heatmap,
    )
    from data_dumps.telegram_queries import (
        data_bounds as tg_data_bounds,
    )
    from data_dumps.telegram_queries import (
        filter_from_widgets as tg_filter_from_widgets,
    )
    from data_dumps.telegram_queries import (
        scoreboard as tg_scoreboard,
    )
    from data_dumps.telegram_queries import (
        streak_stats as tg_streak_stats,
    )
    from data_dumps.linkedin_queries import data_bounds as li_data_bounds
    from data_dumps.sleep_queries import data_bounds as sl_data_bounds
    from data_dumps.miband_queries import data_bounds as mb_hr_data_bounds
    from data_dumps.twitter_queries import (
        account_reply_scatter,
        bump_chart_accounts,
        calendar_daily as tw_calendar_daily,
        circadian_heatmap as tw_circadian_heatmap,
        client_mix,
        comeback_accounts,
        data_bounds as tw_data_bounds,
        discovery_vs_repeats as tw_discovery_vs_repeats,
        dm_volume,
        filter_from_widgets as tw_filter_from_widgets,
        forgotten_accounts,
        hashtag_account_treemap,
        has_table as tw_has_table,
        language_mix,
        likes_by_year,
        media_mix as tw_media_mix,
        monthly_by_type,
        monthly_volume,
        narrative_context as tw_narrative_context,
        network_snapshot,
        scoreboard as tw_scoreboard,
        streak_stats as tw_streak_stats,
        top_dm_conversations,
        top_hashtags,
        top_liked_accounts,
        top_mentions,
        top_replied_to,
        tweet_type_mix,
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
    has_linkedin = _has_table(conn, "linkedin", "connections")
    has_twitter = _has_table(conn, "twitter", "tweets")
    has_sleep = _has_table(conn, "sleep", "sessions")
    has_miband = _has_table(conn, "miband", "heart_rate")
    sp_bounds = sp_data_bounds(conn) if has_spotify else None
    tg_bounds = tg_data_bounds(conn) if has_telegram else None
    li_bounds = li_data_bounds(conn) if has_linkedin else None
    tw_bounds = tw_data_bounds(conn) if has_twitter else None
    sl_bounds = sl_data_bounds(conn) if has_sleep else None
    mb_hr_bounds = mb_hr_data_bounds(conn) if has_miband else None
    mb_ready = has_mb_data(conn) if has_spotify else False
    tg_dow = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    iso_dow = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
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
        has_linkedin,
        has_miband,
        has_sleep,
        has_spotify,
        has_telegram,
        has_twitter,
        hours_by_country,
        hours_by_kind,
        hours_by_platform,
        iso_dow,
        kind_platform_sunburst,
        li_bounds,
        make_linkedin_controls,
        make_miband_controls,
        make_sleep_controls,
        make_spotify_controls,
        make_telegram_controls,
        make_twitter_controls,
        mb_hr_bounds,
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
        render_linkedin_panel,
        render_miband_panel,
        render_sleep_panel,
        render_spotify_panel,
        render_telegram_panel,
        render_twitter_panel,
        shuffle_intent,
        skip_trends,
        sl_bounds,
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
        tw_bounds,
        tw_calendar_daily,
        tw_circadian_heatmap,
        tw_discovery_vs_repeats,
        tw_filter_from_widgets,
        tw_has_table,
        tw_media_mix,
        tw_narrative_context,
        tw_scoreboard,
        tw_streak_stats,
        account_reply_scatter,
        bump_chart_accounts,
        client_mix,
        comeback_accounts,
        dm_volume,
        forgotten_accounts,
        hashtag_account_treemap,
        language_mix,
        likes_by_year,
        monthly_by_type,
        monthly_volume,
        network_snapshot,
        top_dm_conversations,
        top_hashtags,
        top_liked_accounts,
        top_mentions,
        top_replied_to,
        tweet_type_mix,
    )


@app.cell(hide_code=True)
def _(
    has_linkedin,
    has_miband,
    has_sleep,
    has_spotify,
    has_telegram,
    has_twitter,
    li_bounds,
    mb_hr_bounds,
    mo,
    sl_bounds,
    sp_bounds,
    tg_bounds,
    tw_bounds,
):
    default_tab = (
        "Spotify"
        if has_spotify
        else "Telegram"
        if has_telegram
        else "Twitter"
        if has_twitter
        else "Sleep"
        if has_sleep
        else "Mi Band"
        if has_miband
        else "LinkedIn"
    )
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
    li_caption = (
        f"{li_bounds['first_day']} → {li_bounds['last_day']}"
        if li_bounds
        else "Not ingested"
    )
    tw_caption = (
        f"{tw_bounds['first_day']} → {tw_bounds['last_day']}"
        if tw_bounds
        else "Not ingested"
    )
    sl_caption = (
        f"{sl_bounds['first_day']} → {sl_bounds['last_day']}"
        if sl_bounds
        else "Not ingested"
    )
    mb_caption = (
        f"{mb_hr_bounds['first_day']} → {mb_hr_bounds['last_day']}"
        if mb_hr_bounds
        else "Not ingested"
    )
    source = mo.ui.tabs(
        {
            "Spotify": mo.md(f"_{sp_caption}_"),
            "Telegram": mo.md(f"_{tg_caption}_"),
            "LinkedIn": mo.md(f"_{li_caption}_"),
            "Twitter": mo.md(f"_{tw_caption}_"),
            "Sleep": mo.md(f"_{sl_caption}_"),
            "Mi Band": mo.md(f"_{mb_caption}_"),
        },
        value=default_tab,
    )
    mo.vstack([mo.md("# data dumps"), source], gap=0.5)
    return (source,)


@app.cell(hide_code=True)
def _(has_spotify, make_spotify_controls, mo, sp_bounds):
    # Always create controls (cheap). Do not display here — render cell owns the UI.
    sp_controls = make_spotify_controls(mo, sp_bounds) if has_spotify and sp_bounds else None
    return (sp_controls,)


@app.cell(hide_code=True)
def _(has_telegram, make_telegram_controls, mo, tg_bounds):
    tg_controls = make_telegram_controls(mo, tg_bounds) if has_telegram and tg_bounds else None
    return (tg_controls,)


@app.cell(hide_code=True)
def _(has_linkedin, li_bounds, make_linkedin_controls, mo):
    li_controls = (
        make_linkedin_controls(mo, li_bounds) if has_linkedin and li_bounds else None
    )
    return (li_controls,)


@app.cell(hide_code=True)
def _(has_twitter, make_twitter_controls, mo, tw_bounds):
    tw_controls = (
        make_twitter_controls(mo, tw_bounds) if has_twitter and tw_bounds else None
    )
    return (tw_controls,)


@app.cell(hide_code=True)
def _(has_sleep, make_sleep_controls, mo, sl_bounds):
    sl_controls = make_sleep_controls(mo, sl_bounds) if has_sleep and sl_bounds else None
    return (sl_controls,)


@app.cell(hide_code=True)
def _(has_miband, make_miband_controls, mb_hr_bounds, mo):
    mb_hr_controls = (
        make_miband_controls(mo, mb_hr_bounds) if has_miband and mb_hr_bounds else None
    )
    return (mb_hr_controls,)

@app.cell(hide_code=True)
def _(
    artist_hours_vs_skip,
    bump_chart_artists,
    comeback_artists,
    conn,
    decade_bars,
    discovery_vs_repeats,
    forgotten_artists,
    genre_treemap,
    has_spotify,
    hours_by_country,
    hours_by_kind,
    hours_by_platform,
    kind_platform_sunburst,
    mb_ready,
    mo,
    monthly_hours,
    narrate,
    narrative_context,
    px,
    render_spotify_panel,
    shuffle_intent,
    skip_trends,
    source,
    sp_bounds,
    sp_calendar_daily,
    sp_circadian_heatmap,
    sp_controls,
    sp_filter_from_widgets,
    sp_scoreboard,
    sp_streak_stats,
    top_albums,
    top_artists,
    top_shows,
    top_tracks,
    treemap_artist_album,
):
    # Leaf cell: mo.stop must not fan out to descendants.
    mo.stop(source.value != "Spotify", output=None)
    if not has_spotify or sp_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `spotify.plays` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/spotify/my_spotify_data.zip`"
            ),
        )
    render_spotify_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=sp_bounds,
        mb_ready=mb_ready,
        controls=sp_controls,
        filter_from_widgets=sp_filter_from_widgets,
        scoreboard=sp_scoreboard,
        streak_stats=sp_streak_stats,
        top_artists=top_artists,
        top_tracks=top_tracks,
        top_albums=top_albums,
        top_shows=top_shows,
        discovery_vs_repeats=discovery_vs_repeats,
        shuffle_intent=shuffle_intent,
        circadian_heatmap=sp_circadian_heatmap,
        forgotten_artists=forgotten_artists,
        comeback_artists=comeback_artists,
        monthly_hours=monthly_hours,
        hours_by_kind=hours_by_kind,
        hours_by_platform=hours_by_platform,
        hours_by_country=hours_by_country,
        skip_trends=skip_trends,
        treemap_artist_album=treemap_artist_album,
        calendar_daily=sp_calendar_daily,
        bump_chart_artists=bump_chart_artists,
        artist_hours_vs_skip=artist_hours_vs_skip,
        kind_platform_sunburst=kind_platform_sunburst,
        genre_treemap=genre_treemap,
        decade_bars=decade_bars,
        narrative_context=narrative_context,
        narrate=narrate,
    )


@app.cell(hide_code=True)
def _(
    PEOPLE_CHAT_TYPES,
    bump_chart_chats,
    calls_by_year,
    chat_reply_scatter,
    comeback_chats,
    conn,
    forgotten_chats,
    has_telegram,
    me_vs_them,
    media_mix,
    messages_by_chat,
    mo,
    monthly_by_chat_type,
    px,
    reaction_mix,
    render_telegram_panel,
    source,
    tg_bounds,
    tg_calendar_daily,
    tg_circadian_heatmap,
    tg_controls,
    tg_dow,
    tg_filter_from_widgets,
    tg_scoreboard,
    tg_streak_stats,
):
    mo.stop(source.value != "Telegram", output=None)
    if not has_telegram or tg_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `telegram.messages` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/telegram/Telegram_Export_2026-09-03`"
            ),
        )
    render_telegram_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=tg_bounds,
        people_chat_types=list(PEOPLE_CHAT_TYPES),
        dow_labels=tg_dow,
        controls=tg_controls,
        filter_from_widgets=tg_filter_from_widgets,
        scoreboard=tg_scoreboard,
        streak_stats=tg_streak_stats,
        monthly_by_chat_type=monthly_by_chat_type,
        me_vs_them=me_vs_them,
        messages_by_chat=messages_by_chat,
        chat_reply_scatter=chat_reply_scatter,
        forgotten_chats=forgotten_chats,
        comeback_chats=comeback_chats,
        calendar_daily=tg_calendar_daily,
        circadian_heatmap=tg_circadian_heatmap,
        bump_chart_chats=bump_chart_chats,
        media_mix=media_mix,
        reaction_mix=reaction_mix,
        calls_by_year=calls_by_year,
    )


@app.cell(hide_code=True)
def _(
    conn,
    has_linkedin,
    li_bounds,
    li_controls,
    mo,
    px,
    render_linkedin_panel,
    source,
    tg_dow,
):
    mo.stop(source.value != "LinkedIn", output=None)
    if not has_linkedin or li_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `linkedin.connections` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/linkedin/Complete_LinkedInDataExport_09-06-2026.zip.zip`"
            ),
        )
    render_linkedin_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=li_bounds,
        controls=li_controls,
        dow_labels=tg_dow,
    )


@app.cell(hide_code=True)
def _(
    account_reply_scatter,
    bump_chart_accounts,
    client_mix,
    comeback_accounts,
    conn,
    dm_volume,
    forgotten_accounts,
    hashtag_account_treemap,
    has_twitter,
    language_mix,
    likes_by_year,
    mo,
    monthly_by_type,
    monthly_volume,
    narrate,
    network_snapshot,
    px,
    render_twitter_panel,
    source,
    top_dm_conversations,
    top_hashtags,
    top_liked_accounts,
    top_mentions,
    top_replied_to,
    tweet_type_mix,
    tw_bounds,
    tw_calendar_daily,
    tw_circadian_heatmap,
    tw_controls,
    tw_discovery_vs_repeats,
    tw_filter_from_widgets,
    tw_has_table,
    tw_media_mix,
    tw_narrative_context,
    tw_scoreboard,
    tw_streak_stats,
    tg_dow,
):
    mo.stop(source.value != "Twitter", output=None)
    if not has_twitter or tw_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `twitter.tweets` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/twitter/twitter-archive-2023-07-20`"
            ),
        )
    render_twitter_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=tw_bounds,
        dow_labels=tg_dow,
        controls=tw_controls,
        filter_from_widgets=tw_filter_from_widgets,
        scoreboard=tw_scoreboard,
        streak_stats=tw_streak_stats,
        top_mentions=top_mentions,
        top_replied_to=top_replied_to,
        top_hashtags=top_hashtags,
        top_liked_accounts=top_liked_accounts,
        tweet_type_mix=tweet_type_mix,
        client_mix=client_mix,
        media_mix=tw_media_mix,
        discovery_vs_repeats=tw_discovery_vs_repeats,
        monthly_volume=monthly_volume,
        monthly_by_type=monthly_by_type,
        likes_by_year=likes_by_year,
        language_mix=language_mix,
        circadian_heatmap=tw_circadian_heatmap,
        calendar_daily=tw_calendar_daily,
        bump_chart_accounts=bump_chart_accounts,
        account_reply_scatter=account_reply_scatter,
        forgotten_accounts=forgotten_accounts,
        comeback_accounts=comeback_accounts,
        hashtag_account_treemap=hashtag_account_treemap,
        dm_volume=dm_volume,
        top_dm_conversations=top_dm_conversations,
        network_snapshot=network_snapshot,
        narrative_context=tw_narrative_context,
        narrate=narrate,
        has_table=tw_has_table,
    )


@app.cell(hide_code=True)
def _(
    conn,
    has_sleep,
    iso_dow,
    mo,
    px,
    render_sleep_panel,
    sl_bounds,
    sl_controls,
    source,
):
    mo.stop(source.value != "Sleep", output=None)
    if not has_sleep or sl_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `sleep.sessions` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/sleep_as_android/sleep-export.zip`"
            ),
        )
    render_sleep_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=sl_bounds,
        controls=sl_controls,
        dow_labels=iso_dow,
    )


@app.cell(hide_code=True)
def _(
    conn,
    has_miband,
    iso_dow,
    mb_hr_bounds,
    mb_hr_controls,
    mo,
    px,
    render_miband_panel,
    source,
):
    mo.stop(source.value != "Mi Band", output=None)
    if not has_miband or mb_hr_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `miband.heart_rate` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/miband_hr/heart_rate.csv`"
            ),
        )
    render_miband_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=mb_hr_bounds,
        controls=mb_hr_controls,
        dow_labels=iso_dow,
    )


if __name__ == "__main__":
    app.run()
