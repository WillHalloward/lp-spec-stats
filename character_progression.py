"""Per-character first-kill aggregation.

A character's first kill of a boss/difficulty is derived from WCL reports they
appeared in (via playerDetails roster). Only WCL-logged kills count — raid-helper
signups without a matched WCL report don't tell us who actually killed what.
"""

import psycopg

import boss_progression
from boss_progression import DIFFICULTY_NAME
from wcl_synthesis import all_excluded_codes, lp_zone_names


def first_kills(conn: psycopg.Connection, character_names: list[str]) -> list[dict]:
    """For each LP boss × difficulty, the earliest timestamp at which one of the
    given character names was in a report that scored a kill."""
    names_lower = sorted({(n or "").lower() for n in character_names if n})
    if not names_lower:
        return []

    # Only count kills on bosses we consider "real LP raid content" — reuse the
    # same heuristic as the guild-wide progression view.
    agg = boss_progression.aggregate(conn)
    valid_eids = {b["encounterID"] for b in agg["bosses"]}
    if not valid_eids:
        return []

    # Which reports the character appeared in is answered from `ilvl_summary`,
    # whose keys are the report's player names. Testing those keys reads a
    # ~400 kB column instead of dragging 44 MB of `player_details` into Python
    # to do the same filtering by hand.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.code, r.fights, r.start_time_ms
              FROM wcl_reports r
             WHERE r.fights IS NOT NULL
               AND r.ilvl_summary IS NOT NULL
               AND r.zone_name = ANY(%s)
               AND r.code != ALL(%s)
               AND EXISTS (
                     SELECT 1 FROM jsonb_object_keys(r.ilvl_summary) AS k
                      WHERE lower(k) = ANY(%s)
                   )
            """,
            (lp_zone_names(conn), list(all_excluded_codes(conn)), names_lower),
        )
        rows = cur.fetchall()

    bosses: dict[tuple[int, str], dict] = {}
    for r in rows:
        fights_blob = r["fights"] or {}
        report_start_ms = fights_blob.get("report_start_ms") or r["start_time_ms"]
        for f in fights_blob.get("fights") or []:
            if not f.get("kill"):
                continue
            eid = f.get("encounterID") or 0
            if eid <= 0 or eid not in valid_eids:
                continue
            diff = DIFFICULTY_NAME.get(f.get("difficulty"))
            if not diff or diff == "LFR":
                continue
            kill_ms = (f.get("startTime") or 0) + (report_start_ms or 0)
            key = (eid, diff)
            existing = bosses.get(key)
            if existing is None or kill_ms < existing["first_kill_ms"]:
                bosses[key] = {
                    "encounterID": eid,
                    "name": f.get("name"),
                    "difficulty": diff,
                    "first_kill_ms": kill_ms,
                    "report_code": r["code"],
                    "fight_id": f.get("id"),
                }

    return sorted(bosses.values(), key=lambda b: (b["first_kill_ms"], b["encounterID"], b["difficulty"]))
