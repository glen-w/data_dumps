"""Telegram ingest smoke tests on a mini Desktop export."""

import json
import shutil
import zipfile
from pathlib import Path

import duckdb

from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.base import Source
from data_dumps.sources.telegram import (
    TelegramSource,
    flatten_text,
    media_kind_of,
    media_relpath_of,
    parse_duration_sec,
)

FIXTURE_JSON = Path(__file__).parent / "fixtures" / "telegram_result_mini.json"
IP_COLUMNS = {"last_ip", "ip_addr", "ip"}


def make_mini_telegram_dir(path: Path) -> Path:
    export = path / "Telegram_Export_mini"
    export.mkdir()
    shutil.copy2(FIXTURE_JSON, export / "result.json")
    (export / "chats").mkdir()
    return export


def make_mini_telegram_zip(path: Path) -> Path:
    export = make_mini_telegram_dir(path)
    zip_path = path / "mini_telegram.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(export / "result.json", "Telegram_Export_mini/result.json")
    return zip_path


def _session_columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in conn.execute("DESCRIBE telegram.sessions").fetchall()}


def test_parse_duration():
    assert parse_duration_sec("0:11") == 11
    assert parse_duration_sec("1:02") == 62
    assert parse_duration_sec("1:02:03") == 3723
    assert parse_duration_sec(None) is None


def test_flatten_text_handles_entity_lists():
    assert flatten_text(None) is None
    assert flatten_text("plain") == "plain"
    assert flatten_text("") == ""
    mixed = [
        "see ",
        {"type": "link", "text": "https://example.org"},
        " and ",
        {"type": "bold", "text": "this"},
        {"type": "custom_emoji", "document_id": "1"},  # no text key -> skipped
    ]
    assert flatten_text(mixed) == "see https://example.org and this"
    assert flatten_text(42) == "42"


def test_media_kind_photo_beats_file():
    assert media_kind_of({"photo": "chats/x/photos/p.jpg"}) == "photo"
    assert (
        media_kind_of({"media_type": "voice_message", "file": "a.ogg"})
        == "voice_message"
    )
    assert media_kind_of({"file": "chats/x/files/a.pdf"}) == "file"
    assert media_kind_of({"text": "hi"}) == "none"
    assert media_kind_of({"webpage": {"url": "https://x"}}) == "webpage"


def test_media_relpath_skips_placeholder():
    assert media_relpath_of({"file": "(File not included. Change settings)"}) is None
    assert media_relpath_of({"photo": "chats/0000_Ada/photos/p.jpg"}) == (
        "chats/0000_Ada/photos/p.jpg"
    )


def test_detect_export_dir(tmp_path):
    export = make_mini_telegram_dir(tmp_path)
    source = TelegramSource()
    assert source.detect(export)
    assert isinstance(source, Source)


def test_detect_parent_of_single_export(tmp_path):
    export = make_mini_telegram_dir(tmp_path)
    assert TelegramSource().detect(export.parent)


def test_detect_zip(tmp_path):
    zip_path = make_mini_telegram_zip(tmp_path)
    assert TelegramSource().detect(zip_path)


def test_detect_rejects_unrelated(tmp_path):
    (tmp_path / "notes.txt").write_text("not a dump")
    assert not TelegramSource().detect(tmp_path)


def test_detect_rejects_result_json_without_chats(tmp_path):
    export = tmp_path / "not_telegram"
    export.mkdir()
    (export / "result.json").write_text('{"about": "no chats here"}')
    assert not TelegramSource().detect(export)


def test_detect_rejects_invalid_json(tmp_path):
    export = tmp_path / "broken"
    export.mkdir()
    (export / "result.json").write_text("{not json")
    assert not TelegramSource().detect(export)


def test_detect_rejects_two_nested_exports(tmp_path):
    make_mini_telegram_dir(tmp_path)
    second = tmp_path / "Telegram_Export_other"
    second.mkdir()
    shutil.copy2(FIXTURE_JSON, second / "result.json")
    assert not TelegramSource().detect(tmp_path)


