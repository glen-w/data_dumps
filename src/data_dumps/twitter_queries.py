"""Filter state and DuckDB queries for the Twitter Marimo dashboard."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

NARRATIVE_CONTEXT_KEYS = frozenset(
    {
        "filter_digest",
        "filters",
        "scoreboard",
        "streak",
        "discovery",
        "top_mentions",
        "top_hashtags",
        "comebacks",
        "forgotten",
    }
)


@dataclass
class FilterState:
    """One filter state drives every Twitter dashboard query."""

    year_start: int | None = None
    year_end: int | None = None
    tweet_types: list[str] = field(default_factory=list)
    media_kinds: list[str] = field(default_factory=list)
    langs: list[str] = field(default_factory=list)
    account_search: str | None = None
    account_name: str | None = None
    hashtag: str | None = None

    def has_entity_lock(self) -> bool:
        return bool(self.account_name or self.hashtag)

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        for t in self.tweet_types:
            chips.append(("tweet_type", f"type={t}"))
        for m in self.media_kinds:
            chips.append(("media_kind", f"media={m}"))
        for lang in self.langs:
            chips.append(("lang", f"lang={lang}"))
        if self.account_search:
            chips.append(("account_search", f"search: {self.account_search}"))
        if self.account_name:
            chips.append(("account_name", f"account: @{self.account_name}"))
        if self.hashtag:
            chips.append(("hashtag", f"#{self.hashtag}"))
        return chips

    def filter_digest(self) -> str:
        payload = {
            "year_start": self.year_start,
            "year_end": self.year_end,
            "tweet_types": sorted(self.tweet_types),
            "media_kinds": sorted(self.media_kinds),
            "langs": sorted(self.langs),
            "account_search": self.account_search,
            "account_name": self.account_name,
            "hashtag": self.hashtag,
        }
        blob = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def clear_field(self, field_name: str) -> None:
        if field_name == "year_range":
            self.year_start = None
            self.year_end = None
        elif field_name == "tweet_type":
            self.tweet_types = []
        elif field_name == "media_kind":
            self.media_kinds = []
        elif field_name == "lang":
            self.langs = []
        elif field_name == "account_search":
            self.account_search = None
        elif field_name == "account_name":
            self.account_name = None
        elif field_name == "hashtag":
            self.hashtag = None


def has_table(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = conn.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'twitter' AND table_name = ?
        """,
        [table],
    ).fetchone()
    return row is not None and row[0] > 0


