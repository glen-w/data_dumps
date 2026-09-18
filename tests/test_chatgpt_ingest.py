"""ChatGPT export ingest smoke tests (synthetic fixture only)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import duckdb

from data_dumps.ingest import pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.base import Source
from data_dumps.sources.chatgpt import FORBIDDEN_COLUMN_NAMES, ChatGPTSource

FORBIDDEN_COLUMNS = FORBIDDEN_COLUMN_NAMES


def _mini_conversation(
    *,
    cid: str,
    title: str,
    create: float,
    model: str,
    user_text: str,
    asst_text: str,
    gizmo: str | None = None,
) -> dict:
    user_id = f"{cid}-user"
    asst_id = f"{cid}-asst"
    root_id = f"{cid}-root"
    return {
        "conversation_id": cid,
        "id": cid,
        "title": title,
        "create_time": create,
        "update_time": create + 120,
        "default_model_slug": model,
        "gizmo_id": gizmo,
        "is_archived": False,
        "is_starred": None,
        "is_study_mode": False,
        "is_do_not_remember": False,
        "memory_scope": None,
        "mapping": {
            root_id: {"id": root_id, "message": None, "parent": None},
            user_id: {
                "id": user_id,
                "parent": root_id,
                "message": {
                    "id": user_id,
                    "author": {"role": "user", "name": None},
                    "create_time": create + 10,
                    "content": {"content_type": "text", "parts": [user_text]},
                    "metadata": {},
                },
            },
            asst_id: {
                "id": asst_id,
                "parent": user_id,
                "message": {
                    "id": asst_id,
                    "author": {"role": "assistant", "name": None},
                    "create_time": create + 40,
                    "content": {"content_type": "text", "parts": [asst_text]},
                    "metadata": {"model_slug": model},
                },
            },
        },
    }


def make_mini_chatgpt_dir(path: Path) -> Path:
    root = path / "mini_chatgpt"
    root.mkdir(parents=True)
    convs = [
        _mini_conversation(
            cid="c-1",
            title="Basketball glossary",
            create=1717580311.0,
            model="gpt-4o",
            user_text="explain box and one",
            asst_text="A box-and-one is a defensive mix.",
        ),
        _mini_conversation(
            cid="c-2",
            title="Python refactor",
            create=1735689600.0,  # 2025-01-01
            model="gpt-5-2",
            user_text="refactor this",
            asst_text="Sure — extract a helper.",
            gizmo="g-project-1",
        ),
        _mini_conversation(
            cid="c-3",
            title="Old thread return",
            create=1640995200.0,  # 2022-01-01
            model="text-davinci-002-render-sha",
            user_text="hi again after a long time",
            asst_text="welcome back",
        ),
    ]
    # Add a comeback gap on c-3: second user/asst pair months later
    late_user = "c-3-user2"
    late_asst = "c-3-asst2"
    convs[2]["mapping"][late_user] = {
        "id": late_user,
        "parent": "c-3-asst",
        "message": {
            "id": late_user,
            "author": {"role": "user", "name": None},
            "create_time": 1717580311.0,
            "content": {"content_type": "text", "parts": ["remember this?"]},
            "metadata": {},
        },
    }
    convs[2]["mapping"][late_asst] = {
        "id": late_asst,
        "parent": late_user,
        "message": {
            "id": late_asst,
            "author": {"role": "assistant", "name": None},
            "create_time": 1717580400.0,
            "content": {"content_type": "text", "parts": ["yes"]},
            "metadata": {"model_slug": "gpt-4o"},
        },
    }
    convs[2]["update_time"] = 1717580400.0

    (root / "conversations-000.json").write_text(json.dumps(convs), encoding="utf-8")
    (root / "shared_conversations.json").write_text(
        json.dumps(
            [
                {
                    "id": "share-1",
                    "conversation_id": "c-1",
                    "title": "Basketball glossary",
                    "is_anonymous": False,
                }
            ]
        ),
        encoding="utf-8",
    )
    (root / "conversation_asset_file_names.json").write_text(
        json.dumps({"file-abc.dat": "diagram.png"}), encoding="utf-8"
    )
    (root / "library_files.json").write_text(
        json.dumps(
            [
                {
                    "file_id": "file_lib1",
                    "file_name": "notes.py",
                    "file_extension": "py",
                    "file_size_bytes": 120,
                    "file_name_provenance": "upload",
                    "created_at": "2025-06-01T12:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    (root / "export_manifest.json").write_text(
        json.dumps({"version": 1, "export_files": []}), encoding="utf-8"
    )
    (root / "user.json").write_text(
        json.dumps(
            {
                "id": "user-test",
                "email": "secret@example.com",
                "phone_number": "+33123456789",
                "chatgpt_plus_user": True,
                "birth_year": 1988,
            }
        ),
        encoding="utf-8",
    )
    (root / "ads.json").write_text("{}", encoding="utf-8")
    (root / "chat.html").write_text("<html></html>", encoding="utf-8")
    (root / "file-abc.dat").write_bytes(b"\x89PNG")
    return root


def make_mini_chatgpt_zip(path: Path) -> Path:
    root = make_mini_chatgpt_dir(path / "zip_fixture")
    zip_path = path / "mini_chatgpt.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for file in root.rglob("*"):
            if file.is_file():
                zf.write(file, file.name)
    return zip_path


def _all_columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'chatgpt'
        """).fetchall()
    return {r[0].lower() for r in rows}


