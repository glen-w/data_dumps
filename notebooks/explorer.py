import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full", app_title="data_dumps")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import (
        make_amazon_controls,
        make_browser_controls,
        make_compare_controls,
        make_correlate_controls,
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
        render_correlate_panel,
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
    from data_dumps.compare_queries import compare_bounds as cmp_data_bounds
    from data_dumps.compare_queries import list_available_series as cmp_list_series
    from data_dumps.correlation_queries import correlate_bounds as corr_data_bounds
    from data_dumps.correlation_queries import list_available_metrics as corr_list_metrics
    from data_dumps.spotify_queries import has_mb_data
    from data_dumps.contributions import (
        COMPARE_TAB_ICON,
        COMPARE_TAB_LABEL,
        CORRELATE_TAB_ICON,
        CORRELATE_TAB_LABEL,
        explorer_contributions,
    )
    from data_dumps.query_util import has_table as _qu_has_table

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run ingest, then reopen this notebook."
        )
    conn = duckdb.connect(str(db_path), read_only=True)

    def _tab_label(icon: str, label: str) -> str:
        return f"{mo.icon(icon, size=16)} {label}"

    tab_compare = _tab_label(COMPARE_TAB_ICON, COMPARE_TAB_LABEL)
    tab_correlate = _tab_label(CORRELATE_TAB_ICON, CORRELATE_TAB_LABEL)

    # Presence + bounds driven by CONTRIBUTIONS (thin registry).
    _by_slug: dict = {}
    for _c in explorer_contributions():
        assert _c.gate_table is not None
        assert _c.tab_label is not None and _c.tab_icon is not None
        _schema, _table = _c.gate_table
        _present = _qu_has_table(conn, _schema, _table)
        _bounds = (
            _c.data_bounds(conn) if _present and _c.data_bounds is not None else None
        )
        _by_slug[_c.slug] = {
            "present": _present,
            "bounds": _bounds,
            "tab_label": _tab_label(_c.tab_icon, _c.tab_label),
        }

    has_spotify = _by_slug["spotify"]["present"]
    has_telegram = _by_slug["telegram"]["present"]
    has_linkedin = _by_slug["linkedin"]["present"]
    has_twitter = _by_slug["twitter"]["present"]
    has_sleep = _by_slug["sleep"]["present"]
    has_miband = _by_slug["miband"]["present"]
    has_ring = _by_slug["ring"]["present"]
    has_slack = _by_slug["slack"]["present"]
    has_browser = _by_slug["browser"]["present"]
    has_thunderbird = _by_slug["thunderbird"]["present"]
    has_amazon = _by_slug["amazon"]["present"]
    sp_bounds = _by_slug["spotify"]["bounds"]
    tg_bounds = _by_slug["telegram"]["bounds"]
    li_bounds = _by_slug["linkedin"]["bounds"]
    tw_bounds = _by_slug["twitter"]["bounds"]
    sl_bounds = _by_slug["sleep"]["bounds"]
    mb_hr_bounds = _by_slug["miband"]["bounds"]
    ring_bounds = _by_slug["ring"]["bounds"]
    sk_bounds = _by_slug["slack"]["bounds"]
    br_bounds = _by_slug["browser"]["bounds"]
    tb_bounds = _by_slug["thunderbird"]["bounds"]
    amz_bounds = _by_slug["amazon"]["bounds"]
    cmp_bounds = cmp_data_bounds(conn)
    cmp_series = cmp_list_series(conn)
    has_compare = len(cmp_series) > 0
    corr_bounds = corr_data_bounds(conn)
    corr_metrics = corr_list_metrics(conn)
    has_correlate = len(corr_metrics) >= 2
    mb_ready = has_mb_data(conn) if has_spotify else False
    tg_dow = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    iso_dow = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
    explorer_by_slug = _by_slug
    return (
        amz_bounds,
        br_bounds,
        cmp_bounds,
        cmp_series,
        conn,
        corr_bounds,
        corr_metrics,
        explorer_by_slug,
        has_amazon,
        has_browser,
        has_compare,
        has_correlate,
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
        make_correlate_controls,
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
        render_correlate_panel,
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
        tab_compare,
        tab_correlate,
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
    corr_bounds,
    explorer_by_slug,
    has_amazon,
    has_browser,
    has_compare,
    has_correlate,
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
    tab_compare,
    tab_correlate,
    tb_bounds,
    tg_bounds,
    tw_bounds,
):
    default_tab = (
        explorer_by_slug["spotify"]["tab_label"]
        if has_spotify
        else explorer_by_slug["telegram"]["tab_label"]
        if has_telegram
        else explorer_by_slug["twitter"]["tab_label"]
        if has_twitter
        else explorer_by_slug["slack"]["tab_label"]
        if has_slack
        else explorer_by_slug["browser"]["tab_label"]
        if has_browser
        else explorer_by_slug["sleep"]["tab_label"]
        if has_sleep
        else explorer_by_slug["miband"]["tab_label"]
        if has_miband
        else explorer_by_slug["ring"]["tab_label"]
        if has_ring
        else explorer_by_slug["thunderbird"]["tab_label"]
        if has_thunderbird
        else explorer_by_slug["amazon"]["tab_label"]
        if has_amazon
        else explorer_by_slug["linkedin"]["tab_label"]
        if has_linkedin
        else tab_compare
        if has_compare
        else tab_correlate
    )

    def _span_caption(bounds):
        if not bounds:
            return "Not ingested"
        if bounds.get("first_day") is not None and bounds.get("last_day") is not None:
            return f"{bounds['first_day']} → {bounds['last_day']}"
        return f"{bounds['min_year']} → {bounds['max_year']}"

    captions = {
        "spotify": _span_caption(sp_bounds),
        "telegram": (
            f"{tg_bounds['first_day']} → {tg_bounds['last_day']} · {len(tg_bounds['chats'])} chats"
            if tg_bounds
            else "Not ingested"
        ),
        "linkedin": _span_caption(li_bounds),
        "twitter": _span_caption(tw_bounds),
        "sleep": _span_caption(sl_bounds),
        "miband": _span_caption(mb_hr_bounds),
        "ring": _span_caption(ring_bounds),
        "slack": (
            f"{sk_bounds['first_day']} → {sk_bounds['last_day']} · "
            f"{len(sk_bounds['channels'])} channels"
            if sk_bounds
            else "Not ingested"
        ),
        "browser": _span_caption(br_bounds),
        "thunderbird": _span_caption(tb_bounds),
        "amazon": (
            f"{amz_bounds['first_day']} → {amz_bounds['last_day']}"
            if amz_bounds and amz_bounds.get("first_day")
            else (
                f"{amz_bounds['min_year']} → {amz_bounds['max_year']}"
                if amz_bounds
                else "Not ingested"
            )
        ),
    }
    cmp_caption = (
        f"{cmp_bounds['n_series']} series · "
        f"{cmp_bounds['min_year']} → {cmp_bounds['max_year']}"
        if has_compare and cmp_bounds
        else "No sources"
    )
    corr_caption = (
        f"{corr_bounds['n_metrics']} metrics · "
        f"{corr_bounds['min_year']} → {corr_bounds['max_year']}"
        if has_correlate and corr_bounds
        else "Need ≥2 sources"
    )
    # Cross-cutting tabs first; platform tabs from CONTRIBUTIONS order.
    tab_items = {
        tab_correlate: mo.md(f"_{corr_caption}_"),
        tab_compare: mo.md(f"_{cmp_caption}_"),
    }
    for slug, meta in explorer_by_slug.items():
        label = meta["tab_label"]
        tab_items[label] = mo.md(f"_{captions.get(slug, 'Not ingested')}_")
    source = mo.ui.tabs(tab_items, value=default_tab)
    from pathlib import Path

    logo = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
    header = mo.hstack(
        [
            mo.image(src=logo, alt="data_dumps", width=48, height=48),
            mo.md("# data_dumps"),
        ],
        justify="start",
        align="center",
        gap=0.75,
    )
    mo.vstack([header, source], gap=0.5)
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
    corr_bounds,
    corr_metrics,
    has_correlate,
    make_correlate_controls,
    mo,
):
    corr_controls = (
        make_correlate_controls(mo, corr_bounds, corr_metrics)
        if has_correlate and corr_bounds
        else None
    )
    return (corr_controls,)


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
    tab_compare,
):
    mo.stop(source.value != tab_compare, output=None)
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
    corr_bounds,
    corr_controls,
    has_correlate,
    mo,
    px,
    render_correlate_panel,
    source,
    tab_correlate,
):
    mo.stop(source.value != tab_correlate, output=None)
    if not has_correlate or corr_controls is None:
        mo.stop(
            True,
            mo.md(
                "Need at least two sources with activity series. Ingest more dumps, then reopen."
            ),
        )
    render_correlate_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=corr_bounds,
        controls=corr_controls,
    )


