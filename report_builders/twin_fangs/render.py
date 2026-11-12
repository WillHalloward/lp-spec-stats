"""Fill the template: payloads as JSON, everything the prose states as a token.

Every number the page says out loud is computed here, so the next prog night on
Twin Fangs regenerates its own sentences rather than inheriting this one's.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from . import spells as S
from .analyze import CASCADE_N, CASCADE_S, GROUP_LABEL, Analysis

TEMPLATE = Path(__file__).parent / "template.html"

# why a Broodling went off (analyze.burst_causes), worst first, with a colour each
CAUSE_ORDER = ["none", "late", "early", "pairmate", "other", "double", "boss", "snake", "cd", "spent", "recast", "dead", "unplaced"]
CAUSE_LABEL = {
    "none": ["No kick, kick was ready", "var(--crit)"],
    "late": ["Kick just too late", "var(--s2)"],
    "early": ["Kicked before it began casting", "var(--s4)"],
    "pairmate": ["Kicked pair-mate's Broodling", "var(--s5)"],
    "other": ["Kicked another group's Broodling", "var(--cls-DemonHunter)"],
    "double": ["Double kick", "var(--cls-Warlock)"],
    "boss": ["Kick went into the boss", "var(--s1)"],
    "snake": ["Kick went into a snake", "var(--cls-Mage)"],
    "cd": ["Kick on cooldown", "var(--inter)"],
    "spent": ["Out of kicks, backup didn't cover", "var(--s3)"],
    "recast": ["Kicked, it cast again, nobody kicked", "var(--cls-Monk)"],
    "dead": ["Kicker dead", "var(--ink-2)"],
    "unplaced": ["No spot in the log", "var(--rule)"],
}

GROUP_COLOR = {
    "burst": "var(--crit)",
    "tainted": "var(--s5)",
    "feast": "var(--cls-Warlock)",
    "venom": "var(--s3)",
    "globule": "var(--cls-Hunter)",
    "soak": "var(--cls-Rogue)",
    "waves": "var(--s1)",
    "snakes": "var(--s4)",
    "ichor": "var(--cls-Druid)",
    "stone": "var(--ink-2)",
    "tank": "var(--cls-Warrior)",
    "flood": "var(--cls-Mage)",
    "attrition": "var(--inter)",
    "other": "var(--muted)",
}
DEATH_ORDER = list(GROUP_COLOR)
MARKS = [
    ["globules", "Blood Torrent + globules", "var(--cls-Hunter)"],
    ["stone", "Stone Breaker", "var(--ink-2)"],
    ["rouse", "Rouse the Brood + snakes", "var(--s4)"],
    ["ichor", "Coiling Ichor", "var(--cls-Druid)"],
    ["waves", "Stir the Depths", "var(--s1)"],
    ["feast", "Ravenous Feast", "var(--cls-Warlock)"],
    ["storm", "Sanguine Storm", "var(--muted)"],
    ["flood", "Submerge / Vile Flood", "var(--cls-Mage)"],
]
CLASSES = ["DeathKnight", "DemonHunter", "Druid", "Evoker", "Hunter", "Mage", "Monk", "Paladin", "Priest",
           "Rogue", "Shaman", "Warlock", "Warrior"]
# the class colours are theme tokens in the template (light and dark values)
CLASS_COLOR = {c: f"var(--cls-{c})" for c in CLASSES}
CLASS_NAME = {"DeathKnight": "Death Knight", "DemonHunter": "Demon Hunter"}
# death groups as a sentence says them, without nested brackets
PROSE_LABEL = {
    "burst": "Visceral Burst from a missed kick",
    "tainted": "Tainted Burst from an unhealed fount",
    "venom": "Eternal Venom ticks",
    "waves": "Stir the Depths waves",
    "snakes": "the snakes",
    "tank": "tank damage",
    "attrition": "attrition from Toxic Fumes",
    "other": "other causes",
}
ROLE_ORDER = {"tank": 0, "healer": 1, "dps": 2}


def names(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def plural(n, one, many=None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def top_ties(pairs, n, cap=3):
    """The first n of (label, count) pairs sorted by count, plus anyone tied
    with the nth, so a list never cuts through a tie. If that would add more
    than `cap` extra, stop above the tie instead."""
    pairs = list(pairs)
    if len(pairs) <= n:
        return pairs
    edge = pairs[n - 1][1]
    out = [p for p in pairs if p[1] >= edge]
    if len(out) > n + cap:
        out = [p for p in pairs if p[1] > edge] or pairs[:n]
    return out


def names_or(items, empty="nobody") -> str:
    return names(items) or empty


def cls_name(c, n=1) -> str:
    base = CLASS_NAME.get(c, c)
    return base if n == 1 else base + "s"


def prose_label(g) -> str:
    return PROSE_LABEL.get(g, GROUP_LABEL.get(g, g))


def ordinal(n) -> str:
    return {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth"}.get(n, f"{n}th")


def night_summary(a: Analysis) -> dict:
    """The few numbers one night is compared with the next on."""
    pulls = a.pull_rows()
    R = a.rouses
    ends = [p["wipe"] if p["wipe"] is not None else p["dur"] for p in pulls]
    return {
        "pulls": len(pulls),
        "burst_wipes": sum(1 for p in pulls if p["wipe_cause"] == "burst"),
        "bursts_per_rouse": round(sum(r["bursts"] for r in R) / len(R), 2) if R else 0,
        "submerge": sum(1 for p in pulls if reached_flood(p)),
        "med_end": round(statistics.median(ends)) if ends else 0,
        "best": min(p["pct"] for p in pulls) if pulls else None,
        "tainted_wipes": sum(1 for p in pulls if p["wipe_cause"] == "tainted"),
    }


def reached_flood(p) -> bool:
    return any(m["k"] == "flood" and (p["wipe"] is None or m["t"] < p["wipe"]) for m in p["marks"])


def med(xs, default=0.0):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else default


def fmt(x, d=1):
    return f"{x:.{d}f}"


def pct(a, b):
    return round(100 * a / b) if b else 0


def payloads(a: Analysis, plan: dict | None = None) -> tuple[dict, dict]:
    pulls = a.pull_rows()
    roster = sorted(a.roles, key=lambda n: (ROLE_ORDER[a.roles[n]], a.cls[n], n))
    players = [{"name": n, "cls": a.cls[n], "role": a.roles[n], "spec": a.spec.get(n, "")} for n in roster]

    # ---- deaths, before the wipe ----
    pre = defaultdict(Counter)
    first = Counter()
    for fid, p in zip(a.ids, pulls):
        w = a.wipe[fid]
        live = [d for d in a.deaths[fid] if w is None or d["ts"] < w]
        for d in live:
            pre[d["player"]][d["group"]] += 1
        if live:
            first[live[0]["player"]] += 1
    death_rows = [
        {
            "name": n,
            "pulls": sum(1 for fid in a.ids if n in a.present[fid]),
            "pre": dict(pre[n]),
            "n": sum(pre[n].values()),
            "first": first[n],
        }
        for n in roster
    ]

    # ---- kicks ----
    patterns = a.kick_patterns()
    side_of = {k["player"]: (k["top_spot"][0] if k["top_spot"] != "?" else None) for k in patterns}
    missed = []
    for r in a.rouses:
        for ad in r["adds"]:
            if ad["bursts"]:
                side = ad["side"]
                missed.append(
                    {
                        "pull": r["pull"],
                        "rouse": r["n"],
                        "spot": ad["spot"],
                        "t": round(r["t"] + ad["burst_t"], 1),
                        "after": ad["burst_t"],
                        "spawn_rank": ad["spawn_rank"],
                        "kicked_late": ad["kicker"],
                        "bursts": ad["bursts"],
                        "near": [n for n in ad["ready"] if side and side_of.get(n) == side],
                        "far": [n for n in ad["ready"] if not (side and side_of.get(n) == side)],
                        "ended": r["ended"],
                    }
                )
    grid = [
        {
            "pull": r["pull"],
            "rouse": r["n"],
            "ended": r["ended"],
            "cells": [
                {"spot": ad["spot"], "who": ad["kicker"], "rank": ad["kick_rank"], "spawn": ad["spawn_rank"],
                 "t": ad["kick"], "b": ad["bursts"], "bt": ad["burst_t"], "try": ad.get("try"),
                 "inf": ad["inferred"], "side": ad["side"]}
                for ad in r["adds"]
            ],
        }
        for r in a.rouses
    ]

    # ---- side sequences, second Rouse in a place (2, 4, 6) ----
    # One side at a time: its five spots in spawn order, lettered by first use
    # (ABCDA = the 5th Broodling came back to the 1st one's spot). Sides
    # alternate every Broodling, so a "?" Broodling's side is still known; a
    # side with any "?" can't be lettered and is only counted. Spots filled in
    # from the sequences themselves count as "?" here, or they'd count twice.
    seqs, seq_unread, seq_cut = [], 0, 0
    for r in a.rouses:
        if r["n"] % 2:
            continue
        adds = r["adds"]
        known = next((i for i, ad in enumerate(adds) if ad["spot"] != "?"), None)
        if known is None:
            seq_unread += 2
            continue
        other = {"L": "R", "R": "L"}
        side_of = [adds[known]["spot"][0] if (i - known) % 2 == 0 else other[adds[known]["spot"][0]]
                   for i in range(len(adds))]
        for sd in "LR":
            spots = [("?" if ad["inferred"] else ad["spot"]) for ad, x in zip(adds, side_of) if x == sd]
            if len(spots) < 5 and "?" not in spots:
                seq_cut += 1  # the wipe cut the Rouse short
                continue
            if len(spots) != 5 or "?" in spots:
                seq_unread += 1
                continue
            m = {}
            seqs.append({"pull": r["pull"], "rouse": r["n"], "side": sd, "spots": spots,
                         "seq": "".join(m.setdefault(x, "ABCDE"[len(m)]) for x in spots)})

    # ---- globules ----
    waves = a.waves
    gl = defaultdict(lambda: {"waves": 0, "soaked": 0, "doubles": 0, "extra": 0, "idle": 0, "boom_waves": 0,
                              "wave_soaks": 0, "death_soaks": 0})
    for w in waves:
        fid = w["fight"]
        for n in a.present[fid]:
            if not a.alive(fid, n, w["ts"]):
                continue
            g = gl[n]
            g["waves"] += 1
            ds = w["death_soaks"].get(n, 0)
            k = w["soakers"].get(n, 0) - ds  # wave globules only
            g["soaked"] += 1 if k else 0
            g["wave_soaks"] += k
            g["death_soaks"] += ds
            if k > 1:
                g["doubles"] += 1
                g["extra"] += k - 1
            if w["boom_ts"] and any(a.alive(fid, n, b) for b in w["boom_ts"]):
                g["boom_waves"] += 1
                if n in w["idle"]:
                    g["idle"] += 1
    for n, c in a.death_soaks_loose.items():
        gl[n]["death_soaks"] += c
    # stacks gained by source, before the wipe
    src = defaultdict(Counter)
    for g in a.stack_gains:
        fid = g["fight"]
        if a.wipe[fid] and g["ts"] >= a.wipe[fid]:
            continue
        src[g["player"]][g["src"]] += g["n"]
    glob_rows = [
        {"name": n, **gl[n], "src": dict(src[n]), "pulls": sum(1 for fid in a.ids if n in a.present[fid])}
        for n in roster
    ]
    shields_cls = Counter()
    shields_spell = defaultdict(Counter)
    for w in waves:
        for s in w["strips"]:
            shields_cls[s["cls"]] += 1
            shields_spell[s["cls"]][s["spell"]] += 1
    wave_rows = [
        {k: w[k] for k in ("pull", "wave", "t", "globules", "death_globules", "death_droppers", "shielded", "stripped", "soaks", "booms")}
        | {"doubles": [n for n, k in w["soakers"].items() if k - w["death_soaks"].get(n, 0) > 1],
           "idle": [n for n in w["idle"] if a.roles.get(n) != "tank"]}
        for w in waves
    ]

    # ---- Feast and Tainted Blood ----
    feasts = a.feasts
    fp = defaultdict(lambda: {"feasts": 0, "soaked": 0})
    for f in feasts:
        fid = f["fight"]
        for n in a.present[fid]:
            if a.alive(fid, n, f["ts"]):
                fp[n]["feasts"] += 1
                fp[n]["soaked"] += 1 if n in f["soakers"] else 0
    healed = Counter()
    for f in feasts:
        healed.update(f["healed"])
    feast_rows = [
        {
            "pull": f["pull"],
            "t": f["t"],
            "hits": [len(h["who"]) for h in f["hits"]],
            "raid": [h["raid"] for h in f["hits"]],
            "burst": f["burst"],
            "burst_t": f["burst_t"],
            "cut": f["cut"],
            "healed": {k: round(v / 1e6, 1) for k, v in f["healed"].items() if v >= 5e4},
        }
        for f in feasts
    ]

    # ---- snakes ----
    sn = defaultdict(lambda: {"n": 0, "snake": 0, "all": 0, "focus": 0, "first": [], "hit": 0, "secs": 0.0})
    for s in a.snakes:
        for n, d in s["dmg"].items():
            if a.roles.get(n) != "dps":
                continue
            x = sn[n]
            x["n"] += 1
            x["snake"] += d["snake"]
            x["all"] += d["all"]
            x["focus"] += d["focus"]
            x["secs"] += d["secs"]
            if d["first"] is not None:
                x["first"].append(d["first"])
                x["hit"] += 1
    snake_rows = sorted(
        (
            {
                "name": n,
                "emergences": x["n"],
                "hit": x["hit"],
                "share": round(100 * x["snake"] / x["all"], 1) if x["all"] else 0,
                "focus": round(100 * x["focus"] / x["snake"], 1) if x["snake"] else 0,
                "react": round(med(x["first"]), 1) if x["first"] else None,
                # damage per second alive while snakes were up
                "dps": round(x["all"] / x["secs"]) if x["secs"] else 0,
                "snake_dps": round(x["snake"] / x["secs"]) if x["secs"] else 0,
            }
            for n, x in sn.items()
        ),
        key=lambda r: -r["share"],
    )
    snake_waves = [{k: s[k] for k in ("pull", "n", "t", "deaths", "alive_after", "spits", "window")} for s in a.snakes]

    payload = {
        "pulls": pulls,
        "tmax": max(p["dur"] for p in pulls),
        "players": players,
        "groups": [[g, GROUP_LABEL[g], GROUP_COLOR[g]] for g in DEATH_ORDER],
        "marks": MARKS,
        "cls_color": CLASS_COLOR,
        "cls_name": {c: CLASS_NAME.get(c, c) for c in CLASSES},
        "deaths": death_rows,
        "kicks": {"patterns": patterns, "missed": missed, "grid": grid, "seqs": seqs, "seq_unread": seq_unread, "seq_cut": seq_cut,
                  "plan": a.kick_plan(plan) if plan else None,
                  "causes": a.burst_causes(plan) if plan else None,
                  "cause_label": CAUSE_LABEL, "cause_order": CAUSE_ORDER},
        "dsoak": a.double_soaks,
        "spots": S.SPOTS,
        "waves": wave_rows,
        "globules": glob_rows,
        "ev_label": S.EV_LABEL,
        "shields": {"cls": dict(shields_cls), "spell": {k: dict(v) for k, v in shields_spell.items()}},
        "feast": {n: fp[n] for n in roster},
        "feasts": feast_rows,
        "healed": {k: round(v / 1e6, 1) for k, v in healed.items()},
        "snakes": snake_rows,
        "snake_waves": snake_waves,
    }
    return payload, {"a": a, "causes": payload["kicks"]["causes"], "dsoak": payload["dsoak"], "pulls": pulls, "patterns": patterns, "missed": missed, "glob": glob_rows,
                     "waves": waves, "feasts": feasts, "fp": fp, "healed": healed, "snakes": snake_rows,
                     "deaths": death_rows, "shields_cls": shields_cls}


def tokens(
    a: Analysis, payload: dict, raw: dict, *, date_long: str, night_title: str,
    prev: dict | None = None, prev_date: str | None = None,
) -> dict:
    pulls = raw["pulls"]
    t: dict = {}
    t["report"] = a.code
    t["boss"] = "The Twin Fangs"
    t["difficulty"] = {3: "Normal", 4: "Heroic", 5: "Mythic"}.get(a.difficulty, "Mythic")
    t["zone"] = (a.meta.get("zone") or {}).get("name", "")
    t["pulls"] = len(pulls)
    t["raiders"] = len(a.roles)
    t["date_long"] = date_long
    t["night_title"] = night_title
    kills = [p for p in pulls if p.get("kill")]
    wipes = [p for p in pulls if not p.get("kill")]
    t["wipes_n"] = len(wipes)
    best = min(wipes or pulls, key=lambda p: p["pct"])
    t["best_pull"] = best["pull"]
    t["best_pct"] = fmt(best["pct"], 1)
    t["best_vex"] = fmt(best["vex"] or 0, 0)
    t["best_ith"] = fmt(best["ith"] or 0, 0)
    t["best_dur"] = f"{int(best['dur'] // 60)}:{int(best['dur'] % 60):02d}"
    if kills:
        k = kills[0]
        t["best_tile"] = (
            f'<span class="lab">Kill</span><span class="n">pull {k["pull"]}</span>'
            f'<span class="muted">{int(k["dur"] // 60)}:{int(k["dur"] % 60):02d}; best wipe {fmt(best["pct"])}%</span>'
        )
        t["best_meta"] = f"killed on pull {k['pull']}"
        t["outcome"] = f"killed on pull {k['pull']}"
    else:
        t["best_tile"] = (
            f'<span class="lab">Best pull</span><span class="n">{t["best_pct"]}<small>%</small></span>'
            f'<span class="muted">pull {best["pull"]}, {t["best_dur"]}: Vexhul {t["best_vex"]}%, Ithraz {t["best_ith"]}%</span>'
        )
        t["best_meta"] = f"best: {t['best_pct']}% on pull {best['pull']}"
        t["outcome"] = f"best {t['best_pct']}%"
    t["tmax"] = round(payload["tmax"])
    t["boss_minutes"] = round(sum(p["dur"] for p in pulls) / 60)
    t["cascade_n"] = CASCADE_N
    t["cascade_s"] = round(CASCADE_S)

    # where pulls ended
    ended = Counter(p["wipe_cause"] for p in pulls if p["wipe_cause"])
    t["ended_top"] = names_or((f"{prose_label(g)} ({n})" for g, n in ended.most_common()), "no wipe at all")
    t["ended_burst"] = ended.get("burst", 0)
    # Where each pull broke, by the stretch of the boss script its wipe (or its
    # end, for a pull with no cascade) fell in. Times are the Mythic script.
    stretches = [
        (36, "before the first Rouse"),
        (61, "the first Rouse"),
        (97, "the first Feast and its founts"),
        (122, "the second Rouse"),
        (140, "the second Feast"),
        (1e9, "after Submerge"),
    ]
    broke: dict[str, list[int]] = {}
    for p in wipes:
        at = p["wipe"] if p["wipe"] is not None else p["dur"]
        label = next(lab for end, lab in stretches if at < end)
        broke.setdefault(label, []).append(p["pull"])
    parts = []
    for _, lab in stretches:
        if lab in broke:
            ps = broke[lab]
            parts.append(f"{lab} ({'pull' if len(ps) == 1 else 'pulls'} {names(str(x) for x in ps)})")
    t["walls"] = names_or(parts, "nowhere: nothing wiped")
    # reached the second Rouse: it started before the wipe did
    reach2 = [p for p in pulls if p["rouses"] >= 2]
    t["reach_r2_line"] = f"{plural(len(reach2), 'pull')} reached the second Rouse." if reach2 else "No pull reached the second Rouse."

    # deaths
    D = raw["deaths"]
    t["pre_deaths"] = sum(d["n"] for d in D)
    t["post_deaths"] = sum(len(p["deaths"]) for p in pulls) - t["pre_deaths"]
    top = top_ties([(d, d["n"]) for d in sorted((d for d in D if d["n"]), key=lambda d: (-d["n"], d["name"]))], 4)
    # the pulls they played only when it differs from the night's count
    t["death_top"] = names_or(
        f"{d['name']} ({d['n']}" + (f" in {d['pulls']} pulls)" if d["pulls"] != len(pulls) else ")") for d, _ in top
    )
    fc = top_ties([(d, d["first"]) for d in sorted((d for d in D if d["first"]), key=lambda d: (-d["first"], d["name"]))], 3)
    t["first_top"] = names_or(f"{d['name']} ({d['first']})" for d, _ in fc)

    def pre_n(p):
        return sum(1 for d in p["deaths"] if p["wipe"] is None or d["t"] < p["wipe"])

    def pre_min(p):
        return (p["wipe"] if p["wipe"] is not None else p["dur"]) / 60

    clean = sum(1 for p in pulls if not pre_n(p))
    t["clean_pulls"] = clean
    t["clean_pulls_line"] = "none had" if clean == 0 else f"{plural(clean, 'pull')} had none"
    late_p = [p for p in pulls if reached_flood(p)]
    early_p = [p for p in pulls if not reached_flood(p)]
    if clean * 2 > len(pulls):
        t["deaths_line"] = (
            f"Most wipes were sudden: {clean} of {len(pulls)} pulls had nobody dead before the wipe started, "
            "so they were lost to one mechanic rather than to players dying one by one."
        )
    elif clean * 2 == len(pulls):
        t["deaths_line"] = f"Half the wipes were sudden: {clean} of {len(pulls)} pulls had nobody dead before the wipe started."
    else:
        t["deaths_line"] = (
            f"Players were dying before most wipes: in {len(pulls) - clean} of {len(pulls)} pulls someone died before the wipe started."
        )
    if late_p and early_p and sum(map(pre_n, late_p)):
        lr = sum(map(pre_n, late_p)) / sum(map(pre_min, late_p))
        er = sum(map(pre_n, early_p)) / sum(map(pre_min, early_p)) if sum(map(pre_min, early_p)) else 0
        t["deaths_line"] += (
            f" Pulls that reached Submerge averaged {fmt(sum(map(pre_n, late_p)) / len(late_p))} deaths before the wipe and the rest "
            f"{fmt(sum(map(pre_n, early_p)) / len(early_p))}, mostly because they ran longer: per minute it is {fmt(lr, 2)} against {fmt(er, 2)}."
        )

    # kicks
    R = a.rouses
    M = raw["missed"]
    t["rouses"] = len(R)
    t["broodlings"] = sum(len(r["adds"]) for r in R)
    t["kicked"] = sum(r["kicked"] for r in R)
    t["bursts"] = sum(r["bursts"] for r in R)
    t["clean_rouses"] = sum(1 for r in R if not r["bursts"])
    t["went_off"] = sum(1 for r in R for b in r["adds"] if b["bursts"])
    t["burst_rouses"] = len(R) - t["clean_rouses"]
    note = (
        f" ({t['bursts']} Bursts in all, since a Broodling nobody kicks keeps casting)" if t["bursts"] > t["went_off"] else ""
    )
    t["went_off_line"] = (
        f"{plural(t['went_off'], 'Broodling')} got a Visceral Burst off{note}, in {t['burst_rouses']} of the {len(R)} Rouses; "
        f"the other {t['clean_rouses']} had none."
        if t["went_off"] else "No Broodling got a Visceral Burst off."
    )
    no_pos = [ad for r in R for ad in r["adds"] if ad["spot"] == "?" or ad["inferred"]]
    t["spot_unknown"] = len(no_pos)
    t["spot_inferred"] = sum(1 for ad in no_pos if ad["inferred"])
    t["spot_side_only"] = sum(1 for ad in no_pos if not ad["inferred"])
    sq = payload["kicks"]["seqs"]
    t["seq_sides"] = len(sq)
    t["seq_repeat"] = sum(1 for x in sq if x["seq"] != "ABCDE")
    su, sc_ = payload["kicks"]["seq_unread"], payload["kicks"]["seq_cut"]
    bits = []
    if su:
        bits.append(f"{su} had a Broodling with no spot")
    if sc_:
        bits.append(f"{sc_} {'was' if sc_ == 1 else 'were'} cut short by the wipe")
    t["seq_other_line"] = (
        f" {plural(su + sc_, 'other side')} could not be read in full: {names(bits)}." if bits else ""
    )
    t["missed_n"] = len(M)
    late = [m["after"] for m in M]
    if len(late) >= 2:
        t["late_line"] = f"Half of the {len(late)} went off {fmt(med(late))} seconds or more after the Rouse began."
    elif late:
        t["late_line"] = f"It went off {fmt(late[0])} seconds after the Rouse began."
    else:
        t["late_line"] = ""
    second = [m for m in M if m["rouse"] % 2 == 0]
    evens = sorted({r["n"] for r in R if r["n"] % 2 == 0})
    t["miss_r2_line"] = (
        f" {len(second)} of the {len(M)} came in a second Rouse at a boss position "
        f"(Rouse {names_or((str(n) for n in evens), '2').replace(' and ', ' or ')})."
        if M and evens else ""
    )
    spot_miss = top_ties(Counter(m["spot"] for m in M if m["spot"] != "?").most_common(), 3)
    t["miss_spots_line"] = (
        "Broodlings went off most often at " + names(f"{s} ({n})" for s, n in spot_miss) + "." if spot_miss else ""
    )
    P = raw["patterns"]
    fixed = [k for k in P if k["label"].startswith("fixed spot")]
    t["fixed_line"] = (
        "Kicking the same spot most of the night (60% or more): "
        + names(f"{k['player']} ({k['top_spot']}, {pct(k['spots'].get(k['top_spot'], 0), sum(k['spots'].values()))}%)" for k in fixed)
        + "."
        if fixed else ""
    )
    # backups kick rarely by design, so they are not listed as rare kickers
    plan = payload["kicks"]["plan"]
    backups = {r["player"] for r in (plan or {}).get("rows", []) if r["role"].startswith(("backup", "centre"))}
    rare = [k for k in P if k["kicks"] < 0.4 * k["rouses"] and k["role"] == "dps" and k["player"] not in backups]
    t["rare_line"] = (
        "Kicked in under 40% of the Rouses they were alive for"
        + (", leaving out the plan's backups" if backups else "")
        + ": " + names(f"{k['player']} ({k['kicks']} of {k['rouses']})" for k in rare)
        + (". Check these against the night's assignments; a player kept on something else will show low here." if not plan else ".")
        if rare else ""
    )
    # Was a kick available? Only when something went off.
    near_n = sum(1 for m in M if m["near"])
    ended_m = [m for m in M if m["ended"]]
    if not M:
        t["kick_ready_para"] = ""
    else:
        lead_in = f"For all {len(M)}" if near_n == len(M) else f"For {near_n} of the {len(M)}"
        line = (
            "<p><b>Was a kick available?</b> For each Broodling that went off, the table at the end of this section lists every "
            "kicker who was alive with their interrupt off cooldown. &ldquo;On that side&rdquo; means a kicker who normally kicks "
            f"the side the Broodling was on. {lead_in}, at least one such kicker was ready. "
        )
        if ended_m and plan:
            pair_of = {sp: g for g in plan.get("groups", []) for sp in g["spots"]}
            descr = []
            for m in ended_m:
                g = pair_of.get(m["spot"])
                who_ = (g.get("flex") or [g.get("early"), g.get("late")]) if g else []
                descr.append(
                    f"{m['spot']} on pull {m['pull']}" + (f" ({names([w for w in who_ if w])}&rsquo;s pair)" if who_ else "")
                )
            line += f"The {plural(len(ended_m), 'Broodling')} that started a wipe: {names(descr)}. "
        elif ended_m:
            near = top_ties(Counter(n for m in ended_m for n in m["near"]).most_common(), 4)
            if near:
                line += (
                    f"In the {plural(len({(m['pull'], m['rouse']) for m in ended_m}), 'Rouse')} where a missed kick started the wipe, "
                    "these kickers had their interrupt ready for the most of those Broodlings on that side: "
                    + names(f"{n} ({plural(c, 'Broodling')})" for n, c in near) + ". "
                )
        line += "The log has no range check, so &ldquo;ready&rdquo; means the cooldown was up, not that the Broodling was in reach.</p>"
        t["kick_ready_para"] = line

    # feast / tainted blood
    F = raw["feasts"]
    t["feasts"] = len(F)
    raid_hits = [(f, i) for f in F for i, h in enumerate(f["hits"]) if h["raid"]]
    thin = [(f, i) for f in F for i, h in enumerate(f["hits"]) if not h["raid"] and len(h["who"]) < 4]
    line = (
        f"{plural(len(raid_hits), 'smash', 'smashes')} went out to the whole raid because too few were in "
        f"{'it' if len(raid_hits) == 1 else 'them'}."
        if raid_hits else "No smash went out to the whole raid."
    )
    if thin:
        line += f" {plural(len(thin), 'more smash', 'more smashes')} had fewer than four in {'it' if len(thin) == 1 else 'them'}."
    t["feast_short_line"] = line
    # the Feast that started each Feast wipe
    fw = []
    for fid in a.ids:
        if a.wipe_cause(fid) == "feast":
            mine = [f for f in F if f["fight"] == fid and f["ts"] <= a.wipe[fid]]
            if mine:
                fw.append(mine[-1])
    fw_raid = [f for f in fw if any(h["raid"] for h in f["hits"])]
    t["fw_n"], t["fw_raid_n"] = len(fw), len(fw_raid)

    def split(f):
        return f"pull {f['pull']} " + " · ".join(("all " + str(len(h["who"]))) if h["raid"] else str(len(h["who"])) for h in f["hits"])

    if fw_raid:
        lead_in = (
            "The Feast that started a wipe" if len(fw) == 1
            else f"All {len(fw)} Feasts that started a wipe" if len(fw_raid) == len(fw)
            else f"{len(fw_raid)} of the {len(fw)} Feasts that started a wipe"
        )
        # the people were there when the other smashes of that Feast had plenty
        spread = [f for f in fw_raid if sum(len(h["who"]) for h in f["hits"] if not h["raid"]) >= 12]
        t["feast_wipe_line"] = (
            f" {lead_in} had a smash go out to the raid (players hit per smash: {'; '.join(split(f) for f in fw_raid)})."
            + (
                f" In {len(spread)} of them the other smashes had 12 or more between them, "
                "so the people were there but not spread across all three."
                if spread else ""
            )
        )
    else:
        t["feast_wipe_line"] = ""
    # by Feast number in the pull: which one fails
    order = defaultdict(lambda: [0, 0])
    for f in F:
        k_ = sum(1 for g in F if g["fight"] == f["fight"] and g["ts"] <= f["ts"])
        order[k_][0] += 1
        order[k_][1] += 1 if (f["burst"] or any(h["raid"] for h in f["hits"])) else 0
    rows = [(k_, n, bad) for k_, (n, bad) in sorted(order.items()) if n >= 3]
    t["feast_order_line"] = (
        " A smash went to the raid or a Tainted Burst went off in "
        + names(f"{bad} of {n} {ordinal(k_)} Feasts" if i == 0 else f"{bad} of {n} {ordinal(k_)}" for i, (k_, n, bad) in enumerate(rows))
        + "."
        if any(bad for _, _, bad in rows) else ""
    )
    t["tainted_bursts"] = sum(1 for f in F if f["burst"])
    fp = raw["fp"]
    never = [n for n, x in fp.items() if x["feasts"] >= 4 and x["soaked"] == 0]
    low = [n for n, x in fp.items() if x["feasts"] >= 4 and 0 < x["soaked"] / x["feasts"] < 0.75]
    if not never and not low:
        t["feast_soak_line"] = "Everyone soaked at least three in four of the Feasts they were alive for."
    else:
        bits = []
        if never:
            bits.append(f"{names(never)} never soaked a Feast they were alive for")
        if low:
            low_s = names(f"{n} ({fp[n]['soaked']} of {fp[n]['feasts']})" for n in low)
            bits.append(f"{low_s} soaked fewer than three in four")
        t["feast_soak_line"] = names(bits) + "."
    # who carries the most globule stacks and sheds the fewest at the Feast
    G = raw["glob"]
    gs = sorted(G, key=lambda g: -g["src"].get("soak", 0))[:3]
    heavy = [g for g in gs if fp.get(g["name"], {}).get("feasts", 0) >= 4
             and fp[g["name"]]["soaked"] / fp[g["name"]]["feasts"] <= 0.8]
    t["feast_heavy_line"] = (
        " " + names(
            f"{g['name']} took {g['src'].get('soak', 0)} globule-soak stacks and skipped "
            f"{fp[g['name']]['feasts'] - fp[g['name']]['soaked']} of {fp[g['name']]['feasts']} Feasts"
            for g in heavy
        ) + "; Feast soaks are the only way to shed stacks."
        if heavy else ""
    )
    H = raw["healed"]
    hh = sorted(((n, v) for n, v in H.items() if a.roles.get(n) == "healer"), key=lambda x: -x[1])
    tot = sum(H.values())
    t["tb_healers"] = names_or((f"{n} ({pct(v, tot)}%)" for n, v in hh), "no healer")
    t["tb_nonhealer"] = pct(sum(v for n, v in H.items() if a.roles.get(n) != "healer"), tot)

    # globules
    W = raw["waves"]
    t["waves"] = len(W)
    LG = a.loose_globules
    t["globules"] = sum(w["globules"] + w["death_globules"] for w in W) + LG["globules"]
    t["glob_soaks"] = sum(w["soaks"] for w in W) + LG["soaks"]
    rest = LG["globules"] - LG["death_globules"]
    t["glob_loose"] = (
        f" Another {LG['globules']} dropped outside those waves: {LG['death_globules']} from players dying away from a wave"
        + (f" and {rest} not tied to a death" if rest else "")
        + "."
        if LG["globules"] else ""
    )
    boom_w = [w for w in W if w["booms"]]
    t["boom_waves"] = len(boom_w)
    t["booms"] = sum(len(w["booms"]) for w in W) + len(LG["booms"])
    ba = a.booms_after_wipe()
    t["booms_after_line"] = (
        ("Another went" if ba == 1 else f"Another {ba} went")
        + " off after a wipe had started, mostly the globules dead players drop: a cost of wiping, not a soak problem."
        if ba else ""
    )
    by_wave = defaultdict(list)
    for w in boom_w:
        by_wave[w["wave"]] += [w["pull"]] * len(w["booms"])
    parts = [f"{'pull' if len(set(ps)) == 1 else 'pulls'} {names(str(x) for x in sorted(set(ps)))} in wave {k}" for k, ps in sorted(by_wave.items())]
    dead_b = [b for b in LG["booms"] if b["from"]]
    other_b = [b for b in LG["booms"] if not b["from"]]
    if dead_b:
        parts.append(
            names(
                f"pull {b['pull']} at {round(b['t'])}s from {b['from']}&rsquo;s globules"
                + (f" ({plural(b['killed'], 'death')} within 1.5s)" if b["killed"] else "")
                for b in dead_b
            )
        )
    if other_b:
        parts.append(names(f"pull {b['pull']} at {round(b['t'])}s" for b in other_b) + " outside a wave")
    t["boom_line"] = (
        f"{plural(t['booms'], 'globule')} exploded unsoaked before a wipe: {'; '.join(parts)}."
        if t["booms"] else "No globule exploded before a wipe."
    )
    t["shield_strips"] = sum(w["stripped"] for w in W)
    t["shield_total"] = sum(w["shielded"] for w in W)
    left = t["shield_total"] - t["shield_strips"]
    t["shield_verdict"] = (
        "The shields were not the problem: " if t["shield_total"] and left <= 0.02 * t["shield_total"] else ""
    )
    t["shield_left_line"] = f" {left} were not." if left > 0.02 * t["shield_total"] else ""
    sh = [w["shielded"] for w in W]
    t["shield_lo"], t["shield_hi"] = (min(sh), max(sh)) if sh else (0, 0)
    sc = raw["shields_cls"]
    t["shield_top"] = names_or(f"{cls_name(c, n)} ({n})" for c, n in sc.most_common(3))
    # tanks are left out of the soak lists
    dps_heal = [g for g in G if a.roles.get(g["name"]) != "tank"]
    nonsoak = [g for g in dps_heal if g["waves"] >= 6 and g["soaked"] / g["waves"] < 0.5]
    t["soak_low"] = names_or(f"{g['name']} ({g['soaked']} of {g['waves']})" for g in sorted(nonsoak, key=lambda g: g["soaked"] / g["waves"]))
    over = top_ties([(g, g["doubles"]) for g in sorted((g for g in G if g["doubles"]), key=lambda g: (-g["doubles"], g["name"]))], 5)
    t["soak_over"] = names_or(f"{g['name']} ({plural(g['doubles'], 'wave')})" for g, _ in over)
    idle = top_ties([(g, g["idle"]) for g in sorted((g for g in dps_heal if g["idle"] >= 2), key=lambda g: (-g["idle"], g["name"]))], 6)
    t["soak_idle"] = names_or(f"{g['name']} ({g['idle']} of {g['boom_waves']})" for g, _ in idle)
    alive_n = [sum(1 for n in a.present[w["fight"]] if a.alive(w["fight"], n, w["ts"])) for w in W]
    t["skip_n"] = max(0, round(med(alive_n)) - 15) if alive_n else 0
    t["alive_med"] = round(med(alive_n)) if alive_n else 0
    t["per_wave_fair"] = f"{15 / t['alive_med']:.2f}" if t["alive_med"] else "&ndash;"
    srcall = Counter()
    for g in G:
        srcall.update(g["src"])
    stot = sum(srcall.values())
    t["ev_total"] = stot
    for k in ("soak", "burst", "emergence", "spit", "cleave", "wave", "flood", "deluge", "other"):
        t[f"ev_{k}"] = srcall.get(k, 0)
        t[f"ev_{k}_pct"] = pct(srcall.get(k, 0), stot)

    def dodge(g):
        return g["src"].get("cleave", 0) + g["src"].get("wave", 0)

    def flood(g):
        return g["src"].get("flood", 0)

    spitters = top_ties([(g, dodge(g)) for g in sorted(G, key=lambda g: (-dodge(g), g["name"])) if dodge(g)], 4)
    t["ev_avoid_top"] = names_or(f"{g['name']} ({n})" for g, n in spitters)
    flooders = top_ties([(g, flood(g)) for g in sorted(G, key=lambda g: (-flood(g), g["name"])) if flood(g)], 4)
    t["ev_flood_top"] = (
        f" Most Vile Flood stacks, from standing in the beam during Submerge: {names_or(f'{g["name"]} ({n})' for g, n in flooders)}."
        if flooders else ""
    )
    t["ev_other_line"] = (
        f" {plural(srcall.get('other', 0), 'stack')} had nothing that could be matched to {'it' if srcall.get('other', 0) == 1 else 'them'}."
        if srcall.get("other") else ""
    )
    # Venom deaths before a wipe started, by the stacks the player carried in
    vd = Counter(d["ev"] for p in pulls for d in p["deaths"] if d["group"] == "venom" and (p["wipe"] is None or d["t"] < p["wipe"]))
    nv = sum(vd.values())
    t["venom_line"] = (
        f"{plural(nv, 'death')} to Eternal Venom ticks before a wipe started: "
        + names(f"{n} at {plural(k, 'stack')}" for k, n in sorted(vd.items(), key=lambda kv: -kv[0]))
        + "."
        if nv else "No deaths to Eternal Venom ticks before a wipe started."
    ) + (" (A Venom death that started a wipe is counted with the wipe causes above.)" if ended.get("venom") else "")

    # snakes
    SW = a.snakes
    skills = [s["deaths"][-1] for s in SW if s["alive_after"] == 0 and s["deaths"]]
    t["emergences"] = len(SW)
    t["snake_kill_med"] = fmt(med(skills))
    t["snake_full"] = len(skills)
    t["snake_spits"] = sum(s["spits"] for s in SW)
    t["snake_spits_med"] = fmt(med([s["spits"] for s in SW]), 0)
    SR = raw["snakes"]
    top = [r for r in SR if r["emergences"] >= 5][:4]
    t["snake_top"] = names_or(f"{r['name']} ({round(r['share'])}%)" for r in top)
    lowr = [r for r in SR if r["emergences"] >= 5 and r["share"] < 10]
    t["snake_low_line"] = (
        "Lowest: " + names(f"{r['name']} ({round(r['share'])}%)" for r in lowr)
        + ". Check these against who was assigned to the snakes before reading them as a problem; a player kept on the bosses will show low here."
        if lowr else ""
    )
    foc = [r["focus"] for r in SR if r["emergences"] >= 5 and r["focus"]]
    mf = med(foc) if foc else None
    if mf is None:
        t["snake_focus_line"] = ""
    elif mf <= 42:
        t["snake_focus_line"] = (
            f"They were cleaved down together: for the median dps, {round(mf)}% of their snake damage went into the "
            "first one to die, about an even split across the three."
        )
    else:
        t["snake_focus_line"] = (
            f"Damage went into one snake at a time: for the median dps, {round(mf)}% of their snake damage went into the first one to die."
        )
    t["flood_pulls"] = plural(sum(1 for p in pulls if reached_flood(p)), "pull")
    gw = [w["globules"] for w in W if w["globules"]]
    # the scheduled drop is the commonest count; a short one is a wave the
    # wipe cut into
    base = Counter(gw).most_common(1)[0][0] if gw else 0
    t["glob_n"] = base
    dw = [w for w in W if w["death_globules"]]
    t["glob_extra_n"] = len(dw)
    t["glob_extra"] = (
        f". Players who died during a wave dropped {sum(w['death_globules'] for w in dw)} more, "
        f"one to three each, two seconds after the death ("
        + "; ".join(f"{names(w['death_droppers'])} on pull {w['pull']}" for w in dw)
        + ")"
        if dw else ""
    )
    # the script, for the Stone Breaker and Stir the Depths cards
    longest = max(pulls, key=lambda p: p["dur"])

    def times(k):
        ts = [m["t"] for m in longest["marks"] if m["k"] == k and m["t"] < 140]
        return ", ".join(f"{round(x)}s" for x in ts)

    stone_d = sum(1 for p in pulls for d in p["deaths"] if d["group"] == "stone" and (p["wipe"] is None or d["t"] <= p["wipe"]))
    t["stone_times"] = times("stone")
    t["stone_line"] = (
        f"It killed {plural(stone_d, 'player')} before or at the start of a wipe and started {plural(ended.get('stone', 0), 'wipe')}."
        if stone_d else "Nobody died to it before a wipe."
    )
    t["stir_times"] = times("waves")
    t["plan_line"] = plan_line(payload["kicks"]["plan"])
    sk = (payload["kicks"]["plan"] or {}).get("skipped", 0)
    t["plan_skipped_line"] = (
        f", and so are {sk} that came after one on the same side, since the unplaced one may have been the first in their pair"
        if sk else ""
    )
    t["plan_hidden"] = "" if payload["kicks"]["plan"] else " hidden"
    t["causes_hidden"] = "" if payload["kicks"]["causes"] else " hidden"
    t["cause_line"] = cause_line(payload["kicks"]["causes"])
    t["dsoak_line"] = dsoak_line(payload["dsoak"])
    t["dsoak_window"] = f"{payload['dsoak']['window']:g}"
    t["after_sub_card"] = after_submerge(pulls)
    t["lead"] = lead_points(a, pulls, raw, t, ended, prev, prev_date)
    return t


def cause_line(rows: list[dict] | None) -> str:
    """One paragraph on why the Broodlings that went off weren't kicked."""
    if not rows:
        return "No Broodling got a Visceral Burst off before a wipe."
    c = Counter(r["cause"] for r in rows)
    g = Counter(r["group"] for r in rows)
    wiped = [r for r in rows if r["ended"]]
    out = (
        f"{plural(len(rows), 'Broodling')} finished a Visceral Burst before a wipe"
        + (f", and the Rouse {'they were' if len(wiped) > 1 else 'it was'} in started the wipe for {len(wiped)} of them" if wiped else "")
        + ". By cause: "
        + names(f"{CAUSE_LABEL[k][0].lower()} ({n})" for k, n in sorted(c.items(), key=lambda kv: (-kv[1], CAUSE_ORDER.index(kv[0]))))
        + ". By group: "
        + names(f"{k} ({n})" for k, n in g.most_common())
        + ". "
    )
    if c.get("early"):
        out += (
            "&ldquo;Kicked before it began casting&rdquo; means the interrupt landed a fraction of a second before the "
            "Broodling started its cast, so there was nothing to interrupt and the kick went on cooldown. "
        )
    if c.get("spent"):
        out += (
            "&ldquo;Out of kicks&rdquo; is a third or fourth Broodling on a pair whose kickers had already, correctly, used "
            "their interrupts on that pair&rsquo;s earlier ones: that one was the backup&rsquo;s, and the row says what the backups were doing. "
        )
    return out


