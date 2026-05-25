"""One-off: re-fetch fights for WCL reports started since SEASON_START_TS so
the stored `fights` JSONB picks up the newly-queried fightPercentage / lastPhase
fields.

Safe to re-run — the WCL query is idempotent, and we only touch reports whose
stored fights blob is missing fightPercentage on at least one fight.

Usage:
    DATABASE_URL=postgres://... WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... \\
    uv run python backfill_fight_percentage.py
"""

import json
import os
import time

import psycopg

import db
import wcl
from wcl_synthesis import SEASON_START_TS

REQUEST_DELAY = float(os.environ.get("WCL_REQUEST_DELAY_SEC", "0.3"))


def _needs_backfill(fights_blob: dict | None) -> bool:
    """True if the stored fights payload predates the fightPercentage column."""
    if not isinstance(fights_blob, dict):
        return True
    fights = fights_blob.get("fights") or []
    if not fights:
        return False  # No fights at all — nothing to backfill.
    # If ANY boss fight lacks the key, refresh. (Trash pulls legitimately won't
    # have it, so check only encounter fights.)
    for f in fights:
        if (f.get("encounterID") or 0) > 0 and "fightPercentage" not in f:
            return True
    return False


def _persist_with_reconnect(conn, code: str, fights_payload: dict):
    """Persist one row, reconnecting once if the Railway proxy idle-dropped us.
    Long-running scripts over the public Postgres proxy are prone to this."""
    for attempt in (1, 2):
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE wcl_reports SET fights = %s WHERE code = %s",
                    (json.dumps(fights_payload), code),
                )
            conn.commit()
            return conn
        except psycopg.OperationalError as exc:
            if attempt == 2:
                raise
            print(f"  reconnecting after DB drop: {exc}", flush=True)
            try:
                conn.close()
            except Exception:
                pass
            conn = db.connect()
    return conn  # unreachable


def main() -> None:
    client = wcl.WclClient()
    conn = db.connect()

    season_start_ms = SEASON_START_TS * 1000
    with conn.cursor() as cur:
        cur.execute(
            "SELECT code, fights FROM wcl_reports "
            "WHERE start_time_ms >= %s ORDER BY start_time_ms",
            (season_start_ms,),
        )
        rows = cur.fetchall()

    candidates = [r for r in rows if _needs_backfill(r["fights"])]
    print(f"Considering {len(rows)} reports since season start; "
          f"{len(candidates)} need backfill.", flush=True)

    updated = 0
    failed = 0
    for r in candidates:
        code = r["code"]
        try:
            fights_payload = wcl.fetch_report_fights(client, code)
        except Exception as exc:
            print(f"  {code} failed: {exc}", flush=True)
            failed += 1
            time.sleep(REQUEST_DELAY)
            continue
        try:
            conn = _persist_with_reconnect(conn, code, fights_payload)
        except Exception as exc:
            print(f"  {code} db update failed: {exc}", flush=True)
            failed += 1
            time.sleep(REQUEST_DELAY)
            continue
        updated += 1
        if updated % 25 == 0:
            print(f"  {updated}/{len(candidates)} updated", flush=True)
        time.sleep(REQUEST_DELAY)

    print(f"Done. updated={updated} failed={failed}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
