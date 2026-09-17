"""Offline city / country geocoding for explorer maps.

Trip GPS and street addresses are scrubbed at ingest. Dashboards that still
have city names or ISO country codes can plot coarse bubble / choropleth maps
using this static lookup — no network calls, no new dependencies.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

# Approximate city centroids (WGS84). Keys are normalized via ``normalize_place``.
CITY_COORDS: dict[str, tuple[float, float]] = {
    "amsterdam": (52.3676, 4.9041),
    "barcelona": (41.3874, 2.1686),
    "berlin": (52.5200, 13.4050),
    "birmingham": (52.4862, -1.8904),
    "bogota": (4.7110, -74.0721),
    "bristol": (51.4545, -2.5879),
    "cali": (3.4516, -76.5320),
    "krakow": (50.0647, 19.9450),
    "london": (51.5074, -0.1278),
    "los angeles": (34.0522, -118.2437),
    "miami": (25.7617, -80.1918),
    "new york": (40.7128, -74.0060),
    "paris": (48.8566, 2.3522),
    "san francisco": (37.7749, -122.4194),
    "singapore": (1.3521, 103.8198),
    "sydney": (-33.8688, 151.2093),
    "washington": (38.9072, -77.0369),
    "brierley hill": (52.4810, -2.1210),
    "rome": (41.9028, 12.4964),
    "milan": (45.4642, 9.1900),
    "madrid": (40.4168, -3.7038),
    "lisbon": (38.7223, -9.1393),
    "dublin": (53.3498, -6.2603),
    "brussels": (50.8503, 4.3517),
    "zurich": (47.3769, 8.5417),
    "geneva": (46.2044, 6.1432),
    "vienna": (48.2082, 16.3738),
    "prague": (50.0755, 14.4378),
    "warsaw": (52.2297, 21.0122),
    "stockholm": (59.3293, 18.0686),
    "copenhagen": (55.6761, 12.5683),
    "oslo": (59.9139, 10.7522),
    "helsinki": (60.1699, 24.9384),
    "athens": (37.9838, 23.7275),
    "istanbul": (41.0082, 28.9784),
    "dubai": (25.2048, 55.2708),
    "tokyo": (35.6762, 139.6503),
    "seoul": (37.5665, 126.9780),
    "hong kong": (22.3193, 114.1694),
    "shanghai": (31.2304, 121.4737),
    "beijing": (39.9042, 116.4074),
    "mumbai": (19.0760, 72.8777),
    "delhi": (28.7041, 77.1025),
    "bangalore": (12.9716, 77.5946),
    "mexico city": (19.4326, -99.1332),
    "sao paulo": (-23.5558, -46.6396),
    "buenos aires": (-34.6037, -58.3816),
    "santiago": (-33.4489, -70.6693),
    "lima": (-12.0464, -77.0428),
    "toronto": (43.6532, -79.3832),
    "montreal": (45.5017, -73.5673),
    "vancouver": (49.2827, -123.1207),
    "chicago": (41.8781, -87.6298),
    "boston": (42.3601, -71.0589),
    "seattle": (47.6062, -122.3321),
    "austin": (30.2672, -97.7431),
    "denver": (39.7392, -104.9903),
    "atlanta": (33.7490, -84.3880),
    "houston": (29.7604, -95.3698),
    "melbourne": (-37.8136, 144.9631),
    "auckland": (-36.8509, 174.7645),
    "cape town": (-33.9249, 18.4241),
    "johannesburg": (-26.2041, 28.0473),
    "cairo": (30.0444, 31.2357),
    "lagos": (6.5244, 3.3792),
    "nairobi": (-1.2921, 36.8219),
}

# Free-text place labels → CITY_COORDS key.
CITY_ALIASES: dict[str, str] = {
    "birmingham, uk": "birmingham",
    "new york city": "new york",
    "nyc": "new york",
    "washington d.c.": "washington",
    "washington d.c": "washington",
    "washington dc": "washington",
    "washington, d.c.": "washington",
    "washington, d.c": "washington",
    "los angeles, ca": "los angeles",
    "san francisco, ca": "san francisco",
    "greater paris metropolitan region": "paris",
    "paris area, france": "paris",
    "paris, france": "paris",
    "south west, uk": "bristol",
    "southwest, uk": "bristol",
    "kraków": "krakow",
    "cracow": "krakow",
    "bogotá": "bogota",
    "são paulo": "sao paulo",
    "mexico city, mx": "mexico city",
    "sydney, australia": "sydney",
    "london, uk": "london",
    "london, england": "london",
}

# ISO-3166-1 alpha-2 → alpha-3 (subset; unknowns stay unmapped).
ISO2_TO_ISO3: dict[str, str] = {
    "AD": "AND",
    "AE": "ARE",
    "AL": "ALB",
    "AR": "ARG",
    "AT": "AUT",
    "AU": "AUS",
    "BE": "BEL",
    "BG": "BGR",
    "BR": "BRA",
    "CA": "CAN",
    "CH": "CHE",
    "CL": "CHL",
    "CN": "CHN",
    "CO": "COL",
    "CY": "CYP",
    "CZ": "CZE",
    "DE": "DEU",
    "DK": "DNK",
    "EC": "ECU",
    "EE": "EST",
    "EG": "EGY",
    "ES": "ESP",
    "FI": "FIN",
    "FJ": "FJI",
    "FR": "FRA",
    "GB": "GBR",
    "GR": "GRC",
    "HK": "HKG",
    "HR": "HRV",
    "HU": "HUN",
    "IE": "IRL",
    "IL": "ISR",
    "IN": "IND",
    "IS": "ISL",
    "IT": "ITA",
    "JP": "JPN",
    "KE": "KEN",
    "KR": "KOR",
    "LT": "LTU",
    "LU": "LUX",
    "LV": "LVA",
    "MC": "MCO",
    "MD": "MDA",
    "MX": "MEX",
    "MY": "MYS",
    "NG": "NGA",
    "NL": "NLD",
    "NO": "NOR",
    "NZ": "NZL",
    "PE": "PER",
    "PH": "PHL",
    "PL": "POL",
    "PT": "PRT",
    "RO": "ROU",
    "RS": "SRB",
    "RU": "RUS",
    "SE": "SWE",
    "SG": "SGP",
    "SI": "SVN",
    "SK": "SVK",
    "TH": "THA",
    "TR": "TUR",
    "TW": "TWN",
    "UA": "UKR",
    "US": "USA",
    "UY": "URY",
    "VN": "VNM",
    "ZA": "ZAF",
}

_STRIP_SUFFIXES = (
    r"\bmetropolitan region\b",
    r"\bmetro area\b",
    r"\barea\b",
    r"\bregion\b",
    r"\bgreater\b",
)


def normalize_place(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    if not text or text in {"(unknown)", "unknown", "n/a", "na", "none", "null"}:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("&", " and ")
    text = re.sub(r"[/_|]+", " ", text)
    text = re.sub(r"[^\w\s,.-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.-")
    return text


def lookup_city_coords(place: Any) -> tuple[float, float] | None:
    """Return (lat, lon) for a free-text city label, or None if unknown."""
    norm = normalize_place(place)
    if not norm:
        return None

    candidates = [norm]
    if norm in CITY_ALIASES:
        candidates.append(CITY_ALIASES[norm])

    # Drop country/region suffixes: "paris, france" → "paris"
    if "," in norm:
        head = norm.split(",", 1)[0].strip()
        if head:
            candidates.append(head)
            if head in CITY_ALIASES:
                candidates.append(CITY_ALIASES[head])

    cleaned = norm
    for pat in _STRIP_SUFFIXES:
        cleaned = re.sub(pat, " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    if cleaned and cleaned != norm:
        candidates.append(cleaned)
        if "," in cleaned:
            candidates.append(cleaned.split(",", 1)[0].strip())

    seen: set[str] = set()
    for key in candidates:
        if not key or key in seen:
            continue
        seen.add(key)
        if key in CITY_COORDS:
            return CITY_COORDS[key]
        alias = CITY_ALIASES.get(key)
        if alias and alias in CITY_COORDS:
            return CITY_COORDS[alias]
    return None


def attach_city_coords(
    df: pd.DataFrame,
    *,
    place_col: str = "city",
    lat_col: str = "lat",
    lon_col: str = "lon",
) -> pd.DataFrame:
    """Copy ``df`` and add lat/lon columns from the static city gazetteer."""
    out = df.copy()
    if out.empty or place_col not in out.columns:
        out[lat_col] = pd.Series(dtype="float64")
        out[lon_col] = pd.Series(dtype="float64")
        return out
    coords = out[place_col].map(lookup_city_coords)
    out[lat_col] = coords.map(lambda c: c[0] if c else None)
    out[lon_col] = coords.map(lambda c: c[1] if c else None)
    return out


def iso2_to_iso3(code: Any) -> str | None:
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return None
    raw = str(code).strip().upper()
    if not raw or raw in {"ZZ", "XK", "NONE", "NULL", "N/A"}:
        return None
    if len(raw) == 3 and raw.isalpha():
        return raw
    if len(raw) == 2:
        return ISO2_TO_ISO3.get(raw)
    return None


def attach_country_iso3(
    df: pd.DataFrame,
    *,
    code_col: str = "country",
    iso3_col: str = "iso3",
) -> pd.DataFrame:
    out = df.copy()
    if out.empty or code_col not in out.columns:
        out[iso3_col] = pd.Series(dtype="object")
        return out
    out[iso3_col] = out[code_col].map(iso2_to_iso3)
    return out