def dsoak_line(d: dict) -> str:
    """One paragraph on deaths to soaking a second globule too soon."""
    dd = d["deaths"]
    if not dd:
        return f"Nobody died to a second globule within {d['window']:g} seconds of a first."
    pre = [r for r in dd if r["when"] in ("pre", "start")]
    single_pre = [r for r in d["single"] if r["when"] in ("pre", "start")]
    started = [r for r in dd if r["when"] == "start"]
    top = [p for p in d["players"] if p["pre"] + p["start"] + p["wipe"]][:4]
    out = (
        f"One globule soak takes most of a health bar, so a second one inside {d['window']:g} seconds, before the healers have "
        f"caught up, kills. {plural(len(dd), 'player')} died that way, {len(pre)} of them before a wipe or as its first death"
        + (f" ({plural(len(started), 'wipe')} started with one)" if started else "")
        + f". That is {len(pre)} of the {len(pre) + len(single_pre)} soak deaths before a wipe; the other {len(single_pre)} died to a single globule. "
        + f"The median gap between the two soaks was {statistics.median(r['gap'] for r in dd):.1f} seconds. "
        + "Most: " + names(f"{p['player']} ({p['pre'] + p['start'] + p['wipe']})" for p in top) + "."
    )
    return out


def plan_line(plan: dict | None) -> str:
    """One paragraph on how the night went against the kick plan."""
    if not plan or not plan["rows"]:
        return ""
    rows = plan["rows"]
    main = [r for r in rows if r["role"].startswith(("early", "late")) and r["theirs"] >= 10]
    theirs = sum(r["theirs"] for r in rows)
    kicked = sum(r["kicked"] for r in rows)
    by_pair: dict[str, list] = {}
    for r in rows:
        if r["role"].split(" ")[0] in ("early", "late", "backup", "shared"):
            v = by_pair.setdefault(r["role"].split(" ", 1)[1], [0, 0, []])
            v[0] += r["kicked"]
            v[1] += r["theirs"]
            v[2].append(r)
    pairs = sorted(((k / n, p, rs) for p, (k, n, rs) in by_pair.items() if n), key=lambda x: -x[0])
    out = f"{kicked} of the {theirs} placed Broodlings ({pct(kicked, theirs)}%) were kicked by the player the plan gave them to. "
    if len(pairs) > 1:
        out += (
            f"Best-kept pair: {pairs[0][1]} ({round(100 * pairs[0][0])}% kicked by the assigned player); "
            f"least: {pairs[-1][1]} ({round(100 * pairs[-1][0])}%). "
        )
        _, pair, rs = pairs[-1]
        mates = {r["player"] for r in rs}
        swaps = sorted(((c, n, r["player"]) for r in rs for n, c in r["lost_to"] if n in mates), key=lambda x: -x[0])
        if swaps and swaps[0][0] >= 5:
            out += (
                f"On {pair} the kicks moved between {names(sorted(mates))} with no settled order: "
                + names(f"{n} took {c} of {o}&rsquo;s" for c, n, o in swaps[:3])
                + f". That is a spot pair the {len(mates)} of them need to settle, not one player&rsquo;s miss. "
            )
    tight = sorted(main, key=lambda r: -r["kicked"] / r["theirs"])
    if tight:
        out += "Kicked most of their own: " + names(f"{r['player']} ({r['kicked']} of {r['theirs']})" for r in tight[:3]) + ". "
    backs = sorted((r for r in rows if r["role"].startswith(("backup", "centre")) and r["helped"]), key=lambda r: -r["helped"])
    if backs:
        out += "Backups filling in: " + names(f"{r['player']} ({r['helped']})" for r in backs[:4]) + "."
    return out


