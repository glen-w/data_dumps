import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.paths import warehouse_db
    from data_dumps.telegram_queries import (
        circadian_heatmap,
        data_bounds,
        filter_from_widgets,
        media_mix,
        messages_by_chat,
        messages_by_chat_type,
        monthly_messages,
        scoreboard,
        FilterState,
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
    return (
        FilterState,
        bounds,
        circadian_heatmap,
        conn,
        data_bounds,
        filter_from_widgets,
        media_mix,
        messages_by_chat,
        messages_by_chat_type,
        mo,
        monthly_messages,
        px,
        scoreboard,
        warehouse_db,
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
    clear_chat_btn = mo.ui.run_button(label="Clear chat lock")
    get_chat_name, set_chat_name = mo.state(None)

    mo.md(
        f"# Telegram explorer\n"
        f"Data: {bounds['first_day']} → {bounds['last_day']} "
        f"({len(bounds['chats'])} chats). Media files stay on disk; this view is counts only."
    )
    mo.hstack(
        [
            year_start_slider,
            year_end_slider,
            chat_type_select,
            event_select,
            media_select,
            clear_chat_btn,
        ],
        justify="start",
        gap=1,
    )
    return (
        chat_type_select,
        clear_chat_btn,
        event_select,
        get_chat_name,
        media_select,
        set_chat_name,
        year_end_slider,
        year_start_slider,
    )


@app.cell
def _(clear_chat_btn, set_chat_name):
    if clear_chat_btn.value:
        set_chat_name(None)
    return


@app.cell
def _(
    bounds,
    chat_type_select,
    event_select,
    filter_from_widgets,
    get_chat_name,
    media_select,
    mo,
    year_end_slider,
    year_start_slider,
):
    filters = filter_from_widgets(
        bounds,
        year_start=year_start_slider.value,
        year_end=year_end_slider.value,
        chat_types=list(chat_type_select.value),
        event_types=list(event_select.value),
        media_kinds=list(media_select.value),
        chat_name=get_chat_name(),
    )
    chip_items = filters.chip_labels()
    if chip_items:
        _chip = mo.hstack([mo.md(f"**{label}**") for _, label in chip_items], gap=0.5)
    else:
        _chip = mo.md("_No extra filters active_")
    _chip
    return (filters,)


@app.cell
def _(conn, filters, mo, scoreboard):
    score_df = scoreboard(conn, filters)
    mo.md("## Scoreboard")
    mo.ui.table(score_df)
    return


@app.cell
def _(conn, filters, mo, monthly_messages, px):
    monthly_df = monthly_messages(conn, filters)
    mo.md("## Monthly volume")
    if monthly_df.empty:
        _month = mo.md("_No messages for this filter._")
    else:
        fig_month = px.bar(
            monthly_df,
            x="year_month",
            y="events",
            title="Events by month",
        )
        fig_month.update_layout(xaxis_title="Month", yaxis_title="Events")
        _month = mo.ui.plotly(fig_month)
    _month
    return


@app.cell
def _(conn, filters, messages_by_chat, mo):
    chats_df = messages_by_chat(conn, filters, limit=25)
    mo.md("## Chats — select a row to filter")
    chats_table = mo.ui.table(chats_df, selection="single")
    chats_table
    return (chats_table,)


@app.cell
def _(chats_table, set_chat_name):
    _selected = chats_table.value
    if _selected is not None and len(_selected) == 1:
        set_chat_name(_selected.iloc[0]["chat_name"])
    return


@app.cell
def _(
    circadian_heatmap,
    conn,
    filters,
    media_mix,
    messages_by_chat,
    messages_by_chat_type,
    mo,
    px,
):
    ranking_df = messages_by_chat(conn, filters, limit=15)
    type_df = messages_by_chat_type(conn, filters)
    media_df = media_mix(conn, filters)
    circadian_df = circadian_heatmap(conn, filters)

    mo.md("## Chat ranking · Type mix · Media mix · Circadian")

    fig_rank = px.bar(
        ranking_df,
        x="events",
        y="chat_name",
        orientation="h",
        title="Top chats by events",
    )
    fig_rank.update_layout(xaxis_title="Events", yaxis_title="Chat")

    fig_type = px.pie(
        type_df,
        names="chat_type",
        values="events",
        title="Events by chat type",
    )
    fig_media = px.pie(
        media_df,
        names="media_kind",
        values="events",
        title="Events by media kind",
    )

    if not circadian_df.empty:
        circ = circadian_df.copy()
        circ["dow_label"] = circ["dow"].map(
            {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
        )
        fig_circ = px.density_heatmap(
            circ,
            x="hour",
            y="dow_label",
            z="events",
            title="Events by weekday × hour (Europe/Rome)",
            color_continuous_scale="Viridis",
        )
        fig_circ.update_layout(xaxis_title="Hour", yaxis_title="Weekday")
    else:
        fig_circ = px.imshow([[0]], title="No circadian data for filter")

    mo.hstack(
        [
            mo.ui.plotly(fig_rank),
            mo.ui.plotly(fig_type),
            mo.ui.plotly(fig_media),
            mo.ui.plotly(fig_circ),
        ],
        gap=1,
    )
    return


if __name__ == "__main__":
    app.run()