def table_row_count(conn: duckdb.DuckDBPyConnection, table: str) -> int:
    if not has_table(conn, table):
        return 0
    row = conn.execute(f"SELECT count(*)::BIGINT FROM twitter.{table}").fetchone()
    return int(row[0]) if row else 0


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def _tweet_where(f: FilterState, alias: str = "t") -> tuple[str, list[Any]]:
    prefix = f"{alias}."
    clauses: list[str] = []
    params: list[Any] = []

    if f.year_start is not None:
        clauses.append(f"{prefix}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{prefix}year <= ?")
        params.append(f.year_end)
    if f.tweet_types:
        placeholders = ", ".join("?" for _ in f.tweet_types)
        clauses.append(f"{prefix}tweet_type IN ({placeholders})")
        params.extend(f.tweet_types)
    if f.media_kinds:
        placeholders = ", ".join("?" for _ in f.media_kinds)
        clauses.append(f"{prefix}media_kind IN ({placeholders})")
        params.extend(f.media_kinds)
    if f.langs:
        placeholders = ", ".join("?" for _ in f.langs)
        clauses.append(f"{prefix}lang IN ({placeholders})")
        params.extend(f.langs)
    if f.account_search:
        clauses.append(f"""(
                contains(lower({prefix}full_text), lower(?))
                OR exists (
                    SELECT 1 FROM twitter.tweet_mentions m
                    WHERE m.tweet_id = {prefix}tweet_id
                      AND contains(lower(m.screen_name), lower(?))
                )
            )""")
        params.extend([f.account_search, f.account_search])
    if f.account_name:
        acct = f.account_name.lower().lstrip("@")
        clauses.append(f"""(
                lower({prefix}in_reply_to_screen_name) = ?
                OR exists (
                    SELECT 1 FROM twitter.tweet_mentions m
                    WHERE m.tweet_id = {prefix}tweet_id
                      AND lower(m.screen_name) = ?
                )
            )""")
        params.extend([acct, acct])
    if f.hashtag:
        tag = f.hashtag.lower().lstrip("#")
        clauses.append(f"""exists (
                SELECT 1 FROM twitter.tweet_hashtags h
                WHERE h.tweet_id = {prefix}tweet_id AND lower(h.hashtag) = ?
            )""")
        params.append(tag)

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT AS min_year,
            max(year)::INT AS max_year,
            min(ts_utc)::DATE AS first_day,
            max(ts_utc)::DATE AS last_day
        FROM twitter.tweets
        """).fetchone()
    assert row is not None
    min_year = row[0] if row[0] is not None else 2010
    max_year = row[1] if row[1] is not None else 2026
    tweet_types = conn.execute(
        "SELECT DISTINCT tweet_type FROM twitter.tweets ORDER BY 1"
    ).fetchall()
    media_kinds = conn.execute(
        "SELECT DISTINCT media_kind FROM twitter.tweets ORDER BY 1"
    ).fetchall()
    langs = conn.execute(
        "SELECT DISTINCT lang FROM twitter.tweets WHERE lang IS NOT NULL ORDER BY 1"
    ).fetchall()
    followers = conn.execute(
        "SELECT count(*)::BIGINT FROM twitter.followers"
    ).fetchone()
    following = conn.execute(
        "SELECT count(*)::BIGINT FROM twitter.following"
    ).fetchone()
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "tweet_types": [r[0] for r in tweet_types],
        "media_kinds": [r[0] for r in media_kinds],
        "langs": [r[0] for r in langs],
        "n_followers": followers[0] if followers else 0,
        "n_following": following[0] if following else 0,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    tweet_types: list[str],
    media_kinds: list[str],
    langs: list[str],
    account_search: str = "",
    account_name: str | None = None,
    hashtag: str | None = None,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    search = account_search.strip() or None
    return FilterState(
        year_start=ys,
        year_end=ye,
        tweet_types=tweet_types,
        media_kinds=media_kinds,
        langs=langs,
        account_search=search,
        account_name=account_name,
        hashtag=hashtag,
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
    min_row = conn.execute("SELECT min(year)::INT FROM twitter.tweets").fetchone()
    assert min_row is not None
    min_year = min_row[0]
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
        tweet_types=list(f.tweet_types),
        media_kinds=list(f.media_kinds),
        langs=list(f.langs),
        account_search=f.account_search,
        account_name=f.account_name,
        hashtag=f.hashtag,
    )
    prev = _scoreboard_row(conn, prev_f)
    current["window"] = "current"
    prev["window"] = f"previous ({prev_start}–{prev_end})"
    return pd.concat([current, prev], ignore_index=True)


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _tweet_where(f)
    like_where, like_params = _likes_where(f)
    dm_where, dm_params = _dm_where(f)
    sql = f"""
        SELECT
            count(*)::BIGINT AS tweets,
            count(DISTINCT t.ts_utc::DATE)::BIGINT AS active_days,
            count(*) FILTER (WHERE t.tweet_type = 'reply')::BIGINT AS replies,
            count(*) FILTER (WHERE t.tweet_type = 'retweet')::BIGINT AS retweets,
            count(*) FILTER (WHERE t.tweet_type = 'quote')::BIGINT AS quotes,
            count(*) FILTER (WHERE t.tweet_type = 'original')::BIGINT AS originals,
            round(
                100.0 * avg(
                    CASE WHEN t.tweet_type = 'reply' THEN 1.0 ELSE 0.0 END
                ),
                1
            ) AS reply_pct,
            min(t.ts_utc)::DATE AS first_day,
            max(t.ts_utc)::DATE AS last_day,
            (SELECT count(*)::BIGINT FROM twitter.likes l WHERE {like_where}) AS likes_given,
            (SELECT count(*)::BIGINT FROM twitter.dm_messages d WHERE {dm_where}) AS dm_messages
        FROM twitter.tweets t
        WHERE {where}
    """
    return _query_df(conn, sql, params + like_params + dm_params)


def _likes_where(f: FilterState) -> tuple[str, list[Any]]:
    if f.year_start is None and f.year_end is None:
        return "1=1", []
    clauses: list[str] = []
    params: list[Any] = []
    if f.year_start is not None:
        clauses.append("year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append("year <= ?")
        params.append(f.year_end)
    return " AND ".join(clauses) if clauses else "1=1", params


def _dm_where(f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if f.year_start is not None:
        clauses.append("year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append("year <= ?")
        params.append(f.year_end)
    return " AND ".join(clauses) if clauses else "1=1", params


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _tweet_where(f)
    sql = f"""
        WITH daily AS (
            SELECT t.ts_local::DATE AS day, count(*)::BIGINT AS tweets
            FROM twitter.tweets t
            WHERE {where}
            GROUP BY 1
        ),
        ranked AS (
            SELECT
                day,
                tweets,
                day - (row_number() OVER (ORDER BY day))::INT AS grp
            FROM daily
        ),
        streaks AS (
            SELECT grp, count(*) AS streak_days, sum(tweets) AS streak_tweets
            FROM ranked
            GROUP BY grp
        ),
        busiest AS (
            SELECT day, tweets
            FROM daily
            ORDER BY tweets DESC
            LIMIT 1
        )
        SELECT
            (SELECT max(streak_days) FROM streaks) AS longest_streak_days,
            (SELECT max(streak_tweets) FROM streaks) AS longest_streak_tweets,
            (SELECT day FROM busiest) AS busiest_day,
            (SELECT tweets FROM busiest) AS busiest_day_tweets
    """
    return _query_df(conn, sql, params)


def top_mentions(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _tweet_where(f, alias="t")
    params.append(limit)
    sql = f"""
        SELECT
            lower(m.screen_name) AS account,
            count(*)::BIGINT AS mentions
        FROM twitter.tweet_mentions m
        JOIN twitter.tweets t ON t.tweet_id = m.tweet_id
        WHERE {where}
        GROUP BY 1
        ORDER BY mentions DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def top_replied_to(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _tweet_where(f)
    params.append(limit)
    sql = f"""
        SELECT
            lower(in_reply_to_screen_name) AS account,
            count(*)::BIGINT AS replies
        FROM twitter.tweets t
        WHERE {where}
          AND in_reply_to_screen_name IS NOT NULL
        GROUP BY 1
        ORDER BY replies DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def top_hashtags(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _tweet_where(f, alias="t")
    params.append(limit)
    sql = f"""
        SELECT
            lower(h.hashtag) AS hashtag,
            count(*)::BIGINT AS uses
        FROM twitter.tweet_hashtags h
        JOIN twitter.tweets t ON t.tweet_id = h.tweet_id
        WHERE {where}
        GROUP BY 1
        ORDER BY uses DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def top_liked_accounts(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _likes_where(f)
    params.append(limit)
    sql = f"""
        WITH parsed AS (
            SELECT
                lower(
                    coalesce(
                        nullif(
                            regexp_extract(
                                expanded_url,
                                'twitter\\.com/([^/]+)/',
                                1
                            ),
                            ''
                        ),
                        nullif(
                            regexp_extract(full_text, '^RT @([^ :]+)', 1),
                            ''
                        ),
                        nullif(
                            regexp_extract(full_text, '@([^ :]+)', 1),
                            ''
                        )
                    )
                ) AS account
            FROM twitter.likes
            WHERE {where}
        )
        SELECT account, count(*)::BIGINT AS likes
        FROM parsed
        WHERE account IS NOT NULL
          AND account NOT IN ('i', 'intent', 'home', 'search')
        GROUP BY 1
        ORDER BY likes DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def tweet_type_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _tweet_where(f)
    sql = f"""
        SELECT tweet_type, count(*)::BIGINT AS tweets
        FROM twitter.tweets t
        WHERE {where}
        GROUP BY 1
        ORDER BY tweets DESC
    """
    return _query_df(conn, sql, params)


def client_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _tweet_where(f)
    sql = f"""
        SELECT coalesce(client, 'unknown') AS client, count(*)::BIGINT AS tweets
        FROM twitter.tweets t
        WHERE {where}
        GROUP BY 1
        ORDER BY tweets DESC
        LIMIT 15
    """
    return _query_df(conn, sql, params)


def media_mix(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    exclude_none: bool = True,
) -> pd.DataFrame:
    where, params = _tweet_where(f)
    extra = " AND media_kind <> 'none'" if exclude_none else ""
    sql = f"""
        SELECT media_kind, count(*)::BIGINT AS tweets
        FROM twitter.tweets t
        WHERE {where}{extra}
        GROUP BY 1
        ORDER BY tweets DESC
    """
    return _query_df(conn, sql, params)


def discovery_vs_repeats(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _tweet_where(f, alias="t")
    sql = f"""
        WITH engaged AS (
            SELECT lower(m.screen_name) AS account, t.year
            FROM twitter.tweet_mentions m
            JOIN twitter.tweets t ON t.tweet_id = m.tweet_id
            WHERE {where}
            UNION ALL
            SELECT lower(t.in_reply_to_screen_name) AS account, t.year
            FROM twitter.tweets t
            WHERE {where} AND t.in_reply_to_screen_name IS NOT NULL
        ),
        first_seen AS (
            SELECT account, min(year) AS first_year
            FROM engaged
            WHERE account IS NOT NULL AND account <> ''
            GROUP BY 1
        ),
        window_accounts AS (
            SELECT DISTINCT account, year
            FROM engaged
            WHERE account IS NOT NULL AND account <> ''
        )
        SELECT
            count(*) FILTER (WHERE w.year = f.first_year)::BIGINT AS new_accounts,
            count(*) FILTER (WHERE w.year > f.first_year)::BIGINT AS repeat_accounts
        FROM window_accounts w
        JOIN first_seen f ON w.account = f.account
    """
    return _query_df(conn, sql, params + params)


def monthly_volume(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _tweet_where(f)
    sql = f"""
        SELECT year, month, count(*)::BIGINT AS tweets
        FROM twitter.tweets t
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    df = _query_df(conn, sql, params)
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def monthly_by_type(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _tweet_where(f)
    sql = f"""
        SELECT year, month, tweet_type, count(*)::BIGINT AS tweets
        FROM twitter.tweets t
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """
    df = _query_df(conn, sql, params)
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def likes_by_year(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _likes_where(f)
    sql = f"""
        SELECT year, count(*)::BIGINT AS likes
        FROM twitter.likes
        WHERE {where} AND year IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)


def language_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _tweet_where(f)
    sql = f"""
        SELECT coalesce(lang, 'unknown') AS lang, count(*)::BIGINT AS tweets
        FROM twitter.tweets t
        WHERE {where}
        GROUP BY 1
        ORDER BY tweets DESC
        LIMIT 12
    """
    return _query_df(conn, sql, params)


def circadian_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _tweet_where(f)
    sql = f"""
        SELECT
            dayofweek(t.ts_local) AS dow,
            hour(t.ts_local) AS hour,
            count(*)::BIGINT AS tweets
        FROM twitter.tweets t
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    return _query_df(conn, sql, params)


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _tweet_where(f)
    sql = f"""
        SELECT t.ts_local::DATE AS day, count(*)::BIGINT AS tweets
        FROM twitter.tweets t
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)


def bump_chart_accounts(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    top_n: int = 8,
) -> pd.DataFrame:
    where, params = _tweet_where(f, alias="t")
    params.append(top_n)
    sql = f"""
        WITH yearly AS (
            SELECT t.year, lower(m.screen_name) AS account, count(*)::BIGINT AS mentions
            FROM twitter.tweet_mentions m
            JOIN twitter.tweets t ON t.tweet_id = m.tweet_id
            WHERE {where}
            GROUP BY 1, 2
        ),
        top_accounts AS (
            SELECT account
            FROM yearly
            GROUP BY 1
            ORDER BY sum(mentions) DESC
            LIMIT ?
        ),
        ranked AS (
            SELECT
                y.year,
                y.account,
                y.mentions,
                row_number() OVER (PARTITION BY y.year ORDER BY y.mentions DESC) AS rank
            FROM yearly y
            INNER JOIN top_accounts a ON y.account = a.account
        )
        SELECT year, account, mentions, rank
        FROM ranked
        ORDER BY year, rank
    """
    return _query_df(conn, sql, params)


def account_reply_scatter(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _tweet_where(f)
    sql = f"""
        SELECT
            lower(in_reply_to_screen_name) AS account,
            count(*)::BIGINT AS tweets,
            round(
                100.0 * avg(
                    CASE WHEN tweet_type = 'reply' THEN 1.0 ELSE 0.0 END
                ),
                1
            ) AS reply_pct,
            max(ts_utc)::DATE AS last_day
        FROM twitter.tweets t
        WHERE {where}
          AND in_reply_to_screen_name IS NOT NULL
        GROUP BY 1
        ORDER BY tweets DESC
    """
    return _query_df(conn, sql, params)


def forgotten_accounts(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_mentions: int = 20,
    silent_years: int = 2,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _tweet_where(f, alias="t")
    query_params = params + params + [min_mentions, silent_years, limit]
    sql = f"""
        WITH engaged AS (
            SELECT lower(m.screen_name) AS account, max(t.ts_utc) AS last_ts,
                   count(*)::BIGINT AS mentions
            FROM twitter.tweet_mentions m
            JOIN twitter.tweets t ON t.tweet_id = m.tweet_id
            WHERE {where}
            GROUP BY 1
            UNION ALL
            SELECT lower(t.in_reply_to_screen_name) AS account, max(t.ts_utc) AS last_ts,
                   count(*)::BIGINT AS replies
            FROM twitter.tweets t
            WHERE {where} AND t.in_reply_to_screen_name IS NOT NULL
            GROUP BY 1
        ),
        combined AS (
            SELECT account, max(last_ts) AS last_ts, sum(mentions) AS engagements
            FROM engaged
            WHERE account IS NOT NULL AND account <> ''
            GROUP BY 1
            HAVING sum(mentions) >= ?
        )
        SELECT account, engagements, last_ts::DATE AS last_day
        FROM combined
        WHERE last_ts < current_timestamp - (? * INTERVAL '1 year')
        ORDER BY engagements DESC
        LIMIT ?
    """
    return _query_df(conn, sql, query_params)


def comeback_accounts(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 2,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _tweet_where(f, alias="t")
    query_params = params + params + [silent_years, limit]
    sql = f"""
        WITH engaged AS (
            SELECT lower(m.screen_name) AS account, t.ts_utc
            FROM twitter.tweet_mentions m
            JOIN twitter.tweets t ON t.tweet_id = m.tweet_id
            WHERE {where}
            UNION ALL
            SELECT lower(t.in_reply_to_screen_name) AS account, t.ts_utc
            FROM twitter.tweets t
            WHERE {where} AND t.in_reply_to_screen_name IS NOT NULL
        ),
        window_span AS (
            SELECT account, min(ts_utc) AS first_in_window, max(ts_utc) AS last_in_window,
                   count(*)::BIGINT AS window_engagements
            FROM engaged
            WHERE account IS NOT NULL AND account <> ''
            GROUP BY 1
        ),
        prior AS (
            SELECT e.account, max(e.ts_utc) AS last_before
            FROM engaged e
            JOIN window_span w ON e.account = w.account
            WHERE e.ts_utc < w.first_in_window
            GROUP BY 1
        )
        SELECT
            w.account,
            w.window_engagements,
            p.last_before::DATE AS last_before,
            w.first_in_window::DATE AS returned_on
        FROM window_span w
        INNER JOIN prior p ON w.account = p.account
        WHERE p.last_before < w.first_in_window - (? * INTERVAL '1 year')
        ORDER BY w.window_engagements DESC
        LIMIT ?
    """
    return _query_df(conn, sql, query_params)


def hashtag_account_treemap(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 40,
) -> pd.DataFrame:
    where, params = _tweet_where(f, alias="t")
    params.append(limit)
    sql = f"""
        SELECT
            lower(h.hashtag) AS hashtag,
            lower(m.screen_name) AS account,
            count(*)::BIGINT AS tweets
        FROM twitter.tweet_hashtags h
        JOIN twitter.tweets t ON t.tweet_id = h.tweet_id
        JOIN twitter.tweet_mentions m ON m.tweet_id = t.tweet_id
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY tweets DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def dm_volume(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _dm_where(f)
    sql = f"""
        SELECT year, month, count(*)::BIGINT AS messages
        FROM twitter.dm_messages
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    df = _query_df(conn, sql, params)
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def top_dm_conversations(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 15,
) -> pd.DataFrame:
    where, params = _dm_where(f)
    params.append(limit)
    sql = f"""
        SELECT conversation_id, count(*)::BIGINT AS messages
        FROM twitter.dm_messages
        WHERE {where}
        GROUP BY 1
        ORDER BY messages DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def network_snapshot(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    row = conn.execute("""
        SELECT
            (SELECT count(*)::BIGINT FROM twitter.followers) AS followers,
            (SELECT count(*)::BIGINT FROM twitter.following) AS following
        """).fetchone()
    assert row is not None
    return pd.DataFrame(
        [
            {"metric": "followers (snapshot)", "count": row[0]},
            {"metric": "following (snapshot)", "count": row[1]},
        ]
    )


def narrative_context(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> dict[str, Any]:
    score = scoreboard(conn, f).iloc[0].to_dict()
    streak = streak_stats(conn, f).iloc[0].to_dict()
    discovery = discovery_vs_repeats(conn, f)
    top_m = top_mentions(conn, f, limit=8)
    top_h = top_hashtags(conn, f, limit=8)
    forgotten = forgotten_accounts(conn, f, limit=5)
    comebacks = comeback_accounts(conn, f, limit=5)
    return {
        "filter_digest": f.filter_digest(),
        "filters": f.chip_labels(),
        "scoreboard": score,
        "streak": streak,
        "discovery": discovery.to_dict(orient="records"),
        "top_mentions": top_m.to_dict(orient="records"),
        "top_hashtags": top_h.to_dict(orient="records"),
        "forgotten": forgotten.to_dict(orient="records"),
        "comebacks": comebacks.to_dict(orient="records"),
    }
