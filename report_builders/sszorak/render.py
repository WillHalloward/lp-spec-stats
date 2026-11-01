"""Fill the template: payloads as JSON, everything the prose states as a token.

Every number the page says out loud is computed here, so a second prog night on
the same boss regenerates its own sentences rather than inheriting this one's.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

from . import spells as S
from .analyze import GROUP_LABEL, Analysis, death_group, night, players

TEMPLATE = Path(__file__).parent / "template.html"

WORDS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
         8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}

# colour per death group / pull ending, in the template's palette
GROUP_COLOR = {
    "enrage": "var(--fatal)",
    "inter": "var(--s1)",
    "cyst_p1": "var(--s4)",
    "tornado": "var(--s3)",
    "crosswinds": "var(--s5)",
    "virulence": "var(--s2)",
    "mutilate": "var(--crit)",
    "ravage": "var(--cls-Warlock)",
    "tank": "var(--ink-2)",
    "surge": "var(--cls-Druid)",
    "floor": "var(--cls-Hunter)",
    "other": "var(--muted)",
}
ENDED_LABEL = {**GROUP_LABEL, "enrage": "Serpent's Fury enrage"}
DEATH_ORDER = ["inter", "cyst_p1", "tornado", "mutilate", "virulence", "crosswinds", "ravage",
               "surge", "floor", "tank", "other"]


def word(n: int) -> str:
    return WORDS.get(n, str(n))


def names(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def med(xs, default=0.0):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else default


def thirds(rows):
    n = len(rows)
    a, b = round(n / 3), round(2 * n / 3)
    return [rows[:a], rows[a:b], rows[b:]]


def fmt(x, d=1):
    return f"{x:.{d}f}"


def payloads(a: Analysis) -> tuple[dict, dict]:
    R = night(a)
    P = players(a)
    # rage windows, read off the enrages themselves
    long_w = med([r["fury"]["enrage_after"] for r in R if r["fury"]["enrage_after"] and r["fury"]["enrage_after"] > 70])
    short_w = med([r["fury"]["enrage_after"] for r in R if r["fury"]["enrage_after"] and r["fury"]["enrage_after"] <= 70])
    pulls = []
    for r in R:
        mins = r["dur"] / 60
        cut = r["called"] or r["enrage"] or r["dur"]
        # each pop's deadline: the long window when an intermission opens before it would run out
        inter_starts = [i["start"] for i in r["inter"]]
        deadlines = []
        for t in r["fury"]["pops"]:
            w = long_w if any(t < s < t + short_w for s in inter_starts) else short_w
            deadlines.append(round(t + w, 1))
        pulls.append(
            {
                "pull": r["pull"],
                "dur": r["dur"],
                "pct": r["pct"],
                "inters": r["inters"],
                "inters_done": r["inters_done"],
                "ended": r["ended"],
                "called": r["called"] and round(r["called"], 1),
                "cut": round(cut, 1),
                "enrage": r["enrage"],
                "enrage_forced": r["enrage_forced"],
                "under": r["under"] and round(r["under"], 1),
                "walked": r["walked"],
                "tempests": r["tempests"],
                "tornado_hits": r["tornado_hits"],
                "tornado_rate": round(r["tornado_hits"] / r["tempests"], 2) if r["tempests"] else None,
                "xw_sets": r["xw_sets"],
                "xw_flung": r["xw_flung"],
                "xw_rate": round(r["xw_flung"] / r["xw_sets"], 2) if r["xw_sets"] else None,
                "xw_own": r["xw_late"] + r["xw_none"],
                "xw_partner": r["xw_partner"],
                "xw_own_rate": round((r["xw_late"] + r["xw_none"]) / r["xw_sets"], 2) if r["xw_sets"] else None,
                "acc_pops": r["acc_pops"],
                "acc_hit": r["acc_hit"],
                "deaths_live": r["deaths_live"],
                "dpm": round(r["deaths_live"] / (cut / 60), 2) if cut > 0 else 0,
                "deaths": r["deaths"],
                "fury": {**r["fury"], "deadlines": deadlines},
                "inter": r["inter"],
                "mut_double": r["mut_double"],
                "ravage_raid": r["ravage_raid"],
                "first": r["first"],
            }
        )
    # the best pull's schedule, for the timeline
    best = min(R, key=lambda r: r["pct"])
    fid = a.ids[best["pull"] - 1]
    rel = lambda t: round(a.rel(fid, t), 1)  # noqa: E731
    tl = []
    for ab, kind in ((S.RAVAGE_CAST, "ravage"), (S.MUTILATE_CAST, "mutilate"), (S.TEMPEST_CAST, "tempest"),
                     (S.SURGE_CAST, "surge")):
        tl += [{"t": rel(t), "k": kind} for t in a.casts(fid, ab)]
    tl += [{"t": rel(s["t"]), "k": "crosswinds"} for s in a.crosswind_sets(fid)]
    tl += [{"t": rel(t), "k": "fury"} for t in [p["t"] for p in a.fury_pops(fid)[0]]]
    tl += [{"t": rel(p["t"]), "k": "pop"} for p in a.cyst_pops(fid)]
    segs = [{"k": k, "s": rel(s), "e": rel(e)} for k, s, e in a.segments(fid)]
    payload = {
        "pulls": pulls,
        "players": P,
        "groups": [[g, ENDED_LABEL[g], GROUP_COLOR[g]] for g in DEATH_ORDER],
        "ended": {g: [ENDED_LABEL[g], GROUP_COLOR[g]] for g in GROUP_COLOR},
        "timeline": {"pull": best["pull"], "dur": best["dur"], "events": sorted(tl, key=lambda e: e["t"]), "segs": segs},
        "windows": {"long": long_w, "short": short_w},
    }
    return payload, {"R": R, "P": P, "a": a, "best": best}


def tokens(a: Analysis, payload: dict, raw: dict, *, date_long: str, night_title: str) -> dict:
    R, P = raw["R"], raw["P"]
    pulls = payload["pulls"]
    T = thirds(pulls)
    TR = thirds(R)
    best = raw["best"]
    t = {}
    t["report"] = a.code
    t["boss"] = "Sszorak"
    t["difficulty"] = {3: "Normal", 4: "Heroic", 5: "Mythic"}.get(a.difficulty, "Mythic")
    t["zone"] = (a.meta.get("zone") or {}).get("name", "")
    t["pulls"] = len(pulls)
    t["raiders"] = len(a.roles)
    t["date_long"] = date_long
    t["night_title"] = night_title
    t["best_pull"] = best["pull"]
    t["best_pct"] = fmt(best["pct"], 2)
    t["best_dur"] = f"{int(best['dur'] // 60)}:{int(best['dur'] % 60):02d}"
    t["best_inters"] = best["inters"]
    t["boss_minutes"] = round(sum(p["dur"] for p in pulls) / 60)
    t["best_line"] = f"best: {t['best_pct']}% on pull {best['pull']}"

    def span(g):
        return f"{g[0]['pull']}&ndash;{g[-1]['pull']}"

    for i, g in enumerate(T, 1):
        t[f"t{i}"] = span(g)
        t[f"t{i}_med_pct"] = fmt(med([p["pct"] for p in g]), 0)
        t[f"t{i}_best"] = fmt(min(p["pct"] for p in g), 1)
        t[f"t{i}_med_dur"] = round(med([p["dur"] for p in g]))
        tem = sum(p["tempests"] for p in g)
        t[f"t{i}_tor"] = fmt(sum(p["tornado_hits"] for p in g) / tem, 1) if tem else "0"
        xs = sum(p["xw_sets"] for p in g)
        t[f"t{i}_xw"] = fmt(sum(p["xw_flung"] for p in g) / xs, 1) if xs else "0"
        t[f"t{i}_xw_own"] = sum(p["xw_own"] for p in g)
        t[f"t{i}_xw_sets"] = xs
        t[f"t{i}_acc"] = sum(p["acc_pops"] for p in g)
        dc = Counter()
        for p in g:
            dc.update(p["deaths"])
        t[f"t{i}_cyst_dead"] = dc["cyst_p1"]
        t[f"t{i}_tor_dead"] = dc["tornado"]
        t[f"t{i}_xw_dead"] = dc["crosswinds"]
        t[f"t{i}_mut_dead"] = dc["mutilate"]
        t[f"t{i}_vir_dead"] = dc["virulence"]
        t[f"t{i}_inter_dead"] = dc["inter"]
        inters = [x for p in g for x in p["inter"]]
        clean = [x for x in inters if len(x["pops"]) == 3 and not x["double"] and x["died"] <= 1]
        t[f"t{i}_inters"] = len(inters)
        t[f"t{i}_clean"] = len(clean)
        mins = sum(p["cut"] for p in g) / 60
        t[f"t{i}_dpm"] = fmt(sum(p["deaths_live"] for p in g) / mins, 1)
        t[f"t{i}_enrage"] = sum(1 for p in g if p["enrage"] and not p["enrage_forced"])
        t[f"t{i}_n"] = len(g)
        t[f"t{i}_reach"] = sum(1 for p in g if p["inters_done"] >= 1)

    # tornadoes
    all_tem = sum(p["tempests"] for p in pulls)
    t["tempests"] = all_tem
    t["tornado_hits"] = sum(p["tornado_hits"] for p in pulls)
    dc_all = Counter()
    for p in pulls:
        dc_all.update(p["deaths"])
    t["tornado_deaths"] = dc_all["tornado"]
    nt = [p for p in P if p["role"] != "tank" and p["tempests"] >= 20]
    nt.sort(key=lambda p: -p["tornado_rate"])
    t["tor_top"] = names(f"{p['player']} ({fmt(p['tornado_rate'], 2)})" for p in nt[:4])
    t["tor_med"] = fmt(med([p["tornado_rate"] for p in nt]), 2)
    tanks = [p for p in P if p["role"] == "tank"]
    t["tor_tanks"] = names(f"{p['player']} ({fmt(p['tornado_rate'], 2)})" for p in tanks)
    # when tornado hits land relative to the cast
    since = [h["since"] for fid in a.ids for h in a.tornado_hits(fid) if h["since"] is not None]
    t["tor_late_pct"] = round(100 * sum(1 for s in since if s > 15) / len(since)) if since else 0
    t["tor_first10_pct"] = round(100 * sum(1 for s in since if s <= 10) / len(since)) if since else 0

    # cysts in phase one
    acc = [(p["pull"], p["acc_pops"], p["acc_hit"]) for p in pulls if p["acc_pops"]]
    t["acc_total"] = sum(x[1] for x in acc)
    t["acc_pulls"] = len(acc)
    t["acc_pull_list"] = names(str(x[0]) for x in acc)
    t["acc_hit_med"] = round(med([pp["acc_hit"] / pp["acc_pops"] for pp in pulls if pp["acc_pops"]]))
    last_acc = max((x[0] for x in acc), default=0)
    t["acc_last"] = last_acc
    later = [p for p in pulls if p["pull"] > 25]
    t["acc_after25"] = sum(p["acc_pops"] for p in later)
    t["cyst_p1_dead"] = dc_all["cyst_p1"]
    fresh = [x for r in R for x in [r] if r["acc_fresh"]]
    t["acc_fresh"] = sum(r["acc_fresh"] for r in R)

    # intermissions
    inters = [(p["pull"], i, x) for p in pulls for i, x in enumerate(p["inter"], 1)]
    t["inter_n"] = len(inters)
    clean = [x for _, _, x in inters if len(x["pops"]) == 3 and not x["double"] and x["died"] <= 1]
    t["inter_clean"] = len(clean)
    pop_times = [x["pops"] for x in clean]
    t["pop1"] = fmt(med([p[0] for p in pop_times]))
    t["pop2"] = fmt(med([p[1] for p in pop_times]))
    t["pop3"] = fmt(med([p[2] for p in pop_times]))
    dbl = [(pl, i, x) for pl, i, x in inters if x["double"]]
    t["inter_double"] = len(dbl)
    t["inter_double_list"] = names(f"{pl}" + (f" (intermission {i})" if i > 1 else "") for pl, i, _ in dbl)
    t["inter_double_dead"] = sum(x["died"] for _, _, x in dbl)
    short = [(pl, i, x) for pl, i, x in inters if not x["double"] and len(x["pops"]) < 3]
    t["inter_short"] = len(short)
    t["inter_short_list"] = names(str(pl) for pl, _, _ in short)
    t["inter_short_dead"] = sum(x["died"] for _, _, x in short)
    t["inter_dead"] = dc_all["inter"]
    t["inter_dead_pct"] = round(100 * dc_all["inter"] / max(1, sum(dc_all.values())))
    last_bad = max((pl for pl, _, x in inters if x["died"] >= 5), default=0)
    t["inter_last_bad"] = last_bad

    # crosswinds
    t["xw_sets"] = sum(p["xw_sets"] for p in pulls)
    t["xw_flung"] = sum(p["xw_flung"] for p in pulls)
    t["xw_dead"] = dc_all["crosswinds"]
    edge_xw = sum(1 for fid in a.ids for d in a.deaths(fid) if d["cause"] == "edge_crosswinds" and not d["after_call"])
    t["xw_edge"] = edge_xw
    t["xw_clean_sets"] = sum(
        1 for fid in a.ids for s in a.crosswind_sets(fid)
        if len(s["marked"]) >= 6 and not [n for n in s["flung"] if n in s["marked"]]
        and s["t"] < min(x for x in (a.called_at(fid), a.enrage_at(fid), a.F[fid]["endTime"]) if x)
    )
    from .analyze import NEEDS_PARTNER
    t["xw_solo"] = sum(p["xw_solo"] for p in P)
    t["xw_cancelled"] = sum(p["xw_cancelled"] for p in P)
    t["xw_late"] = sum(p["xw_late"] for p in P)
    t["xw_none"] = sum(p["xw_none"] for p in P)
    t["xw_partner"] = sum(p["xw_partner"] for p in P)
    t["xw_knocks"] = sum(p["xw_marked"] for p in P)
    t["xw_own"] = t["xw_late"] + t["xw_none"]
    from .analyze import SOLO_MOVES
    t["solo_moves"] = ", ".join(sorted(SOLO_MOVES))
    t["xw_partner_classes"] = names(sorted(f"{c}s" for c in NEEDS_PARTNER))
    own = [p for p in P if a.cls[p["player"]] not in NEEDS_PARTNER and p["xw_late"] + p["xw_none"] >= 3]
    own.sort(key=lambda p: -(p["xw_late"] + p["xw_none"]))
    t["xw_top"] = names(
        f"{p['player']} ({p['xw_late'] + p['xw_none']} of {p['xw_marked']}: {p['xw_late']} late, {p['xw_none']} with no movement)"
        for p in own[:4]
    )
    solo = sorted((p for p in P if p["xw_solo"] >= 5), key=lambda p: -p["xw_solo"])
    t["xw_soloists"] = names(f"{p['player']} ({p['xw_solo']})" for p in solo[:5])
    dep = [p for p in P if a.cls[p["player"]] in NEEDS_PARTNER]
    t["xw_dep"] = names(f"{p['player']} ({p['xw_partner']} of {p['xw_marked']})" for p in sorted(dep, key=lambda p: -p["xw_partner"]))

    # Serpent's Fury
    W = payload["windows"]
    t["fury_long"] = fmt(W["long"])
    t["fury_short"] = fmt(W["short"])
    from .analyze import FURY_NEED
    t["fury_need"] = FURY_NEED
    t["fury_need_less"] = FURY_NEED - 1
    forced = [p for p in pulls if p["enrage"] and p["enrage_forced"]]
    t["enrage_forced_n"] = len(forced)
    t["enrage_forced_list"] = names(str(p["pull"]) for p in forced)
    t["enrage_all_n"] = sum(1 for p in pulls if p["enrage"])
    enr = [p for p in pulls if p["enrage"] and not p["enrage_forced"]]
    t["enrage_n"] = len(enr)
    t["enrage_list"] = names(str(p["pull"]) for p in enr)
    first_slot = [p for p in enr if p["enrage"] < 180]
    t["enrage_slot3"] = len(first_slot)
    t["enrage_slot3_list"] = names(str(p["pull"]) for p in first_slot)
    mid_slot = [p for p in enr if 180 <= p["enrage"] < 240]
    t["enrage_slot4"] = len(mid_slot)
    t["enrage_slot4_list"] = names(str(p["pull"]) for p in mid_slot)
    late_slot = [p for p in enr if p["enrage"] >= 240]
    t["enrage_slot5"] = len(late_slot)
    t["enrage_slot5_list"] = names(str(p["pull"]) for p in late_slot)
    ok3 = [x for p in pulls for x in p["fury"]["pops"] if 125 < x < 175]
    t["pop3_lo"], t["pop3_hi"] = (fmt(min(ok3)), fmt(max(ok3))) if ok3 else ("-", "-")
    ok3n = [x for x in ok3 if x < 158]
    t["pop3_med"] = fmt(med(ok3n))
    pre2 = [p["fury"]["pops"][1] for p in pulls if len(p["fury"]["pops"]) >= 2]
    t["pop2_lo"], t["pop2_hi"] = fmt(min(pre2)), fmt(max(pre2))
    soak = [s for p in pulls for s in p["fury"]["soakers"]]
    t["fury_pops"] = len(soak)
    t["soak_med"] = round(med(soak))
    t["soak_lo"] = min(soak)
    t["soak_short"] = sum(1 for s in soak if s < 14)
    miss = [m for p in pulls for m in p["fury"]["missing"]]
    t["fury_full"] = sum(1 for m in miss if m == 0)
    t["fury_missing_pops"] = sum(1 for m in miss if m > 0)
    mp = sorted((p for p in P if p["fury_missed"]), key=lambda p: -p["fury_missed"])
    t["fury_missers"] = names(f"{p['player']} ({p['fury_missed']})" for p in mp[:5])
    ex = [x for p in pulls for x in p["fury"]["extra_healers"]]
    t["fury_extra_pops"] = sum(1 for x in ex if x)
    hp = sorted((p for p in P if p["role"] == "healer"), key=lambda p: -p["fury_extra"])
    t["fury_extra_names"] = names(f"{p['player']} ({p['fury_extra']} of {p['fury_in']})" for p in hp if p["fury_in"])
    for i, g in enumerate(T, 1):
        mm = [m for p in g for m in p["fury"]["missing"]]
        t[f"t{i}_fury_miss"] = sum(1 for m in mm if m)
        t[f"t{i}_fury_pops"] = len(mm)
    # the 5th pop (after the second intermission)
    p5 = [(p["pull"], p["fury"]["pops"][3], p["fury"]["pops"][4] if len(p["fury"]["pops"]) > 4 else None,
           p["enrage"], p["enrage_forced"], p["under"])
          for p in pulls if len(p["fury"]["pops"]) >= 4 and p["inters_done"] >= 2]
    t["p5_rows"] = "; ".join(
        f"pull {pl}: pop four at {fmt(b)}s, so the boss would enrage at {fmt(b + W['long'])}s"
        + (f", and the raid popped at {fmt(c)}s" if c
           else f", and it did at {fmt(e)}s, but the raid had been under {FURY_NEED} alive since {fmt(u)}s" if e and forced
           else f", and it did at {fmt(e)}s" if e else "")
        for pl, b, c, e, forced, u in p5
    )
    # a pop that goes off as Dig In opens carries Virulence into the intermission
    dig = [
        (p["pull"], x, p["deaths"].get("virulence", 0))
        for p in pulls
        for x in p["fury"]["pops"]
        if any(-0.5 <= x - i["start"] <= 25 for i in p["inter"])
    ]
    t["dig_pops"] = len(dig)
    t["dig_note"] = (
        "; ".join(f"on pull {pl} it went off at {fmt(x)}s, as Dig In started, and Virulence killed {v} that pull" for pl, x, v in dig)
        if dig
        else "it never happened this night"
    )
    clip = [p["fury"]["clipped"] for p in pulls]
    t["clipped_total"] = sum(clip)
    t["vir_dead"] = dc_all["virulence"]
    for i, g in enumerate(T, 1):
        pops = sum(len(p["fury"]["pops"]) for p in g)
        t[f"t{i}_clip"] = fmt(sum(p["fury"]["clipped"] for p in g) / pops, 1) if pops else "0"

    # Mutilate / Ravage
    t["mut_dead"] = dc_all["mutilate"]
    t["mut_double"] = sum(p["mut_double"] for p in pulls)
    worst_mut = max(pulls, key=lambda p: p["deaths"].get("mutilate", 0))
    t["mut_worst"] = worst_mut["pull"]
    t["mut_worst_n"] = worst_mut["deaths"].get("mutilate", 0)
    t["mut_worst_double"] = worst_mut["mut_double"]
    t["ravage_raid"] = sum(p["ravage_raid"] for p in pulls)
    t["ravage_dead"] = dc_all["ravage"]
    t["surge_dead"] = dc_all["surge"]
    t["floor_dead"] = dc_all["floor"]

    # deaths
    t["deaths_live"] = sum(p["deaths_live"] for p in pulls)
    t["under_n"] = sum(1 for p in pulls if p["under"] and not (p["enrage"] and not p["enrage_forced"]))
    t["walked_n"] = sum(1 for p in pulls if p["walked"])
    t["called_n"] = sum(1 for p in pulls if p["called"])
    walk = sum(1 for fid in a.ids for d in a.deaths(fid) if d["after_call"])
    t["called_deaths"] = walk
    t["enrage_deaths"] = sum(1 for fid in a.ids for d in a.deaths(fid) if d["cause"] == "enrage" and not d["after_call"])
    top = dc_all.most_common(3)
    t["death_top"] = names(f"{ENDED_LABEL[g].lower()} ({n})" for g, n in top)
    ended = Counter(p["ended"] for p in pulls)
    t["ended_top"] = names(f"{ENDED_LABEL[g].lower()} ({n})" for g, n in ended.most_common(4))
    firsts = Counter(p["first"]["group"] for p in pulls if p["first"])
    t["first_top"] = names(f"{ENDED_LABEL[g].lower()} ({n})" for g, n in firsts.most_common(3))
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
