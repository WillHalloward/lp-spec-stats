"""Per-character first-kill aggregation.

A character's first kill of a boss/difficulty is derived from WCL reports they
appeared in (via playerDetails roster). Only WCL-logged kills count — raid-helper
signups without a matched WCL report don't tell us who actually killed what.
"""

from typing import Any

import psycopg

import boss_progression
from boss_progression import DIFFICULTY_NAME
from wcl_synthesis import EXCLUDED_CODES


def _unwrap(pd: Any) -> Any:
    while isinstance(pd, dict) and not any(k in pd for k in ("tanks", "healers", "dps")):
        if len(pd) != 1:
            return pd
        pd = next(iter(pd.values()))
    return pd


def first_kills(conn: psycopg.Connection, character_names: list[str]) -> list[dict]:
    """For each LP boss × difficulty, the earliest timestamp at which one of the
    given character names was in a report that scored a kill."""
    names_lower = {(n or "").lower() for n in character_names if n}
    if not names_lower:
        return []

    # Only count kills on bosses we consider "real LP raid content" — reuse the
    # same heuristic as the guild-wide progression view.
    agg = boss_progression.aggregate(conn)
    valid_eids = {b["encounterID"] for b in agg["bosses"]}
    if not valid_eids:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT code, fights, player_details, start_time_ms
            FROM wcl_reports
            WHERE player_details IS NOT NULL
              AND fights IS NOT NULL
              AND zone_name = 'VS / DR / MQD'
              AND code != ALL(%s)
            """,
            (list(EXCLUDED_CODES),),
        )
        rows = cur.fetchall()

    bosses: dict[tuple[int, str], dict] = {}
    for r in rows:
        pd = _unwrap(r["player_details"])
        if not isinstance(pd, dict):
            continue
        present = False
        for group in ("tanks", "healers", "dps"):
            for p in pd.get(group) or []:
                if ((p.get("name") or "").lower()) in names_lower:
                    present = True
                    break
            if present:
                break
        if not present:
            continue

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
