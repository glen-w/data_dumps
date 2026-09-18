import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.explorer_panels import make_linkedin_controls, render_linkedin_panel
    from data_dumps.linkedin_queries import data_bounds
    from data_dumps.paths import warehouse_db

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run: "
            "uv run ingest /path/to/Complete_LinkedInDataExport.zip"
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    has_li = conn.execute("""
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'linkedin' AND table_name = 'connections'
        """).fetchone()
    if has_li is None or has_li[0] == 0:
        raise FileNotFoundError(
            "linkedin.connections is missing. Stop the dashboard, then: "
            "uv run ingest /path/to/Complete_LinkedInDataExport.zip"
        )
    bounds = data_bounds(conn)
    dow_labels = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    return bounds, conn, dow_labels, make_linkedin_controls, mo, px, render_linkedin_panel


@app.cell(hide_code=True)
def _(bounds, make_linkedin_controls, mo):
    controls = make_linkedin_controls(mo, bounds)
    return (controls,)


@app.cell(hide_code=True)
def _(bounds, conn, controls, dow_labels, mo, px, render_linkedin_panel):
    render_linkedin_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=bounds,
        controls=controls,
        dow_labels=dow_labels,
    )
    return


if __name__ == "__main__":
    app.run()
