import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import make_telegram_controls, render_telegram_panel
    from data_dumps.paths import warehouse_db
    from data_dumps.telegram_queries import data_bounds

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run: "
            "uv run ingest /path/to/Telegram_Export"
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    has_tg = conn.execute("""
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'telegram' AND table_name = 'messages'
        """).fetchone()
    if has_tg is None or has_tg[0] == 0:
        raise FileNotFoundError(
            "telegram.messages is missing. Stop the dashboard, then: "
            "uv run ingest /path/to/Telegram_Export"
        )
    bounds = data_bounds(conn)
    dow_labels = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    return (
        bounds,
        conn,
        dow_labels,
        make_telegram_controls,
        mo,
        px,
        render_telegram_panel,
    )


@app.cell(hide_code=True)
def _(bounds, make_telegram_controls, mo):
    controls = make_telegram_controls(mo, bounds)
    return (controls,)


@app.cell(hide_code=True)
def _(bounds, conn, controls, dow_labels, mo, px, render_telegram_panel):
    render_telegram_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=bounds,
        dow_labels=dow_labels,
        controls=controls,
    )
    return


if __name__ == "__main__":
    app.run()
