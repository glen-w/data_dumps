import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import make_sleep_controls, render_sleep_panel
    from data_dumps.paths import warehouse_db
    from data_dumps.sleep_queries import data_bounds

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run: "
            "uv run ingest ~/Documents/data_dumps_raw/sleep_as_android/sleep-export.zip"
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    has_sleep = conn.execute("""
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'sleep' AND table_name = 'sessions'
        """).fetchone()
    if has_sleep is None or has_sleep[0] == 0:
        raise FileNotFoundError(
            "sleep.sessions is missing. Stop the dashboard, then: "
            "uv run ingest ~/Documents/data_dumps_raw/sleep_as_android/sleep-export.zip"
        )
    bounds = data_bounds(conn)
    iso_dow = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
    return (
        bounds,
        conn,
        iso_dow,
        make_sleep_controls,
        mo,
        px,
        render_sleep_panel,
    )


@app.cell(hide_code=True)
def _(bounds, make_sleep_controls, mo):
    # Controls are created here and read in the render cell (Marimo rule).
    controls = make_sleep_controls(mo, bounds)
    return (controls,)


@app.cell(hide_code=True)
def _(bounds, conn, controls, iso_dow, mo, px, render_sleep_panel):
    render_sleep_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=bounds,
        controls=controls,
        dow_labels=iso_dow,
    )
    return


if __name__ == "__main__":
    app.run()
