"""Twitter YTD archive ingest smoke tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb

from data_dumps.ingest import pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.base import Source
from data_dumps.sources.twitter import TwitterSource, _parse_ytd_json

FORBIDDEN_COLUMNS = {
    "email",
    "email_address",
    "ip",
    "ip_address",
    "phone",
    "phone_number",
}

ACCOUNT_JS = """window.YTD.account.part0 = [
  {"account": {"email": "secret@example.com", "username": "testuser", "accountId": "1", "createdAt": "2011-05-20T04:48:36.000Z", "accountDisplayName": "Test User"}}
]"""

TWEETS_JS = """window.YTD.tweets.part0 = [
  {"tweet": {"id_str": "100", "created_at": "Sun Apr 02 08:04:52 +0000 2023", "full_text": "hello world", "lang": "en", "source": "<a href=\\"https://twitter.com\\">Twitter Web App</a>", "favorite_count": 1, "retweet_count": 0, "favorited": false, "retweeted": false, "entities": {"hashtags": [{"text": "hello"}], "user_mentions": [{"screen_name": "friend", "id_str": "9"}]}}},
  {"tweet": {"id_str": "101", "created_at": "Mon Apr 03 09:00:00 +0000 2023", "full_text": "@friend thanks", "lang": "en", "source": "<a href=\\"https://twitter.com\\">Twitter Web App</a>", "in_reply_to_status_id_str": "99", "in_reply_to_screen_name": "friend", "favorite_count": 0, "retweet_count": 0, "favorited": false, "retweeted": false, "entities": {"hashtags": [], "user_mentions": [{"screen_name": "friend", "id_str": "9"}]}}},
  {"tweet": {"id_str": "102", "created_at": "bad-date", "full_text": "skip me"}}
]"""

TWEETS_PART1_JS = """window.YTD.tweets.part1 = [
  {"tweet": {"id_str": "103", "created_at": "Tue Apr 04 10:00:00 +0000 2023", "full_text": "RT @someone shared", "lang": "en", "source": "<a href=\\"https://twitter.com\\">TweetDeck</a>", "favorite_count": 0, "retweet_count": 0, "favorited": false, "retweeted": false, "entities": {"hashtags": [], "user_mentions": []}}}
]"""

LIKE_JS = """window.YTD.like.part0 = [
  {"like": {"tweetId": "500", "fullText": "liked tweet", "expandedUrl": "https://twitter.com/i/web/status/500"}}
]"""

FOLLOWER_JS = """window.YTD.follower.part0 = [
  {"follower": {"accountId": "42", "userLink": "https://twitter.com/intent/user?user_id=42"}}
]"""

FOLLOWING_JS = """window.YTD.following.part0 = [
  {"following": {"accountId": "7", "userLink": "https://twitter.com/intent/user?user_id=7"}}
]"""

DM_JS = """window.YTD.direct_messages.part0 = [
  {"dmConversation": {"conversationId": "c1", "messages": [
    {"messageCreate": {"id": "m1", "senderId": "1", "recipientId": "2", "text": "hi", "createdAt": "2023-04-02T08:05:00.000Z"}}
  ]}}
]"""

IP_AUDIT_JS = """window.YTD.ip_audit.part0 = [
  {"ipAudit": {"accountId": "1", "createdAt": "2023-01-01T00:00:00.000Z", "loginIp": "203.0.113.1"}}
]"""


def make_mini_twitter_dir(path: Path) -> Path:
    root = path / "mini_twitter"
    data = root / "data"
    data.mkdir(parents=True)
    (root / "Your archive.html").write_text("<html></html>", encoding="utf-8")
    (data / "account.js").write_text(ACCOUNT_JS, encoding="utf-8")
    (data / "tweets.js").write_text(TWEETS_JS, encoding="utf-8")
    (data / "tweets.part1.js").write_text(TWEETS_PART1_JS, encoding="utf-8")
    (data / "like.js").write_text(LIKE_JS, encoding="utf-8")
    (data / "follower.js").write_text(FOLLOWER_JS, encoding="utf-8")
    (data / "following.js").write_text(FOLLOWING_JS, encoding="utf-8")
    (data / "direct-messages.js").write_text(DM_JS, encoding="utf-8")
    (data / "ip-audit.js").write_text(IP_AUDIT_JS, encoding="utf-8")
    return root


def make_mini_twitter_zip(path: Path) -> Path:
    root = make_mini_twitter_dir(path / "zip_fixture")
    zip_path = path / "mini_twitter.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for file in root.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(root.parent))
    return zip_path


def _all_columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'twitter'
        """).fetchall()
    return {r[0].lower() for r in rows}


def test_parse_ytd_json():
    payload = _parse_ytd_json(ACCOUNT_JS)
    assert isinstance(payload, list)
    assert payload[0]["account"]["username"] == "testuser"


def test_detect_dir_and_zip(tmp_path):
    root = make_mini_twitter_dir(tmp_path)
    source = TwitterSource()
    assert source.detect(root)
    assert isinstance(source, Source)
    assert pick_source(root) is not None
    zip_path = make_mini_twitter_zip(tmp_path)
    assert source.detect(zip_path)


def test_detect_rejects_unrelated(tmp_path):
    (tmp_path / "notes.txt").write_text("nope")
    assert not TwitterSource().detect(tmp_path)


def test_detect_rejects_non_ytd_shape(tmp_path):
    root = tmp_path / "bad"
    data = root / "data"
    data.mkdir(parents=True)
    (root / "Your archive.html").write_text("<html></html>", encoding="utf-8")
    (data / "tweets.js").write_text('{"not": "ytd"}', encoding="utf-8")
    assert not TwitterSource().detect(root)


def test_load_skips_pii_and_bad_rows(tmp_path):
    root = make_mini_twitter_dir(tmp_path)
    db_path = tmp_path / "ingest.duckdb"
    conn = duckdb.connect(str(db_path))
    source = TwitterSource()
    source.load(root, conn)
    inv = source.inventory(conn)

    assert inv["n_tweets"] == 3
    assert inv["n_likes"] == 1
    assert inv["n_dm_messages"] == 1
    assert inv["n_followers"] == 1
    assert inv["n_following"] == 1
    assert inv["skipped_rows"] >= 1

    cols = _all_columns(conn)
    assert not (cols & FORBIDDEN_COLUMNS)

    raw_data = raw_dir("twitter") / "data"
    assert not (raw_data / "ip-audit.js").exists()
    assert (raw_data / "tweets.js").exists()

    types = conn.execute(
        "SELECT tweet_type, count(*) FROM twitter.tweets GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert ("original", 1) in types
    assert ("reply", 1) in types
    assert ("retweet", 1) in types

    hashtags = conn.execute("SELECT count(*) FROM twitter.tweet_hashtags").fetchone()
    assert hashtags is not None and hashtags[0] == 1

    account = conn.execute(
        "SELECT username, display_name FROM twitter.account"
    ).fetchone()
    assert account == ("testuser", "Test User")

    deleted_count = conn.execute(
        "SELECT count(*) FROM twitter.deleted_tweets"
    ).fetchone()
    assert deleted_count is not None and deleted_count[0] == 0

    conn.close()


def test_missing_optional_files_ok(tmp_path):
    root = tmp_path / "bare"
    data = root / "data"
    data.mkdir(parents=True)
    (root / "Your archive.html").write_text("<html></html>", encoding="utf-8")
    (data / "account.js").write_text(ACCOUNT_JS, encoding="utf-8")
    (data / "tweets.js").write_text(
        """window.YTD.tweets.part0 = [
  {"tweet": {"id_str": "1", "created_at": "Sun Apr 02 08:04:52 +0000 2023", "full_text": "solo", "lang": "en", "source": "<a>Twitter Web App</a>", "favorite_count": 0, "retweet_count": 0, "favorited": false, "retweeted": false, "entities": {"hashtags": [], "user_mentions": []}}}
]""",
        encoding="utf-8",
    )
    conn = duckdb.connect(str(tmp_path / "bare.duckdb"))
    TwitterSource().load(root, conn)
    assert conn.execute("SELECT count(*) FROM twitter.likes").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM twitter.dm_messages").fetchone()[0] == 0
    conn.close()
