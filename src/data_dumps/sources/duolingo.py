"""Duolingo GDPR CSV export → DuckDB.

Keep-list only: profile (username + joined_at), languages, leaderboards,
inventory (no payment_processor / code_id), friends aggregate counts, and
user-tree-backend progress events (blob length only). Auth, IPs, emails,
notify/ads, avatars, experiments, tutor/video, and DET profile are dropped.
"""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Rome")

SIGNATURE_CSVS = ("languages.csv", "leaderboards.csv", "profile.csv")

KEEP_CSV_NAMES = {
    "profile.csv",
    "languages.csv",
    "leaderboards.csv",
    "inventory.csv",
    "friends-follow.csv",
    "user-tree-backend.csv",
}

DUOLINGO_TABLES = [
    "duolingo.account",
    "duolingo.languages",
    "duolingo.leaderboards",
    "duolingo.inventory",
    "duolingo.friends",
    "duolingo.progress_events",
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
    ts = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    py = ts.to_pydatetime()
    if py.tzinfo is None:
        py = py.replace(tzinfo=UTC)
    return py.astimezone(UTC)


def _parse_unix(value: Any) -> datetime | None:
    if _blank(value):
        return None
    raw = str(value).strip()
    try:
        epoch = float(raw)
    except ValueError:
        return None
    # Heuristic: ms vs seconds
    if epoch > 1e12:
        epoch /= 1000.0
    try:
        return datetime.fromtimestamp(epoch, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _ts_pair(value: Any) -> tuple[datetime | None, datetime | None]:
    ts = _parse_datetime(value)
    if ts is None:
        ts = _parse_unix(value)
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


def _to_int(value: Any) -> int | None:
    if _blank(value):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if _blank(value):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _to_bool(value: Any) -> bool | None:
    if _blank(value):
        return None
    raw = str(value).strip().lower()
    if raw in {"true", "1", "yes", "y"}:
        return True
    if raw in {"false", "0", "no", "n"}:
        return False
    return None


def _read_csv_records(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _zip_basenames(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as zf:
        return {Path(n).name.lower() for n in zf.namelist() if not n.endswith("/")}


def _dir_has_signature(export: Path) -> bool:
    names = {p.name.lower() for p in export.iterdir() if p.is_file()}
    return all(name in names for name in SIGNATURE_CSVS)


class DuolingoSource:
    name = "duolingo"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                bases = _zip_basenames(path)
            except (OSError, zipfile.BadZipFile):
                return False
            return all(name in bases for name in SIGNATURE_CSVS)
        return self._export_dir(path) is not None

    def _export_dir(self, path: Path) -> Path | None:
        if not path.is_dir():
            return None
        if _dir_has_signature(path):
            return path
        nested = path / "duolingo"
        if nested.is_dir() and _dir_has_signature(nested):
            return nested
        candidates = [p for p in path.iterdir() if p.is_dir() and _dir_has_signature(p)]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def tables(self) -> list[str]:
        return list(DUOLINGO_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        raw = self._materialize(path)
        files = {p.name.lower(): p for p in raw.glob("*.csv")}
        frames = {
            "account": self._account_frame(files.get("profile.csv")),
            "languages": self._languages_frame(files.get("languages.csv")),
            "leaderboards": self._leaderboards_frame(files.get("leaderboards.csv")),
            "inventory": self._inventory_frame(files.get("inventory.csv")),
            "friends": self._friends_frame(files.get("friends-follow.csv")),
            "progress_events": self._progress_frame(files.get("user-tree-backend.csv")),
        }

        conn.execute("DROP SCHEMA IF EXISTS duolingo CASCADE")
        conn.execute("CREATE SCHEMA duolingo")
        self._create_tables(conn)
        for table, df in frames.items():
            tmp = f"_duo_{table}"
            conn.register(tmp, df)
            conn.execute(f"INSERT INTO duolingo.{table} BY NAME SELECT * FROM {tmp}")
            conn.unregister(tmp)

    def _materialize(self, path: Path) -> Path:
        dest = raw_dir("duolingo")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if name.endswith("/") or not name.lower().endswith(".csv"):
                        continue
                    base = Path(name).name.lower()
                    if base not in KEEP_CSV_NAMES:
                        continue
                    with zf.open(name) as zf_src, (dest / base).open("wb") as out:
                        out.write(zf_src.read())
        else:
            export = self._export_dir(path)
            if export is None:
                raise FileNotFoundError(f"No Duolingo CSVs in {path}")
            for f in export.iterdir():
                if not f.is_file() or not f.name.lower().endswith(".csv"):
                    continue
                base = f.name.lower()
                if base not in KEEP_CSV_NAMES:
                    continue
                shutil.copy2(f, dest / base)
        self._scrub_raw_csvs(dest)
        return dest

    def _scrub_raw_csvs(self, dest: Path) -> None:
        """Rewrite keep-list CSVs so raw/ never retains dropped PII columns."""
        profile = dest / "profile.csv"
        if profile.exists():
            keep_keys = {
                "username",
                "joined_at",
                "ui_language",
                "daily_goal",
                "timezone",
            }
            rows = _read_csv_records(profile)
            kept: list[tuple[str, str]] = []
            for rec in rows:
                name = (_cell(rec, "name") or "").strip().lower()
                value = _cell(rec, "value")
                if name in keep_keys and value is not None:
                    kept.append((name, value))
            with profile.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["name", "value"])
                writer.writerows(kept)

        inventory = dest / "inventory.csv"
        if inventory.exists():
            drop_cols = {"payment_processor", "code_id", "wager_day"}
            rows = _read_csv_records(inventory)
            if rows:
                fieldnames = [c for c in rows[0].keys() if c.lower() not in drop_cols]
                with inventory.open("w", encoding="utf-8", newline="") as fh:
                    writer = csv.DictWriter(
                        fh, fieldnames=fieldnames, extrasaction="ignore"
                    )
                    writer.writeheader()
                    for rec in rows:
                        writer.writerow({k: rec.get(k, "") for k in fieldnames})

    def _create_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE duolingo.account (
                username VARCHAR,
                joined_at_utc TIMESTAMP,
                joined_at_local TIMESTAMP,
                year BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE duolingo.languages (
                learning_language VARCHAR,
                from_language VARCHAR,
                points BIGINT,
                skills_learned BIGINT,
                total_lessons BIGINT,
                days_active BIGINT,
                last_active_utc TIMESTAMP,
                last_active_local TIMESTAMP,
                prior_proficiency VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE duolingo.leaderboards (
                leaderboard VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT,
                tier BIGINT,
                score BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE duolingo.inventory (
                item_type VARCHAR,
                purchase_ts_utc TIMESTAMP,
                purchase_ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT,
                active BOOLEAN,
                price_in_virtual_currency DOUBLE,
                product VARCHAR,
                expected_expiration_utc TIMESTAMP,
                expected_expiration_local TIMESTAMP
            )
            """)
        conn.execute("""
            CREATE TABLE duolingo.friends (
                num_following BIGINT,
                num_followers BIGINT,
                num_blocking BIGINT,
                num_blockers BIGINT,
                generated_ts_utc TIMESTAMP,
                generated_ts_local TIMESTAMP
            )
            """)
        conn.execute("""
            CREATE TABLE duolingo.progress_events (
                language VARCHAR,
                learning_lang VARCHAR,
                from_lang VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT,
                progress_bytes BIGINT
            )
            """)

    def _account_frame(self, path: Path | None) -> pd.DataFrame:
        cols = ["username", "joined_at_utc", "joined_at_local", "year"]
        if path is None:
            return _empty(cols)
        kv: dict[str, str] = {}
        for rec in _read_csv_records(path):
            name = _cell(rec, "name")
            value = _cell(rec, "value")
            if name:
                kv[name.lower()] = value or ""
        # Also support flat columnar profile if present
        if not kv:
            records = _read_csv_records(path)
            if records:
                rec = records[0]
                username = _cell(rec, "username")
                joined = _cell(rec, "joined_at")
                utc_naive, local_naive = _ts_pair(joined)
                year, _ = _year_month(utc_naive, local_naive)
                return pd.DataFrame(
                    [
                        {
                            "username": username,
                            "joined_at_utc": utc_naive,
                            "joined_at_local": local_naive,
                            "year": year,
                        }
                    ]
                )
            return _empty(cols)

        username = kv.get("username") or None
        utc_naive, local_naive = _ts_pair(kv.get("joined_at"))
        year, _ = _year_month(utc_naive, local_naive)
        return pd.DataFrame(
            [
                {
                    "username": username,
                    "joined_at_utc": utc_naive,
                    "joined_at_local": local_naive,
                    "year": year,
                }
            ]
        )

    def _languages_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "learning_language",
            "from_language",
            "points",
            "skills_learned",
            "total_lessons",
            "days_active",
            "last_active_utc",
            "last_active_local",
            "prior_proficiency",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            last_utc, last_local = _ts_pair(_cell(rec, "last_active"))
            rows.append(
                {
                    "learning_language": _cell(rec, "learning_language"),
                    "from_language": _cell(rec, "from_language"),
                    "points": _to_int(_cell(rec, "points")),
                    "skills_learned": _to_int(_cell(rec, "skills_learned")),
                    "total_lessons": _to_int(_cell(rec, "total_lessons")),
                    "days_active": _to_int(_cell(rec, "days_active")),
                    "last_active_utc": last_utc,
                    "last_active_local": last_local,
                    "prior_proficiency": _cell(rec, "prior_proficiency"),
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _leaderboards_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "leaderboard",
            "ts_utc",
            "ts_local",
            "year",
            "month",
            "tier",
            "score",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(_cell(rec, "timestamp", "ts"))
            year, month = _year_month(utc_naive, local_naive)
            rows.append(
                {
                    "leaderboard": _cell(rec, "leaderboard"),
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "year": year,
                    "month": month,
                    "tier": _to_int(_cell(rec, "tier")),
                    "score": _to_int(_cell(rec, "score")),
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _inventory_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "item_type",
            "purchase_ts_utc",
            "purchase_ts_local",
            "year",
            "month",
            "active",
            "price_in_virtual_currency",
            "product",
            "expected_expiration_utc",
            "expected_expiration_local",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            utc_naive, local_naive = _ts_pair(
                _cell(rec, "purchase_datetime", "purchase_ts")
            )
            year, month = _year_month(utc_naive, local_naive)
            exp_utc, exp_local = _ts_pair(_cell(rec, "expected_expiration"))
            rows.append(
                {
                    "item_type": _cell(rec, "item_type"),
                    "purchase_ts_utc": utc_naive,
                    "purchase_ts_local": local_naive,
                    "year": year,
                    "month": month,
                    "active": _to_bool(_cell(rec, "active")),
                    "price_in_virtual_currency": _to_float(
                        _cell(rec, "price_in_virtual_currency")
                    ),
                    "product": _cell(rec, "product"),
                    "expected_expiration_utc": exp_utc,
                    "expected_expiration_local": exp_local,
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def _friends_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "num_following",
            "num_followers",
            "num_blocking",
            "num_blockers",
            "generated_ts_utc",
            "generated_ts_local",
        ]
        if path is None:
            return _empty(cols)
        records = _read_csv_records(path)
        if not records:
            return _empty(cols)
        rec = records[0]
        gen_utc, gen_local = _ts_pair(_cell(rec, "timestamp_generated", "timestamp"))
        return pd.DataFrame(
            [
                {
                    "num_following": _to_int(_cell(rec, "num_following")),
                    "num_followers": _to_int(_cell(rec, "num_followers")),
                    "num_blocking": _to_int(_cell(rec, "num_blocking")),
                    "num_blockers": _to_int(_cell(rec, "num_blockers")),
                    "generated_ts_utc": gen_utc,
                    "generated_ts_local": gen_local,
                }
            ]
        )

    def _progress_frame(self, path: Path | None) -> pd.DataFrame:
        cols = [
            "language",
            "learning_lang",
            "from_lang",
            "ts_utc",
            "ts_local",
            "year",
            "month",
            "progress_bytes",
        ]
        if path is None:
            return _empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in _read_csv_records(path):
            language = _cell(rec, "language")
            learning_lang: str | None = None
            from_lang: str | None = None
            if language and "<-" in language:
                parts = language.split("<-", 1)
                learning_lang = parts[0].strip() or None
                from_lang = parts[1].strip() or None
            utc_naive, local_naive = _ts_pair(_cell(rec, "event_timestamp"))
            year, month = _year_month(utc_naive, local_naive)
            progress = _cell(rec, "true_progress") or ""
            rows.append(
                {
                    "language": language,
                    "learning_lang": learning_lang,
                    "from_lang": from_lang,
                    "ts_utc": utc_naive,
                    "ts_local": local_naive,
                    "year": year,
                    "month": month,
                    "progress_bytes": len(progress.encode("utf-8")),
                }
            )
        return pd.DataFrame(rows) if rows else _empty(cols)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        row = conn.execute("""
            SELECT
                (SELECT count(*)::BIGINT FROM duolingo.progress_events) AS n_progress,
                (SELECT count(*)::BIGINT FROM duolingo.languages) AS n_languages,
                (SELECT count(*)::BIGINT FROM duolingo.leaderboards) AS n_leaderboards,
                (SELECT count(*)::BIGINT FROM duolingo.inventory) AS n_inventory,
                (SELECT max(tier)::BIGINT FROM duolingo.leaderboards) AS max_tier,
                (SELECT min(ts_local)::TIMESTAMP FROM duolingo.progress_events)
                    AS first_progress,
                (SELECT max(ts_local)::TIMESTAMP FROM duolingo.progress_events)
                    AS last_progress,
                (SELECT username FROM duolingo.account LIMIT 1) AS username
            """).fetchone()
        assert row is not None
        inv = {
            "n_progress": row[0],
            "n_languages": row[1],
            "n_leaderboards": row[2],
            "n_inventory": row[3],
            "max_tier": row[4],
            "first_progress": row[5],
            "last_progress": row[6],
            "username": row[7],
        }
        who = inv["username"] or "?"
        inv["summary"] = (
            f"duolingo @{who}: progress {inv['n_progress']:,} | "
            f"languages {inv['n_languages']:,} | "
            f"leaderboards {inv['n_leaderboards']:,} | "
            f"inventory {inv['n_inventory']:,} | "
            f"max tier {inv['max_tier']} | "
            f"{inv['first_progress']} → {inv['last_progress']}"
        )
        return inv
