"""Cursor History export → DuckDB.

Prefer a portable ``cursor-history`` / ``direct_export.py`` Desktop folder
(``EXPORT_MANIFEST.md`` + ``json/`` + ``agent-transcripts/``). Message text is
kept (product is chat). Never copy live ``state.vscdb``. Skip redundant
Markdown and Composer backup zips at materialize time.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Paris")

SLUG = "cursor_history"

FORBIDDEN_COLUMN_NAMES = {
    "email",
    "email_address",
    "phone",
    "phone_number",
    "ip",
    "ip_address",
    "login_ip",
}

CURSOR_HISTORY_TABLES = [
    "cursor_history.sessions",
    "cursor_history.messages",
    "cursor_history.tool_calls",
    "cursor_history.models",
]

KEEP_ROOT_FILES = {
    "EXPORT_MANIFEST.md",
    "composer-headers-inventory.json",
    "direct-export-summary.json",
    "session-ids.txt",
    "exported-ids.txt",
}

# Truncate warehouse tool args/results (full bodies stay in raw JSON).
_TOOL_TEXT_MAX = 4_000
_BATCH = 2_000

_SOURCE_KIND_RANK = {
    "merged": 3,
    "composer": 2,
    "agent_transcript": 1,
    "store": 0,
}

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_TIMESTAMP_TAG_RE = re.compile(
    r"<timestamp>\s*([^<]+?)\s*</timestamp>", re.I | re.DOTALL
)

# Warehouse-only redaction (raw export files stay untouched).
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED_GITHUB_PAT]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED_GITHUB_PAT]"),
    (re.compile(r"gho_[A-Za-z0-9]{20,}"), "[REDACTED_GITHUB_OAUTH]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(
            r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?"
            r"(?!\[REDACTED)[^\s'\"]{12,}"
        ),
        r"\1=[REDACTED]",
    ),
)


def redact_secrets(text: str | None) -> str | None:
    """Mask common credential shapes in warehouse text. Raw files unchanged."""
    if not text:
        return text
    out = text
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"1", "true", "yes"}:
            return True
        if s in {"0", "false", "no"}:
            return False
    return bool(value)


def _truncate(text: str | None, limit: int = _TOOL_TEXT_MAX) -> str | None:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _token_estimate(text: str | None) -> int | None:
    if not text:
        return None
    return max(1, len(text) // 4)


def _ms_pair(ms: Any) -> tuple[datetime | None, datetime | None]:
    if ms is None or ms == "":
        return None, None
    try:
        value = float(ms)
    except (TypeError, ValueError):
        return None, None
    # Composer headers use unix ms; guard against accidental seconds.
    if value > 1e12:
        value = value / 1000.0
    if value < 1e9:
        return None, None
    ts_utc = datetime.fromtimestamp(value, tz=UTC)
    ts_local = ts_utc.astimezone(LOCAL_TZ)
    return ts_utc.replace(tzinfo=None), ts_local.replace(tzinfo=None)


def _iso_pair(value: Any) -> tuple[datetime | None, datetime | None]:
    if value is None or value == "":
        return None, None
    if isinstance(value, (int, float)):
        return _ms_pair(value)
    if not isinstance(value, str):
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


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _session_id_from_json_name(name: str) -> str | None:
    stem = Path(name).stem
    m = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        stem,
        re.I,
    )
    if m:
        return m.group(1).lower()
    return None


def _looks_like_export(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "EXPORT_MANIFEST.md").is_file():
        return True
    if (path / "composer-headers-inventory.json").is_file():
        return True
    if (path / "json").is_dir() and any((path / "json").glob("*.json")):
        return True
    if (path / "agent-transcripts").is_dir() and any(
        (path / "agent-transcripts").rglob("*.jsonl")
    ):
        return True
    return False


def _link_or_copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def _extract_text_parts(content: Any) -> tuple[str | None, bool, list[dict[str, Any]]]:
    """Return (text, has_thinking, tool_use blobs) from agent transcript content."""
    tools: list[dict[str, Any]] = []
    chunks: list[str] = []
    has_thinking = False
    if isinstance(content, str):
        return (content if content.strip() else None), False, tools
    if not isinstance(content, list):
        return None, False, tools
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            txt = part.get("text")
            if isinstance(txt, str) and txt.strip():
                chunks.append(txt)
        elif ptype in {"thinking", "reasoning"}:
            has_thinking = True
            txt = part.get("thinking") or part.get("text") or part.get("content")
            if isinstance(txt, str) and txt.strip():
                chunks.append(txt)
        elif ptype == "tool_use":
            tools.append(part)
        elif ptype == "tool_result":
            # Fold short results into text for search; full blob stays in raw.
            txt = part.get("content")
            if isinstance(txt, str) and txt.strip():
                chunks.append(_truncate(txt, 500) or "")
            elif isinstance(txt, list):
                for sub in txt:
                    if isinstance(sub, dict) and isinstance(sub.get("text"), str):
                        chunks.append(sub["text"])
    text = "\n".join(c for c in chunks if c).strip() or None
    return text, has_thinking, tools


def _tool_rows_from_message(
    *,
    session_id: str,
    message_id: str,
    ordinal_base: int,
    tool_blob: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    items: list[Any]
    if tool_blob is None:
        return rows
    if isinstance(tool_blob, dict):
        # Composer export: single tool call object (not a list).
        if "name" in tool_blob or "toolCallId" in tool_blob or "tool" in tool_blob:
            items = [tool_blob]
        else:
            items = list(tool_blob.values())
    elif isinstance(tool_blob, list):
        items = tool_blob
    else:
        return rows

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        tool_name = item.get("name") or item.get("toolName")
        if tool_name is None and item.get("tool") is not None:
            tool_name = str(item.get("tool"))
        tool_call_id = (
            item.get("toolCallId")
            or item.get("tool_call_id")
            or item.get("id")
            or f"{message_id}:tool:{ordinal_base + i}"
        )
        args_raw = (
            item.get("rawArgs")
            or item.get("params")
            or item.get("arguments")
            or item.get("input")
        )
        if isinstance(args_raw, (dict, list)):
            args_json = _truncate(
                redact_secrets(json.dumps(args_raw, ensure_ascii=False))
            )
        elif isinstance(args_raw, str):
            args_json = _truncate(redact_secrets(args_raw))
        else:
            args_json = None
        result = item.get("result") or item.get("additionalData")
        if isinstance(result, (dict, list)):
            result_summary = _truncate(
                redact_secrets(json.dumps(result, ensure_ascii=False)), 1_500
            )
        elif isinstance(result, str):
            result_summary = _truncate(redact_secrets(result), 1_500)
        else:
            result_summary = None
        if isinstance(tool_name, str):
            tool_name = tool_name.strip() or None
        rows.append(
            {
                "session_id": session_id,
                "tool_call_id": str(tool_call_id),
                "message_id": message_id,
                "ordinal": ordinal_base + i,
                "tool_name": str(tool_name) if tool_name is not None else None,
                "status": item.get("status"),
                "args_json": args_json,
                "result_summary": result_summary,
                "duration_ms": None,
            }
        )
    return rows


def _empty_sessions_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "session_id",
            "source_kind",
            "title",
            "workspace_id",
            "workspace_path",
            "project_slug",
            "created_at_utc",
            "created_at_local",
            "updated_at_utc",
            "updated_at_local",
            "year",
            "month",
            "is_subagent",
            "subagent_type",
            "is_archived",
            "unified_mode",
            "message_count",
            "tool_call_count",
            "model_primary",
            "export_path",
            "content_sha256",
        ]
    )


def _empty_messages_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "session_id",
            "message_id",
            "ordinal",
            "id_provenance",
            "role",
            "created_at_utc",
            "created_at_local",
            "year",
            "month",
            "weekday",
            "hour",
            "model",
            "text",
            "char_count",
            "token_estimate",
            "has_diff",
            "has_thinking",
        ]
    )


def _empty_tools_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "session_id",
            "tool_call_id",
            "message_id",
            "ordinal",
            "tool_name",
            "status",
            "args_json",
            "result_summary",
            "duration_ms",
        ]
    )


class CursorHistorySource:
    name = SLUG

    def __init__(self) -> None:
        self._parse_stats: dict[str, int] = {}

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            # Composer backup zip — accept name hint only; v1 loads folder exports.
            name = path.name.lower()
            return "cursor" in name and "backup" in name
        return (
            _looks_like_export(path)
            or _looks_like_export(path / "cursor_history")
            or _looks_like_export(path / "cursor-history-export")
        )

    def tables(self) -> list[str]:
        return list(CURSOR_HISTORY_TABLES)

    def _export_dir(self, path: Path) -> Path | None:
        path = path.resolve()
        if _looks_like_export(path):
            return path
        for child in (path / "cursor_history", path / "cursor-history-export"):
            if _looks_like_export(child):
                return child
        return None

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        self._parse_stats = {
            "composer_files": 0,
            "composer_corrupt": 0,
            "transcript_files": 0,
            "transcript_corrupt": 0,
            "transcript_merged_skip_messages": 0,
        }
        export_root = self._materialize(path)
        headers = self._load_headers(export_root)
        sessions, messages, tools = self._parse_all(export_root, headers)

        sessions_df = pd.DataFrame(sessions) if sessions else _empty_sessions_df()
        messages_df = pd.DataFrame(messages) if messages else _empty_messages_df()
        tools_df = pd.DataFrame(tools) if tools else _empty_tools_df()
        models_df = self._models_frame(messages_df)

        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SLUG}")
        for table in ("models", "tool_calls", "messages", "sessions"):
            conn.execute(f"DROP TABLE IF EXISTS {SLUG}.{table}")

        conn.register("_ch_sessions", sessions_df)
        conn.execute(f"CREATE TABLE {SLUG}.sessions AS SELECT * FROM _ch_sessions")
        conn.unregister("_ch_sessions")

        conn.register("_ch_messages", messages_df)
        conn.execute(f"CREATE TABLE {SLUG}.messages AS SELECT * FROM _ch_messages")
        conn.unregister("_ch_messages")

        conn.register("_ch_tools", tools_df)
        conn.execute(f"CREATE TABLE {SLUG}.tool_calls AS SELECT * FROM _ch_tools")
        conn.unregister("_ch_tools")

        conn.register("_ch_models", models_df)
        conn.execute(f"CREATE TABLE {SLUG}.models AS SELECT * FROM _ch_models")
        conn.unregister("_ch_models")

    def _materialize(self, path: Path) -> Path:
        path = path.resolve()
        dest = raw_dir(self.name)
        export = self._export_dir(path)
        if export is None:
            raise ValueError(f"not a Cursor History export: {path}")

        # Already the owned raw copy — load in place.
        if export == dest or dest in export.parents or export in dest.parents:
            if _looks_like_export(dest):
                return dest
            return export

        # Re-ingest from the same Desktop path: keep hardlinks, skip wipe/copy.
        marker = dest / "source_path.txt"
        if (
            dest.exists()
            and _looks_like_export(dest)
            and marker.is_file()
            and marker.read_text(encoding="utf-8").strip() == str(export)
        ):
            return dest

        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        for name in KEEP_ROOT_FILES:
            src = export / name
            if src.is_file():
                _link_or_copy_file(src, dest / name)

        json_src = export / "json"
        if json_src.is_dir():
            for f in json_src.glob("*.json"):
                _link_or_copy_file(f, dest / "json" / f.name)

        transcripts = export / "agent-transcripts"
        if transcripts.is_dir():
            for f in transcripts.rglob("*.jsonl"):
                rel = f.relative_to(transcripts)
                _link_or_copy_file(f, dest / "agent-transcripts" / rel)

        (dest / "source_path.txt").write_text(str(export), encoding="utf-8")
        (dest / "manifest.json").write_text(
            json.dumps(
                {
                    "source_path": str(export),
                    "materialized_at": datetime.now(tz=UTC).isoformat(),
                    "kept": sorted(KEEP_ROOT_FILES) + ["json/", "agent-transcripts/"],
                    "skipped": ["markdown/", "backup/", "*.log", "*.pid"],
                    "timezone": str(LOCAL_TZ),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return dest

    def _load_headers(self, export_root: Path) -> dict[str, dict[str, Any]]:
        path = export_root / "composer-headers-inventory.json"
        if not path.is_file():
            return {}
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        sessions = payload.get("sessions") if isinstance(payload, dict) else payload
        out: dict[str, dict[str, Any]] = {}
        if not isinstance(sessions, list):
            return out
        for row in sessions:
            if not isinstance(row, dict):
                continue
            cid = row.get("composerId") or row.get("composer_id") or row.get("id")
            if cid:
                out[str(cid).lower()] = row
        return out

    def _parse_all(
        self, export_root: Path, headers: dict[str, dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        by_id: dict[str, dict[str, Any]] = {}
        messages: list[dict[str, Any]] = []
        tools: list[dict[str, Any]] = []

        json_dir = export_root / "json"
        if json_dir.is_dir():
            for path in sorted(json_dir.glob("*.json")):
                self._ingest_composer_json(
                    path, headers, by_id, messages, tools, export_root
                )

        transcripts = export_root / "agent-transcripts"
        if transcripts.is_dir():
            for path in sorted(transcripts.rglob("*.jsonl")):
                self._ingest_transcript(
                    path, headers, by_id, messages, tools, export_root, transcripts
                )

        return list(by_id.values()), messages, tools

    def _prefer_session(
        self, existing: dict[str, Any] | None, candidate: dict[str, Any]
    ) -> dict[str, Any]:
        if existing is None:
            return candidate
        er = _SOURCE_KIND_RANK.get(str(existing.get("source_kind")), -1)
        cr = _SOURCE_KIND_RANK.get(str(candidate.get("source_kind")), -1)
        if cr > er:
            # Keep richer metadata from loser when winner is blank.
            merged = dict(candidate)
            for key in (
                "workspace_id",
                "workspace_path",
                "project_slug",
                "is_subagent",
                "subagent_type",
                "is_archived",
                "title",
            ):
                if merged.get(key) in (None, "") and existing.get(key) not in (
                    None,
                    "",
                ):
                    merged[key] = existing[key]
            if er >= 0 and cr >= 0 and er != cr:
                merged["source_kind"] = "merged"
            return merged
        if cr == er:
            # Same kind — keep newer updated_at.
            eu = existing.get("updated_at_utc")
            cu = candidate.get("updated_at_utc")
            if cu is not None and (eu is None or cu >= eu):
                return candidate
        return existing

    def _ingest_composer_json(
        self,
        path: Path,
        headers: dict[str, dict[str, Any]],
        by_id: dict[str, dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        export_root: Path,
    ) -> None:
        raw_bytes = path.read_bytes()
        try:
            payload = json.loads(raw_bytes)
        except json.JSONDecodeError:
            self._parse_stats["composer_corrupt"] = (
                self._parse_stats.get("composer_corrupt", 0) + 1
            )
            return
        if not isinstance(payload, dict):
            self._parse_stats["composer_corrupt"] = (
                self._parse_stats.get("composer_corrupt", 0) + 1
            )
            return
        self._parse_stats["composer_files"] = (
            self._parse_stats.get("composer_files", 0) + 1
        )
        sid = str(payload.get("id") or "").lower()
        if not sid:
            sid = (_session_id_from_json_name(path.name) or path.stem).lower()
        header = headers.get(sid) or {}
        meta = payload.get("composerMeta") or {}
        if not isinstance(meta, dict):
            meta = {}

        created_utc, created_local = _iso_pair(
            payload.get("createdAt") or meta.get("createdAt") or header.get("createdAt")
        )
        updated_utc, updated_local = _iso_pair(
            payload.get("lastUpdatedAt")
            or header.get("lastUpdatedAt")
            or header.get("recency")
            or payload.get("createdAt")
        )
        title = (
            payload.get("title")
            or meta.get("name")
            or header.get("parsed_name")
            or sid[:8]
        )
        is_subagent = _as_bool(header.get("isSubagent"))
        if is_subagent is None:
            is_subagent = False
        subagent_type = header.get("subagentTypeName") or header.get("subagentType")
        is_archived = _as_bool(header.get("isArchived"))
        if is_archived is None:
            is_archived = False

        msg_list = payload.get("messages") or []
        if not isinstance(msg_list, list):
            msg_list = []

        n_tools = 0
        model_counts: dict[str, int] = {}
        for ordinal, msg in enumerate(msg_list):
            if not isinstance(msg, dict):
                continue
            mid = str(msg.get("id") or f"{sid}:{ordinal}")
            provenance = "export" if msg.get("id") else "synthetic"
            role = msg.get("role") or "unknown"
            text = msg.get("content")
            if text is not None and not isinstance(text, str):
                text = str(text)
            text = redact_secrets(text)
            ts_utc, ts_local = _iso_pair(msg.get("createdAt"))
            model = msg.get("model") or msg.get("modelSlug")
            if isinstance(model, str) and model.strip():
                model_counts[model] = model_counts.get(model, 0) + 1
            has_thinking = bool(msg.get("thinking") or msg.get("hasThinking"))
            raw_keys = msg.get("raw_keys") or []
            if isinstance(raw_keys, list) and "allThinkingBlocks" in raw_keys:
                has_thinking = True
            has_diff = False
            if isinstance(raw_keys, list):
                has_diff = any(
                    k in raw_keys
                    for k in (
                        "diffsSinceLastApply",
                        "assistantSuggestedDiffs",
                        "codeBlocks",
                    )
                )
            char_count = len(text) if text else 0
            messages.append(
                {
                    "session_id": sid,
                    "message_id": mid,
                    "ordinal": ordinal,
                    "id_provenance": provenance,
                    "role": role,
                    "created_at_utc": ts_utc,
                    "created_at_local": ts_local,
                    "year": int(ts_local.year) if ts_local else None,
                    "month": int(ts_local.month) if ts_local else None,
                    "weekday": int(ts_local.isoweekday()) if ts_local else None,
                    "hour": int(ts_local.hour) if ts_local else None,
                    "model": model,
                    "text": text,
                    "char_count": char_count,
                    "token_estimate": _token_estimate(text),
                    "has_diff": has_diff,
                    "has_thinking": has_thinking,
                }
            )
            for row in _tool_rows_from_message(
                session_id=sid,
                message_id=mid,
                ordinal_base=n_tools,
                tool_blob=msg.get("toolCalls"),
            ):
                tools.append(row)
                n_tools += 1

        # Top-level toolCalls (usually empty in this export shape).
        for row in _tool_rows_from_message(
            session_id=sid,
            message_id=f"{sid}:toplevel",
            ordinal_base=n_tools,
            tool_blob=payload.get("toolCalls"),
        ):
            tools.append(row)
            n_tools += 1

        model_primary = None
        if model_counts:
            model_primary = max(model_counts.items(), key=lambda kv: kv[1])[0]
        elif isinstance(meta.get("unifiedMode"), str):
            model_primary = None

        rel = str(path.relative_to(export_root))
        anchor = created_local or updated_local
        session_row = {
            "session_id": sid,
            "source_kind": "composer",
            "title": title,
            "workspace_id": header.get("workspaceId"),
            "workspace_path": None,
            "project_slug": None,
            "created_at_utc": created_utc,
            "created_at_local": created_local,
            "updated_at_utc": updated_utc,
            "updated_at_local": updated_local,
            "year": anchor.year if anchor is not None else None,
            "month": anchor.month if anchor is not None else None,
            "is_subagent": is_subagent,
            "subagent_type": subagent_type,
            "is_archived": is_archived,
            "unified_mode": meta.get("unifiedMode") or meta.get("forceMode"),
            "message_count": len(msg_list),
            "tool_call_count": n_tools,
            "model_primary": model_primary,
            "export_path": rel,
            "content_sha256": _sha256_bytes(raw_bytes),
        }
        by_id[sid] = self._prefer_session(by_id.get(sid), session_row)

    def _ingest_transcript(
        self,
        path: Path,
        headers: dict[str, dict[str, Any]],
        by_id: dict[str, dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        export_root: Path,
        transcripts_root: Path,
    ) -> None:
        rel = path.relative_to(transcripts_root)
        parts = rel.parts
        project_slug = parts[0] if parts else None
        # …/<project>/<uuid>/<uuid>.jsonl or …/<project>/<uuid>.jsonl
        sid_candidate = path.stem
        if len(parts) >= 2 and _UUID_RE.match(parts[-2]):
            sid_candidate = parts[-2]
        sid = sid_candidate.lower()
        if not _UUID_RE.match(sid):
            sid = path.stem.lower()

        header = headers.get(sid) or {}
        existing = by_id.get(sid)
        # Composer already owns this UUID — still attach project_slug if blank.
        # Prefer composer message bodies; skip transcript lines for the same id.
        if existing is not None and existing.get("source_kind") in {
            "composer",
            "merged",
        }:
            if not existing.get("project_slug") and project_slug:
                existing["project_slug"] = project_slug
                existing["source_kind"] = "merged"
            self._parse_stats["transcript_merged_skip_messages"] = (
                self._parse_stats.get("transcript_merged_skip_messages", 0) + 1
            )
            return

        self._parse_stats["transcript_files"] = (
            self._parse_stats.get("transcript_files", 0) + 1
        )
        raw_bytes = path.read_bytes()
        lines = raw_bytes.splitlines()
        n_tools = 0
        msg_rows_local = 0
        first_ts_utc = None
        first_ts_local = None
        last_ts_utc = None
        last_ts_local = None
        title = header.get("parsed_name") or (project_slug or sid[:8])
        corrupt_lines = 0

        for ordinal, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                corrupt_lines += 1
                continue
            if not isinstance(row, dict):
                corrupt_lines += 1
                continue
            role = row.get("role") or "unknown"
            message = (
                row.get("message") if isinstance(row.get("message"), dict) else row
            )
            content = message.get("content") if isinstance(message, dict) else None
            text, has_thinking, tool_parts = _extract_text_parts(content)
            text = redact_secrets(text)
            mid_raw = message.get("id") if isinstance(message, dict) else None
            mid = str(mid_raw) if mid_raw else f"{sid}:{ordinal}"
            provenance = "export" if mid_raw else "synthetic"
            ts_utc, ts_local = _iso_pair(
                (message or {}).get("createdAt") if isinstance(message, dict) else None
            )
            if ts_local is None and text:
                m = _TIMESTAMP_TAG_RE.search(text)
                if m:
                    # Best-effort; leave tz-naive wall clock as local.
                    try:
                        parsed = datetime.strptime(
                            m.group(1).strip().split("(")[0].strip(),
                            "%A, %b %d, %Y, %I:%M %p",
                        )
                        ts_local = parsed
                        ts_utc = None
                    except ValueError:
                        pass
            if ts_local is not None:
                if first_ts_local is None:
                    first_ts_local = ts_local
                    first_ts_utc = ts_utc
                last_ts_local = ts_local
                last_ts_utc = ts_utc

            messages.append(
                {
                    "session_id": sid,
                    "message_id": mid,
                    "ordinal": ordinal,
                    "id_provenance": provenance,
                    "role": role,
                    "created_at_utc": ts_utc,
                    "created_at_local": ts_local,
                    "year": int(ts_local.year) if ts_local else None,
                    "month": int(ts_local.month) if ts_local else None,
                    "weekday": int(ts_local.isoweekday()) if ts_local else None,
                    "hour": int(ts_local.hour) if ts_local else None,
                    "model": None,
                    "text": text,
                    "char_count": len(text) if text else 0,
                    "token_estimate": _token_estimate(text),
                    "has_diff": False,
                    "has_thinking": has_thinking,
                }
            )
            msg_rows_local += 1
            for tpart in tool_parts:
                tool_rows = _tool_rows_from_message(
                    session_id=sid,
                    message_id=mid,
                    ordinal_base=n_tools,
                    tool_blob={
                        "name": tpart.get("name"),
                        "toolCallId": tpart.get("id"),
                        "input": tpart.get("input"),
                        "status": "completed",
                    },
                )
                for tr in tool_rows:
                    tools.append(tr)
                    n_tools += 1

        if corrupt_lines:
            self._parse_stats["transcript_corrupt"] = (
                self._parse_stats.get("transcript_corrupt", 0) + corrupt_lines
            )

        created_utc, created_local = _ms_pair(header.get("createdAt"))
        if created_local is None:
            created_utc, created_local = first_ts_utc, first_ts_local
        updated_utc, updated_local = _ms_pair(
            header.get("lastUpdatedAt") or header.get("recency")
        )
        if updated_local is None:
            updated_utc, updated_local = last_ts_utc, last_ts_local

        anchor = created_local or updated_local
        session_row = {
            "session_id": sid,
            "source_kind": "agent_transcript",
            "title": title,
            "workspace_id": header.get("workspaceId"),
            "workspace_path": None,
            "project_slug": project_slug,
            "created_at_utc": created_utc,
            "created_at_local": created_local,
            "updated_at_utc": updated_utc,
            "updated_at_local": updated_local,
            "year": anchor.year if anchor is not None else None,
            "month": anchor.month if anchor is not None else None,
            "is_subagent": bool(_as_bool(header.get("isSubagent")) or False),
            "subagent_type": header.get("subagentTypeName"),
            "is_archived": bool(_as_bool(header.get("isArchived")) or False),
            "unified_mode": None,
            "message_count": msg_rows_local,
            "tool_call_count": n_tools,
            "model_primary": None,
            "export_path": str(path.relative_to(export_root)),
            "content_sha256": _sha256_bytes(raw_bytes),
        }
        by_id[sid] = self._prefer_session(by_id.get(sid), session_row)

    def _models_frame(self, messages_df: pd.DataFrame) -> pd.DataFrame:
        cols = ["model", "message_count", "first_seen_local", "last_seen_local"]
        if messages_df.empty or "model" not in messages_df.columns:
            return pd.DataFrame(columns=cols)
        framed = messages_df.dropna(subset=["model"])
        if framed.empty:
            return pd.DataFrame(columns=cols)
        g = (
            framed.groupby("model", dropna=True)
            .agg(
                message_count=("message_id", "count"),
                first_seen_local=("created_at_local", "min"),
                last_seen_local=("created_at_local", "max"),
            )
            .reset_index()
        )
        return g

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        row = conn.execute(f"""
            SELECT
                (SELECT count(*)::BIGINT FROM {SLUG}.sessions),
                (SELECT count(*)::BIGINT FROM {SLUG}.messages),
                (SELECT count(*)::BIGINT FROM {SLUG}.tool_calls),
                (SELECT min(created_at_local)::DATE FROM {SLUG}.sessions),
                (SELECT max(coalesce(updated_at_local, created_at_local))::DATE
                 FROM {SLUG}.sessions)
            """).fetchone()
        assert row is not None
        n_sess, n_msg, n_tools, first_day, last_day = row
        by_kind = conn.execute(f"""
            SELECT source_kind, count(*)::BIGINT
            FROM {SLUG}.sessions
            GROUP BY 1
            ORDER BY 2 DESC
            """).fetchall()
        kind_bits = ", ".join(f"{k}={n}" for k, n in by_kind) or "none"
        stats = getattr(self, "_parse_stats", {}) or {}
        parse_bits = ""
        if stats:
            parse_bits = (
                f"; parse composer={stats.get('composer_files', 0)}"
                f"/{stats.get('composer_corrupt', 0)} corrupt,"
                f" transcripts={stats.get('transcript_files', 0)}"
                f" (+{stats.get('transcript_merged_skip_messages', 0)} merged-skip)"
            )
        return {
            "sessions": int(n_sess or 0),
            "messages": int(n_msg or 0),
            "tool_calls": int(n_tools or 0),
            "first_day": first_day,
            "last_day": last_day,
            "parse_stats": dict(stats),
            "summary": (
                f"cursor_history: {n_sess} sessions ({kind_bits}), "
                f"{n_msg} messages, {n_tools} tool calls"
                + (f", {first_day} → {last_day}" if first_day and last_day else "")
                + parse_bits
            ),
        }


def iter_session_files(export_root: Path) -> Iterable[Path]:
    """Test helper: composer JSON files under an export root."""
    json_dir = export_root / "json"
    if json_dir.is_dir():
        yield from sorted(json_dir.glob("*.json"))
