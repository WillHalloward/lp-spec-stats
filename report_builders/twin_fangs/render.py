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

GROUP_COLOR = {
    "burst": "var(--crit)",
    "tainted": "var(--s5)",
    "feast": "var(--cls-Warlock)",
    "venom": "var(--s3)",
    "globule": "var(--cls-Hunter)",
    "waves": "var(--s1)",
    "snakes": "var(--s4)",
    "ichor": "var(--cls-Druid)",
    "stone": "var(--ink-2)",
    "tank": "var(--muted)",
    "flood": "var(--s2)",
    "attrition": "var(--inter)",
    "other": "var(--rule)",
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
    ["flood", "Submerge / Vile Flood", "var(--s2)"],
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
    "attrition": "Toxic Fumes and attrition",
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
                 "t": ad["kick"], "b": ad["bursts"], "bt": ad["burst_t"],
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
    seqs, seq_unread = [], 0
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
            if len(spots) != 5 or "?" in spots:
                seq_unread += 1
                continue
            m = {}
            seqs.append({"pull": r["pull"], "rouse": r["n"], "side": sd, "spots": spots,
                         "seq": "".join(m.setdefault(x, "ABCDE"[len(m)]) for x in spots)})

    # ---- globules ----
    waves = a.waves
    gl = defaultdict(lambda: {"waves": 0, "soaked": 0, "doubles": 0, "extra": 0, "idle": 0, "boom_waves": 0})
    for w in waves:
        fid = w["fight"]
        for n in a.present[fid]:
            if not a.alive(fid, n, w["ts"]):
                continue
            g = gl[n]
            g["waves"] += 1
            k = w["soakers"].get(n, 0)
            g["soaked"] += 1 if k else 0
            if k > 1:
                g["doubles"] += 1
                g["extra"] += k - 1
            if w["boom_ts"] and any(a.alive(fid, n, b) for b in w["boom_ts"]):
                g["boom_waves"] += 1
                if n in w["idle"]:
                    g["idle"] += 1
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
        {k: w[k] for k in ("pull", "wave", "t", "globules", "death_globules", "death_droppers", "shielded", "stripped", "soaks", "booms", "idle")}
        | {"doubles": [n for n, k in w["soakers"].items() if k > 1]}
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
            "burst": f["burst"],
            "burst_t": f["burst_t"],
            "cut": f["cut"],
            "healed": {k: round(v / 1e6, 2) for k, v in f["healed"].items()},
        }
        for f in feasts
    ]

    # ---- snakes ----
    sn = defaultdict(lambda: {"n": 0, "snake": 0, "all": 0, "focus": 0, "first": [], "hit": 0})
    for s in a.snakes:
        for n, d in s["dmg"].items():
            if a.roles.get(n) != "dps":
                continue
            x = sn[n]
            x["n"] += 1
            x["snake"] += d["snake"]
            x["all"] += d["all"]
            x["focus"] += d["focus"]
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
        "kicks": {"patterns": patterns, "missed": missed, "grid": grid, "seqs": seqs, "seq_unread": seq_unread,
                  "plan": a.kick_plan(plan) if plan else None},
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
    return payload, {"a": a, "pulls": pulls, "patterns": patterns, "missed": missed, "glob": glob_rows,
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
    best = min(pulls, key=lambda p: p["pct"])
    t["best_pull"] = best["pull"]
    t["best_pct"] = fmt(best["pct"], 1)
    t["best_vex"] = fmt(best["vex"] or 0, 0)
    t["best_ith"] = fmt(best["ith"] or 0, 0)
    t["best_dur"] = f"{int(best['dur'] // 60)}:{int(best['dur'] % 60):02d}"
    t["tmax"] = round(payload["tmax"])
    t["boss_minutes"] = round(sum(p["dur"] for p in pulls) / 60)
    t["cascade_n"] = CASCADE_N
    t["cascade_s"] = round(CASCADE_S)

    # where pulls ended
    ended = Counter(p["wipe_cause"] for p in pulls if p["wipe_cause"])
    t["ended_top"] = names_or((f"{prose_label(g)} ({n})" for g, n in ended.most_common()), "no wipe at all")
    t["ended_burst"] = ended.get("burst", 0)
    first_rouse = [p for p in pulls if p["wipe"] and p["wipe_cause"] == "burst" and p["wipe"] < 60]
    second_rouse = [p for p in pulls if p["wipe"] and p["wipe_cause"] == "burst" and 95 < p["wipe"] < 125]
    t["r1_wipes"] = len(first_rouse)
    t["r1_list"] = names(str(p["pull"]) for p in first_rouse)
    t["r2_wipes"] = len(second_rouse)
    t["r2_list"] = names(str(p["pull"]) for p in second_rouse)
    fe = [p for p in pulls if p["wipe_cause"] in ("tainted", "feast")]
    t["feast_wipes"] = len(fe)
    t["feast_list"] = names(str(p["pull"]) for p in fe)
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
    for p in pulls:
        if p.get("kill"):
            continue
        at = p["wipe"] if p["wipe"] is not None else p["dur"]
        label = next(lab for end, lab in stretches if at < end)
        broke.setdefault(label, []).append(p["pull"])
    parts = []
    for _, lab in stretches:
        if lab in broke:
            ps = broke[lab]
            parts.append(f"{lab} ({'pull' if len(ps) == 1 else 'pulls'} {names(str(x) for x in ps)})")
    t["walls"] = names(parts)
    last_r1 = max((p["pull"] for p in first_rouse), default=0)
    t["last_r1"] = last_r1
    # reached the second Rouse: it started before the wipe did
    reach2 = [p for p in pulls if p["rouses"] >= 2]
    t["reach_r2_line"] = (
        f"{plural(len(reach2), 'pull')} reached the second Rouse, the first of them pull {min(p['pull'] for p in reach2)}."
        if reach2 else "No pull reached the second Rouse."
    )

    # deaths
    D = raw["deaths"]
    t["pre_deaths"] = sum(d["n"] for d in D)
    t["post_deaths"] = sum(len(p["deaths"]) for p in pulls) - t["pre_deaths"]
    top = sorted((d for d in D if d["n"]), key=lambda d: (-d["n"], d["name"]))
    # the pulls they played only when it differs from the night's count
    t["death_top"] = names_or(
        f"{d['name']} ({d['n']}" + (f" in {d['pulls']} pulls)" if d["pulls"] != len(pulls) else ")") for d in top[:4]
    )
    fc = sorted((d for d in D if d["first"]), key=lambda d: (-d["first"], d["name"]))
    t["first_top"] = names_or(f"{d['name']} ({d['first']})" for d in fc[:3])

    def pre_n(p):
        return sum(1 for d in p["deaths"] if p["wipe"] is None or d["t"] < p["wipe"])

    clean = sum(1 for p in pulls if not pre_n(p))
    t["clean_pulls"] = clean
    t["clean_pulls_line"] = "none had" if clean == 0 else f"{plural(clean, 'pull')} had none"
    late_p = [p for p in pulls if reached_flood(p)]
    early_p = [p for p in pulls if not reached_flood(p)]
    if clean * 2 >= len(pulls):
        t["deaths_line"] = (
            f"Most wipes were sudden: {clean} of {len(pulls)} pulls had nobody dead before the cascade, "
            "so they were lost to one mechanic rather than to players dying one by one."
        )
    else:
        t["deaths_line"] = (
            f"Players were dying before most wipes: in {len(pulls) - clean} of {len(pulls)} pulls someone died before the cascade."
        )
        if late_p and early_p:
            t["deaths_line"] += (
                f" Pulls that reached Submerge averaged {fmt(sum(map(pre_n, late_p)) / len(late_p))} deaths before the wipe, "
                f"the rest {fmt(sum(map(pre_n, early_p)) / len(early_p))}."
            )

    # kicks
    R = a.rouses
    t["rouses"] = len(R)
    t["broodlings"] = sum(len(r["adds"]) for r in R)
    t["kicked"] = sum(r["kicked"] for r in R)
    t["bursts"] = sum(r["bursts"] for r in R)
    t["clean_rouses"] = sum(1 for r in R if not r["bursts"])
    t["went_off"] = sum(1 for r in R for b in r["adds"] if b["bursts"])
    t["burst_rouses"] = len(R) - t["clean_rouses"]
    t["rouses_ended"] = sum(1 for r in R if r["ended"])
    no_pos = [ad for r in R for ad in r["adds"] if ad["spot"] == "?" or ad["inferred"]]
    t["spot_unknown"] = len(no_pos)
    t["spot_inferred"] = sum(1 for ad in no_pos if ad["inferred"])
    t["spot_side_only"] = sum(1 for ad in no_pos if not ad["inferred"])
    M = raw["missed"]
    sq = payload["kicks"]["seqs"]
    t["seq_sides"] = len(sq)
    t["seq_repeat"] = sum(1 for x in sq if x["seq"] != "ABCDE")
    t["seq_unread"] = payload["kicks"]["seq_unread"]
    t["missed_n"] = len(M)
    late = [m["after"] for m in M]
    if late:
        m_ = med(late)
        t["late_line"] = (
            f"Half of them went off {fmt(m_)} seconds or more into the Rouse, when the first round of kicks was still on cooldown."
            if m_ >= 10 else f"Half of them went off within {fmt(m_)} seconds of the Rouse starting."
        )
    else:
        t["late_line"] = ""
    second = sum(1 for m in M if m["rouse"] % 2 == 0)
    t["miss_r2_line"] = (
        f" {second} of the {len(M)} came in a second Rouse at a boss position (Rouse 2, 4 or 6)." if M else ""
    )
    t["missed_near"] = sum(1 for m in M if m["near"])
    t["missed_near_line"] = (
        f"For all {len(M)}" if M and t["missed_near"] == len(M) else f"For {t['missed_near']} of the {len(M)}"
    )
    t["bursts_note"] = (
        f" ({t['bursts']} Bursts in all, since a Broodling nobody kicks keeps casting)" if t["bursts"] > t["went_off"] else ""
    )
    t["missed_none"] = sum(1 for m in M if not m["near"] and not m["far"])
    spot_miss = Counter(m["spot"] for m in M if m["spot"] != "?")
    t["miss_spots_line"] = (
        "Went off most often at " + names(f"{s} ({n})" for s, n in spot_miss.most_common(3)) + "." if spot_miss else ""
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
        + ": " + names(f"{k['player']} ({k['kicks']} of {k['rouses']})" for k in rare) + "."
        if rare else ""
    )
    # ready kickers on the side, across the Rouses a missed kick ended
    near = Counter(n for m in M if m["ended"] for n in m["near"])
    t["near_ready_line"] = (
        "In the Rouses where a missed kick started the wipe, the kickers most often ready on that side were "
        + names(f"{n} ({c})" for n, c in near.most_common(4)) + "."
        if near else ""
    )

    # feast / tainted blood
    F = raw["feasts"]
    t["feasts"] = len(F)
    short = [(f, i) for f in F for i, h in enumerate(f["hits"]) if len(h["who"]) < 4]
    t["feast_short_line"] = (
        f"{plural(len(short), 'smash', 'smashes')} landed with fewer than four soakers"
        + (f", {sum(1 for f, i in short if i == len(f['hits']) - 1)} of them the last of its Feast" if short else "")
        + "."
    )
    # the Feast that started each Feast wipe: was one smash short?
    fw = []
    for fid in a.ids:
        if a.wipe_cause(fid) in ("feast", "tainted"):
            mine = [f for f in F if f["fight"] == fid and f["ts"] <= a.wipe[fid]]
            if mine:
                fw.append(mine[-1])
    fw_short = [f for f in fw if any(len(h["who"]) < 4 for h in f["hits"])]
    def split(f):
        return f"pull {f['pull']}: " + " · ".join(str(len(h["who"])) for h in f["hits"])

    t["feast_wipe_line"] = (
        (f" All {len(fw)} Feasts that started a wipe" if len(fw_short) == len(fw) else f" {len(fw_short)} of the {len(fw)} Feasts that started a wipe")
        + " had a short smash "
        + 
        f"({names(split(f) for f in fw_short)} soakers), so those Feasts were lost on how the soakers split, not on who turned up."
        if fw_short else ""
    )
    t["tainted_bursts"] = sum(1 for f in F if f["burst"])
    fp = raw["fp"]
    never = [n for n, x in fp.items() if x["feasts"] >= 4 and x["soaked"] == 0]
    low = [n for n, x in fp.items() if x["feasts"] >= 4 and 0 < x["soaked"] / x["feasts"] < 0.75]
    t["feast_never"] = names(never) or "nobody"
    t["feast_low"] = names(f"{n} ({fp[n]['soaked']} of {fp[n]['feasts']})" for n in low) or "nobody"
    if never:
        lead = f"{names(never)} never soaked a Feast they were alive for"
    else:
        lead = "Everyone soaked: nobody missed every Feast they were alive for"
    if low:
        tail = f"only {t['feast_low']} soaked fewer than three in four"
    else:
        tail = "everyone soaked at least three in four"
    t["feast_soak_line"] = f"{lead}, and {tail}"
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
    t["glob_loose"] = (
        f" Another {LG['globules']} dropped outside those waves: {LG['death_globules']} from players dying away from a wave"
        + (f" and {LG['globules'] - LG['death_globules']} from waves the wipe cut short" if LG["globules"] > LG["death_globules"] else "")
        + "."
        if LG["globules"] else ""
    )
    boom_w = [w for w in W if w["booms"]]
    t["boom_waves"] = len(boom_w)
    t["booms"] = sum(len(w["booms"]) for w in W) + len(LG["booms"])
    ba = a.booms_after_wipe()
    t["booms_after_line"] = (
        f"{'Another ' + str(ba) + ' went' if ba != 1 else 'Another went'} off after a wipe had started, mostly the globules dead players drop: a cost of wiping, not a soak problem."
        if ba else ""
    )
    by_wave = defaultdict(list)
    for w in boom_w:
        by_wave[w["wave"]] += [w["pull"]] * len(w["booms"])
    parts = [f"{'pull' if len(set(ps)) == 1 else 'pulls'} {names(str(x) for x in sorted(set(ps)))} in wave {k}" for k, ps in sorted(by_wave.items())]
    if LG["booms"]:
        parts.append(names(f"pull {b['pull']} at {round(b['t'])}s" for b in LG["booms"]) + " outside a wave")
    t["boom_line"] = (
        f"{plural(t['booms'], 'globule')} exploded unsoaked before a wipe: {'; '.join(parts)}."
        if t["booms"] else "No globule exploded before a wipe."
    )
    t["shield_strips"] = sum(w["stripped"] for w in W)
    t["shield_total"] = sum(w["shielded"] for w in W)
    left = t["shield_total"] - t["shield_strips"]
    t["shield_verdict"] = (
        ", so the shields were not the problem" if t["shield_total"] and left <= 0.02 * t["shield_total"]
        else f"; {left} were not"
    )
    sh = [w["shielded"] for w in W]
    t["shield_lo"], t["shield_hi"] = (min(sh), max(sh)) if sh else (0, 0)
    sc = raw["shields_cls"]
    t["shield_top"] = names_or(f"{cls_name(c, n)} ({n})" for c, n in sc.most_common(3))
    G = raw["glob"]
    # tanks are left out of the soak lists
    dps_heal = [g for g in G if a.roles.get(g["name"]) != "tank"]
    nonsoak = [g for g in dps_heal if g["waves"] >= 6 and g["soaked"] / g["waves"] < 0.5]
    t["soak_low"] = names_or(f"{g['name']} ({g['soaked']} of {g['waves']})" for g in sorted(nonsoak, key=lambda g: g["soaked"] / g["waves"]))
    over = sorted((g for g in G if g["doubles"]), key=lambda g: (-g["doubles"], g["name"]))
    t["soak_over"] = names_or(f"{g['name']} ({plural(g['doubles'], 'wave')})" for g in over[:5])
    idle = sorted((g for g in dps_heal if g["idle"] >= 2), key=lambda g: (-g["idle"], g["name"]))
    t["soak_idle"] = names_or(f"{g['name']} ({g['idle']} of {g['boom_waves']})" for g in idle[:6])
    alive_n = [sum(1 for n in a.present[w["fight"]] if a.alive(w["fight"], n, w["ts"])) for w in W]
    t["skip_n"] = max(0, round(med(alive_n)) - 15) if alive_n else 0
    t["alive_med"] = round(med(alive_n)) if alive_n else 0
    srcall = Counter()
    for g in G:
        srcall.update(g["src"])
    stot = sum(srcall.values())
    t["ev_total"] = stot
    for k in ("soak", "burst", "emergence", "spit", "wave", "flood", "deluge", "other"):
        t[f"ev_{k}"] = srcall.get(k, 0)
        t[f"ev_{k}_pct"] = pct(srcall.get(k, 0), stot)
    t["ev_avoidable"] = srcall.get("burst", 0) + srcall.get("spit", 0) + srcall.get("wave", 0) + srcall.get("flood", 0)
    spitters = sorted(G, key=lambda g: -(g["src"].get("spit", 0) + g["src"].get("wave", 0)))
    t["ev_avoid_top"] = names_or(
        f"{g['name']} ({g['src'].get('spit', 0) + g['src'].get('wave', 0)})" for g in spitters[:4]
        if g["src"].get("spit", 0) + g["src"].get("wave", 0)
    )
    t["ev_other_line"] = (
        f" {plural(srcall.get('other', 0), 'stack')} had nothing that could be matched to {'it' if srcall.get('other', 0) == 1 else 'them'}."
        if srcall.get("other") else ""
    )
    # Venom deaths before a wipe, by the stacks the player carried in
    vd = Counter(d["ev"] for p in pulls for d in p["deaths"] if d["group"] == "venom" and (p["wipe"] is None or d["t"] < p["wipe"]))
    nv = sum(vd.values())
    t["venom_line"] = (
        f"{plural(nv, 'player')} died to Eternal Venom ticks before a wipe: "
        + names(f"{n} at {plural(k, 'stack')}" for k, n in sorted(vd.items(), key=lambda kv: (-kv[1], kv[0])))
        + ". Guides put the one-shot at nine."
        if nv else "Nobody died to Eternal Venom ticks before a wipe."
    )

    # snakes
    SW = a.snakes
    kills = [s["deaths"][-1] for s in SW if s["alive_after"] == 0 and s["deaths"]]
    t["emergences"] = len(SW)
    t["snake_kill_med"] = fmt(med(kills))
    t["snake_full"] = len(kills)
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
    t["plan_line"] = plan_line(payload["kicks"]["plan"])
    t["plan_skipped"] = (payload["kicks"]["plan"] or {}).get("skipped", 0)
    t["after_sub_card"] = after_submerge(pulls)
    t["lead"] = lead_points(a, pulls, raw, t, ended, prev, prev_date)
    t["outcome"] = f"best {t['best_pct']}%"
    return t


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
        # in the least-kept pair, how much moved between its own kickers
        _, pair, rs = pairs[-1]
        mates = {r["player"] for r in rs}
        swaps = sorted(
            ((c, n, r["player"]) for r in rs for n, c in r["lost_to"] if n in mates), key=lambda x: -x[0]
        )
        if swaps and swaps[0][0] >= 5:
            out += (
                f"On {pair} the kicks moved between {names(sorted(mates))} with no settled order: "
                + names(f"{n} took {c} of {o}'s" for c, n, o in swaps[:3])
                + ". That reads as a pair to settle between them, not one player's miss. "
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
    n = sum(1 for p in pulls if reached_flood(p))
    if fl is None or not n:
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
        + f", read off pull {longest['pull']}. The Rouse spots move with the bosses. {plural(n, 'pull')} got this far "
        "before the wipe.</div>"
    )


def lead_points(a, pulls, raw, t, ended, prev, prev_date) -> str:
    """The night in a few lines, for the top of the page."""
    out = []
    n = len(pulls)
    best = min(pulls, key=lambda p: p["pct"])
    after = [p for p in pulls if p["pull"] > best["pull"]]
    h = n // 2
    line = f"<b>Progress.</b> Best pull {fmt(best['pct'])}% (pull {best['pull']})."
    if h >= 3:
        line += (
            f" The median pull went from {fmt(med([p['pct'] for p in pulls[:h]]))}% in pulls 1&ndash;{h} "
            f"to {fmt(med([p['pct'] for p in pulls[h:]]))}% in pulls {h + 1}&ndash;{n}."
        )
    if len(after) >= 4:
        line += f" Nothing after pull {best['pull']} beat it: the {len(after)} pulls after it got no lower than {fmt(min(p['pct'] for p in after))}%."
    out.append(line)
    if prev:
        cur = {
            "burst_wipes": t["ended_burst"],
            "bursts_per_rouse": round(t["bursts"] / t["rouses"], 2) if t["rouses"] else 0,
            "submerge": sum(1 for p in pulls if reached_flood(p)),
            "med_end": round(med([p["wipe"] if p["wipe"] is not None else p["dur"] for p in pulls])),
        }
        out.append(
            f"<b>Against {prev_date}.</b> Wipes started by a missed kick: {prev['burst_wipes']} of {prev['pulls']} pulls, now "
            f"{cur['burst_wipes']} of {n}. Visceral Bursts per Rouse: {prev['bursts_per_rouse']} &rarr; {cur['bursts_per_rouse']}. "
            f"Pulls that reached Submerge: {prev['submerge']} &rarr; {cur['submerge']}. "
            f"Median pull until the wipe: {prev['med_end']}s &rarr; {cur['med_end']}s."
        )
    top = ended.most_common(2)
    if top:
        g, k = top[0]
        line = f"<b>What starts the wipes.</b> The first death of the wipe was {prose_label(g)} in {k} of {n} pulls"
        if len(top) > 1:
            line += f", then {prose_label(top[1][0])} ({top[1][1]})"
        late = sum(1 for p in pulls if p["wipe"] is not None and p["wipe"] >= 140)
        line += f". {plural(late, 'pull')} broke after Submerge." if late else "."
        out.append(line)
    W = raw["waves"]
    bw = Counter(w["wave"] for w in W for _ in w["booms"])
    tb = sum(bw.values())
    if tb >= 4:
        k, c = bw.most_common(1)[0]
        if c / tb >= 0.6:
            ts = [w["t"] for w in W if w["wave"] == k]
            out.append(
                f"<b>Globules.</b> {c} of the {tb} explosions inside a wave came in the {ordinal(k)} wave "
                f"(Blood Torrent at about {round(med(ts))}s), in {plural(sum(1 for w in W if w['wave'] == k and w['booms']), 'pull')}."
            )
    if t.get("feast_wipe_line"):
        out.append("<b>Feast.</b>" + t["feast_wipe_line"])
    if t["missed_n"]:
        line = f"<b>Kicks.</b> {plural(t['went_off'], 'Broodling')} got a Visceral Burst off before a wipe.{t['miss_r2_line']}"
        out.append(line)
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
