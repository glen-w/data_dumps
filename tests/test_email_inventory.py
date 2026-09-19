"""Email index: in-text mentions, other people, and dropped account fields."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import duckdb
import marimo as mo
import plotly.express as px

from data_dumps.email_inventory import (
    discover_gloda,
    extract_airbnb,
    extract_amazon,
    extract_duolingo,
    extract_google,
    extract_linkedin,
    extract_ring,
    extract_slack_profiles,
    extract_spotify,
    extract_twitter,
    extract_uber,
    find_emails,
    inventory_frame,
    main,
    normalize_email,
    scan_gloda_bodies,
    scan_text_columns,
    scan_thunderbird_headers,
)
from data_dumps.explorer_panels.tools import render_tools_panel


def test_normalize_rejects_filenames() -> None:
    assert normalize_email("Ada@Example.com") == "ada@example.com"
    assert normalize_email("see user@2x.png") is None
    assert find_emails("write ada@example.com, not user@2x.png") == ["ada@example.com"]


def test_text_scan_counts_mentions_and_skips_filenames() -> None:
    conn = duckdb.connect()
    conn.execute("CREATE SCHEMA chatgpt")
    conn.execute("CREATE TABLE chatgpt.messages (text VARCHAR)")
    conn.execute("""
        INSERT INTO chatgpt.messages VALUES
            ('ping other@example.com please'),
            ('again other@example.com and pal@example.org'),
            ('asset user@2x.png')
        """)
    hits = {
        (hit.use, hit.email)
        for hit in scan_text_columns(conn)
        if hit.service == "ChatGPT"
    }
    assert ("mentioned in chat (2 mentions)", "other@example.com") in hits
    assert ("mentioned in chat (1 mention)", "pal@example.org") in hits
    assert all("2x.png" not in email for _use, email in hits)


def test_thunderbird_headers_keep_other_people() -> None:
    conn = duckdb.connect()
    conn.execute("CREATE SCHEMA thunderbird")
    conn.execute(
        "CREATE TABLE thunderbird.accounts (email VARCHAR, display_name VARCHAR)"
    )
    conn.execute("INSERT INTO thunderbird.accounts VALUES ('me@example.com', 'Me')")
    conn.execute("""
        CREATE TABLE thunderbird.participants (
            message_id BIGINT, role VARCHAR, addr VARCHAR,
            domain VARCHAR, display_name VARCHAR
        )
        """)
    conn.execute("""
        INSERT INTO thunderbird.participants VALUES
            (1, 'from', 'ada@example.com', 'example.com', 'Ada Lovelace'),
            (2, 'from', 'ada@example.com', 'example.com', 'Ada Lovelace'),
            (1, 'to', 'me@example.com', 'example.com', 'Me')
        """)
    hits = {(hit.use, hit.email) for hit in scan_thunderbird_headers(conn)}
    assert ("mail identity", "me@example.com") in hits
    assert (
        "correspondent, from · Ada Lovelace (2 messages)",
        "ada@example.com",
    ) in hits


def test_extractors_and_panel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DUMPS_SKIP_GLODA", "1")
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    assert discover_gloda() is None

    linkedin = tmp_path / "linkedin" / "Complete_export.zip"
    linkedin.parent.mkdir()
    with zipfile.ZipFile(linkedin, "w") as archive:
        archive.writestr(
            "Email Addresses.csv",
            "Email Address,Confirmed,Primary\n"
            "me@example.com,Yes,Yes\n"
            "old@example.com,Yes,No\n",
        )
    hits = {(hit.use, hit.email) for hit in extract_linkedin(linkedin)}
    assert ("primary account email", "me@example.com") in hits
    assert ("confirmed account email", "old@example.com") in hits

    slack = tmp_path / "raw" / "slack" / "users.json"
    slack.parent.mkdir(parents=True)
    slack.write_text(
        json.dumps(
            [
                {
                    "id": "U1",
                    "real_name": "Ada Lovelace",
                    "is_bot": False,
                    "deleted": False,
                    "profile": {
                        "email": "ada@example.com",
                        "display_name": "Ada",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    slack_hits = extract_slack_profiles(slack)
    assert slack_hits[0].email == "ada@example.com"
    assert slack_hits[0].use == "user profile · Ada"
    assert slack_hits[0].service == "Slack"

    google = tmp_path / "google" / "takeout-1.zip"
    google.parent.mkdir()
    vcf = "BEGIN:VCARD\nFN:Grace Hopper\nEMAIL;TYPE=INTERNET:grace@example.com\nEND:VCARD\n"
    profile = json.dumps({"emails": [{"value": "me@gmail.com"}]})
    subscriber = "<html><body><p>e-Mail: me@gmail.com</p><p>Recovery e-Mail: backup@example.com</p></body></html>"
    with zipfile.ZipFile(google, "w") as archive:
        archive.writestr("Takeout/Profile/Profile.json", profile)
        archive.writestr("Takeout/Google Account/me.SubscriberInfo.html", subscriber)
        archive.writestr("Takeout/Contacts/All.vcf", vcf)
    google_hits = {(hit.use, hit.email) for hit in extract_google(google.parent)}
    assert ("profile email", "me@gmail.com") in google_hits
    assert ("account email", "me@gmail.com") in google_hits
    assert ("recovery email", "backup@example.com") in google_hits
    assert ("contact · Grace Hopper", "grace@example.com") in google_hits

    twitter = tmp_path / "twitter" / "data"
    twitter.mkdir(parents=True)
    (twitter / "account.js").write_text(
        'window.YTD.account.part0 = [{"account": {"email": "bird@example.com"}}]',
        encoding="utf-8",
    )
    tw_hits = extract_twitter(twitter.parent)
    assert any(hit.email == "bird@example.com" for hit in tw_hits)

    gloda = tmp_path / "gloda.sqlite"
    con = sqlite3.connect(gloda)
    con.execute("""
        CREATE TABLE messagesText_content (
            docid INTEGER,
            c0body TEXT,
            c1subject TEXT,
            c2attachmentNames TEXT,
            c3author TEXT,
            c4recipients TEXT
        )
        """)
    con.execute(
        "INSERT INTO messagesText_content VALUES (1, ?, 'subj', '', '', '')",
        ["please reply to body@example.com"],
    )
    con.commit()
    con.close()
    body_hits = scan_gloda_bodies(gloda)
    assert any(
        hit.email == "body@example.com" and "message body" in hit.use
        for hit in body_hits
    )

    conn = duckdb.connect()
    conn.execute("CREATE SCHEMA chatgpt")
    conn.execute("CREATE TABLE chatgpt.messages (text VARCHAR)")
    conn.execute(
        "INSERT INTO chatgpt.messages VALUES ('see chat@example.com in the thread')"
    )
    frame, note = inventory_frame(conn, force=True)
    emails = set(frame["Email address"])
    assert "chat@example.com" in emails
    assert "ada@example.com" in emails
    assert "grace@example.com" in emails
    assert "me@example.com" in emails
    assert "Source dashboards" in note
    chat = frame[frame["Email address"] == "chat@example.com"].iloc[0]
    assert chat["Service"] == "ChatGPT"
    assert "mentioned in chat" in chat["Provenance / use"]
    # Source table did not grow an email column.
    cols = {row[0] for row in conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'chatgpt'
            """).fetchall()}
    assert "email" not in cols

    panel = render_tools_panel(mo=mo, px=px, conn=conn)
    assert panel is not None


