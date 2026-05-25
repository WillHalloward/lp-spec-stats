"""One-off: re-run WCL → raid-helper matching across every stored report.

When `event_matching.find_matching_event` is updated (new signals, better
scoring), existing rows in `wcl_reports.raid_id` are stale. This script
recomputes the match for each report and updates `raid_id` where it changed.

Respects admin overrides:
  - Reports with `wcl_report_overrides.forced_raid_id` set are skipped.
  - Reports listed in `event_overrides.wcl_codes[]` are skipped (the admin has
    manually pinned them; we trust the human).

Usage:
    DATABASE_URL=... uv run python backfill_event_matching.py            # report
    DATABASE_URL=... uv run python backfill_event_matching.py --apply    # write
"""

import argparse
from datetime import datetime, timezone

import db
import event_matching
from wcl_synthesis import LEADER_CHARACTERS as LEADER_CHAR_LOOKUP

LEADER_MAINS = tuple(c for c, _ in LEADER_CHAR_LOOKUP.values())
MATCH_WINDOW_SEC = 3 * 3600


def _admin_pinned_codes(conn) -> set[str]:
    pinned: set[str] = set()
    with conn.cursor() as cur:
        cur.execute("SELECT code FROM wcl_report_overrides WHERE forced_raid_id IS NOT NULL")
        pinned.update(r["code"] for r in cur.fetchall())
        cur.execute("SELECT wcl_codes FROM event_overrides WHERE wcl_codes IS NOT NULL")
        for r in cur.fetchall():
            for c in r["wcl_codes"] or []:
                pinned.add(c)
    return pinned


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Persist changes; without this, dry-runs and prints diffs.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only N reports (handy for spot-checks).")
    args = ap.parse_args()

    conn = db.connect()
    pinned = _admin_pinned_codes(conn)
    print(f"Admin-pinned codes (skipped): {len(pinned)}", flush=True)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT code, start_time_ms, title, owner_name, roster, raid_id, difficulty "
            "FROM wcl_reports ORDER BY start_time_ms"
        )
        reports = cur.fetchall()
    if args.limit:
        reports = reports[: args.limit]

    print(f"Processing {len(reports)} reports...", flush=True)

    unchanged = 0
    newly_matched = 0
    rematched = 0
    unmatched_now = 0
    unlinked_zero_overlap = 0
    skipped_pinned = 0
    score_too_low_keep_existing = 0

    changes: list[dict] = []

    for r in reports:
        code = r["code"]
        if code in pinned:
            skipped_pinned += 1
            continue

        old = r["raid_id"]
        new, info = event_matching.find_matching_event(
            conn,
            r["start_time_ms"] // 1000,
            roster=r["roster"] or [],
            wcl_difficulty=r["difficulty"],
            match_window_sec=MATCH_WINDOW_SEC,
            leader_characters=LEADER_MAINS,
            debug=True,  # need per-candidate breakdown to inspect old's overlap
        )

        if old == new:
            unchanged += 1
            continue

        # If new is None but old exists, the new matcher refused to endorse
        # any candidate. Find the old link's overlap in the debug breakdown:
        #  - If overlap with the OLD event was 0 → smoking gun that the old
        #    match was wrong (no shared player names). Drop the link.
        #  - Otherwise the new matcher just couldn't score anything high
        #    enough (borderline / few-signups events). Conservatively keep
        #    the existing link.
        if new is None and old is not None:
            old_overlap = None
            for cand in info.get("all", []):
                if cand["raid_id"] == old:
                    old_overlap = cand["overlap"]
                    break
            if old_overlap is not None and old_overlap == 0.0:
                # Confirmed wrong match — record this as an unlink.
                unlinked_zero_overlap += 1
                changes.append({
                    "code": code,
                    "start": datetime.fromtimestamp(r["start_time_ms"] // 1000, timezone.utc).isoformat(),
                    "title": (r["title"] or "")[:60],
                    "old_raid_id": old,
                    "new_raid_id": None,
                    "score": None,
                    "overlap": 0.0,
                    "delta_min": None,
                    "diff_match": None,
                    "reason": "zero-overlap with old link",
                })
                continue
            score_too_low_keep_existing += 1
            continue

        if old is None and new is not None:
            newly_matched += 1
        elif new is None and old is None:
            unmatched_now += 1
        else:
            rematched += 1

        changes.append({
            "code": code,
            "start": datetime.fromtimestamp(r["start_time_ms"] // 1000, timezone.utc).isoformat(),
            "title": (r["title"] or "")[:60],
            "old_raid_id": old,
            "new_raid_id": new,
            "score": info.get("chosen", {}).get("score"),
            "overlap": info.get("chosen", {}).get("overlap"),
            "delta_min": info.get("chosen", {}).get("delta_min"),
            "diff_match": info.get("chosen", {}).get("diff_match"),
        })

    print()
    print(f"unchanged                 : {unchanged}")
    print(f"newly matched (None→id)   : {newly_matched}")
    print(f"re-matched (id→differentid): {rematched}")
    print(f"unlinked (zero overlap)   : {unlinked_zero_overlap}")
    print(f"kept stale (new<min_score, old kept): {score_too_low_keep_existing}")
    print(f"skipped (admin-pinned)    : {skipped_pinned}")
    print(f"still unmatched           : {unmatched_now}")
    print()

    if not changes:
        print("No changes to apply.")
        conn.close()
        return

    print(f"=== {len(changes)} changes ===")
    for c in changes[:50]:
        # The unlinked-zero-overlap rows carry None for score/delta/diff_match
        # (we didn't pick a new candidate), so format defensively.
        score = c.get("score")
        delta = c.get("delta_min")
        score_s = f"{score:>5}" if score is not None else "  —  "
        delta_s = f"{delta:+d}min" if delta is not None else "  — "
        reason = c.get("reason", "")
        print(
            f"  {c['code']}  {c['start']}  "
            f"score={score_s}  overlap={c['overlap']:<5}  diff_match={c['diff_match']}  "
            f"Δ={delta_s}  "
            f"{(c['old_raid_id'] or 'None'):>20} -> {(c['new_raid_id'] or 'None'):>20}  "
            f"{reason or c['title']}"
        )
    if len(changes) > 50:
        print(f"  ... and {len(changes) - 50} more.")

    if not args.apply:
        print()
        print("Dry-run. Re-run with --apply to persist.")
        conn.close()
        return

    print()
    print("Applying...", flush=True)
    with conn.cursor() as cur:
        for c in changes:
            cur.execute(
                "UPDATE wcl_reports SET raid_id = %s WHERE code = %s",
                (c["new_raid_id"], c["code"]),
            )
    conn.commit()
    print(f"Updated {len(changes)} rows.", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
