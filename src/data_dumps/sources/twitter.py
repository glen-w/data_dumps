"""Twitter / X YTD archive (window.YTD.*.partN) → DuckDB.

Classic HTML-viewer exports use JavaScript assignment files under data/.
IPs, emails, phones, ads, and device tokens are not loaded. Media stays in the
inbox archive; the warehouse stores paths/kinds only.

Newer X exports may use different filenames or shapes — detect/load fail clearly.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Rome")

TWEETS_JS = "tweets.js"
ARCHIVE_HTML = "Your archive.html"
MANIFEST_JS = "manifest.js"
ACCOUNT_JS = "account.js"

YTD_ASSIGN_RE = re.compile(r"^window\.YTD\.[^=]+=\s*", re.MULTILINE)
SOURCE_TAG_RE = re.compile(r"<[^>]+>([^<]*)</[^>]+>")

KEEP_JS_STEMS = {
    "account",
    "tweets",
    "like",
    "follower",
    "following",
    "direct-messages",
    "deleted-tweets",
}

SKIP_JS_STEMS = {
    "account-creation-ip",
    "ip-audit",
    "phone-number",
    "email-address-change",
    "contact",
    "device-token",
    "ni-devices",
    "personalization",
    "ageinfo",
    "sso",
    "key-registry",
    "ad-engagements",
    "ad-impressions",
    "ad-mobile-conversions-attributed",
    "ad-mobile-conversions-unattributed",
    "ad-online-conversions-attributed",
    "ad-online-conversions-unattributed",
}

TWITTER_TABLES = [
    "twitter.account",
    "twitter.tweets",
    "twitter.tweet_hashtags",
    "twitter.tweet_mentions",
    "twitter.likes",
    "twitter.followers",
    "twitter.following",
    "twitter.dm_conversations",
    "twitter.dm_messages",
    "twitter.deleted_tweets",
]


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {"N/A", "NA", "NONE", "NULL"}


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


def _stem(name: str) -> str:
    return Path(name).name.removesuffix(".js").lower()


def _base_stem(name: str) -> str:
    stem = _stem(name)
    if ".part" in stem:
        return stem.split(".part", 1)[0]
    return stem


def _parse_ytd_json(text: str) -> list[Any]:
    body = YTD_ASSIGN_RE.sub("", text, count=1).strip()
    if body.endswith(";"):
        body = body[:-1].strip()
    return json.loads(body)


def _load_ytd_records(
    raw_dir_path: Path, stem: str
) -> tuple[list[dict[str, Any]], int]:
    """Load and merge all part files for a YTD stem; return (records, skipped_rows)."""
    files = sorted(raw_dir_path.glob(f"{stem}.js")) + sorted(
        raw_dir_path.glob(f"{stem}.part*.js")
    )
    if not files:
        return [], 0
    records: list[dict[str, Any]] = []
    skipped = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            payload = _parse_ytd_json(text)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            skipped += 1
            continue
        if not isinstance(payload, list):
            skipped += 1
            continue
        for item in payload:
            if isinstance(item, dict):
                records.append(item)
            else:
                skipped += 1
    return records, skipped


def _unwrap(record: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        inner = record.get(key)
        if isinstance(inner, dict):
            return inner
    return record


def _parse_twitter_ts(raw: str | None) -> tuple[datetime | None, datetime | None]:
    if _blank(raw):
        return None, None
    text = str(raw).strip()
    try:
        if text.endswith("Z") or re.match(r"^\d{4}-\d{2}-\d{2}T", text):
            ts_utc = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
        else:
            ts_utc = parsedate_to_datetime(text).astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None, None
    ts_local = ts_utc.astimezone(LOCAL_TZ)
    return ts_utc.replace(tzinfo=None), ts_local.replace(tzinfo=None)


def _year_month(
    ts_utc: datetime | None, ts_local: datetime | None
) -> tuple[int | None, int | None]:
    ts = ts_local or ts_utc
    if ts is None:
        return None, None
    return ts.year, ts.month


def _strip_source(html: str | None) -> str | None:
    if _blank(html):
        return None
    text = unescape(str(html))
    match = SOURCE_TAG_RE.search(text)
    if match:
        return match.group(1).strip() or None
    return re.sub(r"<[^>]+>", "", text).strip() or None


def _tweet_type(tweet: dict[str, Any]) -> str:
    text = str(tweet.get("full_text") or "")
    if text.startswith("RT @"):
        return "retweet"
    if tweet.get("quoted_status_id") or tweet.get("is_quote_status"):
        return "quote"
    if tweet.get("in_reply_to_status_id_str") or tweet.get("in_reply_to_status_id"):
        return "reply"
    return "original"


def _media_kind(tweet: dict[str, Any]) -> str:
    media = (tweet.get("entities") or {}).get("media") or []
    if not media:
        return "none"
    kinds = {str(m.get("type") or "unknown") for m in media if isinstance(m, dict)}
    if len(kinds) == 1:
        return next(iter(kinds))
    return "mixed"


def _media_relpath(tweet: dict[str, Any], export_root: Path) -> str | None:
    media = (tweet.get("entities") or {}).get("media") or []
    for item in media:
        if not isinstance(item, dict):
            continue
        for key in ("media_url_https", "media_url", "url"):
            url = item.get(key)
            if isinstance(url, str) and url:
                # Archive stores files under data/tweets_media/ etc.; keep URL tail hint.
                return url.split("/")[-1] if "/" in url else url
    return None


class TwitterSource:
    name = "twitter"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    names = {
                        n.rstrip("/").split("/")[-1].lower() for n in zf.namelist()
                    }
            except (OSError, zipfile.BadZipFile):
                return False
            return (
                TWEETS_JS in names
                and (
                    ARCHIVE_HTML.lower().replace(" ", " ") in names
                    or MANIFEST_JS in names
                    or ACCOUNT_JS in names
                )
                and any(n.rstrip("/").endswith(TWEETS_JS) for n in zf.namelist())
            )
        root = self._archive_root(path)
        if root is None:
            return False
        data = root / "data"
        if not (data / TWEETS_JS).is_file():
            return False
        if not (
            (root / ARCHIVE_HTML).is_file()
            or (data / MANIFEST_JS).is_file()
            or (data / ACCOUNT_JS).is_file()
        ):
            return False
        return self._looks_like_ytd_archive(data)

    def _looks_like_ytd_archive(self, data_dir: Path) -> bool:
        records, _ = _load_ytd_records(data_dir, "tweets")
        if not records:
            return False
        sample = _unwrap(records[0], "tweet")
        return bool(sample.get("id_str") or sample.get("id"))

    def _archive_root(self, path: Path) -> Path | None:
        if not path.is_dir():
            return None
        if (path / "data" / TWEETS_JS).is_file():
            return path
        nested = [
            p
            for p in path.iterdir()
            if p.is_dir() and (p / "data" / TWEETS_JS).is_file()
        ]
        if len(nested) == 1:
            return nested[0]
        return None

    def tables(self) -> list[str]:
        return list(TWITTER_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        raw, export_root = self._materialize(path)
        data_dir = raw / "data"
        if not (data_dir / TWEETS_JS).is_file():
            raise ValueError(
                "Expected Twitter YTD archive with data/tweets.js; "
                "newer X dumps may use a different layout."
            )

        skipped_rows = 0
        frames: dict[str, pd.DataFrame] = {}
        account_df, n = self._account_frame(data_dir, export_root)
        skipped_rows += n
        frames["account"] = account_df

        tweets_df, hashtags_df, mentions_df, n = self._tweet_frames(
            data_dir, export_root
        )
        skipped_rows += n
        frames["tweets"] = tweets_df
        frames["tweet_hashtags"] = hashtags_df
        frames["tweet_mentions"] = mentions_df

        likes_df, n = self._likes_frame(data_dir)
        skipped_rows += n
        frames["likes"] = likes_df

        followers_df, n = self._followers_frame(data_dir)
        skipped_rows += n
        frames["followers"] = followers_df

        following_df, n = self._following_frame(data_dir)
        skipped_rows += n
        frames["following"] = following_df

        dm_conv_df, dm_msg_df, n = self._dm_frames(data_dir)
        skipped_rows += n
        frames["dm_conversations"] = dm_conv_df
        frames["dm_messages"] = dm_msg_df

        deleted_df, n = self._deleted_tweets_frame(data_dir)
        skipped_rows += n
        frames["deleted_tweets"] = deleted_df

        conn.execute("DROP SCHEMA IF EXISTS twitter CASCADE")
        conn.execute("CREATE SCHEMA twitter")
        self._create_tables(conn)
        for table, df in frames.items():
            tmp = f"_tw_{table}"
            conn.register(tmp, df)
            conn.execute(f"INSERT INTO twitter.{table} BY NAME SELECT * FROM {tmp}")
            conn.unregister(tmp)

        self._skipped_rows = skipped_rows

    def _materialize(self, path: Path) -> tuple[Path, Path]:
        dest = raw_dir("twitter")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        data_dest = dest / "data"
        data_dest.mkdir(parents=True)

        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    base = name.rstrip("/").split("/")[-1]
                    if not base.endswith(".js"):
                        continue
                    stem = _base_stem(base)
                    if stem in SKIP_JS_STEMS:
                        continue
                    if stem in KEEP_JS_STEMS:
                        target = data_dest / base
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as zf_src, target.open("wb") as out:
                            shutil.copyfileobj(zf_src, out)
            export_root = path
        else:
            root = self._archive_root(path)
            if root is None:
                raise FileNotFoundError(f"No Twitter YTD data/tweets.js under {path}")
            for js_path in (root / "data").glob("*.js"):
                stem = _base_stem(js_path.name)
                if stem in SKIP_JS_STEMS:
                    continue
                if stem in KEEP_JS_STEMS:
                    shutil.copy2(js_path, data_dest / js_path.name)
            export_root = root

        (dest / "export_root.txt").write_text(str(export_root) + "\n", encoding="utf-8")
        return dest, export_root

    def _create_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE twitter.account (
                account_id VARCHAR,
                username VARCHAR,
                display_name VARCHAR,
                created_at TIMESTAMP,
                export_root VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE twitter.tweets (
                tweet_id VARCHAR,
                full_text VARCHAR,
                lang VARCHAR,
                client VARCHAR,
                tweet_type VARCHAR,
                in_reply_to_tweet_id VARCHAR,
                in_reply_to_screen_name VARCHAR,
                in_reply_to_user_id VARCHAR,
                favorite_count BIGINT,
                retweet_count BIGINT,
                favorited BOOLEAN,
                retweeted BOOLEAN,
                media_kind VARCHAR,
                media_relpath VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE twitter.tweet_hashtags (
                tweet_id VARCHAR,
                hashtag VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE twitter.tweet_mentions (
                tweet_id VARCHAR,
                screen_name VARCHAR,
                user_id VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE twitter.likes (
                tweet_id VARCHAR,
                full_text VARCHAR,
                expanded_url VARCHAR,
                liked_screen_name VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE twitter.followers (
                account_id VARCHAR,
                user_link VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE twitter.following (
                account_id VARCHAR,
                user_link VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE twitter.dm_conversations (
                conversation_id VARCHAR,
                n_messages BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE twitter.dm_messages (
                conversation_id VARCHAR,
                message_id VARCHAR,
                sender_id VARCHAR,
                recipient_id VARCHAR,
                text VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE twitter.deleted_tweets (
                tweet_id VARCHAR,
                full_text VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                year BIGINT,
                month BIGINT
            )
            """)

    def _account_frame(
        self, data_dir: Path, export_root: Path
    ) -> tuple[pd.DataFrame, int]:
        cols = ["account_id", "username", "display_name", "created_at", "export_root"]
        records, skipped = _load_ytd_records(data_dir, "account")
        if not records:
            return _empty(cols), skipped
        acct = _unwrap(records[0], "account")
        created_utc, _ = _parse_twitter_ts(acct.get("createdAt"))
        return (
            pd.DataFrame(
                [
                    {
                        "account_id": str(acct.get("accountId") or ""),
                        "username": acct.get("username"),
                        "display_name": acct.get("accountDisplayName"),
                        "created_at": created_utc,
                        "export_root": str(export_root),
                    }
                ]
            ),
            skipped,
        )

    def _tweet_frames(
        self, data_dir: Path, export_root: Path
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
        tweet_cols = [
            "tweet_id",
            "full_text",
            "lang",
            "client",
            "tweet_type",
            "in_reply_to_tweet_id",
            "in_reply_to_screen_name",
            "in_reply_to_user_id",
            "favorite_count",
            "retweet_count",
            "favorited",
            "retweeted",
            "media_kind",
            "media_relpath",
            "ts_utc",
            "ts_local",
            "year",
            "month",
        ]
        records, skipped = _load_ytd_records(data_dir, "tweets")
        tweet_rows: list[dict[str, Any]] = []
        hashtag_rows: list[dict[str, Any]] = []
        mention_rows: list[dict[str, Any]] = []
        for rec in records:
            try:
                tweet = _unwrap(rec, "tweet")
                tweet_id = str(tweet.get("id_str") or tweet.get("id") or "")
                if not tweet_id:
                    skipped += 1
                    continue
                ts_utc, ts_local = _parse_twitter_ts(tweet.get("created_at"))
                if ts_utc is None:
                    skipped += 1
                    continue
                year, month = _year_month(ts_utc, ts_local)
                tweet_rows.append(
                    {
                        "tweet_id": tweet_id,
                        "full_text": tweet.get("full_text"),
                        "lang": tweet.get("lang"),
                        "client": _strip_source(tweet.get("source")),
                        "tweet_type": _tweet_type(tweet),
                        "in_reply_to_tweet_id": tweet.get("in_reply_to_status_id_str")
                        or (
                            str(tweet.get("in_reply_to_status_id"))
                            if tweet.get("in_reply_to_status_id") is not None
                            else None
                        ),
                        "in_reply_to_screen_name": tweet.get("in_reply_to_screen_name"),
                        "in_reply_to_user_id": (
                            str(tweet.get("in_reply_to_user_id_str"))
                            if tweet.get("in_reply_to_user_id_str") is not None
                            else None
                        ),
                        "favorite_count": int(tweet.get("favorite_count") or 0),
                        "retweet_count": int(tweet.get("retweet_count") or 0),
                        "favorited": bool(tweet.get("favorited")),
                        "retweeted": bool(tweet.get("retweeted")),
                        "media_kind": _media_kind(tweet),
                        "media_relpath": _media_relpath(tweet, export_root),
                        "ts_utc": ts_utc,
                        "ts_local": ts_local,
                        "year": year,
                        "month": month,
                    }
                )
                for tag in (tweet.get("entities") or {}).get("hashtags") or []:
                    if isinstance(tag, dict) and tag.get("text"):
                        hashtag_rows.append(
                            {"tweet_id": tweet_id, "hashtag": tag["text"].lower()}
                        )
                for mention in (tweet.get("entities") or {}).get("user_mentions") or []:
                    if isinstance(mention, dict) and mention.get("screen_name"):
                        mention_rows.append(
                            {
                                "tweet_id": tweet_id,
                                "screen_name": mention["screen_name"].lower(),
                                "user_id": str(mention.get("id_str") or ""),
                            }
                        )
            except (TypeError, ValueError):
                skipped += 1
        return (
            pd.DataFrame(tweet_rows) if tweet_rows else _empty(tweet_cols),
            (
                pd.DataFrame(hashtag_rows)
                if hashtag_rows
                else _empty(["tweet_id", "hashtag"])
            ),
            (
                pd.DataFrame(mention_rows)
                if mention_rows
                else _empty(["tweet_id", "screen_name", "user_id"])
            ),
            skipped,
        )

    def _likes_frame(self, data_dir: Path) -> tuple[pd.DataFrame, int]:
        cols = [
            "tweet_id",
            "full_text",
            "expanded_url",
            "liked_screen_name",
            "ts_utc",
            "ts_local",
            "year",
            "month",
        ]
        records, skipped = _load_ytd_records(data_dir, "like")
        rows: list[dict[str, Any]] = []
        for rec in records:
            try:
                like = _unwrap(rec, "like")
                tweet_id = str(like.get("tweetId") or "")
                if not tweet_id:
                    skipped += 1
                    continue
                rows.append(
                    {
                        "tweet_id": tweet_id,
                        "full_text": like.get("fullText"),
                        "expanded_url": like.get("expandedUrl"),
                        "liked_screen_name": None,
                        "ts_utc": None,
                        "ts_local": None,
                        "year": None,
                        "month": None,
                    }
                )
            except (TypeError, ValueError):
                skipped += 1
        return (pd.DataFrame(rows) if rows else _empty(cols), skipped)

    def _followers_frame(self, data_dir: Path) -> tuple[pd.DataFrame, int]:
        records, skipped = _load_ytd_records(data_dir, "follower")
        rows = []
        for rec in records:
            try:
                follower = _unwrap(rec, "follower")
                rows.append(
                    {
                        "account_id": str(follower.get("accountId") or ""),
                        "user_link": follower.get("userLink"),
                    }
                )
            except (TypeError, ValueError):
                skipped += 1
        cols = ["account_id", "user_link"]
        return (pd.DataFrame(rows) if rows else _empty(cols), skipped)

    def _following_frame(self, data_dir: Path) -> tuple[pd.DataFrame, int]:
        records, skipped = _load_ytd_records(data_dir, "following")
        rows = []
        for rec in records:
            try:
                following = _unwrap(rec, "following")
                rows.append(
                    {
                        "account_id": str(following.get("accountId") or ""),
                        "user_link": following.get("userLink"),
                    }
                )
            except (TypeError, ValueError):
                skipped += 1
        cols = ["account_id", "user_link"]
        return (pd.DataFrame(rows) if rows else _empty(cols), skipped)

    def _dm_frames(self, data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, int]:
        records, skipped = _load_ytd_records(data_dir, "direct-messages")
        conv_rows: list[dict[str, Any]] = []
        msg_rows: list[dict[str, Any]] = []
        for rec in records:
            try:
                conv = _unwrap(rec, "dmConversation")
                conv_id = str(conv.get("conversationId") or "")
                messages = conv.get("messages") or []
                if not conv_id:
                    skipped += 1
                    continue
                conv_rows.append(
                    {"conversation_id": conv_id, "n_messages": len(messages)}
                )
                for msg_wrap in messages:
                    if not isinstance(msg_wrap, dict):
                        skipped += 1
                        continue
                    msg = msg_wrap.get("messageCreate") or {}
                    ts_utc, ts_local = _parse_twitter_ts(msg.get("createdAt"))
                    year, month = _year_month(ts_utc, ts_local)
                    msg_rows.append(
                        {
                            "conversation_id": conv_id,
                            "message_id": str(msg.get("id") or ""),
                            "sender_id": str(msg.get("senderId") or ""),
                            "recipient_id": str(msg.get("recipientId") or ""),
                            "text": msg.get("text"),
                            "ts_utc": ts_utc,
                            "ts_local": ts_local,
                            "year": year,
                            "month": month,
                        }
                    )
            except (TypeError, ValueError):
                skipped += 1
        conv_cols = ["conversation_id", "n_messages"]
        msg_cols = [
            "conversation_id",
            "message_id",
            "sender_id",
            "recipient_id",
            "text",
            "ts_utc",
            "ts_local",
            "year",
            "month",
        ]
        return (
            pd.DataFrame(conv_rows) if conv_rows else _empty(conv_cols),
            pd.DataFrame(msg_rows) if msg_rows else _empty(msg_cols),
            skipped,
        )

    def _deleted_tweets_frame(self, data_dir: Path) -> tuple[pd.DataFrame, int]:
        cols = ["tweet_id", "full_text", "ts_utc", "ts_local", "year", "month"]
        records, skipped = _load_ytd_records(data_dir, "deleted-tweets")
        rows: list[dict[str, Any]] = []
        for rec in records:
            try:
                tweet = _unwrap(rec, "tweet")
                tweet_id = str(tweet.get("id_str") or tweet.get("id") or "")
                ts_utc, ts_local = _parse_twitter_ts(tweet.get("created_at"))
                year, month = _year_month(ts_utc, ts_local)
                rows.append(
                    {
                        "tweet_id": tweet_id,
                        "full_text": tweet.get("full_text"),
                        "ts_utc": ts_utc,
                        "ts_local": ts_local,
                        "year": year,
                        "month": month,
                    }
                )
            except (TypeError, ValueError):
                skipped += 1
        return (pd.DataFrame(rows) if rows else _empty(cols), skipped)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        row = conn.execute("""
            SELECT
                (SELECT count(*)::BIGINT FROM twitter.tweets) AS n_tweets,
                (SELECT count(*)::BIGINT FROM twitter.likes) AS n_likes,
                (SELECT count(*)::BIGINT FROM twitter.dm_messages) AS n_dm_messages,
                (SELECT count(*)::BIGINT FROM twitter.followers) AS n_followers,
                (SELECT count(*)::BIGINT FROM twitter.following) AS n_following,
                (SELECT min(ts_utc)::DATE FROM twitter.tweets) AS first_day,
                (SELECT max(ts_utc)::DATE FROM twitter.tweets) AS last_day
            """).fetchone()
        assert row is not None
        skipped = getattr(self, "_skipped_rows", 0)
        inv = {
            "n_tweets": row[0],
            "n_likes": row[1],
            "n_dm_messages": row[2],
            "n_followers": row[3],
            "n_following": row[4],
            "first_day": row[5],
            "last_day": row[6],
            "skipped_rows": skipped,
        }
        inv["summary"] = (
            f"twitter.tweets: {inv['n_tweets']:,} | "
            f"likes {inv['n_likes']:,} | "
            f"DMs {inv['n_dm_messages']:,} | "
            f"followers {inv['n_followers']:,} / following {inv['n_following']:,} | "
            f"{inv['first_day']} → {inv['last_day']} | "
            f"PII/ad files skipped; {skipped} malformed rows skipped"
        )
        return inv