def test_empty_panel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DUMPS_SKIP_GLODA", "1")
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    conn = duckdb.connect()
    panel = render_tools_panel(mo=mo, px=px, conn=conn)
    assert panel is not None


def test_dropped_files_keep_other_people_off_source_tables(tmp_path: Path) -> None:
    uber = tmp_path / "uber.zip"
    with zipfile.ZipFile(uber, "w") as archive:
        archive.writestr(
            "Uber Data/Account and Profile/user_profile-0.csv",
            "First Name,E-Mail\nAda,ride@example.com\n",
        )
    assert extract_uber(uber)[0].email == "ride@example.com"

    duo = tmp_path / "duo"
    duo.mkdir()
    (duo / "profile.csv").write_text(
        "name,value\nusername,owl\nemail,owl@example.com\nphone,5551212\n",
        encoding="utf-8",
    )
    duo_hits = extract_duolingo(duo)
    assert [hit.email for hit in duo_hits] == ["owl@example.com"]

    spotify = tmp_path / "spotify.zip"
    with zipfile.ZipFile(spotify, "w") as archive:
        archive.writestr(
            "Spotify Account Data/UserAttributes.json",
            json.dumps({"email": "listen@example.com", "mobileNumber": "555"}),
        )
    spotify_hits = extract_spotify(spotify)
    assert [hit.email for hit in spotify_hits] == ["listen@example.com"]

    ring = tmp_path / "ring.zip"
    with zipfile.ZipFile(ring, "w") as archive:
        archive.writestr(
            "RequestAllYourData.UserAccount/datasets/users/users.json",
            json.dumps([{"Email": "bell@example.com"}]),
        )
    assert extract_ring(ring)[0].email == "bell@example.com"

    airbnb = tmp_path / "airbnb.zip"
    html = """
    <h2>User</h2>
    <table><thead><tr><th>key</th><th>value</th></tr></thead>
    <tbody><tr><td>email</td><td>stay@example.com</td></tr></tbody></table>
    """
    with zipfile.ZipFile(airbnb, "w") as archive:
        archive.writestr("html/profile_information.html", html)
    assert extract_airbnb(airbnb)[0].email == "stay@example.com"

    amazon = tmp_path / "amazon"
    amazon.mkdir()
    with zipfile.ZipFile(amazon / "All Data Categories.2.zip", "w") as archive:
        archive.writestr(
            "note.eml",
            "From: shop@example.com\n\nReply to guest@example.com not user@2x.png\n",
        )
        archive.writestr(
            "Additional Data/Alexa/Communications/Contacts/contacts-2.csv",
            "First Name,Last Name,Email Address\nGrace,Hopper,hopper@example.com\n",
        )
        archive.writestr(
            "Kindle.KindleDocs.ApprovedPersonalDocumentEmailList.csv",
            "Email Address\nsender@example.com\n",
        )
    amazon_hits = {(hit.use, hit.email) for hit in extract_amazon(amazon)}
    assert ("Alexa contact · Grace Hopper", "hopper@example.com") in amazon_hits
    assert ("Kindle approved sender", "sender@example.com") in amazon_hits
    assert ("mentioned in Amazon email (1 file)", "guest@example.com") in amazon_hits
    assert ("mentioned in Amazon email (1 file)", "shop@example.com") in amazon_hits
    assert all(not email.endswith(".png") for _use, email in amazon_hits)


