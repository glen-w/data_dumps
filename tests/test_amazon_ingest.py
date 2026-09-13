"""Amazon GDPR multipart ingest smoke tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb

from data_dumps.amazon_queries import (
    FilterState,
    alexa_tag_monthly,
    alexa_tags,
    basket_sizes,
    cart_vs_ordered,
    comeback_asins,
    data_bounds,
    footprint_by_category,
    impression_mix,
    impulse_index_by_family,
    order_calendar,
    returns_by_family,
    scoreboard,
    search_funnel_stages,
    spend_by_currency,
    spend_sunburst,
)
from data_dumps.ingest import main, pick_source
from data_dumps.sources.amazon import AmazonSource
from data_dumps.sources.base import Source

FORBIDDEN_COLUMNS = {
    "email",
    "email_address",
    "billing_address",
    "shipping_address",
    "customer_ip",
    "ip",
    "ip_address",
    "phone",
    "voice_phone",
    "card_number",
    "last_digits",
    "contact_name",
    "device_id",
    "device_serial_number",
    "customer_city",
    "customer_postal_code",
    "user_agent",
    "http_referer",
}

ORDER_CSV = """ASIN,Billing Address,Carrier Name & Tracking Number,Currency,Department,Gift Message,Gift Recipient Contact,Gift Sender Name,Item Serial Number,Order Date,Order ID,Order Status,Original Quantity,Payment Method Type,Product Condition,Product Name,Purchase Order Number,Ship Date,Shipment Item Subtotal,Shipment Item Subtotal Tax,Shipment Status,Shipping Address,Shipping Charge,Shipping Option,Total Amount,Total Discounts,Unit Price,Unit Price Tax,Website
B00TEST1,123 Secret St,AMZN(TRACK),EUR,Paperback,Not Available,Not Available,Not Available,Not Available,2024-06-01T10:00:00Z,111-1,Closed,1,Visa,New,Test Book,Not Available,2024-06-02T10:00:00Z,10,0,Shipped,123 Secret St,0,Not Applicable,10.00,0,10.00,0,Amazon.fr
B00TEST2,123 Secret St,AMZN(TRACK),GBP,Electronics,Not Available,secret@x.com,Not Available,Not Available,2025-01-15T12:00:00Z,222-2,Cancelled,1,Visa,New,Test Gadget,Not Available,Not Available,20,0,Cancelled,123 Secret St,0,Not Applicable,20.00,0,20.00,0,Amazon.co.uk
B00TEST1,123 Secret St,AMZN(TRACK),EUR,Broché,Not Available,Not Available,Not Available,Not Available,2023-03-01T08:00:00Z,333-3,Closed,1,Visa,New,Test Book FR,Not Available,2023-03-02T08:00:00Z,8,0,Shipped,123 Secret St,0,Not Applicable,8.00,0,8.00,0,Amazon.fr
"""

SEARCH_CSV = """Added Any Item (Y/N),All Department (APS) or Category,Amazon Business Customer (Y/N),Amazon Fresh (Y/N),Amazon Fresh Customer (Y/N),App Version,Application / Browser Name,Application Name,Browse Node,Clicked Any Item (Y/N),Country Code,Customer IP,Department,Department Count,Device Category,Device Model,Device Type ID,First Added Item,First Browse Node,First Consumed Item (Subscription),First Purchased Item,First Search Domain,First Search Query String,First Search Time (GMT),Free Units Ordered,Highest Number of Shopping Refinements,Is First Search From External Ad,Is From External Link (Y/N),Item Borrowed (Y/N),Items Borrowed,Items Consumed (Subscription),Keywords,Language of Preference,Last Browse Node,Last Department,Last search Time (GMT),Maximum Purchase Price,Music Subscriber (Y/N),Next Query Group via Click,Number of Clicked Items,Number of Free Items Ordered,Number of Items Added to Cart,Number of Items Ordered,Number of Paid Items Ordered,Number of Shopping Refinements,Operating System Name,Operating System Version,Paid Purchase (Y/N),Paid Units Ordered,Prime Customer (Y/N),Purchased Any Item (Y/N),Query Abandoned (Y/N),Query ID,Query Reformulated (Y/N),Search From External Site (Y/N),Search Method,Search Type (Keyword,Visual,Browse),Server,Session ID,Shopping Refinement,Shopping Refinement Pickers,Site Variant,Units Ordered,User Agent Info Family
No,aps,No,No,No,Not Available,Desktop,Not Available,0,Yes,UK,203.0.113.9,aps,1,Desktop,Not Available,Not Available,Not Available,0,Not Available,Not Available,Not Available,usb cable,2024-05-01T10:00:00Z,0,0,No,No,No,Not Applicable,Not Applicable,usb cable,en,0,aps,2024-05-01T10:00:00Z,0,No,Not Available,1,0,0,0,0,0,Not Available,Not Available,No,0,Yes,No,No,q1,No,No,typed,Keyword,s,sess,Not Available,Not Available,retail,0,Chrome
"""

CART_CSV = """ASIN,Add-on Item,Cart Domain,Cart List,Cart Source,Date Added to Cart,Gift Wrapped,One-Click Enabled,Order Quantity,Pantry Item,Prime Subscription,Product Name
B00CART,No,Not Applicable,saved,Retail,2024-05-25T14:40:35.316Z,No,Yes,1,No,No,Cart Widget
"""

INTENT_CSV = """Currently Playing Song,Screen Contents,Contact Name,Utterance text,Utterance Creation Date
Not Available,Not Available,Alice Secret,alexa play radio two,2024-08-21T13:53:36.929Z
Not Available,Not Available,Not Available,turn on the lamp,2024-08-21T14:00:00Z
"""

IMPRESSIONS_CSV = """marketplace_id,ASIN,product_name,customer_country_code,customer_state,customer_city,customer_district,customer_postal_code,creation_date,promised_delivery_date,device_type,website_list_price,website_list_price_currency_code,shipping_charge_value,shipping_charge_unit,merchant_asin_price,merchant_asin_price_currency_code,root_uri,user_agent,http_referer,is_business_customer,is_prime_customer
www.amazon.co.uk,B00IMP1,Glance Widget,GB,West Midlands,BRIERLEY HILL,Not Available,DY5 3,2024-07-01T10:00:00Z,Not Available,Desktop,9.99,GBP,0,GBP,9.99,GBP,/,Mozilla,https://amazon.co.uk,No,Yes
"""

DEVICE_REG_CSV = """Account Name,Amazon Device Model Name,Current Firmware Version,Customer Login Pool,Customer Type,Device Account Role,Device Model,Device Pairing Details,Device Serial Number,First Time Registered,IP Address,Last Time Registered,Local Time Offset,State,Time Deregistered
Everywhere,Echo Dot,1.0,Amazon,ADULT,PRIMARY,Echo Dot (3rd Gen),Not Applicable,G090SECRET123,2024-01-01T09:00:00Z,203.0.113.50,2024-01-02T09:00:00Z,Not Available,ACTIVE,Not Available
"""


def make_mini_amazon_dir(path: Path) -> Path:
    """Multipart-style folder: FileDescriptions + curated zip 3 + tiny alexa zip."""
    root = path / "amazon"
    root.mkdir()
    (root / "FileDescriptions.csv").write_text(
        "File name,Description\nOrder History.csv,orders\n", encoding="utf-8"
    )

    z3 = root / "All Data Categories.3.zip"
    with zipfile.ZipFile(z3, "w") as zf:
        zf.writestr("Your Amazon Orders/Order History.csv", ORDER_CSV)
        zf.writestr("Your Shopping Search/Search Queries.csv", SEARCH_CSV)
        zf.writestr("Your Amazon Orders/Cart History.csv", CART_CSV)
        zf.writestr(
            "Your Returns & Refunds/Refund Details.csv",
            "Creation Date,Currency,Direct Debit Refund Amount,Disbursement Type,"
            "Order ID,Payment Status,Quantity,Refund Amount,Refund Date,"
            "Reversal Amount State,Reversal Reason,Reversal Status,Website\n"
            "2024-06-10T00:00:00Z,EUR,0,Refund,111-1,Completed,1,5.00,"
            "2024-06-11T00:00:00Z,Final,Customer return,Completed,Amazon.fr\n",
        )
        zf.writestr(
            "Your Fire TV Device & Setup/Device Registration.csv", DEVICE_REG_CSV
        )

    z2 = root / "All Data Categories.2.zip"
    with zipfile.ZipFile(z2, "w") as zf:
        zf.writestr(
            "Additional Data/Request All Your Data.Detail Page Glance View Impressions/"
            "Request All Your Data.Detail Page Glance View Impressions.csv",
            IMPRESSIONS_CSV,
        )

    z4 = root / "All Data Categories.4.zip"
    with zipfile.ZipFile(z4, "w") as zf:
        zf.writestr("Additional Data/Alexa/Alexa/NLU/Intent-2-1.csv", INTENT_CSV)
        # Shadow voice file — must appear in inventory, never as a table row source
        zf.writestr("Additional Data/Alexa/Voice/sample.wav", b"RIFF....WAVE")

    return root


def _all_columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'amazon'
        """).fetchall()
    return {r[0].lower() for r in rows}


