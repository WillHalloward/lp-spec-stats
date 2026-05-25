"""Synthesize raid-helper-shaped events from WCL reports to gap-fill missing data.

Strategy:
  1. Load gap-fill candidates: zone = "VS / DR / MQD", roster size 8-40, no pug in title,
     no matching raid-helper event.
  2. Pattern-match the title to a known LP raid leader (Ragz/Piian/Rezn0r/...) so the
     synthesized event lands in the right series.
  3. Bucket by hour-of-start; keep the fullest roster per bucket (dedup multiple uploads
     of the same raid).
  4. Emit JSON shaped like a raid-helper event so the frontend doesn't need a special case.
"""

import re
from typing import Any

import psycopg


# Map title patterns -> (canonical leader display name, leader_id used in raid-helper data).
LEADER_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bragz|raigs", re.IGNORECASE),       "🆁🅰🅶🅾🅽🆉",    "217965404335636482"),
    (re.compile(r"\bpiian",       re.IGNORECASE),        "Piian",       "247328889184059392"),
    (re.compile(r"\breznor|\brezn0r|\blowfi|\blow-fi", re.IGNORECASE), "Rezn0r",  "1023365272549204079"),
    (re.compile(r"\bgryph",       re.IGNORECASE),        "Gryph",       "101944487927873536"),
    (re.compile(r"\bsaurfang|saürfang", re.IGNORECASE),  "Saurfang",    "416710811445231629"),
    (re.compile(r"\bmelody|mêlôdý", re.IGNORECASE),      "Melody",      "201451367376617472"),
    (re.compile(r"\byoro",        re.IGNORECASE),        "Yoro",        "198040805083054080"),
    (re.compile(r"\bjustinsane",  re.IGNORECASE),        "JustInsane",  "290239723572559872"),
    (re.compile(r"\bjaysale",     re.IGNORECASE),        "Jaysale",     "203844195310501888"),
    (re.compile(r"\bblossy",      re.IGNORECASE),        "Blossy",      "636247753315581952"),
    (re.compile(r"\bfaerhune|raaza", re.IGNORECASE),     "FaeRhune/Raaza", "179339863659642880"),
]

# Fallback when title doesn't pattern-match: look for the leader's own (eponymous)
# character in the roster. Each character listed here MUST be reliably present in their
# raids AND absent from others' — Mêlódý was excluded because she attends most Ragz
# raids, so her presence doesn't distinguish a Melody-led raid.
LEADER_CHARACTERS: dict[str, tuple[str, str]] = {
    "Piian":       ("Piian",        "247328889184059392"),
    "Ragz":        ("🆁🅰🅶🅾🅽🆉",      "217965404335636482"),
    "Gryphandrus": ("Gryph",        "101944487927873536"),
    "Rezuk":       ("Rezn0r",       "1023365272549204079"),
}


CLASS_MAP: dict[str, str] = {
    "DeathKnight": "DK",
    "DemonHunter": "DH",
    "Druid": "Druid",
    "Evoker": "Evoker",
    "Hunter": "Hunter",
    "Mage": "Mage",
    "Monk": "Monk",
    "Paladin": "Paladin",
    "Priest": "Priest",
    "Rogue": "Rogue",
    "Shaman": "Shaman",
    "Warlock": "Warlock",
    "Warrior": "Warrior",
}


# Season cutoff lives in normalize.ts on the frontend; we apply it here too for the SQL filter.
SEASON_START_TS = 1742083200  # 2026-03-16 UTC

