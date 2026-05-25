"""Aggregate boss progression stats from wcl_reports.fights.

Produces a per-boss / per-difficulty summary:
  - total kills + wipes + total attempts
  - first kill timestamp + report code
  - latest kill timestamp
  - cumulative time spent (sum of attempt durations)

WCL reports often include fights from OTHER raids (M+ runs, side raids) that
the raid leader uploaded in the same log. We filter those out by requiring an
encounter to have been attempted at least MIN_ATTEMPTS times across our entire
report set — real LP raid bosses get hundreds of attempts; pugged M+ keys and
one-off raids do not.
"""

from typing import Any
from collections import defaultdict  # noqa: F401

import psycopg

from wcl_synthesis import EXCLUDED_CODES, all_excluded_codes, effective_report_links


DIFFICULTY_NAME = {
    1: "LFR", 17: "LFR",
    3: "Normal", 14: "Normal",
    4: "Heroic", 15: "Heroic",
    5: "Mythic", 16: "Mythic",
}

# Minimum attempts (across all difficulties combined) for an encounter to count
# as an LP raid boss. Empirically the LP bosses are all 250+ while M+ /
# unrelated content sits at ≤25, so 50 leaves comfortable headroom either way.
MIN_ATTEMPTS = 50

# Only include LP-shape reports (raid zone, raid-sized roster).
# Roster > 50 is almost always a multi-night farm pool log (aggregated across days)
# and not a single raid — exclude those from boss progression counts.
# Escapes %% so psycopg doesn't read e.g. %p as a placeholder when bound vars are present.
PROGRESSION_FILTER_SQL = """
    fights IS NOT NULL
    AND zone_name = 'VS / DR / MQD'
    AND COALESCE(title, '') NOT ILIKE '%%pug%%'
    AND COALESCE(title, '') NOT ILIKE '%%mythic+%%'
    AND COALESCE(title, '') NOT ILIKE '%%farm%%'
    AND jsonb_array_length(roster) BETWEEN 8 AND 50
"""


