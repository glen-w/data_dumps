"""Filter state and DuckDB queries for the ChatGPT Marimo dashboard."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util

NARRATIVE_CONTEXT_KEYS = frozenset(
    {
        "filter_digest",
        "filters",
        "scoreboard",
        "streak",
        "model_mix",
        "top_conversations",
        "forgotten",
        "comebacks",
        "content_mix",
    }
)


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    roles: list[str] = field(default_factory=list)
    model_families: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    title_search: str | None = None
    conversation_id: str | None = None
    shared_only: bool = False

    def has_entity_lock(self) -> bool:
        return bool(self.conversation_id)

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        for role in self.roles:
            chips.append(("role", f"role={role}"))
        for fam in self.model_families:
            chips.append(("model_family", f"model={fam}"))
        for ct in self.content_types:
            chips.append(("content_type", f"type={ct}"))
        if self.title_search:
            chips.append(("title_search", f"search: {self.title_search}"))
        if self.conversation_id:
            chips.append(("conversation_id", f"thread: {self.conversation_id[:8]}…"))
        if self.shared_only:
            chips.append(("shared_only", "shared only"))
        return chips

    def filter_digest(self) -> str:
        payload = {
            "year_start": self.year_start,
            "year_end": self.year_end,
            "roles": sorted(self.roles),
            "model_families": sorted(self.model_families),
            "content_types": sorted(self.content_types),
            "title_search": self.title_search,
            "conversation_id": self.conversation_id,
            "shared_only": self.shared_only,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def clear_field(self, field_name: str) -> None:
        if field_name == "year_range":
            self.year_start = None
            self.year_end = None
        elif field_name == "role":
            self.roles = []
        elif field_name == "model_family":
            self.model_families = []
        elif field_name == "content_type":
            self.content_types = []
        elif field_name == "title_search":
            self.title_search = None
        elif field_name == "conversation_id":
            self.conversation_id = None
        elif field_name == "shared_only":
            self.shared_only = False


def has_table(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return query_util.has_table(conn, "chatgpt", table)


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def _msg_where(f: FilterState, alias: str = "m") -> tuple[str, list[Any]]:
    p = f"{alias}."
    clauses: list[str] = [f"{p}ts_local IS NOT NULL"]
    params: list[Any] = []
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
    if f.roles:
        placeholders = ", ".join("?" for _ in f.roles)
        clauses.append(f"{p}role IN ({placeholders})")
        params.extend(f.roles)
    if f.model_families:
        placeholders = ", ".join("?" for _ in f.model_families)
        clauses.append(f"{p}model_family IN ({placeholders})")
        params.extend(f.model_families)
    if f.content_types:
        placeholders = ", ".join("?" for _ in f.content_types)
        clauses.append(f"{p}content_type IN ({placeholders})")
        params.extend(f.content_types)
    if f.conversation_id:
        clauses.append(f"{p}conversation_id = ?")
        params.append(f.conversation_id)
    if f.title_search or f.shared_only:
        sub: list[str] = [
            f"c.conversation_id = {p}conversation_id",
        ]
        if f.title_search:
            sub.append("contains(lower(coalesce(c.title, '')), lower(?))")
            params.append(f.title_search)
        if f.shared_only:
            sub.append("c.is_shared")
        clauses.append(
            "exists (SELECT 1 FROM chatgpt.conversations c WHERE "
            + " AND ".join(sub)
            + ")"
        )
    return " AND ".join(clauses), params


def _conv_where(f: FilterState, alias: str = "c") -> tuple[str, list[Any]]:
    p = f"{alias}."
    clauses: list[str] = []
    params: list[Any] = []
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
    if f.conversation_id:
        clauses.append(f"{p}conversation_id = ?")
        params.append(f.conversation_id)
    if f.title_search:
        clauses.append(f"contains(lower(coalesce({p}title, '')), lower(?))")
        params.append(f.title_search)
    if f.shared_only:
        clauses.append(f"{p}is_shared")
    if f.model_families:
        placeholders = ", ".join("?" for _ in f.model_families)
        clauses.append(f"{p}default_model_family IN ({placeholders})")
        params.extend(f.model_families)
    return (" AND ".join(clauses) if clauses else "1=1"), params


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(ts_local)::DATE, max(ts_local)::DATE
        FROM chatgpt.messages
        WHERE ts_local IS NOT NULL
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2023, 2023
    roles = [
        r[0]
        for r in conn.execute(
            "SELECT role FROM chatgpt.messages WHERE role IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC"
        ).fetchall()
        if r[0]
    ]
    families = [r[0] for r in conn.execute("""
            SELECT model_family FROM chatgpt.messages
            WHERE model_family IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """).fetchall() if r[0]]
    content_types = [r[0] for r in conn.execute("""
            SELECT content_type FROM chatgpt.messages
            WHERE content_type IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """).fetchall() if r[0]]
    n_shared = conn.execute("SELECT count(*)::BIGINT FROM chatgpt.shared").fetchone()
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "roles": roles,
        "model_families": families,
        "content_types": content_types,
        "n_shared": int(n_shared[0]) if n_shared else 0,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int | None,
    year_end: int | None,
    roles: list[str] | None = None,
    model_families: list[str] | None = None,
    content_types: list[str] | None = None,
    title_search: str = "",
    conversation_id: str | None = None,
    shared_only: bool = False,
) -> FilterState:
    ys = year_start if year_start is not None else bounds.get("min_year")
    ye = year_end if year_end is not None else bounds.get("max_year")
    # Treat full span as no year filter for compare windows.
    if ys == bounds.get("min_year") and ye == bounds.get("max_year"):
        pass  # keep explicit years for scoreboard compare
    return FilterState(
        year_start=ys,
        year_end=ye,
        roles=list(roles or []),
        model_families=list(model_families or []),
        content_types=list(content_types or []),
        title_search=(title_search or "").strip() or None,
        conversation_id=conversation_id or None,
        shared_only=bool(shared_only),
    )


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare_previous: bool = False,
) -> pd.DataFrame:
    current = _scoreboard_row(conn, f)
    if not compare_previous or f.year_start is None or f.year_end is None:
        current["window"] = "current"
        return current
    span = f.year_end - f.year_start + 1
    prev_start = f.year_start - span
    prev_end = f.year_start - 1
    min_row = conn.execute(
        "SELECT min(year)::INT FROM chatgpt.messages WHERE year IS NOT NULL"
    ).fetchone()
    min_year = min_row[0] if min_row else None
    if min_year is None or prev_start < min_year:
        current["window"] = "current"
        current["compare_note"] = (
            f"previous window ({prev_start}–{prev_end}) predates data "
            f"(min year {min_year})"
        )
        return current
    prev_f = FilterState(
        year_start=prev_start,
        year_end=prev_end,
        roles=list(f.roles),
        model_families=list(f.model_families),
        content_types=list(f.content_types),
        title_search=f.title_search,
        conversation_id=f.conversation_id,
        shared_only=f.shared_only,
    )
    prev = _scoreboard_row(conn, prev_f)
    current["window"] = "current"
    prev["window"] = f"previous ({prev_start}–{prev_end})"
    return pd.concat([current, prev], ignore_index=True)


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    mw, mp = _msg_where(f)
    cw, cp = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            (SELECT count(*)::BIGINT FROM chatgpt.messages m WHERE {mw}) AS messages,
            (SELECT count(DISTINCT m.conversation_id)::BIGINT
             FROM chatgpt.messages m WHERE {mw}) AS conversations,
            (SELECT count(DISTINCT m.ts_local::DATE)::BIGINT
             FROM chatgpt.messages m WHERE {mw}) AS active_days,
            (SELECT count(*)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.role = 'user') AS user_messages,
            (SELECT count(*)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.role = 'assistant') AS assistant_messages,
            (SELECT coalesce(sum(m.char_count), 0)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.role = 'user') AS user_chars,
            (SELECT coalesce(sum(m.char_count), 0)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.role = 'assistant') AS assistant_chars,
            (SELECT count(*)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.content_type = 'thoughts') AS thought_messages,
            (SELECT coalesce(sum(m.image_count), 0)::BIGINT FROM chatgpt.messages m
             WHERE {mw}) AS images,
            (SELECT count(*)::BIGINT FROM chatgpt.conversations c
             WHERE {cw} AND c.is_shared) AS shared_conversations,
            (SELECT min(m.ts_local)::DATE FROM chatgpt.messages m WHERE {mw}) AS first_day,
            (SELECT max(m.ts_local)::DATE FROM chatgpt.messages m WHERE {mw}) AS last_day
        """,
        [*mp, *mp, *mp, *mp, *mp, *mp, *mp, *mp, *mp, *cp, *mp, *mp],
    )


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT m.ts_local::DATE AS day, count(*)::BIGINT AS messages
            FROM chatgpt.messages m
            WHERE {where}
            GROUP BY 1
        ),
        ranked AS (
            SELECT
                day,
                messages,
                day - (row_number() OVER (ORDER BY day))::INT AS grp
            FROM daily
        ),
        streaks AS (
            SELECT grp, count(*) AS streak_days, sum(messages) AS streak_messages
            FROM ranked
            GROUP BY grp
        ),
        busiest AS (
            SELECT day, messages FROM daily ORDER BY messages DESC LIMIT 1
        )
        SELECT
            (SELECT max(streak_days) FROM streaks) AS longest_streak_days,
            (SELECT max(streak_messages) FROM streaks) AS longest_streak_messages,
            (SELECT day FROM busiest) AS busiest_day,
            (SELECT messages FROM busiest) AS busiest_day_messages,
            (SELECT count(*) FROM daily) AS active_days
        """,
        params,
    )


def messages_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE role = 'user')::BIGINT AS user_messages,
            count(*) FILTER (WHERE role = 'assistant')::BIGINT AS assistant_messages,
            count(DISTINCT conversation_id)::BIGINT AS conversations,
            coalesce(sum(char_count) FILTER (WHERE role = 'user'), 0)::BIGINT AS user_chars
        FROM chatgpt.messages m
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def messages_daily_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT m.ts_local::DATE AS day, count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def messages_monthly_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    return messages_monthly(conn, f)[["year_month", "messages"]]


def conversations_monthly_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS conversations
        FROM chatgpt.conversations c
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def conversations_daily_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT c.create_ts_local::DATE AS day, count(*)::BIGINT AS conversations
        FROM chatgpt.conversations c
        WHERE {where} AND c.create_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def conversation_messages_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    conversation_id: str,
) -> pd.DataFrame:
    f = FilterState(
        year_start=year_start,
        year_end=year_end,
        conversation_id=conversation_id,
    )
    return messages_monthly(conn, f)[["year_month", "messages"]]


def conversation_options(
    conn: duckdb.DuckDBPyConnection, *, limit: int = 40
) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT conversation_id, coalesce(nullif(title, ''), conversation_id) AS label,
               n_messages
        FROM chatgpt.conversations
        ORDER BY n_messages DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [
        {"value": str(r[0]), "label": f"{r[1][:60]} ({r[2]})"} for r in rows if r[0]
    ]


def model_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(model_family, 'unknown') AS model_family,
            coalesce(model_slug, 'unknown') AS model_slug,
            count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where} AND role = 'assistant'
        GROUP BY 1, 2
        ORDER BY messages DESC
        """,
        params,
    )