def test_detect_dir_and_zip(tmp_path):
    root = make_mini_chatgpt_dir(tmp_path)
    source = ChatGPTSource()
    assert source.detect(root)
    assert isinstance(source, Source)
    assert pick_source(root) is not None
    assert pick_source(root).name == "chatgpt"
    zip_path = make_mini_chatgpt_zip(tmp_path)
    assert source.detect(zip_path)


def test_detect_rejects_unrelated(tmp_path):
    (tmp_path / "notes.txt").write_text("nope")
    assert not ChatGPTSource().detect(tmp_path)
    assert not ChatGPTSource().detect(tmp_path / "missing")


def test_load_counts_and_privacy(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    z = make_mini_chatgpt_zip(tmp_path)
    conn = duckdb.connect(str(tmp_path / "t.duckdb"))
    ChatGPTSource().load(z, conn)

    n_conv = conn.execute("SELECT count(*) FROM chatgpt.conversations").fetchone()[0]
    n_msg = conn.execute("SELECT count(*) FROM chatgpt.messages").fetchone()[0]
    n_shared = conn.execute("SELECT count(*) FROM chatgpt.shared").fetchone()[0]
    n_assets = conn.execute("SELECT count(*) FROM chatgpt.assets").fetchone()[0]
    assert n_conv == 3
    assert n_msg >= 8  # 2+2+4
    assert n_shared == 1
    assert n_assets == 2

    cols = _all_columns(conn)
    assert not (cols & {c.lower() for c in FORBIDDEN_COLUMNS})

    # Email/phone must not appear in any cell value either.
    for table in ("account", "conversations", "messages", "shared", "assets"):
        rows = conn.execute(f"SELECT * FROM chatgpt.{table}").fetchdf()
        blob = rows.to_csv(index=False).lower()
        assert "secret@example.com" not in blob
        assert "+33123456789" not in blob

    plus = conn.execute("SELECT chatgpt_plus_user FROM chatgpt.account").fetchone()[0]
    assert plus is True

    # Keep-list only under raw/chatgpt — no .dat / chat.html / user.json with email
    raw = raw_dir("chatgpt")
    names = {p.name for p in raw.iterdir()}
    assert "conversations-000.json" in names
    assert "account.json" in names
    assert "file-abc.dat" not in names
    assert "chat.html" not in names
    assert "user.json" not in names
    account = json.loads((raw / "account.json").read_text(encoding="utf-8"))
    assert "email" not in account
    assert "phone_number" not in account

    inv = ChatGPTSource().inventory(conn)
    assert "conversations" in inv["summary"]
    conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    from data_dumps.ingest import main

    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    z = make_mini_chatgpt_zip(tmp_path)
    db = tmp_path / "cli.duckdb"
    assert main([str(z), "--db", str(db)]) == 0
