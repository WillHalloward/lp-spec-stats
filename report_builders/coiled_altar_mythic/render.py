"""Fill the template: one JSON payload, and a token for every number the prose
says out loud, so the next night regenerates its own sentences."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from . import spells as S
from .analyze import Analysis

TEMPLATE = Path(__file__).parent / "template.html"
CSS = Path(__file__).parents[1] / "twin_fangs" / "template.html"

CLASSES = ["DeathKnight", "DemonHunter", "Druid", "Evoker", "Hunter", "Mage", "Monk", "Paladin", "Priest",
           "Rogue", "Shaman", "Warlock", "Warrior"]
DIFF = {3: "Normal", 4: "Heroic", 5: "Mythic"}
PHASE_LONG = {"P1": "stage one", "P2": "stage two", "INT": "the intermission", "P3": "stage three"}


def payload(a: Analysis) -> dict:
    d = a.build()
    roster = a.roster()
    d["players"] = [
        {"name": n, "cls": r.get("class", ""), "role": r.get("role", ""), "spec": r.get("spec", "")}
        for n, r in sorted(roster.items())
    ]
    d["cls_color"] = {c: f"var(--cls-{c})" for c in CLASSES}
    d["ax_min_alive"] = S.AXE_MIN_ALIVE_MIN
    return d


def _pct(a, b) -> str:
    return f"{round(100 * a / b)}%" if b else "–"


def tokens(a: Analysis, d: dict, *, date_long: str, night_title: str) -> dict:
    pulls = d["pulls"]
    counted = [p for p in pulls if not p["reset"]]
    best = max(pulls, key=lambda p: (["P1", "P2", "INT", "P3"].index(p["reached"]), -p["pct"]))
    reached = {k: sum(1 for p in counted if p["reached"] == k) for k in ("P1", "P2", "INT", "P3")}
    ex = d["orbs"]["explosions"]
    ex_pre = [e for e in ex if e["before_wipe"]]
    ex_pulls = sorted({e["pull"] for e in ex})
    gw = [w for w in d["guillotine"]["windows"] if not w["after_wipe"]]
    g_miss = [w for w in gw if w["missed"]]
    g_all_miss = [w for w in d["guillotine"]["windows"] if w["missed"]]
    g_soak_deaths = [x for x in d["guillotine"]["deaths"] if x["soaked"]]
    veil = [w for w in d["veil"]["windows"] if not w["after_wipe"] and not w["open"]]
    veil_broken = [w for w in veil if w["broken"]]
    veil_res = [w for w in veil if w["resolved"]]
    times = sorted(w["secs"] for w in veil_broken)
    fd = [x for x in d["frontals"]["deaths"] if x["before_wipe"]]
    fd_tank = [x for x in fd if x["tank"]]
    adds = [x for x in d["adds"]["adds"] if not x["after_wipe"]]
    killed = [x for x in adds if x["killed"]]
    ax1, ax2 = d["axes"]["P1"], d["axes"]["P2"]
    duration = sum(p["dur"] for p in pulls)

    def trend(rows):
        # ticks against the night's own rate for the same seconds, so the halves
        # compare like with like however long their pulls ran
        rows = [r for r in rows if r["expected"] and r["alive_min"] >= S.AXE_MIN_ALIVE_MIN]
        h = len(rows) // 2
        if not h:
            return "–", "–"
        f = lambda L: sum(r["ticks"] for r in L) / sum(r["expected"] for r in L)
        return f"{f(rows[:h]):.2f}", f"{f(rows[h:]):.2f}"

    t1a, t1b = trend(ax1["pulls"])
    t2a, t2b = trend(ax2["pulls"])
    shield = max((w["absorbed"] for w in veil_broken), default=0)

    # the intermission; every token has a value even on a night that never got there
    ir = d["intermission"]["rows"]
    ic = [r for r in ir if not r["after_wipe"]]
    med = lambda L: sorted(L)[len(L) // 2] if L else None
    i_missed = sum(r["missed"] for r in ic)
    i_frag = sum(r["missed"] + r["blocked"] for r in ic)
    i_dps = med([r["dps"] for r in ic])
    z_max = med([r["max_hp"] for r in ic])
    m_pct = med([x["malacrass_pct"] for r in ir for x in r["reclaims"] if x["malacrass_pct"]])
    z_ends = sorted(r["z_end"] for r in ic if r["z_end"] is not None)
    i_tok = {
        "int_pulls": len(ir),
        "int_clean": len(ic),
        "int_missed": i_missed,
        "int_fragments": i_frag,
        "int_fragments_each": med([r["missed"] + r["blocked"] for r in ic]) or "–",
        "int_secs": f"{med([r['secs'] for r in ir]):.0f}" if ir else "–",
        "int_regen_pct": f"{med([r['regen_pct'] for r in ic]):.0f}" if ic else "–",
        "int_z_best": f"{z_ends[0]:.0f}" if z_ends else "–",
        "int_z_worst": f"{z_ends[-1]:.0f}" if z_ends else "–",
        "int_dps": f"{i_dps / 1e6:.1f}M" if i_dps else "–",
        "int_missed_secs": f"{0.10 * z_max / i_dps:.0f}" if i_dps and z_max else "–",
        "int_m_pct": f"{m_pct:g}" if m_pct else "–",
    }
    B = d["intermission"].get("best")
    i_tok.update(
        {
            "int_best_dmg": f"{B['damage'] / 1e6:.0f}M" if B else "–",
            "int_best_pct": f"{B['damage_pct']:.1f}" if B else "–",
            "int_best_z": f"{B['z_end']:.1f}" if B else "–",
            "int_real_pct": f"{B['best_real_damage_pct']:.1f}" if B else "–",
            "int_real_pull": B["best_real_pull"] if B else "–",
            "int_real_z": f"{B['best_real_z_end']:.1f}" if B and B["best_real_z_end"] is not None else "–",
        }
    )
    closest = max((w for w in veil_res), key=lambda w: w["absorbed"], default=None)

    # what ended each pull
    W = d["wipes"]["wipes"]
    pre = d["wipes"]["before"]
    wc = Counter(r["cause"] for r in W).most_common()
    pc = Counter(x["group"] for x in pre).most_common()
    touched = [e for e in ex_pre if e["how"] == "touched"]
    c_tok = {
        "touch_yd": f"{S.ORB_TOUCH_YD:g}",
        "fresh_s": f"{S.ORB_FRESH_MS / 1000:g}",
        "contact_of": len(touched),
        "contact_named": sum(1 for e in touched if e["named"]),
        "false_pct": f"{100 * S.CONTACT_FALSE_RATE:.0f}",
    }
    w_tok = {
        "w_count": len(W),
        "w_top": wc[0][0].lower() if wc else "–",
        "w_top_n": wc[0][1] if wc else 0,
        "w_second": wc[1][0].lower() if len(wc) > 1 else "–",
        "w_second_n": wc[1][1] if len(wc) > 1 else 0,
        "pre_deaths": len(pre),
        "pre_top": pc[0][0] if pc else "–",
        "pre_top_n": pc[0][1] if pc else 0,
        "pre_top_pulls": len({x["pull"] for x in pre if pc and x["group"] == pc[0][0]}),
    }

    return {
        "report": a.code,
        "boss": a.boss,
        "difficulty": DIFF.get(a.difficulty, str(a.difficulty)),
        "zone": "The Venomous Abyss",
        "night_title": night_title,
        "date_long": date_long,
        "pulls": len(pulls),
        "resets": len(pulls) - len(counted),
        "counted": len(counted),
        "raiders": len({n for fid in a.F for n in a.players[fid]}),
        "boss_minutes": round(duration / 60),
        "best_pull": best["pull"],
        "best_phase": PHASE_LONG[best["reached"]],
        "best_pct": f"{best['pct']:.1f}",
        "reached_p1": reached["P1"],
        "reached_p2": reached["P2"] + reached["INT"] + reached["P3"],
        "reached_p3": reached["P3"],
        "outcome": "the kill" if any(p["kill"] for p in pulls) else f"best {best['pct']:.1f}%",
        "headline": "the kill" if any(p["kill"] for p in pulls) else f"best pull into {PHASE_LONG[best['reached']]}",
        # axes
        "ax1_ticks": ax1["ticks"],
        "ax1_bouts": ax1["bouts"],
        "ax1_per_min": f"{ax1['per_min']:.1f}",
        "ax1_first": t1a,
        "ax1_second": t1b,
        "ax2_ticks": ax2["ticks"],
        "ax2_bouts": ax2["bouts"],
        "ax2_per_min": f"{ax2['per_min']:.1f}",
        "ax2_first": t2a,
        "ax2_second": t2b,
        "bout_gap": f"{S.AXE_BOUT_GAP_MS / 1000:.2f}",
        "cascade_n": S.CASCADE_N,
        "w_open": S.WIPE_OPEN_MS // 1000,
        "cascade_s": f"{S.CASCADE_S:g}",
        "reset_s": S.RESET_MAX_SEC,
        "recover_s": f"{S.RECOVER_S:g}",
        "bucket_s": S.AXE_BUCKET_MS // 1000,
        "ax_min_alive": S.AXE_MIN_ALIVE_MIN,
        # orbs
        "explosions": len(ex),
        "explosion_pulls": len(ex_pulls),
        "explosions_pre": len(ex_pre),
        "explosions_touched": sum(1 for e in ex_pre if e["how"] == "touched"),
        "explosions_small": sum(1 for e in ex if e["stacks"] is None),
        "explosions_left": sum(1 for e in ex_pre if e["how"] == "left"),
        "explosion_stacks": S.EXPLOSION_STACKS,
        "hold_s": S.EXPLOSION_HOLD_MS // 1000,
        "deluge_grace": f"{S.DELUGE_GRACE_MS / 1000:.1f}",
        "green": sum(r["green"] for r in d["orbs"]["carriers"]),
        "purple": sum(r["purple"] for r in d["orbs"]["carriers"]),
        # guillotine
        "g_windows": len(gw),
        "g_misses": len(g_miss),
        "g_misses_all": len(g_all_miss),
        "g_soak_deaths": len(g_soak_deaths),
        "g_min_soak": min((len(w["soakers"]) for w in gw if not w["missed"]), default=0),
        "g_median_soak": sorted(len(w["soakers"]) for w in gw)[len(gw) // 2] if gw else 0,
        "plan_absent": sum(r["absent"] for r in (d["guillotine"]["plan"] or [])),
        "plan_windows": sum(1 for w in gw if w["absent"] is not None),
        # frontals
        "f_deaths": len(fd),
        "f_tank": len(fd_tank),
        "f_other": len(fd) - len(fd_tank),
        "f_vuln": sum(1 for x in fd_tank if x["had_vuln"]),
        # veil
        "veils": len(veil),
        "veils_broken": len(veil_broken),
        "veils_resolved": len(veil_res),
        "veil_shield": f"{shield / 1e6:.1f}M" if shield else "–",
        "veil_median": f"{times[len(times) // 2]:.1f}" if times else "–",
        "veil_fastest": f"{times[0]:.1f}" if times else "–",
        "veil_slowest": f"{times[-1]:.1f}" if times else "–",
        "veil_closest": (f"pull {closest['pull']}: {_pct(closest['absorbed'], shield)} of it" if closest and shield else "–"),
        # adds
        "adds": len(adds),
        "adds_killed": len(killed),
        "add_ttk": f"{sorted(x['ttk'] for x in killed)[len(killed) // 2]:.0f}" if killed else "–",
        **i_tok,
        **w_tok,
        **c_tok,
    }


def render(d: dict, tok: dict) -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    css_src = CSS.read_text(encoding="utf-8")
    css = css_src[css_src.index("<link rel=\"stylesheet\""): css_src.index("</style>")]
    src = src.replace("__SHARED_CSS__", css)

    def sub(m):
        key = m.group(1)
        if key not in tok:
            raise KeyError(f"template token {{{{{key}}}}} has no value")
        return str(tok[key])

    out = re.sub(r"\{\{(\w+)\}\}", sub, src)
    return out.replace("__PAYLOAD__", json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
