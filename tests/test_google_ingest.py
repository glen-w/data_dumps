"""Google Takeout ingest smoke tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import duckdb

from data_dumps.google_queries import (
    FilterState,
    data_bounds,
    duration_vs_hour_scatter,
    filter_from_widgets,
    scoreboard,
    streak_stats,
    surfaces_monthly,
)
from data_dumps.ingest import main, pick_source
from data_dumps.sources.base import Source
from data_dumps.sources.google import GoogleSource, parse_calendar_ics

FORBIDDEN_COLUMNS = {
    "email",
    "ip",
    "ip_address",
    "ipaddress",
    "gaia",
    "gaia_id",
    "payment",
    "payment_method",
    "paymentmethodtitle",
    "billing",
    "address",
    "latitude",
    "longitude",
    "geodata",
    "altitude",
}


def make_mini_google_dir(tmp_path: Path) -> Path:
    """Build a tiny Takeout-shaped multipart folder for detect/load tests."""
    root = tmp_path / "google_export"
    root.mkdir(parents=True)

    takeout_files: dict[str, bytes] = {}

    ics = """BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
X-WR-CALNAME:work
BEGIN:VEVENT
DTSTART:20240201T100000Z
DTEND:20240201T110000Z
UID:evt-1@example
SUMMARY:Standup
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20250301T090000Z
DTEND:20250301T093000Z
UID:evt-2@example
SUMMARY:Focus
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR
"""
    takeout_files["Takeout/Calendar/work.ics"] = ics.encode()

    sleep_ics = """BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
X-WR-CALNAME:Sleep
BEGIN:VEVENT
DTSTART:20240202T220000Z
DTEND:20240203T060000Z
UID:sleep-1@example
SUMMARY:Sleep block
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR
"""
    takeout_files["Takeout/Calendar/Sleep.ics"] = sleep_ics.encode()

    nba_ics = """BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
X-WR-CALNAME:NBA 2022-23 Schedule
BEGIN:VEVENT
DTSTART:20240210T010000Z
DTEND:20240210T040000Z
UID:nba-1@example
SUMMARY:Game
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR
"""
    takeout_files["Takeout/Calendar/NBA.ics"] = nba_ics.encode()

    installs = [
        {
            "install": {
                "doc": {"documentType": "Android Apps", "title": "Sleep as Android"},
                "firstInstallationTime": "2024-04-06T20:26:11.321995Z",
                "deviceAttribute": {
                    "model": "Pixel 3a",
                    "manufacturer": "Google",
                },
                "lastUpdateTime": "2025-01-01T00:00:00Z",
            }
        },
        {
            "install": {
                "doc": {"documentType": "Android Apps", "title": "Old Calculator"},
                "firstInstallationTime": "2018-06-01T12:00:00Z",
                "deviceAttribute": {
                    "model": "Pixel 3a",
                    "manufacturer": "Google",
                },
                "lastUpdateTime": "2019-03-15T00:00:00Z",
            }
        },
    ]
    takeout_files["Takeout/Google Play Store/Installs.json"] = json.dumps(
        installs
    ).encode()
    takeout_files["Takeout/Google Play Store/Library.json"] = json.dumps(
        [
            {
                "libraryDoc": {
                    "doc": {"documentType": "Android Apps", "title": "Maps"},
                    "acquisitionTime": "2020-01-01T00:00:00Z",
                }
            }
        ]
    ).encode()
    takeout_files["Takeout/Google Play Store/Purchase History.json"] = json.dumps(
        [
            {
                "purchaseHistory": {
                    "invoicePrice": "A$4.99",
                    "paymentMethodTitle": "PayPal: secret@example.com",
                    "userCountry": "AU",
                    "doc": {"documentType": "In App Item", "title": "Coins"},
                    "purchaseTime": "2024-02-02T23:42:29.999Z",
                }
            }
        ]
    ).encode()
    takeout_files["Takeout/Google Play Store/Subscriptions.json"] = json.dumps(
        [
            {
                "subscription": {
                    "doc": {"documentType": "Subscription", "title": "Premium"},
                    "expirationDate": "2023-10-08T11:26:00.746Z",
                    "state": "Canceled",
                }
            }
        ]
    ).encode()

    reviews = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [2.32, 48.83]},
                "properties": {
                    "date": "2019-04-26T04:39:22Z",
                    "five_star_rating_published": 5,
                    "location": {
                        "address": "121 Rue du Château, 75014 Paris, France",
                        "country_code": "FR",
                        "name": "Hexagone Café",
                    },
                },
            }
        ],
    }
    takeout_files["Takeout/Maps (your places)/Reviews.json"] = json.dumps(
        reviews
    ).encode()
    saves = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [2.35, 48.88]},
                "properties": {
                    "date": "2024-03-15T08:24:19Z",
                    "location": {
                        "address": "1 bis Rue Ambroise Paré, Paris",
                        "country_code": "FR",
                        "name": "Parking Indigo",
                    },
                },
            }
        ],
    }
    takeout_files["Takeout/Maps (your places)/Saved Places.json"] = json.dumps(
        saves
    ).encode()

    takeout_files["Takeout/Saved/Want to go.csv"] = (
        "Title,Note,URL,Tags,Comment\n"
        "Mont-Valérien,,https://maps.google.com/place/x,,\n"
    ).encode()
    takeout_files["Takeout/Saved/Addresses.csv"] = (
        b"Title,Note,URL\nHome,secret street,https://maps.google.com/\n"
    )

    photo_meta = {
        "title": "IMG_1.JPG",
        "photoTakenTime": {"timestamp": "1700000000", "formatted": "14 Nov 2023"},
        "geoData": {"latitude": 48.86, "longitude": 2.36, "altitude": 36.0},
    }
    takeout_files[
        "Takeout/Google Photos/Photos from 2023/IMG_1.JPG.supplemental-metadata.json"
    ] = json.dumps(photo_meta).encode()
    takeout_files["Takeout/Google Photos/Photos from 2023/IMG_1.JPG"] = b"fake-jpeg"

    activity_html = """<!DOCTYPE html><html><body>
