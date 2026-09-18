"""Airbnb personal data HTML export → DuckDB.

Keep-list: reservations (guest/host role from account id), search history
(city/country + search-pin lat/lon), reviews provided/received, wishlists.
Dropped: profile contact fields / street addresses / IPs / phones / KYC /
payments / activity log / search telemetry / messages / listing host tools.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import zipfile
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Paris")

KEEP_HTML = {
    "reservations.html",
    "search_history.html",
    "reviews.html",
    "wishlists.html",
    "profile_information.html",  # account id only; not copied to raw/
}

DROP_HTML_HINTS = {
    "activity_log",
    "payment",
    "payout",
    "kyc",
    "id_verification",
    "search_telemetry",
    "messages",
    "host_kyc",
    "coupons",
    "guest_referrals",
    "listing_",
    "resolution_center",
    "airbnb_customer_support",
    "third_party_payees",
}

AIRBNB_TABLES = [
    "airbnb.account",
    "airbnb.reservations",
    "airbnb.searches",
    "airbnb.reviews",
    "airbnb.wishlists",
]

FORBIDDEN_COLUMN_NAMES = {
    "email",
    "phone",
    "number",
    "ip",
    "initial_ip",
    "most_recent_ip",
    "street",
    "formatted_address",
    "raw_location",
    "message",
    "birthdate",
    "facebook_id",
    "verification_code",
    "card",
    "lat",  # profile home coords — search lat kept as search_lat
    "lng",
}


class _AirbnbTableParser(HTMLParser):
    """Extract bootstrap-table sections, including nested item subtables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[tuple[str, list[str], list[list[str]]]] = []
        self._heading = ""
        self._in_heading = False
        self._heading_tag = ""
        self._heading_buf: list[str] = []
        self._stack: list[dict[str, Any]] = []

    def _frame(self) -> dict[str, Any] | None:
        return self._stack[-1] if self._stack else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3"}:
            self._in_heading = True
            self._heading_tag = tag
            self._heading_buf = []
            return
        if tag == "table":
            parent = self._frame()
            if parent is not None and parent["in_td"]:
                # Close the parent cell before diving into the nested table.
                parent["row"].append("".join(parent["cell_buf"]).strip())
                parent["in_td"] = False
                parent["cell_buf"] = []
            self._stack.append(
                {
                    "heading": self._heading,
                    "headers": [],
                    "rows": [],
                    "in_thead": False,
                    "in_tbody": False,
                    "in_th": False,
                    "in_td": False,
                    "cell_buf": [],
                    "row": [],
                    "row_active": False,
                }
            )
            return
        frame = self._frame()
        if frame is None:
            return
        if tag == "thead":
            frame["in_thead"] = True
        elif tag == "tbody":
            frame["in_tbody"] = True
        elif tag == "tr" and (frame["in_thead"] or frame["in_tbody"]):
            frame["row"] = []
            frame["row_active"] = True
        elif tag == "th" and frame["in_thead"] and frame["row_active"]:
            frame["in_th"] = True
            frame["cell_buf"] = []
        elif tag == "td" and frame["in_tbody"] and frame["row_active"]:
            frame["in_td"] = True
            frame["cell_buf"] = []

    def handle_endtag(self, tag: str) -> None:
        if self._in_heading and tag == self._heading_tag:
            self._heading = "".join(self._heading_buf).strip()
            self._in_heading = False
            return
        if tag == "table":
            frame = self._stack.pop() if self._stack else None
            if frame and frame["headers"]:
                self.sections.append(
                    (frame["heading"], frame["headers"], frame["rows"])
                )
            return
        frame = self._frame()
        if frame is None:
            return
        if tag == "thead":
            frame["in_thead"] = False
        elif tag == "tbody":
            frame["in_tbody"] = False
        elif tag == "tr":
            if frame["in_thead"] and frame["row"]:
                frame["headers"] = [c.strip() for c in frame["row"]]
            elif frame["in_tbody"] and frame["row"]:
                frame["rows"].append(frame["row"])
            frame["row_active"] = False
        elif tag == "th" and frame["in_th"]:
            frame["row"].append("".join(frame["cell_buf"]).strip())
            frame["in_th"] = False
        elif tag == "td" and frame["in_td"]:
            frame["row"].append("".join(frame["cell_buf"]).strip())
            frame["in_td"] = False

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self._heading_buf.append(data)
            return
        frame = self._frame()
        if frame is not None and (frame["in_th"] or frame["in_td"]):
            frame["cell_buf"].append(data)


