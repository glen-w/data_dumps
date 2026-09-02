import marimo

__generated_with = "0.9.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import duckdb
    import plotly.express as px
    from data_dumps.paths import warehouse_db

    db_path = warehouse_db()
    if not db_path.exists():
        raise FileNotFoundError(
            f"No warehouse at {db_path}. Run: uv run ingest my_spotify_data.zip"
        )
    conn = duckdb.connect(str(db_path), read_only=True)
    return conn, px


@app.cell
def _(conn):
    conn.execute(
        """
        SELECT
            count(*) AS plays,
            round(sum(hours), 1) AS hours,
            min(played_at)::DATE AS first_day,
            max(played_at)::DATE AS last_day,
            count(*) FILTER (WHERE year = 2017) AS plays_2017
        FROM spotify.plays
        """
    ).df()
    return


@app.cell
def _(conn, px):
    # 1. Hours by year/month — surface the 2017 hole
    monthly = conn.execute(
        """
        SELECT
            year,
            month,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).df()
    monthly["year_month"] = (
        monthly["year"].astype(str) + "-" + monthly["month"].astype(str).str.zfill(2)
    )
    fig1 = px.bar(
        monthly,
        x="year_month",
        y="hours",
        title="Listening hours by month (2017 gap is export data, not life)",
        labels={"year_month": "month", "hours": "hours"},
    )
    fig1.update_layout(xaxis_tickangle=-45)
    fig1
    return


@app.cell
def _(conn, px):
    # 2. Music vs podcast vs audiobook over years
    by_kind = conn.execute(
        """
        SELECT year, kind, round(sum(hours), 2) AS hours
        FROM spotify.plays
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).df()
    fig2 = px.bar(
        by_kind,
        x="year",
        y="hours",
        color="kind",
        barmode="stack",
        title="Hours by content kind",
    )
    fig2
    return


@app.cell
def _(conn, px):
    # 3. Platform as life proxy
    platforms = conn.execute(
        """
        SELECT platform_bucket, round(sum(hours), 1) AS hours
        FROM spotify.plays
        GROUP BY 1
        ORDER BY hours DESC
        """
    ).df()
    fig3 = px.pie(
        platforms,
        names="platform_bucket",
        values="hours",
        title="Hours by platform bucket",
    )
    fig3
    return


@app.cell
def _(conn, px):
    # 4. Country as travel diary
    countries = conn.execute(
        """
        SELECT
            strftime(played_at, '%Y-%m') AS month,
            conn_country,
            round(sum(hours), 2) AS hours
        FROM spotify.plays
        WHERE conn_country IS NOT NULL
        GROUP BY 1, 2
        HAVING sum(hours) > 5
        ORDER BY 1, 3 DESC
        """
    ).df()
    fig4 = px.area(
        countries,
        x="month",
        y="hours",
        color="conn_country",
        title="Hours by country (months with >5h)",
    )
    fig4.update_layout(xaxis_tickangle=-45)
    fig4
    return


@app.cell
def _(conn):
    # 5. Forgotten — artists once high-hours, silent >2 years
    forgotten = conn.execute(
        """
        WITH artist_hours AS (
            SELECT
                artist_name,
                round(sum(hours), 1) AS total_hours,
                max(played_at) AS last_play
            FROM spotify.plays
            WHERE kind = 'track' AND artist_name IS NOT NULL
            GROUP BY 1
            HAVING sum(hours) >= 20
        )
        SELECT artist_name, total_hours, last_play::DATE AS last_play
        FROM artist_hours
        WHERE last_play < current_timestamp - INTERVAL '2 years'
        ORDER BY total_hours DESC
        LIMIT 25
        """
    ).df()
    forgotten
    return


@app.cell
def _(conn, px):
    # 6. Skip / incomplete rate by year
    skips = conn.execute(
        """
        SELECT
            year,
            round(100.0 * avg(CASE WHEN skipped THEN 1.0 ELSE 0.0 END), 1) AS skip_pct,
            round(100.0 * avg(CASE WHEN full_play THEN 1.0 ELSE 0.0 END), 1) AS full_play_pct,
            round(100.0 * avg(CASE WHEN ms_played < 30000 THEN 1.0 ELSE 0.0 END), 1) AS under_30s_pct
        FROM spotify.plays
        WHERE kind = 'track'
        GROUP BY 1
        ORDER BY 1
        """
    ).df()
    fig6 = px.line(
        skips,
        x="year",
        y=["skip_pct", "full_play_pct", "under_30s_pct"],
        title="Track playback quality signals by year",
        labels={"value": "percent", "variable": "metric"},
    )
    fig6
    return


@app.cell
def _(conn):
    # Ad-hoc SQL — edit and re-run
    conn.execute(
        """
        SELECT artist_name, round(sum(hours), 1) AS hours
        FROM spotify.plays
        WHERE kind = 'track'
        GROUP BY 1
        ORDER BY hours DESC
        LIMIT 15
        """
    ).df()
    return


if __name__ == "__main__":
    app.run()
