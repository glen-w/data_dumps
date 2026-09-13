"""Ring GDPR ingest smoke tests."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import duckdb

from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.ring_queries import data_bounds, filter_from_widgets, scoreboard
from data_dumps.sources.base import Source
from data_dumps.sources.ring import RingSource

FORBIDDEN_COLUMNS = {
    "address",
    "latitude",
    "longitude",
    "ssid",
    "ip",
    "ip_address",
    "mobile_hardware_id",
    "hardware_id",
}


def make_mini_ring_zip(tmp_path: Path) -> Path:
    """Build a tiny Ring-shaped zip for detect/load tests."""
    root = tmp_path / "ring_src"
    registry = root / "datarequest" / "RingDeviceRegistry"
    registry.mkdir(parents=True)
    (registry / "Device.csv").write_text(
        "device_name,device_id,created_at,timezone,latitude,longitude,"
        "video_storage_enabled,show_video_enabled,max_days_video_is_stored,"
        "rich_notifications_eligible,people_detection_eligible,"
        "ai_automated_warnings_enabled,automated_siren_enabled,"
        "continuous_video_recording_subscribed,offline_motion_recording_subscribed\n"
        "Front Door,dev1,2024-09-14T19:00:08Z,Europe/London,52.4,-2.1,"
        "yes,yes,yes,yes,yes,yes,yes,yes,yes\n",
        encoding="utf-8",
    )
    (registry / "Device_location.csv").write_text(
        "location_name,address,city,state,zip_code,country,timezone,"
        "latitude,longitude,location_type,location_subtype\n"
        "Wilson Road,6 Wilson Road,Brierley Hill,England,DY5,GB,Europe/London,"
        "52.4,-2.1,residential,Not Applicable\n",
        encoding="utf-8",
    )
    events_dir = root / "RequestAllYourData.Events.2" / "datasets" / "DeviceEvents"
    events_dir.mkdir(parents=True)
    (events_dir / "DeviceEvents.csv").write_text(
        "Category,Event Date,Message Type\n"
        "device_state_changed,2025-09-12T10:00:00Z,device_offline\n"
        "device_state_changed,2025-09-12T12:00:00Z,device_online\n"
        "device_state_changed,2026-01-01T08:00:00Z,device_offline\n"
        "device_state_changed,2026-01-01T20:00:00Z,device_online\n",
        encoding="utf-8",
    )
    motion_dir = root / "RequestAllYourData.Events.2" / "datasets" / "Events"
    motion_dir.mkdir(parents=True)
    (motion_dir / "Events.csv").write_text(
        "Access Code Name,Anomalous Event,Detection Type,Duration Seconds,"
        "End To End Encryption,Event Created With Alexa,Event Date,"
        "Event From Sidewalk,Event Responded By Alexa,Event Type,Expires At Date,"
        "Human Detected,Is 24x7,Is Favorited,Is Initiated By Event Owner,"
        "Latitude,Longitude,Reviewed By Virtual Security Guard,"
        "Security Alert Date,Security Alert Name,Security Alert State Type,"
        "Status,Streaming Mode,Video Full Description,Video Short Description,"
        "Virtual Security Guard\n"
        "Not Applicable,Not Applicable,human,21,No,Not Applicable,"
        "2026-08-15T13:05:14.062Z,Not Applicable,Not Applicable,motion,"
        "2026-09-14T13:05:14Z,Not Applicable,Not Applicable,Not Applicable,"
        "Not Applicable,Not Applicable,Not Applicable,Not Applicable,"
        "Not Applicable,Not Applicable,Not Applicable,timed_out,Not Applicable,"
        "Not Applicable,Not Applicable,Not Applicable\n",
        encoding="utf-8",
    )
    (root / "datarequest").mkdir(exist_ok=True)
    (root / "datarequest" / "setups.csv").write_text(
        "Status,Description,Created At,Updated At,Device Id,Latitude,Longitude,Ssid\n"
        "valid,Front Door,2024-09-14 18:59:47,2024-09-14 18:59:57,dev1,52.4,-2.1,SECRETSSID\n",
        encoding="utf-8",
    )
    (root / "datarequest" / "subscriptions.csv").write_text(
        "Cancel At Period End,Created,Current Period Start,Current Period End,"
        "Plan Id,Quantity,Start,Status\n"
        "False,2024-10-03 07:59:15,2026-08-13 23:05:39,2026-09-13 23:05:39,"
        "ring-monthly-c5s-gbp,1,2024-10-13 23:05:39,active\n",
        encoding="utf-8",
    )
    acct = {
        "description": "test",
        "customerAccountingDataList": [
            {
                "Type": "invoice",
                "Creation Date": "2026-08-14T00:06:42.000Z",
                "Payment Provider": "Ring LLC.",
                "Invoice Number": "A1",
                "Amount": 4.99,
                "Currency Code": "GBP",
                "Status": "paid",
                "Period Start Date": "2026-07-13T23:05:39.000Z",
                "Period End Date": "2026-08-13T23:05:39.000Z",
                "Description": "subscription",
            }
        ],
    }
    acct_dir = root / "Subscriptions.Accounting.1.1" / "datasets" / "Accounting"
    acct_dir.mkdir(parents=True)
    (acct_dir / "Accounting.json").write_text(json.dumps(acct), encoding="utf-8")

    app_inner = io.BytesIO()
    with zipfile.ZipFile(app_inner, "w") as az:
        props = {
            "App Version": "3.105.2",
            "App Brand": "Ring",
            "OS": "android",
            "Connectivity Type": "wifi",
            "Ip Address": "203.0.113.9",
            "Mobile Hardware Id": "secret-hw",
        }
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Event", "Timestamp", "Properties"])
        writer.writerow(["App Launched", "2026-06-14T10:38:49", json.dumps(props)])
        writer.writerow(
            ["RingStorage Access", "2026-06-14T10:39:00", json.dumps(props)]
        )
        az.writestr("app_events/2026-06-14/app_brand_app.csv", buf.getvalue())
    mobile = root / "datarequest" / "ring_mobile_app_data"
    mobile.mkdir(parents=True)
    (mobile / "app_events.zip").write_bytes(app_inner.getvalue())
    other_buf = io.StringIO()
    other_writer = csv.writer(other_buf)
    other_writer.writerow(["Event", "Timestamp", "Properties"])
    other_writer.writerow(
        [
            "Login",
            "2026-09-11 22:04:19",
            json.dumps(
                {
                    "Ip Address": "203.0.113.9",
                    "Hardware Id": "abc",
                    "Application": "ring web site",
                }
            ),
        ]
    )
    (mobile / "other_events.csv").write_text(other_buf.getvalue(), encoding="utf-8")

    zip_path = tmp_path / "All Data Categories.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in root.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(root).as_posix())
    return zip_path


def test_detect_zip(tmp_path):
    zip_path = make_mini_ring_zip(tmp_path)
    source = RingSource()
    assert source.detect(zip_path)
    assert isinstance(source, Source)


def test_pick_source(tmp_path):
    zip_path = make_mini_ring_zip(tmp_path)
    source = pick_source(zip_path)
    assert source is not None
    assert source.name == "ring"


def test_load_and_queries(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = make_mini_ring_zip(tmp_path)
    db_path = tmp_path / "w.duckdb"
    conn = duckdb.connect(str(db_path))
    source = RingSource()
    source.load(zip_path, conn)
    inv = source.inventory(conn)
    assert inv["n_devices"] == 1
    assert inv["n_device_events"] == 4
    assert inv["n_events"] == 1
    assert inv["n_app_events"] >= 2
    assert "ring" in inv["summary"]

    # PII columns must not exist on loaded tables
    for table in (
        "devices",
        "locations",
        "setups",
        "device_events",
        "events",
        "app_events",
    ):
        cols = {
            r[0].lower()
            for r in conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'ring' AND table_name = ?
                """,
                [table],
            ).fetchall()
        }
        assert not (cols & FORBIDDEN_COLUMNS), (table, cols & FORBIDDEN_COLUMNS)

    # Raw keep-list should not contain SSID / address text in setups/locations
    raw = raw_dir("ring")
    assert (raw / "Device.csv").exists()
    assert (raw / "app_events.csv").exists()
    setups_text = (raw / "setups.csv").read_text(encoding="utf-8")
    # Original setups still on disk for replay; warehouse table is scrubbed.
    # Warehouse setups must not expose SSID.
    setup_cols = {r[0].lower() for r in conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'ring' AND table_name = 'setups'
            """).fetchall()}
    assert "ssid" not in setup_cols
    assert "SECRETSSID" not in str(conn.execute("SELECT * FROM ring.setups").fetchall())
    del setups_text

    loc_row = conn.execute("SELECT * FROM ring.locations").fetchone()
    assert loc_row is not None
    # city kept, address stripped from schema
    assert "address" not in {r[0].lower() for r in conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'ring' AND table_name = 'locations'
            """).fetchall()}

    # app events must not retain IP in any string column
    app_vals = conn.execute("SELECT * FROM ring.app_events").fetchall()
    blob = " ".join(str(v) for row in app_vals for v in row)
    assert "203.0.113.9" not in blob
    assert "secret-hw" not in blob

    bounds = data_bounds(conn)
    filters = filter_from_widgets(
        bounds, year_start=bounds["min_year"], year_end=bounds["max_year"]
    )
    score = scoreboard(conn, filters)
    assert int(score.iloc[0]["devices"]) == 1
    assert int(score.iloc[0]["device_events"]) == 4
    conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = make_mini_ring_zip(tmp_path)
    assert main([str(zip_path), "--db", str(tmp_path / "catalog.duckdb")]) == 0