# Manual exclusion list — WCL reports the maintainer has flagged as false positives
# (pugs, alt-runs, etc.) that pass our automatic filters.
EXCLUDED_CODES: set[str] = {
    "X6YyaK4V8LDPkmjc",  # 2026-03-23 19:11 — flagged ignore
    "23yMFwXV91GAbfdp",  # 2026-03-23 20:27 — flagged ignore
    "nf8AzXyrGJWZmdcq",  # 2026-03-23 19:12 — same date as above, flagged ignore
    "WHA8Q6Nf4KhRVrqy",  # 2026-04-23 — non-LP group (Dackeli), only Mythic FKS kill in data
    # Anybal's 6 logs on 2026-05-14 09:02 UTC — morning farm batch, not LP raids
    "LDjFtzmAY8GTxdaV",
    "XfKmJ7YN4Zpbax3T",
    "rk93fmpDyaGvFC8c",
    "CmTbwBZNxg1dq4Fp",
    "Dj4MWpyfCdvXPgAq",
    "6aPZVGN8xLFmBj47",
    # Explicit "LFR & NHC VoidShard Farm" — not LP
    "RTYq7MXQzGp94CbJ",
    # Large-roster pool logs that slipped past zone+title filter (>50 players = not single raid).
    # These would also be caught by the new roster≤50 filter in boss_progression but listed
    # here so the gap-fill synthesis ignores them too.
    "9HBZxR48QX6mWNL3", "2kg8yxPzfKCrnZAt", "v8a6LPz1BmnYryZQ",
    "d6HJLj2C9RV8DpxA", "zvpN1y6B4CQwXfAd", "jzmT9vM8npN2DL1W",
    "kdja2TPzXNFAZV3t", "drcVnTFp8b1WXaKA", "vy1x4tZfAHk6mcb3",
    "1LD9M8Gnf6ht4qkK", "PWY8yDFQVq1kBfHG", "zRF76ZWNv4GpdqLA",
    "vBpYqTAg7a8n6DzR", "bq8jrgw42mQGKWhd", "fLNyazBDcAwrtg1V",
}


def _match_leader(title: str | None, owner: str | None, roster: list[dict]) -> tuple[str, str, bool]:
    """Return (leadername, leaderid, confident). Strategy:
      1. Match title/owner against LEADER_PATTERNS (most reliable when present).
      2. Fall back to scanning the roster for a known leader character.
      3. Last resort: use the WCL log owner (not confident — caller may want to skip).
    """
    blob = f"{title or ''} {owner or ''}"
    for pat, name, lid in LEADER_PATTERNS:
        if pat.search(blob):
            return name, lid, True
    for actor in roster:
        cname = actor.get("name", "")
        if cname in LEADER_CHARACTERS:
            name, lid = LEADER_CHARACTERS[cname]
            return name, lid, True
    return owner or "Unknown", f"wcl:{owner or 'unknown'}", False


def _stable_userid(actor: dict, fallback_prefix: str = "wcl") -> str:
    """Build a userid that is stable across reports.
    Prefer GUID (WoW persistent player id), then name+server, then per-report actor id."""
    guid = actor.get("guid")
    if guid:
        return f"wcl-guid:{guid}"
    name = actor.get("name") or ""
    server = actor.get("server") or ""
    if name:
        return f"wcl-char:{name}-{server}".lower()
    return f"{fallback_prefix}:{actor.get('id')}"


def _synthesize_signup(actor: dict) -> dict:
    cls_raw = actor.get("subType") or ""
    cls = CLASS_MAP.get(cls_raw, cls_raw)
    server = actor.get("server") or ""
    name = actor.get("name") or "Unknown"
    full_name = f"{name}-{server}" if server else name
    return {
        "userid": _stable_userid(actor),
        "name": full_name,
        "class": cls,
        "cClass": cls,
        "spec": "",
        "cSpec": "",
        "role": "",
        "status": "primary",
        "spec_emote": "",
        "class_emote": "",
        "_source": "wcl",
    }


# playerDetails groups: tanks / healers / dps. The dps entries carry a "Melee"|"Ranged"
# type field; the others are obvious. Map to the role strings raid-helper uses.
PD_ROLE_FOR_GROUP = {"tanks": "Tanks", "healers": "Healers"}


