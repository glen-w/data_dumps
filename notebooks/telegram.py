import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.paths import warehouse_db
    from data_dumps.telegram_queries import (
        PEOPLE_CHAT_TYPES,
        bump_chart_chats,
        calendar_daily,
        calls_by_year,
        chat_reply_scatter,
        circadian_heatmap,
        comeback_chats,
        data_bounds,
        filter_from_widgets,
        forgotten_chats,
        me_vs_them,
        media_mix,
        messages_by_chat,
        monthly_by_chat_type,
        reaction_mix,
        scoreboard,
        streak_stats,
    )

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run: "
            "uv run ingest ~/Documents/data_dumps_raw/telegram/Telegram_Export_2026-09-03"
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    has_tg = conn.execute("""
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'telegram' AND table_name = 'messages'
        """).fetchone()
    if has_tg is None or has_tg[0] == 0:
        raise FileNotFoundError(
            "telegram.messages is missing. "
            "Stop the dashboard, then: "
            "uv run ingest ~/Documents/data_dumps_raw/telegram/Telegram_Export_2026-09-03"
        )
    bounds = data_bounds(conn)
    dow_labels = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    return (
        PEOPLE_CHAT_TYPES,
        bounds,
        bump_chart_chats,
        calendar_daily,
        calls_by_year,
        chat_reply_scatter,
        circadian_heatmap,
        comeback_chats,
        conn,
        dow_labels,
        filter_from_widgets,
        forgotten_chats,
        me_vs_them,
        media_mix,
        messages_by_chat,
        mo,
        monthly_by_chat_type,
        px,
        reaction_mix,
        scoreboard,
        streak_stats,
    )


@app.cell(hide_code=True)
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
    chat_type_select = mo.ui.multiselect(
        options=bounds["chat_types"],
        value=[],
        label="Chat type",
    )
    event_select = mo.ui.multiselect(
        options=bounds["event_types"],
        value=[],
        label="Event type",
    )
    media_select = mo.ui.multiselect(
        options=bounds["media_kinds"],
        value=[],
        label="Media kind",
    )
    compare_toggle = mo.ui.checkbox(label="Compare vs previous equal window", value=False)
    people_btn = mo.ui.run_button(label="People only")
    clear_types_btn = mo.ui.run_button(label="Clear types")
    clear_chat_btn = mo.ui.run_button(label="Clear chat lock")
    clear_media_btn = mo.ui.run_button(label="Clear media")
    get_chat_name, set_chat_name = mo.state(None)
    get_types_override, set_types_override = mo.state(None)
    get_media_override, set_media_override = mo.state(None)

    mo.vstack(
        [
            mo.md(
                f"# Telegram explorer\n"
                f"Data: {bounds['first_day']} → {bounds['last_day']} "
                f"({len(bounds['chats'])} chats). Media files stay on disk; this view is counts only."
            ),
            mo.hstack(
                [
                    year_start_slider,
                    year_end_slider,
                ],
                justify="start",
                gap=1,
            ),
            mo.hstack(
                [
                    chat_type_select,
                    event_select,
                    media_select,
                ],
                justify="start",
                gap=1,
            ),
            mo.hstack(
                [
                    compare_toggle,
                    people_btn,
                    clear_types_btn,
                    clear_chat_btn,
                    clear_media_btn,
                ],
                gap=1,
            ),
        ],
        gap=0.5,
    )
    return (
        chat_type_select,
        clear_chat_btn,
        clear_media_btn,
        clear_types_btn,
        compare_toggle,
        event_select,
        get_chat_name,
        get_media_override,
        get_types_override,
        media_select,
        people_btn,
        set_chat_name,
        set_media_override,
        set_types_override,
        year_end_slider,
        year_start_slider,
    )


@app.cell(hide_code=True)
def _(
    PEOPLE_CHAT_TYPES,
    clear_chat_btn,
    clear_media_btn,
    clear_types_btn,
    people_btn,
    set_chat_name,
    set_media_override,
    set_types_override,
):
    if people_btn.value:
        set_types_override(list(PEOPLE_CHAT_TYPES))
    if clear_types_btn.value:
        set_types_override([])
    if clear_chat_btn.value:
        set_chat_name(None)
    if clear_media_btn.value:
        set_media_override([])
    return


@app.cell(hide_code=True)
def _(
    bounds,
    chat_type_select,
    event_select,
    filter_from_widgets,
    get_chat_name,
    get_media_override,
    get_types_override,
    media_select,
    mo,
    set_media_override,
    set_types_override,
    year_end_slider,
    year_start_slider,
):
    chat_types = (
        get_types_override()
        if get_types_override() is not None
        else list(chat_type_select.value)
    )
    media_kinds = (
        get_media_override()
        if get_media_override() is not None
        else list(media_select.value)
    )
    if chat_type_select.value and get_types_override() is not None:
        set_types_override(None)
    if media_select.value and get_media_override() is not None:
        set_media_override(None)

    filters = filter_from_widgets(
        bounds,
        year_start=year_start_slider.value,
        year_end=year_end_slider.value,
        chat_types=chat_types,
        event_types=list(event_select.value),
        media_kinds=media_kinds,
        chat_name=get_chat_name(),
    )
    chip_items = filters.chip_labels()
    if chip_items:
        _chip = mo.hstack([mo.md(f"**{label}**") for _, label in chip_items], gap=0.5)
    else:
        _chip = mo.md("_No extra filters active_")
    _chip
    return (filters,)