@app.cell(hide_code=True)
def _(
    conn,
    explorer_by_slug,
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
    mo.stop(source.value != explorer_by_slug["spotify"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_telegram,
    mo,
    px,
    render_telegram_panel,
    source,
    tg_bounds,
    tg_controls,
    tg_dow,
):
    mo.stop(source.value != explorer_by_slug["telegram"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_linkedin,
    li_bounds,
    li_controls,
    mo,
    px,
    render_linkedin_panel,
    source,
    tg_dow,
):
    mo.stop(source.value != explorer_by_slug["linkedin"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_amazon,
    iso_dow,
    mo,
    px,
    render_amazon_panel,
    source,
):
    mo.stop(source.value != explorer_by_slug["amazon"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_twitter,
    mo,
    px,
    render_twitter_panel,
    source,
    tg_dow,
    tw_bounds,
    tw_controls,
):
    mo.stop(source.value != explorer_by_slug["twitter"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_sleep,
    iso_dow,
    mo,
    px,
    render_sleep_panel,
    sl_bounds,
    sl_controls,
    source,
):
    mo.stop(source.value != explorer_by_slug["sleep"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_miband,
    iso_dow,
    mb_hr_bounds,
    mb_hr_controls,
    mo,
    px,
    render_miband_panel,
    source,
):
    mo.stop(source.value != explorer_by_slug["miband"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_ring,
    iso_dow,
    mo,
    px,
    render_ring_panel,
    ring_bounds,
    ring_controls,
    source,
):
    mo.stop(source.value != explorer_by_slug["ring"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_slack,
    iso_dow,
    mo,
    px,
    render_slack_panel,
    sk_bounds,
    sk_controls,
    source,
):
    mo.stop(source.value != explorer_by_slug["slack"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_browser,
    mo,
    px,
    render_browser_panel,
    source,
):
    mo.stop(source.value != explorer_by_slug["browser"]["tab_label"], output=None)
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
    explorer_by_slug,
    has_thunderbird,
    iso_dow,
    mo,
    px,
    render_thunderbird_panel,
    source,
    tb_bounds,
    tb_controls,
):
    mo.stop(source.value != explorer_by_slug["thunderbird"]["tab_label"], output=None)
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
