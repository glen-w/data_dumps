"""LinkedIn GDPR ingest smoke tests."""

import zipfile
from pathlib import Path

import duckdb

from data_dumps.ingest import main, pick_source
from data_dumps.linkedin_queries import (
    FilterState,
    activity_mix,
    career_timeline,
    connections_by_year,
    data_bounds,
    messages_by_conversation,
    scoreboard,
)
from data_dumps.paths import raw_dir
from data_dumps.sources.base import Source
from data_dumps.sources.linkedin import LinkedInSource

FORBIDDEN_COLUMNS = {
    "email",
    "email_address",
    "ip",
    "ip_address",
    "last_ip",
    "phone",
    "phone_number",
    "address",
    "birth_date",
    "invoice_number",
    "payment_method_type",
}

CONNECTIONS_CSV = """Notes:
"When exporting your connection data, some emails are missing."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Ada,Lovelace,https://www.linkedin.com/in/ada,ada@example.com,Analytical Engines,Mathematician,05 Sep 2026
Alan,Turing,https://www.linkedin.com/in/alan,,Bletchley Park,Cryptanalyst,03 Jan 2020
"""

MESSAGES_CSV = """CONVERSATION ID,CONVERSATION TITLE,FROM,SENDER PROFILE URL,TO,RECIPIENT PROFILE URLS,DATE,SUBJECT,CONTENT,FOLDER,ATTACHMENTS
c1,Ada,Glen Wright,https://linkedin.com/in/glen,Ada Lovelace,https://linkedin.com/in/ada,2026-08-31 21:20:46 UTC,Hi,Hello Ada,INBOX,
c1,Ada,Ada Lovelace,https://linkedin.com/in/ada,Glen Wright,https://linkedin.com/in/glen,2026-08-31 21:21:00 UTC,,Hello Glen,INBOX,
"""

POSITIONS_CSV = """Company Name,Title,Description,Location,Started On,Finished On
Sciences Po,Adjunct Professor,,Paris,Jan 2015,
REN21,Knowledge & Data,,Paris,Jul 2023,Feb 2026
"""

INVITATIONS_CSV = """From,To,Sent At,Message,Direction,inviterProfileUrl,inviteeProfileUrl
Glen Wright,Ada Lovelace,"9/5/26, 1:12 AM",,OUTGOING,https://www.linkedin.com/in/glen,https://www.linkedin.com/in/ada
"""

REACTIONS_CSV = """Date,Type,Link
2026-09-05 09:50:45,LIKE,https://www.linkedin.com/feed/update/urn
"""

SHARES_CSV = """Date,ShareLink,ShareCommentary,SharedUrl,MediaUrl,Visibility
2025-11-19 09:59:30,https://linkedin.com/share/1,Interesting,,,MEMBER_NETWORK
"""

COMMENTS_CSV = """Date,Link,Message
2026-06-30 10:26:45,https://linkedin.com/c/1,Congratulations!
"""

COMPANY_FOLLOWS_CSV = """Organization,Followed On
GESAMP,Sat Sep 05 08:12:14 UTC 2026
"""

LOGINS_CSV = """Login Date,IP Address,User Agent,Login Type
2026-01-01,203.0.113.9,Mozilla,PASSWORD
"""

EMAILS_CSV = """Email Address,Confirmed,Primary,Updated On
secret@example.com,Yes,Yes,2020-01-01
"""


def make_mini_linkedin_zip(path: Path) -> Path:
    zip_path = path / "mini_linkedin.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Connections.csv", CONNECTIONS_CSV)
        zf.writestr("messages.csv", MESSAGES_CSV)
        zf.writestr("Positions.csv", POSITIONS_CSV)
        zf.writestr("Invitations.csv", INVITATIONS_CSV)
        zf.writestr("Reactions_1.csv", REACTIONS_CSV)
        zf.writestr("Shares_1.csv", SHARES_CSV)
        zf.writestr("Comments_1.csv", COMMENTS_CSV)
        zf.writestr("Company Follows.csv", COMPANY_FOLLOWS_CSV)
        zf.writestr("Logins.csv", LOGINS_CSV)
        zf.writestr("Email Addresses.csv", EMAILS_CSV)
    return zip_path


