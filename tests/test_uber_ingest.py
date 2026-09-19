"""Uber GDPR ingest smoke tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb

from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.base import Source
from data_dumps.sources.uber import UberSource
from data_dumps.uber_queries import (
    calendar_daily_trips,
    city_rank_bump,
    comeback_cities,
    data_bounds,
    eats_by_restaurant,
    filter_from_widgets,
    forgotten_cities,
    scoreboard,
    streak_stats,
    trips_by_city,
    weekday_heatmap,
)

FORBIDDEN_COLUMNS = {
    "email",
    "e-mail",
    "mobile",
    "phone",
    "first_name",
    "last_name",
    "request_lat",
    "request_lng",
    "begintrip_lat",
    "begintrip_lng",
    "dropoff_lat",
    "dropoff_lng",
    "destination_lat",
    "destination_lng",
    "begintrip_string",
    "destination_string",
    "card_number",
    "ip_address",
    "device_id",
    "latitude",
    "longitude",
    "special_instructions",
    "house_number",
    "street_name",
    "postal_code",
}


def make_mini_uber_zip(tmp_path: Path) -> Path:
    """Build a tiny Uber-shaped zip for detect/load tests."""
    root = tmp_path / "uber_src" / "Uber Data"
    rider = root / "Rider"
    eats = root / "Eats"
    acct = root / "Account and Profile"
    for d in (rider, eats, acct):
        d.mkdir(parents=True)

    (rider / "rider_lifetime_trips-0.csv").write_text(
        "city_name,product_type_name,global_product_name,timezone,currency_code,"
        "request_timestamp_local,request_timestamp_utc,request_lat,request_lng,"
        "begintrip_timestamp_local,begintrip_timestamp_utc,begintrip_lat,begintrip_lng,"
        "begintrip_string,dropoff_timestamp_local,dropoff_timestamp_utc,"
        "dropoff_lat,dropoff_lng,destination_lat,destination_lng,destination_string,"
        "eta,surge_multiplier,is_surged,status,is_completed,"
        "request_to_begin_duration_seconds,trip_distance_miles,trip_duration_seconds,"
        "original_fare_local,original_fare_usd,tip_amount_local_currency,"
        "tip_currency_code,credits_local,credits_usd,promotion_local,promotion_usd,"
        "payment_type,card_number,client_device,client_app_version,"
        "is_airport_trip,is_scheduled_trip,is_cash_trip\n"
        "Paris,uberX,UberX,Europe/Paris,EUR,"
        "2015-05-13T19:45:05.000Z,2015-05-13T17:45:05.000Z,48.85,2.33,"
        "2015-05-13T19:49:15.000Z,2015-05-13T17:49:15.000Z,48.85,2.33,"
        "12 Secret St,"
        "2015-05-13T20:02:27.000Z,2015-05-13T18:02:27.000Z,"
        "48.87,2.34,48.87,2.34,Home Address,"
        "300,,false,completed,true,"
        "250,2.5,780,"
        "12.50,13.80,1.00,EUR,,,,,visa,4111111111111111,android,3.47.2,"
        "false,false,false\n"
        "London,uberX,UberX,Europe/London,GBP,"
        "2024-01-10T18:00:00.000Z,2024-01-10T18:00:00.000Z,51.5,-0.1,"
        "2024-01-10T18:05:00.000Z,2024-01-10T18:05:00.000Z,51.5,-0.1,,"
        "2024-01-10T18:30:00.000Z,2024-01-10T18:30:00.000Z,"
        "51.52,-0.12,,,,"
        "200,,false,completed,true,"
        "300,3.1,1500,"
        "18.00,18.00,,,,,,,paypal,,android,6.0.0,"
        "false,false,false\n"
        "Paris,uberX,UberX,Europe/Paris,EUR,"
        "2025-06-01T12:00:00.000Z,2025-06-01T10:00:00.000Z,48.86,2.35,"
        "2025-06-01T12:10:00.000Z,2025-06-01T10:10:00.000Z,48.86,2.35,,"
        "2025-06-01T12:40:00.000Z,2025-06-01T10:40:00.000Z,"
        "48.87,2.36,,,,"
        "180,1.2,true,completed,true,"
        "600,4.0,1800,"
        "22.00,24.00,,,,,,,visa,,android,6.1.0,"
        "true,false,false\n",
        encoding="utf-8",
    )
    (rider / "rider_lifetime_ratings_received-0.csv").write_text(
        "five_star_rating\n5\n5\n4\n",
        encoding="utf-8",
    )
    (eats / "user_orders-0.csv").write_text(
        "City_Name,Restaurant_Name,Request_Time_Local,Final_Delivery_Time_Local,"
        "Order_Status,Item_Name,Item_quantity,Customizations,"
        "Customization_Cost_Local,Special_Instructions,Item_Price,Order_Price,Currency\n"
        '"Birmingham, UK",Dosa Corner,2025-05-01T18:56:31.000Z,2025-05-01T19:51:39.000Z,'
        "completed,Parotta,2,,,,5.98,43.35,GBP\n"
        '"Birmingham, UK",Dosa Corner,2025-05-01T18:56:31.000Z,2025-05-01T19:51:39.000Z,'
        'completed,Dhaal Curry,1,"extra spice",,"gate code 1234",4.99,43.35,GBP\n',
        encoding="utf-8",
    )
    (acct / "customer_support_tickets-0.csv").write_text(
        "Creator,Message,Date\n"
        "Uber,Hi, welcome to Uber support.,2022-07-03T06:46:58.000Z\n",
        encoding="utf-8",
    )
    # Forbidden files — must not be copied to raw/
    (acct / "user_profile-0.csv").write_text(
        "First Name,Last Name,E-Mail,Mobile\nJane,Doe,secret@example.com,123\n",
        encoding="utf-8",
    )
    (acct / "payment_methods-0.csv").write_text(
        "Payment Method Brand,Bank/Issuer Name\nvisa,Secret Bank\n",
        encoding="utf-8",
    )
    (acct / "rider_eater_saved_locations.csv").write_text(
        "Label,House number,Street name,City,Latitude,Longitude\n"
        "Home,1,Secret St,Paris,48.8,2.3\n",
        encoding="utf-8",
    )
    (rider / "rider_app_analytics-0.csv").write_text(
        "Event Time (UTC),IP Address,Device ID,Latitude,Longitude\n"
        "2026-01-01 00:00:00,1.2.3.4,dev-1,48.8,2.3\n",
        encoding="utf-8",
    )

    zip_path = tmp_path / "uber.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in root.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(root.parent).as_posix())
    return zip_path


def test_detect_zip(tmp_path):
    zip_path = make_mini_uber_zip(tmp_path)
    source = UberSource()
    assert source.detect(zip_path)
    assert isinstance(source, Source)
    unrelated = tmp_path / "other.zip"
    with zipfile.ZipFile(unrelated, "w") as zf:
        zf.writestr("readme.txt", "nope")
    assert not source.detect(unrelated)


def test_pick_source(tmp_path):
    zip_path = make_mini_uber_zip(tmp_path)
    source = pick_source(zip_path)
    assert source is not None
    assert source.name == "uber"


def test_load_and_queries(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = make_mini_uber_zip(tmp_path)
    db_path = tmp_path / "w.duckdb"
    conn = duckdb.connect(str(db_path))
    source = UberSource()
    source.load(zip_path, conn)
    inv = source.inventory(conn)
    assert inv["n_trips"] == 3
    assert inv["n_completed"] == 3
    assert inv["n_orders"] == 1
    assert inv["n_order_items"] == 2
    assert inv["n_ratings"] == 3
    assert inv["n_support"] == 1
    assert "uber" in inv["summary"]

    for table in ("trips", "order_items", "ratings", "support_messages"):
        cols = {
            r[0].lower()
            for r in conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'uber' AND table_name = ?
                """,
                [table],
            ).fetchall()
        }
        assert not (cols & FORBIDDEN_COLUMNS), (table, cols & FORBIDDEN_COLUMNS)

    trip_blob = " ".join(
        str(v)
        for row in conn.execute("SELECT * FROM uber.trips").fetchall()
        for v in row
    )
    assert "48.85" not in trip_blob
    assert "Secret St" not in trip_blob
    assert "Home Address" not in trip_blob
    assert "4111111111111111" not in trip_blob

    order_blob = " ".join(
        str(v)
        for row in conn.execute("SELECT * FROM uber.order_items").fetchall()
        for v in row
    )
    assert "gate code 1234" not in order_blob

    raw = raw_dir("uber")
    assert (raw / "rider_lifetime_trips-0.csv").exists()
    assert (raw / "user_orders-0.csv").exists()
    assert not (raw / "user_profile-0.csv").exists()
    assert not (raw / "payment_methods-0.csv").exists()
    assert not (raw / "rider_eater_saved_locations.csv").exists()
    assert not (raw / "rider_app_analytics-0.csv").exists()
    raw_trips = (raw / "rider_lifetime_trips-0.csv").read_text(encoding="utf-8")
    assert "request_lat" not in raw_trips.lower()
    assert "card_number" not in raw_trips.lower()
    assert "4111111111111111" not in raw_trips
    raw_orders = (raw / "user_orders-0.csv").read_text(encoding="utf-8")
    assert "special_instructions" not in raw_orders.lower()
    assert "gate code" not in raw_orders

    bounds = data_bounds(conn)
    filters = filter_from_widgets(
        bounds, year_start=bounds["min_year"], year_end=bounds["max_year"]
    )
    score = scoreboard(conn, filters)
    assert int(score.iloc[0]["trips"]) == 3
    assert int(score.iloc[0]["eats_orders"]) == 1
    assert not trips_by_city(conn, filters).empty
    assert not weekday_heatmap(conn, filters).empty
    assert not calendar_daily_trips(conn, filters).empty
    assert not streak_stats(conn, filters).empty
    assert not city_rank_bump(conn, filters).empty
    forgotten_cities(conn, filters)
    comeback_cities(conn, filters)
    assert not eats_by_restaurant(conn, filters).empty
    conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = make_mini_uber_zip(tmp_path)
    db_path = tmp_path / "cli.duckdb"
    assert main([str(zip_path), "--db", str(db_path)]) == 0
