"""Incremental WCL enrichment — called from archive.py after each archive cycle.

Pulls recent reports from:
  - The guild feed (zone-tagged uploads)
  - Each known LP leader character's personal feed (untagged uploads)

For any code we haven't seen, fetches: basic metadata + roster + fights +
playerDetails (which gives us per-character spec + ilvl). All stored in the
single `wcl_reports` row so the rest of the pipeline (synthesis, boss
progression) picks it up automatically.

Safe to call repeatedly — idempotent (skips reports already in DB).
"""

import json
import os
import time
from collections import Counter

import psycopg

import db
import event_matching
import wcl
from wcl_synthesis import LEADER_CHARACTERS as LEADER_CHAR_LOOKUP


GUILD_ID = int(os.environ.get("WCL_GUILD_ID", "819778"))
# Same list as enrich_wcl_leaders.py — the raid leaders whose personal feeds
# pick up logs that aren't tagged with the guild.
LEADER_CHARACTERS: list[tuple[str, str, str]] = [
    ("Piian",       "silvermoon",  "EU"),
    ("Ragz",        "arathor",     "EU"),
    ("Gryphandrus", "arathor",     "EU"),
    ("Mêlódý",      "frostwolf",   "EU"),
    ("Karviainen",  "arathor",     "EU"),
    ("Tarp",        "blackmoore",  "EU"),
]
LEADER_FEED_LIMIT = int(os.environ.get("WCL_LEADER_FEED_LIMIT", "30"))

REQUEST_DELAY = float(os.environ.get("WCL_REQUEST_DELAY_SEC", "0.3"))
MATCH_WINDOW_SEC = int(os.environ.get("WCL_MATCH_WINDOW_SEC", str(3 * 3600)))
# If a report started within this window, re-fetch on every cycle to pick up
# late-arriving fights (live-logged raids stream as they happen).
REFRESH_WINDOW_SEC = int(os.environ.get("WCL_REFRESH_WINDOW_SEC", str(24 * 3600)))

DIFFICULTY_MAP = {
    1: "LFR", 17: "LFR",
    3: "Normal", 14: "Normal",
    4: "Heroic", 15: "Heroic",
    5: "Mythic", 16: "Mythic",
}


# Mains we consider authoritative for "this is leader X's raid" — taken from
# wcl_synthesis.LEADER_CHARACTERS (gap-fill leader detection) so the matcher
# and the gap-fill pipeline agree on which characters identify which leaders.
_LEADER_MAIN_NAMES: tuple[str, ...] = tuple(c for c, _ in LEADER_CHAR_LOOKUP.values())


def _find_matching_event(
    conn: psycopg.Connection,
    start_unix_sec: int,
    *,
    roster: list[dict] | None = None,
    wcl_difficulty: str | None = None,
) -> str | None:
    raid_id, _info = event_matching.find_matching_event(
        conn,
        start_unix_sec,
        roster=roster,
        wcl_difficulty=wcl_difficulty,
        match_window_sec=MATCH_WINDOW_SEC,
        leader_characters=_LEADER_MAIN_NAMES,
    )
    return raid_id


def _derive_difficulty(fights_payload: dict) -> str | None:
    counts: Counter = Counter()
    for f in (fights_payload or {}).get("fights") or []:
        if (f.get("encounterID") or 0) <= 0:
            continue
        d = DIFFICULTY_MAP.get(f.get("difficulty"))
        if d:
            counts[d] += 1
    return counts.most_common(1)[0][0] if counts else None


def _unwrap_player_details(pd):
    """WCL's playerDetails scalar nests under {data: {playerDetails: {...}}} sometimes.
    Unwrap until we find the tanks/healers/dps shape."""
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except Exception:
            return None
    while isinstance(pd, dict) and not any(k in pd for k in ("tanks", "healers", "dps")):
        if len(pd) != 1:
            break
        pd = next(iter(pd.values()))
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                return None
    return pd


