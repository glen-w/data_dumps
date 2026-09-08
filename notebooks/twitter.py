import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import make_twitter_controls, render_twitter_panel
    from data_dumps.llm_client import narrate
    from data_dumps.paths import warehouse_db
    from data_dumps.twitter_queries import (
        account_reply_scatter,
        bump_chart_accounts,
        calendar_daily,
        circadian_heatmap,
        client_mix,
        comeback_accounts,
        data_bounds,
        discovery_vs_repeats,
        dm_volume,
        filter_from_widgets,
        forgotten_accounts,
        hashtag_account_treemap,
        has_table,
        language_mix,
        likes_by_year,
        media_mix,
        monthly_by_type,
        monthly_volume,
        narrative_context,
        network_snapshot,
        scoreboard,
        streak_stats,
        top_dm_conversations,
        top_hashtags,
        top_liked_accounts,
        top_mentions,
        top_replied_to,
        tweet_type_mix,
    )

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run: "
            "uv run ingest ~/Documents/data_dumps_raw/twitter/twitter-archive-2023-07-20"
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    has_tw = conn.execute("""
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'twitter' AND table_name = 'tweets'
        """).fetchone()
    if has_tw is None or has_tw[0] == 0:
        raise FileNotFoundError(
            "twitter.tweets is missing. Stop the dashboard, then: "
            "uv run ingest ~/Documents/data_dumps_raw/twitter/twitter-archive-2023-07-20"
        )
    bounds = data_bounds(conn)
    dow_labels = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    return (
        account_reply_scatter,
        bounds,
        bump_chart_accounts,
        calendar_daily,
        circadian_heatmap,
        client_mix,
        comeback_accounts,
        conn,
        data_bounds,
        discovery_vs_repeats,
        dm_volume,
        dow_labels,
        filter_from_widgets,
        forgotten_accounts,
        hashtag_account_treemap,
        has_table,
        language_mix,
        likes_by_year,
        make_twitter_controls,
        media_mix,
        mo,
        monthly_by_type,
        monthly_volume,
        narrate,
        narrative_context,
        network_snapshot,
        px,
        render_twitter_panel,
        scoreboard,
        streak_stats,
        top_dm_conversations,
        top_hashtags,
        top_liked_accounts,
        top_mentions,
        top_replied_to,
        tweet_type_mix,
    )


@app.cell(hide_code=True)
def _(bounds, make_twitter_controls, mo):
    controls = make_twitter_controls(mo, bounds)
    return (controls,)


@app.cell(hide_code=True)
def _(
    account_reply_scatter,
    bounds,
    bump_chart_accounts,
    calendar_daily,
    circadian_heatmap,
    client_mix,
    comeback_accounts,
    conn,
    controls,
    discovery_vs_repeats,
    dm_volume,
    dow_labels,
    filter_from_widgets,
    forgotten_accounts,
    hashtag_account_treemap,
    has_table,
    language_mix,
    likes_by_year,
    media_mix,
    mo,
    monthly_by_type,
    monthly_volume,
    narrate,
    narrative_context,
    network_snapshot,
    px,
    render_twitter_panel,
    scoreboard,
    streak_stats,
    top_dm_conversations,
    top_hashtags,
    top_liked_accounts,
    top_mentions,
    top_replied_to,
    tweet_type_mix,
):
    render_twitter_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=bounds,
        dow_labels=dow_labels,
        controls=controls,
        filter_from_widgets=filter_from_widgets,
        scoreboard=scoreboard,
        streak_stats=streak_stats,
        top_mentions=top_mentions,
        top_replied_to=top_replied_to,
        top_hashtags=top_hashtags,
        top_liked_accounts=top_liked_accounts,
        tweet_type_mix=tweet_type_mix,
        client_mix=client_mix,
        media_mix=media_mix,
        discovery_vs_repeats=discovery_vs_repeats,
        monthly_volume=monthly_volume,
        monthly_by_type=monthly_by_type,
        likes_by_year=likes_by_year,
        language_mix=language_mix,
        circadian_heatmap=circadian_heatmap,
        calendar_daily=calendar_daily,
        bump_chart_accounts=bump_chart_accounts,
        account_reply_scatter=account_reply_scatter,
        forgotten_accounts=forgotten_accounts,
        comeback_accounts=comeback_accounts,
        hashtag_account_treemap=hashtag_account_treemap,
        dm_volume=dm_volume,
        top_dm_conversations=top_dm_conversations,
        network_snapshot=network_snapshot,
        narrative_context=narrative_context,
        narrate=narrate,
        has_table=has_table,
    )
    return


if __name__ == "__main__":
    app.run()
