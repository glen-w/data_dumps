import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import (
        make_amazon_controls,
        make_browser_controls,
        make_compare_controls,
        make_linkedin_controls,
        make_miband_controls,
        make_ring_controls,
        make_slack_controls,
        make_sleep_controls,
        make_spotify_controls,
        make_telegram_controls,
        make_thunderbird_controls,
        make_twitter_controls,
        render_amazon_panel,
        render_browser_panel,
        render_compare_panel,
        render_linkedin_panel,
        render_miband_panel,
        render_ring_panel,
        render_slack_panel,
        render_sleep_panel,
        render_spotify_panel,
        render_telegram_panel,
        render_thunderbird_panel,
        render_twitter_panel,
    )
    from data_dumps.paths import warehouse_db
    from data_dumps.amazon_queries import data_bounds as amz_data_bounds
    from data_dumps.browser_queries import data_bounds as br_data_bounds
    from data_dumps.compare_queries import compare_bounds as cmp_data_bounds
    from data_dumps.compare_queries import list_available_series as cmp_list_series
    from data_dumps.linkedin_queries import data_bounds as li_data_bounds
    from data_dumps.miband_queries import data_bounds as mb_hr_data_bounds
    from data_dumps.ring_queries import data_bounds as ring_data_bounds
    from data_dumps.slack_queries import data_bounds as sk_data_bounds
    from data_dumps.sleep_queries import data_bounds as sl_data_bounds
    from data_dumps.spotify_queries import data_bounds as sp_data_bounds
    from data_dumps.spotify_queries import has_mb_data
    from data_dumps.telegram_queries import data_bounds as tg_data_bounds
    from data_dumps.thunderbird_queries import data_bounds as tb_data_bounds
    from data_dumps.twitter_queries import data_bounds as tw_data_bounds

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
    has_ring = _has_table(conn, "ring", "device_events")
    has_slack = _has_table(conn, "slack", "messages")
    has_browser = _has_table(conn, "browser", "pages")
    has_thunderbird = _has_table(conn, "thunderbird", "messages")
    has_amazon = _has_table(conn, "amazon", "order_items")
    sp_bounds = sp_data_bounds(conn) if has_spotify else None
    tg_bounds = tg_data_bounds(conn) if has_telegram else None
    li_bounds = li_data_bounds(conn) if has_linkedin else None
    tw_bounds = tw_data_bounds(conn) if has_twitter else None
    sl_bounds = sl_data_bounds(conn) if has_sleep else None
    mb_hr_bounds = mb_hr_data_bounds(conn) if has_miband else None
    ring_bounds = ring_data_bounds(conn) if has_ring else None
    sk_bounds = sk_data_bounds(conn) if has_slack else None
    br_bounds = br_data_bounds(conn) if has_browser else None
    tb_bounds = tb_data_bounds(conn) if has_thunderbird else None
    amz_bounds = amz_data_bounds(conn) if has_amazon else None
    cmp_bounds = cmp_data_bounds(conn)
    cmp_series = cmp_list_series(conn)
    has_compare = len(cmp_series) > 0
    mb_ready = has_mb_data(conn) if has_spotify else False
    tg_dow = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    iso_dow = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
    return (
        amz_bounds,
        br_bounds,
        cmp_bounds,
        cmp_series,
        conn,
        has_amazon,
        has_browser,
        has_compare,
        has_linkedin,
        has_miband,
        has_ring,
        has_slack,
        has_sleep,
        has_spotify,
        has_telegram,
        has_thunderbird,
        has_twitter,
        iso_dow,
        li_bounds,
        make_amazon_controls,
        make_browser_controls,
        make_compare_controls,
        make_linkedin_controls,
        make_miband_controls,
        make_ring_controls,
        make_slack_controls,
        make_sleep_controls,
        make_spotify_controls,
        make_telegram_controls,
        make_thunderbird_controls,
        make_twitter_controls,
        mb_hr_bounds,
        mb_ready,
        mo,
        px,
        render_amazon_panel,
        render_browser_panel,
        render_compare_panel,
        render_linkedin_panel,
        render_miband_panel,
        render_ring_panel,
        render_slack_panel,
        render_sleep_panel,
        render_spotify_panel,
        render_telegram_panel,
        render_thunderbird_panel,
        render_twitter_panel,
        ring_bounds,
        sk_bounds,
        sl_bounds,
        sp_bounds,
        tb_bounds,
        tg_bounds,
        tg_dow,
        tw_bounds,
    )


