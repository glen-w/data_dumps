"""Thunderbird Gloda ingest + query smoke tests (synthetic fixture only)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import duckdb

from data_dumps.ingest import main, pick_source
from data_dumps.sources.base import Source
from data_dumps.sources.thunderbird import ThunderbirdSource
from data_dumps.sources.thunderbird_gloda import (
    detect_signals,
    parse_address_blob,
    snapshot_gloda,
)
from data_dumps.thunderbird_queries import (
    calendar_daily,
    circadian_heatmap,
    data_bounds,
    filter_from_widgets,
    scoreboard,
    top_domains,
)


def make_mini_gloda_profile(root: Path, *, identity: str = "me@example.com") -> Path:
    """Build a tiny Thunderbird-like profile with Gloda + prefs.js."""
    profile = root / "abcd1234.default-release"
    profile.mkdir(parents=True)
    prefs = profile / "prefs.js"
    prefs.write_text(
        'user_pref("mail.accountmanager.accounts", "account1");\n'
        'user_pref("mail.account.account1.identities", "id1");\n'
        'user_pref("mail.account.account1.server", "server1");\n'
        'user_pref("mail.server.server1.name", "Example");\n'
        'user_pref("mail.server.server1.type", "imap");\n'
        'user_pref("mail.server.server1.hostname", "imap.example.com");\n'
        f'user_pref("mail.identity.id1.useremail", "{identity}");\n'
        'user_pref("mail.identity.id1.fullName", "Me");\n',
        encoding="utf-8",
    )
    db_path = profile / "global-messages-db.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE folderLocations (
                id INTEGER PRIMARY KEY,
                folderURI TEXT NOT NULL,
                dirtyStatus INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL,
                indexingPriority INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                folderID INTEGER,
                messageKey INTEGER,
                conversationID INTEGER NOT NULL,
                date INTEGER,
                headerMessageID TEXT,
                deleted INTEGER NOT NULL DEFAULT 0,
                jsonAttributes TEXT,
                notability INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE messagesText_content (
                docid INTEGER PRIMARY KEY,
                c0body TEXT,
                c1subject TEXT,
                c2attachmentNames TEXT,
                c3author TEXT,
                c4recipients TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO folderLocations (id, folderURI, name) VALUES "
            "(1, 'imap://me@example.com/INBOX', 'Inbox'),"
            "(2, 'imap://me@example.com/Sent', 'Sent')"
        )
        t0 = 1718452800_000000  # 2024-06-15 12:00:00 UTC
        rows = [
            (
                1,
                1,
                1,
                10,
                t0,
                "<a@x>",
                0,
                "{}",
                "SECRET BODY SHOULD NOT LAND",
                "Weekly Newsletter digest",
                "",
                "News Bot <news@mailchimp.com>",
                "me@example.com",
            ),
            (
                2,
                2,
                2,
                10,
                t0 + 3600_000000,
                "<b@x>",
                0,
                "{}",
                "body2",
                "Re: project",
                "report.pdf",
                "Me <me@example.com>",
                "alice@corp.example",
            ),
            (
                3,
                1,
                3,
                11,
                t0 + 86400_000000,
                "<c@x>",
                0,
                "{}",
                "body3",
                "Your order receipt #42",
                "invoice.pdf",
                "Amazon <auto-confirm@amazon.com>",
                "me@example.com",
            ),
            (
                4,
                1,
                4,
                12,
                t0,
                "<d@x>",
                1,
                "{}",
                "gone",
                "deleted",
                "",
                "x@y.com",
                "me@example.com",
            ),
        ]
        for r in rows:
            conn.execute(
                """
                INSERT INTO messages
                (id, folderID, messageKey, conversationID, date, headerMessageID,
                 deleted, jsonAttributes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                r[:8],
            )
            conn.execute(
                """
                INSERT INTO messagesText_content
                (docid, c0body, c1subject, c2attachmentNames, c3author, c4recipients)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (r[0], r[8], r[9], r[10], r[11], r[12]),
            )
        conn.commit()
    finally:
        conn.close()
    return profile


def test_parse_address_and_signals():
    parsed = parse_address_blob("News Bot <news@Mailchimp.com>")
    assert parsed
    assert parsed[0][1] == "news@mailchimp.com"
    assert parsed[0][2] == "mailchimp.com"
    hits = detect_signals(
        message_id=1,
        subject="Weekly Newsletter digest",
        from_domain="mailchimp.com",
        attachment_names="",
    )
    kinds = {h["kind"] for h in hits}
    assert "newsletter" in kinds


def test_detect_profile_and_sqlite(tmp_path):
    profile = make_mini_gloda_profile(tmp_path)
    src = ThunderbirdSource()
    assert src.detect(profile)
    assert src.detect(profile / "global-messages-db.sqlite")
    assert isinstance(src, Source)
    picked = pick_source(profile)
    assert picked is not None
    assert picked.name == "thunderbird"


def test_snapshot_does_not_modify_source(tmp_path):
    profile = make_mini_gloda_profile(tmp_path)
    gloda = profile / "global-messages-db.sqlite"
    before = gloda.stat().st_mtime_ns
    snap = snapshot_gloda(gloda)
    try:
        assert snap.is_file()
        assert snap != gloda
        assert gloda.stat().st_mtime_ns == before
    finally:
        snap.unlink(missing_ok=True)


def test_load_no_body_direction_signals(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    profile = make_mini_gloda_profile(tmp_path)
    db_path = tmp_path / "w.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        ThunderbirdSource().load(profile, conn)
        cols = [
            r[1]
            for r in conn.execute("PRAGMA table_info('thunderbird.messages')").fetchall()
        ]
        assert "subject" in cols
        assert "from_addr" in cols
        assert not any("body" in c.lower() for c in cols)

        n = conn.execute("SELECT count(*) FROM thunderbird.messages").fetchone()[0]
        assert n == 3

        directions = dict(
            conn.execute(
                "SELECT direction, count(*) FROM thunderbird.messages GROUP BY 1"
            ).fetchall()
        )
        assert directions.get("sent", 0) >= 1
        assert directions.get("received", 0) >= 1

        kinds = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT kind FROM thunderbird.signals"
            ).fetchall()
        }
        assert "newsletter" in kinds
        assert "receipt" in kinds

        for table in ("messages", "participants", "signals", "folders", "accounts"):
            blob = str(
                conn.execute(f"SELECT * FROM thunderbird.{table} LIMIT 100").fetchall()
            )
            assert "SECRET BODY" not in blob

        inv = ThunderbirdSource().inventory(conn)
        assert inv["n_messages"] == 3
        assert "thunderbird.messages=3" in inv["summary"]

        bounds = data_bounds(conn)
        f = filter_from_widgets(bounds, year_start=2024, year_end=2024)
        score = scoreboard(conn, f)
        assert int(score.iloc[0]["messages"]) == 3
        assert not circadian_heatmap(conn, f).empty
        assert not top_domains(conn, f).empty
        assert not calendar_daily(conn, f).empty

        conn.execute(
            "UPDATE thunderbird.messages SET local_date = NULL "
            "WHERE gloda_id = (SELECT min(gloda_id) FROM thunderbird.messages)"
        )
        cal = calendar_daily(conn, f)
        assert cal["day"].notna().all()
        assert int(cal["messages"].sum()) == 2

        nasty = filter_from_widgets(
            bounds,
            year_start=2024,
            year_end=2024,
            contact_substr="'; DROP TABLE thunderbird.messages;--",
        )
        scoreboard(conn, nasty)
        assert (
            conn.execute("SELECT count(*) FROM thunderbird.messages").fetchone()[0] == 3
        )
    finally:
        conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    profile = make_mini_gloda_profile(tmp_path, identity="cli@example.com")
    assert (
        main(
            [
                str(profile),
                "--db",
                str(tmp_path / "catalog.duckdb"),
                "--identity",
                "cli@example.com",
            ]
        )
        == 0
    )
    conn = duckdb.connect(str(tmp_path / "catalog.duckdb"), read_only=True)
    try:
        assert conn.execute("SELECT count(*) FROM thunderbird.messages").fetchone()[0] == 3
    finally:
        conn.close()