def model_family_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            coalesce(model_family, 'unknown') AS model_family,
            count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where} AND role = 'assistant' AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 3 DESC
        """,
        params,
    )


def content_type_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT content_type, count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where}
        GROUP BY 1
        ORDER BY messages DESC
        """,
        params,
    )


def role_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT role, count(*)::BIGINT AS messages,
               coalesce(sum(char_count), 0)::BIGINT AS chars
        FROM chatgpt.messages m
        WHERE {where}
        GROUP BY 1
        ORDER BY messages DESC
        """,
        params,
    )


def weekday_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT weekday::INT AS dow, hour, count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where} AND weekday IS NOT NULL AND hour IS NOT NULL
        GROUP BY 1, 2
        """,
        params,
    )


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            m.ts_local::DATE AS day,
            isodow(m.ts_local) AS weekday,
            weekofyear(m.ts_local) AS iso_week,
            year(m.ts_local) AS year,
            count(*)::BIGINT AS events
        FROM chatgpt.messages m
        WHERE {where}
        GROUP BY 1, 2, 3, 4
        ORDER BY 1
        """,
        params,
    )


def top_conversations(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    mw, mp = _msg_where(f, "m")
    return _query_df(
        conn,
        f"""
        SELECT
            c.conversation_id,
            coalesce(nullif(c.title, ''), '(untitled)') AS title,
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE m.role = 'user')::BIGINT AS user_messages,
            coalesce(sum(m.char_count) FILTER (WHERE m.role = 'user'), 0)::BIGINT
                AS user_chars,
            min(m.ts_local)::DATE AS first_day,
            max(m.ts_local)::DATE AS last_day,
            c.default_model_family,
            c.is_shared,
            c.gizmo_id IS NOT NULL AS is_project
        FROM chatgpt.messages m
        JOIN chatgpt.conversations c ON c.conversation_id = m.conversation_id
        WHERE {mw}
        GROUP BY
            c.conversation_id, c.title, c.default_model_family, c.is_shared, c.gizmo_id
        ORDER BY messages DESC
        LIMIT ?
        """,
        [*mp, limit],
    )


def conversation_scatter(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 400
) -> pd.DataFrame:
    cw, cp = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            conversation_id,
            coalesce(nullif(title, ''), '(untitled)') AS title,
            n_messages,
            n_user,
            user_chars,
            assistant_chars,
            n_thoughts,
            n_images,
            default_model_family,
            is_shared,
            date_diff('day', create_ts_local, update_ts_local) AS span_days,
            create_ts_local::DATE AS created
        FROM chatgpt.conversations c
        WHERE {cw}
          AND n_messages > 0
          AND create_ts_local IS NOT NULL
          AND update_ts_local IS NOT NULL
        ORDER BY n_messages DESC
        LIMIT ?
        """,
        [*cp, limit],
    )