<div class="outer-cell mdl-cell">
<div class="mdl-grid">
<div class="header-cell mdl-cell mdl-cell--12-col">
<p class="mdl-typography--title">YouTube<br></p></div>
<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">
Liked&nbsp;<a href="https://www.youtube.com/watch?v=abc">Demo Video</a><br>
<a href="https://www.youtube.com/channel/x">Channel</a><br>
29 Jan 2021, 19:12:27 CEST<br></div>
<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1 mdl-typography--text-right"></div>
</div></div>
</body></html>"""
    takeout_files["Takeout/My Activity/YouTube/My Activity.html"] = (
        activity_html.encode()
    )

    tasks = {
        "kind": "tasks#taskLists",
        "items": [
            {
                "title": "To do",
                "items": [
                    {
                        "id": "t1",
                        "title": "Buy milk",
                        "status": "needsAction",
                        "created": "2024-01-01T10:00:00Z",
                    }
                ],
            }
        ],
    }
    takeout_files["Takeout/Tasks/Tasks.json"] = json.dumps(tasks).encode()

    # Forbidden / inventory-only
    takeout_files["Takeout/Access log activity/Activities.csv"] = (
        b"Gaia ID,IP Address\n1,1.2.3.4\n"
    )
    takeout_files["Takeout/Mail/All mail Including Spam and Trash.mbox"] = b"From: x\n"

    zip_a = root / "takeout-20260101T000000Z-1-001.zip"
    with zipfile.ZipFile(zip_a, "w") as zf:
        for name, data in takeout_files.items():
            zf.writestr(name, data)
    return root


def test_parse_calendar_ics_skips_epoch_and_missing_dtstart():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:19700101T000000Z
UID:habit@google.com
SUMMARY:Habit placeholder
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
UID:no-start@google.com
SUMMARY:Missing DTSTART
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20240201T100000Z
DTEND:20240201T110000Z
UID:ok@google.com
SUMMARY:Real event
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR
"""
    rows = parse_calendar_ics(ics, "habits.ics")
    assert len(rows) == 1
    assert rows[0]["uid"] == "ok@google.com"
    assert rows[0]["year"] == 2024


def test_detect_dir(tmp_path):
    root = make_mini_google_dir(tmp_path)
    source = GoogleSource()
    assert source.detect(root)
    assert list(root.glob("takeout-*.zip"))
    assert isinstance(source, Source)
    assert not source.detect(tmp_path / "missing")
    unrelated = tmp_path / "other.zip"
    with zipfile.ZipFile(unrelated, "w") as zf:
        zf.writestr("readme.txt", "nope")
    assert not source.detect(unrelated)
    empty_dir = tmp_path / "empty_folder"
    empty_dir.mkdir()
    assert not source.detect(empty_dir)


def test_pick_source(tmp_path):
    root = make_mini_google_dir(tmp_path)
    assert pick_source(root).name == "google"


