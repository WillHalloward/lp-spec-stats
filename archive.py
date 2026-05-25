"""Railway cron entrypoint — runs every 15 minutes.

For each event in the calendar:
  - if it has started (or starts within LEAD_TIME_SEC) and isn't archived yet → fetch + insert
  - if it's archived but the event was less than REFRESH_WINDOW_SEC ago → refresh
  - otherwise → skip

Safe to re-run; idempotent.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

import db
import enrich_wcl_auto


def _config() -> dict:
    return {
        "server_id": os.environ.get("RAID_HELPER_SERVER_ID", "1411835313696804976"),
        "access_token": os.environ["RAID_HELPER_ACCESS_TOKEN"],
        "lead_time_sec": int(os.environ.get("ARCHIVE_LEAD_TIME_SEC", str(15 * 60))),
        "refresh_window_sec": int(os.environ.get("ARCHIVE_REFRESH_WINDOW_SEC", str(24 * 3600))),
        "request_delay_sec": float(os.environ.get("ARCHIVE_REQUEST_DELAY_SEC", "0.5")),
    }

HEADERS = {
    "User-Agent": "lp-spec-stats archiver",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://raid-helper.xyz",
}

RATE_LIMIT_BACKOFFS = [30, 60, 120, 240]


def _post_with_retry(url: str, headers: dict, payload: dict) -> requests.Response:
    for wait in [*RATE_LIMIT_BACKOFFS, None]:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        if wait is None:
            resp.raise_for_status()
        retry_after = resp.headers.get("Retry-After")
        sleep_for = int(retry_after) if retry_after and retry_after.isdigit() else wait
        print(f"    429 rate-limited, sleeping {sleep_for}s", flush=True)
        time.sleep(sleep_for)
    raise RuntimeError("unreachable")


def fetch_event_list(cfg: dict) -> dict:
    headers = {**HEADERS, "Referer": f"https://raid-helper.xyz/calendar/{cfg['server_id']}"}
    payload = {"serverid": cfg["server_id"], "accessToken": cfg["access_token"]}
    return _post_with_retry("https://raid-helper.xyz/api/events/", headers, payload).json()


def fetch_event_detail(cfg: dict, raid_id: str) -> dict:
    headers = {**HEADERS, "Referer": f"https://raid-helper.xyz/event/{raid_id}"}
    payload = {"accessToken": cfg["access_token"]}
    return _post_with_retry(f"https://raid-helper.xyz/api/event/{raid_id}", headers, payload).json()


def _run_raid_helper_archive(cfg: dict, conn) -> None:
    """The raid-helper portion. Isolated so a token failure here doesn't block
    the WCL enrichment pass."""
    now = int(datetime.now(timezone.utc).timestamp())
    archived = db.get_archived_ids(conn)
    print(f"DB currently holds {len(archived)} events", flush=True)

    print("Fetching event list...", flush=True)
    listing = fetch_event_list(cfg)
    events = listing.get("events", [])
    print(f"  {len(events)} events visible in calendar", flush=True)

    fetched, refreshed, skipped, failed = 0, 0, 0, 0
    for ev in events:
        raid_id = str(ev["raidId"])
        unixtime = int(ev["unixtime"])
        starts_within_window = unixtime < now + cfg["lead_time_sec"]
        already_archived = raid_id in archived

        if not starts_within_window:
            skipped += 1
            continue

        if already_archived:
            # Refresh only if event was within the refresh window of now.
            if (now - unixtime) > cfg["refresh_window_sec"]:
                skipped += 1
                continue
            action = "refresh"
        else:
            action = "archive"

        try:
            detail = fetch_event_detail(cfg, raid_id)
            db.upsert_event(conn, detail, is_refresh=(action == "refresh"))
            if action == "refresh":
                refreshed += 1
            else:
                fetched += 1
            print(f"  {action}: {raid_id}  {ev.get('displayTitle','')[:80]}", flush=True)
            time.sleep(cfg["request_delay_sec"])
        except Exception as exc:
            print(f"  failed: {raid_id}: {exc}", flush=True)
            failed += 1

    print(f"Done. archived={fetched} refreshed={refreshed} skipped={skipped} failed={failed}", flush=True)


def main() -> None:
    cfg = _config()
    conn = db.connect()
    db.ensure_schema(conn)

    print("=== Raid-helper archive ===", flush=True)
    try:
        _run_raid_helper_archive(cfg, conn)
    except Exception as exc:
        print(f"Raid-helper archive failed: {exc}", flush=True)

    print("\n=== WCL enrichment ===", flush=True)
    try:
        result = enrich_wcl_auto.run(conn)
        print(f"WCL enrichment done: {result}", flush=True)
    except Exception as exc:
        print(f"WCL enrichment failed: {exc}", flush=True)

    conn.close()


if __name__ == "__main__":
    main()
