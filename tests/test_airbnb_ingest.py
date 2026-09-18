"""Airbnb personal-data HTML ingest smoke tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb

from data_dumps.airbnb_queries import (
    data_bounds,
    filter_from_widgets,
    scoreboard,
    search_map_points,
    streak_stats,
    weekday_heatmap,
)
from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.airbnb import AirbnbSource

FORBIDDEN_COLUMNS = {
    "email",
    "phone",
    "number",
    "ip",
    "initial_ip",
    "most_recent_ip",
    "street",
    "formatted_address",
    "raw_location",
    "message",
    "birthdate",
    "facebook_id",
    "verification_code",
    "card_number",
}


def _html_page(
    title: str, sections: list[tuple[str, list[str], list[list[str]]]]
) -> str:
    parts = [
        "<!doctype html><html><body>",
        f"<h1>{title}</h1>",
    ]
    for heading, headers, rows in sections:
        parts.append(f"<h2>{heading}</h2>")
        parts.append('<table data-toggle="table"><thead><tr>')
        for h in headers:
            parts.append(f"<th>{h}</th>")
        parts.append("</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>")
            for cell in row:
                parts.append(f"<td><pre>{cell}</pre></td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
    parts.append("</body></html>")
    return "\n".join(parts)


def make_mini_airbnb_zip(tmp_path: Path) -> Path:
    root = tmp_path / "airbnb_src" / "Airbnb_data_request_01Jan2024_GMT"
    html = root / "html"
    html.mkdir(parents=True)
    (root / "readme.html").write_text("<html><body>Airbnb User Data</body></html>")

    (html / "profile_information.html").write_text(
        _html_page(
            "Profile",
            [
                (
                    "User",
                    ["key", "value"],
                    [
                        ["id", "999001"],
                        ["email", "secret@example.com"],
                        ["firstName", "Ada"],
                        ["lastName", "Lovelace"],
                        ["initialIp", "1.2.3.4"],
                        ["birthdate", "1815-12-10"],
                        ["createdAt", "2015-01-01T12:00:00.000Z"],
                        ["market", "Paris"],
                        ["preferredLocale", "en"],
                        ["nativeCurrency", "EUR"],
                    ],
                ),
                (
                    "Phone Numbers",
                    ["Number", "Country"],
                    [["33600000000", "FR"]],
                ),
                (
                    "User Shipping Addresses",
                    ["Street", "City", "Lat", "Lng"],
                    [["1 Secret St", "Paris", "48.85", "2.35"]],
                ),
            ],
        ),
        encoding="utf-8",
    )

    (html / "reservations.html").write_text(
        _html_page(
            "Reservations",
            [
                (
                    "Booking Sessions",
                    ["Listing Owner Profile Url", "Created At"],
                    [
                        [
                            "https://www.airbnb.com/users/show/999001",
                            "2019-01-01T00:00:00.000Z",
                        ]
                    ],
                ),
                (
                    "Reservations",
                    [
                        "Confirmation Code",
                        "Host Currency",
                        "Guest Profile Url",
                        "Number Of Guests",
                        "Created At",
                        "Hosting Url",
                        "Nights",
                        "Host Profile Url",
                        "Start Date",
                        "Status",
                        "Host Vat Country",
                        "Canceled At",
                        "Guest Currency",
                        "Guest Vat Country",
                        "Message",
                        "Is Bringing Pets",
                    ],
                    [
                        [
                            "GUEST01",
                            "EUR",
                            "https://www.airbnb.com/users/show/999001",
                            "2",
                            "2023-06-01T10:00:00.000Z",
                            "https://www.airbnb.com/rooms/111",
                            "3",
                            "https://www.airbnb.com/users/show/555",
                            "2023-07-10",
                            "accepted",
                            "FR",
                            "",
                            "EUR",
                            "",
                            "Please hide this note",
                            "false",
                        ],
                        [
                            "HOST01",
                            "EUR",
                            "https://www.airbnb.com/users/show/777",
                            "1",
                            "2024-02-01T10:00:00.000Z",
                            "https://www.airbnb.com/rooms/222",
                            "2",
                            "https://www.airbnb.com/users/show/999001",
                            "2024-03-01",
                            "accepted",
                            "FR",
                            "",
                            "",
                            "",
                            "",
                            "",
                        ],
                        [
                            "CANCEL1",
                            "EUR",
                            "https://www.airbnb.com/users/show/999001",
                            "1",
                            "2022-01-01T10:00:00.000Z",
                            "https://www.airbnb.com/rooms/333",
                            "1",
                            "https://www.airbnb.com/users/show/555",
                            "2022-02-01",
                            "cancelled",
                            "IE",
                            "2022-01-15T10:00:00.000Z",
                            "EUR",
                            "",
                            "",
                            "",
                        ],
                    ],
                ),
            ],
        ),
        encoding="utf-8",
    )

    (html / "search_history.html").write_text(
        _html_page(
            "Search History",
            [
                (
                    "Service Data",
                    [
                        "Time of Search",
                        "Number of Nights",
                        "Number of Guests",
                        "Search Location Latitude",
                        "Country",
                        "Amenities",
                        "Check Out Date",
                        "Check In Date",
                        "City",
                        "Raw Location",
                        "Search Location Longitude",
                        "State",
                    ],
                    [
                        [
                            "2023-10-25 09:39:12",
                            "5",
                            "1",
                            "48.86",
                            "France",
                            "[]",
                            "2023-11-14",
                            "2023-11-09",
                            "Paris",
                            "1 Secret Street, Paris",
                            "2.35",
                            "Île-de-France",
                        ],
                        [
                            "2024-01-10 18:00:00",
                            "3",
                            "2",
                            "51.51",
                            "United Kingdom",
                            "[]",
                            "2024-02-04",
                            "2024-02-01",
                            "London",
                            "London, UK",
                            "-0.12",
                            "England",
                        ],
                    ],
                ),
            ],
        ),
        encoding="utf-8",
    )

    review_provided = (
        '{"reviewId":1001,"reviewerId":999001,"revieweeId":555,'
        '"reviewerRole":"GUEST","revieweeRole":"HOST","rating":5,'
        '"comment":"Great stay","commentLanguage":"en",'
        '"entityId":111,"bookableId":9001,"entityType":"HOME",'
        '"submittedAt":"2023-07-15T12:00:00.000Z",'
        '"isEntityRecommended":true}'
    )
    review_received = (
        '{"reviewId":1002,"reviewerId":777,"revieweeId":999001,'
        '"reviewerRole":"GUEST","revieweeRole":"HOST","rating":5,'
        '"comment":"Nice host","entityId":222,"bookableId":9002,'
        '"entityType":"HOME","submittedAt":"2024-03-05T12:00:00.000Z",'
        '"isEntityRecommended":true}'
    )
    (html / "reviews.html").write_text(
        _html_page(
            "Reviews",
            [
                (
                    "Reviews Provided",
                    ["Review Category Ratings", "Review", "Review Category Tags"],
                    [["", review_provided, ""]],
                ),
                (
                    "Reviews Received",
                    ["Review Category Ratings", "Review", "Review Category Tags"],
                    [["", review_received, ""]],
                ),
            ],
        ),
        encoding="utf-8",
    )

    (html / "wishlists.html").write_text(
        _html_page(
            "Wishlists",
            [
                (
                    "Wishlist Data",
                    ["Wishlist Id", "Name", "Num Guests"],
                    [["10", "Dream Homes", "2"]],
                ),
                (
                    "Wishlist Data",
                    ["Wishlist Item Id", "Pdp Type", "Wishlist Id", "Pdp Id"],
                    [["1", "HOME", "10", "55555"]],
                ),
            ],
        ),
        encoding="utf-8",
    )

    # Forbidden files present in export but must not be copied / loaded.
    (html / "activity_log.html").write_text(
        _html_page(
            "Activity",
            [
                (
                    "Session Activities",
                    ["IP", "Location"],
                    [["9.9.9.9", "Paris"]],
                )
            ],
        ),
        encoding="utf-8",
    )
    (html / "payment_instruments.html").write_text(
        "<html><body>card 4111</body></html>", encoding="utf-8"
    )

    zip_path = tmp_path / "airbnb_mini.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in root.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(root.parent).as_posix())
    return zip_path


def test_detect_yes_and_no(tmp_path: Path):
    z = make_mini_airbnb_zip(tmp_path)
    src = AirbnbSource()
    assert src.detect(z) is True
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("readme.txt", "nope")
    assert src.detect(other) is False
    assert pick_source(z).name == "airbnb"


def test_load_counts_and_privacy(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    z = make_mini_airbnb_zip(tmp_path)
    conn = duckdb.connect(str(tmp_path / "wh.duckdb"))
    AirbnbSource().load(z, conn)

    assert conn.execute("SELECT count(*) FROM airbnb.reservations").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM airbnb.searches").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM airbnb.reviews").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM airbnb.wishlists").fetchone()[0] == 1
    assert (
        conn.execute("SELECT account_id FROM airbnb.account").fetchone()[0] == "999001"
    )

    roles = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT confirmation_code, role FROM airbnb.reservations"
        ).fetchall()
    }
    assert roles["GUEST01"] == "guest"
    assert roles["HOST01"] == "host"

    # Message / raw location / email never persisted as columns or values.
    for table in ("account", "reservations", "searches", "reviews", "wishlists"):
        cols = {
            c[0].lower()
            for c in conn.execute(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = 'airbnb' AND table_name = '{table}'"
            ).fetchall()
        }
        assert not (cols & FORBIDDEN_COLUMNS), cols & FORBIDDEN_COLUMNS

    blob = " ".join(
        str(v)
        for row in conn.execute("SELECT * FROM airbnb.reservations").fetchall()
        for v in row
    )
    assert "Please hide this note" not in blob
    assert "secret@example.com" not in blob
    assert "1 Secret Street" not in blob
    assert "1.2.3.4" not in blob

    raw = raw_dir("airbnb")
    names = {p.name for p in raw.iterdir() if p.is_file()}
    assert "reservations.html" in names
    assert "search_history.html" in names
    assert "profile_information.html" not in names
    assert "activity_log.html" not in names
    assert "payment_instruments.html" not in names

    inv = AirbnbSource().inventory(conn)
    assert "reservations" in inv["summary"]

    bounds = data_bounds(conn)
    assert bounds["min_year"] <= 2022
    assert "Paris" in (bounds.get("places") or [])
    assert "guest" in (bounds.get("roles") or [])
    assert "accepted" in (bounds.get("statuses") or [])
    f = filter_from_widgets(bounds, year_start=2022, year_end=2024, place="Paris")
    assert f.place == "Paris"
    assert not scoreboard(conn, f).empty
    assert not streak_stats(conn, f).empty
    assert not weekday_heatmap(conn, f).empty
    mp = search_map_points(conn, f)
    assert len(mp) >= 1
    assert mp["lat"].notna().all()

    from data_dumps.compare_queries import entity_options, list_available_series
    from data_dumps.correlation_queries import list_available_metrics

    series_ids = {s.id for s in list_available_series(conn)}
    assert {
        "airbnb_reservations",
        "airbnb_nights",
        "airbnb_searches",
        "airbnb_place",
    } <= series_ids
    metric_ids = {m.id for m in list_available_metrics(conn)}
    assert {
        "airbnb_reservations",
        "airbnb_nights",
        "airbnb_searches",
    } <= metric_ids
    opts = entity_options(conn, "airbnb_place")
    assert any(o["value"] == "Paris" for o in opts)

    conn.close()


def test_cli_ingest(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    z = make_mini_airbnb_zip(tmp_path)
    db = tmp_path / "cli.duckdb"
    assert main([str(z), "--db", str(db)]) == 0
    conn = duckdb.connect(str(db), read_only=True)
    assert conn.execute("SELECT count(*) FROM airbnb.searches").fetchone()[0] == 2
    conn.close()
