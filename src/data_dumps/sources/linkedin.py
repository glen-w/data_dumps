"""LinkedIn GDPR CSV export → DuckDB.

Complete (and Basic) archives are a bag of CSVs. Connections.csv has a Notes
preamble before the header. IPs, emails, phones, ads, inferences, receipts,
and identity-document files are not loaded.
"""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Rome")

CONNECTIONS_CSV = "Connections.csv"
POSITIONS_CSV = "Positions.csv"

SKIP_CSV_NAMES = {
    "logins.csv",
    "security challenges.csv",
    "registration.csv",
    "email addresses.csv",
    "phonenumbers.csv",
    "whatsapp phone numbers.csv",
    "ad_targeting.csv",
    "ads clicked.csv",
    "lan ads engagement.csv",
    "inferences_about_you.csv",
    "inferred credibility scores.csv",
    "receipts_v2.csv",
    "job seeker preferences.csv",
    "verifications.csv",
    "guide_messages.csv",
    "learning_coach_messages.csv",
    "learning_role_play_messages.csv",
    "learningcoachmessages.csv",
    "profile.csv",
    "profile summary.csv",
    "notes.csv",
    "causes you care about.csv",
    "rich_media.csv",
    "savedjobalerts.csv",
}

PREFIX_TABLES = {
    "comments_": "comments",
    "reactions_": "reactions",
    "shares_": "shares",
    "instantreposts_": "reposts",
    "member_follows_": "member_follows",
}

EXACT_TABLES = {
    "connections.csv": "connections",
    "messages.csv": "messages",
    "invitations.csv": "invitations",
    "positions.csv": "positions",
    "education.csv": "education",
    "skills.csv": "skills",
    "publications.csv": "publications",
    "languages.csv": "languages",
    "courses.csv": "courses",
    "company follows.csv": "company_follows",
    "endorsement_given_info.csv": "endorsements_given",
    "endorsement_received_info.csv": "endorsements_received",
    "events.csv": "events",
    "saved jobs.csv": "saved_jobs",
    "learning.csv": "learning",
}

LINKEDIN_TABLES = [
    "linkedin.account",
    "linkedin.connections",
    "linkedin.messages",
    "linkedin.invitations",
    "linkedin.positions",
    "linkedin.education",
    "linkedin.skills",
    "linkedin.publications",
    "linkedin.languages",
    "linkedin.courses",
    "linkedin.reactions",
    "linkedin.shares",
    "linkedin.comments",
    "linkedin.reposts",
    "linkedin.member_follows",
    "linkedin.company_follows",
    "linkedin.endorsements_given",
    "linkedin.endorsements_received",
    "linkedin.events",
    "linkedin.saved_jobs",
    "linkedin.learning",
]


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {"N/A", "NA", "NONE", "NULL"}


def _cell(row: dict[str, Any], *names: str) -> str | None:
    lower = {k.strip().lower(): k for k in row if k}
    for name in names:
        key = lower.get(name.lower())
        if key is None:
            continue
        val = row.get(key)
        if _blank(val):
            return None
        return str(val).strip()
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if _blank(value):
        return None
    raw = str(value).strip()
    if " - " in raw and any(tok in raw for tok in ("AM", "PM", "am", "pm")):
        raw = raw.split(" - ", 1)[0].strip()
    ts = pd.to_datetime(raw, utc=True, errors="coerce", dayfirst=False)
    if pd.isna(ts):
        return None
    py = ts.to_pydatetime()
    if py.tzinfo is None:
        py = py.replace(tzinfo=UTC)
    return py.astimezone(UTC)


def _ts_pair(value: Any) -> tuple[datetime | None, datetime | None]:
    ts = _parse_datetime(value)
    if ts is None:
        return None, None
    utc_naive = ts.astimezone(UTC).replace(tzinfo=None)
    local_naive = ts.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return utc_naive, local_naive


def _year_month(
    utc_naive: datetime | None, local_naive: datetime | None
) -> tuple[int | None, int | None]:
    src = local_naive or utc_naive
    if src is None:
        return None, None
    return src.year, src.month


