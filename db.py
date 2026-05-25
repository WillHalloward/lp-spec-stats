"""Postgres data layer for archived raid-helper events.

DATABASE_URL is provided by Railway when Postgres is attached to the service.
"""

import json
import os
from datetime import datetime, timezone
from typing import Iterable

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
    return psycopg.connect(database_url(), row_factory=dict_row)


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


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
