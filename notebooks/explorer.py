import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full", app_title="data_dumps")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import (
        make_airbnb_controls,
        make_amazon_controls,
        make_browser_controls,
        make_chatgpt_controls,
        make_compare_controls,
        make_correlate_controls,
        make_custom_controls,
        make_duolingo_controls,
        make_google_controls,
        make_linkedin_controls,
        make_miband_controls,
        make_ring_controls,
        make_slack_controls,
        make_sleep_controls,
        make_spotify_controls,
        make_telegram_controls,
        make_thunderbird_controls,
        make_twitter_controls,
        make_uber_controls,
        render_airbnb_panel,
        render_amazon_panel,
        render_browser_panel,
        render_chatgpt_panel,
        render_compare_panel,
        render_correlate_panel,
        render_custom_panel,
        render_duolingo_panel,
        render_google_panel,
        render_home_hero,
        render_home_panel,
        render_linkedin_panel,
        render_miband_panel,
        render_ring_panel,
        render_slack_panel,
        render_sleep_panel,
        render_spotify_panel,
        render_telegram_panel,
        render_thunderbird_panel,
        render_tools_panel,
        render_twitter_panel,
        render_uber_panel,
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
        HOME_TAB_ICON,
        HOME_TAB_LABEL,
        TOOLS_TAB_ICON,
        TOOLS_TAB_LABEL,
        explorer_contributions,
    )
    from data_dumps.overview_queries import warehouse_overview
    from data_dumps.query_util import has_table as _qu_has_table

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run ingest, then reopen this notebook."
        )
    conn = duckdb.connect(str(db_path), read_only=True)

    def _tab_label(icon: str, label: str) -> str:
        return f"{mo.icon(icon, size=16)} {label}"

    tab_home = _tab_label(HOME_TAB_ICON, HOME_TAB_LABEL)
    tab_compare = _tab_label(COMPARE_TAB_ICON, COMPARE_TAB_LABEL)
    tab_correlate = _tab_label(CORRELATE_TAB_ICON, CORRELATE_TAB_LABEL)
    tab_tools = _tab_label(TOOLS_TAB_ICON, TOOLS_TAB_LABEL)

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
            "name": _c.tab_label,
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
    has_duolingo = _by_slug["duolingo"]["present"]
    has_uber = _by_slug["uber"]["present"]
    has_google = _by_slug["google"]["present"]
    has_airbnb = _by_slug["airbnb"]["present"]
    has_chatgpt = _by_slug["chatgpt"]["present"]
    has_custom = _by_slug["custom"]["present"]
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
    duo_bounds = _by_slug["duolingo"]["bounds"]
    uber_bounds = _by_slug["uber"]["bounds"]
    google_bounds = _by_slug["google"]["bounds"]
    airbnb_bounds = _by_slug["airbnb"]["bounds"]
    chatgpt_bounds = _by_slug["chatgpt"]["bounds"]
    custom_bounds = _by_slug["custom"]["bounds"]
    cmp_bounds = cmp_data_bounds(conn)
    cmp_series = cmp_list_series(conn)
    has_compare = len(cmp_series) > 0
    corr_bounds = corr_data_bounds(conn)
    corr_metrics = corr_list_metrics(conn)
    has_correlate = len(corr_metrics) >= 2
    mb_ready = has_mb_data(conn) if has_spotify else False
    overview = warehouse_overview(
        conn,
        bounds_by_slug={slug: meta["bounds"] for slug, meta in _by_slug.items()},
    )
    tg_dow = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    iso_dow = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
    explorer_by_slug = _by_slug
    return (
        airbnb_bounds,
        amz_bounds,
        br_bounds,
        chatgpt_bounds,
        custom_bounds,
        cmp_bounds,
        cmp_series,
        conn,
        corr_bounds,
        corr_metrics,
        duo_bounds,
        explorer_by_slug,
        google_bounds,
        has_airbnb,
        has_amazon,
        has_browser,
        has_chatgpt,
        has_compare,
        has_correlate,
        has_custom,
        has_duolingo,
        has_google,
        has_linkedin,
        has_miband,
        has_ring,
        has_slack,
        has_sleep,
        has_spotify,
        has_telegram,
        has_thunderbird,
        has_twitter,
        has_uber,
        iso_dow,
        li_bounds,
        make_airbnb_controls,
        make_amazon_controls,
        make_browser_controls,
        make_chatgpt_controls,
        make_compare_controls,
        make_correlate_controls,
        make_custom_controls,
        make_duolingo_controls,
        make_google_controls,
        make_linkedin_controls,
        make_miband_controls,
        make_ring_controls,
        make_slack_controls,
        make_sleep_controls,
        make_spotify_controls,
        make_telegram_controls,
        make_thunderbird_controls,
        make_twitter_controls,
        make_uber_controls,
        mb_hr_bounds,
        mb_ready,
        mo,
        overview,
        px,
        render_airbnb_panel,
        render_amazon_panel,
        render_browser_panel,
        render_chatgpt_panel,
        render_compare_panel,
        render_correlate_panel,
        render_custom_panel,
        render_duolingo_panel,
        render_google_panel,
        render_home_hero,
        render_home_panel,
        render_linkedin_panel,
        render_miband_panel,
        render_ring_panel,
        render_slack_panel,
        render_sleep_panel,
        render_spotify_panel,
        render_telegram_panel,
        render_thunderbird_panel,
        render_tools_panel,
        render_twitter_panel,
        render_uber_panel,
        ring_bounds,
        sk_bounds,
        sl_bounds,
        sp_bounds,
        tab_compare,
        tab_correlate,
        tab_home,
        tab_tools,
        tb_bounds,
        tg_bounds,
        tg_dow,
        tw_bounds,
        uber_bounds,
    )


