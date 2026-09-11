"""Postgres data layer for archived raid-helper events.

DATABASE_URL is provided by Railway when Postgres is attached to the service.
"""

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable, Iterator

import psycopg
from psycopg.rows import dict_row


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    raid_id            TEXT PRIMARY KEY,
    unixtime           BIGINT NOT NULL,
    leader_id          TEXT,
    title              TEXT,
    data               JSONB NOT NULL,
    archived_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_refreshed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS events_unixtime_idx ON events(unixtime);

-- Warcraft Logs reports, used to gap-fill events that were deleted from raid-helper
-- before the archiver caught them.
CREATE TABLE IF NOT EXISTS wcl_reports (
    code               TEXT PRIMARY KEY,           -- WCL report code (e.g. "abc123")
    start_time_ms      BIGINT NOT NULL,            -- WCL uses millisecond epoch
    end_time_ms        BIGINT,
    title              TEXT,
    zone_name          TEXT,
    owner_name         TEXT,                       -- log uploader
    guild_id           INTEGER,                    -- WCL guild id, if tagged
    raid_id            TEXT REFERENCES events(raid_id) ON DELETE SET NULL,
    is_lp              BOOLEAN NOT NULL DEFAULT TRUE,
    roster             JSONB NOT NULL,             -- masterData.actors[] payload
    difficulty         TEXT,                       -- Mythic / Heroic / Normal / LFR (from boss fights)
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS wcl_reports_start_idx ON wcl_reports(start_time_ms);
CREATE INDEX IF NOT EXISTS wcl_reports_raid_idx ON wcl_reports(raid_id);
ALTER TABLE wcl_reports ADD COLUMN IF NOT EXISTS difficulty TEXT;
ALTER TABLE wcl_reports ADD COLUMN IF NOT EXISTS player_details JSONB;
ALTER TABLE wcl_reports ADD COLUMN IF NOT EXISTS fights JSONB;
-- Slim {name: {min, max}} ilvl digest of player_details. The full blobs carry
-- every combatant's gear and talents (~70 MB across the table); the dashboard
-- only ever wants these three fields, so they are kept ready to read.
ALTER TABLE wcl_reports ADD COLUMN IF NOT EXISTS ilvl_summary JSONB;

-- Manual override tables. These let an admin tweak categorization decisions the
-- auto-detection got wrong (e.g. events whose titles don't say the difficulty)
-- without having to edit code. All fields are nullable — set only what you want
-- to override; everything else falls through to the auto-detected value.
CREATE TABLE IF NOT EXISTS event_overrides (
    raid_id        TEXT PRIMARY KEY,
    difficulty     TEXT,                          -- Mythic / Heroic / Normal / LFR / Other
    series_suffix  TEXT,                          -- e.g. "Mythic" or "Heroic" — full series label is leader + this
    excluded       BOOLEAN NOT NULL DEFAULT FALSE,
    wcl_codes      TEXT[] NOT NULL DEFAULT '{}', -- additional WCL report codes to manually link to this event
    notes          TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wcl_report_overrides (
    code             TEXT PRIMARY KEY,
    excluded         BOOLEAN NOT NULL DEFAULT FALSE,
    forced_raid_id   TEXT,                       -- pin this report to a specific event when time-window match missed
    notes            TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url


def connect() -> psycopg.Connection:
    """Open a one-off connection. Used by the cron scripts, which run once and exit.

    Long-lived processes (the web service) should use `session()` instead so they
    reuse pooled connections rather than paying the handshake on every request.
    """
    return psycopg.connect(database_url(), row_factory=dict_row)


# Connection pool, opened by the web service at startup (see `init_pool`). The
# cron scripts leave it as None and fall back to a fresh connection per call.
_pool = None


def init_pool(min_size: int = 1, max_size: int = 4) -> None:
    """Open the shared connection pool. Idempotent; safe to call if DATABASE_URL
    is unset (it simply does nothing and `session()` keeps its fallback)."""
    global _pool
    if _pool is not None or not os.environ.get("DATABASE_URL"):
        return
    from psycopg_pool import ConnectionPool

    _pool = ConnectionPool(
        database_url(),
        min_size=min_size,
        max_size=max_size,
        kwargs={"row_factory": dict_row},
        # Railway's proxy drops idle connections; check before handing one out so
        # a stale socket surfaces as a reconnect rather than a failed request.
        check=ConnectionPool.check_connection,
        timeout=10,
        open=True,
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def session() -> Iterator[psycopg.Connection]:
    """A connection for the duration of one request.

    Pooled when `init_pool()` has run, otherwise a plain connection. Both forms
    commit on clean exit and roll back on exception, so callers can't tell which
    one they got.
    """
    if _pool is None:
        with connect() as conn:
            yield conn
        return
    with _pool.connection() as conn:
        yield conn


def data_version(conn: psycopg.Connection) -> tuple:
    """A cheap fingerprint of everything the read APIs derive from.

    The archiver rewrites `last_refreshed_at` on every pass, so this changes
    exactly once per cron run; admin edits move an override table's `updated_at`.
    Row counts are in there too because deleting an override lowers no maximum.
    Used as the cache key in serve.py — one round trip instead of several
    seconds of aggregation.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT (SELECT max(last_refreshed_at) FROM events)               AS ev,
                   (SELECT count(*)               FROM events)               AS ev_n,
                   (SELECT max(fetched_at)        FROM wcl_reports)          AS wcl,
                   (SELECT count(*)               FROM wcl_reports)          AS wcl_n,
                   (SELECT max(updated_at)        FROM event_overrides)      AS eo,
                   (SELECT count(*)               FROM event_overrides)      AS eo_n,
                   (SELECT max(updated_at)        FROM wcl_report_overrides) AS wo,
                   (SELECT count(*)               FROM wcl_report_overrides) AS wo_n
            """
        )
        r = cur.fetchone()
    return tuple(r[k] for k in ("ev", "ev_n", "wcl", "wcl_n", "eo", "eo_n", "wo", "wo_n"))


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()
    backfill_ilvl_summary(conn)


ILVL_SUMMARY_SQL = """
    SELECT jsonb_object_agg(e->>'name', jsonb_build_object(
               'min', e->'minItemLevel', 'max', e->'maxItemLevel'))
      FROM jsonb_array_elements(
               COALESCE(pd->'tanks',   '[]'::jsonb)
            || COALESCE(pd->'healers', '[]'::jsonb)
            || COALESCE(pd->'dps',     '[]'::jsonb)) AS e
     WHERE e->>'name' IS NOT NULL AND e->'maxItemLevel' IS NOT NULL
"""


def backfill_ilvl_summary(conn: psycopg.Connection) -> int:
    """Fill ilvl_summary for reports that have player_details but no digest yet.

    Runs on startup and on every archiver pass; a no-op once caught up, since
    the writer fills the column as reports come in.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE wcl_reports r
               SET ilvl_summary = COALESCE((
                       WITH unwrapped AS (
                           SELECT COALESCE(r.player_details->'data'->'playerDetails',
                                           r.player_details->'playerDetails',
                                           r.player_details) AS pd
                       )
                       SELECT s.agg FROM unwrapped, LATERAL ({ILVL_SUMMARY_SQL}) AS s(agg)
                   ), '{{}}'::jsonb)
             WHERE r.player_details IS NOT NULL AND r.ilvl_summary IS NULL
            """
        )
        n = cur.rowcount
    conn.commit()
    if n:
        print(f"ilvl_summary backfilled for {n} reports", flush=True)
    return n


def upsert_event(conn: psycopg.Connection, event_data: dict, *, is_refresh: bool = False) -> None:
    """Insert or update one event. `event_data` is the full raid-helper event response."""
    raid_id = str(event_data["raidid"])
    unixtime = int(event_data["unixtime"])
    leader_id = event_data.get("leaderid")
    title = event_data.get("displayTitle") or event_data.get("title")

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (raid_id, unixtime, leader_id, title, data)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (raid_id) DO UPDATE SET
                unixtime = EXCLUDED.unixtime,
                leader_id = EXCLUDED.leader_id,
                title = EXCLUDED.title,
                data = EXCLUDED.data,
                last_refreshed_at = NOW()
            """,
            (raid_id, unixtime, leader_id, title, json.dumps(event_data)),
        )
    conn.commit()


def get_archived_ids(conn: psycopg.Connection) -> dict[str, int]:
    """Return {raid_id: unixtime} for everything already in the DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT raid_id, unixtime FROM events")
        return {r["raid_id"]: r["unixtime"] for r in cur.fetchall()}


def load_all_events(conn: psycopg.Connection) -> list[dict]:
    """Return every archived event's full data payload, ordered by unixtime."""
    with conn.cursor() as cur:
        cur.execute("SELECT data FROM events ORDER BY unixtime")
        return [r["data"] for r in cur.fetchall()]


def load_slim_events(conn: psycopg.Connection, event_fields, signup_fields) -> list[dict]:
    """Like load_all_events, but Postgres does the field selection.

    The stored payloads total ~11 MB and the dashboard reads a dozen fields out
    of them; projecting here means psycopg never decodes the rest. Field names
    come from the caller so the API's contract stays in one place.
    """
    ev_pairs = ", ".join(f"'{f}', data->'{f}'" for f in event_fields)
    su_pairs = ", ".join(f"'{f}', s->'{f}'" for f in signup_fields)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT jsonb_strip_nulls(jsonb_build_object({ev_pairs}))
                   || jsonb_build_object('signups', COALESCE((
                          SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object({su_pairs})))
                            FROM jsonb_array_elements(data->'signups') AS s
                      ), '[]'::jsonb)) AS data
              FROM events
             ORDER BY unixtime
            """
        )
        return [r["data"] for r in cur.fetchall()]


def count_events(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM events")
        return cur.fetchone()["n"]


def load_event_overrides(conn: psycopg.Connection) -> dict[str, dict]:
    """Return {raid_id: override_row} for all events with manual overrides."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM event_overrides")
        return {r["raid_id"]: dict(r) for r in cur.fetchall()}