@app.cell(hide_code=True)
def _(
    amz_bounds,
    br_bounds,
    cmp_bounds,
    has_amazon,
    has_browser,
    has_compare,
    has_linkedin,
    has_miband,
    has_ring,
    has_slack,
    has_sleep,
    has_spotify,
    has_telegram,
    has_thunderbird,
    has_twitter,
    li_bounds,
    mb_hr_bounds,
    mo,
    ring_bounds,
    sk_bounds,
    sl_bounds,
    sp_bounds,
    tb_bounds,
    tg_bounds,
    tw_bounds,
):
    default_tab = (
        "🎵 Spotify"
        if has_spotify
        else "✈️ Telegram"
        if has_telegram
        else "🐦 Twitter"
        if has_twitter
        else "💬 Slack"
        if has_slack
        else "🌐 Browser"
        if has_browser
        else "😴 Sleep"
        if has_sleep
        else "⌚ Mi Band"
        if has_miband
        else "🔔 Ring"
        if has_ring
        else "📧 Thunderbird"
        if has_thunderbird
        else "📦 Amazon"
        if has_amazon
        else "💼 LinkedIn"
        if has_linkedin
        else "📊 Compare"
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
    ring_caption = (
        f"{ring_bounds['first_day']} → {ring_bounds['last_day']}"
        if ring_bounds
        else "Not ingested"
    )
    sk_caption = (
        f"{sk_bounds['first_day']} → {sk_bounds['last_day']} · "
        f"{len(sk_bounds['channels'])} channels"
        if sk_bounds
        else "Not ingested"
    )
    br_caption = (
        f"{br_bounds['first_day']} → {br_bounds['last_day']}"
        if br_bounds
        else "Not ingested"
    )
    tb_caption = (
        f"{tb_bounds['first_day']} → {tb_bounds['last_day']}"
        if tb_bounds
        else "Not ingested"
    )
    amz_caption = (
        f"{amz_bounds['first_day']} → {amz_bounds['last_day']}"
        if amz_bounds and amz_bounds.get("first_day")
        else (
            f"{amz_bounds['min_year']} → {amz_bounds['max_year']}"
            if amz_bounds
            else "Not ingested"
        )
    )
    cmp_caption = (
        f"{cmp_bounds['n_series']} series · "
        f"{cmp_bounds['min_year']} → {cmp_bounds['max_year']}"
        if has_compare and cmp_bounds
        else "No sources"
    )
    source = mo.ui.tabs(
        {
            "📊 Compare": mo.md(f"_{cmp_caption}_"),
            "📦 Amazon": mo.md(f"_{amz_caption}_"),
            "🌐 Browser": mo.md(f"_{br_caption}_"),
            "📧 Thunderbird": mo.md(f"_{tb_caption}_"),
            "💼 LinkedIn": mo.md(f"_{li_caption}_"),
            "⌚ Mi Band": mo.md(f"_{mb_caption}_"),
            "🔔 Ring": mo.md(f"_{ring_caption}_"),
            "💬 Slack": mo.md(f"_{sk_caption}_"),
            "😴 Sleep": mo.md(f"_{sl_caption}_"),
            "🎵 Spotify": mo.md(f"_{sp_caption}_"),
            "✈️ Telegram": mo.md(f"_{tg_caption}_"),
            "🐦 Twitter": mo.md(f"_{tw_caption}_"),
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
def _(amz_bounds, has_amazon, make_amazon_controls, mo):
    amz_controls = (
        make_amazon_controls(mo, amz_bounds) if has_amazon and amz_bounds else None
    )
    return (amz_controls,)


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
def _(has_ring, make_ring_controls, mo, ring_bounds):
    ring_controls = (
        make_ring_controls(mo, ring_bounds) if has_ring and ring_bounds else None
    )
    return (ring_controls,)


@app.cell(hide_code=True)
def _(has_slack, make_slack_controls, mo, sk_bounds):
    sk_controls = make_slack_controls(mo, sk_bounds) if has_slack and sk_bounds else None
    return (sk_controls,)


@app.cell(hide_code=True)
def _(br_bounds, has_browser, make_browser_controls, mo):
    br_controls = (
        make_browser_controls(mo, br_bounds) if has_browser and br_bounds else None
    )
    return (br_controls,)


@app.cell(hide_code=True)
def _(has_thunderbird, make_thunderbird_controls, mo, tb_bounds):
    tb_controls = (
        make_thunderbird_controls(mo, tb_bounds)
        if has_thunderbird and tb_bounds
        else None
    )
    return (tb_controls,)


@app.cell(hide_code=True)
def _(
    cmp_bounds,
    cmp_series,
    conn,
    has_compare,
    make_compare_controls,
    mo,
):
    cmp_controls = (
        make_compare_controls(mo, cmp_bounds, cmp_series, conn=conn)
        if has_compare and cmp_bounds
        else None
    )
    return (cmp_controls,)


@app.cell(hide_code=True)
def _(
    cmp_bounds,
    cmp_controls,
    conn,
    has_compare,
    mo,
    px,
    render_compare_panel,
    source,
):
    mo.stop(source.value != "📊 Compare", output=None)
    if not has_compare or cmp_controls is None:
        mo.stop(
            True,
            mo.md(
                "No comparable sources in the warehouse yet. Ingest a dump, then reopen."
            ),
        )
    render_compare_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=cmp_bounds,
        controls=cmp_controls,
    )


@app.cell(hide_code=True)
def _(
    conn,
    has_spotify,
    mb_ready,
    mo,
    px,
    render_spotify_panel,
    source,
    sp_bounds,
    sp_controls,
):
    # Leaf cell: mo.stop must not fan out to descendants.
    mo.stop(source.value != "🎵 Spotify", output=None)
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
    )




@app.cell(hide_code=True)
def _(
    conn,
    has_telegram,
    mo,
    px,
    render_telegram_panel,
    source,
    tg_bounds,
    tg_controls,
    tg_dow,
):
    mo.stop(source.value != "✈️ Telegram", output=None)
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
        dow_labels=tg_dow,
        controls=tg_controls,
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
    mo.stop(source.value != "💼 LinkedIn", output=None)
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
    amz_bounds,
    amz_controls,
    conn,
    has_amazon,
    iso_dow,
    mo,
    px,
    render_amazon_panel,
    source,
):
    mo.stop(source.value != "📦 Amazon", output=None)
    if not has_amazon or amz_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `amazon.order_items` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/amazon`"
            ),
        )
    render_amazon_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=amz_bounds,
        controls=amz_controls,
        dow_labels=iso_dow,
    )


@app.cell(hide_code=True)
def _(
    conn,
    has_twitter,
    mo,
    px,
    render_twitter_panel,
    source,
    tg_dow,
    tw_bounds,
    tw_controls,
):
    mo.stop(source.value != "🐦 Twitter", output=None)
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
    mo.stop(source.value != "😴 Sleep", output=None)
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
    mo.stop(source.value != "⌚ Mi Band", output=None)
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


@app.cell(hide_code=True)
def _(
    conn,
    has_ring,
    iso_dow,
    mo,
    px,
    render_ring_panel,
    ring_bounds,
    ring_controls,
    source,
):
    mo.stop(source.value != "🔔 Ring", output=None)
    if not has_ring or ring_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `ring.device_events` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/ring/All\\ Data\\ Categories.zip`"
            ),
        )
    render_ring_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=ring_bounds,
        controls=ring_controls,
        dow_labels=iso_dow,
    )