@app.cell(hide_code=True)
def _(mo):
    # Lives in its own cell so menu rebuilds don't reset the selection.
    get_tab, set_tab = mo.state(None, allow_self_loops=True)
    return get_tab, set_tab


@app.cell(hide_code=True)
def _(mo):
    query_params = mo.query_params()
    requested_theme = query_params.get("theme")
    dark_mode = mo.ui.switch(
        value=(
            requested_theme == "dark"
            if requested_theme in {"dark", "light"}
            else mo.app_meta().theme == "dark"
        ),
        label="Dark mode",
        on_change=lambda enabled: query_params.set(
            "theme", "dark" if enabled else "light"
        ),
    )
    return (dark_mode,)


@app.cell(hide_code=True)
def _(
    airbnb_bounds,
    amz_bounds,
    br_bounds,
    chatgpt_bounds,
    custom_bounds,
    cmp_bounds,
    corr_bounds,
    dark_mode,
    duo_bounds,
    explorer_by_slug,
    google_bounds,
    has_compare,
    has_correlate,
    li_bounds,
    mb_hr_bounds,
    get_tab,
    mo,
    overview,
    render_home_hero,
    ring_bounds,
    set_tab,
    sk_bounds,
    sl_bounds,
    sp_bounds,
    tab_compare,
    tab_correlate,
    tab_home,
    tab_tools,
    tb_bounds,
    tg_bounds,
    tw_bounds,
    uber_bounds,
):
    default_tab = tab_home

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
        "duolingo": _span_caption(duo_bounds),
        "uber": _span_caption(uber_bounds),
        "google": _span_caption(google_bounds),
        "airbnb": _span_caption(airbnb_bounds),
        "chatgpt": _span_caption(chatgpt_bounds),
        "custom": _span_caption(custom_bounds),
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
    # Home + Compare + Correlations on row 1; dumps A–Z on the next row.
    selected = get_tab() or default_tab

    def _chip(label: str):
        button = mo.ui.button(
            label=label,
            on_click=lambda _value, picked=label: set_tab(picked) or picked,
        )
        active = label == selected
        return button.style(
            {
                "background": "var(--background)" if active else "var(--muted)",
                "border-radius": "6px",
                "box-shadow": (
                    "inset 0 0 0 2px var(--foreground)" if active else "none"
                ),
            }
        )

    cross_row = mo.hstack(
        [_chip(tab_home), _chip(tab_compare), _chip(tab_correlate), _chip(tab_tools)],
        justify="start",
        gap=0.35,
    )
    dump_row = mo.hstack(
        [
            _chip(meta["tab_label"])
            for _slug, meta in sorted(
                explorer_by_slug.items(),
                key=lambda item: item[1]["name"].casefold(),
            )
        ],
        justify="start",
        wrap=True,
        gap=0.35,
    )
    if selected == tab_home:
        shown_caption = None
    elif selected == tab_compare:
        shown_caption = cmp_caption
    elif selected == tab_correlate:
        shown_caption = corr_caption
    elif selected == tab_tools:
        shown_caption = "Email index"
    else:
        shown_slug = next(
            (
                slug
                for slug, meta in explorer_by_slug.items()
                if meta["tab_label"] == selected
            ),
            None,
        )
        shown_caption = captions.get(shown_slug)
        if shown_caption is None and shown_slug is not None:
            meta = explorer_by_slug.get(shown_slug)
            shown_caption = (
                _span_caption(meta["bounds"]) if meta else "Not ingested"
            )

    class _Menu:
        def __init__(self, value: str) -> None:
            self.value = value

    source = _Menu(selected)
    from pathlib import Path

    logo = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
    header = mo.hstack(
        [
            mo.hstack(
                [
                    mo.image(src=logo, alt="data_dumps", width=48, height=48),
                    mo.md("# data_dumps"),
                ],
                justify="start",
                align="center",
                gap=0.75,
            ),
            dark_mode,
        ],
        justify="space-between",
        align="center",
    )
    chrome = [header]
    if selected == tab_home:
        chrome.append(render_home_hero(mo, overview))
    chrome.extend([cross_row, dump_row])
    if shown_caption:
        chrome.append(mo.md(f"_{shown_caption}_"))
    mo.vstack(chrome, gap=0.5)
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
def _(duo_bounds, has_duolingo, make_duolingo_controls, mo):
    duo_controls = (
        make_duolingo_controls(mo, duo_bounds)
        if has_duolingo and duo_bounds
        else None
    )
    return (duo_controls,)


