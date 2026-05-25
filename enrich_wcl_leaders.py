"""Pull WCL reports from individual LP raid leaders' personal feeds.

Complements enrich_wcl.py — that only sees logs tagged to guild 819778. Many
LP raids are uploaded under personal accounts without the guild tag, so we
miss them. This script queries each known leader character's recent reports
and fetches rosters for any not already in the DB.

After running, /api/events will pick up new gap-fill candidates automatically
via the existing synthesis pipeline (filters + leader matching apply).

Run locally with DATABASE_URL + WCL_CLIENT_ID + WCL_CLIENT_SECRET set, or
deploy as a Railway one-off / scheduled job.
"""

import os
import json
import sys
import time
from datetime import datetime, timezone

import psycopg

import db
import wcl


# (character_name, server_slug, region). Slugs are lowercased server names.
LEADER_CHARACTERS: list[tuple[str, str, str]] = [
    ("Piian",       "silvermoon",  "EU"),  # Piian's main
    ("Ragz",        "arathor",     "EU"),  # Ragz's main
    ("Gryphandrus", "arathor",     "EU"),  # Gryph's main
    ("Mêlódý",      "frostwolf",   "EU"),  # Melody's main
    ("Karviainen",  "arathor",     "EU"),  # Rezn0r's main
    ("Tarp",        "blackmoore",  "EU"),  # In every Ragz raid we have
]


REQUEST_DELAY = float(os.environ.get("WCL_REQUEST_DELAY_SEC", "0.4"))
MATCH_WINDOW_SEC = int(os.environ.get("WCL_MATCH_WINDOW_SEC", str(3 * 3600)))


def find_matching_event(conn: psycopg.Connection, start_unix_sec: int) -> str | None:
    lo = start_unix_sec - MATCH_WINDOW_SEC
    hi = start_unix_sec + MATCH_WINDOW_SEC
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT raid_id
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
    raid_id: str | None,
    roster: list[dict],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wcl_reports (code, start_time_ms, end_time_ms, title, zone_name, owner_name,
                                      guild_id, raid_id, is_lp, roster)
            VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, TRUE, %s)
            ON CONFLICT (code) DO NOTHING
            """,
            (code, start_ms, end_ms, title, zone, owner, raid_id, json.dumps(roster)),
        )
    conn.commit()


def main() -> None:
    client = wcl.WclClient()
    conn = db.connect()
    db.ensure_schema(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT code FROM wcl_reports")
        existing = {r["code"] for r in cur.fetchall()}
    print(f"DB already has {len(existing)} reports", flush=True)

    fetched = 0
    skipped = 0
    failed = 0
    seen_codes: set[str] = set()

    for char_name, server, region in LEADER_CHARACTERS:
        print(f"\n=== {char_name}-{server} ({region}) ===", flush=True)
        try:
            reports = wcl.fetch_character_reports(client, char_name, server, region, limit=100)
        except Exception as exc:
            print(f"  failed to list reports: {exc}", flush=True)
            continue
        print(f"  {len(reports)} reports on this character's feed", flush=True)
        time.sleep(REQUEST_DELAY)

        for r in reports:
            code = r["code"]
            if code in existing or code in seen_codes:
                skipped += 1
                continue
            seen_codes.add(code)
            start_ms = int(r["startTime"])
            start_sec = start_ms // 1000

            try:
                detail = wcl.fetch_report_roster(client, code)
            except Exception as exc:
                print(f"  failed roster {code}: {exc}", flush=True)
                failed += 1
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
                raid_id=raid_id,
                roster=roster,
            )
            fetched += 1
            dt = datetime.fromtimestamp(start_sec, timezone.utc).strftime("%Y-%m-%d %H:%M")
            link = f"-> {raid_id}" if raid_id else "(gap-fill)"
            print(f"  + {code}  {dt}  {len(roster):2d}p  {link}  {(r.get('title') or '')[:55]}", flush=True)
            time.sleep(REQUEST_DELAY)

    print(f"\nDone. fetched={fetched} skipped={skipped} failed={failed}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
