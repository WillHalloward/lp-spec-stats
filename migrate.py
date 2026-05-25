"""One-off: load existing cache/events/*.json into Postgres.

Run once after setting DATABASE_URL. Safe to re-run — upserts.
"""

import glob
import json
from pathlib import Path

import db


CACHE_DIR = Path("cache/events")


def main() -> None:
    conn = db.connect()
    db.ensure_schema(conn)

    files = sorted(glob.glob(str(CACHE_DIR / "*.json")))
    print(f"Found {len(files)} cached events to migrate")

    for i, f in enumerate(files, 1):
        with open(f) as fh:
            event = json.load(fh)
        db.upsert_event(conn, event)
        if i % 10 == 0 or i == len(files):
            print(f"  {i}/{len(files)}")

    print(f"Done. DB now holds {db.count_events(conn)} events")
    conn.close()


if __name__ == "__main__":
    main()
