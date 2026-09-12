import marimo

__generated_with = "0.9.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import duckdb
    import marimo as mo
    import plotly.express as px

    from data_dumps.amazon_queries import data_bounds
    from data_dumps.explorer_panels import make_amazon_controls, render_amazon_panel
    from data_dumps.paths import warehouse_db

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run: "
            "uv run ingest ~/Documents/data_dumps_raw/amazon"
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    has_amz = conn.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'amazon' AND table_name = 'order_items'
        """
    ).fetchone()
    if has_amz is None or has_amz[0] == 0:
        raise FileNotFoundError(
            "amazon.order_items is missing. Stop the dashboard, then: "
            "uv run ingest ~/Documents/data_dumps_raw/amazon"
        )
    bounds = data_bounds(conn)
    dow_labels = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
    return bounds, conn, dow_labels, make_amazon_controls, mo, px, render_amazon_panel


@app.cell(hide_code=True)
def _(bounds, make_amazon_controls, mo):
    controls = make_amazon_controls(mo, bounds)
    return (controls,)


@app.cell(hide_code=True)
def _(bounds, conn, controls, dow_labels, mo, px, render_amazon_panel):
    render_amazon_panel(
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