def _synthesize_signups_from_player_details(pd: dict) -> list[dict]:
    """Build signups[] from a playerDetails payload (class + spec + role + ilvl)."""
    # WCL returns: {playerDetails: {tanks: [...], healers: [...], dps: [...]}}.
    # Caller may pass either the outer object or the inner one — unwrap here.
    if isinstance(pd, dict) and "playerDetails" in pd:
        pd = pd["playerDetails"]
    out: list[dict] = []
    for group, players in (pd or {}).items():
        for p in players or []:
            cls_raw = p.get("type") or ""
            cls = CLASS_MAP.get(cls_raw, cls_raw)
            specs = p.get("specs") or []
            # specs entries are {spec: "Frost", count: N}; pick the one used most.
            if specs and isinstance(specs[0], dict):
                spec = max(specs, key=lambda s: s.get("count", 0))["spec"]
            elif specs:
                spec = specs[0]
            else:
                spec = ""
            if group == "dps":
                # The dps group carries melee/ranged distinction in "type" but type also
                # holds the class for actors. WCL's playerDetails uses `icon` like
                # "DeathKnight-Frost" and `type`==class. Distinguish via spec convention
                # or fall back to a generic melee assumption.
                # In Cataclysm Classic specifically, p["type"] = "Melee"|"Ranged" sometimes;
                # in newer encoding it's the class. Handle both.
                t = p.get("type")
                if t in ("Melee", "Ranged"):
                    role = t
                else:
                    role = "Ranged" if _is_ranged_dps(cls, spec) else "Melee"
            else:
                role = PD_ROLE_FOR_GROUP.get(group, "")
            name = p.get("name") or "Unknown"
            server = p.get("server") or ""
            full_name = f"{name}-{server}" if server else name
            out.append({
                "userid": _stable_userid(p),
                "name": full_name,
                "class": cls,
                "cClass": cls,
                "spec": spec,
                "cSpec": spec,
                "role": role,
                "status": "primary",
                "spec_emote": "",
                "class_emote": "",
                "_source": "wcl",
                "_ilvl_min": p.get("minItemLevel"),
                "_ilvl_max": p.get("maxItemLevel"),
            })
    return out


# Map of class + spec → role hint when WCL doesn't tell us directly.
_RANGED_DPS_SPECS = {
    ("Mage", "Frost"), ("Mage", "Fire"), ("Mage", "Arcane"),
    ("Warlock", "Affliction"), ("Warlock", "Demonology"), ("Warlock", "Destruction"),
    ("Shaman", "Elemental"),
    ("Druid", "Balance"),
    ("Priest", "Shadow"),
    ("Hunter", "Beastmastery"), ("Hunter", "Marksmanship"), ("Hunter", "Survival"),
    ("Evoker", "Devastation"), ("Evoker", "Augmentation"),
}


def _is_ranged_dps(cls: str, spec: str) -> bool:
    return (cls, spec) in _RANGED_DPS_SPECS


def _synthesize_event(report: dict) -> dict:
    title = report["title"] or report["zone_name"] or "(unknown raid)"
    diff = report.get("difficulty")
    if diff and diff.lower() not in (title or "").lower():
        title = f"{title} ({diff})"
    leader_name, leader_id, _ = _match_leader(report["title"], report["owner_name"], report["roster"])

    pd = report.get("player_details")
    if pd:
        signups = _synthesize_signups_from_player_details(pd)
    else:
        signups = [_synthesize_signup(a) for a in report["roster"] if a.get("subType") in CLASS_MAP]
    return {
        "raidid": f"wcl:{report['code']}",
        "unixtime": report["start_time_ms"] // 1000,
        "leaderid": leader_id,
        "leadername": leader_name,
        "title": title,
        "displayTitle": title,
        "signups": signups,
        "_source": "wcl",
        "_wcl_code": report["code"],
        "_wcl_owner": report["owner_name"],
        "_encounter_ids": _encounter_ids_from_fights(report.get("fights")),
    }


