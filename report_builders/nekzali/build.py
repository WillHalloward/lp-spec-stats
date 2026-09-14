"""Build the Soulcoil Well report page for one Warcraft Logs report.

    python -m report_builders.nekzali.build --report nVtMWTA7rCXag2h6 \
        --date 2026-09-14 --night "Low Pressure progression night" --publish

--publish writes it into reports/ and adds (or updates) its row in
reports/index.json; without it the HTML goes to --out for a look first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from .analyze import Analysis
from .render import payloads, render, tokens

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports"

NAV = """<nav class="report-nav">
  <a href="/reports">&larr; Reports</a>
  <span>Low Pressure</span>
  <a href="https://www.warcraftlogs.com/reports/{code}">Warcraft Logs</a>
</nav>
"""
NAV_CSS = """<style>
/* Strip tying the report back to the site it is served from. */
.report-nav{display:flex;gap:18px;align-items:center;justify-content:center;
  background:#070912;color:#8b95ad;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;
  padding:10px 16px;border-bottom:1px solid #1c2438}
.report-nav a{color:#8b95ad;text-decoration:none}
.report-nav a:hover{color:#e0a526}
.report-nav span{color:#e0a526;letter-spacing:.12em;text-transform:uppercase}
</style>
"""

SUMMARY = (
    "why two well teams cannot cover a forty-second Echo, the pulls where the rotation "
    "broke, the Soul Exhaustion hits that killed the divers, and the same night measured "
    "against the four earliest public kills."
)


def standalone(inner: str, code: str) -> str:
    """Wrap the page body in a document the site can serve directly."""
    cut = inner.index('<div class="wrap">')
    head, body = inner[:cut], inner[cut:]
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<link rel="icon" type="image/svg+xml" href="/favicon.svg">\n'
        + head
        + "<style>img{max-width:100%}[hidden]{display:none!important}</style>\n"
        + NAV_CSS
        + "</head>\n<body>\n"
        + NAV.format(code=code)
        + body
        + "\n</body>\n</html>\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True, help="Warcraft Logs report code")
    ap.add_argument("--date", help="night's date, YYYY-MM-DD (default: the report's own start date)")
    ap.add_argument(
        "--night", default="raid night", help='phrase for the header, e.g. "Low Pressure progression night"'
    )
    ap.add_argument("--slug", help="file name under reports/ (default: <boss>-<difficulty>-well-<date>)")
    ap.add_argument("--title", help="title for the reports index")
    ap.add_argument("--team", help="team name, for a night where two teams raid the same boss")
    ap.add_argument("--encounter", type=int, help="encounter id, if the report holds more than one boss")
    ap.add_argument("--difficulty", type=int, help="3 normal, 4 heroic, 5 mythic")
    ap.add_argument("--out", type=Path, help="write the HTML here instead of publishing")
    ap.add_argument(
        "--publish", action="store_true", help="write into reports/ and update reports/index.json"
    )
    args = ap.parse_args()

    a = Analysis(args.report, args.encounter, args.difficulty)
    built = a.build()
    start = dt.datetime.fromtimestamp(a.report["startTime"] / 1000)
    date = args.date or start.strftime("%Y-%m-%d")
    date_long = dt.datetime.strptime(date, "%Y-%m-%d").strftime("%-d %B %Y")
    tok = tokens(a, built, date_long=date_long, night_title=args.night)
    html = render(payloads(built), tok)

    boss_slug = "".join(c.lower() if c.isalnum() else "-" for c in tok["boss"]).strip("-")
    slug = args.slug or f"{boss_slug}-{tok['difficulty'].lower()}-well-{date}"
    doc = standalone(html, args.report)

    if args.publish:
        path = REPORTS / f"{slug}.html"
        path.write_text(doc, encoding="utf-8")
        index_path = REPORTS / "index.json"
        rows = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
        team_bit = f" — {args.team}" if args.team else ""
        row = {
            "slug": slug,
            "title": args.title
            or f"{tok['boss']} {tok['difficulty']}{team_bit} — the Soulcoil Well rotation",
            "date": date,
            "kind": "prog night",
            "summary": (
                (f"{args.team}, " if args.team else "")
                + f"{tok['pulls']} pulls at {tok['difficulty'].lower()} {tok['boss']}: "
                + SUMMARY
            ),
            "source": f"https://www.warcraftlogs.com/reports/{args.report}",
        }
        rows = [r for r in rows if r.get("slug") != slug]
        rows.append(row)
        rows.sort(key=lambda r: r.get("date", ""), reverse=True)
        index_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path} ({len(doc):,} bytes) and updated {index_path.name}")
    else:
        out = args.out or Path(f"{slug}.html")
        out.write_text(doc, encoding="utf-8")
        print(f"wrote {out} ({len(doc):,} bytes)")


if __name__ == "__main__":
    main()