def load_wcl_overrides(conn: psycopg.Connection) -> dict[str, dict]:
    """Return {code: override_row} for all WCL reports with manual overrides."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM wcl_report_overrides")
        return {r["code"]: dict(r) for r in cur.fetchall()}


def upsert_event_override(
    conn: psycopg.Connection,
    raid_id: str,
    *,
    difficulty: str | None,
    series_suffix: str | None,
    excluded: bool,
    wcl_codes: list[str],
    notes: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO event_overrides (raid_id, difficulty, series_suffix, excluded, wcl_codes, notes, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (raid_id) DO UPDATE SET
                difficulty = EXCLUDED.difficulty,
                series_suffix = EXCLUDED.series_suffix,
                excluded = EXCLUDED.excluded,
                wcl_codes = EXCLUDED.wcl_codes,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            """,
            (raid_id, difficulty, series_suffix, excluded, wcl_codes, notes),
        )
    conn.commit()


def delete_event_override(conn: psycopg.Connection, raid_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM event_overrides WHERE raid_id = %s", (raid_id,))
    conn.commit()


def upsert_wcl_override(
    conn: psycopg.Connection,
    code: str,
    *,
    excluded: bool,
    forced_raid_id: str | None,
    notes: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wcl_report_overrides (code, excluded, forced_raid_id, notes, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (code) DO UPDATE SET
                excluded = EXCLUDED.excluded,
                forced_raid_id = EXCLUDED.forced_raid_id,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            """,
            (code, excluded, forced_raid_id, notes),
        )
    conn.commit()


def delete_wcl_override(conn: psycopg.Connection, code: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM wcl_report_overrides WHERE code = %s", (code,))
    conn.commit()