def load_event_encounters(conn: psycopg.Connection) -> dict[str, list[int]]:
    """For each raid-helper event matched to a WCL report (auto-match or admin
    override), return the encounter IDs pulled in that raid. Used by the frontend
    to derive raid-series labels per event.
    """
    out: dict[str, set[int]] = {}
    excluded = _load_db_excluded_codes(conn) | EXCLUDED_CODES
    links = effective_report_links(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT code, fights FROM wcl_reports WHERE fights IS NOT NULL")
        rows = cur.fetchall()
    for r in rows:
        code = r["code"]
        if code in excluded:
            continue
        raid_id = links.get(code)
        if not raid_id:
            continue
        fights_payload = r["fights"] or {}
        fights = fights_payload.get("fights") if isinstance(fights_payload, dict) else None
        if not fights:
            continue
        bucket = out.setdefault(raid_id, set())
        for f in fights:
            enc = f.get("encounterID") or 0
            if enc > 0:
                bucket.add(enc)
    return {k: sorted(v) for k, v in out.items()}


def _encounter_ids_from_fights(fights_payload: dict | None) -> list[int]:
    if not isinstance(fights_payload, dict):
        return []
    out: set[int] = set()
    for f in fights_payload.get("fights") or []:
        enc = f.get("encounterID") or 0
        if enc > 0:
            out.add(enc)
    return sorted(out)


def _load_db_excluded_codes(conn: psycopg.Connection) -> set[str]:
    """Codes flagged as excluded in the wcl_report_overrides table. Combines with
    the hard-coded EXCLUDED_CODES set so admin edits don't lose the historical
    exclusions."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM wcl_report_overrides WHERE excluded = TRUE")
            return {r["code"] for r in cur.fetchall()}
    except Exception:
        return set()


def all_excluded_codes(conn: psycopg.Connection) -> set[str]:
    """Combined exclusion set: hard-coded + DB overrides."""
    return EXCLUDED_CODES | _load_db_excluded_codes(conn)


def _load_forced_raid_links(conn: psycopg.Connection) -> dict[str, str]:
    """code -> forced raid_id from wcl_report_overrides."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, forced_raid_id FROM wcl_report_overrides "
                "WHERE forced_raid_id IS NOT NULL"
            )
            return {r["code"]: r["forced_raid_id"] for r in cur.fetchall()}
    except Exception:
        return {}


def effective_report_links(conn: psycopg.Connection) -> dict[str, str]:
    """For each WCL code, the raid_id we consider it matched to, after applying
    overrides. Sources, in increasing priority:
      1. wcl_reports.raid_id (auto-matched at enrich time)
      2. wcl_report_overrides.forced_raid_id (admin force-link)
      3. event_overrides.wcl_codes[] (admin pinning extra codes to an event)
    """
    links: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT code, raid_id FROM wcl_reports WHERE raid_id IS NOT NULL")
        for r in cur.fetchall():
            links[r["code"]] = r["raid_id"]
    for code, rid in _load_forced_raid_links(conn).items():
        links[code] = rid
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT raid_id, wcl_codes FROM event_overrides")
            for r in cur.fetchall():
                for code in r["wcl_codes"] or []:
                    links[code] = r["raid_id"]
    except Exception:
        pass
    return links


def load_ilvl_map(conn: psycopg.Connection) -> dict[str, dict[str, dict]]:
    """For every WCL report that's matched to a raid-helper event (auto-match or
    admin override), harvest the per-character min/max ilvl. Returns:
    raid_id -> stripped_name -> {min, max}.
    """
    out: dict[str, dict[str, dict]] = {}
    excluded = _load_db_excluded_codes(conn) | EXCLUDED_CODES
    links = effective_report_links(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT code, player_details FROM wcl_reports WHERE player_details IS NOT NULL"
        )
        rows = cur.fetchall()
    rows = [
        {"raid_id": links[r["code"]], "player_details": r["player_details"]}
        for r in rows
        if r["code"] not in excluded and r["code"] in links
    ]
    for r in rows:
        pd = r["player_details"]
        # Unwrap WCL's {data: {playerDetails: {...}}} or {playerDetails: {...}}.
        while isinstance(pd, dict) and not any(k in pd for k in ("tanks", "healers", "dps")):
            if len(pd) != 1:
                break
            pd = next(iter(pd.values()))
        if not isinstance(pd, dict):
            continue
        bucket = out.setdefault(r["raid_id"], {})
        for group in ("tanks", "healers", "dps"):
            for p in pd.get(group) or []:
                nm = p.get("name")
                mn = p.get("minItemLevel")
                mx = p.get("maxItemLevel")
                if nm and mx:
                    bucket[nm] = {"min": mn, "max": mx}
    return out


