"""Integration tests for spotify_queries against synthetic plays."""

from data_dumps.spotify_queries import (
    FilterState,
    album_depth,
    artist_monthly_timeline,
    artist_rank_movement,
    bump_chart_artists,
    calendar_daily,
    circadian_heatmap,
    comeback_artists,
    data_bounds,
    decade_bars,
    discovery_vs_repeats,
    forgotten_artists,
    genre_treemap,
    has_mb_data,
    has_mb_tables,
    hours_by_country,
    hours_by_kind,
    hours_by_platform,
    kind_platform_sunburst,
    listening_sessions,
    milestones,
    monthly_hours,
    narrative_context,
    offline_vs_online,
    scoreboard,
    searched_but_rarely_played,
    shuffle_intent,
    skip_trends,
    streak_stats,
    top_albums,
    top_artists,
    top_shows,
    top_tracks,
    treemap_artist_album,
)


def test_data_bounds(plays_conn):
    conn, _ = plays_conn
    bounds = data_bounds(conn)
    assert bounds["min_year"] == 2016
    assert bounds["max_year"] == 2020
    assert "track" in bounds["kinds"]
    assert "episode" in bounds["kinds"]


def test_scoreboard_and_streak(plays_conn):
    conn, _ = plays_conn
    f = FilterState(year_start=2020, year_end=2020)
    score = scoreboard(conn, f)
    assert score.iloc[0]["plays"] > 0
    streak = streak_stats(conn, f)
    assert streak.iloc[0]["longest_streak_days"] is not None


def test_scoreboard_empty_year(plays_conn):
    conn, _ = plays_conn
    f = FilterState(year_start=2017, year_end=2017)
    score = scoreboard(conn, f)
    assert score.iloc[0]["plays"] == 0


def test_scoreboard_compare_predates_data(plays_conn):
    conn, _ = plays_conn
    f = FilterState(year_start=2016, year_end=2016)
    score = scoreboard(conn, f, compare_previous=True)
    assert len(score) == 1
    assert "compare_note" in score.columns


def test_top_rankings(plays_conn):
    conn, _ = plays_conn
    f = FilterState()
    artists = top_artists(conn, f, limit=5)
    assert "Alpha" in artists["artist_name"].tolist()
    tracks = top_tracks(conn, f, limit=5)
    assert len(tracks) > 0
    albums = top_albums(conn, f, limit=5)
    assert len(albums) > 0
    shows = top_shows(conn, f, limit=5)
    assert shows.iloc[0]["episode_show_name"] == "Test Podcast"


def test_filter_narrows_artists(plays_conn):
    conn, _ = plays_conn
    all_f = FilterState()
    narrow = FilterState(artist_name="Alpha")
    assert top_artists(conn, narrow).iloc[0]["artist_name"] == "Alpha"
    assert len(top_artists(conn, all_f)) >= len(top_artists(conn, narrow))


def test_discovery_vs_repeats(plays_conn):
    conn, _ = plays_conn
    f = FilterState(year_start=2020, year_end=2020)
    disc = discovery_vs_repeats(conn, f)
    types = set(disc["play_type"])
    assert "discovery" in types
    assert "repeat" in types


def test_comeback_artists(plays_conn):
    conn, _ = plays_conn
    f = FilterState(year_start=2020, year_end=2020)
    comebacks = comeback_artists(conn, f)
    assert "Return Act" in comebacks["artist_name"].tolist()


def test_forgotten_artists(plays_conn):
    conn, _ = plays_conn
    f = FilterState()
    forgotten = forgotten_artists(conn, f, min_hours=20.0, silent_years=2, limit=10)
    assert "Old Star" in forgotten["artist_name"].tolist()


def test_circadian_shuffle_longitudinal(plays_conn):
    conn, _ = plays_conn
    f = FilterState()
    assert not circadian_heatmap(conn, f).empty
    assert not shuffle_intent(conn, f).empty
    assert not monthly_hours(conn, f).empty
    assert not hours_by_kind(conn, f).empty
    assert not hours_by_platform(conn, f).empty
    assert not hours_by_country(conn, f).empty
    assert not skip_trends(conn, f).empty


def test_expanded_charts(plays_conn):
    conn, _ = plays_conn
    f = FilterState()
    assert not treemap_artist_album(conn, f).empty
    assert not calendar_daily(conn, f).empty
    assert not bump_chart_artists(conn, f).empty
    assert not kind_platform_sunburst(conn, f).empty


def test_mb_tables_without_data(plays_conn):
    conn, _ = plays_conn
    assert not has_mb_tables(conn)
    assert not has_mb_data(conn)


def test_mb_genre_decade(plays_conn_mb):
    conn, _ = plays_conn_mb
    assert has_mb_data(conn)
    f = FilterState()
    genre = genre_treemap(conn, f)
    assert "rock" in genre["genre"].tolist()
    decade = decade_bars(conn, f)
    assert "2010s" in decade["decade"].tolist()


