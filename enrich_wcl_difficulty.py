"""Backfill the `difficulty` column on wcl_reports by fetching per-fight difficulty
from the WCL API.

WCL stores a per-fight numeric difficulty. We map the standard codes:
  Retail/MoP+        : 14=N, 15=H, 16=M, 17=LFR
  Classic/legacy     : 3=N,  4=H,  5=M,  1=LFR

For each report, pick the most common difficulty among boss fights (encounterID > 0).
"""

import os
import time
from collections import Counter

import db
import wcl


DIFFICULTY_MAP = {
    1: "LFR", 17: "LFR",
    3: "Normal", 14: "Normal",
    4: "Heroic", 15: "Heroic",
    5: "Mythic", 16: "Mythic",
}

REQUEST_DELAY = float(os.environ.get("WCL_REQUEST_DELAY_SEC", "0.3"))


def main() -> None:
    client = wcl.WclClient()
    conn = db.connect()
    db.ensure_schema(conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT code
            FROM wcl_reports
            WHERE difficulty IS NULL
              AND zone_name = 'VS / DR / MQD'
            ORDER BY start_time_ms DESC
            """
        )
        codes = [r["code"] for r in cur.fetchall()]
    print(f"{len(codes)} reports need difficulty backfill")

    filled = 0
    skipped = 0
    failed = 0
    for code in codes:
        try:
            fights_data = wcl.fetch_report_fights(client, code)
        except Exception as exc:
            print(f"  failed {code}: {exc}", flush=True)
            failed += 1
            continue

        fights = fights_data.get("fights") if isinstance(fights_data, dict) else fights_data
        counts: Counter = Counter()
        for f in fights or []:
            if (f.get("encounterID") or 0) <= 0:
                continue
            d = DIFFICULTY_MAP.get(f.get("difficulty"))
            if d:
                counts[d] += 1

        if not counts:
            skipped += 1
            print(f"  {code}: no boss fights, skipping", flush=True)
            time.sleep(REQUEST_DELAY)
            continue

        diff = counts.most_common(1)[0][0]
        with conn.cursor() as cur:
            cur.execute("UPDATE wcl_reports SET difficulty = %s WHERE code = %s", (diff, code))
        conn.commit()
        filled += 1
        print(f"  {code}: {diff}  ({dict(counts)})", flush=True)
        time.sleep(REQUEST_DELAY)

    print(f"\nDone. filled={filled} skipped={skipped} failed={failed}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
