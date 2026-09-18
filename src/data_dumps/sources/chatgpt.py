"""ChatGPT / OpenAI GDPR export → DuckDB.

Keep-list: conversation shards, shared conversation metadata, asset name map,
library file metadata (extension/size/timestamps). Message text is kept
(product is chat). Media ``.dat`` bytes and ``chat.html`` stay out of raw/.

Dropped: email / phone from ``user.json``, ``ads.json``, payment/KYC blobs
(not present as first-class tables here).
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Paris")

CONV_SHARD_RE = re.compile(r"(?:.*/)?conversations-\d{3}\.json$")

KEEP_ROOT_FILES = {
    "shared_conversations.json",
    "conversation_asset_file_names.json",
    "library_files.json",
    "export_manifest.json",
}

FORBIDDEN_COLUMN_NAMES = {
    "email",
    "email_address",
    "phone",
    "phone_number",
    "ip",
    "ip_address",
    "login_ip",
}

CHATGPT_TABLES = [
    "chatgpt.account",
    "chatgpt.conversations",
    "chatgpt.messages",
    "chatgpt.shared",
    "chatgpt.assets",
]


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return bool(value)


def _ts_pair(unix: Any) -> tuple[datetime | None, datetime | None]:
    sec = _as_float(unix)
    if sec is None:
        return None, None
    ts_utc = datetime.fromtimestamp(sec, tz=UTC)
    ts_local = ts_utc.astimezone(LOCAL_TZ)
    return ts_utc.replace(tzinfo=None), ts_local.replace(tzinfo=None)


def _iso_pair(value: Any) -> tuple[datetime | None, datetime | None]:
    if not isinstance(value, str) or not value.strip():
        return None, None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    ts_utc = parsed.astimezone(UTC)
    ts_local = ts_utc.astimezone(LOCAL_TZ)
    return ts_utc.replace(tzinfo=None), ts_local.replace(tzinfo=None)


def flatten_parts(content: dict[str, Any] | None) -> tuple[str | None, int]:
    """Return plain text + image-pointer count for a message content blob."""
    if not isinstance(content, dict):
        return None, 0
    ct = content.get("content_type") or "none"
    image_n = 0
    chunks: list[str] = []

    if ct == "thoughts":
        for thought in content.get("thoughts") or []:
            if not isinstance(thought, dict):
                continue
            summary = thought.get("summary")
            body = thought.get("content")
            if isinstance(summary, str) and summary.strip():
                chunks.append(summary.strip())
            elif isinstance(body, str) and body.strip():
                chunks.append(body.strip())
            else:
                for part in thought.get("chunks") or []:
                    if isinstance(part, str) and part.strip():
                        chunks.append(part.strip())
    elif ct == "reasoning_recap":
        recap = content.get("content")
        if isinstance(recap, str) and recap.strip():
            chunks.append(recap.strip())
    else:
        for part in content.get("parts") or []:
            if isinstance(part, str):
                if part.strip():
                    chunks.append(part)
            elif isinstance(part, dict):
                pct = part.get("content_type") or part.get("type")
                if pct == "image_asset_pointer":
                    image_n += 1
                else:
                    txt = part.get("text") or part.get("content")
                    if isinstance(txt, str) and txt.strip():
                        chunks.append(txt)

    text = "\n".join(chunks) if chunks else None
    return text, image_n


def model_family(slug: str | None) -> str | None:
    if not slug:
        return None
    s = slug.lower()
    if s.startswith("text-davinci") or "davinci" in s:
        return "gpt-3.5"
    if s.startswith("o1") or s.startswith("o3") or s.startswith("o4"):
        return "reasoning-o"
    if "research" in s:
        return "research"
    if s.startswith("gpt-5") or s.startswith("gpt-5."):
        return "gpt-5"
    if s.startswith("gpt-4o"):
        return "gpt-4o"
    if s.startswith("gpt-4"):
        return "gpt-4"
    if s.startswith("gpt-3"):
        return "gpt-3"
    if s == "auto":
        return "auto"
    return "other"


def _looks_like_chatgpt_payload(names: list[str]) -> bool:
    has_conv = any(CONV_SHARD_RE.match(n.replace("\\", "/")) for n in names)
    if not has_conv:
        return False
    basenames = {Path(n).name for n in names}
    return (
        "user.json" in basenames
        or "export_manifest.json" in basenames
        or "chat.html" in basenames
    )


class ChatGPTSource:
    name = "chatgpt"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    return _looks_like_chatgpt_payload(zf.namelist())
            except (OSError, zipfile.BadZipFile):
                return False
        export = self._export_dir(path)
        if export is None:
            return False
        names = [p.name for p in export.iterdir() if p.is_file()]
        return _looks_like_chatgpt_payload(names)

    def _export_dir(self, path: Path) -> Path | None:
        if not path.is_dir():
            return None
        if any(path.glob("conversations-*.json")):
            return path
        nested = [
            p
            for p in path.iterdir()
            if p.is_dir() and any(p.glob("conversations-*.json"))
        ]
        if len(nested) == 1:
            return nested[0]
        return None

    def tables(self) -> list[str]:
        return list(CHATGPT_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        export_root = self._materialize(path)
        account_row = self._account_row(export_root)
        conv_rows, msg_rows = self._conversation_frames(export_root)
        shared_rows = self._shared_rows(export_root)
        asset_rows = self._asset_rows(export_root)

        account_df = pd.DataFrame([account_row])
        conversations_df = (
            pd.DataFrame(conv_rows)
            if conv_rows
            else pd.DataFrame(
                columns=[
                    "conversation_id",
                    "title",
                    "create_ts_utc",
                    "create_ts_local",
                    "update_ts_utc",
                    "update_ts_local",
                    "default_model_slug",
                    "default_model_family",
                    "gizmo_id",
                    "is_archived",
                    "is_starred",
                    "is_study_mode",
                    "is_do_not_remember",
                    "memory_scope",
                    "n_messages",
                    "n_user",
                    "n_assistant",
                    "n_thoughts",
                    "n_images",
                    "user_chars",
                    "assistant_chars",
                    "year",
                    "month",
                    "is_shared",
                ]
            )
        )
        messages_df = (
            pd.DataFrame(msg_rows)
            if msg_rows
            else pd.DataFrame(
                columns=[
                    "conversation_id",
                    "message_id",
                    "parent_id",
                    "role",
                    "content_type",
                    "text",
                    "char_count",
                    "image_count",
                    "model_slug",
                    "model_family",
                    "ts_utc",
                    "ts_local",
                    "year",
                    "month",
                    "weekday",
                    "hour",
                ]
            )
        )
        shared_df = (
            pd.DataFrame(shared_rows)
            if shared_rows
            else pd.DataFrame(
                columns=["share_id", "conversation_id", "title", "is_anonymous"]
            )
        )
        assets_df = (
            pd.DataFrame(asset_rows)
            if asset_rows
            else pd.DataFrame(
                columns=[
                    "asset_id",
                    "source",
                    "file_name",
                    "file_extension",
                    "file_size_bytes",
                    "provenance",
                    "ts_utc",
                    "ts_local",
                    "year",
                    "month",
                ]
            )
        )

        shared_ids = set(shared_df["conversation_id"].dropna().astype(str))
        if not conversations_df.empty and "conversation_id" in conversations_df.columns:
            conversations_df["is_shared"] = (
                conversations_df["conversation_id"].astype(str).isin(shared_ids)
            )

        conn.execute("CREATE SCHEMA IF NOT EXISTS chatgpt")
        for table in ("assets", "shared", "messages", "conversations", "account"):
            conn.execute(f"DROP TABLE IF EXISTS chatgpt.{table}")

        conn.register("_chatgpt_account", account_df)
        conn.execute("CREATE TABLE chatgpt.account AS SELECT * FROM _chatgpt_account")
        conn.unregister("_chatgpt_account")

        conn.register("_chatgpt_conversations", conversations_df)
        conn.execute(
            "CREATE TABLE chatgpt.conversations AS SELECT * FROM _chatgpt_conversations"
        )
        conn.unregister("_chatgpt_conversations")

        conn.register("_chatgpt_messages", messages_df)
        conn.execute("CREATE TABLE chatgpt.messages AS SELECT * FROM _chatgpt_messages")
        conn.unregister("_chatgpt_messages")

        conn.register("_chatgpt_shared", shared_df)
        conn.execute("CREATE TABLE chatgpt.shared AS SELECT * FROM _chatgpt_shared")
        conn.unregister("_chatgpt_shared")

        conn.register("_chatgpt_assets", assets_df)
        conn.execute("CREATE TABLE chatgpt.assets AS SELECT * FROM _chatgpt_assets")
        conn.unregister("_chatgpt_assets")

    def _materialize(self, path: Path) -> Path:
        path = path.resolve()
        dest = raw_dir(self.name)
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        if path.is_file() and path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename.replace("\\", "/")
                    base = Path(name).name
                    keep = (
                        CONV_SHARD_RE.match(name) is not None or base in KEEP_ROOT_FILES
                    )
                    if not keep:
                        continue
                    target = dest / base
                    with zf.open(info) as src, target.open("wb") as out:
                        shutil.copyfileobj(src, out)
                if "user.json" in {Path(n).name for n in zf.namelist()}:
                    user_blob = json.loads(
                        zf.read(
                            next(
                                n for n in zf.namelist() if Path(n).name == "user.json"
                            )
                        )
                    )
                    self._write_account_stub(dest, user_blob)
            (dest / "source_path.txt").write_text(str(path), encoding="utf-8")
            return dest

        export = self._export_dir(path)
        if export is None:
            raise ValueError(f"not a ChatGPT export: {path}")
        for shard in sorted(export.glob("conversations-*.json")):
            shutil.copy2(shard, dest / shard.name)
        for name in KEEP_ROOT_FILES:
            keep_path = export / name
            if keep_path.is_file():
                shutil.copy2(keep_path, dest / name)
        user_path = export / "user.json"
        if user_path.is_file():
            with user_path.open(encoding="utf-8") as fh:
                self._write_account_stub(dest, json.load(fh))
        (dest / "source_path.txt").write_text(str(path), encoding="utf-8")
        return dest

    def _write_account_stub(self, dest: Path, user_blob: object) -> None:
        payload: dict[str, Any] = {}
        if isinstance(user_blob, dict):
            payload = {
                "id": user_blob.get("id"),
                "chatgpt_plus_user": bool(user_blob.get("chatgpt_plus_user")),
                "birth_year": user_blob.get("birth_year"),
            }
        (dest / "account.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    def _account_row(self, export_root: Path) -> dict[str, Any]:
        stub = export_root / "account.json"
        payload: dict[str, Any] = {}
        if stub.is_file():
            with stub.open(encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                payload = raw
        return {
            "user_id": payload.get("id"),
            "chatgpt_plus_user": bool(payload.get("chatgpt_plus_user")),
            "birth_year": payload.get("birth_year"),
        }

    def _conversation_frames(
        self, export_root: Path
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        conv_rows: list[dict[str, Any]] = []
        msg_rows: list[dict[str, Any]] = []
        for shard in sorted(export_root.glob("conversations-*.json")):
            with shard.open(encoding="utf-8") as fh:
                payload = json.load(fh)
            if not isinstance(payload, list):
                continue
            for conv in payload:
                if not isinstance(conv, dict):
                    continue
                cid = conv.get("conversation_id") or conv.get("id")
                if not cid:
                    continue
                cid_s = str(cid)
                create_utc, create_local = _ts_pair(conv.get("create_time"))
                update_utc, update_local = _ts_pair(conv.get("update_time"))
                default_model = conv.get("default_model_slug")
                gizmo = conv.get("gizmo_id") or conv.get("conversation_template_id")
                n_messages = 0
                n_user = 0
                n_assistant = 0
                n_thoughts = 0
                n_images = 0
                user_chars = 0
                assistant_chars = 0

                mapping = conv.get("mapping") or {}
                if isinstance(mapping, dict):
                    for node in mapping.values():
                        if not isinstance(node, dict):
                            continue
                        msg = node.get("message")
                        if not isinstance(msg, dict):
                            continue
                        msg_id = msg.get("id") or node.get("id")
                        if not msg_id:
                            continue
                        author_raw = msg.get("author")
                        author: dict[str, Any] = (
                            author_raw if isinstance(author_raw, dict) else {}
                        )
                        role = author.get("role") or "unknown"
                        content_raw = msg.get("content")
                        content: dict[str, Any] = (
                            content_raw if isinstance(content_raw, dict) else {}
                        )
                        content_type = content.get("content_type") or "none"
                        text, image_n = flatten_parts(content)
                        char_count = len(text) if text else 0
                        meta_raw = msg.get("metadata")
                        meta: dict[str, Any] = (
                            meta_raw if isinstance(meta_raw, dict) else {}
                        )
                        model_slug = meta.get("model_slug") or (
                            default_model if role == "assistant" else None
                        )
                        ts_utc, ts_local = _ts_pair(msg.get("create_time"))
                        parent = node.get("parent")
                        parent_id = str(parent) if parent else None

                        n_messages += 1
                        n_images += image_n
                        if role == "user":
                            n_user += 1
                            user_chars += char_count
                        elif role == "assistant":
                            n_assistant += 1
                            assistant_chars += char_count
                        if content_type == "thoughts":
                            n_thoughts += 1

                        msg_rows.append(
                            {
                                "conversation_id": cid_s,
                                "message_id": str(msg_id),
                                "parent_id": parent_id,
                                "role": role,
                                "content_type": content_type,
                                "text": text,
                                "char_count": char_count,
                                "image_count": image_n,
                                "model_slug": model_slug,
                                "model_family": model_family(
                                    model_slug if isinstance(model_slug, str) else None
                                ),
                                "ts_utc": ts_utc,
                                "ts_local": ts_local,
                                "year": ts_local.year if ts_local else None,
                                "month": ts_local.month if ts_local else None,
                                "weekday": (
                                    ts_local.isoweekday() if ts_local else None
                                ),
                                "hour": ts_local.hour if ts_local else None,
                            }
                        )

                conv_rows.append(
                    {
                        "conversation_id": cid_s,
                        "title": conv.get("title"),
                        "create_ts_utc": create_utc,
                        "create_ts_local": create_local,
                        "update_ts_utc": update_utc,
                        "update_ts_local": update_local,
                        "default_model_slug": default_model,
                        "default_model_family": model_family(
                            default_model if isinstance(default_model, str) else None
                        ),
                        "gizmo_id": str(gizmo) if gizmo else None,
                        "is_archived": bool(conv.get("is_archived")),
                        "is_starred": _as_bool(conv.get("is_starred")),
                        "is_study_mode": bool(conv.get("is_study_mode")),
                        "is_do_not_remember": bool(conv.get("is_do_not_remember")),
                        "memory_scope": conv.get("memory_scope"),
                        "n_messages": n_messages,
                        "n_user": n_user,
                        "n_assistant": n_assistant,
                        "n_thoughts": n_thoughts,
                        "n_images": n_images,
                        "user_chars": user_chars,
                        "assistant_chars": assistant_chars,
                        "year": create_local.year if create_local else None,
                        "month": create_local.month if create_local else None,
                        "is_shared": False,
                    }
                )
        return conv_rows, msg_rows

    def _shared_rows(self, export_root: Path) -> list[dict[str, Any]]:
        path = export_root / "shared_conversations.json"
        if not path.is_file():
            return []
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "share_id": str(item.get("id")) if item.get("id") else None,
                    "conversation_id": (
                        str(item.get("conversation_id"))
                        if item.get("conversation_id")
                        else None
                    ),
                    "title": item.get("title"),
                    "is_anonymous": bool(item.get("is_anonymous")),
                }
            )
        return rows

    def _asset_rows(self, export_root: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        names_path = export_root / "conversation_asset_file_names.json"
        if names_path.is_file():
            with names_path.open(encoding="utf-8") as fh:
                payload = json.load(fh)
            if isinstance(payload, dict):
                for dat_name, file_name in payload.items():
                    ext = None
                    if isinstance(file_name, str) and "." in file_name:
                        ext = file_name.rsplit(".", 1)[-1].lower()
                    rows.append(
                        {
                            "asset_id": str(dat_name),
                            "source": "conversation_asset",
                            "file_name": (
                                str(file_name) if file_name is not None else None
                            ),
                            "file_extension": ext,
                            "file_size_bytes": None,
                            "provenance": "conversation",
                            "ts_utc": None,
                            "ts_local": None,
                            "year": None,
                            "month": None,
                        }
                    )

        lib_path = export_root / "library_files.json"
        if lib_path.is_file():
            with lib_path.open(encoding="utf-8") as fh:
                payload = json.load(fh)
            if isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    file_id = item.get("file_id")
                    if not file_id:
                        fid = item.get("id")
                        if isinstance(fid, dict):
                            file_id = fid.get("id")
                    ts_utc, ts_local = _iso_pair(
                        item.get("created_at") or item.get("file_upload_time")
                    )
                    rows.append(
                        {
                            "asset_id": str(file_id) if file_id else None,
                            "source": "library",
                            "file_name": item.get("file_name"),
                            "file_extension": (
                                str(item.get("file_extension")).lower()
                                if item.get("file_extension")
                                else None
                            ),
                            "file_size_bytes": item.get("file_size_bytes"),
                            "provenance": item.get("file_name_provenance"),
                            "ts_utc": ts_utc,
                            "ts_local": ts_local,
                            "year": ts_local.year if ts_local else None,
                            "month": ts_local.month if ts_local else None,
                        }
                    )
        return rows

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        row = conn.execute("""
            SELECT
                (SELECT count(*)::BIGINT FROM chatgpt.conversations),
                (SELECT count(*)::BIGINT FROM chatgpt.messages),
                (SELECT count(*)::BIGINT FROM chatgpt.shared),
                (SELECT count(*)::BIGINT FROM chatgpt.assets),
                (SELECT min(create_ts_local)::DATE FROM chatgpt.conversations),
                (SELECT max(update_ts_local)::DATE FROM chatgpt.conversations)
            """).fetchone()
        assert row is not None
        n_conv, n_msg, n_shared, n_assets, first_day, last_day = row
        plus = conn.execute(
            "SELECT chatgpt_plus_user FROM chatgpt.account LIMIT 1"
        ).fetchone()
        plus_s = "Plus" if plus and plus[0] else "free"
        summary = (
            f"chatgpt: {n_conv} conversations, {n_msg} messages, "
            f"{n_shared} shared, {n_assets} assets ({plus_s}); "
            f"{first_day} → {last_day}"
        )
        return {
            "conversations": n_conv,
            "messages": n_msg,
            "shared": n_shared,
            "assets": n_assets,
            "first_day": first_day,
            "last_day": last_day,
            "summary": summary,
        }
