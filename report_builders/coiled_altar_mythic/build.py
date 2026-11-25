"""Build the Mythic Coiled Altar page for one Warcraft Logs report.

    python -m report_builders.coiled_altar_mythic.build --report 3aw7TmPX2t6Zfr4g \
        --date 2026-11-19 --night "Piian's Mid-Pressure progression night" --out /tmp/preview.html

--publish writes it into reports/ and adds (or updates) its row in
reports/index.json; without it the HTML goes to --out for a look first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from report_builders.twin_fangs.build import SITE, standalone

from .analyze import Analysis
from .render import payload, render, tokens

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True)
    ap.add_argument("--date", help="YYYY-MM-DD (default: the report's start date)")
    ap.add_argument("--night", default="raid night", help='e.g. "Piian\'s Mid-Pressure progression night"')
    ap.add_argument("--slug", help="file name under reports/ (default: the-coiled-altar-mythic-prog-<date>)")
    ap.add_argument("--title")
    ap.add_argument("--team")
    ap.add_argument("--summary")
    ap.add_argument("--difficulty", type=int, default=5)
    ap.add_argument("--soak-plan", type=Path, help="JSON Guillotine soak teams (see plans/)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()

    a = Analysis(args.report, None, args.difficulty)
    if args.soak_plan:
        a.plan = json.loads(args.soak_plan.read_text(encoding="utf-8"))
    d = payload(a)
    start = dt.datetime.fromtimestamp(a.meta["startTime"] / 1000)
    date = args.date or start.strftime("%Y-%m-%d")
    date_long = dt.datetime.strptime(date, "%Y-%m-%d").strftime("%-d %B")
    tok = tokens(a, d, date_long=date_long, night_title=args.night)
    page = render(d, tok)

    slug = args.slug or f"the-coiled-altar-{tok['difficulty'].lower()}-prog-{date}"
    team_bit = f" — {args.team}" if args.team else ""
    angle = "the night it died" if tok["outcome"] == "the kill" else "where the pulls broke"
    row_title = args.title or f"{tok['boss']} {tok['difficulty']}{team_bit} — {angle}"
    row_summary = args.summary or (
        (f"{args.team}, " if args.team else "")
        + f"{tok['pulls']} {tok['difficulty']} pulls on {tok['boss']}: spinning axes eaten per player and "
        "across the night, stage one and two apart, who ran the green and purple orbs and every purple "
        "explosion, the Guillotine soaks and misses, frontal deaths, the shield burn, the Soulcoiler, "
        "and the intermission: Zul'jan's health into stage three and the fragments blocked and missed."
    )
    doc = standalone(
        page, args.report,
        title=f"{tok['boss']} {tok['difficulty']}: {angle} ({args.team + ', ' if args.team else ''}{date_long})",
        description=row_summary,
        url=f"{SITE}/reports/{slug}",
    )
    if args.publish:
        path = REPORTS / f"{slug}.html"
        path.write_text(doc, encoding="utf-8")
        index_path = REPORTS / "index.json"
        rows = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
        row = {"slug": slug, "title": row_title, "date": date, "kind": "prog night", "summary": row_summary,
               "source": f"https://www.warcraftlogs.com/reports/{args.report}"}
        rows = [r for r in rows if r.get("slug") != slug] + [row]
        rows.sort(key=lambda r: r.get("date", ""), reverse=True)
        index_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path} ({len(doc):,} bytes) and updated {index_path.name}")
    else:
        out = args.out or Path(f"{slug}.html")
        out.write_text(doc, encoding="utf-8")
        print(f"wrote {out} ({len(doc):,} bytes)")


if __name__ == "__main__":
    main()