def _all_columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'linkedin'
        """).fetchall()
    return {r[0].lower() for r in rows}


def test_detect_zip(tmp_path):
    zip_path = make_mini_linkedin_zip(tmp_path)
    source = LinkedInSource()
    assert source.detect(zip_path)
    assert isinstance(source, Source)
    picked = pick_source(zip_path)
    assert picked is not None and picked.name == "linkedin"


def test_detect_rejects_unrelated(tmp_path):
    (tmp_path / "notes.txt").write_text("nope")
    assert not LinkedInSource().detect(tmp_path)
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "hi")
    assert not LinkedInSource().detect(zip_path)


def test_load_strips_email_and_skips_logins(tmp_path):
    zip_path = make_mini_linkedin_zip(tmp_path)
    db_path = tmp_path / "ingest.duckdb"
    conn = duckdb.connect(str(db_path))
    source = LinkedInSource()
    source.load(zip_path, conn)
    inv = source.inventory(conn)
    assert inv["n_connections"] == 2
    assert inv["n_messages"] == 2
    assert inv["n_reactions"] == 1
    assert inv["n_shares"] == 1
    assert inv["n_comments"] == 1

    cols = _all_columns(conn)
    leaked = cols & FORBIDDEN_COLUMNS
    assert not leaked, f"PII columns survived ingest: {leaked}"

    emails_in_values = conn.execute("""
        SELECT count(*) FROM linkedin.connections
        WHERE first_name ILIKE '%@%' OR last_name ILIKE '%@%'
           OR company ILIKE '%@%' OR position ILIKE '%@%'
           OR profile_url ILIKE '%@%'
        """).fetchone()
    assert emails_in_values is not None and emails_in_values[0] == 0

    me = conn.execute("SELECT display_name FROM linkedin.account").fetchone()
    assert me is not None and me[0] == "Glen Wright"

    from_me = conn.execute(
        "SELECT count(*) FROM linkedin.messages WHERE is_from_me"
    ).fetchone()
    assert from_me is not None and from_me[0] == 1

    n_pos = conn.execute("SELECT count(*) FROM linkedin.positions").fetchone()
    assert n_pos is not None and n_pos[0] == 2

    raw_names = {p.name.lower() for p in raw_dir("linkedin").iterdir()}
    assert "logins.csv" not in raw_names
    assert "email addresses.csv" not in raw_names
    assert "connections.csv" in raw_names

    kinds = set(source.tables())
    present = {f"{r[0]}.{r[1]}" for r in conn.execute("""
            SELECT table_schema, table_name FROM information_schema.tables
            WHERE table_schema = 'linkedin'
            """).fetchall()}
    assert kinds == present
    conn.close()


def test_cli_ingest_zip(tmp_path):
    zip_path = make_mini_linkedin_zip(tmp_path)
    db_path = tmp_path / "catalog.duckdb"
    rc = main([str(zip_path), "--db", str(db_path)])
    assert rc == 0
    conn = duckdb.connect(str(db_path), read_only=True)
    n = conn.execute("SELECT count(*) FROM linkedin.connections").fetchone()
    assert n is not None and n[0] == 2
    conn.close()


def test_linkedin_queries(tmp_path):
    zip_path = make_mini_linkedin_zip(tmp_path)
    db_path = tmp_path / "q.duckdb"
    conn = duckdb.connect(str(db_path))
    LinkedInSource().load(zip_path, conn)
    bounds = data_bounds(conn)
    assert bounds["min_year"] <= 2020
    assert bounds["display_name"] == "Glen Wright"
    f = FilterState()
    score = scoreboard(conn, f)
    assert score.iloc[0]["connections"] == 2
    assert score.iloc[0]["messages"] == 2
    by_year = connections_by_year(conn, f)
    assert 2026 in set(by_year["year"].tolist())
    career = career_timeline(conn)
    assert "Sciences Po" in career["org"].tolist()
    conv = messages_by_conversation(conn, f)
    assert not conv.empty
    mix = activity_mix(conn, f)
    assert {"reaction", "share", "comment"} <= set(mix["kind"].tolist())
    conn.close()