def _parse_year(value: Any) -> int | None:
    if _blank(value):
        return None
    raw = str(value).strip()
    if raw.isdigit() and len(raw) == 4:
        return int(raw)
    ts = _parse_datetime(raw)
    return ts.year if ts else None


def _csv_table_name(filename: str) -> str | None:
    base = Path(filename).name.lower()
    if base in SKIP_CSV_NAMES:
        return None
    if base in EXACT_TABLES:
        return EXACT_TABLES[base]
    for prefix, table in PREFIX_TABLES.items():
        if base.startswith(prefix) and base.endswith(".csv"):
            return table
    return None


def _read_csv_records(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    header_idx = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip("\ufeff")
        if stripped.startswith("First Name,") or stripped.startswith(
            "CONVERSATION ID,"
        ):
            header_idx = i
            break
        if i == 0 and "," in stripped and not stripped.startswith("Notes:"):
            header_idx = 0
            break
    blob = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(blob))
    rows: list[dict[str, str]] = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


class LinkedInSource:
    name = "linkedin"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    bases = {Path(n).name.lower() for n in zf.namelist()}
            except (OSError, zipfile.BadZipFile):
                return False
            return CONNECTIONS_CSV.lower() in bases and POSITIONS_CSV.lower() in bases
        export = self._export_dir(path)
        if export is None:
            return False
        names = {p.name.lower() for p in export.iterdir() if p.is_file()}
        return CONNECTIONS_CSV.lower() in names and POSITIONS_CSV.lower() in names

    def _export_dir(self, path: Path) -> Path | None:
        if not path.is_dir():
            return None
        names = {p.name.lower() for p in path.iterdir() if p.is_file()}
        if CONNECTIONS_CSV.lower() in names and POSITIONS_CSV.lower() in names:
            return path
        nested = [
            p
            for p in path.iterdir()
            if p.is_dir()
            and (p / CONNECTIONS_CSV).is_file()
            and (p / POSITIONS_CSV).is_file()
        ]
        if len(nested) == 1:
            return nested[0]
        return None

    def tables(self) -> list[str]:
        return list(LINKEDIN_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        raw = self._materialize(path)
        files = self._index_csvs(raw)
        frames = self._build_frames(files)

        conn.execute("DROP SCHEMA IF EXISTS linkedin CASCADE")
        conn.execute("CREATE SCHEMA linkedin")
        self._create_tables(conn)
        for table, df in frames.items():
            tmp = f"_li_{table}"
            conn.register(tmp, df)
            conn.execute(f"INSERT INTO linkedin.{table} BY NAME SELECT * FROM {tmp}")
            conn.unregister(tmp)

    def _materialize(self, path: Path) -> Path:
        dest = raw_dir("linkedin")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if name.endswith("/") or not name.lower().endswith(".csv"):
                        continue
                    if _csv_table_name(name) is None:
                        continue
                    dest_name = Path(name).name
                    with zf.open(name) as zf_src, (dest / dest_name).open("wb") as out:
                        out.write(zf_src.read())
        else:
            export = self._export_dir(path)
            if export is None:
                raise FileNotFoundError(f"No LinkedIn CSVs in {path}")
            for f in export.rglob("*.csv"):
                if _csv_table_name(f.name) is None:
                    continue
                shutil.copy2(f, dest / f.name)
        return dest

    def _index_csvs(self, raw: Path) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for path in raw.glob("*.csv"):
            table = _csv_table_name(path.name)
            if table:
                found[table] = path
        return found

    def _create_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE linkedin.account (
                display_name VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.connections (
                first_name VARCHAR,
                last_name VARCHAR,
                profile_url VARCHAR,
                company VARCHAR,
                position VARCHAR,
                connected_on DATE,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.messages (
                conversation_id VARCHAR,
                conversation_title VARCHAR,
                from_name VARCHAR,
                sender_profile_url VARCHAR,
                to_name VARCHAR,
                recipient_profile_urls VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                subject VARCHAR,
                content VARCHAR,
                folder VARCHAR,
                is_from_me BOOLEAN,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.invitations (
                from_name VARCHAR,
                to_name VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                message VARCHAR,
                direction VARCHAR,
                inviter_profile_url VARCHAR,
                invitee_profile_url VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.positions (
                company_name VARCHAR,
                title VARCHAR,
                description VARCHAR,
                location VARCHAR,
                started_on VARCHAR,
                finished_on VARCHAR,
                start_year BIGINT,
                end_year BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.education (
                school_name VARCHAR,
                start_date VARCHAR,
                end_date VARCHAR,
                notes VARCHAR,
                degree_name VARCHAR,
                activities VARCHAR,
                start_year BIGINT,
                end_year BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.skills (
                name VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.publications (
                name VARCHAR,
                published_on VARCHAR,
                description VARCHAR,
                publisher VARCHAR,
                url VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.languages (
                name VARCHAR,
                proficiency VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.courses (
                name VARCHAR,
                number VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.reactions (
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                reaction_type VARCHAR,
                link VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.shares (
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                share_link VARCHAR,
                commentary VARCHAR,
                shared_url VARCHAR,
                media_url VARCHAR,
                visibility VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.comments (
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                link VARCHAR,
                message VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.reposts (
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                link VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.member_follows (
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                status VARCHAR,
                full_name VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.company_follows (
                organization VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.endorsements_given (
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                skill_name VARCHAR,
                endorsee_first_name VARCHAR,
                endorsee_last_name VARCHAR,
                endorsee_url VARCHAR,
                status VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.endorsements_received (
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                skill_name VARCHAR,
                endorser_first_name VARCHAR,
                endorser_last_name VARCHAR,
                endorser_url VARCHAR,
                status VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.events (
                event_name VARCHAR,
                event_time VARCHAR,
                status VARCHAR,
                external_url VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.saved_jobs (
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                job_url VARCHAR,
                job_title VARCHAR,
                company_name VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE linkedin.learning (
                content_title VARCHAR,
                content_type VARCHAR,
                last_watched_at TIMESTAMP,
                completed_at TIMESTAMP,
                saved BOOLEAN,
                year BIGINT,
                month BIGINT
            )
            """)

    def _build_frames(self, files: dict[str, Path]) -> dict[str, pd.DataFrame]:
        invitations = self._invitations_frame(files.get("invitations"))
        me_name: str | None = None
        if not invitations.empty and "from_name" in invitations.columns:
            outgoing = invitations[invitations["direction"] == "OUTGOING"]
            if not outgoing.empty:
                mode = outgoing["from_name"].dropna().mode()
                if len(mode):
                    me_name = str(mode.iloc[0])
        account = pd.DataFrame([{"display_name": me_name}])
        return {
            "account": account,
            "connections": self._connections_frame(files.get("connections")),
            "messages": self._messages_frame(files.get("messages"), me_name),
            "invitations": invitations,
            "positions": self._positions_frame(files.get("positions")),
            "education": self._education_frame(files.get("education")),
            "skills": self._name_frame(files.get("skills"), ["name"]),
            "publications": self._publications_frame(files.get("publications")),
            "languages": self._languages_frame(files.get("languages")),
            "courses": self._courses_frame(files.get("courses")),
            "reactions": self._activity_frame(
                files.get("reactions"),
                extra={"reaction_type": ("Type",)},
                link_keys=("Link",),
            ),
            "shares": self._shares_frame(files.get("shares")),
            "comments": self._activity_frame(
                files.get("comments"),
                extra={"message": ("Message",)},
                link_keys=("Link",),
            ),
            "reposts": self._activity_frame(
                files.get("reposts"), extra={}, link_keys=("Link",)
            ),
            "member_follows": self._member_follows_frame(files.get("member_follows")),
            "company_follows": self._company_follows_frame(
                files.get("company_follows")
            ),
            "endorsements_given": self._endorsements_frame(
                files.get("endorsements_given"), given=True
            ),
            "endorsements_received": self._endorsements_frame(
                files.get("endorsements_received"), given=False
            ),
            "events": self._events_frame(files.get("events")),
            "saved_jobs": self._saved_jobs_frame(files.get("saved_jobs")),
            "learning": self._learning_frame(files.get("learning")),
        }

    def _connections_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "first_name",
            "last_name",
            "profile_url",
            "company",
            "position",
            "connected_on",
            "ts_utc",
            "ts_local",
            "year",
            "month",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "Connected On"))
            connected_on: date | None = None
            if local_naive:
                connected_on = local_naive.date()
            elif utc_naive:
                connected_on = utc_naive.date()
            year, month = _year_month(utc_naive, local_naive)
            rows.append(
                {
                    "first_name": _cell(rec, "First Name"),
                    "last_name": _cell(rec, "Last Name"),
                    "profile_url": _cell(rec, "URL"),
                    "company": _cell(rec, "Company"),
                    "position": _cell(rec, "Position"),
                    "connected_on": connected_on,
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _messages_frame(self, path: Path | None, me_name: str | None) -> pd.DataFrame:
        cols = [
            "conversation_id",
            "conversation_title",
            "from_name",
            "sender_profile_url",
            "to_name",
            "recipient_profile_urls",
            "ts_utc",
            "ts_local",
            "subject",
            "content",
            "folder",
            "is_from_me",
            "year",
            "month",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "DATE", "Date"))
            year, month = _year_month(utc_naive, local_naive)
            from_name = _cell(rec, "FROM", "From")
            rows.append(
                {
                    "conversation_id": _cell(rec, "CONVERSATION ID"),
                    "conversation_title": _cell(rec, "CONVERSATION TITLE"),
                    "from_name": from_name,
                    "sender_profile_url": _cell(rec, "SENDER PROFILE URL"),
                    "to_name": _cell(rec, "TO"),
                    "recipient_profile_urls": _cell(rec, "RECIPIENT PROFILE URLS"),
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "subject": _cell(rec, "SUBJECT"),
                    "content": _cell(rec, "CONTENT"),
                    "folder": _cell(rec, "FOLDER"),
                    "is_from_me": bool(me_name and from_name == me_name),
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _invitations_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "from_name",
            "to_name",
            "ts_utc",
            "ts_local",
            "message",
            "direction",
            "inviter_profile_url",
            "invitee_profile_url",
            "year",
            "month",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "Sent At"))
            year, month = _year_month(utc_naive, local_naive)
            rows.append(
                {
                    "from_name": _cell(rec, "From"),
                    "to_name": _cell(rec, "To"),
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "message": _cell(rec, "Message"),
                    "direction": _cell(rec, "Direction"),
                    "inviter_profile_url": _cell(rec, "inviterProfileUrl"),
                    "invitee_profile_url": _cell(rec, "inviteeProfileUrl"),
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _positions_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "company_name",
            "title",
            "description",
            "location",
            "started_on",
            "finished_on",
            "start_year",
            "end_year",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            started = _cell(rec, "Started On")
            finished = _cell(rec, "Finished On")
            rows.append(
                {
                    "company_name": _cell(rec, "Company Name"),
                    "title": _cell(rec, "Title"),
                    "description": _cell(rec, "Description"),
                    "location": _cell(rec, "Location"),
                    "started_on": started,
                    "finished_on": finished,
                    "start_year": _parse_year(started),
                    "end_year": _parse_year(finished),
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _education_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "school_name",
            "start_date",
            "end_date",
            "notes",
            "degree_name",
            "activities",
            "start_year",
            "end_year",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            start = _cell(rec, "Start Date")
            end = _cell(rec, "End Date")
            rows.append(
                {
                    "school_name": _cell(rec, "School Name"),
                    "start_date": start,
                    "end_date": end,
                    "notes": _cell(rec, "Notes"),
                    "degree_name": _cell(rec, "Degree Name"),
                    "activities": _cell(rec, "Activities"),
                    "start_year": _parse_year(start),
                    "end_year": _parse_year(end),
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _name_frame(self, path: Path | None, columns: list[str]) -> pd.DataFrame:
        if path is None:
            return _empty(columns)
        rows = []
        for rec in _read_csv_records(path):
            name = _cell(rec, "Name")
            if name:
                rows.append({"name": name})
        return pd.DataFrame(rows) if rows else _empty(columns)

    def _publications_frame(self, path: Path | None) -> pd.DataFrame:
        cols = ["name", "published_on", "description", "publisher", "url"]
        if path is None:
            return _empty(cols)
        rows = []
        for rec in _read_csv_records(path):
            rows.append(
                {
                    "name": _cell(rec, "Name"),
                    "published_on": _cell(rec, "Published On"),
                    "description": _cell(rec, "Description"),
                    "publisher": _cell(rec, "Publisher"),
                    "url": _cell(rec, "Url"),
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _languages_frame(self, path: Path | None) -> pd.DataFrame:
        cols = ["name", "proficiency"]
        if path is None:
            return _empty(cols)
        rows = []
        for rec in _read_csv_records(path):
            rows.append(
                {
                    "name": _cell(rec, "Name"),
                    "proficiency": _cell(rec, "Proficiency"),
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _courses_frame(self, path: Path | None) -> pd.DataFrame:
        cols = ["name", "number"]
        if path is None:
            return _empty(cols)
        rows = []
        for rec in _read_csv_records(path):
            rows.append(
                {
                    "name": _cell(rec, "Name"),
                    "number": _cell(rec, "Number"),
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _activity_frame(
        self,
        path: Path | None,
        *,
        extra: dict[str, tuple[str, ...]],
        link_keys: tuple[str, ...],
    ) -> pd.DataFrame:
        ordered = ["ts_utc", "ts_local", *extra.keys()]
        if link_keys:
            ordered.append("link")
        ordered.extend(["year", "month"])
        if path is None:
            return _empty(ordered)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "Date"))
            year, month = _year_month(utc_naive, local_naive)
            row: dict[str, Any] = {
                "ts_utc": utc_naive,
                "ts_local": local_naive,
                "year": year,
                "month": month,
            }
            for col, keys in extra.items():
                row[col] = _cell(rec, *keys)
            if link_keys:
                row["link"] = _cell(rec, *link_keys)
            rows.append(row)
        return pd.DataFrame(rows) if rows else _empty(ordered)

    def _shares_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "ts_utc",
            "ts_local",
            "share_link",
            "commentary",
            "shared_url",
            "media_url",
            "visibility",
            "year",
            "month",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "Date"))
            year, month = _year_month(utc_naive, local_naive)
            rows.append(
                {
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "share_link": _cell(rec, "ShareLink"),
                    "commentary": _cell(rec, "ShareCommentary"),
                    "shared_url": _cell(rec, "SharedUrl"),
                    "media_url": _cell(rec, "MediaUrl"),
                    "visibility": _cell(rec, "Visibility"),
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _member_follows_frame(self, path: Path | None) -> pd.DataFrame:
        cols = ["ts_utc", "ts_local", "status", "full_name", "year", "month"]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "Date"))
            year, month = _year_month(utc_naive, local_naive)
            rows.append(
                {
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "status": _cell(rec, "Status"),
                    "full_name": _cell(rec, "FullName"),
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _company_follows_frame(self, path: Path | None) -> pd.DataFrame:
        cols = ["organization", "ts_utc", "ts_local", "year", "month"]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "Followed On"))
            year, month = _year_month(utc_naive, local_naive)
            rows.append(
                {
                    "organization": _cell(rec, "Organization"),
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _endorsements_frame(self, path: Path | None, *, given: bool) -> pd.DataFrame:
        person_prefix = "endorsee" if given else "endorser"
        cols = [
            "ts_utc",
            "ts_local",
            "skill_name",
            f"{person_prefix}_first_name",
            f"{person_prefix}_last_name",
            f"{person_prefix}_url",
            "status",
            "year",
            "month",
        ]
        if path is None:
            return _empty(cols)
        first_keys = ("Endorsee First Name",) if given else ("Endorser First Name",)
        last_keys = ("Endorsee Last Name",) if given else ("Endorser Last Name",)
        url_keys = ("Endorsee Public Url",) if given else ("Endorser Public Url",)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "Endorsement Date"))
            year, month = _year_month(utc_naive, local_naive)
            rows.append(
                {
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "skill_name": _cell(rec, "Skill Name"),
                    f"{person_prefix}_first_name": _cell(rec, *first_keys),
                    f"{person_prefix}_last_name": _cell(rec, *last_keys),
                    f"{person_prefix}_url": _cell(rec, *url_keys),
                    "status": _cell(rec, "Endorsement Status"),
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _events_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "event_name",
            "event_time",
            "status",
            "external_url",
            "ts_utc",
            "ts_local",
            "year",
            "month",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            event_time = _cell(rec, "Event Time")
            utc_naive, local_naive = _ts_pair(event_time)
            year, month = _year_month(utc_naive, local_naive)
            rows.append(
                {
                    "event_name": _cell(rec, "Event Name"),
                    "event_time": event_time,
                    "status": _cell(rec, "Status"),
                    "external_url": _cell(rec, "External Url"),
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _saved_jobs_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "ts_utc",
            "ts_local",
            "job_url",
            "job_title",
            "company_name",
            "year",
            "month",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "Saved Date"))
            year, month = _year_month(utc_naive, local_naive)
            rows.append(
                {
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "job_url": _cell(rec, "Job Url"),
                    "job_title": _cell(rec, "Job Title"),
                    "company_name": _cell(rec, "Company Name"),
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _learning_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "content_title",
            "content_type",
            "last_watched_at",
            "completed_at",
            "saved",
            "year",
            "month",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            watched_utc, watched_local = _ts_pair(
                _cell(rec, "Content Last Watched Date (if viewed)")
            )
            completed_utc, _ = _ts_pair(
                _cell(rec, "Content Completed At (if completed)")
            )
            saved_raw = _cell(rec, "Content Saved")
            saved = None
            if saved_raw is not None:
                saved = saved_raw.lower() in {"true", "1", "yes"}
            year, month = _year_month(watched_utc, watched_local)
            rows.append(
                {
                    "content_title": _cell(rec, "Content Title"),
                    "content_type": _cell(rec, "Content Type"),
                    "last_watched_at": watched_utc,
                    "completed_at": completed_utc,
                    "saved": saved,
                    "year": year,
                    "month": month,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        row = conn.execute("""
            SELECT
                (SELECT count(*)::BIGINT FROM linkedin.connections) AS n_connections,
                (SELECT count(*)::BIGINT FROM linkedin.messages) AS n_messages,
                (SELECT count(*)::BIGINT FROM linkedin.reactions) AS n_reactions,
                (SELECT count(*)::BIGINT FROM linkedin.shares) AS n_shares,
                (SELECT count(*)::BIGINT FROM linkedin.comments) AS n_comments,
                (SELECT min(connected_on) FROM linkedin.connections) AS first_connected,
                (SELECT max(connected_on) FROM linkedin.connections) AS last_connected
            """).fetchone()
        assert row is not None
        inv = {
            "n_connections": row[0],
            "n_messages": row[1],
            "n_reactions": row[2],
            "n_shares": row[3],
            "n_comments": row[4],
            "first_connected": row[5],
            "last_connected": row[6],
        }
        inv["summary"] = (
            f"linkedin.connections: {inv['n_connections']:,} | "
            f"messages {inv['n_messages']:,} | "
            f"reactions {inv['n_reactions']:,} | "
            f"shares {inv['n_shares']:,} | "
            f"comments {inv['n_comments']:,} | "
            f"{inv['first_connected']} → {inv['last_connected']}"
        )
        return inv