def inject_ilvl(events: list[dict], ilvl_map: dict[str, dict[str, dict]]) -> None:
    """In-place: stamp `_ilvl_min` and `_ilvl_max` onto raid-helper signups that
    we can match by character name to a WCL roster for the same event."""
    for e in events:
        per_char = ilvl_map.get(str(e.get("raidid", "")))
        if not per_char:
            continue
        for s in e.get("signups") or []:
            raw = s.get("name") or ""
            stripped = raw.split("-", 1)[0].strip()
            data = per_char.get(stripped) or per_char.get(raw)
            if data:
                s["_ilvl_min"] = data["min"]
                s["_ilvl_max"] = data["max"]


def load_gap_fill_events(conn: psycopg.Connection) -> list[dict]:
    """Return synthesized event dicts for gap-fillable WCL reports."""
    # Exclude both hard-coded and admin-flagged codes, plus anything an admin
    # has force-linked to a raid (those aren't gap-fills, they're matched).
    excluded = list(EXCLUDED_CODES | _load_db_excluded_codes(conn))
    forced_codes = list(effective_report_links(conn).keys())
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT code, start_time_ms, end_time_ms, title, zone_name, owner_name, roster, difficulty, player_details, fights
            FROM wcl_reports
            WHERE raid_id IS NULL
              AND zone_name = 'VS / DR / MQD'
              AND start_time_ms / 1000 >= %s
              AND jsonb_array_length(roster) BETWEEN 8 AND 40
              AND COALESCE(title, '') NOT ILIKE '%%pug%%'
              AND COALESCE(title, '') NOT ILIKE '%%m+%%'
              AND COALESCE(title, '') NOT ILIKE '%%mythic+%%'
              AND code != ALL(%s)
              AND code != ALL(%s)
            ORDER BY start_time_ms
            """,
            (SEASON_START_TS, excluded, forced_codes),
        )
        rows = cur.fetchall()

    # Detect leader for each report up-front so we can cluster by (leader, time).
    # Two different leaders running back-to-back on the same evening are NOT the same raid.
    # Reports where we can't confidently identify the leader are dropped — they're almost
    # always duplicate uploads of someone else's raid by a non-leader logger.
    annotated: list[tuple[dict, str, str]] = []  # (row, leader_name, leader_id)
    for r in rows:
        name, lid, confident = _match_leader(r["title"], r["owner_name"], r["roster"])
        if not confident:
            continue
        annotated.append((r, name, lid))

    annotated.sort(key=lambda x: x[0]["start_time_ms"])

    # Cluster: same leader + within 2.5h of latest report by that leader = same raid.
    # We walk reports in time order but track each leader's latest cluster separately so
    # interleaved leaders (e.g. Ragz raid right next to Piian raid) don't break the chain.
    CLUSTER_GAP_MS = int(2.5 * 3600 * 1000)
    clusters: list[list[tuple[dict, str, str]]] = []
    latest_by_leader: dict[str, int] = {}  # leader_id -> index into clusters

    for entry in annotated:
        r, _name, lid = entry
        idx = latest_by_leader.get(lid)
        if idx is not None and r["start_time_ms"] - clusters[idx][-1][0]["start_time_ms"] <= CLUSTER_GAP_MS:
            clusters[idx].append(entry)
        else:
            clusters.append([entry])
            latest_by_leader[lid] = len(clusters) - 1

    chosen = [max(c, key=lambda e: len(e[0]["roster"])) for c in clusters]
    return [_synthesize_event(r) for r, _, _ in chosen]
