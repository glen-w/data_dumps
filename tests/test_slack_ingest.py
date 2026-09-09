"""Slack export ingest and query smoke tests (synthetic mini workspace)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import duckdb

from data_dumps import slack_queries as skq
from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.base import Source
from data_dumps.sources.slack import SlackSource, clean_text

ALICE = "U0000ALICE"
BOB = "U0000BOB00"
GHOST = "U0000GHOST"
BOT = "U0000BOT00"

USERS = [
    {
        "id": ALICE,
        "name": "alice",
        "real_name": "Alice Example",
        "is_bot": False,
        "deleted": False,
        "tz": "Europe/Paris",
        "profile": {
            "real_name": "Alice Example",
            "display_name": "alice",
            "email": "alice@example.org",
            "phone": "+33 6 00 00 00 00",
            "title": "Analyst",
        },
    },
    {
        "id": BOB,
        "name": "bob",
        "real_name": "Bob Example",
        "is_bot": False,
        "deleted": False,
        "profile": {"real_name": "Bob Example", "email": "bob@example.org"},
    },
    {
        "id": GHOST,
        "name": "ghost",
        "real_name": "Gone Person",
        "is_bot": False,
        "deleted": True,
        "profile": {"email": "ghost@example.org"},
    },
    {
        "id": BOT,
        "name": "helperbot",
        "real_name": "Helper Bot",
        "is_bot": True,
        "deleted": False,
        "profile": {},
    },
]

CHANNELS = [
    {
        "id": "C000GENERAL",
        "name": "general",
        "created": 1526169600,
        "creator": ALICE,
        "is_archived": False,
        "is_general": True,
        "members": [ALICE, BOB, GHOST],
        "purpose": {"value": "Company-wide"},
        "topic": {"value": ""},
    },
    {
        "id": "C000OLDPROJ",
        "name": "old_project",
        "created": 1526169600,
        "creator": BOB,
        "is_archived": True,
        "is_general": False,
        "members": [ALICE, BOB],
        "purpose": {"value": ""},
        "topic": {"value": ""},
    },
]

# 2021-03-01 10:00 UTC
ROOT_TS = "1614592800.000100"
REPLY_TS = "1614593400.000200"  # +10 min
BOT_TS = "1614594000.000300"
JOIN_TS = "1614594600.000400"
MENTION_TS = "1614595200.000500"
OLD_TS = "1614681600.000600"  # 2021-03-02 in old_project
FC_TS = "1614768000.000700"

GENERAL_DAY = [
    {
        "type": "message",
        "user": ALICE,
        "ts": ROOT_TS,
        "text": "Kick-off for the report, see <https://example.org/doc|the doc>",
        "thread_ts": ROOT_TS,
        "reply_count": 1,
        "reply_users_count": 1,
        "latest_reply": REPLY_TS,
        "reply_users": [BOB],
        "reactions": [{"name": "thumbsup", "users": [BOB], "count": 1}],
        "files": [
            {
                "id": "F0001",
                "name": "plan.pdf",
                "filetype": "pdf",
                "size": 1234,
                "mode": "hosted",
            }
        ],
    },
    {
        "type": "message",
        "user": BOB,
        "ts": REPLY_TS,
        "text": "On it &amp; done",
        "thread_ts": ROOT_TS,
        "parent_user_id": ALICE,
        "edited": {"user": BOB, "ts": "1614593500.000000"},
    },
    {
        "type": "message",
        "subtype": "bot_message",
        "bot_id": "B0001",
        "username": "helperbot",
        "ts": BOT_TS,
        "text": "Daily digest",
    },
    {
        "type": "message",
        "subtype": "channel_join",
        "user": GHOST,
        "ts": JOIN_TS,
        "text": f"<@{GHOST}> has joined the channel",
    },
    {
        "type": "message",
        "user": ALICE,
        "ts": MENTION_TS,
        "text": f"<@{BOB}> can you check <#C000OLDPROJ|old_project>? <!here>",
    },
]

OLD_DAY = [
    {"type": "message", "user": BOB, "ts": OLD_TS, "text": "Archived chatter"},
]

FC_DAY = [
    {"type": "message", "user": ALICE, "ts": FC_TS, "text": "Comment on the canvas"},
]


def make_mini_slack_zip(path: Path) -> Path:
    zip_path = path / "Mini Slack export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", json.dumps(USERS))
        zf.writestr("channels.json", json.dumps(CHANNELS))
        zf.writestr("canvases.json", "[]")
        zf.writestr("general/2021-03-01.json", json.dumps(GENERAL_DAY))
        zf.writestr("old_project/2021-03-02.json", json.dumps(OLD_DAY))
        zf.writestr("FC:F0CANVAS1:Rana’s Notes/2021-03-03.json", json.dumps(FC_DAY))
    return zip_path


class _LegacyZipInfo(zipfile.ZipInfo):
    """Write UTF-8 bytes without the UTF-8 flag, like Windows-made Slack zips."""

    def _encodeFilenameFlags(self):  # type: ignore[override]
        return self.filename.encode("utf-8"), self.flag_bits


def make_legacy_slack_zip(path: Path) -> Path:
    zip_path = path / "Legacy Slack export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", json.dumps(USERS))
        zf.writestr("channels.json", json.dumps(CHANNELS))
        zf.writestr(
            _LegacyZipInfo("FC:F0CANVAS1:Rana’s Notes/2021-03-03.json"),
            json.dumps(FC_DAY),
        )
    return zip_path


def make_mini_slack_dir(path: Path) -> Path:
    root = path / "slack_extracted"
    (root / "general").mkdir(parents=True)
    (root / "users.json").write_text(json.dumps(USERS))
    (root / "channels.json").write_text(json.dumps(CHANNELS))
    (root / "general" / "2021-03-01.json").write_text(json.dumps(GENERAL_DAY))
    return root


def _load(tmp_path: Path, monkeypatch) -> duckdb.DuckDBPyConnection:
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = make_mini_slack_zip(tmp_path)
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    SlackSource().load(zip_path, conn)
    return conn


def test_detect_zip_and_dir(tmp_path):
    source = SlackSource()
    assert isinstance(source, Source)
    assert source.detect(make_mini_slack_zip(tmp_path))
    assert source.detect(make_mini_slack_dir(tmp_path))
    assert not source.detect(tmp_path)


def test_pick_source(tmp_path):
    source = pick_source(make_mini_slack_zip(tmp_path))
    assert source is not None
    assert source.name == "slack"


def test_cp437_zip_names_are_repaired(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = make_legacy_slack_zip(tmp_path)
    # Sanity: stdlib really does hand us mojibake for this entry.
    with zipfile.ZipFile(zip_path) as zf:
        raw_names = zf.namelist()
    assert any("Γ" in n or "â" in n for n in raw_names), raw_names

    assert SlackSource().detect(zip_path)
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    SlackSource().load(zip_path, conn)
    fc = conn.execute(
        "SELECT channel_id, name FROM slack.channels WHERE kind = 'file_conversation'"
    ).fetchone()
    assert fc == ("F0CANVAS1", "Rana’s Notes")
    conn.close()


def test_clean_text_resolves_markup():
    names = {BOB: "Bob Example"}
    text, mentioned = clean_text(
        f"<@{BOB}> see <https://x.y/z|link> and <https://plain.example> &lt;ok&gt;",
        names,
    )
    assert text == "@Bob Example see link and https://plain.example <ok>"
    assert mentioned == [BOB]


def test_load_tables_and_privacy(tmp_path, monkeypatch):
    conn = _load(tmp_path, monkeypatch)
    inv = SlackSource().inventory(conn)
    assert inv["n_events"] == 7
    assert inv["n_human_messages"] == 5  # root, reply, mention, old, fc
    assert inv["n_channels"] == 3
    assert inv["n_replies"] == 1
    assert inv["n_reactions"] == 1
    assert "slack.messages" in inv["summary"]
    assert (raw_dir("slack") / "users.json").exists()
    assert (raw_dir("slack") / "channels.json").exists()

    cols = {r[1] for r in conn.execute("PRAGMA table_info('slack.users')").fetchall()}
    assert "email" not in cols and "phone" not in cols
    assert cols >= {"user_id", "real_name", "is_bot", "deleted"}

    users = conn.execute(
        "SELECT user_id, is_bot, deleted FROM slack.users ORDER BY user_id"
    ).fetchall()
    assert (BOT, True, False) in users
    assert (GHOST, False, True) in users

    # FC dir became a file_conversation channel with title as name (utf-8 kept)
    fc = conn.execute(
        "SELECT channel_id, name, kind, n_messages FROM slack.channels "
        "WHERE kind = 'file_conversation'"
    ).fetchone()
    assert fc == ("F0CANVAS1", "Rana’s Notes", "file_conversation", 1)

    row = conn.execute(
        "SELECT text, n_mentions, is_bot FROM slack.messages WHERE ts = ?",
        [MENTION_TS],
    ).fetchone()
    assert row == ("@Bob Example can you check #old_project? @here", 1, False)

    root = conn.execute(
        "SELECT is_thread_root, is_reply, reply_count, n_reactions, n_files, "
        "has_link, latest_reply_utc IS NOT NULL FROM slack.messages WHERE ts = ?",
        [ROOT_TS],
    ).fetchone()
    assert root == (True, False, 1, 1, 1, True, True)
    reply = conn.execute(
        "SELECT is_thread_root, is_reply, parent_user_id, edited, text "
        "FROM slack.messages WHERE ts = ?",
        [REPLY_TS],
    ).fetchone()
    assert reply == (False, True, ALICE, True, "On it & done")
    bot = conn.execute(
        "SELECT is_bot, bot_name, subtype FROM slack.messages WHERE ts = ?", [BOT_TS]
    ).fetchone()
    assert bot == (True, "helperbot", "bot_message")

    assert conn.execute("SELECT count(*) FROM slack.channel_members").fetchone()[0] == 5
    assert conn.execute("SELECT emoji, user_id FROM slack.reactions").fetchall() == [
        ("thumbsup", BOB)
    ]
    assert conn.execute(
        "SELECT mentioned_user_id FROM slack.mentions ORDER BY ts"
    ).fetchall() == [(GHOST,), (BOB,)]
    assert conn.execute("SELECT name, size_bytes FROM slack.files").fetchall() == [
        ("plan.pdf", 1234)
    ]
    conn.close()


def test_queries_and_filters(tmp_path, monkeypatch):
    conn = _load(tmp_path, monkeypatch)
    bounds = skq.data_bounds(conn)
    assert bounds["min_year"] == 2021 and bounds["max_year"] == 2021
    assert [p["user_id"] for p in bounds["people"]] == [ALICE, BOB]  # by messages
    assert len(bounds["channels"]) == 3

    f = skq.filter_from_widgets(bounds, year_start=2021, year_end=2021)
    score = skq.scoreboard(conn, f)
    assert int(score.iloc[0]["messages"]) == 5  # bots + system excluded
    assert int(score.iloc[0]["people"]) == 2
    assert int(score.iloc[0]["replies"]) == 1

    f_all = skq.filter_from_widgets(
        bounds, year_start=2021, year_end=2021, include_bots=True, include_system=True
    )
    assert int(skq.scoreboard(conn, f_all).iloc[0]["messages"]) == 7

    f_active = skq.filter_from_widgets(
        bounds, year_start=2021, year_end=2021, include_archived=False
    )
    assert int(skq.scoreboard(conn, f_active).iloc[0]["messages"]) == 4

    lat = skq.reply_latency(conn, f)
    assert int(lat.iloc[0]["threads"]) == 1
    assert float(lat.iloc[0]["median_min"]) == 10.0

    kinds = skq.monthly_messages_by_kind(conn, f)
    assert set(kinds["kind"]) == {"human", "bot", "system"}

    f_bob = skq.filter_from_widgets(
        bounds, year_start=2021, year_end=2021, user_ids=[BOB]
    )
    assert int(skq.scoreboard(conn, f_bob).iloc[0]["messages"]) == 2
    assert skq.reaction_mix(conn, f).iloc[0]["emoji"] == "thumbsup"
    assert skq.top_mentioned(conn, f).iloc[0]["name"] == "Bob Example"
    # No channel is silent for a year inside a 3-day fixture
    assert skq.comeback_channels(conn, f).empty
    assert skq.forgotten_channels(conn, f, min_messages=1, silent_years=0).shape[0] >= 0
    conn.close()


def test_person_spotlight(tmp_path, monkeypatch):
    conn = _load(tmp_path, monkeypatch)
    bounds = skq.data_bounds(conn)
    f = skq.filter_from_widgets(bounds, year_start=2021, year_end=2021)

    ps = skq.person_scoreboard(conn, f, ALICE).iloc[0]
    assert ps["name"] == "Alice Example"
    assert int(ps["messages"]) == 3
    assert int(ps["root_posts"]) == 3 and int(ps["replies"]) == 0
    assert int(ps["threads_started"]) == 1
    assert int(ps["reactions_received"]) == 1
    assert int(ps["reactions_given"]) == 0
    assert int(ps["mentions_given"]) == 1
    assert int(ps["mentions_received"]) == 0
    assert float(ps["median_min_until_others_reply"]) == 10.0
    assert float(ps["share_of_team_pct"]) == 60.0
    assert int(ps["rank_by_messages"]) == 1

    # spotlight ignores f.user_ids for the team baseline
    f_bob = skq.filter_from_widgets(
        bounds, year_start=2021, year_end=2021, user_ids=[BOB]
    )
    share = skq.person_share_of_team(conn, f_bob, ALICE)
    assert int(share.iloc[0]["team_messages"]) == 5
    assert float(share.iloc[0]["share_pct"]) == 60.0

    collab = skq.person_collaborators(conn, f, ALICE)
    by_kind = dict(zip(collab["kind"], collab["n"], strict=True))
    assert set(collab["other_name"]) == {"Bob Example"}
    assert by_kind["I mentioned them"] == 1
    assert by_kind["they replied in my thread"] == 1
    assert by_kind["they reacted to me"] == 1

    mix = skq.person_channel_mix(conn, f, ALICE)
    assert set(mix["channel_name"]) == {"general", "Rana’s Notes"}
    heat = skq.person_circadian(conn, f, ALICE)
    assert set(heat["who"]) == {"person", "team"}
    prof = skq.person_text_profile(conn, f, ALICE)
    assert list(prof["who"]) == ["person", "team"]
    assert not skq.person_top_messages(conn, f, ALICE).empty
    assert int(skq.person_streaks(conn, f, ALICE).iloc[0]["active_days"]) == 2
    conn.close()


def test_empty_export_loads_and_bounds_fall_back(tmp_path, monkeypatch):
    """users/channels but no daily files: ingest, inventory, bounds, panel all OK."""
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", json.dumps(USERS))
        zf.writestr("channels.json", json.dumps(CHANNELS))
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    src = SlackSource()
    assert src.detect(zip_path)
    src.load(zip_path, conn)
    inv = src.inventory(conn)
    assert inv["n_events"] == 0 and "slack.messages" in inv["summary"]
    assert conn.execute("SELECT count(*) FROM slack.channels").fetchone()[0] == 2
    bounds = skq.data_bounds(conn)
    assert bounds["min_year"] <= bounds["max_year"]
    assert bounds["people"] == []
    f = skq.filter_from_widgets(
        bounds, year_start=bounds["min_year"], year_end=bounds["max_year"]
    )
    assert int(skq.scoreboard(conn, f).iloc[0]["messages"]) == 0
    assert skq.reply_latency(conn, f).iloc[0]["threads"] == 0
    assert skq.person_scoreboard(conn, f, ALICE).iloc[0]["messages"] == 0
    conn.close()


def test_duplicates_and_reactions_without_users(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    dup = dict(GENERAL_DAY[0])  # same (channel, ts) appearing in a second file
    anon_react = {
        "type": "message",
        "user": BOB,
        "ts": "1614600000.000900",
        "text": "no user list on this reaction",
        "reactions": [{"name": "eyes", "count": 2}],
    }
    zip_path = tmp_path / "dups.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", json.dumps(USERS))
        zf.writestr("channels.json", json.dumps(CHANNELS))
        zf.writestr("general/2021-03-01.json", json.dumps(GENERAL_DAY))
        zf.writestr("general/2021-03-02.json", json.dumps([dup, anon_react]))
        zf.writestr("general/not-a-day.json", json.dumps([anon_react]))  # ignored
        zf.writestr("general/2021-03-03.json", "not json at all")  # skipped
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    SlackSource().load(zip_path, conn)
    n = conn.execute(
        "SELECT count(*), count(DISTINCT ts) FROM slack.messages WHERE channel_id = 'C000GENERAL'"
    ).fetchone()
    assert n == (6, 6)  # 5 originals + anon_react; duplicate root dropped
    assert (
        conn.execute(
            "SELECT count(*) FROM slack.reactions WHERE user_id IS NULL AND emoji = 'eyes'"
        ).fetchone()[0]
        == 2
    )
    assert (
        conn.execute(
            "SELECT n_reactions FROM slack.messages WHERE ts = '1614600000.000900'"
        ).fetchone()[0]
        == 2
    )
    bounds = skq.data_bounds(conn)
    f = skq.filter_from_widgets(bounds, year_start=2021, year_end=2021)
    # NULL-user reactions are counted in the mix but never attributed to a reactor.
    assert (
        int(skq.reaction_mix(conn, f).set_index("emoji").loc["eyes", "reactions"]) == 2
    )
    assert "eyes" not in set(skq.top_reactors(conn, f)["favourite_emoji"])
    conn.close()


def test_filters_are_parameterized_not_interpolated(tmp_path, monkeypatch):
    conn = _load(tmp_path, monkeypatch)
    bounds = skq.data_bounds(conn)
    hostile = "' OR 1=1 --"
    f = skq.filter_from_widgets(
        bounds,
        year_start=2021,
        year_end=2021,
        channel_ids=[hostile],
        user_ids=[hostile, 'x"; DROP TABLE slack.messages; --'],
    )
    assert int(skq.scoreboard(conn, f).iloc[0]["messages"]) == 0
    assert skq.messages_by_channel(conn, f).empty
    assert skq.person_collaborators(conn, f, hostile).empty
    assert skq.person_scoreboard(conn, f, hostile).iloc[0]["messages"] == 0
    # table still there
    assert conn.execute("SELECT count(*) FROM slack.messages").fetchone()[0] == 7
    conn.close()


def test_filter_from_widgets_full_range_is_no_filter(tmp_path, monkeypatch):
    conn = _load(tmp_path, monkeypatch)
    bounds = skq.data_bounds(conn)
    f = skq.filter_from_widgets(
        bounds, year_start=bounds["min_year"], year_end=bounds["max_year"]
    )
    assert f.year_start is None and f.year_end is None
    assert f.chip_labels() == []
    f2 = skq.filter_from_widgets(
        bounds, year_start=2021, year_end=2021, user_ids=[ALICE], include_bots=True
    )
    labels = dict(f2.chip_labels())
    assert labels["people"] == "1 person(s)" and labels["include_bots"] == "incl. bots"
    conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("DATA_DUMPS_WAREHOUSE", str(tmp_path / "catalog.duckdb"))
    zip_path = make_mini_slack_zip(tmp_path)
    assert main([str(zip_path), "--db", str(tmp_path / "catalog.duckdb")]) == 0
