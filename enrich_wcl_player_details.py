"""Backfill the `player_details` column on wcl_reports.

`playerDetails` gives us class + spec + role per player, plus ilvl ranges.
This is much better than masterData.actors (which only has class + name).
"""

import json
import os
import time

import db
import wcl


REQUEST_DELAY = float(os.environ.get("WCL_REQUEST_DELAY_SEC", "0.4"))


def main() -> None:
    client = wcl.WclClient()
    conn = db.connect()
    db.ensure_schema(conn)

    # Only fetch for reports that pass the synthesis filters — i.e. ones we'd
    # actually surface as gap-fill events. Skip pugs, M+, and pre-season.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT code
            FROM wcl_reports
            WHERE player_details IS NULL
              AND zone_name = 'VS / DR / MQD'
              AND jsonb_array_length(roster) BETWEEN 8 AND 40
              AND COALESCE(title, '') NOT ILIKE '%pug%'
            ORDER BY start_time_ms DESC
            """
        )
        codes = [r["code"] for r in cur.fetchall()]
    print(f"{len(codes)} reports need playerDetails")

    filled = 0
    failed = 0
    for code in codes:
        try:
            pd = wcl.fetch_report_player_details(client, code)
        except Exception as exc:
            print(f"  failed {code}: {exc}", flush=True)
            failed += 1
            continue
        if not pd:
            print(f"  no playerDetails for {code}", flush=True)
            time.sleep(REQUEST_DELAY)
            continue
        # WCL's playerDetails JSON scalar can be wrapped in any nesting of
        # {"data": {...}} and {"playerDetails": {...}}. Unwrap recursively until we
        # see one of the role keys (tanks / healers / dps).
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except json.JSONDecodeError:
                print(f"  {code}: playerDetails was unparseable string", flush=True)
                time.sleep(REQUEST_DELAY)
                continue
        while isinstance(pd, dict) and not any(k in pd for k in ("tanks", "healers", "dps")):
            if len(pd) != 1:
                break
            pd = next(iter(pd.values()))
            if isinstance(pd, str):
                try: pd = json.loads(pd)
                except json.JSONDecodeError: break
        with conn.cursor() as cur:
            cur.execute("UPDATE wcl_reports SET player_details = %s WHERE code = %s",
                         (json.dumps(pd), code))
        conn.commit()
        filled += 1
        n = (
            len(pd.get("tanks") or []) +
            len(pd.get("healers") or []) +
            len(pd.get("dps") or [])
        )
        print(f"  {code}: {n} players", flush=True)
        time.sleep(REQUEST_DELAY)

    print(f"\nDone. filled={filled} failed={failed}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