def forgotten_conversations(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    """Deep threads silent for ≥2 years relative to the filter end."""
    max_row = conn.execute("SELECT max(year) FROM chatgpt.messages").fetchone()
    end_year: int | None = f.year_end
    if end_year is None and max_row is not None:
        end_year = max_row[0]
    if end_year is None:
        return pd.DataFrame()
    cutoff_year = int(end_year) - 2
    mw, mp = _msg_where(
        FilterState(
            year_start=None,
            year_end=None,
            roles=list(f.roles),
            model_families=[],
            content_types=list(f.content_types),
            title_search=f.title_search,
            conversation_id=f.conversation_id,
            shared_only=f.shared_only,
        )
    )
    return _query_df(
        conn,
        f"""
        WITH activity AS (
            SELECT
                m.conversation_id,
                count(*)::BIGINT AS messages,
                max(m.ts_local) AS last_ts,
                min(m.ts_local) AS first_ts
            FROM chatgpt.messages m
            WHERE {mw}
            GROUP BY 1
        )
        SELECT
            c.conversation_id,
            coalesce(nullif(c.title, ''), '(untitled)') AS title,
            a.messages,
            a.first_ts::DATE AS first_day,
            a.last_ts::DATE AS last_day,
            date_diff('day', a.last_ts, current_date) AS days_silent
        FROM activity a
        JOIN chatgpt.conversations c ON c.conversation_id = a.conversation_id
        WHERE year(a.last_ts) <= ?
          AND a.messages >= 6
        ORDER BY a.messages DESC, a.last_ts
        LIMIT ?
        """,
        [*mp, cutoff_year, limit],
    )


def comeback_conversations(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    """Threads resumed after a ≥90 day silence, within the filter years."""
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                conversation_id,
                ts_local,
                lag(ts_local) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local
                ) AS prev_ts
            FROM chatgpt.messages m
            WHERE {where}
        ),
        gaps AS (
            SELECT
                conversation_id,
                prev_ts,
                ts_local,
                date_diff('day', prev_ts, ts_local) AS gap_days
            FROM ordered
            WHERE prev_ts IS NOT NULL
              AND date_diff('day', prev_ts, ts_local) >= 90
        )
        SELECT
            c.conversation_id,
            coalesce(nullif(c.title, ''), '(untitled)') AS title,
            g.gap_days,
            g.prev_ts::DATE AS paused_on,
            g.ts_local::DATE AS resumed_on,
            c.n_messages
        FROM gaps g
        JOIN chatgpt.conversations c ON c.conversation_id = g.conversation_id
        ORDER BY g.gap_days DESC, g.ts_local DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def model_rank_bump(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, top_n: int = 8
) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT
                year,
                coalesce(model_family, 'unknown') AS model_family,
                count(*)::BIGINT AS messages
            FROM chatgpt.messages m
            WHERE {where} AND role = 'assistant' AND year IS NOT NULL
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT
                year,
                model_family,
                messages,
                row_number() OVER (PARTITION BY year ORDER BY messages DESC) AS rank
            FROM yearly
        ),
        keep AS (
            SELECT model_family
            FROM ranked
            WHERE rank <= ?
            GROUP BY 1
        )
        SELECT r.year, r.model_family, r.messages, r.rank
        FROM ranked r
        JOIN keep k ON k.model_family = r.model_family
        ORDER BY r.year, r.rank
        """,
        [*params, top_n],
    )


def reply_latency(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """User → next assistant latency distribution (minutes)."""
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                conversation_id,
                role,
                ts_local,
                lead(role) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local, message_id
                ) AS next_role,
                lead(ts_local) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local, message_id
                ) AS next_ts
            FROM chatgpt.messages m
            WHERE {where}
              AND role IN ('user', 'assistant')
              AND content_type IN ('text', 'multimodal_text')
        )
        SELECT
            count(*)::BIGINT AS pairs,
            round(avg(epoch(next_ts - ts_local) / 60.0), 2) AS mean_minutes,
            round(median(epoch(next_ts - ts_local) / 60.0), 2) AS median_minutes,
            round(quantile_cont(epoch(next_ts - ts_local) / 60.0, 0.9), 2)
                AS p90_minutes
        FROM ordered
        WHERE role = 'user' AND next_role = 'assistant' AND next_ts IS NOT NULL
          AND epoch(next_ts - ts_local) BETWEEN 0 AND 86400 * 2
        """,
        params,
    )