def test_detect_multipart_dir(tmp_path):
    root = make_mini_amazon_dir(tmp_path)
    source = AmazonSource()
    assert source.detect(root)
    assert isinstance(source, Source)
    picked = pick_source(root)
    assert picked is not None and picked.name == "amazon"


def test_detect_rejects_unrelated(tmp_path):
    (tmp_path / "notes.txt").write_text("nope")
    assert not AmazonSource().detect(tmp_path)


def test_load_strips_pii_and_loads_surfaces(tmp_path, monkeypatch):
    root = make_mini_amazon_dir(tmp_path)
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    db_path = tmp_path / "ingest.duckdb"
    conn = duckdb.connect(str(db_path))
    source = AmazonSource()
    source.load(root, conn)
    inv = source.inventory(conn)
    assert inv["n_order_items"] == 3
    assert inv["n_alexa_intents"] == 2
    assert inv["voice_files"] >= 1

    cols = _all_columns(conn)
    leaked = cols & FORBIDDEN_COLUMNS
    assert not leaked, f"PII columns survived ingest: {leaked}"

    # Address / IP text must not land in product_name etc.
    bad = conn.execute("""
        SELECT count(*) FROM amazon.order_items
        WHERE product_name ILIKE '%Secret St%'
           OR product_name ILIKE '%@%'
        """).fetchone()
    assert bad is not None and bad[0] == 0

    ip_in_search = conn.execute("""
        SELECT count(*) FROM amazon.searches
        WHERE keywords ILIKE '%203.0.113%'
        """).fetchone()
    assert ip_in_search is not None and ip_in_search[0] == 0

    contact = conn.execute("""
        SELECT count(*) FROM amazon.alexa_intents
        WHERE utterance ILIKE '%Alice Secret%'
        """).fetchone()
    assert contact is not None and contact[0] == 0

    families = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT dept_family FROM amazon.order_items"
        ).fetchall()
    }
    assert "books" in families
    assert "electronics" in families

    tags = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT utterance_tag FROM amazon.alexa_intents"
        ).fetchall()
    }
    assert "music" in tags
    assert "smart_home" in tags

    foot = footprint_by_category(conn)
    assert not foot.empty
    assert "voice_audio" in set(foot["category"].tolist())

    n_imp = conn.execute("SELECT count(*) FROM amazon.product_impressions").fetchone()
    assert n_imp is not None and n_imp[0] == 1
    city_leak = conn.execute("""
        SELECT count(*) FROM amazon.product_impressions
        WHERE product_name ILIKE '%BRIERLEY%' OR coalesce(asin, '') = ''
        """).fetchone()
    assert city_leak is not None and city_leak[0] == 0

    n_dev = conn.execute("SELECT count(*) FROM amazon.devices_summary").fetchone()
    assert n_dev is not None and n_dev[0] >= 1
    serial_plain = conn.execute("""
        SELECT count(*) FROM amazon.devices_summary
        WHERE coalesce(serial_hash, '') ILIKE '%SECRET%'
           OR coalesce(device_model, '') ILIKE '%203.0.113%'
        """).fetchone()
    assert serial_plain is not None and serial_plain[0] == 0

    orders = conn.execute("SELECT count(*) FROM amazon.orders").fetchone()
    assert orders is not None and orders[0] == 3
    conn.close()