@app.cell(hide_code=True)
def _(compare_toggle, conn, filters, mo, scoreboard, streak_stats):
    score_df = scoreboard(conn, filters, compare_previous=compare_toggle.value)
    streak_df = streak_stats(conn, filters)
    mo.vstack(
        [
            mo.md("## Scoreboard"),
            mo.ui.table(score_df),
            mo.ui.table(streak_df),
        ],
        gap=0.5,
    )
    return


@app.cell(hide_code=True)
def _(conn, filters, me_vs_them, mo, monthly_by_chat_type, px):
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
            title="Messages sent by you vs others",
        )
        fig_me.update_layout(xaxis_title="Year", yaxis_title="Messages")
    mo.vstack(
        [
            mo.md("## Longitudinal"),
            mo.hstack([mo.ui.plotly(fig_month), mo.ui.plotly(fig_me)], gap=1),
        ],
        gap=0.5,
    )
    return


@app.cell(hide_code=True)
def _(conn, filters, messages_by_chat, mo, px):
    chats_df = messages_by_chat(conn, filters, limit=25)
    chats_table = mo.ui.table(chats_df, selection="single")
    if chats_df.empty:
        rank_plot = mo.ui.plotly(px.bar(title="No chats for this filter"))
    else:
        fig_rank = px.bar(
            chats_df.head(15),
            x="events",
            y="chat_name",
            orientation="h",
            title="Top chats by events",
        )
        fig_rank.update_layout(xaxis_title="Events", yaxis_title="Chat")
        rank_plot = mo.ui.plotly(fig_rank)
    mo.vstack(
        [
            mo.md("## Chats — select a row or click the bar to filter"),
            mo.hstack([chats_table, rank_plot], gap=1),
        ],
        gap=0.5,
    )
    return chats_table, rank_plot


@app.cell(hide_code=True)
def _(chats_table, rank_plot, set_chat_name):
    _selected = chats_table.value
    if _selected is not None and len(_selected) == 1:
        set_chat_name(_selected.iloc[0]["chat_name"])
    if rank_plot.value and rank_plot.value.get("points"):
        _y = rank_plot.value["points"][0].get("y")
        if _y:
            set_chat_name(_y)
    return


@app.cell(hide_code=True)
def _(
    chat_reply_scatter,
    comeback_chats,
    conn,
    filters,
    forgotten_chats,
    mo,
    px,
):
    scatter_df = chat_reply_scatter(conn, filters)
    forgotten_df = forgotten_chats(conn, filters)
    comebacks_df = comeback_chats(conn, filters)
    if scatter_df.empty:
        scatter_plot = mo.ui.plotly(px.scatter(title="No chat scatter"))
    else:
        fig_sc = px.scatter(
            scatter_df,
            x="events",
            y="reply_pct",
            size="events",
            color="chat_type",
            hover_name="chat_name",
            title="Volume vs reply %",
        )
        fig_sc.update_layout(xaxis_title="Events", yaxis_title="Reply %")
        scatter_plot = mo.ui.plotly(fig_sc)
    mo.vstack(
        [
            mo.md("## Relationships — click a point to lock that chat"),
            scatter_plot,
            mo.hstack(
                [
                    mo.vstack(
                        [mo.md("**Forgotten** (≥50 events, silent >2y)"), mo.ui.table(forgotten_df)]
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
        gap=1,
    )
    return (scatter_plot,)


@app.cell(hide_code=True)
def _(scatter_plot, set_chat_name):
    if scatter_plot.value and scatter_plot.value.get("points"):
        point = scatter_plot.value["points"][0]
        name = point.get("hovertext") or point.get("customdata")
        if isinstance(name, list) and name:
            name = name[0]
        if name:
            set_chat_name(name)
    return


@app.cell(hide_code=True)
def _(
    bump_chart_chats,
    calendar_daily,
    circadian_heatmap,
    conn,
    dow_labels,
    filters,
    mo,
    px,
):
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

    mo.vstack(
        [
            mo.md("## Time"),
            mo.hstack([mo.ui.plotly(fig_cal), mo.ui.plotly(fig_circ)], gap=1),
            mo.ui.plotly(fig_bump),
        ],
        gap=1,
    )
    return


@app.cell(hide_code=True)
def _(calls_by_year, conn, filters, media_mix, mo, px, reaction_mix):
    media_df = media_mix(conn, filters, exclude_none=True)
    react_df = reaction_mix(conn, filters)
    calls_df = calls_by_year(conn, filters)

    fig_media = (
        px.pie(media_df, names="media_kind", values="events", title="Media mix (excluding none)")
        if not media_df.empty
        else px.pie(title="No media in this filter")
    )
    media_plot = mo.ui.plotly(fig_media)

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
            mo.md("## Media · reactions · calls"),
            mo.hstack(
                [media_plot, mo.ui.plotly(fig_react), mo.ui.plotly(fig_calls)],
                gap=1,
            ),
        ],
        gap=0.5,
    )
    return (media_plot,)


@app.cell(hide_code=True)
def _(media_plot, set_media_override):
    if media_plot.value and media_plot.value.get("points"):
        label = media_plot.value["points"][0].get("label")
        if label:
            set_media_override([label])
    return


if __name__ == "__main__":
    app.run()