def reply_latency_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                conversation_id,
                role,
                ts_local,
                year,
                month,
                lead(role) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local, message_id
                ) AS next_role,
                lead(ts_local) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local, message_id
                ) AS next_ts
            FROM chatgpt.messages m
            WHERE {where}
              AND role IN ('user', 'assistant')
              AND content_type IN ('text', 'multimodal_text')
        )
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            round(median(epoch(next_ts - ts_local) / 60.0), 2) AS median_minutes,
            count(*)::BIGINT AS pairs
        FROM ordered
        WHERE role = 'user' AND next_role = 'assistant' AND next_ts IS NOT NULL
          AND year IS NOT NULL AND month IS NOT NULL
          AND epoch(next_ts - ts_local) BETWEEN 0 AND 86400 * 2
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def gizmo_usage(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    cw, cp = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            gizmo_id,
            count(*)::BIGINT AS conversations,
            sum(n_messages)::BIGINT AS messages,
            sum(user_chars)::BIGINT AS user_chars
        FROM chatgpt.conversations c
        WHERE {cw} AND gizmo_id IS NOT NULL
        GROUP BY 1
        ORDER BY conversations DESC
        LIMIT ?
        """,
        [*cp, limit],
    )


def asset_extension_mix(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    if not has_table(conn, "assets"):
        return pd.DataFrame()
    return _query_df(
        conn,
        """
        SELECT
            coalesce(file_extension, 'unknown') AS file_extension,
            source,
            count(*)::BIGINT AS files,
            coalesce(sum(file_size_bytes), 0)::BIGINT AS bytes
        FROM chatgpt.assets
        GROUP BY 1, 2
        ORDER BY files DESC
        """,
    )


def shared_list(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 40
) -> pd.DataFrame:
    cw, cp = _conv_where(f, alias="c2")
    return _query_df(
        conn,
        f"""
        SELECT
            s.title,
            s.conversation_id,
            s.is_anonymous,
            c.n_messages,
            c.default_model_family,
            c.create_ts_local::DATE AS created
        FROM chatgpt.shared s
        LEFT JOIN chatgpt.conversations c ON c.conversation_id = s.conversation_id
        WHERE s.conversation_id IS NULL OR exists (
            SELECT 1 FROM chatgpt.conversations c2
            WHERE c2.conversation_id = s.conversation_id AND ({cw})
        )
        ORDER BY c.n_messages DESC NULLS LAST
        LIMIT ?
        """,
        [*cp, limit],
    )


def title_tokens(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 30
) -> pd.DataFrame:
    """Crude title-word frequency (stopword-light) for topic vibes."""
    cw, cp = _conv_where(f)
    return _query_df(
        conn,
        f"""
        WITH words AS (
            SELECT
                unnest(
                    regexp_extract_all(coalesce(title, ''), '[A-Za-z]{{3,}}')
                ) AS token
            FROM chatgpt.conversations c
            WHERE {cw} AND title IS NOT NULL
        )
        SELECT lower(token) AS token, count(*)::BIGINT AS uses
        FROM words
        WHERE lower(token) NOT IN (
            'the', 'and', 'for', 'with', 'from', 'that', 'this', 'your',
            'what', 'how', 'are', 'can', 'into', 'about', 'have', 'will'
        )
        GROUP BY 1
        ORDER BY uses DESC
        LIMIT ?
        """,
        [*cp, limit],
    )


def conversation_messages(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 80
) -> pd.DataFrame:
    if not f.conversation_id:
        return pd.DataFrame()
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            ts_local,
            role,
            content_type,
            model_slug,
            char_count,
            image_count,
            left(coalesce(text, ''), 240) AS preview
        FROM chatgpt.messages m
        WHERE {where}
        ORDER BY ts_local, message_id
        LIMIT ?
        """,
        [*params, limit],
    )


def narrative_context(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> dict[str, Any]:
    score = scoreboard(conn, f).to_dict(orient="records")
    streak = streak_stats(conn, f).to_dict(orient="records")
    models = model_mix(conn, f).head(8).to_dict(orient="records")
    tops = top_conversations(conn, f, limit=8).to_dict(orient="records")
    forgotten = forgotten_conversations(conn, f, limit=5).to_dict(orient="records")
    comebacks = comeback_conversations(conn, f, limit=5).to_dict(orient="records")
    content = content_type_mix(conn, f).to_dict(orient="records")
    ctx = {
        "filter_digest": f.filter_digest(),
        "filters": dict(f.chip_labels()),
        "scoreboard": score,
        "streak": streak,
        "model_mix": models,
        "top_conversations": [
            {k: v for k, v in row.items() if k != "conversation_id"} for row in tops
        ],
        "forgotten": [
            {k: v for k, v in row.items() if k != "conversation_id"}
            for row in forgotten
        ],
        "comebacks": [
            {k: v for k, v in row.items() if k != "conversation_id"}
            for row in comebacks
        ],
        "content_mix": content,
    }
    return {k: ctx[k] for k in NARRATIVE_CONTEXT_KEYS}
