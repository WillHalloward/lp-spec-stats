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
    ["rouse", "Rouse the Brood + snakes", "var(--crit)"],
    ["ichor", "Coiling Ichor", "var(--cls-Druid)"],
    ["waves", "Stir the Depths", "var(--s1)"],
    ["feast", "Ravenous Feast", "var(--cls-Warlock)"],
    ["storm", "Sanguine Storm", "var(--s2)"],
    ["flood", "Submerge / Vile Flood", "var(--s2)"],
]
CLASS_COLOR = {
    "DeathKnight": "#C41E3A", "DemonHunter": "#A330C9", "Druid": "#FF7C0A", "Evoker": "#33937F",
    "Hunter": "#AAD372", "Mage": "#3FC7EB", "Monk": "#00FF98", "Paladin": "#F48CBA", "Priest": "#E8E8E8",
    "Rogue": "#FFF468", "Shaman": "#0070DD", "Warlock": "#8788EE", "Warrior": "#C69B6D",
}
ROLE_ORDER = {"tank": 0, "healer": 1, "dps": 2}


def names(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def med(xs, default=0.0):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else default


def fmt(x, d=1):
    return f"{x:.{d}f}"


def pct(a, b):
    return round(100 * a / b) if b else 0


def payloads(a: Analysis) -> tuple[dict, dict]:
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
                side = ad["spot"][0] if ad["spot"] != "?" else None
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
                 "t": ad["kick"], "b": ad["bursts"], "bt": ad["burst_t"]}
                for ad in r["adds"]
            ],
        }
        for r in a.rouses
    ]

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
        {k: w[k] for k in ("pull", "wave", "t", "globules", "stripped", "soaks", "booms", "idle")}
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
        "deaths": death_rows,
        "kicks": {"patterns": patterns, "missed": missed, "grid": grid},
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


