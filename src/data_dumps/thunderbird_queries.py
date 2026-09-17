"""Filter state and DuckDB queries for the Thunderbird Marimo dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    account_keys: list[str] = field(default_factory=list)
    folder_ids: list[int] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    signal_kinds: list[str] = field(default_factory=list)
    contact_substr: str | None = None
    contact_exact: str | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        if self.account_keys:
            chips.append(("accounts", f"{len(self.account_keys)} account(s)"))
        if self.folder_ids:
            chips.append(("folders", f"{len(self.folder_ids)} folder(s)"))
        if self.directions:
            chips.append(("direction", ",".join(self.directions)))
        if self.domains:
            chips.append(("domains", f"{len(self.domains)} domain(s)"))
        if self.signal_kinds:
            chips.append(("signals", ",".join(self.signal_kinds)))
        if self.contact_exact:
            chips.append(("contact_lock", self.contact_exact))
        elif self.contact_substr:
            chips.append(("contact", self.contact_substr))
        return chips


def _where(f: FilterState, alias: str = "m") -> tuple[str, list[Any]]:
    p = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
    if f.account_keys:
        ph = ", ".join("?" for _ in f.account_keys)
        clauses.append(f"fo.account_key IN ({ph})")
        params.extend(f.account_keys)
    if f.folder_ids:
        ph = ", ".join("?" for _ in f.folder_ids)
        clauses.append(f"{p}folder_id IN ({ph})")
        params.extend(f.folder_ids)
    if f.directions:
        ph = ", ".join("?" for _ in f.directions)
        clauses.append(f"{p}direction IN ({ph})")
        params.extend(f.directions)
    if f.domains:
        ph = ", ".join("?" for _ in f.domains)
        clauses.append(f"{p}from_domain IN ({ph})")
        params.extend(f.domains)
    if f.contact_exact:
        clauses.append(f"lower(coalesce({p}from_addr, {p}from_raw, '')) = ?")
        params.append(f.contact_exact.lower())
    elif f.contact_substr:
        clauses.append(
            f"(lower(coalesce({p}from_addr,'')) LIKE ? "
            f"OR lower(coalesce({p}from_raw,'')) LIKE ?)"
        )
        needle = f"%{f.contact_substr.lower()}%"
        params.extend([needle, needle])
    if f.signal_kinds:
        ph = ", ".join("?" for _ in f.signal_kinds)
        clauses.append(f"""EXISTS (
                SELECT 1 FROM thunderbird.signals s
                WHERE s.message_id = {p}gloda_id AND s.kind IN ({ph})
            )""")
        params.extend(f.signal_kinds)
    return (" AND ".join(clauses) if clauses else "1=1"), params


def _from_join() -> str:
    return """
        FROM thunderbird.messages m
        LEFT JOIN thunderbird.folders fo ON fo.folder_id = m.folder_id
    """


def _query_df(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(local_date)::DATE, max(local_date)::DATE
        FROM thunderbird.messages
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2018, 2025
    accounts = conn.execute("""
        SELECT account_key, count(*)::BIGINT AS n
        FROM thunderbird.folders
        GROUP BY 1
        ORDER BY n DESC, account_key
        """).fetchall()
    folders = conn.execute("""
        SELECT f.folder_id, f.name, f.account_key, count(m.gloda_id)::BIGINT AS n
        FROM thunderbird.folders f
        LEFT JOIN thunderbird.messages m ON m.folder_id = f.folder_id
        GROUP BY 1, 2, 3
        ORDER BY n DESC, f.name
        """).fetchall()
    domains = conn.execute("""
        SELECT from_domain, count(*)::BIGINT AS n
        FROM thunderbird.messages
        WHERE from_domain IS NOT NULL AND from_domain <> ''
        GROUP BY 1
        ORDER BY n DESC
        LIMIT 80
        """).fetchall()
    signal_kinds = conn.execute("""
        SELECT kind, count(*)::BIGINT AS n
        FROM thunderbird.signals
        GROUP BY 1
        ORDER BY n DESC
        """).fetchall()
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "accounts": [{"account_key": r[0], "folders": r[1]} for r in accounts],
        "folders": [
            {
                "folder_id": r[0],
                "name": r[1],
                "account_key": r[2],
                "messages": r[3],
            }
            for r in folders
        ],
        "domains": [{"domain": r[0], "messages": r[1]} for r in domains],
        "signal_kinds": [{"kind": r[0], "messages": r[1]} for r in signal_kinds],
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    account_keys: list[str] | None = None,
    folder_ids: list[int] | None = None,
    directions: list[str] | None = None,
    domains: list[str] | None = None,
    signal_kinds: list[str] | None = None,
    contact_substr: str | None = None,
    contact_exact: str | None = None,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    contact = (contact_substr or "").strip() or None
    exact = (contact_exact or "").strip() or None
    return FilterState(
        year_start=ys,
        year_end=ye,
        account_keys=list(account_keys or []),
        folder_ids=list(folder_ids or []),
        directions=list(directions or []),
        domains=list(domains or []),
        signal_kinds=list(signal_kinds or []),
        contact_substr=contact,
        contact_exact=exact,
    )


def previous_window(f: FilterState) -> FilterState | None:
    bounds = query_util.previous_year_bounds(f.year_start, f.year_end)
    if bounds is None:
        return None
    return replace(
        f,
        year_start=bounds[0],
        year_end=bounds[1],
    )


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare_previous: bool = False,
) -> pd.DataFrame:
    where, params = _where(f)
    cur = _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE direction = 'sent')::BIGINT AS sent,
            count(*) FILTER (WHERE direction = 'received')::BIGINT AS received,
            count(*) FILTER (WHERE has_attachment)::BIGINT AS with_attachments,
            count(DISTINCT local_date)::BIGINT AS active_days,
            count(DISTINCT from_addr)::BIGINT AS unique_senders,
            count(DISTINCT conversation_id)::BIGINT AS conversations
        {_from_join()}
        WHERE {where}
        """,
        params,
    )
    cur["window"] = "current"
    if not compare_previous:
        return cur
    prev_f = previous_window(f)
    if prev_f is None:
        return cur
    where_p, params_p = _where(prev_f)
    prev = _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE direction = 'sent')::BIGINT AS sent,
            count(*) FILTER (WHERE direction = 'received')::BIGINT AS received,
            count(*) FILTER (WHERE has_attachment)::BIGINT AS with_attachments,
            count(DISTINCT local_date)::BIGINT AS active_days,
            count(DISTINCT from_addr)::BIGINT AS unique_senders,
            count(DISTINCT conversation_id)::BIGINT AS conversations
        {_from_join()}
        WHERE {where_p}
        """,
        params_p,
    )
    prev["window"] = "previous"
    return pd.concat([cur, prev], ignore_index=True)


def monthly_volume(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    df = _query_df(
        conn,
        f"""
        SELECT year, month, direction, count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
        """,
        params,
    )
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def yearly_volume(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT year, direction, count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def circadian_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT coalesce(weekday, dow) AS dow, hour, count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day, count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def top_senders(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(from_addr, from_raw, '(unknown)') AS contact,
            from_domain AS domain,
            count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where} AND direction = 'received'
        GROUP BY 1, 2
        ORDER BY messages DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def top_recipients(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _where(f)
    # Participants role=to for sent mail in window
    return _query_df(
        conn,
        f"""
        SELECT
            p.addr AS contact,
            p.domain AS domain,
            count(*)::BIGINT AS messages
        FROM thunderbird.participants p
        JOIN thunderbird.messages m ON m.gloda_id = p.message_id
        LEFT JOIN thunderbird.folders fo ON fo.folder_id = m.folder_id
        WHERE p.role = 'to' AND m.direction = 'sent' AND {where}
        GROUP BY 1, 2
        ORDER BY messages DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def top_domains(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 30
) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT from_domain AS domain, count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
          AND from_domain IS NOT NULL AND from_domain <> ''
        GROUP BY 1
        ORDER BY messages DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def domain_sunburst(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            year,
            month,
            from_domain AS domain,
            count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
          AND from_domain IS NOT NULL AND from_domain <> ''
        GROUP BY 1, 2, 3
        ORDER BY messages DESC
        LIMIT 500
        """,
        params,
    )


def folder_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(fo.name, '(unknown)') AS folder,
            coalesce(fo.account_key, '(unknown)') AS account_key,
            count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY messages DESC
        """,
        params,
    )


