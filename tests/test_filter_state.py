"""FilterState and WHERE clause tests."""

from data_dumps.spotify_queries import (
    FilterState,
    _where_and_params,
    filter_from_widgets,
)


def test_chip_labels_full_year_range_hidden():
    bounds = {"min_year": 2016, "max_year": 2020}
    f = filter_from_widgets(
        bounds,
        year_start=2016,
        year_end=2020,
        kinds=[],
        platform_buckets=[],
        conn_countries=[],
    )
    labels = [field for field, _ in f.chip_labels()]
    assert "year_range" not in labels


def test_chip_labels_narrowed_year():
    bounds = {"min_year": 2016, "max_year": 2020}
    f = filter_from_widgets(
        bounds,
        year_start=2018,
        year_end=2020,
        kinds=[],
        platform_buckets=[],
        conn_countries=[],
    )
    labels = dict(f.chip_labels())
    assert "year_range" in labels
    assert "2018" in labels["year_range"]


def test_clear_field_resets_artist():
    f = FilterState(artist_name="Alpha", kinds=["track"])
    f.clear_field("artist_name")
    assert f.artist_name is None
    assert f.kinds == ["track"]


def test_where_params_order():
    f = FilterState(
        year_start=2018,
        year_end=2020,
        kinds=["track"],
        platform_buckets=["android"],
        conn_countries=["IT"],
        artist_search="alp",
    )
    where, params = _where_and_params(f)
    assert "year >=" in where
    assert "kind IN" in where
    assert "platform_bucket IN" in where
    assert "conn_country IN" in where
    assert "contains(lower(artist_name)" in where
    assert params == [2018, 2020, "track", "android", "IT", "alp"]


def test_where_table_alias():
    f = FilterState(year_start=2020)
    where, params = _where_and_params(f, table_alias="p")
    assert where.startswith("p.year")
    assert params == [2020]


def test_filter_digest_stable():
    f1 = FilterState(year_start=2020, kinds=["track"])
    f2 = FilterState(kinds=["track"], year_start=2020)
    assert f1.filter_digest() == f2.filter_digest()
