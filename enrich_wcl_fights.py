"""Fetch full fights data (boss kills + wipes + times) for each WCL report.

Stores the fights array (and report start ms) as JSONB. Powers the boss
progression view: first-kill dates, kill counts, wipe counts.
"""

import json
import os
import time

import db
import wcl


REQUEST_DELAY = float(os.environ.get("WCL_REQUEST_DELAY_SEC", "0.3"))


def main() -> None:
    client = wcl.WclClient()
    conn = db.connect()
    db.ensure_schema(conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT code FROM wcl_reports
            WHERE fights IS NULL
              AND zone_name = 'VS / DR / MQD'
            ORDER BY start_time_ms DESC
            """
        )
        codes = [r["code"] for r in cur.fetchall()]
    print(f"{len(codes)} reports need fights backfill")

    filled = 0
    failed = 0
    for code in codes:
        try:
            data = wcl.fetch_report_fights(client, code)
        except Exception as exc:
            print(f"  failed {code}: {exc}", flush=True)
            failed += 1
            continue

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE wcl_reports SET fights = %s WHERE code = %s",
                (json.dumps(data), code),
            )
        conn.commit()
        filled += 1
        boss_fights = [f for f in (data.get("fights") or []) if (f.get("encounterID") or 0) > 0]
        kills = sum(1 for f in boss_fights if f.get("kill"))
        print(f"  {code}: {len(boss_fights)} boss attempts, {kills} kills", flush=True)
        time.sleep(REQUEST_DELAY)

    print(f"\nDone. filled={filled} failed={failed}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
