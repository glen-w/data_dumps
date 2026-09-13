import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import make_twitter_controls, render_twitter_panel
    from data_dumps.paths import warehouse_db
    from data_dumps.twitter_queries import data_bounds

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
        bounds,
        conn,
        dow_labels,
        make_twitter_controls,
        mo,
        px,
        render_twitter_panel,
    )


@app.cell(hide_code=True)
def _(bounds, make_twitter_controls, mo):
    controls = make_twitter_controls(mo, bounds)
    return (controls,)


@app.cell(hide_code=True)
def _(bounds, conn, controls, dow_labels, mo, px, render_twitter_panel):
    render_twitter_panel(
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