@app.cell(hide_code=True)
def _(has_uber, make_uber_controls, mo, uber_bounds):
    uber_controls = (
        make_uber_controls(mo, uber_bounds) if has_uber and uber_bounds else None
    )
    return (uber_controls,)


@app.cell(hide_code=True)
def _(google_bounds, has_google, make_google_controls, mo):
    google_controls = (
        make_google_controls(mo, google_bounds)
        if has_google and google_bounds
        else None
    )
    return (google_controls,)


@app.cell(hide_code=True)
def _(airbnb_bounds, has_airbnb, make_airbnb_controls, mo):
    airbnb_controls = (
        make_airbnb_controls(mo, airbnb_bounds)
        if has_airbnb and airbnb_bounds
        else None
    )
    return (airbnb_controls,)


@app.cell(hide_code=True)
def _(chatgpt_bounds, has_chatgpt, make_chatgpt_controls, mo):
    chatgpt_controls = (
        make_chatgpt_controls(mo, chatgpt_bounds)
        if has_chatgpt and chatgpt_bounds
        else None
    )
    return (chatgpt_controls,)


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
def _(custom_bounds, has_custom, make_custom_controls, mo):
    custom_controls = (
        make_custom_controls(mo, custom_bounds) if has_custom and custom_bounds else None
    )
    return (custom_controls,)


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
def _(mo, overview, px, render_home_panel, source, tab_home):
    mo.stop(source.value != tab_home, output=None)
    render_home_panel(mo=mo, px=px, overview=overview)


@app.cell(hide_code=True)
def _(conn, mo, px, render_tools_panel, source, tab_tools):
    mo.stop(source.value != tab_tools, output=None)
    render_tools_panel(mo=mo, px=px, conn=conn)


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
                "`uv run ingest /path/to/Telegram_Export`"
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
                "`uv run ingest /path/to/Complete_LinkedInDataExport.zip`"
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
    duo_bounds,
    duo_controls,
    explorer_by_slug,
    has_duolingo,
    iso_dow,
    mo,
    px,
    render_duolingo_panel,
    source,
):
    mo.stop(source.value != explorer_by_slug["duolingo"]["tab_label"], output=None)
    if not has_duolingo or duo_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `duolingo.progress_events` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/duolingo`  # keep-list CSVs"
            ),
        )
    render_duolingo_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=duo_bounds,
        controls=duo_controls,
        dow_labels=iso_dow,
    )


@app.cell(hide_code=True)
def _(
    conn,
    explorer_by_slug,
    has_uber,
    iso_dow,
    mo,
    px,
    render_uber_panel,
    source,
    uber_bounds,
    uber_controls,
):
    mo.stop(source.value != explorer_by_slug["uber"]["tab_label"], output=None)
    if not has_uber or uber_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `uber.trips` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/uber/Uber\\ Data\\ Request\\ ….zip`"
            ),
        )
    render_uber_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=uber_bounds,
        controls=uber_controls,
        dow_labels=iso_dow,
    )


