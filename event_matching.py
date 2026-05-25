"""Match a WCL report to the raid-helper event it actually came from.

The previous matcher (`enrich_wcl_auto._find_matching_event`) used closest-in-time
within a ±3h window — which silently picked the wrong event whenever two raids
started within ~15 minutes of each other. This module replaces that with a small
weighted score over multiple signals:

  - **Roster overlap** (Jaccard of WCL roster names ∩ event signup names).
    Single strongest signal; unrelated parallel raids share ~0 names while the
    correct event shares 60-90%.
  - **Difficulty agreement** between WCL fights and the event title.
  - **Time proximity** (just a tiebreaker now, not the deciding factor).
  - **Roster-size sanity penalty** to keep small M+ posts from absorbing
    full raid logs and vice versa.

Returns `None` rather than guessing when no candidate clears a minimum score —
unmatched is much better than wrongly-matched (the gap-fill pipeline picks up
unmatched reports safely).
"""

import re
from typing import Iterable

import psycopg


# Same regex set as frontend/src/normalize.ts detectDifficulty.
_DIFFICULTY_PATTERNS = [
    ("Mythic", re.compile(r"\bmythic\b", re.IGNORECASE)),
    ("Heroic", re.compile(r"\bheroic\b|\bhc\b", re.IGNORECASE)),
    ("Normal", re.compile(r"\bnormal\b", re.IGNORECASE)),
    ("LFR",    re.compile(r"\blfr\b", re.IGNORECASE)),
]


def detect_difficulty_from_title(title: str | None) -> str | None:
    if not title:
        return None
    for label, pat in _DIFFICULTY_PATTERNS:
        if pat.search(title):
            return label
    return None


def _strip_realm(name: str | None) -> str:
    if not name:
        return ""
    return name.split("-", 1)[0].strip().lower()


def _roster_name_set(roster: Iterable[dict] | None) -> set[str]:
    return {n for n in (_strip_realm(a.get("name")) for a in (roster or [])) if n}


def _signup_name_set(signups: Iterable[dict] | None) -> set[str]:
    """Attending signups only — absence/tentative/bench shouldn't count as
    'this player was actually there'."""
    out: set[str] = set()
    for s in signups or []:
        role = s.get("role") or ""
        cls = s.get("className") or s.get("class") or ""
        if role in ("Absence", "Tentative", "Bench", "Late"):
            continue
        if cls in ("Absence", "Tentative", "Bench", "Late"):
            continue
        nm = _strip_realm(s.get("name"))
        if nm:
            out.add(nm)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Score weights — tuned so roster overlap dominates and difficulty acts as a
# strong tiebreaker. Threshold below leaves room for fuzzy matches but rejects
# everything that's "just close in time".
W_OVERLAP = 10.0          # multiplied by jaccard (0..1)
W_DIFFICULTY = 5.0        # bonus when log difficulty matches event difficulty
W_LEADER_CHAR = 3.0       # leader's main character is in the roster
W_TIME = 1.0              # 1.0 at delta=0, decays with delta
W_ROSTER_SIZE_BAD = -5.0  # penalty when sizes are wildly different

MIN_SCORE = 3.0           # below this → leave unmatched


def _time_score(start_unix_sec: int, ev_unix_sec: int) -> float:
    delta_min = abs(start_unix_sec - ev_unix_sec) / 60.0
    return 1.0 / (1.0 + delta_min / 60.0)  # 1.0 at delta=0, 0.5 at delta=60min


def find_matching_event(
    conn: psycopg.Connection,
    start_unix_sec: int,
    *,
    roster: list[dict] | None,
    wcl_difficulty: str | None,
    match_window_sec: int = 3 * 3600,
    leader_characters: Iterable[str] = (),
    debug: bool = False,
) -> tuple[str | None, dict]:
    """Pick the best raid-helper event for one WCL report.

    Returns (raid_id_or_None, debug_info). debug_info always contains the score
    breakdown for the chosen candidate (and all candidates when debug=True).
    """
    lo = start_unix_sec - match_window_sec
    hi = start_unix_sec + match_window_sec

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT raid_id, unixtime, title, data
              FROM events
             WHERE unixtime BETWEEN %s AND %s
            """,
            (lo, hi),
        )
        candidates = cur.fetchall()

    if not candidates:
        return None, {"reason": "no_candidates_in_window"}

    roster_names = _roster_name_set(roster)
    leader_chars_lower = {(n or "").lower() for n in leader_characters if n}

    scored: list[tuple[float, dict, dict]] = []  # (score, candidate, breakdown)

    for cand in candidates:
        signups = (cand.get("data") or {}).get("signups") or []
        signup_names = _signup_name_set(signups)
        overlap = _jaccard(roster_names, signup_names)

        ev_diff = detect_difficulty_from_title(cand.get("title"))
        diff_bonus = (
            W_DIFFICULTY
            if (wcl_difficulty and ev_diff and wcl_difficulty == ev_diff)
            else 0.0
        )

        leader_char_in_roster = bool(roster_names & leader_chars_lower)
        leader_bonus = W_LEADER_CHAR if leader_char_in_roster else 0.0

        size_diff = abs(len(roster_names) - len(signup_names))
        size_penalty = W_ROSTER_SIZE_BAD if size_diff > 12 else 0.0

        time_bonus = W_TIME * _time_score(start_unix_sec, cand["unixtime"])

        score = W_OVERLAP * overlap + diff_bonus + leader_bonus + time_bonus + size_penalty

        scored.append((score, cand, {
            "raid_id": cand["raid_id"],
            "overlap": round(overlap, 3),
            "diff_match": ev_diff == wcl_difficulty if (ev_diff and wcl_difficulty) else None,
            "ev_diff": ev_diff,
            "wcl_diff": wcl_difficulty,
            "leader_char_in_roster": leader_char_in_roster,
            "size_diff": size_diff,
            "delta_min": (start_unix_sec - cand["unixtime"]) // 60,
            "score": round(score, 2),
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_cand, best_break = scored[0]

    info: dict = {"chosen": best_break, "min_score": MIN_SCORE}
    if debug:
        info["all"] = [b for _, _, b in scored]

    if best_score < MIN_SCORE:
        info["reason"] = "below_threshold"
        return None, info

    return best_cand["raid_id"], info
