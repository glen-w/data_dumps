"""Thunderbird Gloda (`global-messages-db.sqlite`) read helpers.

Read-only: snapshot via SQLite online-backup (thunderbird-mcp pattern), then
extract message-grain metadata. Never copies or mutates mail dirs / mbox.
Body text (``c0body`` / legacy ``c1body``) is never selected or stored.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.parse
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import getaddresses
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Rome")
GLODA_DB_NAME = "global-messages-db.sqlite"
PREFS_JS = "prefs.js"

# Gloda ``jsonAttributes`` keys (attributeDefinitions.id) — modern Thunderbird.
ATTR_IS_ENCRYPTED = "50"
ATTR_ATTACHMENT_INFOS = "51"
ATTR_FROM_ME = "54"
ATTR_TO_ME = "55"
ATTR_STAR = "58"
ATTR_READ = "59"
ATTR_REPLIED = "60"
ATTR_FORWARDED = "61"

EMAIL_RE = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}"
    r"[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)
GLODA_UNDEFINED_RE = re.compile(r"\s+undefined\s*$", re.IGNORECASE)
PREF_RE = re.compile(
    r'^user_pref\("(?P<key>[^"]+)",\s*(?P<val>.+)\);\s*$'
)

SENT_FOLDER_RE = re.compile(
    r"(^|[/\s\[\]])(sent|sent mail|sent messages|outbox)($|[/\s\]])",
    re.IGNORECASE,
)
DRAFT_FOLDER_RE = re.compile(
    r"(^|[/\s\[\]])(drafts?|templates?)($|[/\s\]])",
    re.IGNORECASE,
)

NEWSLETTER_DOMAINS = frozenset(
    {
        "mailchimp.com",
        "mailchimpapp.net",
        "list-manage.com",
        "campaign-archive.com",
        "sendgrid.net",
        "sendgrid.com",
        "exacttarget.com",
        "exacttargetapis.com",
        "sfmc-content.com",
        "constantcontact.com",
        "ccsend.com",
        "substack.com",
        "beehiiv.com",
        "convertkit.com",
        "ck.page",
        "klaviyo.com",
        "klclick.com",
        "mailerlite.com",
        "mlsend.com",
        "getresponse.com",
        "mailjet.com",
        "sendinblue.com",
        "brevo.com",
        "amazonaws.com",  # SES / bulk often under this; scored lower alone
    }
)
NEWSLETTER_SUBJECT_RE = re.compile(
    r"\b(newsletter|digest|weekly\s+roundup|unsubscribe|"
    r"email\s+preferences|view\s+in\s+(your\s+)?browser)\b",
    re.IGNORECASE,
)
RECEIPT_SUBJECT_RE = re.compile(
    r"\b(receipt|invoice|order\s*#?\s*\d|order\s+confirmation|"
    r"payment\s+(received|confirmed)|your\s+order|purchase\s+confirmation|"
    r"tax\s+invoice|facture|reçu)\b",
    re.IGNORECASE,
)
RECEIPT_ATTACH_RE = re.compile(
    r"(invoice|receipt|facture|order).*\.(pdf|png|jpe?g)$",
    re.IGNORECASE,
)
SUBSCRIPTION_SUBJECT_RE = re.compile(
    r"\b(subscription|renew(al|s|ing)?|membership|"
    r"your\s+plan|billing\s+(statement|update)|auto[- ]?renew)\b",
    re.IGNORECASE,
)
SIGNUP_SUBJECT_RE = re.compile(
    r"\b(verify\s+your\s+e-?mail|confirm\s+your\s+e-?mail|"
    r"activate\s+your\s+account|complete\s+your\s+registration|"
    r"welcome\s+to|confirm\s+your\s+account|email\s+verification)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# Path / profile resolve


def resolve_gloda_paths(path: Path) -> tuple[Path, Path | None]:
    """Return ``(gloda_sqlite, profile_dir_or_none)``.

    Accepts the sqlite file itself, a profile directory that contains it, or a
    parent that contains a profile with the file one level down.
    """
    path = path.expanduser().resolve()
    if path.is_file() and path.name == GLODA_DB_NAME:
        profile = path.parent if (path.parent / PREFS_JS).is_file() else path.parent
        return path, profile
    if path.is_dir():
        direct = path / GLODA_DB_NAME
        if direct.is_file():
            return direct, path
        for child in sorted(path.iterdir()):
            if child.is_dir():
                nested = child / GLODA_DB_NAME
                if nested.is_file():
                    return nested, child
    raise FileNotFoundError(f"no {GLODA_DB_NAME} under {path}")


def looks_like_gloda_path(path: Path) -> bool:
    try:
        resolve_gloda_paths(path)
    except (OSError, FileNotFoundError):
        return False
    return True


# --------------------------------------------------------------------------- #
# Snapshot (online backup)


def snapshot_gloda(
    db_path: Path,
    *,
    retries: int = 5,
    backoff: float = 1.5,
    pages: int = 2000,
    sleep: float = 0.05,
) -> Path:
    """Copy Gloda via ``Connection.backup`` into a tempfile; retry on lock.

    Source is opened read-only + immutable so Thunderbird's WAL is never written.
    Caller must delete the returned path when finished.
    """
    db_path = db_path.resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    fd, tmp_name = tempfile.mkstemp(prefix="gloda_snap_", suffix=".sqlite")
    os.close(fd)
    tmp = Path(tmp_name)
    tmp.unlink(missing_ok=True)

    last_err: Exception | None = None
    for attempt in range(retries):
        src: sqlite3.Connection | None = None
        dst: sqlite3.Connection | None = None
        try:
            src = sqlite3.connect(
                f"file:{db_path}?mode=ro&immutable=1",
                uri=True,
                timeout=15,
            )
            dst = sqlite3.connect(tmp)
            with dst:
                src.backup(dst, pages=pages, sleep=sleep)
            dst.close()
            dst = None
            src.close()
            src = None
            return tmp
        except sqlite3.OperationalError as exc:
            last_err = exc
            for con in (dst, src):
                if con is not None:
                    try:
                        con.close()
                    except sqlite3.Error:
                        pass
            tmp.unlink(missing_ok=True)
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(
        f"could not snapshot {db_path} after {retries} attempts: {last_err}"
    )


# --------------------------------------------------------------------------- #
# Address / prefs parsing


def domain_of(addr: str | None) -> str | None:
    if not addr or "@" not in addr:
        return None
    return addr.rsplit("@", 1)[-1].lower().strip() or None


def parse_address_blob(raw: str | None) -> list[tuple[str | None, str, str | None]]:
    """Parse Gloda author/recipients blobs → ``(display, addr, domain)``."""
    if not raw or not str(raw).strip():
        return []
    text = GLODA_UNDEFINED_RE.sub("", str(raw).strip())
    pairs = getaddresses([text])
    out: list[tuple[str | None, str, str | None]] = []
    seen: set[str] = set()
    for display, addr in pairs:
        addr_l = (addr or "").strip().lower()
        if not addr_l or "@" not in addr_l:
            continue
        if addr_l in seen:
            continue
        seen.add(addr_l)
        name = display.strip() if display and display.strip() else None
        out.append((name, addr_l, domain_of(addr_l)))
    if out:
        return out
    # Fallback: bare emails when getaddresses fails on Gloda quirks.
    for m in EMAIL_RE.finditer(text):
        addr_l = m.group(0).lower()
        if addr_l in seen:
            continue
        seen.add(addr_l)
        out.append((None, addr_l, domain_of(addr_l)))
    return out


def _pref_unquote(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        inner = val[1:-1]
        return (
            inner.replace(r"\\", "\\")
            .replace(r"\"", '"')
            .replace(r"\n", "\n")
        )
    return val


def parse_prefs_identities(prefs_path: Path) -> list[dict[str, Any]]:
    """Parse Thunderbird ``prefs.js`` into account / identity rows."""
    if not prefs_path.is_file():
        return []
    try:
        text = prefs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    prefs: dict[str, str] = {}
    for line in text.splitlines():
        m = PREF_RE.match(line.strip())
        if not m:
            continue
        prefs[m.group("key")] = _pref_unquote(m.group("val"))

    accounts_csv = prefs.get("mail.accountmanager.accounts", "")
    account_keys = [a.strip() for a in accounts_csv.split(",") if a.strip()]
    rows: list[dict[str, Any]] = []
    for account_key in account_keys:
        server_key = prefs.get(f"mail.account.{account_key}.server")
        identities_csv = prefs.get(f"mail.account.{account_key}.identities", "")
        identity_keys = [i.strip() for i in identities_csv.split(",") if i.strip()]
        label = None
        server_type = None
        hostname = None
        if server_key:
            label = prefs.get(f"mail.server.{server_key}.name")
            server_type = prefs.get(f"mail.server.{server_key}.type")
            hostname = prefs.get(f"mail.server.{server_key}.hostname")
        if not identity_keys:
            rows.append(
                {
                    "account_key": account_key,
                    "identity_key": None,
                    "email": None,
                    "full_name": None,
                    "account_label": label,
                    "server_type": server_type,
                    "server_hostname": hostname,
                }
            )
            continue
        for identity_key in identity_keys:
            email = prefs.get(f"mail.identity.{identity_key}.useremail")
            full_name = prefs.get(f"mail.identity.{identity_key}.fullName")
            rows.append(
                {
                    "account_key": account_key,
                    "identity_key": identity_key,
                    "email": email.lower().strip() if email else None,
                    "full_name": full_name,
                    "account_label": label,
                    "server_type": server_type,
                    "server_hostname": hostname,
                }
            )
    return rows


def account_key_from_folder_uri(uri: str | None) -> str | None:
    """Derive a stable account key from ``folderURI`` (URL-decoded username)."""
    if not uri:
        return None
    parsed = urllib.parse.urlparse(uri)
    if parsed.username:
        return urllib.parse.unquote(parsed.username).lower()
    # mailbox://nobody@Local%20Folders/...
    netloc = urllib.parse.unquote(parsed.netloc or "")
    if "@" in netloc:
        user, _, host = netloc.partition("@")
        if user and user.lower() != "nobody":
            return user.lower()
        if host:
            return host.lower()
    return parsed.scheme or None


def identities_from_env() -> set[str]:
    raw = os.environ.get("DATA_DUMPS_TB_IDENTITIES", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


# --------------------------------------------------------------------------- #
# Flags / direction / signals


def parse_json_attributes(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def flags_from_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    attach_infos = attrs.get(ATTR_ATTACHMENT_INFOS) or []
    return {
        "starred": bool(attrs.get(ATTR_STAR)),
        "read": bool(attrs.get(ATTR_READ)),
        "replied": bool(attrs.get(ATTR_REPLIED)),
        "forwarded": bool(attrs.get(ATTR_FORWARDED)),
        "is_encrypted": bool(attrs.get(ATTR_IS_ENCRYPTED)),
        "from_me": bool(attrs.get(ATTR_FROM_ME)),
        "to_me": bool(attrs.get(ATTR_TO_ME)),
        "has_attachment_attr": bool(attach_infos),
    }


def classify_direction(
    *,
    from_addr: str | None,
    identities: set[str],
    folder_name: str | None,
    folder_uri: str | None,
    from_me: bool,
    to_me: bool,
) -> str:
    blob = f"{folder_name or ''} {folder_uri or ''}"
    if SENT_FOLDER_RE.search(blob):
        return "sent"
    if from_me or (from_addr and from_addr in identities):
        return "sent"
    if to_me:
        return "received"
    if identities and from_addr and from_addr not in identities:
        return "received"
    if DRAFT_FOLDER_RE.search(blob):
        return "unknown"
    return "unknown"


def _domain_matches(domain: str | None, needles: Iterable[str]) -> bool:
    if not domain:
        return False
    d = domain.lower()
    for n in needles:
        if d == n or d.endswith("." + n):
            return True
    return False


def detect_signals(
    *,
    message_id: int,
    subject: str | None,
    from_domain: str | None,
    attachment_names: str | None,
) -> list[dict[str, Any]]:
    """Heuristic signals from subject / from-domain / attachment names only."""
    subj = subject or ""
    atts = attachment_names or ""
    signals: list[dict[str, Any]] = []

    # Newsletter
    news_hits: list[str] = []
    conf = 0.0
    if NEWSLETTER_SUBJECT_RE.search(subj):
        news_hits.append("subject")
        conf += 0.45
    if _domain_matches(from_domain, NEWSLETTER_DOMAINS):
        # amazonaws alone is weak
        if from_domain and from_domain.endswith("amazonaws.com"):
            conf += 0.15
            news_hits.append("domain:ses")
        else:
            conf += 0.5
            news_hits.append("domain")
    if conf >= 0.45:
        signals.append(
            {
                "message_id": message_id,
                "kind": "newsletter",
                "confidence": min(conf, 1.0),
                "detail": ",".join(news_hits),
            }
        )

    # Receipt
    recv_hits: list[str] = []
    conf = 0.0
    if RECEIPT_SUBJECT_RE.search(subj):
        recv_hits.append("subject")
        conf += 0.55
    if RECEIPT_ATTACH_RE.search(atts):
        recv_hits.append("attachment")
        conf += 0.4
    if conf >= 0.55:
        signals.append(
            {
                "message_id": message_id,
                "kind": "receipt",
                "confidence": min(conf, 1.0),
                "detail": ",".join(recv_hits),
            }
        )

    # Subscription
    if SUBSCRIPTION_SUBJECT_RE.search(subj):
        signals.append(
            {
                "message_id": message_id,
                "kind": "subscription",
                "confidence": 0.6,
                "detail": "subject",
            }
        )

    # Signup / verification
    if SIGNUP_SUBJECT_RE.search(subj):
        signals.append(
            {
                "message_id": message_id,
                "kind": "signup",
                "confidence": 0.65,
                "detail": "subject",
            }
        )

    return signals


def date_from_gloda_us(date_us: int | None) -> tuple[datetime | None, datetime | None]:
    """Gloda ``date`` is microseconds since Unix epoch → naive UTC + local."""
    if date_us is None:
        return None, None
    try:
        ts = int(date_us)
    except (TypeError, ValueError):
        return None, None
    # Tolerate accidental second-scale values
    if ts < 10_000_000_000:
        ts_utc = datetime.fromtimestamp(ts, tz=UTC)
    else:
        ts_utc = datetime.fromtimestamp(ts / 1_000_000, tz=UTC)
    ts_local = ts_utc.astimezone(LOCAL_TZ)
    return ts_utc.replace(tzinfo=None), ts_local.replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# Extract


def _text_columns(con: sqlite3.Connection) -> dict[str, str]:
    """Map logical fields → actual ``messagesText_content`` column names."""
    cols = {row[1] for row in con.execute("PRAGMA table_info(messagesText_content)")}
    # Modern (thunderbird-mcp): c0body, c1subject, c2attachmentNames, c3author, c4recipients
    # Legacy: c0subject, c1body, c2attachmentNames, c3author, c4recipients
    if "c1subject" in cols:
        subject = "c1subject"
    elif "c0subject" in cols:
        subject = "c0subject"
    else:
        raise RuntimeError("messagesText_content missing subject column")
    if "c2attachmentNames" not in cols:
        raise RuntimeError("messagesText_content missing c2attachmentNames")
    if "c3author" not in cols or "c4recipients" not in cols:
        raise RuntimeError("messagesText_content missing author/recipients columns")
    return {
        "subject": subject,
        "attachments": "c2attachmentNames",
        "author": "c3author",
        "recipients": "c4recipients",
    }


def extract_folders(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT id, name, folderURI FROM folderLocations"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for folder_id, name, uri in rows:
        out.append(
            {
                "folder_id": folder_id,
                "name": name,
                "folder_uri": uri,
                "account_key": account_key_from_folder_uri(uri),
            }
        )
    return out


def extract_messages(
    con: sqlite3.Connection,
    *,
    identities: set[str],
    folder_meta: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(messages, participants, signals)`` — no body column selected."""
    cols = _text_columns(con)
    sql = f"""
        SELECT
            m.id,
            m.folderID,
            m.conversationID,
            m.date,
            m.headerMessageID,
            m.deleted,
            m.jsonAttributes,
            mt.{cols["subject"]},
            mt.{cols["attachments"]},
            mt.{cols["author"]},
            mt.{cols["recipients"]}
        FROM messages m
        LEFT JOIN messagesText_content mt ON mt.docid = m.id
    """
    message_rows: list[dict[str, Any]] = []
    participant_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []

    for row in con.execute(sql):
        (
            gloda_id,
            folder_id,
            conversation_id,
            date_us,
            header_message_id,
            deleted,
            json_attributes,
            subject,
            attachment_names,
            author_raw,
            recipients_raw,
        ) = row

        attrs = parse_json_attributes(json_attributes)
        flags = flags_from_attributes(attrs)
        from_parsed = parse_address_blob(author_raw)
        from_display, from_addr, from_domain = (
            from_parsed[0] if from_parsed else (None, None, None)
        )
        # Prefer email as from_raw when Gloda stores "addr name"
        from_raw = author_raw
        recip_parsed = parse_address_blob(recipients_raw)

        folder = folder_meta.get(folder_id) or {}
        direction = classify_direction(
            from_addr=from_addr,
            identities=identities,
            folder_name=folder.get("name"),
            folder_uri=folder.get("folder_uri"),
            from_me=bool(flags["from_me"]),
            to_me=bool(flags["to_me"]),
        )
        date_utc, date_local = date_from_gloda_us(date_us)
        att = (attachment_names or "").strip() or None
        has_attachment = bool(att) or bool(flags["has_attachment_attr"])

        message_rows.append(
            {
                "gloda_id": gloda_id,
                "date_utc": date_utc,
                "date_local": date_local,
                "folder_id": folder_id,
                "conversation_id": conversation_id,
                "header_message_id": header_message_id,
                "subject": subject,
                "attachment_names": att,
                "has_attachment": has_attachment,
                "deleted": bool(deleted),
                "starred": flags["starred"],
                "read": flags["read"],
                "replied": flags["replied"],
                "forwarded": flags["forwarded"],
                "is_encrypted": flags["is_encrypted"],
                "from_me": flags["from_me"],
                "to_me": flags["to_me"],
                "direction": direction,
                "from_raw": from_raw,
                "from_addr": from_addr,
                "from_name": from_display,
                "from_domain": from_domain,
                "year": date_local.year if date_local else None,
                "month": date_local.month if date_local else None,
                "day": date_local.day if date_local else None,
                "hour": date_local.hour if date_local else None,
                "dow": date_local.isoweekday() if date_local else None,
            }
        )

        if from_addr:
            participant_rows.append(
                {
                    "message_id": gloda_id,
                    "role": "from",
                    "addr": from_addr,
                    "domain": from_domain,
                    "display_name": from_display,
                }
            )
        for display, addr, domain in recip_parsed:
            participant_rows.append(
                {
                    "message_id": gloda_id,
                    "role": "to",
                    "addr": addr,
                    "domain": domain,
                    "display_name": display,
                }
            )

        signal_rows.extend(
            detect_signals(
                message_id=gloda_id,
                subject=subject,
                from_domain=from_domain,
                attachment_names=att,
            )
        )

    return message_rows, participant_rows, signal_rows
