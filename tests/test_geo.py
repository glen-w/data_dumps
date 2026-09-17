"""Offline geocoder + map chart helpers."""

from __future__ import annotations

import pandas as pd
import plotly.express as px

from data_dumps.explorer_panels import charts as panel_charts
from data_dumps.geo import (
    attach_city_coords,
    attach_country_iso3,
    iso2_to_iso3,
    lookup_city_coords,
    normalize_place,
)


def test_normalize_and_lookup_common_cities():
    assert lookup_city_coords("Paris") == (48.8566, 2.3522)
    assert lookup_city_coords("Birmingham, UK") is not None
    assert lookup_city_coords("Greater Paris Metropolitan Region") is not None
    assert lookup_city_coords("Washington D.C.") is not None
    assert lookup_city_coords("New York City") is not None
    assert lookup_city_coords("South West, UK") is not None
    assert lookup_city_coords("") is None
    assert lookup_city_coords("(unknown)") is None
    assert normalize_place("  Paris, France  ") == "paris, france"


def test_attach_city_coords():
    df = pd.DataFrame({"city": ["Paris", "Atlantis", "London"], "trips": [3, 1, 2]})
    out = attach_city_coords(df)
    assert out.loc[0, "lat"] == 48.8566
    assert pd.isna(out.loc[1, "lat"])
    assert out.loc[2, "lon"] == -0.1278


def test_iso_country_mapping():
    assert iso2_to_iso3("FR") == "FRA"
    assert iso2_to_iso3("gb") == "GBR"
    assert iso2_to_iso3("ZZ") is None
    assert iso2_to_iso3("USA") == "USA"
    df = pd.DataFrame({"country": ["FR", "ZZ", "US"], "hours": [1.0, 2.0, 3.0]})
    out = attach_country_iso3(df)
    assert out.loc[0, "iso3"] == "FRA"
    assert pd.isna(out.loc[1, "iso3"])
    assert out.loc[2, "iso3"] == "USA"


def test_geo_bubble_map_and_choropleth_smoke():
    cities = attach_city_coords(
        pd.DataFrame({"city": ["Paris", "London"], "trips": [10, 4]})
    )
    fig = panel_charts.geo_bubble_map(
        px, cities, size="trips", hover_name="city", title="Trips"
    )
    assert fig.data
    # Avoid tile.openstreetmap.org (403 for Plotly UAs); use Carto.
    assert fig.layout.map.style == "carto-positron"
    countries = attach_country_iso3(
        pd.DataFrame({"country": ["FR", "GB"], "hours": [10.0, 4.0]})
    )
    fig2 = panel_charts.country_choropleth(
        px, countries, color="hours", hover_name="country", title="Hours"
    )
    assert fig2.data
    empty = panel_charts.geo_bubble_map(
        px,
        pd.DataFrame(columns=["city", "trips", "lat", "lon"]),
        size="trips",
        hover_name="city",
        title="Empty",
    )
    assert empty.layout.title.text == "Empty"