def test_pick_source_telegram(tmp_path):
    export = make_mini_telegram_dir(tmp_path)
    source = pick_source(export)
    assert source is not None
    assert source.name == "telegram"


def test_load_mini_export(tmp_path):
    export = make_mini_telegram_dir(tmp_path)
    db_path = tmp_path / "ingest.duckdb"
    conn = duckdb.connect(str(db_path))
    source = TelegramSource()
    source.load(export, conn)
    inv = source.inventory(conn)
    assert inv["n_events"] == 4
    assert inv["n_messages"] == 3
    assert inv["n_chats"] == 2
    assert inv["n_photos"] == 1
    assert inv["n_replies"] == 1
    assert "summary" in inv

    n_chats = conn.execute("SELECT count(*) FROM telegram.chats").fetchone()
    assert n_chats is not None and n_chats[0] == 2

    pk = conn.execute("""
        SELECT chat_id, message_id, count(*)
        FROM telegram.messages
        GROUP BY 1, 2
        HAVING count(*) > 1
        """).fetchall()
    assert pk == []

    kinds = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT media_kind FROM telegram.messages"
        ).fetchall()
    }
    assert "photo" in kinds
    assert "video_file" in kinds
    assert "none" in kinds

    rel = conn.execute("""
        SELECT media_relpath FROM telegram.messages
        WHERE media_kind = 'photo'
        """).fetchone()
    assert rel is not None
    assert rel[0] == "chats/0000_Ada/photos/photo_1_0.jpg"

    blob_cols = {
        row[0]
        for row in conn.execute("DESCRIBE telegram.messages").fetchall()
        if "blob" in row[1].lower() or "binary" in row[1].lower()
    }
    assert not blob_cols

    duration = conn.execute("""
        SELECT duration_sec FROM telegram.messages WHERE file_name = 'paper.pdf'
        """).fetchone()
    assert duration is not None and duration[0] == 11

    n_react = conn.execute("SELECT count(*) FROM telegram.reactions").fetchone()
    assert n_react is not None and n_react[0] == 1

    leaked = _session_columns(conn) & IP_COLUMNS
    assert not leaked, f"IP columns survived ingest: {leaked}"

    raw_json = raw_dir("telegram") / "result.json"
    assert raw_json.is_file()
    copied = json.loads(raw_json.read_text())
    assert "chats" in copied
    raw_names = {p.name for p in raw_dir("telegram").iterdir()}
    assert raw_names == {"result.json", "export_root.txt"}

    fwd = conn.execute("""
        SELECT forwarded_from, edited, webpage_url
        FROM telegram.messages
        WHERE message_id = 2 AND chat_id = 222
        """).fetchone()
    assert fwd is not None
    assert fwd[0] == "Someone"
    assert fwd[1] is True
    assert fwd[2] == "https://example.com"

    kinds = set(source.tables())
    present = {f"{r[0]}.{r[1]}" for r in conn.execute("""
            SELECT table_schema, table_name FROM information_schema.tables
            WHERE table_schema = 'telegram'
            """).fetchall()}
    assert kinds == present
    conn.close()


def test_cli_ingest_mini(tmp_path):
    export = make_mini_telegram_dir(tmp_path)
    db_path = tmp_path / "catalog.duckdb"
    rc = main([str(export), "--db", str(db_path)])
    assert rc == 0
    conn = duckdb.connect(str(db_path), read_only=True)
    n = conn.execute("SELECT count(*) FROM telegram.messages").fetchone()
    assert n is not None and n[0] == 4
    conn.close()


def test_cli_ingest_zip(tmp_path):
    zip_path = make_mini_telegram_zip(tmp_path)
    db_path = tmp_path / "from_zip.duckdb"
    rc = main([str(zip_path), "--db", str(db_path)])
    assert rc == 0
    conn = duckdb.connect(str(db_path), read_only=True)
    n = conn.execute("SELECT count(*) FROM telegram.chats").fetchone()
    assert n is not None and n[0] == 2
    conn.close()
