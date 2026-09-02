"""Integration tests for spotify_queries against synthetic plays."""

from data_dumps.spotify_queries import (
    FilterState,
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
    monthly_hours,
    narrative_context,
    scoreboard,
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


def test_narrative_context_keys(plays_conn):
    conn, _ = plays_conn
    ctx = narrative_context(conn, FilterState(year_start=2020))
    assert "filter_digest" in ctx
    assert "scoreboard" in ctx
    assert "top_artists" in ctx