def _enrich_one(
    conn: psycopg.Connection,
    client: wcl.WclClient,
    code: str,
    list_meta: dict,
    *,
    guild_id: int | None,
) -> bool:
    """Fetch + store one WCL report. Returns True if stored, False on failure."""
    try:
        roster_detail = wcl.fetch_report_roster(client, code)
    except Exception as exc:
        print(f"    {code} roster: {exc}", flush=True)
        return False
    time.sleep(REQUEST_DELAY)

    fights_payload: dict | None = None
    try:
        fights_payload = wcl.fetch_report_fights(client, code)
    except Exception as exc:
        print(f"    {code} fights: {exc}", flush=True)
    time.sleep(REQUEST_DELAY)

    player_details = None
    try:
        player_details = wcl.fetch_report_player_details(client, code)
        player_details = _unwrap_player_details(player_details)
    except Exception as exc:
        print(f"    {code} playerDetails: {exc}", flush=True)
    time.sleep(REQUEST_DELAY)

    start_ms = int(list_meta["startTime"])
    end_ms = int(list_meta["endTime"]) if list_meta.get("endTime") else None
    title = list_meta.get("title")
    zone = (list_meta.get("zone") or {}).get("name")
    owner = (list_meta.get("owner") or {}).get("name")
    roster = (roster_detail or {}).get("masterData", {}).get("actors") or []
    difficulty = _derive_difficulty(fights_payload) if fights_payload else None
    # Roster + difficulty feed into the matcher's scoring so we don't pick a
    # time-adjacent event that doesn't actually share players or difficulty.
    raid_id = _find_matching_event(
        conn, start_ms // 1000, roster=roster, wcl_difficulty=difficulty,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wcl_reports (
                code, start_time_ms, end_time_ms, title, zone_name, owner_name,
                guild_id, raid_id, is_lp, roster, difficulty, fights, player_details
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                fights = COALESCE(EXCLUDED.fights, wcl_reports.fights),
                player_details = COALESCE(EXCLUDED.player_details, wcl_reports.player_details),
                difficulty = COALESCE(EXCLUDED.difficulty, wcl_reports.difficulty),
                raid_id = COALESCE(EXCLUDED.raid_id, wcl_reports.raid_id)
            """,
            (
                code, start_ms, end_ms, title, zone, owner,
                guild_id, raid_id, json.dumps(roster), difficulty,
                json.dumps(fights_payload) if fights_payload else None,
                json.dumps(player_details) if player_details else None,
            ),
        )
    conn.commit()
    return True


def run(conn: psycopg.Connection) -> dict[str, int]:
    """Incremental WCL pull. Returns counts for logging."""
    try:
        client = wcl.WclClient()
    except KeyError:
        print("WCL credentials not set, skipping enrichment", flush=True)
        return {"new": 0, "skipped": 0, "failed": 0}

    # Gather candidate codes from both sources, keeping the listing-level metadata
    # so we don't have to re-fetch it later.
    candidates: dict[str, dict] = {}  # code -> list metadata
    sources: dict[str, str] = {}      # code -> "guild" or "leader-X" (for logging)

    try:
        guild_reports = wcl.list_guild_reports(client, GUILD_ID)
        for r in guild_reports:
            candidates.setdefault(r["code"], r)
            sources.setdefault(r["code"], "guild")
        print(f"  guild feed: {len(guild_reports)} reports", flush=True)
    except Exception as exc:
        print(f"  guild feed failed: {exc}", flush=True)

    for char_name, server, region in LEADER_CHARACTERS:
        try:
            reports = wcl.fetch_character_reports(client, char_name, server, region,
                                                   limit=LEADER_FEED_LIMIT)
            n_new = 0
            for r in reports:
                if r["code"] not in candidates:
                    candidates[r["code"]] = r
                    sources[r["code"]] = f"leader:{char_name}"
                    n_new += 1
            print(f"  {char_name} feed: {len(reports)} reports ({n_new} new to candidate set)",
                  flush=True)
        except Exception as exc:
            print(f"  {char_name} feed failed: {exc}", flush=True)

    with conn.cursor() as cur:
        cur.execute("SELECT code, start_time_ms FROM wcl_reports")
        existing = {r["code"]: r["start_time_ms"] for r in cur.fetchall()}

    now_ms = int(time.time() * 1000)
    refresh_cutoff_ms = now_ms - REFRESH_WINDOW_SEC * 1000

    new_codes: list[str] = []
    refresh_codes: list[str] = []
    for code in candidates:
        existing_start = existing.get(code)
        if existing_start is None:
            new_codes.append(code)
        elif existing_start >= refresh_cutoff_ms:
            # Recent / potentially still-live raid — refresh so we get late-arriving fights.
            refresh_codes.append(code)
    print(
        f"  {len(candidates)} unique codes seen, "
        f"{len(new_codes)} new + {len(refresh_codes)} refresh (last 24h)",
        flush=True,
    )

    fetched = 0
    refreshed = 0
    failed = 0
    for code in new_codes + refresh_codes:
        list_meta = candidates[code]
        gid = GUILD_ID if sources.get(code) == "guild" else None
        is_refresh = code in existing
        if _enrich_one(conn, client, code, list_meta, guild_id=gid):
            if is_refresh:
                refreshed += 1
                print(f"    ~ {code}  refresh  ({sources.get(code, '?')})", flush=True)
            else:
                fetched += 1
                print(f"    + {code}  new      ({sources.get(code, '?')})", flush=True)
        else:
            failed += 1

    return {
        "new": fetched,
        "refreshed": refreshed,
        "skipped": len(existing) - refreshed,
        "failed": failed,
    }
