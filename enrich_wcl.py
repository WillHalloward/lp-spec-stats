"""Fetch Warcraft Logs reports for the guild and store rosters in Postgres.

v1 scope:
  - Lists all reports for guild WCL_GUILD_ID (defaults to 819778 = Low Pressure).
  - For each report, fetches the full player roster (masterData.actors filtered to Player).
  - Stores in wcl_reports table.
  - Matches each report to an event by start-time proximity (±MATCH_WINDOW_SEC).
  - Idempotent: skips reports already in DB unless ARGV[1] == 'refresh'.

Run locally with DATABASE_URL set, or as a Railway one-off / scheduled job.
"""

import os
import sys
import json
import time
from datetime import datetime, timezone

import psycopg

import db
import wcl


GUILD_ID = int(os.environ.get("WCL_GUILD_ID", "819778"))
# Match a WCL report to a raid-helper event if their start times are within this window.
MATCH_WINDOW_SEC = int(os.environ.get("WCL_MATCH_WINDOW_SEC", str(3 * 3600)))
REQUEST_DELAY = float(os.environ.get("WCL_REQUEST_DELAY_SEC", "0.3"))


def find_matching_event(conn: psycopg.Connection, start_unix_sec: int) -> str | None:
    """Find a raid-helper event whose start time is within MATCH_WINDOW_SEC of the report."""
    lo = start_unix_sec - MATCH_WINDOW_SEC
    hi = start_unix_sec + MATCH_WINDOW_SEC
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT raid_id, unixtime
            FROM events
            WHERE unixtime BETWEEN %s AND %s
            ORDER BY ABS(unixtime - %s) ASC
            LIMIT 1
            """,
            (lo, hi, start_unix_sec),
        )
        row = cur.fetchone()
        return row["raid_id"] if row else None


def upsert_report(
    conn: psycopg.Connection,
    *,
    code: str,
    start_ms: int,
    end_ms: int | None,
    title: str | None,
    zone: str | None,
    owner: str | None,
    guild_id: int | None,
    raid_id: str | None,
    roster: list[dict],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wcl_reports (code, start_time_ms, end_time_ms, title, zone_name, owner_name,
                                      guild_id, raid_id, is_lp, roster)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (code) DO UPDATE SET
                start_time_ms = EXCLUDED.start_time_ms,
                end_time_ms = EXCLUDED.end_time_ms,
                title = EXCLUDED.title,
                zone_name = EXCLUDED.zone_name,
                owner_name = EXCLUDED.owner_name,
                guild_id = EXCLUDED.guild_id,
                raid_id = EXCLUDED.raid_id,
                roster = EXCLUDED.roster
            """,
            (code, start_ms, end_ms, title, zone, owner, guild_id, raid_id, json.dumps(roster)),
        )
    conn.commit()


def main() -> None:
    refresh = len(sys.argv) > 1 and sys.argv[1] == "refresh"

    client = wcl.WclClient()
    conn = db.connect()
    db.ensure_schema(conn)

    print(f"Listing reports for guild {GUILD_ID}...", flush=True)
    reports = wcl.list_guild_reports(client, GUILD_ID)
    print(f"  {len(reports)} reports in guild feed", flush=True)

    # Already-stored codes
    with conn.cursor() as cur:
        cur.execute("SELECT code FROM wcl_reports")
        existing = {r["code"] for r in cur.fetchall()}
    print(f"  {len(existing)} already in DB", flush=True)

    fetched = 0
    skipped = 0
    matched = 0
    unmatched = 0
    for r in reports:
        code = r["code"]
        if code in existing and not refresh:
            skipped += 1
            continue
        start_ms = int(r["startTime"])
        start_sec = start_ms // 1000

        try:
            detail = wcl.fetch_report_roster(client, code)
        except Exception as exc:
            print(f"  failed {code}: {exc}", flush=True)
            continue

        roster = detail.get("masterData", {}).get("actors", []) or []
        raid_id = find_matching_event(conn, start_sec)
        upsert_report(
            conn,
            code=code,
            start_ms=start_ms,
            end_ms=int(r["endTime"]) if r.get("endTime") else None,
            title=r.get("title"),
            zone=(r.get("zone") or {}).get("name"),
            owner=(r.get("owner") or {}).get("name"),
            guild_id=GUILD_ID,
            raid_id=raid_id,
            roster=roster,
        )
        fetched += 1
        if raid_id:
            matched += 1
        else:
            unmatched += 1
        dt = datetime.fromtimestamp(start_sec, timezone.utc).strftime("%Y-%m-%d %H:%M")
        link = f"-> {raid_id}" if raid_id else "(gap-fill)"
        print(f"  fetched {code}  {dt}  {len(roster):2d} players  {link}  {r.get('title','')[:60]}", flush=True)
        time.sleep(REQUEST_DELAY)

    print(f"\nDone. fetched={fetched} matched={matched} unmatched={unmatched} skipped={skipped}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
