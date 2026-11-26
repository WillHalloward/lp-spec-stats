"""Build the Mythic Coiled Altar progress page: every night in nights.json,
side by side.

    python -m report_builders.coiled_altar_progress.build --out /tmp/preview.html
    python -m report_builders.coiled_altar_progress.build --publish

Add the next night as a row in nights.json (its soak plan too, if it has one)
and run it again. --publish writes reports/<slug>.html and its index row.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from report_builders.coiled_altar_mythic.render import CSS
from report_builders.twin_fangs.build import SITE, standalone

from .analyze import night

HERE = Path(__file__).parent
REPO = HERE.parents[1]
REPORTS = REPO / "reports"
TEMPLATE = HERE / "template.html"
PHASE_LONG = {"P1": "stage one", "P2": "stage two", "INT": "the intermission", "P3": "stage three"}


def _pct(a, b) -> str:
    return f"{round(100 * a / b)}%" if b else "–"


def tokens(nights: list[dict], team: str) -> dict:
    f, l = nights[0], nights[-1]
    boom = lambda n: _pct(n["wipe_causes"].get("Purple orb explosion", 0), n["wipes"])
    return {
        "boss": "The Coiled Altar",
        "difficulty": "Mythic",
        "zone": "The Venomous Abyss",
        "team": team,
        "nights": len(nights),
        "pulls": sum(n["pulls"] for n in nights),
        "hours": f"{sum(n['minutes'] for n in nights) / 60:.1f}",
        "first_label": f["label"],
        "last_label": l["label"],
        "first_best_pct": f"{f['best']['pct']:.1f}",
        "first_best_phase": PHASE_LONG[f["best"]["reached"]],
        "last_best_pct": f"{l['best']['pct']:.1f}",
        "last_best_phase": PHASE_LONG[l["best"]["reached"]],
        "first_p3_share": _pct(f["at_least"]["P3"], f["pulls"]),
        "last_p3_share": _pct(l["at_least"]["P3"], l["pulls"]),
        "first_boom_share": boom(f),
        "last_boom_share": boom(l),
        "first_pre_pp": f"{f['pre_deaths'] / f['pulls']:.1f}",
        "last_pre_pp": f"{l['pre_deaths'] / l['pulls']:.1f}",
        "codes": " &middot; ".join(n["code"] for n in nights),
    }


def render(nights: list[dict], tok: dict) -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    css_src = CSS.read_text(encoding="utf-8")
    src = src.replace("__SHARED_CSS__", css_src[css_src.index('<link rel="stylesheet"'): css_src.index("</style>")])

    def sub(m):
        if m.group(1) not in tok:
            raise KeyError(f"template token {{{{{m.group(1)}}}}} has no value")
        return str(tok[m.group(1)])

    out = re.sub(r"\{\{(\w+)\}\}", sub, src)
    payload = json.dumps({"nights": nights}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return out.replace("__PAYLOAD__", payload)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nights", type=Path, default=HERE / "nights.json")
    ap.add_argument("--slug", default="the-coiled-altar-mythic-progress")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(args.nights.read_text(encoding="utf-8"))
    team = cfg.get("team", "")
    nights = []
    for n in cfg["nights"]:
        row = night(n["code"], n["date"], n.get("plan"))
        # each night's own page, for the column headers
        row["slug"] = n.get("slug") or f"the-coiled-altar-mythic-piian-{n['date']}"
        nights.append(row)
    tok = tokens(nights, team)
    page = render(nights, tok)
    last = nights[-1]
    title = f"The Coiled Altar Mythic — {team} — progress, night by night"
    summary = (
        f"{team}, {tok['nights']} Mythic nights on The Coiled Altar ({tok['first_label']} to {tok['last_label']}, "
        f"{tok['pulls']} pulls) side by side: how far each pull got, what ended them, deaths before the wipe by "
        "mechanic, purple explosions, Guillotines, axes, the shield, the Soulcoiler, the intermission, and each player."
    )
    doc = standalone(page, last["code"], title=f"The Coiled Altar Mythic: progress ({team}, {tok['first_label']} – {tok['last_label']})",
                     description=summary, url=f"{SITE}/reports/{args.slug}")
    if args.publish:
        path = REPORTS / f"{args.slug}.html"
        path.write_text(doc, encoding="utf-8")
        index_path = REPORTS / "index.json"
        rows = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
        row = {"slug": args.slug, "title": title, "date": last["date"], "kind": "progress", "summary": summary,
               "source": f"https://www.warcraftlogs.com/reports/{last['code']}"}
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