def _parse_html_tables(text: str) -> list[tuple[str, list[str], list[dict[str, str]]]]:
    parser = _AirbnbTableParser()
    parser.feed(text)
    out: list[tuple[str, list[str], list[dict[str, str]]]] = []
    for title, headers, rows in parser.sections:
        dict_rows: list[dict[str, str]] = []
        for cells in rows:
            padded = list(cells) + [""] * max(0, len(headers) - len(cells))
            dict_rows.append(
                {
                    h: html_lib.unescape(padded[i] if i < len(padded) else "")
                    for i, h in enumerate(headers)
                }
            )
        out.append((title, headers, dict_rows))
    return out


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {"N/A", "NA", "NONE", "NULL", "/"}


def _cell(row: dict[str, Any], *names: str) -> str | None:
    lower = {(k or "").strip().lower(): k for k in row if k}
    for name in names:
        key = lower.get(name.lower())
        if key is None:
            continue
        val = row.get(key)
        if _blank(val):
            return None
        return str(val).strip()
    return None


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


def _parse_datetime(value: Any) -> datetime | None:
    if _blank(value):
        return None
    raw = str(value).strip()
    ts = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(raw, errors="coerce")
        if pd.isna(ts):
            return None
        py = ts.to_pydatetime()
        if py.tzinfo is None:
            py = py.replace(tzinfo=UTC)
        return py.astimezone(UTC)
    return ts.to_pydatetime().astimezone(UTC)


def _parse_local_naive(value: Any) -> datetime | None:
    if _blank(value):
        return None
    raw = str(value).strip()
    ts = pd.to_datetime(raw, errors="coerce")
    if pd.isna(ts):
        return None
    py = ts.to_pydatetime()
    return py.replace(tzinfo=None)


def _ts_pair_from_utc(value: Any) -> tuple[datetime | None, datetime | None]:
    ts = _parse_datetime(value)
    if ts is None:
        return None, None
    utc_naive = ts.astimezone(UTC).replace(tzinfo=None)
    local_naive = ts.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return utc_naive, local_naive


def _year_month_hour(
    local_naive: datetime | None, utc_naive: datetime | None = None
) -> tuple[int | None, int | None, int | None, int | None]:
    src = local_naive or utc_naive
    if src is None:
        return None, None, None, None
    return src.year, src.month, src.isoweekday(), src.hour


def _parse_date(value: Any) -> date | None:
    if _blank(value):
        return None
    ts = pd.to_datetime(str(value).strip(), errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _user_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"/users/show/(\d+)", url)
    return m.group(1) if m else None


def _listing_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"/rooms/(\d+)", url)
    return m.group(1) if m else None


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _export_root(path: Path) -> Path | None:
    path = path.resolve()
    if path.is_file() and path.suffix.lower() == ".zip":
        return None
    if not path.is_dir():
        return None
    if (path / "html" / "reservations.html").is_file():
        return path
    if (path / "readme.html").is_file() and (path / "html").is_dir():
        return path
    for child in path.iterdir():
        if child.is_dir() and (child / "html" / "reservations.html").is_file():
            return child
    return None


def _zip_has_airbnb(path: Path) -> bool:
    with zipfile.ZipFile(path) as zf:
        names = {n.lower().replace("\\", "/") for n in zf.namelist()}
    return any(n.endswith("html/reservations.html") for n in names) or any(
        n.endswith("reservations.html") and "/html/" in n for n in names
    )


