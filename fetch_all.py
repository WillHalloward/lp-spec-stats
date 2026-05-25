"""Build a local cache of raid-helper events from the last 3 months.

Run once. Writes:
  cache/events_list.json              -- the raw list response
  cache/events/<raidId>.json          -- one file per event detail

Re-runs skip event files that already exist.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SERVER_ID = "1411835313696804976"
ACCESS_TOKEN = "DQnBnZFQOz-RC-CTdHzVDxWspW4SUQ7t8ogv2n4TX8GpBcYU2GMOT6o6GKtZpm8I82llH7GquyvS2m8uOSLYcFi3oBZ-2Ji1Sz0M83XtaFMzxTc"

CACHE_DIR = Path("cache")
EVENTS_DIR = CACHE_DIR / "events"
LIST_FILE = CACHE_DIR / "events_list.json"

COOKIES = {"JSESSIONID": "node01txn8dk939xie1roqnxhyertle5767.node0"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://raid-helper.xyz",
    "Connection": "keep-alive",
}

REQUEST_DELAY_SEC = 0.5
RATE_LIMIT_BACKOFFS = [30, 60, 120, 240]


def _post_with_retry(url: str, headers: dict, payload: dict) -> requests.Response:
    for wait in [*RATE_LIMIT_BACKOFFS, None]:
        resp = requests.post(url, cookies=COOKIES, headers=headers, json=payload, timeout=30)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        if wait is None:
            resp.raise_for_status()
        retry_after = resp.headers.get("Retry-After")
        sleep_for = int(retry_after) if retry_after and retry_after.isdigit() else wait
        print(f"    429 rate-limited, sleeping {sleep_for}s")
        time.sleep(sleep_for)
    raise RuntimeError("unreachable")


def fetch_event_list() -> dict:
    headers = {**HEADERS, "Referer": f"https://raid-helper.xyz/calendar/{SERVER_ID}"}
    payload = {"serverid": SERVER_ID, "accessToken": ACCESS_TOKEN}
    return _post_with_retry("https://raid-helper.xyz/api/events/", headers, payload).json()


def fetch_event_detail(raid_id: str) -> dict:
    headers = {**HEADERS, "Referer": f"https://raid-helper.xyz/event/{raid_id}"}
    payload = {"accessToken": ACCESS_TOKEN}
    return _post_with_retry(f"https://raid-helper.xyz/api/event/{raid_id}", headers, payload).json()


def main() -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching event list...")
    data = fetch_event_list()
    LIST_FILE.write_text(json.dumps(data, indent=2))
    all_events = data.get("events", [])
    print(f"  got {len(all_events)} events total")

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    cutoff_ts = cutoff.timestamp()
    recent = [e for e in all_events if e.get("unixtime", 0) >= cutoff_ts]
    print(f"  {len(recent)} events within the last 90 days")

    fetched = 0
    skipped = 0
    failed = 0
    for i, event in enumerate(recent, 1):
        raid_id = str(event["raidId"])
        out = EVENTS_DIR / f"{raid_id}.json"
        if out.exists():
            skipped += 1
            continue
        date_str = datetime.fromtimestamp(event["unixtime"], timezone.utc).strftime("%Y-%m-%d")
        title = event.get("displayTitle") or event.get("title") or "?"
        print(f"  [{i}/{len(recent)}] {date_str}  {raid_id}  {title}")
        try:
            detail = fetch_event_detail(raid_id)
            out.write_text(json.dumps(detail, indent=2))
            fetched += 1
            time.sleep(REQUEST_DELAY_SEC)
        except Exception as exc:
            print(f"    failed: {exc}")
            failed += 1

    print(f"\nDone. fetched={fetched} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