def _dedupe_reports(rows: list[dict]) -> list[dict]:
    """Return one representative report per raid session.

    Multiple people often upload the same raid. We detect that by comparing
    each report's set of (encounter_id, absolute_fight_start_time) — two logs
    of the same physical raid have identical fight timestamps within seconds
    (modulo small clock skew between uploaders). This is more robust than
    keying by raid_id, since the same raid uploaded by two players may end up
    matched to two different raid-helper events (e.g. parallel Ragz/Piian
    events at the same time).

    Two reports are considered the same raid when they share ≥3 boss fights
    at the same wall-clock moment (10-second bucket) AND those shared fights
    are ≥50% of the smaller report's fights. Within each cluster we keep the
    log with the most boss fights — usually the most complete one.
    """
    from collections import defaultdict
    BUCKET_SEC = 10  # absorb sub-10s clock skew between uploaders

    def _sig(r: dict) -> set[tuple[int, int]]:
        fights_blob = r.get("fights") or {}
        report_start = fights_blob.get("report_start_ms") or r.get("start_time_ms") or 0
        out: set[tuple[int, int]] = set()
        for f in fights_blob.get("fights") or []:
            eid = f.get("encounterID") or 0
            if eid <= 0:
                continue
            abs_ms = (f.get("startTime") or 0) + report_start
            out.add((eid, abs_ms // (BUCKET_SEC * 1000)))
        return out

    sigs = [_sig(r) for r in rows]

    # Union-find clustering. O(n²) but n stays in the hundreds in practice;
    # an inverted index can replace this if it ever gets slow.
    parent = list(range(len(rows)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(rows)):
        if not sigs[i]:
            continue
        for j in range(i + 1, len(rows)):
            if not sigs[j]:
                continue
            inter = len(sigs[i] & sigs[j])
            if inter == 0:
                continue
            smaller = min(len(sigs[i]), len(sigs[j]))
            # Merge if either:
            #  - The smaller report's fights are fully contained in the larger
            #    (partial upload of the same raid — handles tiny early uploads).
            #  - Substantial overlap: ≥3 shared fights AND ≥50% of the smaller.
            #    Coincidental collisions on (encounter_id, 10s_bucket) tuples
            #    across unrelated raids are astronomically unlikely at this scale.
            if inter == smaller or (inter >= 3 and inter / smaller >= 0.5):
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b

    groups: dict[int, list[dict]] = defaultdict(list)
    for i, r in enumerate(rows):
        groups[find(i)].append(r)

    def boss_fight_count(r: dict) -> int:
        fights = ((r.get("fights") or {}).get("fights")) or []
        return sum(1 for f in fights if (f.get("encounterID") or 0) > 0)

    return [max(rs, key=boss_fight_count) for rs in groups.values()]


def aggregate(conn: psycopg.Connection) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT code, start_time_ms, raid_id, owner_name, title, fights "
            f"FROM wcl_reports WHERE {PROGRESSION_FILTER_SQL} AND code != ALL(%s)",
            (list(all_excluded_codes(conn)),),
        )
        rows = cur.fetchall()

    # Apply effective raid_id (admin overrides win over auto-match) before dedupe
    # so force-linked reports get grouped with their event.
    links = effective_report_links(conn)
    for r in rows:
        r["raid_id"] = links.get(r["code"], r["raid_id"])

    rows = _dedupe_reports(rows)

    # (encounterID, diff_str) -> stats
    bosses: dict[tuple[int, str], dict] = {}

    for r in rows:
        fights_blob = r["fights"]
        # Stored as {"report_start_ms":..., "fights":[...]}
        fights = (fights_blob or {}).get("fights") or []
        report_start_ms = (fights_blob or {}).get("report_start_ms") or r["start_time_ms"]

        for f in fights:
            eid = f.get("encounterID") or 0
            if eid <= 0:
                continue
            diff_raw = f.get("difficulty")
            diff = DIFFICULTY_NAME.get(diff_raw, "Other")
            # LFR runs aren't LP guild content — they're pugs/queues that some
            # of our raiders happened to do. Skip.
            if diff == "LFR":
                continue
            name = f.get("name") or f"Encounter {eid}"
            key = (eid, diff)
            stat = bosses.setdefault(key, {
                "encounterID": eid,
                "name": name,
                "difficulty": diff,
                "kills": 0,
                "wipes": 0,
                "first_kill_ms": None,
                "first_kill_code": None,
                "latest_kill_ms": None,
                "total_duration_ms": 0,
                # Lowest boss HP % reached on a wipe (None = no wipes recorded
                # with fightPercentage data yet). WCL's fightPercentage is the
                # boss HP remaining when the pull ended, so lower = closer to kill.
                "best_pull_pct": None,
                "best_pull_code": None,
                "best_pull_fight_id": None,
            })
            # Fight times are relative to report start. Absolute = report_start + fight_start.
            f_start = (f.get("startTime") or 0) + (report_start_ms or 0)
            f_end = (f.get("endTime") or 0) + (report_start_ms or 0)
            duration = max(0, f_end - f_start)
            stat["total_duration_ms"] += duration
            if f.get("kill"):
                stat["kills"] += 1
                if stat["first_kill_ms"] is None or f_start < stat["first_kill_ms"]:
                    stat["first_kill_ms"] = f_start
                    stat["first_kill_code"] = r["code"]
                if stat["latest_kill_ms"] is None or f_start > stat["latest_kill_ms"]:
                    stat["latest_kill_ms"] = f_start
            else:
                stat["wipes"] += 1
                # fightPercentage is already a 0..100 boss-HP-remaining value
                # (verified empirically against WCL's report UI). Keep it as-is.
                pct = f.get("fightPercentage")
                if isinstance(pct, (int, float)) and (stat["best_pull_pct"] is None or pct < stat["best_pull_pct"]):
                    stat["best_pull_pct"] = float(pct)
                    stat["best_pull_code"] = r["code"]
                    stat["best_pull_fight_id"] = f.get("id")

    # Compute attempts per encounter (summing across difficulties).
    encounter_attempts: dict[int, int] = {}
    for (eid, _), stat in bosses.items():
        encounter_attempts[eid] = encounter_attempts.get(eid, 0) + stat["kills"] + stat["wipes"]
    keep = {eid for eid, n in encounter_attempts.items() if n >= MIN_ATTEMPTS}

    return {
        "bosses": sorted(
            [s for (eid, _), s in bosses.items() if eid in keep],
            key=lambda s: (s["first_kill_ms"] or 1e15, s["encounterID"], s["difficulty"]),
        ),
    }


def attempts_for_boss(
    conn: psycopg.Connection, encounter_id: int, difficulty: str
) -> list[dict]:
    """Every attempt (kill or wipe) on one (encounterID, difficulty), oldest first.

    Returns dicts with: ts_ms, kill (bool), fight_pct (float | None, 0..100),
    duration_ms, report_code, fight_id. Used by the boss-cell modal to show
    the progression that led to the best pull / each kill.
    """
    if difficulty == "LFR":
        return []  # We filter LFR everywhere else; stay consistent.

    diff_codes = [code for code, name in DIFFICULTY_NAME.items() if name == difficulty]
    if not diff_codes:
        return []

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT code, start_time_ms, raid_id, fights FROM wcl_reports "
            f"WHERE {PROGRESSION_FILTER_SQL} AND code != ALL(%s)",
            (list(all_excluded_codes(conn)),),
        )
        rows = cur.fetchall()

    links = effective_report_links(conn)
    for r in rows:
        r["raid_id"] = links.get(r["code"], r["raid_id"])

    rows = _dedupe_reports(rows)

    out: list[dict] = []
    for r in rows:
        fights_blob = r["fights"] or {}
        fights = fights_blob.get("fights") or []
        report_start_ms = fights_blob.get("report_start_ms") or r["start_time_ms"]
        for f in fights:
            if (f.get("encounterID") or 0) != encounter_id:
                continue
            if f.get("difficulty") not in diff_codes:
                continue
            f_start = (f.get("startTime") or 0) + (report_start_ms or 0)
            f_end = (f.get("endTime") or 0) + (report_start_ms or 0)
            raw_pct = f.get("fightPercentage")
            # Already 0..100 — see comment in aggregate() above.
            pct = float(raw_pct) if isinstance(raw_pct, (int, float)) else None
            out.append({
                "ts_ms": f_start,
                "kill": bool(f.get("kill")),
                "fight_pct": pct,
                "duration_ms": max(0, f_end - f_start),
                "report_code": r["code"],
                "fight_id": f.get("id"),
                "last_phase": f.get("lastPhase"),
                # Frontend joins this against the events array to render the
                # series label (leader name). May be null for unmatched reports;
                # in that case the frontend falls back to `wcl:<report_code>`
                # to find the corresponding gap-fill event.
                "raid_id": r["raid_id"],
            })
    out.sort(key=lambda a: a["ts_ms"])
    return out


def per_event_first_kills(conn: psycopg.Connection) -> list[dict]:
    """Return one row per (raid_id, encounterID, difficulty) tracking the first
    kill of that boss within that raid-helper event.

    Lets the client compute first-kills scoped to any subset of events (e.g. a
    raid series) by grouping these rows by their raid_id → series mapping.
    Only includes rows where the report matched a raid-helper event (raid_id
    not null) — unmatched WCL reports can't be associated with a series.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT code, start_time_ms, raid_id, fights FROM wcl_reports "
            f"WHERE {PROGRESSION_FILTER_SQL} AND code != ALL(%s)",
            (list(all_excluded_codes(conn)),),
        )
        rows = cur.fetchall()

    # Apply admin overrides, then drop reports we still can't attribute to a raid.
    links = effective_report_links(conn)
    for r in rows:
        r["raid_id"] = links.get(r["code"], r["raid_id"])
    rows = [r for r in rows if r["raid_id"]]

    rows = _dedupe_reports(rows)

    # Track which encounters survive the MIN_ATTEMPTS gate using the same logic
    # as aggregate() so the two endpoints agree on what's a real LP boss.
    encounter_attempts: dict[int, int] = {}
    for r in rows:
        fights_blob = r["fights"]
        fights = (fights_blob or {}).get("fights") or []
        for f in fights:
            eid = f.get("encounterID") or 0
            if eid <= 0:
                continue
            diff = DIFFICULTY_NAME.get(f.get("difficulty"), "Other")
            if diff == "LFR":
                continue
            encounter_attempts[eid] = encounter_attempts.get(eid, 0) + 1
    keep_encounters = {eid for eid, n in encounter_attempts.items() if n >= MIN_ATTEMPTS}

    # (raid_id, encounterID, difficulty) -> first kill row
    out: dict[tuple[str, int, str], dict] = {}
    for r in rows:
        fights_blob = r["fights"]
        fights = (fights_blob or {}).get("fights") or []
        report_start_ms = (fights_blob or {}).get("report_start_ms") or r["start_time_ms"]
        for f in fights:
            eid = f.get("encounterID") or 0
            if eid <= 0 or eid not in keep_encounters:
                continue
            diff = DIFFICULTY_NAME.get(f.get("difficulty"), "Other")
            if diff == "LFR":
                continue
            if not f.get("kill"):
                continue
            f_start = (f.get("startTime") or 0) + (report_start_ms or 0)
            key = (r["raid_id"], eid, diff)
            existing = out.get(key)
            if existing is None or f_start < existing["kill_ms"]:
                out[key] = {
                    "raid_id": r["raid_id"],
                    "encounterID": eid,
                    "name": f.get("name") or f"Encounter {eid}",
                    "difficulty": diff,
                    "kill_ms": f_start,
                    "report_code": r["code"],
                    "fight_id": f.get("id"),
                }
    return list(out.values())