def _read_member_text(path: Path, *suffixes: str) -> str | None:
    path = path.resolve()
    want = tuple(s.lower().replace("\\", "/") for s in suffixes)
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                norm = name.lower().replace("\\", "/")
                if any(norm.endswith(s) for s in want):
                    return zf.read(name).decode("utf-8", errors="replace")
        return None
    root = _export_root(path)
    if root is None:
        return None
    for s in want:
        candidate = root / s
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
        # also try html/<basename>
        base = Path(s).name
        alt = root / "html" / base
        if alt.is_file():
            return alt.read_text(encoding="utf-8", errors="replace")
    return None


def _copy_keep_html(path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    keep = {n for n in KEEP_HTML if n != "profile_information.html"}
    path = path.resolve()
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                base = Path(name).name.lower()
                if base not in keep:
                    continue
                target = dest / Path(name).name
                target.write_bytes(zf.read(name))
        return
    root = _export_root(path)
    if root is None:
        return
    html_dir = root / "html"
    for name in keep:
        src = html_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)


def _section_rows(
    tables: list[tuple[str, list[str], list[dict[str, str]]]],
    *title_contains: str,
) -> list[dict[str, str]]:
    for title, _headers, rows in tables:
        t = title.lower()
        if all(part.lower() in t for part in title_contains):
            return rows
    return []