def after_submerge(pulls) -> str:
    """The card for what comes after Submerge, read off the longest pull."""
    longest = max(pulls, key=lambda p: p["dur"])
    fl = next((m["t"] for m in longest["marks"] if m["k"] == "flood"), None)
    if fl is None or not any(reached_flood(p) for p in pulls):
        return ""
    after = {}
    for m in longest["marks"]:
        if m["t"] > fl and m["k"] in ("globules", "rouse", "feast") and m["k"] not in after:
            after[m["k"]] = m["t"]
    seq = [f"{lab} at {round(after[k])}s" for k, lab in (("globules", "globules"), ("rouse", "Rouse"), ("feast", "Feast")) if k in after]
    if not seq:
        return ""
    return (
        "<div><b>After Submerge</b>The bosses surface in a corner and the cycle starts again: "
        + names(seq)
        + f", read off pull {longest['pull']}. The Rouse spots move with the bosses.</div>"
    )


def lead_points(a, pulls, raw, t, ended, prev, prev_date) -> str:
    """The night in a few lines, for the top of the page. Each point is short
    and the section below has the detail."""
    out = []
    n = len(pulls)
    wipes = [p for p in pulls if not p.get("kill")]
    kills = [p for p in pulls if p.get("kill")]
    best = min(wipes or pulls, key=lambda p: p["pct"])
    h = n // 2
    # 1. progress
    if kills:
        line = f"<b>Progress.</b> Killed on pull {kills[0]['pull']}."
    else:
        line = (
            f"<b>Progress.</b> Best pull {fmt(best['pct'])}% on pull {best['pull']} "
            f"(Vexhul {fmt(best['vex'] or 0, 0)}%, Ithraz {fmt(best['ith'] or 0, 0)}%)."
        )
        late = [p for p in pulls if reached_flood(p) and p["vex"] is not None and p["ith"] is not None]
        if late:
            gap = med([p["ith"] - p["vex"] for p in late])
            if abs(gap) >= 5:
                hi, lo = ("Ithraz", "Vexhul") if gap > 0 else ("Vexhul", "Ithraz")
                line += f" On the pulls that reached Submerge, {hi} ended a median {fmt(abs(gap), 0)} points higher than {lo}."
    if h >= 3:
        line += (
            f" Median boss health at the wipe went from {fmt(med([p['pct'] for p in pulls[:h]]))}% in pulls 1&ndash;{h} "
            f"to {fmt(med([p['pct'] for p in pulls[h:]]))}% in pulls {h + 1}&ndash;{n}."
        )
    after = [p for p in wipes if p["pull"] > best["pull"]]
    if len(after) >= 4 and not kills:
        early = [p for p in after if (p["wipe"] if p["wipe"] is not None else p["dur"]) < 125]
        line += f" None of the {len(after)} later pulls got the bosses below {fmt(min(p['pct'] for p in after))}%"
        line += (
            f"; {len(early)} of them died before 125s, each to {'a different' if len({p['wipe_cause'] for p in early}) == len(early) else 'an'} early mechanic."
            if early else "."
        )
    out.append(line)
    # 2. against the last night
    if prev:
        cur = {
            "burst_wipes": t["ended_burst"],
            "bursts_per_rouse": t["bursts"] / t["rouses"] if t["rouses"] else 0,
            "submerge": sum(1 for p in pulls if reached_flood(p)),
            "med_end": round(med([p["wipe"] if p["wipe"] is not None else p["dur"] for p in pulls])),
            "tainted_wipes": ended.get("tainted", 0),
        }
        out.append(
            f"<b>Against {prev_date}.</b> Best pull {fmt(prev['best'])}% &rarr; {fmt(best['pct'])}%. "
            f"Wipes started by a missed kick: {prev['burst_wipes']} of {prev['pulls']} &rarr; {cur['burst_wipes']} of {n}. "
            f"Wipes started by a Tainted Burst: {prev['tainted_wipes']} &rarr; {cur['tainted_wipes']}. "
            f"Visceral Bursts per Rouse: {fmt(prev['bursts_per_rouse'], 2)} &rarr; {fmt(cur['bursts_per_rouse'], 2)}. "
            f"Reached Submerge: {prev['submerge']} of {prev['pulls']} &rarr; {cur['submerge']} of {n}. "
            f"Median time to the wipe: {prev['med_end']}s &rarr; {cur['med_end']}s."
        )
    # 3. deaths feed the wipe
    glob = [p for p in pulls if p["wipe_cause"] in ("globule", "soak")]
    if len(glob) >= 3:
        soak_n = sum(1 for p in glob if p["wipe_cause"] == "soak")
        fed = [p for p in glob if any(p["wipe"] - 15 <= d["t"] < p["wipe"] for d in p["deaths"])]
        line = (
            f"<b>Deaths feed the wipe.</b> {plural(len(glob), 'wipe')} began with a globule death "
            f"({soak_n} soaking one, {len(glob) - soak_n} an explosion)"
        )
        if fed:
            line += (
                f"; in {len(fed)} of them another player had died in the 15 seconds before, "
                "and the globules a dead player drops have to be soaked too"
            )
        line += "."
        fd = [(p, d) for p in pulls for d in p["deaths"] if d["group"] == "flood" and (p["wipe"] is None or d["t"] < p["wipe"])]
        if fd:
            quick = {p["pull"] for p, d in fd if p["wipe"] is not None and p["wipe"] - d["t"] <= 15}
            line += (
                f" Vile Flood killed {plural(len(fd), 'player')} before a wipe, in {plural(len({p['pull'] for p, _ in fd}), 'pull')}"
                + (f"; in {len(quick)} of them the wipe followed within 15 seconds." if quick else ".")
            )
        out.append(line)
    # 4. the dead's globules left unsoaked
    LG = a.loose_globules
    dead_b = [b for b in LG["booms"] if b["from"]]
    if dead_b:
        out.append(
            f"<b>Dead players&rsquo; globules.</b> {plural(len(dead_b), 'explosion')} before a wipe came from a dead player&rsquo;s "
            f"globules nobody soaked, about 12 seconds after the death"
            + (f", and {plural(sum(b['killed'] for b in dead_b), 'death')} came within 1.5 seconds of them" if sum(b["killed"] for b in dead_b) else "")
            + ". Someone has to pick those up within about ten seconds."
        )
    # 5. the first globule wave after Submerge
    W = raw["waves"]
    flood_t = {p["pull"]: next((m["t"] for m in p["marks"] if m["k"] == "flood"), None) for p in pulls}
    post = [w for w in W if flood_t.get(w["pull"]) is not None and w["t"] > flood_t[w["pull"]]]
    post = [w for w in post if w is min((x for x in post if x["pull"] == w["pull"]), key=lambda x: x["t"])]
    w2 = [w for w in W if w["wave"] == 2]

    def deaths_after(w):
        p = next(p for p in pulls if p["pull"] == w["pull"])
        return [d for d in p["deaths"] if w["t"] <= d["t"] <= w["t"] + 20 and (p["wipe"] is None or d["t"] <= p["wipe"])]

    if len(post) >= 3 and w2:
        dp = sum(len(deaths_after(w)) for w in post)
        d2 = sum(len(deaths_after(w)) for w in w2)
        if dp / len(post) > d2 / len(w2):
            hit = sum(1 for w in post if deaths_after(w))
            out.append(
                f"<b>The globule wave after Submerge.</b> {plural(len(post), 'pull')} reached it (around {round(med([w['t'] for w in post]))}s); "
                f"{hit} lost someone in the 20 seconds after it, {fmt(dp / len(post))} deaths a pull against "
                f"{fmt(d2 / len(w2))} in the second wave."
            )
    # 6. Feast
    if t["fw_raid_n"]:
        fw, fr = t["fw_n"], t["fw_raid_n"]
        which = "In the Feast wipe" if fw == 1 else f"In all {fw} Feast wipes" if fr == fw else f"In {fr} of the {fw} Feast wipes"
        out.append(f"<b>Feast.</b> {which} a smash went out to the whole raid because too few were in it.{t['feast_order_line']}")
    # 7. kicks: the trend in the night, and which Broodlings still go off
    R = a.rouses
    M = raw["missed"]
    if M and len(R) >= 8:
        half = sorted({r["pull"] for r in R})
        cut_p = pulls[h - 1]["pull"] if h else 0
        r1 = [r for r in R if r["pull"] <= cut_p]
        r2 = [r for r in R if r["pull"] > cut_p]
        line = f"<b>Kicks.</b> {plural(t['went_off'], 'Broodling')} went off before a wipe."
        if r1 and r2:
            b1 = sum(r["bursts"] for r in r1) / len(r1)
            b2 = sum(r["bursts"] for r in r2) / len(r2)
            line += f" Bursts per Rouse: {fmt(b1, 2)} in pulls 1&ndash;{cut_p}, {fmt(b2, 2)} after."
        second = [m for m in M if m["rouse"] % 2 == 0]
        late45 = [m for m in second if m["spawn_rank"] >= 7]
        if len(second) >= 4 and len(late45) * 2 >= len(second):
            line += (
                f" In the second Rouse at a boss position, {len(late45)} of {len(second)} were the 4th or 5th Broodling on a side, "
                "the ones that can land on a used spot: a job to call for the backups."
            )
        C = raw.get("causes")
        if C:
            cc = Counter(r["cause"] for r in C)
            k, c = sorted(cc.items(), key=lambda kv: (-kv[1], CAUSE_ORDER.index(kv[0])))[0]
            line += f" Commonest reason: {CAUSE_LABEL[k][0].lower()} ({c} of {len(C)})."
            if cc.get("early"):
                line += f" {plural(cc['early'], 'kick')} landed just before the Broodling began casting and interrupted nothing."
        out.append(line)
    # double soaks
    DS = raw.get("dsoak") or {}
    dpre = [r for r in DS.get("deaths", []) if r["when"] in ("pre", "start")]
    spre = [r for r in DS.get("single", []) if r["when"] in ("pre", "start")]
    if len(dpre) >= 3:
        st = sum(1 for r in dpre if r["when"] == "start")
        out.append(
            f"<b>Double soaks.</b> {len(dpre)} of the {len(dpre) + len(spre)} globule-soak deaths before a wipe were a second globule "
            f"within {DS['window']:g} seconds of a first" + (f"; {plural(st, 'wipe')} started with one" if st else "") + "."
        )
    # 8. wave-2 explosions
    bw = Counter(w["wave"] for w in W for _ in w["booms"])
    tb = sum(bw.values())
    if tb >= 4:
        k, c = bw.most_common(1)[0]
        if c / tb >= 0.6:
            cut_p = pulls[h - 1]["pull"] if h else 0
            e1 = sum(len(w["booms"]) for w in W if w["wave"] == k and w["pull"] <= cut_p)
            out.append(
                f"<b>Globules.</b> {c} of the {tb} explosions inside a wave came in the {ordinal(k)} wave "
                f"(Blood Torrent at about {round(med([w['t'] for w in W if w['wave'] == k]))}s): "
                f"{e1} in pulls 1&ndash;{cut_p} and {c - e1} after."
            )
    return "".join(f"<li>{x}</li>" for x in out)


def render(payload: dict, tok: dict, template: Path | None = None) -> str:
    src = (template or TEMPLATE).read_text(encoding="utf-8")

    def sub(m):
        key = m.group(1)
        if key not in tok:
            raise KeyError(f"template token {{{{{key}}}}} has no value")
        return str(tok[key])

    out = re.sub(r"\{\{(\w+)\}\}", sub, src)
    return out.replace("__PAYLOAD__", _json(payload))


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