def account_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(fo.account_key, '(unknown)') AS account_key,
            count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1
        ORDER BY messages DESC
        """,
        params,
    )


def thread_sizes(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT conversation_id, count(*)::BIGINT AS messages,
               min(subject) AS sample_subject
        {_from_join()}
        WHERE {where} AND conversation_id IS NOT NULL
        GROUP BY 1
        HAVING count(*) >= 2
        ORDER BY messages DESC
        LIMIT 40
        """,
        params,
    )


def attachment_extensions(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Count attachment file extensions (first match per attachment_names blob)."""
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(
                nullif(lower(regexp_extract(attachment_names, '\\.([A-Za-z0-9]+)(\\n|$)', 1)), ''),
                '(none)'
            ) AS extension,
            count(*)::BIGINT AS files
        {_from_join()}
        WHERE {where} AND has_attachment
          AND attachment_names IS NOT NULL
        GROUP BY 1
        ORDER BY files DESC
        LIMIT 30
        """,
        params,
    )


def signal_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT s.kind, count(*)::BIGINT AS messages
        FROM thunderbird.signals s
        JOIN thunderbird.messages m ON m.gloda_id = s.message_id
        LEFT JOIN thunderbird.folders fo ON fo.folder_id = m.folder_id
        WHERE {where}
        GROUP BY 1
        ORDER BY messages DESC
        """,
        params,
    )


def signal_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    df = _query_df(
        conn,
        f"""
        SELECT m.year, m.month, s.kind, count(*)::BIGINT AS messages
        FROM thunderbird.signals s
        JOIN thunderbird.messages m ON m.gloda_id = s.message_id
        LEFT JOIN thunderbird.folders fo ON fo.folder_id = m.folder_id
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
        """,
        params,
    )
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def signals_total_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    raw = signal_monthly(conn, f)
    if raw.empty:
        return pd.DataFrame(columns=["year_month", "messages"])
    summed = raw.groupby("year_month", as_index=False)["messages"].sum()
    return pd.DataFrame(summed).sort_values("year_month")


def mask_addr(addr: str | None) -> str:
    """InboxPie-style light masking for UI tables."""
    if not addr or "@" not in addr:
        return addr or ""
    local, _, domain = addr.partition("@")
    if len(local) <= 2:
        return f"{local[0]}*@{domain}"
    return f"{local[0]}{'*' * min(4, len(local) - 2)}{local[-1]}@{domain}"


def forgotten_contacts(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_messages: int = 3,
    silent_years: int = 1,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _where(f)
    params.extend([min_messages, silent_years, limit])
    return _query_df(
        conn,
        f"""
        WITH span AS (
            SELECT
                coalesce(from_addr, from_raw, '(unknown)') AS contact,
                from_domain AS domain,
                count(*)::BIGINT AS messages,
                max(date_utc) AS last_ts
            {_from_join()}
            WHERE {where} AND direction = 'received'
            GROUP BY 1, 2
            HAVING count(*) >= ?
        )
        SELECT contact, domain, messages, last_ts::DATE AS last_day
        FROM span
        WHERE last_ts < current_timestamp - (? * INTERVAL '1 year')
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def comeback_contacts(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 1,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _where(f)
    params.extend([silent_years, limit])
    return _query_df(
        conn,
        f"""
        WITH filtered AS (
            SELECT
                coalesce(from_addr, from_raw, '(unknown)') AS contact,
                from_addr,
                date_utc
            {_from_join()}
            WHERE {where} AND direction = 'received'
        ),
        span AS (
            SELECT
                contact,
                from_addr,
                min(date_utc) AS first_in_window,
                count(*)::BIGINT AS window_messages
            FROM filtered
            GROUP BY 1, 2
        ),
        prior AS (
            SELECT
                coalesce(m.from_addr, m.from_raw) AS from_addr,
                max(m.date_utc) AS last_before
            FROM thunderbird.messages m
            INNER JOIN span a ON coalesce(m.from_addr, m.from_raw) = a.from_addr
            WHERE m.date_utc < a.first_in_window AND m.direction = 'received'
            GROUP BY 1
        )
        SELECT
            a.contact,
            a.window_messages,
            p.last_before::DATE AS last_before,
            round(date_diff('day', p.last_before, a.first_in_window) / 365.25, 1)
                AS gap_years
        FROM span a
        INNER JOIN prior p ON a.from_addr = p.from_addr
        WHERE p.last_before < a.first_in_window - (? * INTERVAL '1 year')
        ORDER BY a.window_messages DESC
        LIMIT ?
        """,
        params,
    )


def sender_rank_bump(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 10
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT
                year,
                coalesce(from_addr, from_raw, '(unknown)') AS contact,
                count(*)::BIGINT AS messages
            {_from_join()}
            WHERE {where} AND direction = 'received' AND year IS NOT NULL
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT
                year,
                contact,
                messages,
                row_number() OVER (PARTITION BY year ORDER BY messages DESC) AS rank
            FROM yearly
        )
        SELECT year, contact, messages, rank
        FROM ranked
        WHERE rank <= ?
        ORDER BY year, rank
        """,
        params,
    )


def message_streaks(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT local_date AS day
            {_from_join()}
            WHERE {where} AND local_date IS NOT NULL
            GROUP BY 1
        ),
        ordered AS (
            SELECT
                day,
                day - (row_number() OVER (ORDER BY day))::INT AS grp
            FROM daily
        ),
        streaks AS (
            SELECT count(*)::BIGINT AS streak_len, max(day) AS last_d
            FROM ordered
            GROUP BY grp
        )
        SELECT
            coalesce(max(streak_len), 0)::BIGINT AS longest_active_streak,
            coalesce(
                (SELECT streak_len FROM streaks ORDER BY last_d DESC LIMIT 1),
                0
            )::BIGINT AS current_active_streak
        FROM streaks
        """,
        params,
    )


