"""One summary row per Mythic Coiled Altar night, from the Mythic page's own
analysis, so the progress page and the night pages can never disagree.

Everything that grows with the size of a night (deaths, explosions, axes) is
a rate: per pull, per minute alive or per window. The nights run 18 to 35
pulls, and raw totals would mostly measure that.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from report_builders.coiled_altar_mythic.analyze import Analysis

PLANS = Path(__file__).resolve().parents[1] / "coiled_altar_mythic" / "plans"
STAGES = ["P1", "P2", "INT", "P3"]
# The checkpoints a pull has to get past, in fight order: (label, test). A
# pull is past a time checkpoint if it was still alive (before its wipe)
# a couple of seconds after it; the Guillotines land at 48s and 133s.
CHECKPOINTS = [
    ("Past the opening orbs (25s)", 25),
    ("Past the first Guillotine (48s)", 50),
    ("Past the second Guillotine (133s)", 135),
    ("Stage two", "P2"),
    # only the first: Malacrass often dies before casting a second, so a
    # second-shield checkpoint would sit below the intermission
    ("First shield broken", ("veil", 1)),
    ("Intermission", "INT"),
    ("Stage three", "P3"),
]
# An explosion this early is the opening set of orbs colliding, a different
# problem from carrying one into another mid-stage.
OPENING_EXPLOSION_S = 25


def _med(L):
    return round(statistics.median(L), 1) if L else None


def night(code: str, date: str, plan: str | None) -> dict:
    a = Analysis(code, None, 5)
    if plan:
        a.plan = json.loads((PLANS / plan).read_text(encoding="utf-8"))
    d = a.build()
    pulls = [p for p in d["pulls"] if not p["reset"]]
    n = len(pulls)
    rank = lambda p: (STAGES.index(p["reached"]), -p["pct"])
    best = max(pulls, key=rank)
    reached = Counter(p["reached"] for p in pulls)
    at_least = lambda k: sum(1 for p in pulls if STAGES.index(p["reached"]) >= STAGES.index(k))

    # how long each pull lived before its wipe started: the plainest progress line
    lived = [p["wipe"] if p["wipe"] is not None else p["dur"] for p in pulls]

    W = d["wipes"]["wipes"]
    pre = d["wipes"]["before"]
    ex = [e for e in d["orbs"]["explosions"] if e["before_wipe"]]
    ex_p1 = [e for e in ex if e["phase"] == "P1"]
    gw = [w for w in d["guillotine"]["windows"] if not w["after_wipe"]]
    g_plan = [w for w in gw if w["absent"] is not None]
    veil = [w for w in d["veil"]["windows"] if not w["after_wipe"] and not w["open"]]
    broken = [w for w in veil if w["broken"]]
    adds = [x for x in d["adds"]["adds"] if not x["after_wipe"]]
    killed = [x for x in adds if x["killed"]]
    fd = [x for x in d["frontals"]["deaths"] if x["before_wipe"]]
    ints = [r for r in d["intermission"]["rows"] if not r["after_wipe"]]
    z = [r["z_end"] for r in ints if r["z_end"] is not None]

    # minutes of each stage played before the wipe, the base for stage rates
    def stage_min(k):
        s = 0.0
        for p in pulls:
            if k in p["phases"]:
                a0, b0 = p["phases"][k]
                end = min(b0, p["wipe"]) if p["wipe"] is not None else b0
                s += max(0.0, end - a0)
        return s / 60

    # the funnel: how many pulls got past each checkpoint
    broke = {(w["pull"], w["n"]) for w in d["veil"]["windows"] if w["phase"] == "P2" and w["broken"] and not w["after_wipe"]}
    funnel = []
    for label, test in CHECKPOINTS:
        def past(p, l):
            if isinstance(test, (int, float)):
                return l > test
            if isinstance(test, str):
                return test in p["phases"] and p["phases"][test][0] < l
            return (p["pull"], test[1]) in broke
        funnel.append({"label": label, "n": sum(1 for p, l in zip(pulls, lived) if past(p, l))})

    players = defaultdict(lambda: {"pulls": 0, "deaths": 0, "groups": Counter(), "ax1": None, "ax2": None,
                                   "g_absent": 0, "g_expected": 0, "veil_per": None, "add_per": None,
                                   "int_dps": None, "set_off": 0, "set_off_purple": 0})
    for p in pulls:
        for name in a.players.get(next(f for f, k in a.num.items() if k == p["pull"]), []):
            players[name]["pulls"] += 1
    for x in pre:
        players[x["player"]]["deaths"] += 1
        players[x["player"]]["groups"][x["group"]] += 1
    for k, key in (("P1", "ax1"), ("P2", "ax2")):
        for r in d["axes"][k]["players"]:
            players[r["name"]][key] = r["index"]
    for w in gw:
        if w["absent"] is None:
            continue
        on_team = set(w["soakers"]) - set(w["extra"] or [])
        for n_ in set(w["absent"]) | set(w["locked"] or []) | on_team:
            players[n_]["g_expected"] += 1
        for n_ in w["absent"]:
            players[n_]["g_absent"] += 1
    for r in d["veil"]["players"]:
        players[r["name"]]["veil_per"] = r["per_window"]
    for r in d["adds"]["players"]:
        players[r["name"]]["add_per"] = round(r["damage"] / r["adds"]) if r["adds"] else None
    for r in d["intermission"]["players"]:
        players[r["name"]]["int_dps"] = r["dps"]
    for e in ex:
        for x in e["set_off"]:
            players[x["name"]]["set_off"] += 1
            players[x["name"]]["set_off_purple"] += x["orb"] == "purple"
    roster = a.roster()

    return {
        "code": code,
        "date": date,
        "label": dt.datetime.strptime(date, "%Y-%m-%d").strftime("%-d %b"),
        "pulls": n,
        "resets": len(d["pulls"]) - n,
        "minutes": round(sum(p["dur"] for p in d["pulls"]) / 60),
        "best": {"pull": best["pull"], "reached": best["reached"], "pct": best["pct"]},
        "reached": {k: reached.get(k, 0) for k in STAGES},
        "at_least": {k: at_least(k) for k in STAGES},
        "lived_med": _med(lived),
        "lived_top5": _med(sorted(lived)[-5:]),
        "pull_rows": [
            {"pull": p["pull"], "reached": p["reached"], "pct": p["pct"],
             "lived": l, "cause": next((w["cause"] for w in W if w["pull"] == p["pull"]), None), "kill": p["kill"]}
            for p, l in zip(pulls, lived)
        ],
        "wipe_causes": dict(Counter(w["cause"] for w in W)),
        "wipes": len(W),
        "pre_deaths": len(pre),
        "pre_groups": dict(Counter(x["group"] for x in pre)),
        "explosions": len(ex),
        "explosions_p1": len(ex_p1),
        "explosions_opening": sum(1 for e in ex_p1 if e["t"] <= OPENING_EXPLOSION_S),
        "explosions_left": sum(1 for e in ex if e["how"] == "left"),
        "p1_min": round(stage_min("P1"), 1),
        "p2_min": round(stage_min("P2"), 1),
        "ax1": d["axes"]["P1"]["per_min"],
        "ax2": d["axes"]["P2"]["per_min"],
        "g_windows": len(gw),
        "g_missed": sum(1 for w in gw if w["missed"]),
        "g_soak_med": _med([len(w["soakers"]) for w in gw]),
        "g_absent": sum(len(w["absent"] or []) for w in g_plan),
        "g_plan_windows": len(g_plan),
        "frontal_deaths": len(fd),
        "veils": len(veil),
        "veils_broken": len(broken),
        "veil_secs": _med([w["secs"] for w in broken]),
        "adds": len(adds),
        "adds_killed": len(killed),
        "add_ttk": _med([x["ttk"] for x in killed]),
        "ints": len(ints),
        "int_missed": sum(r["missed"] for r in ints),
        "int_fragments": sum(r["missed"] + r["blocked"] for r in ints),
        "int_z_best": min(z) if z else None,
        "int_z_med": _med(z),
        "funnel": funnel,
        "set_off_named": sum(1 for e in ex if e["set_off"]),
        "set_off_kinds": dict(Counter(e["set_off_kind"] or "nobody's orb came off" for e in ex)),
        "players": {
            k: {"pulls": v["pulls"], "deaths": v["deaths"], "groups": dict(v["groups"]),
                "ax1": v["ax1"], "ax2": v["ax2"],
                "g_absent": v["g_absent"], "g_expected": v["g_expected"],
                "veil_per": v["veil_per"], "add_per": v["add_per"], "int_dps": v["int_dps"],
                "set_off": v["set_off"], "set_off_purple": v["set_off_purple"],
                "cls": (roster.get(k) or {}).get("class", ""), "role": (roster.get(k) or {}).get("role", "")}
            for k, v in players.items() if v["pulls"]
        },
    }