def tokens(a: Analysis, payload: dict, raw: dict, *, date_long: str, night_title: str) -> dict:
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
    t["ended_top"] = names(f"{GROUP_LABEL[g].lower()} ({n})" for g, n in ended.most_common())
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
    last_r1 = max((p["pull"] for p in first_rouse), default=0)
    t["last_r1"] = last_r1
    reach2 = [p for p in pulls if p["dur"] > 100]
    t["reach_r2"] = len(reach2)
    t["first_r2"] = min((p["pull"] for p in reach2), default="-")

    # deaths
    D = raw["deaths"]
    t["pre_deaths"] = sum(d["n"] for d in D)
    t["post_deaths"] = sum(len(p["deaths"]) for p in pulls) - t["pre_deaths"]
    top = sorted((d for d in D if d["n"]), key=lambda d: (-d["n"], d["name"]))
    t["death_top"] = names(f"{d['name']} ({d['n']})" for d in top[:4])
    fc = sorted((d for d in D if d["first"]), key=lambda d: -d["first"])
    t["first_top"] = names(f"{d['name']} ({d['first']})" for d in fc[:3])
    clean = sum(1 for p in pulls if not [d for d in p["deaths"] if p["wipe"] is None or d["t"] < p["wipe"]])
    t["clean_pulls"] = clean

    # kicks
    R = a.rouses
    t["rouses"] = len(R)
    t["broodlings"] = sum(len(r["adds"]) for r in R)
    t["kicked"] = sum(r["kicked"] for r in R)
    t["bursts"] = sum(r["bursts"] for r in R)
    t["clean_rouses"] = sum(1 for r in R if not r["bursts"])
    t["rouses_ended"] = sum(1 for r in R if r["ended"])
    unknown = sum(1 for r in R for ad in r["adds"] if ad["spot"] == "?")
    t["spot_unknown"] = unknown
    M = raw["missed"]
    t["missed_n"] = len(M)
    t["missed_near"] = sum(1 for m in M if m["near"])
    t["missed_none"] = sum(1 for m in M if not m["near"] and not m["far"])
    late = [m["after"] for m in M]
    t["miss_after_med"] = fmt(med(late))
    t["miss_late_share"] = pct(sum(1 for x in late if x >= 10), len(late))
    spot_miss = Counter(m["spot"] for m in M)
    t["miss_spots"] = names(f"{s} ({n})" for s, n in spot_miss.most_common(3))
    P = raw["patterns"]
    fixed = [k for k in P if k["label"].startswith("fixed spot")]
    t["fixed_kickers"] = names(f"{k['player']} ({k['top_spot']}, {pct(k['spots'].get(k['top_spot'], 0), sum(k['spots'].values()))}%)" for k in fixed)
    sides = [k for k in P if "side" in k["label"]]
    t["side_kickers"] = names(f"{k['player']} ({k['label'].split(',')[0]})" for k in sides)
    rare = [k for k in P if k["kicks"] < 0.4 * k["rouses"] and k["role"] == "dps"]
    t["rare_kickers"] = names(f"{k['player']} ({k['kicks']} of {k['rouses']})" for k in rare)
    # ready kickers on the side, across the Rouses that ended a pull
    near = Counter(n for m in M if m["ended"] for n in m["near"])
    t["near_ready_top"] = names(f"{n} ({c})" for n, c in near.most_common(4))
    t["ended_missed"] = sum(1 for m in M if m["ended"])

    # feast / tainted blood
    F = raw["feasts"]
    t["feasts"] = len(F)
    t["feast_short"] = sum(1 for f in F for h in f["hits"] if len(h["who"]) < 4)
    t["tainted_bursts"] = sum(1 for f in F if f["burst"])
    fp = raw["fp"]
    never = [n for n, x in fp.items() if x["feasts"] >= 4 and x["soaked"] == 0]
    low = [n for n, x in fp.items() if x["feasts"] >= 4 and 0 < x["soaked"] / x["feasts"] < 0.75]
    t["feast_never"] = names(never) or "nobody"
    t["feast_low"] = names(f"{n} ({fp[n]['soaked']} of {fp[n]['feasts']})" for n in low) or "nobody"
    H = raw["healed"]
    hh = sorted(((n, v) for n, v in H.items() if a.roles.get(n) == "healer"), key=lambda x: -x[1])
    tot = sum(H.values())
    t["tb_healers"] = names(f"{n} ({pct(v, tot)}%)" for n, v in hh)
    t["tb_nonhealer"] = pct(sum(v for n, v in H.items() if a.roles.get(n) != "healer"), tot)

    # globules
    W = raw["waves"]
    t["waves"] = len(W)
    t["globules"] = sum(w["globules"] for w in W)
    t["glob_soaks"] = sum(w["soaks"] for w in W)
    boom_w = [w for w in W if w["booms"]]
    t["boom_waves"] = len(boom_w)
    t["booms"] = sum(len(w["booms"]) for w in W)
    t["booms_after"] = a.booms_after_wipe()
    t["boom_list"] = names(f"pull {w['pull']} wave {w['wave']}" for w in boom_w)
    t["shield_strips"] = sum(w["stripped"] for w in W)
    t["shield_total"] = sum(w["globules"] for w in W)
    sc = raw["shields_cls"]
    t["shield_top"] = names(f"{c}s ({n})" for c, n in sc.most_common(3))
    G = raw["glob"]
    nonsoak = [g for g in G if g["waves"] >= 6 and g["soaked"] / g["waves"] < 0.5]
    t["soak_low"] = names(f"{g['name']} ({g['soaked']} of {g['waves']})" for g in sorted(nonsoak, key=lambda g: g["soaked"] / g["waves"]))
    over = sorted((g for g in G if g["extra"]), key=lambda g: -g["extra"])
    t["soak_over"] = names(f"{g['name']} ({g['extra']})" for g in over[:5])
    idle = sorted((g for g in G if g["idle"] >= 2), key=lambda g: -g["idle"])
    t["soak_idle"] = names(f"{g['name']} ({g['idle']} of {g['boom_waves']})" for g in idle[:6])
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
    t["ev_avoid_top"] = names(
        f"{g['name']} ({g['src'].get('spit', 0) + g['src'].get('wave', 0)})" for g in spitters[:4]
        if g["src"].get("spit", 0) + g["src"].get("wave", 0)
    )
    last = [p for p in pulls if p["pull"] == best["pull"]][0]
    venom = [d for d in last["deaths"] if last["wipe"] and d["t"] >= last["wipe"] and d["group"] == "venom"]
    t["best_venom_deaths"] = len(venom)
    t["best_venom_ev"] = names(sorted({str(d["ev"]) for d in venom})) or "-"
    t["best_wipe"] = last["wipe"]

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
    t["snake_top"] = names(f"{r['name']} ({r['share']}%)" for r in top)
    lowr = [r for r in SR if r["emergences"] >= 5 and r["share"] < 10]
    t["snake_low"] = names(f"{r['name']} ({r['share']}%)" for r in lowr) or "nobody"
    t["flood_pulls"] = sum(1 for p in pulls if any(m["k"] == "flood" for m in p["marks"]))
    gw = [w["globules"] for w in W if w["globules"]]
    t["glob_lo"], t["glob_hi"] = (min(gw), max(gw)) if gw else (0, 0)
    t["outcome"] = f"best {t['best_pct']}%"
    return t


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