def test_offline_and_milestones(plays_conn):
    conn, _ = plays_conn
    f = FilterState()
    off = offline_vs_online(conn, f)
    assert set(off["mode"]) == {"online"}  # fixture has offline=False everywhere
    assert int(off["plays"].sum()) > 0

    ms = milestones(conn, f)
    row = ms.iloc[0]
    assert int(row["days_listened"]) > 0
    assert row["most_repeated_track"] == "Ancient Hit"
    assert int(row["most_repeated_plays"]) == 15
    assert row["longest_play_title"] == "Early Song"  # 3 h single play
    assert str(row["first_play_day"]).startswith("2016-01-15")


def test_album_depth(plays_conn):
    conn, _ = plays_conn
    # Every fixture play sits on album "Album"; 12 distinct Alpha tracks + repeats.
    depth = album_depth(conn, FilterState(), min_plays=5)
    assert not depth.empty
    alpha = depth.loc[depth["artist_name"] == "Alpha"].iloc[0]
    assert int(alpha["unique_tracks"]) == 12
    assert int(alpha["plays"]) == 17
    assert float(alpha["depth_score"]) > 0
    assert alpha["top_track"] == "Alpha Song 0"
    # Filter narrows albums; a huge min_plays returns nothing.
    assert album_depth(conn, FilterState(), min_plays=10_000).empty


def test_listening_sessions(plays_conn):
    conn, _ = plays_conn
    sessions = listening_sessions(conn, FilterState(), gap_minutes=30, limit=5)
    assert not sessions.empty
    assert set(sessions.columns) >= {
        "started_local",
        "span_hours",
        "played_hours",
        "plays",
        "top_artist",
    }
    # Fixture plays are one per day, so every session is a single play.
    assert int(sessions["plays"].max()) == 1
    assert float(sessions.iloc[0]["played_hours"]) == 3.0


def test_artist_rank_movement(plays_conn):
    conn, _ = plays_conn
    # No year window -> empty with a note.
    none = artist_rank_movement(conn, FilterState())
    assert none.empty
    assert none.attrs["compare_note"]

    mv = artist_rank_movement(conn, FilterState(year_start=2020, year_end=2020))
    assert not mv.empty
    assert set(mv["status"]) <= {"new", "up", "down", "same"}
    # Return Act was silent in 2019 (previous window) so it is "new" in 2020.
    ret = mv.loc[mv["artist_name"] == "Return Act"].iloc[0]
    assert ret["status"] == "new"
    assert ret["prev_rank"] is None or str(ret["prev_rank"]) in {"nan", "None", "<NA>"}


def test_artist_monthly_timeline(plays_conn):
    conn, _ = plays_conn
    locked = artist_monthly_timeline(conn, FilterState(artist_name="Alpha"))
    assert set(locked["artist_name"]) == {"Alpha"}
    assert "year_month" in locked.columns
    top3 = artist_monthly_timeline(conn, FilterState(), max_artists=3)
    assert 1 <= top3["artist_name"].nunique() <= 3
    explicit = artist_monthly_timeline(conn, FilterState(), artists=["Gamma", "Alpha"])
    assert set(explicit["artist_name"]) == {"Gamma", "Alpha"}


def test_searched_but_rarely_played(plays_conn):
    conn, _ = plays_conn
    # No searches table -> empty frame, no crash.
    assert searched_but_rarely_played(conn).empty
    conn.execute("""
        CREATE TABLE spotify.searches (
            searched_at TIMESTAMP, searched_at_local TIMESTAMP,
            search_query VARCHAR, platform VARCHAR, year BIGINT, month BIGINT
        )
        """)
    conn.execute("""
        INSERT INTO spotify.searches VALUES
        (TIMESTAMP '2020-01-01', TIMESTAMP '2020-01-01', 'fresh track', 'android', 2020, 1),
        (TIMESTAMP '2020-01-02', TIMESTAMP '2020-01-02', 'fresh track', 'android', 2020, 1),
        (TIMESTAMP '2020-01-03', TIMESTAMP '2020-01-03', 'ancient hit', 'android', 2020, 1),
        (TIMESTAMP '2020-01-04', TIMESTAMP '2020-01-04', 'zzz nothing', 'android', 2020, 1)
        """)
    df = searched_but_rarely_played(conn, max_plays=3)
    queries = set(df["search_query"])
    assert "fresh track" in queries  # 1 play
    assert "ancient hit" not in queries  # 15 plays
    assert "zzz nothing" not in queries  # no name match
    fresh = df.loc[df["search_query"] == "fresh track"].iloc[0]
    assert int(fresh["searches"]) == 2
    assert int(fresh["matched_plays"]) == 1


def test_narrative_context_keys(plays_conn):
    conn, _ = plays_conn
    ctx = narrative_context(conn, FilterState(year_start=2020))
    assert "filter_digest" in ctx
    assert "scoreboard" in ctx
    assert "top_artists" in ctx
