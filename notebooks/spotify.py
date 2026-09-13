import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import make_spotify_controls, render_spotify_panel
    from data_dumps.paths import warehouse_db
    from data_dumps.spotify_queries import data_bounds, has_mb_data

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run: "
            "uv run ingest ~/Documents/data_dumps_raw/spotify/my_spotify_data.zip"
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    has_plays = conn.execute("""
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'spotify' AND table_name = 'plays'
        """).fetchone()
    if has_plays is None or has_plays[0] == 0:
        raise FileNotFoundError(
            "spotify.plays is missing. Stop the dashboard, then: "
            "uv run ingest ~/Documents/data_dumps_raw/spotify/my_spotify_data.zip"
        )
    bounds = data_bounds(conn)
    mb_ready = has_mb_data(conn)
    return (
        bounds,
        conn,
        make_spotify_controls,
        mb_ready,
        mo,
        px,
        render_spotify_panel,
    )


@app.cell(hide_code=True)
def _(bounds, make_spotify_controls, mo):
    controls = make_spotify_controls(mo, bounds)
    return (controls,)


@app.cell(hide_code=True)
def _(bounds, conn, controls, mb_ready, mo, px, render_spotify_panel):
    render_spotify_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=bounds,
        mb_ready=mb_ready,
        controls=controls,
    )
    return


if __name__ == "__main__":
    app.run()
