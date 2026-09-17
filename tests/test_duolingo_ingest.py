"""Duolingo GDPR ingest smoke tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb

from data_dumps.duolingo_queries import data_bounds, filter_from_widgets, scoreboard
from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.base import Source
from data_dumps.sources.duolingo import DuolingoSource

FORBIDDEN_COLUMNS = {
    "email",
    "fullname",
    "full_name",
    "ip",
    "ip_address",
    "payment_processor",
    "code_id",
    "wager_day",
    "true_progress",
}


def make_mini_duolingo_zip(tmp_path: Path) -> Path:
    """Build a tiny Duolingo-shaped zip for detect/load tests."""
    root = tmp_path / "duo_src" / "duolingo"
    root.mkdir(parents=True)
    (root / "profile.csv").write_text(
        "name,value\n"
        "username,test_owl\n"
        "email,secret@example.com\n"
        "fullname,Secret Name\n"
        "joined_at,2015-06-01 12:00:00\n",
        encoding="utf-8",
    )
    (root / "languages.csv").write_text(
        "learning_language,from_language,points,skills_learned,total_lessons,"
        "days_active,last_active,prior_proficiency\n"
        "es,en,100,2,10,5,2024-01-15 10:00:00,\n"
        "fr,en,0,0,0,0,,\n",
        encoding="utf-8",
    )
    (root / "leaderboards.csv").write_text(
        "leaderboard,timestamp,tier,score\n"
        "leagues,2024-03-01T08:00:00Z,1,10\n"
        "leagues,2025-07-01T09:00:00Z,3,50\n",
        encoding="utf-8",
    )
    (root / "inventory.csv").write_text(
        "item_type,purchase_datetime,active,price_in_virtual_currency,wager_day,"
        "payment_processor,product,code_id,expected_expiration\n"
        "Streak freeze,2025-08-01 10:00:00,false,10,,Stripe,In-app Purchase,"
        "SECRETCODE,2025-08-02 10:00:00\n"
        "Store Item,2026-01-01 03:00:00,true,,,,In-app Purchase,,\n",
        encoding="utf-8",
    )
    (root / "friends-follow.csv").write_text(
        "num_following,num_followers,num_blocking,num_blockers,timestamp_generated\n"
        "2,5,0,0,1700000000\n",
        encoding="utf-8",
    )
    (root / "user-tree-backend.csv").write_text(
        "language,event_timestamp,true_progress\n"
        'es<-en,2025-06-01T12:00:00Z,"course_credit_record { lesson_credits { } }"\n'
        'fr<-en,2026-02-01T15:30:00Z,"course_credit_record { }"\n',
        encoding="utf-8",
    )
    # Forbidden files that must not be copied
    (root / "auth_data.csv").write_text("token,x\n", encoding="utf-8")
    (root / "ip-addresses.csv").write_text("ip\n1.2.3.4\n", encoding="utf-8")

    zip_path = tmp_path / "duolingo.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in root.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(root.parent).as_posix())
    return zip_path


def test_detect_zip(tmp_path):
    zip_path = make_mini_duolingo_zip(tmp_path)
    source = DuolingoSource()
    assert source.detect(zip_path)
    assert isinstance(source, Source)
    assert not source.detect(tmp_path / "missing.zip")
    unrelated = tmp_path / "other.zip"
    with zipfile.ZipFile(unrelated, "w") as zf:
        zf.writestr("readme.txt", "nope")
    assert not source.detect(unrelated)


def test_pick_source(tmp_path):
    zip_path = make_mini_duolingo_zip(tmp_path)
    source = pick_source(zip_path)
    assert source is not None
    assert source.name == "duolingo"


def test_load_and_queries(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = make_mini_duolingo_zip(tmp_path)
    db_path = tmp_path / "w.duckdb"
    conn = duckdb.connect(str(db_path))
    source = DuolingoSource()
    source.load(zip_path, conn)
    inv = source.inventory(conn)
    assert inv["n_progress"] == 2
    assert inv["n_languages"] == 2
    assert inv["n_leaderboards"] == 2
    assert inv["n_inventory"] == 2
    assert inv["max_tier"] == 3
    assert inv["username"] == "test_owl"
    assert "duolingo" in inv["summary"]

    acct = conn.execute("SELECT username FROM duolingo.account").fetchone()
    assert acct is not None and acct[0] == "test_owl"
    # email / fullname must not land in warehouse
    blob = " ".join(
        str(v)
        for row in conn.execute("SELECT * FROM duolingo.account").fetchall()
        for v in row
    )
    assert "secret@example.com" not in blob
    assert "Secret Name" not in blob

    for table in (
        "account",
        "languages",
        "leaderboards",
        "inventory",
        "friends",
        "progress_events",
    ):
        cols = {
            r[0].lower()
            for r in conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'duolingo' AND table_name = ?
                """,
                [table],
            ).fetchall()
        }
        assert not (cols & FORBIDDEN_COLUMNS), (table, cols & FORBIDDEN_COLUMNS)

    inv_blob = " ".join(
        str(v)
        for row in conn.execute("SELECT * FROM duolingo.inventory").fetchall()
        for v in row
    )
    assert "Stripe" not in inv_blob
    assert "SECRETCODE" not in inv_blob

    progress_blob = " ".join(
        str(v)
        for row in conn.execute("SELECT * FROM duolingo.progress_events").fetchall()
        for v in row
    )
    assert "course_credit_record" not in progress_blob
    pe = conn.execute(
        "SELECT learning_lang, from_lang, progress_bytes FROM duolingo.progress_events"
        " ORDER BY ts_utc"
    ).fetchall()
    assert pe[0][0] == "es" and pe[0][1] == "en"
    assert pe[0][2] > 0

    raw = raw_dir("duolingo")
    assert (raw / "languages.csv").exists()
    assert (raw / "profile.csv").exists()
    assert not (raw / "auth_data.csv").exists()
    assert not (raw / "ip-addresses.csv").exists()
    raw_profile = (raw / "profile.csv").read_text(encoding="utf-8")
    assert "secret@example.com" not in raw_profile
    assert "Secret Name" not in raw_profile
    assert "username" in raw_profile and "joined_at" in raw_profile
    raw_inv = (raw / "inventory.csv").read_text(encoding="utf-8")
    assert "Stripe" not in raw_inv
    assert "SECRETCODE" not in raw_inv
    assert "payment_processor" not in raw_inv.lower()

    bounds = data_bounds(conn)
    filters = filter_from_widgets(
        bounds, year_start=bounds["min_year"], year_end=bounds["max_year"]
    )
    score = scoreboard(conn, filters)
    assert int(score.iloc[0]["progress_events"]) == 2
    assert int(score.iloc[0]["languages_with_points"]) == 1
    assert int(score.iloc[0]["inventory_buys"]) == 2
    assert int(score.iloc[0]["league_max_tier"]) == 3
    conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = make_mini_duolingo_zip(tmp_path)
    assert main([str(zip_path), "--db", str(tmp_path / "catalog.duckdb")]) == 0