def test_cli_prints_counts_not_addresses(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATA_DUMPS_SKIP_GLODA", "1")
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    db = tmp_path / "catalog.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute("CREATE SCHEMA chatgpt")
    conn.execute("CREATE TABLE chatgpt.messages (text VARCHAR)")
    conn.execute("INSERT INTO chatgpt.messages VALUES ('ping secret@example.com')")
    conn.close()
    assert main(["--db", str(db), "--refresh"]) == 0
    out = capsys.readouterr().out
    assert "secret@example.com" not in out
    assert "ChatGPT:" in out
    cache = (tmp_path / "warehouse" / "email_inventory.json").read_text(
        encoding="utf-8"
    )
    assert "secret@example.com" in cache


def test_cache_skips_rescan(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DUMPS_SKIP_GLODA", "1")
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    conn = duckdb.connect()
    conn.execute("CREATE SCHEMA chatgpt")
    conn.execute("CREATE TABLE chatgpt.messages (text VARCHAR)")
    conn.execute("INSERT INTO chatgpt.messages VALUES ('cache@example.com')")
    frame, _note = inventory_frame(conn, force=True)
    assert "cache@example.com" in set(frame["Email address"])

    def _boom(*_args, **_kwargs):
        raise AssertionError("cache miss rescanned")

    monkeypatch.setattr("data_dumps.email_inventory.collect_hits", _boom)
    again, _note = inventory_frame(conn)
    assert "cache@example.com" in set(again["Email address"])
