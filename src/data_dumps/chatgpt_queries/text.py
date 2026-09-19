"""ChatGPT queries — text."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps.chatgpt_queries.filters import (
    NARRATIVE_CONTEXT_KEYS,
    FilterState,
    _conv_where,
    _msg_where,
    _query_df,
)
from data_dumps.chatgpt_queries.usage import (
    comeback_conversations,
    content_type_mix,
    forgotten_conversations,
    model_mix,
    scoreboard,
    streak_stats,
    top_conversations,
)

# English function words dropped from message clouds. Constants only — never user text.
MESSAGE_STOPWORDS: tuple[str, ...] = (
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "your",
    "what",
    "how",
    "are",
    "can",
    "into",
    "about",
    "have",
    "will",
    "you",
    "not",
    "but",
    "was",
    "were",
    "been",
    "they",
    "them",
    "their",
    "its",
    "our",
    "out",
    "all",
    "any",
    "just",
    "like",
    "would",
    "could",
    "should",
    "there",
    "here",
    "when",
    "where",
    "which",
    "who",
    "why",
    "then",
    "than",
    "also",
    "more",
    "some",
    "such",
    "only",
    "other",
    "over",
    "after",
    "before",
    "because",
    "while",
    "each",
    "both",
    "very",
    "too",
    "has",
    "had",
    "did",
    "does",
    "don",
    "one",
    "get",
    "got",
)


def _stopword_sql() -> str:
    return ", ".join("'" + word.replace("'", "''") + "'" for word in MESSAGE_STOPWORDS)


def _language_where(
    f: FilterState, *, role: str | None = None
) -> tuple[str, list[Any]]:
    """Message filters plus chat-text grain (no thoughts / recap)."""
    where, params = _msg_where(f)
    clauses = [
        where,
        "m.role IN ('user', 'assistant')",
        "m.content_type IN ('text', 'multimodal_text')",
    ]
    if role is not None and role != "all":
        clauses.append("m.role = ?")
        params.append(role)
    return " AND ".join(clauses), params


def message_tokens(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    role: str | None = None,
    limit: int = 150,
) -> pd.DataFrame:
    """Top message tokens.

    ``role`` is ``user``, ``assistant``, ``all`` (pooled), or ``None`` (top
    ``limit`` per role).
    """
    where, params = _language_where(f, role=None if role in (None, "all") else role)
    stops = _stopword_sql()
    if role == "all":
        params.append(limit)
        return _query_df(
            conn,
            f"""
            WITH raw AS (
                SELECT lower(
                    unnest(regexp_extract_all(coalesce(m.text, ''), '[A-Za-z]{{3,}}'))
                ) AS term
                FROM chatgpt.messages m
                WHERE {where}
            )
            SELECT term, count(*)::BIGINT AS n, 'all' AS role
            FROM raw
            WHERE term NOT IN ({stops})
            GROUP BY 1
            ORDER BY n DESC, term
            LIMIT ?
            """,
            params,
        )
    params.append(limit)
    return _query_df(
        conn,
        f"""
        WITH raw AS (
            SELECT
                m.role,
                lower(
                    unnest(regexp_extract_all(coalesce(m.text, ''), '[A-Za-z]{{3,}}'))
                ) AS term
            FROM chatgpt.messages m
            WHERE {where}
        ),
        counts AS (
            SELECT role, term, count(*)::BIGINT AS n
            FROM raw
            WHERE term NOT IN ({stops})
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT
                role,
                term,
                n,
                row_number() OVER (PARTITION BY role ORDER BY n DESC, term) AS rk
            FROM counts
        )
        SELECT term, n, role
        FROM ranked
        WHERE rk <= ?
        ORDER BY role, n DESC, term
        """,
        params,
    )


def user_bigrams(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 80,
) -> pd.DataFrame:
    """Adjacent user-prompt tokens (stopwords already removed)."""
    where, params = _language_where(f, role="user")
    stops = _stopword_sql()
    params.append(limit)
    return _query_df(
        conn,
        f"""
        WITH scoped AS (
            SELECT m.message_id, coalesce(m.text, '') AS text
            FROM chatgpt.messages m
            WHERE {where}
        ),
        toks AS (
            SELECT
                s.message_id,
                lower(u.term) AS term,
                u.pos
            FROM scoped s,
            LATERAL unnest(
                regexp_extract_all(s.text, '[A-Za-z]{{3,}}')
            ) WITH ORDINALITY AS u(term, pos)
        ),
        filtered AS (
            SELECT message_id, term, pos
            FROM toks
            WHERE term NOT IN ({stops})
        ),
        pairs AS (
            SELECT
                term || ' ' || lead(term) OVER (
                    PARTITION BY message_id ORDER BY pos
                ) AS term
            FROM filtered
        )
        SELECT term, count(*)::BIGINT AS n
        FROM pairs
        WHERE term IS NOT NULL
        GROUP BY 1
        ORDER BY n DESC, term
        LIMIT ?
        """,
        params,
    )


def distinctive_terms(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_count: int = 2,
    limit: int = 30,
) -> pd.DataFrame:
    """User-vs-assistant log-odds. Positive score means more typical of you."""
    where, params = _language_where(f)
    stops = _stopword_sql()
    params.extend([min_count, limit])
    return _query_df(
        conn,
        f"""
        WITH raw AS (
            SELECT
                m.role,
                lower(
                    unnest(regexp_extract_all(coalesce(m.text, ''), '[A-Za-z]{{3,}}'))
                ) AS term
            FROM chatgpt.messages m
            WHERE {where}
        ),
        counts AS (
            SELECT role, term, count(*)::BIGINT AS n
            FROM raw
            WHERE term NOT IN ({stops})
            GROUP BY 1, 2
        ),
        wide AS (
            SELECT
                term,
                coalesce(sum(n) FILTER (WHERE role = 'user'), 0)::BIGINT AS n_user,
                coalesce(sum(n) FILTER (WHERE role = 'assistant'), 0)::BIGINT
                    AS n_assistant
            FROM counts
            GROUP BY 1
        )
        SELECT
            term,
            n_user,
            n_assistant,
            ln((n_user + 1.0) / (n_assistant + 1.0)) AS score
        FROM wide
        WHERE n_user + n_assistant >= ?
        ORDER BY abs(score) DESC, term
        LIMIT ?
        """,
        params,
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