@app.cell(hide_code=True)
def _(
    conn,
    has_slack,
    iso_dow,
    mo,
    px,
    render_slack_panel,
    sk_bounds,
    sk_controls,
    source,
):
    mo.stop(source.value != "💬 Slack", output=None)
    if not has_slack or sk_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `slack.messages` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/slack/<workspace export>.zip`"
            ),
        )
    render_slack_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=sk_bounds,
        controls=sk_controls,
        dow_labels=iso_dow,
    )


@app.cell(hide_code=True)
def _(
    br_bounds,
    br_controls,
    conn,
    has_browser,
    mo,
    px,
    render_browser_panel,
    source,
):
    mo.stop(source.value != "🌐 Browser", output=None)
    if not has_browser or br_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `browser.pages` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/firefox/`"
            ),
        )
    render_browser_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=br_bounds,
        controls=br_controls,
    )



@app.cell(hide_code=True)
def _(
    conn,
    has_thunderbird,
    iso_dow,
    mo,
    px,
    render_thunderbird_panel,
    source,
    tb_bounds,
    tb_controls,
):
    mo.stop(source.value != "📧 Thunderbird", output=None)
    if not has_thunderbird or tb_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `thunderbird.messages` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Library/Thunderbird/Profiles/<id>.default-release`\n\n"
                "Optional: `--identity you@example.com` or `DATA_DUMPS_TB_IDENTITIES`."
            ),
        )
    render_thunderbird_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=tb_bounds,
        controls=tb_controls,
        dow_labels=iso_dow,
    )


if __name__ == "__main__":
    app.run()
