"""IP index: login and access-log addresses, not source-table columns."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import duckdb
import marimo as mo
import pandas as pd
import plotly.express as px

from data_dumps.explorer_panels.tools import render_tools_panel
from data_dumps.ip_inventory import (
    IpHit,
    IpLocation,
    _location_from_records,
    extract_amazon,
    extract_fallback,
    extract_google,
    extract_linkedin,
    extract_telegram,
    extract_twitter,
    extract_uber,
    hits_frame,
    inventory_frame,
    is_public,
    main,
    map_frame,
    normalize_ip,
    resolve_locations,
)
from data_dumps.sources.linkedin import LinkedInSource
from test_airbnb_ingest import make_mini_airbnb_zip
from test_linkedin_ingest import make_mini_linkedin_zip


def test_normalize_and_public_ranges() -> None:
    assert normalize_ip(" 8.8.8.8 ") == "8.8.8.8"
    assert normalize_ip("not an ip") is None
    assert is_public("8.8.8.8")
    assert not is_public("10.1.1.1")
    assert not is_public("203.0.113.1")
    assert not is_public("192.0.2.1")
    assert not is_public("198.51.100.8")
    assert not is_public("100.64.1.1")


def test_extractors_keep_provenance_and_skip_device_gps(tmp_path: Path) -> None:
    linkedin = tmp_path / "li.zip"
    with zipfile.ZipFile(linkedin, "w") as archive:
        archive.writestr(
            "Logins.csv",
            "Notes about this file\n"
            "Login Date,IP Address,User Agent,Login Type\n"
            "2024-06-01,203.0.113.9,Mozilla,PASSWORD\n"
            "2024-01-01,203.0.113.9,Mozilla,PASSWORD\n"
            "2024-03-01,8.8.8.8,Mozilla,PASSWORD\n"
            "2024-02-01,10.1.1.1,Mozilla,PASSWORD\n",
        )
    linkedin_hits = extract_linkedin(linkedin)
    grouped = hits_frame(
        linkedin_hits,
        resolve_locations(
            (hit.ip for hit in linkedin_hits),
            lambda _ip: IpLocation(city="should-not-apply"),
        ),
    )
    row = grouped[grouped["IP address"] == "203.0.113.9"].iloc[0]
    assert row["Events"] == 2
    assert row["First seen"] == "2024-01-01"
    assert row["Last seen"] == "2024-06-01"
    assert "PASSWORD" in row["Provenance / use"]
    assert row["City"] == ""
    assert pd.isna(row["Latitude"])

    twitter = tmp_path / "twitter"
    (twitter / "data").mkdir(parents=True)
    (twitter / "data" / "ip-audit.js").write_text(
        "window.YTD.ip_audit.part0 = ["
        '{"ipAudit": {"accountId": "1", "createdAt": "2023-01-01T00:00:00.000Z",'
        ' "loginIp": "203.0.113.1"}}]',
        encoding="utf-8",
    )
    tw = extract_twitter(twitter)
    assert tw[0].use == "login audit"
    assert tw[0].ip == "203.0.113.1"
    assert tw[0].first == "2023-01-01T00:00:00.000Z"

    google = tmp_path / "google" / "takeout-1.zip"
    google.parent.mkdir()
    with zipfile.ZipFile(google, "w") as archive:
        archive.writestr(
            "Takeout/Access log activity/Activities.csv",
            "Gaia ID,IP Address\n1,203.0.113.50\n",
        )
    ghits = extract_google(google.parent)
    assert ghits[0].use == "access log"
    assert ghits[0].ip == "203.0.113.50"

    telegram = tmp_path / "telegram"
    telegram.mkdir()
    (telegram / "result.json").write_text(
        json.dumps(
            {
                "sessions": {
                    "list": [
                        {
                            "application_name": "Telegram macOS",
                            "created": "2024-01-01T12:00:00",
                            "last_active": "2024-06-01T12:00:00",
                            "last_ip": "203.0.113.9",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    thits = extract_telegram(telegram)
    assert thits[0].use == "session · Telegram macOS"
    assert thits[0].ip == "203.0.113.9"
    assert thits[0].first == "2024-01-01T12:00:00"
    assert thits[0].last == "2024-06-01T12:00:00"

    uber = tmp_path / "uber.zip"
    with zipfile.ZipFile(uber, "w") as archive:
        archive.writestr(
            "Rider/rider_app_analytics-0.csv",
            "Event Time (UTC),IP Address,Device ID,Latitude,Longitude\n"
            "2026-01-01 00:00:00,1.2.3.4,dev-1,48.8,2.3\n",
        )
    uhit = extract_uber(uber)[0]
    assert uhit.ip == "1.2.3.4"
    assert uhit.use == "app analytics"
    assert "48.8" not in uhit.use
    assert uhit.first is not None and "2026-01-01" in uhit.first

    amazon = tmp_path / "amazon.zip"
    with zipfile.ZipFile(amazon, "w") as archive:
        archive.writestr(
            "Your Fire TV Device & Setup/Device Registration.csv",
            "Device Model,First Time Registered,IP Address,Last Time Registered,"
            "Local Time Offset\n"
            "Echo Dot,2024-01-01T09:00:00Z,203.0.113.50,2024-02-01T09:00:00Z,"
            "Not Available\n",
        )
    ahit = extract_amazon(amazon)[0]
    assert ahit.ip == "203.0.113.50"
    assert ahit.use == "device registration · Echo Dot"
    assert ahit.first == "2024-01-01T09:00:00Z"
    assert ahit.last == "2024-02-01T09:00:00Z"


def test_fallback_skips_conversation_text(tmp_path: Path) -> None:
    archive_path = tmp_path / "chatgpt.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("user.json", json.dumps({"login_ip": "8.8.8.8"}))
        archive.writestr(
            "conversations-001.json",
            json.dumps(
                {
                    "message": {"login_ip": "9.9.9.9", "text": "see 1.1.1.1"},
                }
            ),
        )
    hits = extract_fallback(archive_path, "ChatGPT")
    ips = {hit.ip for hit in hits}
    assert ips == {"8.8.8.8"}
    assert hits[0].use == "user.json · login_ip"

    airbnb = make_mini_airbnb_zip(tmp_path)
    found = {hit.ip for hit in extract_fallback(airbnb, "Airbnb")}
    assert "1.2.3.4" in found

    duo = tmp_path / "duo.zip"
    with zipfile.ZipFile(duo, "w") as archive:
        archive.writestr("ip-addresses.csv", "ip\n198.51.100.8\n")
    duo_hits = extract_fallback(duo, "Duolingo")
    assert duo_hits[0].ip == "198.51.100.8"
    assert duo_hits[0].use == "ip-addresses.csv"


def test_lookup_skips_documentation_ranges() -> None:
    seen: list[str] = []

    def resolve(ip: str) -> IpLocation:
        seen.append(ip)
        return IpLocation(
            city="Testville",
            region="Test",
            country="Testland",
            isp="Test ISP",
            asn="AS1",
            lat=10.0,
            lon=20.0,
        )

    locations = resolve_locations(["8.8.8.8", "203.0.113.1", "10.1.1.1"], resolve)
    assert seen == ["8.8.8.8"]
    assert locations["8.8.8.8"].city == "Testville"
    assert locations["203.0.113.1"].city == ""
    assert locations["203.0.113.1"].lat is None
    frame = hits_frame(
        [IpHit("LinkedIn", "account login", ip) for ip in ("8.8.8.8", "203.0.113.1")],
        locations,
    )
    mapped = map_frame(frame)
    assert list(mapped["Place"]) == ["Testville, Testland"]
    assert int(mapped.iloc[0]["Events"]) == 1


def test_inventory_cache_panel_and_ingest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DUMPS_SKIP_GLODA", "1")
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    linkedin = tmp_path / "linkedin" / "Complete_export.zip"
    linkedin.parent.mkdir()
    with zipfile.ZipFile(linkedin, "w") as archive:
        archive.writestr(
            "Logins.csv",
            "Login Date,IP Address,User Agent,Login Type\n"
            "2024-01-01,203.0.113.9,Mozilla,PASSWORD\n"
            "2024-03-01,8.8.8.8,Mozilla,PASSWORD\n",
        )
    twitter = tmp_path / "twitter" / "data"
    twitter.mkdir(parents=True)
    (twitter / "account.js").write_text(
        'window.YTD.account.part0 = [{"account": {"username": "me"}}]',
        encoding="utf-8",
    )
    (twitter / "ip-audit.js").write_text(
        "window.YTD.ip_audit.part0 = ["
        '{"ipAudit": {"createdAt": "2023-01-01T00:00:00.000Z",'
        ' "loginIp": "203.0.113.1"}}]',
        encoding="utf-8",
    )

    calls = {"n": 0}
    from data_dumps import ip_inventory

    real_scan = ip_inventory.scan_exports

    def wrapped(root: Path | None = None):
        calls["n"] += 1
        return real_scan(root)

    monkeypatch.setattr(ip_inventory, "scan_exports", wrapped)
    conn = duckdb.connect()
    frame, note = inventory_frame(conn, force=True)
    assert "203.0.113.9" in set(frame["IP address"])
    assert "203.0.113.1" in set(frame["IP address"])
    assert "8.8.8.8" in set(frame["IP address"])
    assert "warehouse/geoip" in note
    assert calls["n"] == 1
    again, _note = inventory_frame(conn)
    assert calls["n"] == 1
    assert len(again) == len(frame)

    seen: list[str] = []

    def resolve(ip: str) -> IpLocation:
        seen.append(ip)
        return IpLocation(city="Testville", country="Testland", lat=1.0, lon=2.0)

    looked, _note = inventory_frame(conn, force=True, resolve=resolve)
    public = looked[looked["IP address"] == "8.8.8.8"].iloc[0]
    private = looked[looked["IP address"] == "203.0.113.1"].iloc[0]
    assert public["City"] == "Testville"
    assert private["City"] == ""
    assert "203.0.113.1" not in seen
    assert "203.0.113.9" not in seen

    panel = render_tools_panel(mo=mo, px=px, conn=conn)
    assert panel is not None

    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "ingest-root"))
    zip_path = make_mini_linkedin_zip(tmp_path)
    loaded = duckdb.connect()
    LinkedInSource().load(zip_path, loaded)
    cols = {
        row[0].lower()
        for row in loaded.execute(
            "SELECT column_name FROM information_schema.columns"
        ).fetchall()
    }
    assert "ip_address" not in cols
    assert "ip" not in cols


def test_cli_prints_counts_only(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    monkeypatch.setenv("DATA_DUMPS_SKIP_GLODA", "1")
    db = tmp_path / "warehouse" / "catalog.duckdb"
    db.parent.mkdir()
    duckdb.connect(str(db)).close()
    linkedin = tmp_path / "linkedin" / "Complete_export.zip"
    linkedin.parent.mkdir()
    with zipfile.ZipFile(linkedin, "w") as archive:
        archive.writestr(
            "Logins.csv",
            "Login Date,IP Address,User Agent,Login Type\n"
            "2024-01-01,203.0.113.9,Mozilla,PASSWORD\n",
        )
    assert main(["--db", str(db), "--refresh"]) == 0
    out = capsys.readouterr().out
    assert "203.0.113.9" not in out
    assert "1 rows" in out
    assert "LinkedIn" in out


def test_account_creation_and_ring_fallback(tmp_path: Path) -> None:
    twitter = tmp_path / "twitter"
    (twitter / "data").mkdir(parents=True)
    (twitter / "data" / "account-creation-ip.js").write_text(
        "window.YTD.account_creation_ip.part0 = ["
        '{"accountCreationIp": {"userCreationIp": "8.8.4.4"}}]',
        encoding="utf-8",
    )
    created = extract_twitter(twitter)
    assert len(created) == 1
    assert created[0].use == "account creation"
    assert created[0].ip == "8.8.4.4"

    ring = tmp_path / "ring.zip"
    with zipfile.ZipFile(ring, "w") as archive:
        archive.writestr(
            "datarequest/RingDeviceRegistry/Device.csv",
            "device_name,ip_address\nCam,203.0.113.7\n",
        )
    hits = extract_fallback(ring, "Ring")
    assert hits[0].ip == "203.0.113.7"
    assert hits[0].use == "Device.csv"
    assert hits[0].service == "Ring"


def test_location_record_shape() -> None:
    loc = _location_from_records(
        {
            "city": {"names": {"en": "London"}},
            "subdivisions": [{"names": {"en": "England"}}],
            "country": {"names": {"en": "United Kingdom"}},
            "location": {"latitude": 51.5, "longitude": -0.1},
        },
        {
            "autonomous_system_number": 15169,
            "autonomous_system_organization": "Example ISP",
        },
    )
    assert loc.city == "London"
    assert loc.region == "England"
    assert loc.country == "United Kingdom"
    assert loc.isp == "Example ISP"
    assert loc.asn == "AS15169"
    assert loc.lat == 51.5
    assert loc.lon == -0.1
    assert _location_from_records(None, None) == IpLocation()


def test_cache_busts_when_geoip_file_appears(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    monkeypatch.setenv("DATA_DUMPS_SKIP_GLODA", "1")
    linkedin = tmp_path / "linkedin" / "Complete_export.zip"
    linkedin.parent.mkdir()
    with zipfile.ZipFile(linkedin, "w") as archive:
        archive.writestr(
            "Logins.csv",
            "Login Date,IP Address,User Agent,Login Type\n"
            "2024-01-01,8.8.8.8,Mozilla,PASSWORD\n",
        )
    conn = duckdb.connect()
    inventory_frame(conn, force=True)

    from data_dumps import ip_inventory

    calls = {"n": 0}
    real_scan = ip_inventory.scan_exports

    def wrapped(root: Path | None = None):
        calls["n"] += 1
        return real_scan(root)

    monkeypatch.setattr(ip_inventory, "scan_exports", wrapped)
    inventory_frame(conn)
    assert calls["n"] == 0
    geo = tmp_path / "warehouse" / "geoip"
    geo.mkdir(parents=True)
    (geo / "GeoLite2-City.mmdb").write_bytes(b"not-a-database")
    inventory_frame(conn)
    assert calls["n"] == 1


def test_cli_missing_warehouse(tmp_path: Path, capsys) -> None:
    assert main(["--db", str(tmp_path / "missing.duckdb")]) == 1
    err = capsys.readouterr().err
    assert "no warehouse" in err
    assert "8.8.8.8" not in err