def test_detect_single_curated_zip(tmp_path):
    root = make_mini_amazon_dir(tmp_path)
    z3 = root / "All Data Categories.3.zip"
    assert AmazonSource().detect(z3)


def test_cli_ingest(tmp_path, monkeypatch):
    root = make_mini_amazon_dir(tmp_path)
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    db_path = tmp_path / "catalog.duckdb"
    rc = main([str(root), "--db", str(db_path)])
    assert rc == 0
    conn = duckdb.connect(str(db_path), read_only=True)
    n = conn.execute("SELECT count(*) FROM amazon.order_items").fetchone()
    assert n is not None and n[0] == 3
    conn.close()


def test_amazon_queries(tmp_path, monkeypatch):
    root = make_mini_amazon_dir(tmp_path)
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    db_path = tmp_path / "q.duckdb"
    conn = duckdb.connect(str(db_path))
    AmazonSource().load(root, conn)
    bounds = data_bounds(conn)
    assert bounds["min_year"] <= 2024
    f = FilterState()
    score = scoreboard(conn, f)
    assert int(score.iloc[0]["order_lines"]) == 2  # cancelled excluded
    assert "avg_basket_items" in score.columns
    assert "return_orders" in score.columns
    fx = spend_by_currency(conn, f)
    assert "EUR" in set(fx["currency"].tolist())
    f2 = FilterState(include_cancelled=True)
    score2 = scoreboard(conn, f2)
    assert int(score2.iloc[0]["order_lines"]) == 3
    f_fr = FilterState(marketplaces=["fr"])
    score_fr = scoreboard(conn, f_fr)
    assert int(score_fr.iloc[0]["order_lines"]) == 2
    tags = alexa_tags(conn, f)
    assert "music" in set(tags["tag"].tolist())
    imps = impression_mix(conn, f)
    assert int(imps["n"].sum()) == 1
    stages = search_funnel_stages(conn, f)
    assert list(stages["stage"]) == ["searches", "clicked", "added", "purchased"]
    assert int(stages.iloc[0]["n"]) >= 1
    baskets = basket_sizes(conn, f)
    assert not baskets.empty
    sun = spend_sunburst(conn, f)
    assert "books" in set(sun["dept_family"].tolist())
    cal = order_calendar(conn, f)
    assert not cal.empty
    # Add a repurchase in-memory for comeback coverage via second load row already
    # B00TEST1 appears twice in fixture (2023 + 2024) when cancelled included
    comes = comeback_asins(conn, FilterState(include_cancelled=True))
    assert not comes.empty
    assert "B00TEST1" in set(comes["asin"].tolist())
    tag_m = alexa_tag_monthly(conn, f)
    assert not tag_m.empty

    # Impulse vs planned: every kept order line here sits in a one-line basket,
    # so both kept lines are impulse and none are planned.
    imp = impulse_index_by_family(conn, f)
    assert not imp.empty
    assert set(imp["basket_kind"].tolist()) == {"impulse"}
    books_impulse = imp.loc[imp["dept_family"] == "books", "lines"].sum()
    assert books_impulse >= 1

    # Cart vs ordered: the fixture carries one add-to-cart ASIN (B00CART) that is
    # never in an order, i.e. abandoned.
    cart = cart_vs_ordered(conn, f)
    assert not cart.empty
    assert set(cart["outcome"].tolist()) == {"abandoned"}
    assert "B00CART" in set(cart["asin"].tolist())

    # Returns by family: the single refund (5.00) lands on the bought order_id,
    # whose line is a book.
    ret_fam = returns_by_family(conn, f)
    assert not ret_fam.empty
    assert "books" in set(ret_fam["dept_family"].tolist())
    assert float(ret_fam["refund_sum"].sum()) > 0
    conn.close()


def test_scoreboard_empty_filter(tmp_path, monkeypatch):
    root = make_mini_amazon_dir(tmp_path)
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    db_path = tmp_path / "empty.duckdb"
    conn = duckdb.connect(str(db_path))
    AmazonSource().load(root, conn)
    # Year range with no orders
    f = FilterState(year_start=1990, year_end=1991)
    score = scoreboard(conn, f)
    assert int(score.iloc[0]["order_lines"]) == 0
    assert int(score.iloc[0]["orders"]) == 0
    conn.close()