def _kv_map(rows: list[dict[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        key = _cell(row, "key")
        val = _cell(row, "value")
        if key:
            out[key] = val or ""
    return out


class AirbnbSource:
    name = "airbnb"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                return _zip_has_airbnb(path)
            except zipfile.BadZipFile:
                return False
        return _export_root(path) is not None

    def tables(self) -> list[str]:
        return list(AIRBNB_TABLES)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for qualified in AIRBNB_TABLES:
            schema, table = qualified.split(".", 1)
            try:
                n = conn.execute(
                    f"SELECT count(*) FROM {schema}.{table}"  # noqa: S608
                ).fetchone()
                counts[table] = int(n[0]) if n else 0
            except duckdb.Error:
                counts[table] = 0
        span = conn.execute("""
            SELECT min(d), max(d) FROM (
                SELECT start_date AS d FROM airbnb.reservations
                WHERE start_date IS NOT NULL
                UNION ALL
                SELECT cast(ts_local AS DATE) FROM airbnb.searches
                WHERE ts_local IS NOT NULL
            )
            """).fetchone()
        first_d, last_d = (span[0], span[1]) if span else (None, None)
        summary = (
            f"airbnb: {counts.get('reservations', 0)} reservations, "
            f"{counts.get('searches', 0)} searches, "
            f"{counts.get('reviews', 0)} reviews, "
            f"{counts.get('wishlists', 0)} wishlist rows"
        )
        if first_d and last_d:
            summary += f"; {first_d} → {last_d}"
        return {
            "counts": counts,
            "first_day": first_d,
            "last_day": last_d,
            "summary": summary,
        }

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        dest = raw_dir(self.name)
        if dest.exists():
            shutil.rmtree(dest)
        _copy_keep_html(path, dest)

        profile_html = _read_member_text(path, "html/profile_information.html")
        account_id = self._extract_account_id(profile_html)

        reservations_html = _read_member_text(path, "html/reservations.html") or ""
        searches_html = _read_member_text(path, "html/search_history.html") or ""
        reviews_html = _read_member_text(path, "html/reviews.html") or ""
        wishlists_html = _read_member_text(path, "html/wishlists.html") or ""

        account_df = self._account_frame(profile_html, account_id)
        reservations_df = self._reservations_frame(
            _parse_html_tables(reservations_html), account_id
        )
        searches_df = self._searches_frame(_parse_html_tables(searches_html))
        reviews_df = self._reviews_frame(_parse_html_tables(reviews_html), account_id)
        wishlists_df = self._wishlists_frame(_parse_html_tables(wishlists_html))

        self._create_schema(conn)
        conn.register("_ab_account", account_df)
        conn.register("_ab_reservations", reservations_df)
        conn.register("_ab_searches", searches_df)
        conn.register("_ab_reviews", reviews_df)
        conn.register("_ab_wishlists", wishlists_df)
        conn.execute("INSERT INTO airbnb.account SELECT * FROM _ab_account")
        conn.execute("INSERT INTO airbnb.reservations SELECT * FROM _ab_reservations")
        conn.execute("INSERT INTO airbnb.searches SELECT * FROM _ab_searches")
        conn.execute("INSERT INTO airbnb.reviews SELECT * FROM _ab_reviews")
        conn.execute("INSERT INTO airbnb.wishlists SELECT * FROM _ab_wishlists")
        for name in (
            "_ab_account",
            "_ab_reservations",
            "_ab_searches",
            "_ab_reviews",
            "_ab_wishlists",
        ):
            conn.unregister(name)

        (dest / "source_path.txt").write_text(str(path) + "\n", encoding="utf-8")

    def _extract_account_id(self, profile_html: str | None) -> str | None:
        if not profile_html:
            return None
        tables = _parse_html_tables(profile_html)
        user_rows = _section_rows(tables, "User")
        # Prefer the key/value User table (not User Profile Photos etc.)
        for title, headers, rows in tables:
            if title.strip().lower() == "user" and "key" in [
                h.lower() for h in headers
            ]:
                kv = _kv_map(rows)
                if kv.get("id"):
                    return kv["id"].strip()
        kv = _kv_map(user_rows)
        return (kv.get("id") or "").strip() or None

    def _account_frame(
        self, profile_html: str | None, account_id: str | None
    ) -> pd.DataFrame:
        cols = [
            "account_id",
            "created_at_utc",
            "created_at_local",
            "market",
            "preferred_locale",
            "native_currency",
            "year",
        ]
        if not profile_html or not account_id:
            return _empty(cols)
        tables = _parse_html_tables(profile_html)
        kv: dict[str, str] = {}
        for title, headers, rows in tables:
            if title.strip().lower() == "user" and "key" in [
                h.lower() for h in headers
            ]:
                kv = _kv_map(rows)
                break
        created_utc, created_local = _ts_pair_from_utc(kv.get("createdAt"))
        year, _, _, _ = _year_month_hour(created_local, created_utc)
        return pd.DataFrame(
            [
                {
                    "account_id": account_id,
                    "created_at_utc": created_utc,
                    "created_at_local": created_local,
                    "market": kv.get("market") or None,
                    "preferred_locale": kv.get("preferredLocale") or None,
                    "native_currency": kv.get("nativeCurrency") or None,
                    "year": year,
                }
            ]
        )

    def _create_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("CREATE SCHEMA IF NOT EXISTS airbnb")
        conn.execute("DROP TABLE IF EXISTS airbnb.wishlists")
        conn.execute("DROP TABLE IF EXISTS airbnb.reviews")
        conn.execute("DROP TABLE IF EXISTS airbnb.searches")
        conn.execute("DROP TABLE IF EXISTS airbnb.reservations")
        conn.execute("DROP TABLE IF EXISTS airbnb.account")
        conn.execute("""
            CREATE TABLE airbnb.account (
                account_id VARCHAR PRIMARY KEY,
                created_at_utc TIMESTAMP,
                created_at_local TIMESTAMP,
                market VARCHAR,
                preferred_locale VARCHAR,
                native_currency VARCHAR,
                year INTEGER
            )
            """)
        conn.execute("""
            CREATE TABLE airbnb.reservations (
                confirmation_code VARCHAR PRIMARY KEY,
                role VARCHAR,
                status VARCHAR,
                listing_id VARCHAR,
                hosting_url VARCHAR,
                nights INTEGER,
                guests INTEGER,
                start_date DATE,
                end_date DATE,
                host_vat_country VARCHAR,
                guest_vat_country VARCHAR,
                currency VARCHAR,
                bringing_pets BOOLEAN,
                created_at_utc TIMESTAMP,
                created_at_local TIMESTAMP,
                canceled_at_utc TIMESTAMP,
                canceled_at_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                weekday INTEGER
            )
            """)
        conn.execute("""
            CREATE TABLE airbnb.searches (
                search_id INTEGER PRIMARY KEY,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                weekday INTEGER,
                hour INTEGER,
                city VARCHAR,
                state VARCHAR,
                country VARCHAR,
                search_lat DOUBLE,
                search_lon DOUBLE,
                check_in DATE,
                check_out DATE,
                nights INTEGER,
                guests INTEGER
            )
            """)
        conn.execute("""
            CREATE TABLE airbnb.reviews (
                review_id VARCHAR PRIMARY KEY,
                direction VARCHAR,
                role_of_me VARCHAR,
                rating INTEGER,
                comment VARCHAR,
                comment_language VARCHAR,
                listing_id VARCHAR,
                bookable_id VARCHAR,
                entity_type VARCHAR,
                recommended BOOLEAN,
                submitted_at_utc TIMESTAMP,
                submitted_at_local TIMESTAMP,
                year INTEGER,
                month INTEGER,
                weekday INTEGER
            )
            """)
        conn.execute("""
            CREATE TABLE airbnb.wishlists (
                wishlist_id VARCHAR,
                wishlist_name VARCHAR,
                listing_id VARCHAR,
                pdp_type VARCHAR,
                check_in DATE,
                check_out DATE,
                PRIMARY KEY (wishlist_id, listing_id)
            )
            """)

    def _reservations_frame(
        self,
        tables: list[tuple[str, list[str], list[dict[str, str]]]],
        account_id: str | None,
    ) -> pd.DataFrame:
        cols = [
            "confirmation_code",
            "role",
            "status",
            "listing_id",
            "hosting_url",
            "nights",
            "guests",
            "start_date",
            "end_date",
            "host_vat_country",
            "guest_vat_country",
            "currency",
            "bringing_pets",
            "created_at_utc",
            "created_at_local",
            "canceled_at_utc",
            "canceled_at_local",
            "year",
            "month",
            "weekday",
        ]
        rows = _section_rows(tables, "Reservations")
        # Prefer the wide reservations table (has Confirmation Code).
        for title, headers, section_rows in tables:
            if title.strip().lower() == "reservations" and any(
                h.lower() == "confirmation code" for h in headers
            ):
                rows = section_rows
                break
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            code = _cell(row, "Confirmation Code")
            if not code or code in seen:
                continue
            seen.add(code)
            host_id = _user_id_from_url(_cell(row, "Host Profile Url"))
            guest_id = _user_id_from_url(_cell(row, "Guest Profile Url"))
            role: str | None = None
            if account_id and guest_id == account_id:
                role = "guest"
            elif account_id and host_id == account_id:
                role = "host"
            elif account_id and guest_id and host_id:
                role = "other"
            hosting_url = _cell(row, "Hosting Url")
            start = _parse_date(_cell(row, "Start Date"))
            nights = _to_int(_cell(row, "Nights"))
            end = None
            if start is not None and nights is not None:
                end = (pd.Timestamp(start) + pd.Timedelta(days=nights)).date()
            created_utc, created_local = _ts_pair_from_utc(_cell(row, "Created At"))
            canceled_utc, canceled_local = _ts_pair_from_utc(_cell(row, "Canceled At"))
            # Prefer start_date year for trip filters.
            year = start.year if start is not None else None
            month = start.month if start is not None else None
            weekday = start.isoweekday() if start is not None else None
            if year is None:
                year, month, weekday, _ = _year_month_hour(created_local, created_utc)
            out.append(
                {
                    "confirmation_code": code,
                    "role": role,
                    "status": (_cell(row, "Status") or "").lower() or None,
                    "listing_id": _listing_id_from_url(hosting_url),
                    "hosting_url": hosting_url,
                    "nights": nights,
                    "guests": _to_int(_cell(row, "Number Of Guests")),
                    "start_date": start,
                    "end_date": end,
                    "host_vat_country": _cell(row, "Host Vat Country"),
                    "guest_vat_country": _cell(row, "Guest Vat Country"),
                    "currency": _cell(row, "Guest Currency")
                    or _cell(row, "Host Currency"),
                    "bringing_pets": _to_bool(_cell(row, "Is Bringing Pets")),
                    "created_at_utc": created_utc,
                    "created_at_local": created_local,
                    "canceled_at_utc": canceled_utc,
                    "canceled_at_local": canceled_local,
                    "year": year,
                    "month": month,
                    "weekday": weekday,
                }
            )
        return pd.DataFrame(out, columns=cols) if out else _empty(cols)

    def _searches_frame(
        self, tables: list[tuple[str, list[str], list[dict[str, str]]]]
    ) -> pd.DataFrame:
        cols = [
            "search_id",
            "ts_utc",
            "ts_local",
            "year",
            "month",
            "weekday",
            "hour",
            "city",
            "state",
            "country",
            "search_lat",
            "search_lon",
            "check_in",
            "check_out",
            "nights",
            "guests",
        ]
        rows: list[dict[str, str]] = []
        for _title, headers, section_rows in tables:
            if any(h.lower() == "time of search" for h in headers):
                rows = section_rows
                break
        out: list[dict[str, Any]] = []
        for i, row in enumerate(rows):
            # Search timestamps are wall-clock without TZ; treat as Paris local.
            local = _parse_local_naive(_cell(row, "Time of Search"))
            utc = None
            if local is not None:
                aware = local.replace(tzinfo=LOCAL_TZ).astimezone(UTC)
                utc = aware.replace(tzinfo=None)
            year, month, weekday, hour = _year_month_hour(local, utc)
            city = _cell(row, "City")
            # Sometimes City holds a country name; keep as-is for map labels.
            out.append(
                {
                    "search_id": i + 1,
                    "ts_utc": utc,
                    "ts_local": local,
                    "year": year,
                    "month": month,
                    "weekday": weekday,
                    "hour": hour,
                    "city": city,
                    "state": _cell(row, "State"),
                    "country": _cell(row, "Country"),
                    "search_lat": _to_float(_cell(row, "Search Location Latitude")),
                    "search_lon": _to_float(_cell(row, "Search Location Longitude")),
                    "check_in": _parse_date(_cell(row, "Check In Date")),
                    "check_out": _parse_date(_cell(row, "Check Out Date")),
                    "nights": _to_int(_cell(row, "Number of Nights")),
                    "guests": _to_int(_cell(row, "Number of Guests")),
                }
            )
        return pd.DataFrame(out, columns=cols) if out else _empty(cols)

    def _reviews_frame(
        self,
        tables: list[tuple[str, list[str], list[dict[str, str]]]],
        account_id: str | None,
    ) -> pd.DataFrame:
        cols = [
            "review_id",
            "direction",
            "role_of_me",
            "rating",
            "comment",
            "comment_language",
            "listing_id",
            "bookable_id",
            "entity_type",
            "recommended",
            "submitted_at_utc",
            "submitted_at_local",
            "year",
            "month",
            "weekday",
        ]
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for title, headers, section_rows in tables:
            direction: str | None = None
            t = title.lower()
            if "provided" in t:
                direction = "provided"
            elif "received" in t:
                direction = "received"
            else:
                continue
            if "review" not in [h.lower() for h in headers]:
                continue
            for row in section_rows:
                raw = _cell(row, "Review")
                if not raw or raw.lower().startswith("see subtable"):
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                rid = str(payload.get("reviewId") or "")
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                submitted_utc, submitted_local = _ts_pair_from_utc(
                    payload.get("submittedAt") or payload.get("createdAt")
                )
                year, month, weekday, _ = _year_month_hour(
                    submitted_local, submitted_utc
                )
                reviewer = str(payload.get("reviewerId") or "")
                reviewee = str(payload.get("revieweeId") or "")
                role_of_me = None
                if account_id and reviewer == account_id:
                    role_of_me = str(payload.get("reviewerRole") or "").lower() or None
                elif account_id and reviewee == account_id:
                    role_of_me = str(payload.get("revieweeRole") or "").lower() or None
                listing = payload.get("entityId") or payload.get("bookableId")
                out.append(
                    {
                        "review_id": rid,
                        "direction": direction,
                        "role_of_me": role_of_me,
                        "rating": _to_int(payload.get("rating")),
                        "comment": (
                            str(payload["comment"]).strip()
                            if payload.get("comment")
                            else None
                        ),
                        "comment_language": payload.get("commentLanguage") or None,
                        "listing_id": str(listing) if listing is not None else None,
                        "bookable_id": (
                            str(payload["bookableId"])
                            if payload.get("bookableId") is not None
                            else None
                        ),
                        "entity_type": payload.get("entityType") or None,
                        "recommended": _to_bool(payload.get("isEntityRecommended")),
                        "submitted_at_utc": submitted_utc,
                        "submitted_at_local": submitted_local,
                        "year": year,
                        "month": month,
                        "weekday": weekday,
                    }
                )
        return pd.DataFrame(out, columns=cols) if out else _empty(cols)

    def _wishlists_frame(
        self, tables: list[tuple[str, list[str], list[dict[str, str]]]]
    ) -> pd.DataFrame:
        cols = [
            "wishlist_id",
            "wishlist_name",
            "listing_id",
            "pdp_type",
            "check_in",
            "check_out",
        ]
        # Parent wishlist names
        names: dict[str, str] = {}
        for _title, headers, rows in tables:
            if "name" in [h.lower() for h in headers] and "wishlist id" in [
                h.lower() for h in headers
            ]:
                for row in rows:
                    wid = _cell(row, "Wishlist Id")
                    name = _cell(row, "Name")
                    if wid and name:
                        names[wid] = name

        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for _title, headers, rows in tables:
            header_l = [h.lower() for h in headers]
            # Nested item subtables
            if "pdp id" in header_l or "wishlist item id" in header_l:
                for row in rows:
                    wid = _cell(row, "Wishlist Id") or ""
                    listing = _cell(row, "Pdp Id") or _cell(row, "Wishlist Item Id")
                    if not wid or not listing:
                        continue
                    key = (wid, listing)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(
                        {
                            "wishlist_id": wid,
                            "wishlist_name": names.get(wid),
                            "listing_id": listing,
                            "pdp_type": _cell(row, "Pdp Type"),
                            "check_in": _parse_date(
                                _cell(row, "Check In") or _cell(row, "Check In Date")
                            ),
                            "check_out": _parse_date(
                                _cell(row, "Check Out") or _cell(row, "Check Out Date")
                            ),
                        }
                    )
                continue
            # Parent rows with inline JSON item arrays
            if "wishlist item data" in header_l:
                for row in rows:
                    wid = _cell(row, "Wishlist Id") or ""
                    raw_items = _cell(row, "Wishlist Item Data")
                    if (
                        not wid
                        or not raw_items
                        or raw_items.lower().startswith("see subtable")
                    ):
                        continue
                    try:
                        items = json.loads(raw_items)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        listing = str(
                            item.get("pdpId") or item.get("wishlistItemId") or ""
                        )
                        if not listing:
                            continue
                        key = (wid, listing)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(
                            {
                                "wishlist_id": wid,
                                "wishlist_name": names.get(wid) or _cell(row, "Name"),
                                "listing_id": listing,
                                "pdp_type": item.get("pdpType"),
                                "check_in": _parse_date(item.get("checkIn")),
                                "check_out": _parse_date(item.get("checkOut")),
                            }
                        )
        return pd.DataFrame(out, columns=cols) if out else _empty(cols)
