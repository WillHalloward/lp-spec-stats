"""Build the Rouse spawn pattern page: where Twin Fangs Broodlings surface, read
from the longest Mythic kills on Warcraft Logs plus one of our own nights.

    python -m report_builders.rouse_spawns.build --kills 80 --night gfvXpCWVRj43anTH --publish

--publish writes reports/<slug>.html and adds (or updates) its row in
reports/index.json; without it the HTML goes to --out for a look first.
Needs WCL_CLIENT_ID / WCL_CLIENT_SECRET unless everything is cached.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from report_builders.twin_fangs.build import REPORTS, SITE, standalone

from .analyze import load
from .fetch import Rankings

TEMPLATE = Path(__file__).with_name("template.html")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kills", type=int, default=80, help="how many kills to read (longest first, one per guild)")
    ap.add_argument("--night", default="gfvXpCWVRj43anTH", help="our own report to show next to the kills")
    ap.add_argument("--date", default="2026-11-07", help="date for the reports index")
    ap.add_argument("--slug", default="twin-fangs-rouse-spawns")
    ap.add_argument("--title", default="The Twin Fangs Mythic — Rouse spawn pattern")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()

    st = load(Rankings().longest(args.kills), night=args.night)
    p = st.payload()
    summary = (
        f"Where the ten Broodlings surface in each Rouse the Brood, from {p['kills']} Mythic kills "
        f"({p['rouses']} Rouses) and Piian's night: sides always alternate, the first Rouse in each place "
        "uses every spot once, the second reuses spots, and which Broodling it is that comes back."
    )
    inner = TEMPLATE.read_text(encoding="utf-8").replace(
        "__PAYLOAD__", json.dumps(p, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    )
    doc = standalone(inner, args.night, title=args.title, description=summary, url=f"{SITE}/reports/{args.slug}")

    if args.publish:
        path = REPORTS / f"{args.slug}.html"
        path.write_text(doc, encoding="utf-8")
        index_path = REPORTS / "index.json"
        rows = json.loads(index_path.read_text(encoding="utf-8"))
        row = {
            "slug": args.slug,
            "title": args.title,
            "date": args.date,
            "kind": "infographic",
            "summary": summary,
            "source": f"https://www.warcraftlogs.com/reports/{args.night}",
        }
        rows = [r for r in rows if r.get("slug") != args.slug] + [row]
        rows.sort(key=lambda r: r.get("date", ""), reverse=True)
        index_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path} ({len(doc):,} bytes) and updated {index_path.name}")
    else:
        out = args.out or Path(f"{args.slug}.html")
        out.write_text(doc, encoding="utf-8")
        print(f"wrote {out} ({len(doc):,} bytes)")


if __name__ == "__main__":
    main()
