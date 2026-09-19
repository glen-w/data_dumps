"""Every email address in the local exports, with where it came from.

Source dashboards still omit addresses. This module only reads: warehouse text
already ingested, account files those loaders skip, other people's profile and
contact rows, and Thunderbird message bodies (addresses only — the body text is
not stored). Results are cached under the data root, never in git.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sqlite3
import sys
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from data_dumps.paths import data_root, warehouse_db
from data_dumps.query_util import has_table
from data_dumps.sources.thunderbird_gloda import (
    GLODA_DB_NAME,
    resolve_gloda_paths,
    snapshot_gloda,
)

# Loose enough for SQL and prose; ``normalize_email`` drops file-name lookalikes.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)
_SQL_EMAIL_RE = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
_BAD_TLD = frozenset(
    {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "svg",
        "css",
        "js",
        "webp",
        "ico",
        "woff",
        "woff2",
        "ttf",
        "map",
    }
)
_SKIP_VALUES = frozenset({"", "n/a", "na", "none", "null", "not available"})
_MAX_MEMBER = 20 * 1024 * 1024
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_YTD_RE = re.compile(r"^window\.YTD\.[^=]+=\s*", re.MULTILINE)
_GOOGLE_LABELS = (
    ("alternate e-mails", "alternate email"),
    ("alternate e-mail", "alternate email"),
    ("recovery e-mail", "recovery email"),
    ("contact e-mail", "contact email"),
    ("e-mail", "account email"),
)

COLUMNS = ("Service", "Provenance / use", "Email address")


@dataclass(frozen=True)
class TextScan:
    """One warehouse text column that may mention an address."""

    service: str
    use: str
    schema: str
    table: str
    column: str


# In-text mentions. Header/profile rows are collected separately so the use
# string can say *why* the address is there, not only that it occurred.
TEXT_SCANS: tuple[TextScan, ...] = (
    TextScan("ChatGPT", "mentioned in chat", "chatgpt", "messages", "text"),
    TextScan("Telegram", "mentioned in message", "telegram", "messages", "text"),
    TextScan("Slack", "mentioned in message", "slack", "messages", "text"),
    TextScan("LinkedIn", "mentioned in message", "linkedin", "messages", "content"),
    TextScan("LinkedIn", "mentioned in subject", "linkedin", "messages", "subject"),
    TextScan(
        "LinkedIn", "mentioned in invitation", "linkedin", "invitations", "message"
    ),
    TextScan("LinkedIn", "mentioned in comment", "linkedin", "comments", "message"),
    TextScan("LinkedIn", "mentioned in share", "linkedin", "shares", "commentary"),
    TextScan("Twitter", "mentioned in tweet", "twitter", "tweets", "full_text"),
    TextScan(
        "Twitter", "mentioned in direct message", "twitter", "dm_messages", "text"
    ),
    TextScan("Twitter", "mentioned in liked tweet", "twitter", "likes", "full_text"),
    TextScan(
        "Twitter",
        "mentioned in deleted tweet",
        "twitter",
        "deleted_tweets",
        "full_text",
    ),
    TextScan(
        "Thunderbird", "mentioned in subject", "thunderbird", "messages", "subject"
    ),
    TextScan("Browser", "mentioned in page URL", "browser", "pages", "url"),
    TextScan("Browser", "mentioned in page title", "browser", "pages", "title"),
    TextScan("Google", "mentioned in activity", "google", "activity", "title"),
    TextScan("Google", "mentioned in activity URL", "google", "activity", "url"),
    TextScan("Google", "mentioned in task", "google", "tasks", "title"),
    TextScan("Uber", "support ticket creator", "uber", "support_messages", "creator"),
    TextScan(
        "Uber", "mentioned in support message", "uber", "support_messages", "body"
    ),
    TextScan("Airbnb", "mentioned in review", "airbnb", "reviews", "comment"),
)


@dataclass(frozen=True)
class EmailHit:
    service: str
    use: str
    email: str


def normalize_email(value: str | None) -> str | None:
    """Return a lowercase address, or None if this is not one."""
    if value is None:
        return None
    text = str(value).strip().strip("<>\"'()[]{}").lower().rstrip(".,;:)")
    if not text or text in _SKIP_VALUES:
        return None
    match = _EMAIL_RE.search(text)
    if match is None:
        return None
    email = match.group(0).lower().rstrip(".,;:)")
    local, sep, domain = email.partition("@")
    if not sep or not local or "." not in domain:
        return None
    tld = domain.rsplit(".", 1)[-1]
    if tld in _BAD_TLD or len(email) > 254 or len(local) > 64:
        return None
    return email


def find_emails(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _EMAIL_RE.findall(text or ""):
        email = normalize_email(match)
        if email and email not in seen:
            seen.add(email)
            found.append(email)
    return found


def _mention_use(base: str, n: int) -> str:
    noun = "mention" if n == 1 else "mentions"
    return f"{base} ({n} {noun})"


def _q(name: str) -> str:
    if not _IDENT.fullmatch(name):
        raise ValueError(f"unsafe identifier: {name}")
    return '"' + name + '"'


def _has_column(
    conn: duckdb.DuckDBPyConnection, schema: str, table: str, column: str
) -> bool:
    row = conn.execute(
        """
        SELECT count(*) FROM information_schema.columns
        WHERE table_schema = ? AND table_name = ? AND lower(column_name) = lower(?)
        """,
        [schema, table, column],
    ).fetchone()
    return row is not None and row[0] > 0


def scan_text_columns(conn: duckdb.DuckDBPyConnection) -> list[EmailHit]:
    """Addresses mentioned inside text the warehouse already stores."""
    hits: list[EmailHit] = []
    for scan in TEXT_SCANS:
        if not has_table(conn, scan.schema, scan.table):
            continue
        if not _has_column(conn, scan.schema, scan.table, scan.column):
            continue
        sql = f"""
            SELECT email, count(*)::BIGINT
            FROM (
                SELECT unnest(regexp_extract_all({_q(scan.column)}, ?)) AS email
                FROM {_q(scan.schema)}.{_q(scan.table)}
                WHERE {_q(scan.column)} LIKE '%@%'
            )
            GROUP BY 1
            """
        counts: dict[str, int] = defaultdict(int)
        for raw, n in conn.execute(sql, [_SQL_EMAIL_RE]).fetchall():
            email = normalize_email(raw)
            if email:
                counts[email] += int(n)
        for email, n in counts.items():
            hits.append(EmailHit(scan.service, _mention_use(scan.use, n), email))
    return hits


def scan_thunderbird_headers(conn: duckdb.DuckDBPyConnection) -> list[EmailHit]:
    """Identities and from/to addresses already stored as mail metadata."""
    hits: list[EmailHit] = []
    if has_table(conn, "thunderbird", "accounts") and _has_column(
        conn, "thunderbird", "accounts", "email"
    ):
        rows = conn.execute("""
            SELECT DISTINCT lower(trim(email))
            FROM thunderbird.accounts
            WHERE email IS NOT NULL AND trim(email) <> ''
            """).fetchall()
        for (raw,) in rows:
            email = normalize_email(raw)
            if email:
                hits.append(EmailHit("Thunderbird", "mail identity", email))
    if not has_table(conn, "thunderbird", "participants"):
        return hits
    if not _has_column(conn, "thunderbird", "participants", "addr"):
        return hits
    grouped = conn.execute("""
        SELECT lower(trim(addr)),
               coalesce(role, ''),
               any_value(display_name),
               count(*)::BIGINT
        FROM thunderbird.participants
        WHERE addr IS NOT NULL AND trim(addr) <> ''
        GROUP BY 1, 2
        """).fetchall()
    for raw, role, name, n in grouped:
        email = normalize_email(raw)
        if not email:
            continue
        label = {"from": "from", "to": "to"}.get(str(role), str(role) or "participant")
        use = f"correspondent, {label}"
        display = str(name).strip() if name else ""
        if display and "@" not in display and display.lower() != email:
            use = f"{use} · {display}"
        noun = "message" if int(n) == 1 else "messages"
        hits.append(EmailHit("Thunderbird", f"{use} ({int(n)} {noun})", email))
    return hits


def discover_gloda() -> Path | None:
    """Thunderbird global index, if this machine has one."""
    if os.environ.get("DATA_DUMPS_SKIP_GLODA") == "1":
        return None
    explicit = os.environ.get("DATA_DUMPS_TB_PROFILE")
    if explicit:
        try:
            return resolve_gloda_paths(Path(explicit).expanduser())[0]
        except (OSError, FileNotFoundError):
            return None
    roots = (
        Path.home() / "Library" / "Thunderbird" / "Profiles",
        Path.home() / ".thunderbird",
        Path.home() / "snap" / "thunderbird" / "common" / ".thunderbird",
    )
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        direct = root / GLODA_DB_NAME
        if direct.is_file():
            found.append(direct)
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            candidate = child / GLODA_DB_NAME
            if child.is_dir() and candidate.is_file():
                found.append(candidate)
    if not found:
        return None
    return max(found, key=lambda path: path.stat().st_mtime)


def _body_column(con: sqlite3.Connection) -> str | None:
    cols = {row[1] for row in con.execute("PRAGMA table_info(messagesText_content)")}
    if "c0body" in cols and "c1subject" in cols:
        return "c0body"
    if "c1body" in cols:
        return "c1body"
    return None


def _open_gloda(path: Path) -> tuple[sqlite3.Connection, Path | None]:
    uri = f"file:{path.resolve()}?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.execute("SELECT 1 FROM messagesText_content LIMIT 1")
        return con, None
    except sqlite3.Error:
        snap = snapshot_gloda(path)
        con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
        return con, snap


def scan_gloda_bodies(path: Path) -> list[EmailHit]:
    """Addresses that appear only inside mail bodies. Bodies are not kept."""
    con, snap = _open_gloda(path)
    try:
        column = _body_column(con)
        if column is None or not _IDENT.fullmatch(column):
            return []
        counts: dict[str, int] = defaultdict(int)
        query = f"""
            SELECT {column}
            FROM messagesText_content
            WHERE {column} LIKE '%@%'
            """
        for (body,) in con.execute(query):
            if not body:
                continue
            for email in find_emails(str(body)):
                counts[email] += 1
        return [
            EmailHit("Thunderbird", _mention_use("mentioned in message body", n), email)
            for email, n in counts.items()
        ]
    finally:
        con.close()
        if snap is not None:
            snap.unlink(missing_ok=True)


def _is_zip(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".zip") or name.endswith(".zip.zip")


def iter_members(
    path: Path,
    member_ok: Callable[[str], bool],
    loose_globs: tuple[str, ...] = (),
) -> Iterator[tuple[str, bytes]]:
    """Yield ``(relative name, bytes)`` from a zip, a folder of zips, or loose files."""
    path = path.resolve()
    if not path.exists():
        return
    if path.is_file():
        if _is_zip(path):
            yield from _iter_zip(path, member_ok)
            return
        rel = path.name
        if member_ok(rel) and path.stat().st_size <= _MAX_MEMBER:
            yield rel, path.read_bytes()
        return
    zips = sorted(
        child for child in path.iterdir() if child.is_file() and _is_zip(child)
    )
    if zips:
        for archive in zips:
            yield from _iter_zip(archive, member_ok)
        return
    for pattern in loose_globs:
        for child in path.glob(pattern):
            if not child.is_file():
                continue
            rel = child.relative_to(path).as_posix()
            if not member_ok(rel) or child.stat().st_size > _MAX_MEMBER:
                continue
            yield rel, child.read_bytes()


def _iter_zip(
    path: Path, member_ok: Callable[[str], bool]
) -> Iterator[tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not member_ok(name) or info.file_size > _MAX_MEMBER:
                continue
            yield name, archive.read(info)


def _csv_rows(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    start = 0
    for index, line in enumerate(lines[:40]):
        lower = line.lower()
        # Header row names the email column. A data row also contains an address.
        if "email" in lower and "," in line and _EMAIL_RE.search(line) is None:
            start = index
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    return [
        row for row in reader if any((value or "").strip() for value in row.values())
    ]


def _csv_get(row: Mapping[str, str | None], *names: str) -> str | None:
    lower = {(key or "").strip().lower(): key for key in row}
    for name in names:
        key = lower.get(name.lower())
        if key is None:
            continue
        value = (row.get(key) or "").strip()
        if value.lower() in _SKIP_VALUES:
            continue
        return value
    return None


def _keep(service: str, use: str, raw: str | None, into: list[EmailHit]) -> None:
    email = normalize_email(raw)
    if email:
        into.append(EmailHit(service, use, email))


def _parse_ytd(data: bytes) -> Any:
    text = data.decode("utf-8", errors="replace")
    body = _YTD_RE.sub("", text, count=1).strip()
    if body.endswith(";"):
        body = body[:-1].strip()
    return json.loads(body)


def _google_label_hits(html: str) -> list[tuple[str, str]]:
    text = re.sub(r"<[^>]+>", "\n", html)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    found: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        lower = line.lower()
        for label, use in _GOOGLE_LABELS:
            if lower == label or lower.startswith(label + ":"):
                blob = line.split(":", 1)[1] if ":" in line else ""
                if not _EMAIL_RE.search(blob) and index + 1 < len(lines):
                    blob = lines[index + 1]
                for email in find_emails(blob):
                    found.append((use, email))
                break
    return found


def _vcf_cards(text: str) -> list[tuple[str, list[str]]]:
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    cards = re.split(r"(?im)^BEGIN:VCARD\s*", unfolded)
    parsed: list[tuple[str, list[str]]] = []
    for card in cards:
        name_match = re.search(r"(?im)^FN[^:\r\n]*:(.+)$", card)
        name = name_match.group(1).strip() if name_match else ""
        emails = re.findall(r"(?im)^EMAIL[^:\r\n]*:([^\r\n]+)", card)
        if emails:
            parsed.append((name, emails))
    return parsed


def _basename(name: str) -> str:
    return Path(name).name.lower()


def extract_linkedin(path: Path) -> list[EmailHit]:
    hits: list[EmailHit] = []
    for _name, data in iter_members(
        path, lambda name: _basename(name) == "email addresses.csv"
    ):
        for row in _csv_rows(data):
            raw = _csv_get(row, "email address", "email")
            if not raw:
                continue
            primary = (_csv_get(row, "primary") or "").lower() == "yes"
            confirmed = (_csv_get(row, "confirmed") or "").lower() == "yes"
            if primary:
                use = "primary account email"
            elif confirmed:
                use = "confirmed account email"
            else:
                use = "unconfirmed account email"
            _keep("LinkedIn", use, raw, hits)
    return hits


def extract_spotify(path: Path) -> list[EmailHit]:
    hits: list[EmailHit] = []

    def ok(name: str) -> bool:
        base = _basename(name)
        return base in {"userattributes.json", "identifiers.json"}

    for name, data in iter_members(path, ok):
        try:
            obj = json.loads(data.decode("utf-8-sig"))
        except json.JSONDecodeError:
            continue
        base = _basename(name)
        if base == "userattributes.json" and isinstance(obj, dict):
            _keep("Spotify", "account email", obj.get("email"), hits)
        elif base == "identifiers.json":
            items = obj if isinstance(obj, list) else [obj]
            for item in items:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("identifierType") or "")
                if "email" in kind.lower():
                    _keep(
                        "Spotify",
                        "account identifier",
                        item.get("identifierValue"),
                        hits,
                    )
    return hits


def extract_chatgpt_account(path: Path) -> list[EmailHit]:
    hits: list[EmailHit] = []
    for _name, data in iter_members(path, lambda name: _basename(name) == "user.json"):
        try:
            obj = json.loads(data.decode("utf-8-sig"))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            _keep("ChatGPT", "account email", obj.get("email"), hits)
    return hits


def extract_uber(path: Path) -> list[EmailHit]:
    hits: list[EmailHit] = []

    def ok(name: str) -> bool:
        base = _basename(name)
        return base.startswith("user_profile") and base.endswith(".csv")

    for _name, data in iter_members(path, ok):
        for row in _csv_rows(data):
            _keep("Uber", "account email", _csv_get(row, "e-mail", "email"), hits)
    return hits


def extract_twitter(path: Path) -> list[EmailHit]:
    hits: list[EmailHit] = []
    globs = (
        "data/account.js",
        "data/email-address-change.js",
        "*/data/account.js",
        "*/data/email-address-change.js",
    )

    def ok(name: str) -> bool:
        base = _basename(name)
        return base in {"account.js", "email-address-change.js"} or base.startswith(
            "account.part"
        )

    for _name, data in iter_members(path, ok, globs):
        try:
            payload = _parse_ytd(data)
        except json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            account = item.get("account")
            if isinstance(account, dict):
                _keep("Twitter", "account email", account.get("email"), hits)
            change = item.get("emailAddressChange")
            if isinstance(change, dict):
                inner = change.get("emailChange")
                rows = inner if isinstance(inner, list) else [inner]
                for row in rows:
                    if isinstance(row, dict):
                        _keep("Twitter", "address change", row.get("changedTo"), hits)
    return hits


def extract_airbnb(path: Path) -> list[EmailHit]:
    from data_dumps.sources.airbnb import _kv_map, _parse_html_tables

    hits: list[EmailHit] = []
    globs = (
        "html/profile_information.html",
        "*/html/profile_information.html",
    )

    def ok(name: str) -> bool:
        return _basename(name) == "profile_information.html"

    for _name, data in iter_members(path, ok, globs):
        tables = _parse_html_tables(data.decode("utf-8", errors="replace"))
        for title, headers, rows in tables:
            if title.strip().lower() != "user":
                continue
            if "key" not in [header.lower() for header in headers]:
                continue
            kv = {key.lower(): value for key, value in _kv_map(rows).items()}
            _keep("Airbnb", "account email", kv.get("email"), hits)
    return hits


def extract_ring(path: Path) -> list[EmailHit]:
    hits: list[EmailHit] = []

    def ok(name: str) -> bool:
        low = name.lower()
        base = _basename(low)
        if base == "users.json" and "useraccount" in low:
            return True
        return base == "users.csv" and "ring_users" in low

    for name, data in iter_members(path, ok):
        if _basename(name) == "users.csv":
            for row in _csv_rows(data):
                _keep(
                    "Ring",
                    "account email",
                    _csv_get(row, "email address", "email"),
                    hits,
                )
            continue
        try:
            obj = json.loads(data.decode("utf-8-sig"))
        except json.JSONDecodeError:
            continue
        items = obj if isinstance(obj, list) else [obj]
        for item in items:
            if isinstance(item, dict):
                _keep(
                    "Ring",
                    "account email",
                    item.get("Email") or item.get("email"),
                    hits,
                )
    return hits


def extract_duolingo(path: Path) -> list[EmailHit]:
    hits: list[EmailHit] = []
    for _name, data in iter_members(
        path,
        lambda name: _basename(name) == "profile.csv",
        ("profile.csv", "*/profile.csv"),
    ):
        rows = _csv_rows(data)
        if (
            rows
            and _csv_get(rows[0], "name")
            and "value" in {(key or "").lower() for key in rows[0]}
        ):
            for row in rows:
                if (_csv_get(row, "name") or "").lower() == "email":
                    _keep("Duolingo", "account email", _csv_get(row, "value"), hits)
        else:
            for row in rows:
                _keep("Duolingo", "account email", _csv_get(row, "email"), hits)
    return hits


def extract_slack_profiles(path: Path) -> list[EmailHit]:
    """Workspace member addresses. These stay off the Slack dashboard."""
    hits: list[EmailHit] = []
    for _name, data in iter_members(path, lambda name: _basename(name) == "users.json"):
        try:
            payload = json.loads(data.decode("utf-8-sig"))
        except json.JSONDecodeError:
            continue
        users = payload if isinstance(payload, list) else []
        for user in users:
            if not isinstance(user, dict):
                continue
            profile = user.get("profile") or {}
            if not isinstance(profile, dict):
                continue
            raw = profile.get("email")
            name = (
                profile.get("display_name")
                or user.get("real_name")
                or profile.get("real_name")
                or user.get("name")
                or ""
            )
            name = str(name).strip()
            kind = "bot profile" if user.get("is_bot") else "user profile"
            if user.get("deleted"):
                kind += ", deactivated"
            use = f"{kind} · {name}" if name else kind
            _keep("Slack", use, raw if isinstance(raw, str) else None, hits)
    return hits


def extract_google(path: Path) -> list[EmailHit]:
    hits: list[EmailHit] = []

    def ok(name: str) -> bool:
        low = name.lower()
        base = _basename(low)
        return (
            low.endswith("profile/profile.json")
            or base.endswith("subscriberinfo.html")
            or low.endswith(".vcf")
        )

    for name, data in iter_members(path, ok):
        low = name.lower()
        text = data.decode("utf-8", errors="replace")
        if low.endswith("profile/profile.json"):
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            emails = obj.get("emails") if isinstance(obj, dict) else None
            if isinstance(emails, list):
                for item in emails:
                    if isinstance(item, dict):
                        _keep("Google", "profile email", item.get("value"), hits)
                    elif isinstance(item, str):
                        _keep("Google", "profile email", item, hits)
        elif low.endswith("subscriberinfo.html"):
            for use, email in _google_label_hits(text):
                _keep("Google", use, email, hits)
        elif low.endswith(".vcf"):
            for card_name, emails in _vcf_cards(text):
                use = f"contact · {card_name}" if card_name else "contact"
                for email in emails:
                    _keep("Google", use, email, hits)
    return hits


def extract_amazon(path: Path) -> list[EmailHit]:
    hits: list[EmailHit] = []
    eml_counts: dict[str, int] = defaultdict(int)

    def ok(name: str) -> bool:
        low = name.lower()
        base = _basename(low)
        if base.endswith(".eml"):
            return True
        if base in {"retail.customercontacts.json", "amazon pay account.csv"}:
            return True
        if "approvedpersonaldocumentemaillist" in base:
            return True
        if base.startswith("calendars") and base.endswith(".csv"):
            return True
        return "communications/contacts/" in low and base.endswith(".csv")

    for name, data in iter_members(path, ok):
        low = name.lower()
        base = _basename(low)
        if base.endswith(".eml"):
            for email in find_emails(data.decode("utf-8", errors="replace")):
                eml_counts[email] += 1
            continue
        if base == "retail.customercontacts.json":
            try:
                obj = json.loads(data.decode("utf-8-sig"))
            except json.JSONDecodeError:
                continue
            items = obj if isinstance(obj, list) else [obj]
            for item in items:
                if isinstance(item, dict):
                    _keep("Amazon", "account contact", item.get("Email"), hits)
            continue
        if base.endswith(".csv"):
            for row in _csv_rows(data):
                if "approvedpersonaldocumentemaillist" in base:
                    _keep(
                        "Amazon",
                        "Kindle approved sender",
                        _csv_get(row, "email address"),
                        hits,
                    )
                elif base == "amazon pay account.csv":
                    _keep(
                        "Amazon", "Amazon Pay account", _csv_get(row, "email id"), hits
                    )
                elif base.startswith("calendars"):
                    _keep(
                        "Amazon",
                        "Alexa linked calendar",
                        _csv_get(row, "account email id"),
                        hits,
                    )
                elif "communications/contacts/" in low:
                    who = " ".join(
                        part
                        for part in (
                            _csv_get(row, "first name") or "",
                            _csv_get(row, "last name") or "",
                        )
                        if part
                    ).strip()
                    use = f"Alexa contact · {who}" if who else "Alexa contact"
                    _keep("Amazon", use, _csv_get(row, "email address"), hits)
    for email, n in eml_counts.items():
        noun = "file" if n == 1 else "files"
        hits.append(
            EmailHit("Amazon", f"mentioned in Amazon email ({n} {noun})", email)
        )
    return hits


_EXTRACTORS: dict[str, Callable[[Path], list[EmailHit]]] = {
    "linkedin": extract_linkedin,
    "spotify_account": extract_spotify,
    "chatgpt": extract_chatgpt_account,
    "uber": extract_uber,
    "twitter": extract_twitter,
    "airbnb": extract_airbnb,
    "ring": extract_ring,
    "duolingo": extract_duolingo,
    "slack": extract_slack_profiles,
    "google": extract_google,
    "amazon": extract_amazon,
}


def _newest(paths: list[Path], prefer: str | None = None) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if prefer:
        preferred = [path for path in existing if prefer in path.name.lower()]
        if preferred:
            existing = preferred
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _zip_hits(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted([*folder.glob("*.zip"), *folder.glob("*.zip.zip")])


def discover_exports(root: Path | None = None) -> list[tuple[str, Path]]:
    """Original dumps (not the scrubbed ``raw/`` copies, except Slack users)."""
    root = root or data_root()
    found: list[tuple[str, Path]] = []

    def add(slug: str, path: Path | None) -> None:
        if path is not None and path.exists():
            found.append((slug, path))

    add("linkedin", _newest(_zip_hits(root / "linkedin"), prefer="complete"))
    add("spotify_account", _newest(_zip_hits(root / "spotify"), prefer="account"))
    add("chatgpt", _newest(_zip_hits(root / "chatgpt")))
    add("uber", _newest(_zip_hits(root / "uber")))
    add("airbnb", _newest(_zip_hits(root / "airbnb")))
    add("ring", _newest(_zip_hits(root / "ring")))
    add("duolingo", _newest(_zip_hits(root / "duolingo")))
    users = root / "raw" / "slack" / "users.json"
    add("slack", users if users.is_file() else _newest(_zip_hits(root / "slack")))
    twitter = root / "twitter"
    if (twitter / "data" / "account.js").is_file():
        add("twitter", twitter)
    elif twitter.is_dir():
        for child in sorted(twitter.iterdir()):
            if (child / "data" / "account.js").is_file():
                add("twitter", child)
                break
    google = root / "google"
    if any(google.glob("takeout-*.zip")):
        add("google", google)
    amazon = root / "amazon"
    if _zip_hits(amazon):
        add("amazon", amazon)
    return found


def scan_exports(root: Path | None = None) -> list[EmailHit]:
    hits: list[EmailHit] = []
    for slug, path in discover_exports(root):
        extract = _EXTRACTORS.get(slug)
        if extract is None:
            continue
        try:
            hits.extend(extract(path))
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeError):
            continue
    return hits


def _dedupe(hits: list[EmailHit]) -> list[EmailHit]:
    seen: set[tuple[str, str, str]] = set()
    out: list[EmailHit] = []
    for hit in hits:
        key = (hit.service, hit.use, hit.email)
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    out.sort(key=lambda hit: (hit.service.casefold(), hit.use.casefold(), hit.email))
    return out


def hits_frame(hits: list[EmailHit]) -> pd.DataFrame:
    rows = [
        {
            "Service": hit.service,
            "Provenance / use": hit.use,
            "Email address": hit.email,
        }
        for hit in _dedupe(hits)
    ]
    return pd.DataFrame(rows, columns=list(COLUMNS))


def _note(*, gloda_scanned: bool) -> str:
    text = (
        "Every address found in ingested text, in files the source tabs skip, "
        "and on other people's profiles and contacts. "
        "The same address is repeated once per place it showed up, so you can see why it is there. "
        "Source dashboards still do not show these."
    )
    if gloda_scanned:
        text += " Mail bodies were read from the Thunderbird index; the text itself is not stored."
    else:
        text += (
            " Mail bodies were not scanned. Header from/to addresses are included when Thunderbird is ingested."
            " Set `DATA_DUMPS_TB_PROFILE` to the profile folder to include addresses that appear only inside messages."
        )
    return text


def _cache_path() -> Path:
    return data_root() / "warehouse" / "email_inventory.json"


def _stamps(exports: list[tuple[str, Path]], gloda: Path | None) -> list[list[object]]:
    paths: list[Path] = []
    db = warehouse_db()
    if db.is_file():
        paths.append(db)
    if gloda is not None and gloda.is_file():
        paths.append(gloda)
    for _slug, path in exports:
        if path.is_file():
            paths.append(path)
        elif path.is_dir():
            zips = _zip_hits(path)
            paths.extend(zips or [path])
    stamps: list[list[object]] = []
    for path in paths:
        try:
            stamps.append([str(path), path.stat().st_mtime_ns])
        except OSError:
            continue
    stamps.sort()
    return stamps


def _read_cache(
    path: Path, stamps: list[list[object]]
) -> tuple[pd.DataFrame, str] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if payload.get("stamps") != stamps:
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None
    frame = pd.DataFrame(rows, columns=list(COLUMNS))
    note = _note(gloda_scanned=bool(payload.get("gloda_scanned")))
    return frame, note


def _write_cache(
    path: Path,
    stamps: list[list[object]],
    frame: pd.DataFrame,
    *,
    gloda_scanned: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stamps": stamps,
        "gloda_scanned": gloda_scanned,
        "rows": frame.to_dict(orient="records"),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def collect_hits(
    conn: duckdb.DuckDBPyConnection,
    *,
    root: Path | None = None,
    gloda: Path | None = None,
    scan_disk: bool = True,
    scan_mail_bodies: bool = True,
) -> tuple[list[EmailHit], bool]:
    hits = scan_text_columns(conn)
    hits.extend(scan_thunderbird_headers(conn))
    gloda_scanned = False
    if scan_disk:
        hits.extend(scan_exports(root))
    if scan_mail_bodies:
        mail_index = gloda if gloda is not None else discover_gloda()
        if mail_index is not None and mail_index.is_file():
            try:
                hits.extend(scan_gloda_bodies(mail_index))
                gloda_scanned = True
            except (OSError, sqlite3.Error):
                gloda_scanned = False
    return _dedupe(hits), gloda_scanned


def inventory_frame(
    conn: duckdb.DuckDBPyConnection,
    *,
    force: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Table for the Tools tab. Uses the on-disk cache when exports have not changed."""
    gloda = discover_gloda()
    exports = discover_exports()
    stamps = _stamps(exports, gloda)
    cache = _cache_path()
    if not force:
        cached = _read_cache(cache, stamps)
        if cached is not None:
            return cached
    hits, gloda_scanned = collect_hits(conn, gloda=gloda)
    frame = hits_frame(hits)
    try:
        _write_cache(cache, stamps, frame, gloda_scanned=gloda_scanned)
    except OSError:
        pass
    return frame, _note(gloda_scanned=gloda_scanned)


def main(argv: list[str] | None = None) -> int:
    """Print counts only. Addresses stay in the cache file, not the terminal."""
    parser = argparse.ArgumentParser(
        description="Rebuild the Tools email index (counts only on stdout)"
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the cache and scan again",
    )
    args = parser.parse_args(argv)
    db = args.db or warehouse_db()
    if not db.is_file():
        print(f"error: no warehouse at {db}", file=sys.stderr)
        return 1
    conn = duckdb.connect(str(db), read_only=True)
    try:
        frame, note = inventory_frame(conn, force=args.refresh)
    finally:
        conn.close()
    print(f"{len(frame)} rows")
    if not frame.empty:
        counts = frame.groupby("Service").size()
        for service, n in counts.sort_index().items():
            print(f"  {service}: {int(n)}")
    print(note)
    print(f"cache: {_cache_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