def test_load_and_privacy(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    root = make_mini_google_dir(tmp_path)
    conn = duckdb.connect(str(tmp_path / "wh.duckdb"))
    GoogleSource().load(root, conn)

    cal = conn.execute("SELECT count(*) FROM google.calendar_events").fetchone()[0]
    assert cal == 4
    assert conn.execute("SELECT count(*) FROM google.play_installs").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM google.photos").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM google.maps_saves").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM google.activity").fetchone()[0] >= 1
    assert conn.execute("SELECT count(*) FROM google.tasks").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM google.saved_places").fetchone()[0] == 1

    # Addresses.csv not ingested into saved_places
    assert (
        conn.execute(
            "SELECT count(*) FROM google.saved_places WHERE title = 'Home'"
        ).fetchone()[0]
        == 0
    )

    # No geo / payment / email columns anywhere
    cols = {r[0].lower() for r in conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'google'
            """).fetchall()}
    assert not (cols & FORBIDDEN_COLUMNS)

    # Purchase email scrubbed from values
    purchase_blob = " ".join(
        str(x)
        for row in conn.execute("SELECT * FROM google.play_purchases").fetchall()
        for x in row
    )
    assert "secret@example.com" not in purchase_blob
    assert "PayPal" not in purchase_blob

    # Photo geo not stored
    photo_blob = " ".join(
        str(x)
        for row in conn.execute("SELECT * FROM google.photos").fetchall()
        for x in row
    )
    assert "48.86" not in photo_blob

    # Access log / mbox marked not ingested
    inv = conn.execute("""
        SELECT path, ingested, skip_reason FROM google.dump_inventory
        WHERE path LIKE 'Access log%' OR path LIKE 'Mail/%.mbox'
           OR path LIKE '%.JPG'
        """).fetchall()
    assert inv
    for _path, ingested, reason in inv:
        assert ingested is False
        assert reason

    bounds = data_bounds(conn)
    assert bounds["min_year"] <= 2024
    filters = filter_from_widgets(
        bounds, year_start=bounds["min_year"], year_end=bounds["max_year"]
    )
    board = scoreboard(conn, filters, compare_previous=True)
    assert "calendar_events" in board.columns
    assert int(board.iloc[0]["calendar_events"]) >= 1
    assert "calendar_hours" in board.columns
    assert "play_purchases" in board.columns
    assert "map_countries" in board.columns
    assert "photo_days" in board.columns

    conn.close()


def test_filter_year_swap_and_clamp():
    bounds = {"min_year": 2020, "max_year": 2025}
    f = filter_from_widgets(bounds, year_start=2024, year_end=2021)
    assert f.year_start == 2021
    assert f.year_end == 2024
    f2 = filter_from_widgets(bounds, year_start=2010, year_end=2030)
    assert f2.year_start == 2020
    assert f2.year_end == 2025
    f3 = filter_from_widgets(
        bounds, year_start=2022, year_end=2023, exclude_noise=False
    )
    assert f3.exclude_noise is False
    assert ("exclude_noise", "hide noise calendars") not in f3.chip_labels()


def test_exclude_noise_and_surfaces(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    root = make_mini_google_dir(tmp_path)
    conn = duckdb.connect(str(tmp_path / "noise.duckdb"))
    GoogleSource().load(root, conn)
    bounds = data_bounds(conn)
    noisy = filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        exclude_noise=True,
    )
    quiet = filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        exclude_noise=False,
    )
    n_noisy = int(scoreboard(conn, noisy).iloc[0]["calendar_events"])
    n_all = int(scoreboard(conn, quiet).iloc[0]["calendar_events"])
    assert n_all == 4
    assert n_noisy == 2

    locked = filter_from_widgets(
        bounds,
        year_start=bounds["min_year"],
        year_end=bounds["max_year"],
        calendar="Sleep",
        exclude_noise=True,
    )
    assert int(scoreboard(conn, locked).iloc[0]["calendar_events"]) == 1

    surfaces = surfaces_monthly(conn, noisy)
    assert not surfaces.empty
    assert {"year_month", "surface", "events"} <= set(surfaces.columns)
    assert surfaces["events"].sum() >= 1

    scatter = duration_vs_hour_scatter(conn, noisy)
    assert {"hour", "duration_hours", "calendar_name", "summary"} <= set(
        scatter.columns
    )
    assert not scatter.empty

    empty_streak = streak_stats(
        conn, FilterState(year_start=1990, year_end=1991, exclude_noise=True)
    )
    assert len(empty_streak) == 1
    assert int(empty_streak.iloc[0]["longest_streak_days"]) == 0

    conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    root = make_mini_google_dir(tmp_path)
    db = tmp_path / "cli.duckdb"
    assert main([str(root), "--db", str(db)]) == 0