@app.cell(hide_code=True)
def _(
    conn,
    explorer_by_slug,
    google_bounds,
    google_controls,
    has_google,
    iso_dow,
    mo,
    px,
    render_google_panel,
    source,
):
    mo.stop(source.value != explorer_by_slug["google"]["tab_label"], output=None)
    if not has_google or google_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `google.calendar_events` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/google`"
            ),
        )
    render_google_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=google_bounds,
        controls=google_controls,
        dow_labels=iso_dow,
    )


@app.cell(hide_code=True)
def _(
    airbnb_bounds,
    airbnb_controls,
    conn,
    explorer_by_slug,
    has_airbnb,
    iso_dow,
    mo,
    px,
    render_airbnb_panel,
    source,
):
    mo.stop(source.value != explorer_by_slug["airbnb"]["tab_label"], output=None)
    if not has_airbnb or airbnb_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `airbnb.reservations` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/airbnb/airbnb.zip`"
            ),
        )
    render_airbnb_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=airbnb_bounds,
        controls=airbnb_controls,
        dow_labels=iso_dow,
    )


@app.cell(hide_code=True)
def _(
    chatgpt_bounds,
    chatgpt_controls,
    conn,
    explorer_by_slug,
    has_chatgpt,
    iso_dow,
    mo,
    px,
    render_chatgpt_panel,
    source,
):
    mo.stop(source.value != explorer_by_slug["chatgpt"]["tab_label"], output=None)
    if not has_chatgpt or chatgpt_controls is None:
        mo.stop(
            True,
            mo.md(
                "No `chatgpt.messages` in the warehouse. Stop this notebook, then:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/chatgpt/chatgpt.zip`"
            ),
        )
    render_chatgpt_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=chatgpt_bounds,
        controls=chatgpt_controls,
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
                "`uv run ingest /path/to/twitter-archive`"
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


@app.cell(hide_code=True)
def _(
    conn,
    custom_bounds,
    custom_controls,
    explorer_by_slug,
    has_custom,
    iso_dow,
    mo,
    px,
    render_custom_panel,
    source,
):
    mo.stop(source.value != explorer_by_slug["custom"]["tab_label"], output=None)
    if not has_custom or custom_controls is None:
        mo.stop(
            True,
            mo.md(
                "No custom sources yet. Stop this notebook, then ingest a folder or zip "
                "whose root contains `data_dumps.json`:\n\n"
                "`uv run ingest ~/Documents/data_dumps_raw/inbox/my-source`"
            ),
        )
    render_custom_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=custom_bounds,
        controls=custom_controls,
        dow_labels=iso_dow,
    )


@app.cell(hide_code=True)
def _(explorer_by_slug, mo):
    # Plug-in controls. Do not read widget.value here.
    from data_dumps.contributions import (
        user_explorer_contributions as _user_explorer_contributions,
    )

    plug_controls = {}
    for _plug in _user_explorer_contributions():
        _meta = explorer_by_slug.get(_plug.slug)
        if (
            _plug.make_controls is None
            or _meta is None
            or not _meta["present"]
            or _meta["bounds"] is None
        ):
            continue
        plug_controls[_plug.slug] = _plug.make_controls(mo, _meta["bounds"])
    return (plug_controls,)


@app.cell(hide_code=True)
def _(conn, explorer_by_slug, iso_dow, mo, plug_controls, px, source):
    from data_dumps.contributions import (
        user_explorer_contributions as _user_explorer_contributions,
    )

    _plug = next(
        (
            item
            for item in _user_explorer_contributions()
            if explorer_by_slug.get(item.slug, {}).get("tab_label") == source.value
        ),
        None,
    )
    mo.stop(_plug is None, output=None)
    _meta = explorer_by_slug[_plug.slug]
    _controls = plug_controls.get(_plug.slug)
    if not _meta["present"] or _plug.render_panel is None or _controls is None:
        mo.stop(
            True,
            mo.md(
                f"## {_plug.tab_label}\n\n"
                "This plug-in is registered but has no panel. On its `Contribution` "
                "in `$DATA_DUMPS_ROOT/user_contributions.py`, set `make_controls` and "
                "`render_panel`. Do not import Marimo at the top of that file."
            ),
        )
    _plug.render_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=_meta["bounds"],
        controls=_controls,
        dow_labels=iso_dow,
    )


if __name__ == "__main__":
    app.run()