def thread_latency(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 40
) -> pd.DataFrame:
    """Thread depth plus span (hours) between first and last message."""
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            conversation_id,
            count(*)::BIGINT AS messages,
            min(subject) AS sample_subject,
            min(date_utc) AS first_ts,
            max(date_utc) AS last_ts,
            round(epoch(max(date_utc) - min(date_utc)) / 3600.0, 1) AS span_hours
        {_from_join()}
        WHERE {where} AND conversation_id IS NOT NULL
        GROUP BY 1
        HAVING count(*) >= 2
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def contact_scatter(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Per-contact received volume vs messages you sent to them (to: participants)."""
    where, params = _where(f)
    # Build a parallel filter for participants join on sent mail
    where_sent, params_sent = _where(f)
    return _query_df(
        conn,
        f"""
        WITH received AS (
            SELECT
                coalesce(from_addr, from_raw, '(unknown)') AS contact,
                count(*)::BIGINT AS received
            {_from_join()}
            WHERE {where} AND direction = 'received'
            GROUP BY 1
        ),
        sent AS (
            SELECT
                p.addr AS contact,
                count(*)::BIGINT AS sent
            FROM thunderbird.participants p
            JOIN thunderbird.messages m ON m.gloda_id = p.message_id
            LEFT JOIN thunderbird.folders fo ON fo.folder_id = m.folder_id
            WHERE p.role = 'to' AND m.direction = 'sent' AND {where_sent}
            GROUP BY 1
        )
        SELECT
            coalesce(r.contact, s.contact) AS contact,
            coalesce(r.received, 0)::BIGINT AS received,
            coalesce(s.sent, 0)::BIGINT AS sent
        FROM received r
        FULL OUTER JOIN sent s ON r.contact = s.contact
        WHERE coalesce(r.received, 0) + coalesce(s.sent, 0) >= 2
        ORDER BY (coalesce(r.received, 0) + coalesce(s.sent, 0)) DESC
        LIMIT 200
        """,
        [*params, *params_sent],
    )


def narrative_context(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
) -> dict[str, Any]:
    """Aggregates only — addresses and counts, never message bodies."""
    score = scoreboard(conn, f, compare_previous=True)
    streaks = message_streaks(conn, f)
    senders = top_senders(conn, f, limit=10)[["contact", "messages"]]
    domains = top_domains(conn, f, limit=10)
    signals = signal_mix(conn, f)
    forgotten = forgotten_contacts(conn, f, limit=5, min_messages=1)
    comebacks = comeback_contacts(conn, f, limit=5)
    return {
        "filters": f.chip_labels(),
        "scoreboard": score.to_dict(orient="records"),
        "streaks": streaks.to_dict(orient="records"),
        "top_senders": senders.to_dict(orient="records"),
        "top_domains": domains.to_dict(orient="records"),
        "signals": signals.to_dict(orient="records"),
        "forgotten": forgotten.to_dict(orient="records"),
        "comebacks": comebacks.to_dict(orient="records"),
    }
