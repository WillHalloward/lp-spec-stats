"""Fill the template: payloads as JSON, everything the prose states as a token.

Every number the page says out loud is computed here, so a second prog night on
the same boss regenerates its own sentences rather than inheriting the first
night's figures.
"""

from __future__ import annotations

import itertools
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from . import baseline, spells

TEMPLATE = Path(__file__).parent / "template.html"

WORDS = {
    0: "no",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
}

# Killing blows grouped by the mechanic behind them, for the deaths chart.
DEATH_GROUPS = [
    ("droplets", "Droplets", {spells.NOXIOUS, spells.DROPLETS}),
    ("marks", "Marks", {spells.MARK_ACID, spells.MARK_BLOOD}),
    ("slime", "Slime", {spells.CONTAMINATE}),
    ("living", "Living Venom", {spells.LIVING_VENOM}),
    ("proto", "Protovenom", {spells.PROTOVENOM, spells.ERUPTION}),
    ("puzzle", "Puzzle", {spells.HELICAL, spells.BURST}),
    ("blood", "Miasma &amp; pools", {spells.MIASMA, spells.BLOOD_VENOM, "Clinging Murk", spells.BLIGHTED}),
    ("tank", "Tank hits", {"Melee", spells.SLAM, spells.INJECTION}),
]


def word(n: int) -> str:
    return WORDS.get(n, f"{n:,}")


def names(items) -> str:
    items = list(items)
    if not items:
        return "nobody"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def group_of(ability: str | None) -> str:
    for key, _, members in DEATH_GROUPS:
        if ability in members:
            return key
    return "other"


def med(xs, default=0):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else default


# ---------------------------------------------------------------- payloads


def payloads(a) -> tuple[dict, dict]:
    """Everything the charts draw, and the raw pieces the prose needs."""
    clock = a.clock()
    hp = a.health()
    dom = a.dominance()
    teams = a.teams()
    bd = a.boss_damage()
    bal = a.imbalance()
    puzzle = a.puzzle()
    drops = a.droplets()
    soak = a.soakers()
    proto = a.protovenom()
    lv = a.living_venom()
    wm = a.wrong_marks()
    miasma = a.miasma()
    blighted = a.blighted()
    avoid = a.avoidable()
    marks = a.marks()
    deaths = a.death_summary()
    mit = a.mitigation()
    summaries = {a.pull_no[fid]: a.pull_summary(fid) for fid in a.ids}

    # stretches of the night between team changes; moves a few pulls apart are one change
    last_pull = len(a.ids)
    cuts = []
    for m in sorted(teams["moves"], key=lambda m: m["at"]):
        if not cuts or m["at"] - cuts[-1] > 3:
            cuts.append(m["at"])
    edges = [1, *cuts, last_pull + 1]
    periods = []
    for lo, hi in itertools.pairwise(edges):
        rows = [
            (n, i, st)
            for n, v in hp["pulls"].items()
            if lo <= n < hi
            for i, st in enumerate(v["stasis"], 1)
            if not st["cut_short"] and st["gap"] is not None
        ]
        lower_b = lower_n = 0
        for n, i, st in rows:
            if st["gap"] < 0.5:
                continue
            lower = "breath" if st["breath"] < st["blood"] else "blood"
            lower_n += 1
            lower_b += teams["sides"].get(n, {}).get(i, {}).get("B") == lower
        periods.append(
            {
                "lo": lo,
                "hi": hi - 1,
                "n": len(rows),
                "gap": round(med([st["gap"] for _, _, st in rows]), 1) if rows else None,
                "healed": round(med([st["healed"] for _, _, st in rows])) if rows else None,
                "lower_b": lower_b,
                "lower_n": lower_n,
                "moves": [m for m in teams["moves"] if lo <= m["at"] < lo + 4 and lo > 1],
            }
        )
    # each player's runs on a team, for the cards
    spans = {}
    for p in a.players:
        moves_p = sorted((m for m in teams["moves"] if m["player"] == p), key=lambda m: m["at"])
        if not moves_p:
            continue
        out, start, cur = [], 1, moves_p[0]["from"]
        for m in moves_p:
            out.append([cur, start, m["at"] - 1])
            start, cur = m["at"], m["to"]
        out.append([cur, start, last_pull])
        spans[p] = out

    def team_label(p):
        if p in spans:
            return "\u2192".join(t for t, _, _ in spans[p])
        return teams["team"].get(p, "float")

    fights = []
    for row in clock["pulls"]:
        n = row["pull"]
        s = summaries[n]
        fights.append(
            {
                **row,
                "phase_dps": s["phase_dps"],
                "deaths": s["deaths"],
                "deaths_150": s["deaths_150"],
                "healed": s["healed"],
                "gaps": s["gaps"],
                "dom_secs": s["dom_secs"],
                "dom": dom[n],
                "blasts": s["blasts"],
                "eruptions": s["eruptions"],
                "boss_dmg": s["boss_dmg"],
                "boss_dps": s["boss_dps"],
                "final": hp["pulls"][n]["final"],
            }
        )

    pull_secs = sum(a.dur(fid) for fid in a.ids)
    tot = defaultdict(lambda: [0, 0, 0])
    for rows in bd["pulls"].values():
        for p, v in rows.items():
            for i in range(3):
                tot[p][i] += v[i]
    players = []
    for p in sorted(a.players):
        b = tot[p]
        players.append(
            {
                "player": p,
                "class": a.players[p]["subType"],
                "spec": a.spec.get(p, ""),
                "role": a.role.get(p, "dps"),
                "team": team_label(p),
                "breath": b[0],
                "blood": b[1],
                "slime": b[2],
                "total": sum(b),
                "dps": round(sum(b) / pull_secs) if pull_secs else 0,
            }
        )

    # team damage per pull and phase: whatever each team put into either boss
    team_rows = []
    for n, phases in bd["phases"].items():
        out = []
        for ph in phases:
            agg = {t: {"dmg": 0, "n": 0} for t in ("A", "B", "float")}
            for p, (br, bl) in ph["players"].items():
                t = teams["pull_team"].get(n, {}).get(p, "float")
                agg[t]["dmg"] += br + bl
                agg[t]["n"] += 1 if br + bl > 0 else 0
            sides = teams["sides"].get(n, {}).get(ph["phase"], {})
            out.append(
                {
                    "phase": ph["phase"],
                    "secs": ph["secs"],
                    **{
                        t: {"dps": round(agg[t]["dmg"] / ph["secs"]) if ph["secs"] else 0, "n": agg[t]["n"]}
                        for t in agg
                    },
                    "sides": sides,
                }
            )
        team_rows.append({"pull": n, "phases": out})

    members = {
        t: sorted(
            (p for p in a.players if teams["team"].get(p) == t or any(x[0] == t for x in spans.get(p, []))),
            key=lambda p: ({"tank": 0, "healer": 1}.get(a.role.get(p), 2), p),
        )
        for t in ("A", "B")
    }
    loose = sorted(teams["loose"], key=lambda p: ({"tank": 0, "healer": 1}.get(a.role.get(p), 2), p))

    mit_players = []
    for p in sorted(a.players):
        v = mit["per"][p]
        mit_players.append(
            {
                "player": p,
                "class": a.players[p]["subType"],
                "spec": a.spec.get(p, ""),
                "role": a.role.get(p, "dps"),
                "maj": v["maj"],
                "maj_heavy": v["maj_heavy"],
                "minor": v["minor"],
                "ext": v["ext"],
                "coverage": round(100 * len(v["cov"]) / mit["total_spans"], 1) if mit["total_spans"] else 0,
                "hs": v["hs"],
                "pot": v["pot"],
                "consum": v["hs"] + v["pot"],
                "hp_at_use": round(statistics.mean(v["hp"]), 1) if v["hp"] else None,
                "deaths": v["deaths"],
                "early_deaths": v["early"],
                "early_no_def": v["early_no_def"],
                "spirit": v["spirit"],
                "early_spirit": v["early_spirit"],
                "top_spells": v["spells"].most_common(4),
                "top_minor": v["minor_spells"].most_common(1),
            }
        )

    pz_players = {}
    for p, v in puzzle["per_player"].items():
        pz_players[p] = {
            "median": round(med(v["times"]), 1),
            "n": len(v["times"]),
            "last": v["last"],
            "solved_in": v["solved_in"],
            "wrong": v["wrong"],
            "broke": v["broke"],
            "after": v["after"],
            "stranded": v["stranded"],
            "died": v["died"],
        }

    avoid_out = {
        p: {k: (round(x) if isinstance(x, float) else x) for k, x in v.items()} for p, v in avoid.items()
    }
    marks_out = {
        p: {"dmg": round(v["dmg"]), "peak": v["peak"], "deaths": v["deaths"]} for p, v in marks["per"].items()
    }

    payload = {
        "data": {
            "meta": {
                "report": a.code,
                "pulls": len(a.ids),
                "berserk_at": spells.BERSERK_AT,
                "max_hp": hp["max_hp"],
            },
            "fights": fights,
            "players": players,
            "kills": baseline.KILLS,
        },
        "health": hp["pulls"],
        "teams": {
            "team": teams["team"],
            "spans": spans,
            "periods": periods,
            "members": members,
            "loose": loose,
            "roles": {p: a.role.get(p, "dps") for p in a.players},
            "spec": {p: a.spec.get(p, "") for p in a.players},
            "cls": {p: a.players[p]["subType"] for p in a.players},
            "pulls": team_rows,
        },
        "balance": {
            "rows": bal["rows"],
            "players": [
                {
                    "player": p,
                    "team": team_label(p),
                    "spec": a.spec.get(p, ""),
                    "class": a.players[p]["subType"],
                    "role": a.role.get(p, "dps"),
                    "own": round(bal["own"].get(p, 0)),
                    "cross": round(bal["cross"].get(p, 0)),
                }
                for p in teams["team"]
            ],
        },
        "bosspulls": {
            "pulls": {n: {p: v[:3] for p, v in rows.items()} for n, rows in bd["pulls"].items()},
            "durs": {a.pull_no[fid]: round(a.dur(fid)) for fid in a.ids},
        },
        "puzzle": {"rows": puzzle["rows"], "players": pz_players},
        "soak": {
            "players": [
                {
                    "player": p,
                    "role": a.role.get(p, "dps"),
                    "spec": a.spec.get(p, ""),
                    "class": a.players[p]["subType"],
                    "team": team_label(p),
                    "pre": v["pre"],
                    "other": v["other"],
                    "sets": v["sets"],
                    "median": round(med(v["times"]), 1) if v["times"] else None,
                    "late": sum(1 for x in v["times"] if x > 10),
                }
                for p, v in soak["per"].items()
            ],
            # soak times to the tenth of a second, pooled per kind of set, for the histogram
            "times": {
                "pre": [x for st in soak["sets"] if st["pre"] for x in st["times"]],
                "other": [x for st in soak["sets"] if not st["pre"] for x in st["times"]],
            },
        },
        "lv": {
            "players": [
                {
                    "player": p,
                    "role": a.role.get(p, "dps"),
                    "spec": a.spec.get(p, ""),
                    "class": a.players[p]["subType"],
                    "team": team_label(p),
                    **{k: (round(x) if isinstance(x, float) else x) for k, x in v.items()},
                    "rate": round(300 * v["hits"] / v["alive"], 2) if v["alive"] else 0,
                }
                for p, v in lv["per"].items()
            ],
            "per_pull": lv["per_pull"],
            "per_phase": lv["per_phase"],
        },
        "wrong": {
            "players": [
                {
                    "player": p,
                    "role": a.role.get(p, "dps"),
                    "spec": a.spec.get(p, ""),
                    "class": a.players[p]["subType"],
                    "team": team_label(p),
                    "walk": v["walk"],
                    "extended": v["extended"],
                    "fresh": v["fresh"],
                    "phases": v["phases"],
                    "extra": round(v["extra"]),
                    "mark": round(v["mark"]),
                    # per minute alive in damage phases, the same clock Living Venom uses
                    "per_min": round(60 * v["extra"] / lv["per"][p]["alive"]) if lv["per"][p]["alive"] else 0,
                }
                for p, v in wm["per"].items()
            ],
            "events": wm["events"],
        },
        "mech": {
            "drops": drops["casts"],
            "soaks": drops["soaks"],
            "proto": proto["rows"],
            "carriers": proto["carriers"],
            "victims": proto["victims"],
            "caught": proto["caught"],
            "marked": proto["marked"],
            "pv_pairs": proto["pairs"],
            "miasma": miasma,
            "blighted": blighted["rows"],
            "dispellers": blighted["by_dispeller"],
            "avoid": avoid_out,
            "marks": marks_out,
        },
        "deaths": {
            "pulls": deaths["per_pull"],
            "firsts": deaths["firsts"],
            "groups": [[k, label] for k, label, _ in DEATH_GROUPS] + [["other", "Other"]],
            "group_of": {
                ab: group_of(ab)
                for pulls in deaths["per_pull"].values()
                for d in pulls
                for ab in [d["ability"]]
            },
        },
        "mit": {"players": mit_players, "total_spans": mit["total_spans"]},
        "dtps": a.dtps(),
    }
    raw = {
        "clock": clock,
        "hp": hp,
        "dom": dom,
        "teams": teams,
        "periods": periods,
        "bd": bd,
        "bal": bal,
        "puzzle": puzzle,
        "drops": drops,
        "soak": soak,
        "proto": proto,
        "lv": lv,
        "wm": wm,
        "miasma": miasma,
        "blighted": blighted,
        "avoid": avoid,
        "marks": marks,
        "deaths": deaths,
        "mit": mit,
        "summaries": summaries,
    }
    return payload, raw


# ---------------------------------------------------------------- tokens


def tokens(a, P: dict, raw: dict, *, date_long: str, night_title: str) -> dict:
    """One entry per {{token}} in the template."""
    data = P["data"]
    fights = data["fights"]
    max_hp = data["meta"]["max_hp"] or baseline.BOSS_HP
    kills = baseline.KILLS
    kill_pull = next((f["pull"] for f in fights if f["kill"]), 0)
    deep = min(fights, key=lambda f: f["boss_pct"])
    S = raw["summaries"]

    # ---- the clock
    first_stasis = [f["stasis"][0][0] for f in fights if f["stasis"]]
    gaps_between = [
        round(f["stasis"][i + 1][0] - f["stasis"][i][1]) for f in fights for i in range(len(f["stasis"]) - 1)
    ]
    solved = [x for f in fights for x in f["solved"]]
    kill_solved = [x for k in kills for x in k["solved"]]
    berserk_pulls = [f["pull"] for f in fights if f["berserk"] is not None]

    # ---- the heal
    healed_total = sum(f["healed"] for f in fights)
    stasis_rows = [s for n, v in raw["hp"]["pulls"].items() for s in v["stasis"] if not s["cut_short"]]
    gap_all = [s["gap"] for s in stasis_rows if s["gap"] is not None]
    kill_gaps = [g for k in kills for g in k["gaps"]]
    deep_heal = deep["healed"]

    # ---- the teams
    teams = raw["teams"]
    # which team's boss was the lower one going into each Stasis
    lower_team = Counter()
    for n, v in raw["hp"]["pulls"].items():
        sides = teams["sides"].get(n, {})
        for i, s in enumerate(v["stasis"], 1):
            if s["cut_short"] or s["gap"] is None or s["gap"] < 0.5:
                continue
            lower = "breath" if s["breath"] < s["blood"] else "blood"
            ph = sides.get(i, {})
            for t in ("A", "B"):
                if ph.get(t) == lower:
                    lower_team[t] += 1
    lower_n = sum(lower_team.values())
    members = P["teams"]["members"]

    def shape(t):
        """A typical pull's roster for the team: the median count of each role
        across pulls, so somebody who changed team is counted once, where they were."""
        per_role = {r: [] for r in ("tank", "healer", "dps")}
        for pt in teams["pull_team"].values():
            c = Counter(a.role.get(p) for p, tt in pt.items() if tt == t)
            for r, counts in per_role.items():
                counts.append(c.get(r, 0))
        tk, hl, dp = (round(med(per_role[r])) for r in ("tank", "healer", "dps"))
        return f"{plural(tk, 'tank')}, {plural(hl, 'healer')}, {dp} damage on a typical pull"

    opener = {}
    for t in ("A", "B"):
        c = Counter(v.get(1, {}).get(t) for v in teams["sides"].values())
        c.pop(None, None)
        opener[t] = c.most_common(1)[0][0] if c else None
    boss_label = {"breath": "Breath", "blood": "Blood", None: "either"}
    stronger = "B" if lower_team.get("B", 0) >= lower_team.get("A", 0) else "A"

    bal = raw["bal"]
    bal_tok = {}
    for ph in (1, 2):
        rows = [r for r in bal["rows"] if r["phase"] == ph]
        for k in ("teams", "cross", "float"):
            bal_tok[f"bal_p{ph}_{k}"] = f"{med([r[k] for r in rows]) / 1e6:+.1f}" if rows else "0"
        bal_tok[f"bal_p{ph}_n"] = len(rows)
        bal_tok[f"bal_p{ph}_total"] = (
            f"{med([r['teams'] + r['cross'] + r['float'] for r in rows]) / 1e6:.0f}" if rows else "0"
        )

    # healers' boss damage is small enough that a stray dot reads as a big share
    def parts(ph):
        rows = [r for r in bal["rows"] if r["phase"] == ph]
        if not rows:
            return ""
        t_, c_, f_ = (med([r[k] for r in rows]) / 1e6 for k in ("teams", "cross", "float"))
        bits = [
            f"team B did {t_:.1f}M more on its own boss than team A did on theirs"
            if t_ >= 0
            else f"team A did {-t_:.1f}M more on its own boss than team B did on theirs",
            f"cross-room damage put a net {c_:.1f}M more into B&#39;s boss"
            if c_ >= 0
            else f"cross-room damage put a net {-c_:.1f}M more into A&#39;s boss",
        ]
        if abs(f_) >= 0.5:
            bits.append(
                f"damage dealers not placed with a team put {abs(f_):.1f}M more into {'B' if f_ > 0 else 'A'}&#39;s boss"
            )
        return names(bits)

    bal_tok["bal_p1_sentence"] = parts(1)
    bal_tok["bal_p2_sentence"] = parts(2)
    crossers = sorted(
        ((p, bal["cross"].get(p, 0), bal["own"].get(p, 0)) for p in teams["team"] if a.role.get(p) == "dps"),
        key=lambda x: -x[1],
    )
    big_cross = [(p, c, o) for p, c, o in crossers if c + o and c / (c + o) >= 0.10]
    bal_tok["cross_names"] = (
        names(
            f"{p} ({a.spec.get(p, '')}, {c / 1e6:.0f}M, {100 * c / (c + o):.0f}% of their boss damage)"
            for p, c, o in big_cross
        )
        if big_cross
        else "nobody"
    )
    bal_tok["cross_rest"] = (
        f"{max(100 * c / (c + o) for p, c, o in crossers if (p, c, o) not in big_cross and c + o):.0f}"
        if len(crossers) > len(big_cross)
        else "0"
    )
    unplaced = defaultdict(lambda: [0.0, 0.0, 0])
    for n, rows in raw["bd"]["pulls"].items():
        for p, v in rows.items():
            if p not in teams["pull_team"].get(n, {}) and a.role.get(p) == "dps":
                unplaced[p][0] += v[0]
                unplaced[p][1] += v[1]
                unplaced[p][2] += 1
    big_unplaced = sorted(
        ((p, v) for p, v in unplaced.items() if v[0] + v[1] > 50e6), key=lambda x: -(x[1][0] + x[1][1])
    )
    bal_tok["float_sentence"] = (
        "On pulls where a damage dealer could not be placed with either team, standing between the "
        "bosses or collecting both marks, their boss damage counts as its own part. "
        + names(
            f"{p} was unplaced on {v[2]} pulls and put {v[0] / 1e6:.0f}M into Breath against {v[1] / 1e6:.0f}M into Blood on them"
            for p, v in big_unplaced
        )
        + "."
        if big_unplaced
        else "Every damage dealer could be placed with a team on nearly every pull."
    )
    P_ = raw["periods"]

    def span_txt(x):
        return f"pulls {x['lo']}&#8211;{x['hi']}" if x["hi"] > x["lo"] else f"pull {x['lo']}"

    moves_txt = []
    for m in sorted(teams["moves"], key=lambda m: (m["at"], m["player"])):
        moves_txt.append(
            f"{m['player']} ({a.spec.get(m['player'], '')}) from team {m['from']} to team {m['to']} at pull {m['at']}"
        )
    bal_tok["move_sentence"] = (
        "The teams changed during the night: " + names(moves_txt) + "."
        if moves_txt
        else "Nobody changed team during the night."
    )
    if len(P_) >= 2:
        last = P_[-1]
        best = min((x for x in P_ if x["gap"] is not None), key=lambda x: x["gap"])
        worst = max((x for x in P_ if x["gap"] is not None), key=lambda x: x["gap"])
        note = (
            f"The gap moved with those changes. Over {span_txt(worst)} the bosses went into Stasis "
            f"{worst['gap']} points apart at the median and each intermission handed back "
            f"{(worst['healed'] or 0) / 1e6:.1f}M; over {span_txt(best)} it was {best['gap']} points and "
            f"{(best['healed'] or 0) / 1e6:.1f}M"
        )
        if best["gap"] <= med(kill_gaps):
            note += f", level with the kills&#39; {med(kill_gaps):.1f}"
        note += "."
        if best is last and best["n"] < 15:
            note += f" That last stretch is only {best['n']} intermissions, a short run rather than a settled answer."
        # a stretch that opened with only healers changing teams is not explained by
        # the change: healers put next to nothing into the bosses
        opened = worst["moves"]
        if opened and all(a.role.get(m["player"]) == "healer" for m in opened):
            note += (
                f" {span_txt(worst).capitalize()} opened with the healers trading teams, and healers put "
                "next to nothing into the bosses, so that change is unlikely to be the cause."
            )
        bal_tok["period_note"] = note
    else:
        bal_tok["period_note"] = ""
    team_note = (
        f"Going into an intermission with the bosses more than half a point apart, the lower boss was "
        f"team {stronger}&#39;s in {lower_team.get(stronger, 0)} of {lower_n}."
        if lower_n
        else ""
    )

    # ---- against the kills
    def ph_dps(i, rows):
        return [r["phase_dps"][i - 1] for r in rows if len(r["phase_dps"]) > i]  # a phase it lived past

    ours_full = [f for f in fights if len(f["phase_dps"]) >= 3]
    p1 = ph_dps(1, ours_full)
    p2 = ph_dps(2, ours_full)
    k1, k2 = baseline.phase_dps(1), baseline.phase_dps(2)
    late = [f for f in ours_full if f["pull"] > len(fights) // 2]
    deep_s = S[deep["pull"]]
    need = 2 * max_hp + deep_heal
    phase_secs_to_berserk = spells.BERSERK_AT - sum(
        min(b, spells.BERSERK_AT) - a for a, b in deep["stasis"] if a < spells.BERSERK_AT
    )

    # ---- the puzzle
    pz = raw["puzzle"]["rows"]
    pz_ok = [r for r in pz if r["outcome"] == "solved"]
    failed = [r for r in pz if r["outcome"] in ("wrong", "unpaired")]
    broken = [r for r in pz if r["outcome"] == "deaths"]
    decided = len(pz_ok) + len(failed)  # intermissions the puzzle itself decided
    solve_t = [r["solve"] for r in pz_ok]
    first_pair = [r["pairs"][0]["t"] for r in pz_ok if r["pairs"]]
    half = [r["half"] for r in pz_ok if r["half"] is not None]
    kill_solve = [x for k in kills for x in k.get("puzzle_solve", []) if x is not None]
    kill_out = Counter(o for k in kills for o in k.get("puzzle_outcomes", []))
    kill_wrong = sum(k.get("puzzle_wrong", 0) for k in kills)
    any_wrong = [r for r in pz if r["over"]]
    wrong_after_deaths = [r for r in broken if r["over"]]
    kill_decided = kill_out.get("solved", 0) + kill_out.get("wrong", 0) + kill_out.get("unpaired", 0)
    pzp = P["puzzle"]["players"]
    slow = sorted(((p, v) for p, v in pzp.items() if v["n"] >= 10), key=lambda kv: -kv[1]["median"])[:3]
    last_top = sorted(pzp.items(), key=lambda kv: -kv[1]["last"])[:3]
    # only players who did it more than once: a list padded out with ones is a tie, not a ranking
    wrong_top = sorted(((p, v["broke"]) for p, v in pzp.items() if v["broke"] >= 2), key=lambda x: -x[1])
    # a failed solve that the pull survived, against one the pull ended on
    failed_survived = [
        r for r in failed if any(f["pull"] == r["pull"] and len(f["stasis"]) > r["idx"] for f in fights)
    ]
    broken_called = [r for r in broken if r["pull_end"] <= 31 + 20]
    broken_opened_down = [r for r in broken if r["players"] < 0.85 * len(a.players)]
    # how long Stasis ran when the puzzle was solved, against the solve itself
    stasis_after = [r["len"] - r["solve"] for r in pz_ok]

    # ---- droplets
    drops = raw["drops"]["casts"]
    missed_sets = [c for c in drops if c["blasts"]]
    blasts = sum(c["blasts"] for c in drops)
    blast_hits = [
        e
        for fid in a.ids
        for e in a.taken(fid)
        if e.get("abilityGameID") in a.ids_named(spells.NOXIOUS) and a.player_of(e.get("targetID"))
    ]
    blast_hit = med([(e.get("amount") or 0) + (e.get("absorbed") or 0) for e in blast_hits])
    dpp = raw["deaths"]["per_pull"]
    blast_deaths = [d for v in dpp.values() for d in v if d["ability"] == spells.NOXIOUS]
    # read off the sets themselves: a blast kills several at once, so the
    # solo-death rule would never count one however healthy the raid was
    roster = len(a.players) or 1
    killing = [c for c in drops if c["killed"]]
    standing = [c for c in killing if c["alive"] >= 0.7 * roster]
    # the pull ended within thirty seconds of the blast (which lands ~15s after the cast)
    standing_wipes = [c for c in standing if c["pull_end"] <= 45]
    pre = [c for c in drops if c["to_stasis"] is not None and c["to_stasis"] <= 15]
    rest = [c for c in drops if c not in pre]

    def set_line(rows):
        missed = sum(1 for c in rows if c["blasts"])
        return len(rows), missed, sum(c["killed"] or 0 for c in rows)

    pre_n, pre_missed, pre_dead = set_line(pre)

    # who soaks: every complete set is twenty droplets, each soaked by one player or blown
    sk = raw["soak"]
    sk_sets = sk["sets"]
    full = Counter(st["soaked"] + st["blasts"] for st in sk_sets)
    per_set_n, per_set_hits = full.most_common(1)[0] if full else (0, 0)
    soaked_total = sum(v["pre"] + v["other"] for v in sk["per"].values())
    sk_rank = sorted(sk["per"].items(), key=lambda kv: -(kv[1]["pre"] + kv[1]["other"]))
    top4 = sk_rank[:4]
    rate = {p: (v["pre"] + v["other"]) / v["sets"] for p, v in sk["per"].items() if v["sets"]}
    low_dps = sorted((p for p in rate if a.role.get(p) == "dps"), key=lambda p: rate[p])[:4]
    by_side = Counter()
    for st in sk_sets:
        sides = teams["sides"].get(st["pull"], {}).get(st["phase"], {})
        breath_team = next((t for t, b in sides.items() if b == "breath"), None)
        for p in st["who"]:
            t = teams["pull_team"].get(st["pull"], {}).get(p)
            by_side["breath" if t and t == breath_team else ("switch" if not t else "blood")] += 1
    pre_t = [x for st in sk_sets if st["pre"] for x in st["times"]]
    oth_t = [x for st in sk_sets if not st["pre"] for x in st["times"]]
    rest_n, rest_missed, rest_dead = set_line(rest)
    multi = [c for c in drops if c["blasts"] >= 2]
    soakers = [c["soakers"] for c in drops if c["soaks"]]

    # ---- protovenom
    pv = raw["proto"]["rows"]
    pv_full = [r for r in pv if r["marked"] == 8]
    eruptions = sum(len(r["eruptions"]) for r in pv)
    pv_clean = sum(1 for r in pv if r["pairs"] * 2 >= r["marked"] and not r["eruptions"])
    carriers = raw["proto"]["carriers"]
    marked_n = raw["proto"]["marked"]
    collisions = [e for r in pv for e in r["eruptions"]]
    attributed = [e for e in collisions if e["carrier"]]
    quick = [e for e in attributed if e["marked_for"] <= 3]
    # caused per time marked, among players marked often enough to have a rate
    car_rate = sorted(
        ((p, c, marked_n.get(p, 0)) for p, c in carriers.items() if marked_n.get(p, 0) >= 10),
        key=lambda x: -x[1] / x[2],
    )[:3]
    top_car = sorted(carriers.items(), key=lambda kv: -kv[1])[:3]
    top_touched = sorted(raw["proto"]["victims"].items(), key=lambda kv: -kv[1])[:3]
    repeat_pairs = [x for x in raw["proto"]["pairs"] if x[2] >= 3]
    kill_pv = sum(k["pv_pairs"] for k in kills) / max(1, sum(k["pv_sets"] for k in kills))

    # ---- red side
    mi = raw["miasma"]
    mi_low = [m for m in mi if m["soakers"] < 6]
    bl = raw["blighted"]["rows"]
    bl_disp = [r["secs"] for r in bl if r["dispelled"]]
    avoid = raw["avoid"]
    living_first = sum(1 for f in raw["deaths"]["firsts"] if f["ability"] == spells.LIVING_VENOM)
    lvp = raw["lv"]["per"]
    lv_hits = sum(v["hits"] for v in lvp.values())
    lv_side = sum(v["breath"] + v["blood"] for v in lvp.values())
    lv_rate = sorted(
        ((p, 300 * v["hits"] / v["alive"]) for p, v in lvp.items() if v["alive"] and a.role.get(p) != "tank"),
        key=lambda x: -x[1],
    )
    lv_died = sorted(((p, v["then_died"]) for p, v in lvp.items() if v["then_died"]), key=lambda x: -x[1])
    r1, r2 = raw["lv"]["phase_rate"].get(1, 0), raw["lv"]["phase_rate"].get(2, 0)
    if r1 and r2 and abs(r1 - r2) / max(r1, r2) < 0.15:
        lv_phase_note = "about the same rate either way, so it is not the slime phase that gets hit more"
    elif r1 > r2:
        lv_phase_note = "so the opening phase, under lust, is the busier one"
    else:
        lv_phase_note = "so the phase with team A on Breath, and the slime, is the one that gets hit more"
    living_tot = sum(v["living"] for v in avoid.values())
    living_top = sorted(
        ((p, v["living"]) for p, v in avoid.items() if a.role.get(p) != "tank"), key=lambda x: -x[1]
    )[:3]
    pool_top = sorted(
        ((p, v["pool"]) for p, v in avoid.items() if a.role.get(p) != "tank"), key=lambda x: -x[1]
    )[:3]

    # ---- marks from the other boss
    wm = raw["wm"]["per"]
    wm_extra = sum(v["extra"] for v in wm.values())
    wm_mark = sum(v["mark"] for v in wm.values())
    wm_apps = len(raw["wm"]["events"])
    kinds = Counter(e["kind"] for e in raw["wm"]["events"])
    phase_secs_all = sum((b - x) / 1000 for fid in a.ids for x, b in a.phases(fid))
    alive = {p: raw["lv"]["per"][p]["alive"] for p in wm}
    wm_rank = sorted(wm.items(), key=lambda kv: -kv[1]["extra"])
    kill_wm_rate = [
        k["wrong_extra"] / (k["phase_secs"] / 60) for k in kills if k.get("wrong_extra") is not None
    ]
    wm_rate = wm_extra / (phase_secs_all / 60) if phase_secs_all else 0
    wm_top = wm_rank[:4]

    # ---- marks
    mk = raw["marks"]
    taken_total = sum(
        (e.get("amount") or 0) + (e.get("absorbed") or 0)
        for fid in a.ids
        for e in a.taken(fid)
        if a.player_of(e.get("targetID"))
    )
    mark_dmg = sum(v["dmg"] for v in mk["per"].values())
    mark_deaths = [
        d for v in dpp.values() for d in v if d["ability"] in (spells.MARK_ACID, spells.MARK_BLOOD)
    ]
    # how many of those came in the last twenty seconds before an intermission
    late_mark = 0
    for n, ds in dpp.items():
        f = next(x for x in fights if x["pull"] == n)
        for d in ds:
            if d["ability"] in (spells.MARK_ACID, spells.MARK_BLOOD) and any(
                0 <= s - d["t"] <= 20 for s, _ in f["stasis"]
            ):
                late_mark += 1
    peak_med = med(list(mk["peaks_by_phase"].values()))

    # ---- deaths
    firsts = raw["deaths"]["firsts"]
    first_groups = Counter(group_of(f["ability"]) for f in firsts)
    label = {k: lab for k, lab, _ in DEATH_GROUPS} | {"other": "Other"}
    all_deaths = [d for v in dpp.values() for d in v]
    solo = [d for d in all_deaths if d["solo"]]
    solo_groups = Counter(group_of(d["ability"]) for d in solo)

    # ---- mitigation / consumables (the Ula'tek page's section, same rules)
    mit = P["mit"]["players"]
    heavy = raw["mit"]["heavy"]
    spans_total = sum(len(v["spans"]) for v in heavy.values())
    heavy_secs = sum(b - x + 1 for v in heavy.values() for x, b in v["spans"])
    fight_secs = sum(v["dur"] for v in heavy.values())
    heavy_total = sum(v["heavy_total"] for v in heavy.values())
    all_taken = sum(v["total"] for v in heavy.values())
    all_hp = [x for p in a.players for x in raw["mit"]["per"][p]["hp"]]
    stones = raw["mit"]["stones"]
    hs_total = sum(v for k, v in stones.items() if k in spells.HEALTHSTONES)
    pot_total = sum(v for k, v in stones.items() if k in spells.HEALTH_POTIONS)
    never_hs = [p["player"] for p in mit if p["hs"] == 0]
    dt_tot = Counter()
    for pl in P["dtps"]["pulls"].values():
        for row, key in ((pl["taken"], "taken"), (pl["absorb"], "absorb"), (pl["reduced"], "reduced")):
            dt_tot[key] += sum(sum(r) for r in row)
    dt_inc = sum(dt_tot.values()) or 1
    early_nodef = sum(p["early_no_def"] for p in mit)

    dom_all = [r for v in raw["dom"].values() for r in v]
    dom_walk = [r for r in dom_all if r["kind"] == "walkout"]
    dom_mid = [r for r in dom_all if r["kind"] == "midphase"]
    dom_pulls = sorted({n for n, v in raw["dom"].items() if v})

    lust = a.lust()

    def m(v, digits=0):
        return f"{v / 1e6:.{digits}f}"

    t = {
        "report": a.code,
        "zone": (a.meta.get("zone") or {}).get("name", ""),
        "boss": a.fights[0]["name"] if a.fights else "the boss",
        "difficulty": spells.DIFFICULTY.get(a.difficulty, str(a.difficulty)),
        "date_long": date_long,
        "night_title": night_title,
        "pulls": len(fights),
        "raiders": len(a.players),
        "outcome": "all wipes" if not kill_pull else "a kill",
        "best_pct": f"{deep['boss_pct']:.2f}",
        "deep_pull": deep["pull"],
        "best_line": (
            f"Killed on pull {kill_pull} of {len(fights)}"
            if kill_pull
            else f"Best pull: {deep['boss_pct']:.2f}% remaining"
        ),
        "tile_best_n": str(kill_pull) if kill_pull else f"{deep['boss_pct']:.2f}<small>%</small>",
        "tile_best_lab": "the pull it died on"
        if kill_pull
        else f"best pull (pull {deep['pull']}), boss left",
        "pulls_caption_lead": (
            f"Boss health remaining at the end of each pull. Pull {kill_pull} was the kill."
            if kill_pull
            else "Boss health remaining at the wipe, the two Sentinels averaged, as Warcraft Logs reports it."
        ),
        "berserk_note": (
            f"{names(f'pull {n}' for n in berserk_pulls).capitalize()} lived to the berserk at "
            f"{spells.BERSERK_AT // 60}:{spells.BERSERK_AT % 60:02d}"
            + (
                f", pull {deep['pull']} with {deep['boss_pct']:.1f}% still to go."
                if deep["pull"] in berserk_pulls
                else "."
            )
            if berserk_pulls
            else "No pull lived to the berserk."
        ),
        "berserk_pulls_n": len(berserk_pulls),
        "berserk_at": spells.BERSERK_AT,
        "berserk_clock": f"{spells.BERSERK_AT // 60}:{spells.BERSERK_AT % 60:02d}",
        # clock
        "first_stasis": round(med(first_stasis)),
        "stasis_gap": round(med(gaps_between)) if gaps_between else 0,
        "deep_inter": round(deep["inter_secs"]),
        "deep_n_word": word(len(deep["stasis"])),
        "kill_inter_lo": round(min(k["inter_secs"] for k in kills)),
        "kill_inter_hi": round(max(k["inter_secs"] for k in kills)),
        "kill_dur_lo": f"{int(min(k['dur'] for k in kills)) // 60}:{int(min(k['dur'] for k in kills)) % 60:02d}",
        "kill_dur_hi": f"{int(max(k['dur'] for k in kills)) // 60}:{int(max(k['dur'] for k in kills)) % 60:02d}",
        "inter_median": f"{med(solved):.0f}",
        "kill_inter_median": f"{med(kill_solved):.0f}",
        "n_inter": len(solved),
        "inter_over20": sum(1 for x in solved if x > 20),
        "inter_typical_note": (
            "so a typical one is not the problem. The long ones are:"
            if solved and kill_solved and med(solved) - med(kill_solved) <= 2
            else "so even a typical one costs time. On top of that,"
        ),
        "kill_inter_max": f"{max(kill_solved):.0f}",
        # heal
        "healed_total": m(healed_total),
        "healed_bosses": f"{healed_total / max_hp:.1f}",
        "deep_healed": m(deep_heal),
        "deep_healed_pct": f"{100 * deep_heal / max_hp:.1f}",
        "kill_healed_lo": m(min(k["healed"] for k in kills)),
        "kill_healed_hi": m(max(k["healed"] for k in kills)),
        "kill_healed_med": m(med([k["healed"] for k in kills])),
        "gap_median": f"{med(gap_all):.1f}",
        "kill_gap_median": f"{med(kill_gaps):.1f}",
        "gap_over3": sum(1 for g in gap_all if g > 3),
        "n_stasis_full": len(gap_all),
        "max_hp": m(max_hp),
        # stated as a share of the same combined bar the wipe percentage is read
        # off, not as what the pull "would have" done: less to heal would also
        # have meant a different fight
        "deep_heal_note": (
            f"That is {100 * deep_heal / (2 * max_hp):.1f} points of the two Sentinels&#39; combined health, "
            f"on a pull that ended {deep['boss_pct']:.1f} points short."
            if not kill_pull
            else ""
        ),
        # dominance
        "dom_n": len(dom_all),
        "dom_pulls_word": word(len(dom_pulls)),
        "dom_secs": f"{sum(r['secs'] for r in dom_all):.0f}",
        "dom_walk_n": len(dom_walk),
        "dom_walk_secs": f"{sum(r['secs'] for r in dom_walk):.0f}",
        "dom_mid_n": len(dom_mid),
        "dom_mid_secs": f"{sum(r['secs'] for r in dom_mid):.0f}",
        "kill_dom_secs": f"{sum(k['dom_secs'] for k in kills):.0f}",
        "dom_long": (
            names(
                f"pull {n} ({r['secs']:.0f}s at {r['t']:.0f}s)"
                for n, v in sorted(raw["dom"].items())
                for r in v
                if r["secs"] >= 10
            )
            or "no pull"
        ),
        # teams
        "a_shape": shape("A"),
        "b_shape": shape("B"),
        "a_open": boss_label[opener.get("A")],
        "b_open": boss_label[opener.get("B")],
        "a_tank": next((p for p in members["A"] if a.role.get(p) == "tank"), "team A"),
        "b_tank": next((p for p in members["B"] if a.role.get(p) == "tank"), "team B"),
        "team_note": team_note,
        **bal_tok,
        "off_n": len(teams["off"]),
        "off_note": (
            "Nobody stood with the other team for a phase all night."
            if not teams["off"]
            else f"{plural(len(teams['off']), 'phase')} had someone collecting the other team&#39;s mark, "
            + names(
                f"{p} {plural(c, 'time')}"
                for p, c in Counter(o["player"] for o in teams["off"]).most_common(3)
            )
            + "."
        ),
        # kills
        "kill_n_word": word(len(kills)),
        "kill_n_word_cap": word(len(kills)).capitalize(),
        "kill_ilvl_old": min(k["ilvl_median"] for k in kills),
        "kill_ilvl_new": max(k["ilvl_median"] for k in kills),
        "our_ilvl": round(statistics.median([v for v in a.ilvl.values() if v])),
        "k1_lo": m(min(k1), 2),
        "k1_hi": m(max(k1), 2),
        "k2_lo": m(min(k2), 2),
        "k2_hi": m(max(k2), 2),
        "o1_med": m(med(p1), 2),
        "o2_med": m(med(p2), 2),
        "o1_late": m(med(ph_dps(1, late)), 2) if late else "0",
        "o2_late": m(med(ph_dps(2, late)), 2) if late else "0",
        "o2_best": m(max(p2), 2) if p2 else "0",
        "p2_short": round(100 * (1 - med(p2) / med(k2))) if p2 and k2 else 0,
        "deep_dps": m(deep_s["boss_dps"], 2),
        "kill_dps_lo": m(min(k["boss_dps"] for k in kills), 2),
        "kill_dps_hi": m(max(k["boss_dps"] for k in kills), 2),
        "need_m": m(need),
        "deep_phase_secs": round(phase_secs_to_berserk),
        "need_dps": m(need / phase_secs_to_berserk, 2) if phase_secs_to_berserk else "0",
        "kill_deaths_150": names(str(k["deaths_150"]) for k in kills),
        "our_deaths_150_med": f"{med([f['deaths_150'] for f in fights if f['dur'] >= 150]):.0f}",
        # puzzle
        "pz_n": len(pz),
        "pz_solved": len(pz_ok),
        "pz_failed": len(failed),
        "pz_wrong": sum(1 for r in failed if r["outcome"] == "wrong"),
        "pz_any_wrong": len(any_wrong),
        "pz_after_total": sum(v["after"] for v in pzp.values()),
        "pz_wrong_after_deaths": len(wrong_after_deaths),
        "kill_wrong": kill_wrong,
        "kill_pz_n": sum(len(k.get("puzzle_outcomes", [])) for k in kills),
        "kill_pz_note": (
            f"The kills solved every one the puzzle decided, {kill_decided} of their "
            f"{sum(len(k.get('puzzle_outcomes', [])) for k in kills)} intermissions, with {kill_wrong} wrong "
            f"pairing{'s' if kill_wrong != 1 else ''} among them all."
            if kill_decided and not (kill_out.get("wrong", 0) + kill_out.get("unpaired", 0))
            else f"The kills failed {kill_out.get('wrong', 0) + kill_out.get('unpaired', 0)} of the {kill_decided} "
            "their puzzle decided."
        ),
        "pz_unpaired": sum(1 for r in failed if r["outcome"] == "unpaired"),
        "pz_broken": len(broken),
        "pz_broken_called": len(broken_called),
        "pz_broken_down": len(broken_opened_down),
        "pz_decided": decided,
        "pz_fail_pct": round(100 * len(failed) / decided) if decided else 0,
        "pz_failed_survived": len(failed_survived),
        "kill_pz_decided": kill_decided,
        "kill_pz_failed": kill_out.get("wrong", 0) + kill_out.get("unpaired", 0),
        "kill_pz_deaths": kill_out.get("deaths", 0),
        "solve_med": f"{med(solve_t):.1f}",
        "solve_max": f"{max(solve_t):.1f}" if solve_t else "0",
        "kill_solve_med": f"{med(kill_solve):.1f}",
        "kill_solve_lo": f"{min(kill_solve):.1f}" if kill_solve else "0",
        "kill_solve_hi": f"{max(kill_solve):.1f}" if kill_solve else "0",
        "solve_over_kill": sum(1 for x in solve_t if kill_solve and x > max(kill_solve)),
        "first_pair_med": f"{med(first_pair):.1f}",
        "half_med": f"{med(half):.1f}",
        "stasis_after_med": f"{med(stasis_after):.1f}",
        "slow_names": names(f"{p} ({v['median']:.1f}s)" for p, v in slow),
        "last_names": names(f"{p} ({v['last']})" for p, v in last_top),
        "wrong_names": names(f"{p} ({c})" for p, c in wrong_top) or "nobody",
        "stranded_names": names(
            f"{p} ({v['stranded']})"
            for p, v in sorted(pzp.items(), key=lambda kv: -kv[1]["stranded"])
            if v["stranded"] >= 2
        )
        or "nobody more than once",
        "pz_wrong_list": names(f"pull {r['pull']} #{r['idx']}" for r in failed if r["outcome"] == "wrong")
        or "none",
        "pz_unpaired_list": names(
            f"pull {r['pull']} #{r['idx']}" for r in failed if r["outcome"] == "unpaired"
        )
        or "none",
        # droplets
        "drop_casts": len(drops),
        "drop_missed_sets": len(missed_sets),
        "blasts": blasts,
        "blast_hit": f"{blast_hit / 1e3:.0f}",
        "blast_deaths": len(blast_deaths),
        "blast_kill_sets": len(killing),
        "blast_standing_sets": len(standing),
        "blast_standing_deaths": sum(c["killed"] for c in standing),
        "blast_standing_wipes": len(standing_wipes),
        "blast_wipe_note": (
            "These are wipes the droplets started, not a raid already falling over."
            if standing and len(standing_wipes) >= len(standing) / 2
            else "Most of those pulls carried on, so the blasts cost lives more than pulls."
        ),
        "sk_sets": len(sk_sets),
        "sk_full": per_set_hits,
        "sk_per_set": per_set_n,
        "sk_total": soaked_total,
        "sk_top4": names(f"{p} ({v['pre'] + v['other']})" for p, v in top4),
        "sk_top4_pct": round(100 * sum(v["pre"] + v["other"] for _, v in top4) / soaked_total)
        if soaked_total
        else 0,
        "sk_top4_rate": names(f"{rate[p]:.1f}" for p, _ in top4),
        "sk_low": names(f"{p} ({rate[p]:.1f})" for p in low_dps),
        "sk_breath_pct": round(100 * by_side["breath"] / soaked_total) if soaked_total else 0,
        "sk_blood_pct": round(100 * by_side["blood"] / soaked_total) if soaked_total else 0,
        "sk_switch_pct": round(100 * by_side["switch"] / soaked_total) if soaked_total else 0,
        "sk_pre_med": f"{med(pre_t):.1f}",
        "sk_oth_med": f"{med(oth_t):.1f}",
        "sk_pre_late": round(100 * sum(1 for x in pre_t if x > 10) / len(pre_t)) if pre_t else 0,
        "sk_oth_late": round(100 * sum(1 for x in oth_t if x > 10) / len(oth_t)) if oth_t else 0,
        "pre_n": pre_n,
        "pre_missed": pre_missed,
        "pre_pct": round(100 * pre_missed / pre_n) if pre_n else 0,
        "pre_dead": pre_dead,
        "rest_n": rest_n,
        "rest_missed": rest_missed,
        "rest_pct": round(100 * rest_missed / rest_n) if rest_n else 0,
        "rest_dead": rest_dead,
        "multi_n": len(multi),
        "multi_dead": sum(c["killed"] or 0 for c in multi),
        "blast_pulls_word": word(len({c["pull"] for c in missed_sets})),
        "soakers_med": f"{med(soakers):.0f}",
        "kill_blasts": names(str(k["blasts"]) for k in kills),
        "drop_deaths": sum(1 for d in all_deaths if d["ability"] == spells.DROPLETS),
        # protovenom
        "pv_sets": len(pv),
        "pv_clean": pv_clean,
        "pv_pair_rate": f"{sum(r['pairs'] for r in pv_full) / max(1, len(pv_full)):.1f}",
        "kill_pv_rate": f"{kill_pv:.1f}",
        "eruptions": eruptions,
        "kill_eruptions": names(str(k["eruptions"]) for k in kills),
        "pv_deaths": sum(1 for d in all_deaths if d["ability"] in (spells.ERUPTION, spells.PROTOVENOM)),
        "top_carriers": names(f"{p} ({c})" for p, c in top_car),
        "pv_attr": len(attributed),
        "pv_unattr": len(collisions) - len(attributed),
        "pv_dist_med": f"{med([e['dist'] for e in attributed]):.1f}",
        "pv_marked_for_med": f"{med([e['marked_for'] for e in attributed]):.1f}",
        "pv_quick": len(quick),
        "pv_quick_pct": round(100 * len(quick) / len(attributed)) if attributed else 0,
        "pv_quick_note": (
            "Most eruptions happen in the first seconds after the marks go out, before anyone has had to "
            "walk anywhere: a marked player starting the mechanic next to someone clean."
            if attributed and len(quick) / len(attributed) >= 0.5
            else "Most eruptions come later, while marked players are walking to their partner."
        ),
        "car_rate": names(f"{p} ({c} of {m} times marked)" for p, c, m in car_rate),
        "top_touched": names(f"{p} ({c})" for p, c in top_touched),
        "repeat_pairs": names(f"{p} into {q} ({n})" for p, q, n in repeat_pairs) or "no pair more than twice",
        # red side
        "mi_n": len(mi),
        "mi_med": f"{med([x['soakers'] for x in mi]):.0f}",
        "mi_low_n": len(mi_low),
        "mi_deaths": sum(1 for d in all_deaths if d["ability"] == spells.MIASMA),
        "bl_n": len(bl),
        "bl_med": f"{med(bl_disp):.1f}",
        "bl_slow": sum(1 for x in bl_disp if x > 8),
        "bl_missed": sum(1 for r in bl if not r["dispelled"]),
        "pool_total": sum(v["pool"] for v in avoid.values()),
        "pool_deaths": sum(1 for d in all_deaths if d["ability"] == spells.BLOOD_VENOM),
        "pool_top": names(f"{p} ({c})" for p, c in pool_top),
        "living_first": living_first,
        "living_tot": living_tot,
        "living_deaths": sum(1 for d in all_deaths if d["ability"] == spells.LIVING_VENOM),
        "living_top": names(f"{p} ({c})" for p, c in living_top),
        "lv_hits": lv_hits,
        "lv_breath_pct": round(100 * sum(v["breath"] for v in lvp.values()) / lv_side) if lv_side else 0,
        "lv_rate_top": names(f"{p} ({r:.1f})" for p, r in lv_rate[:3]),
        "lv_rate_med": f"{med([r for _, r in lv_rate]):.1f}",
        "lv_rate_low": names(f"{p} ({r:.1f})" for p, r in lv_rate[-3:]),
        "lv_then_died": sum(c for _, c in lv_died),
        "lv_died_top": names(f"{p} ({c})" for p, c in lv_died[:3]) or "nobody",
        "lv_p1_rate": f"{raw['lv']['phase_rate'].get(1, 0):.1f}",
        "lv_p2_rate": f"{raw['lv']['phase_rate'].get(2, 0):.1f}",
        "lv_phase_note": lv_phase_note,
        # marks from the other boss
        "wm_extra": f"{wm_extra / 1e6:.0f}",
        "wm_pct": f"{100 * wm_extra / wm_mark:.1f}" if wm_mark else "0",
        "wm_apps": wm_apps,
        "wm_walk": kinds.get("walk", 0),
        "wm_extended": kinds.get("extended", 0),
        "wm_fresh": kinds.get("fresh", 0),
        "kill_wm_pct_lo": f"{min(k['wrong_pct'] for k in kills):.1f}",
        "kill_wm_pct_hi": f"{max(k['wrong_pct'] for k in kills):.1f}",
        "wm_rate": f"{wm_rate / 1e6:.1f}",
        "kill_wm_rate_lo": f"{min(kill_wm_rate) / 1e6:.1f}" if kill_wm_rate else "0",
        "kill_wm_rate_hi": f"{max(kill_wm_rate) / 1e6:.1f}" if kill_wm_rate else "0",
        "wm_level_note": (
            "So as a raid this night was no worse than the kills: the marks from the other boss are a "
            "handful of players, not a spacing problem across the room."
            if kill_wm_rate
            and wm_rate <= max(kill_wm_rate)
            and wm_mark
            and 100 * wm_extra / wm_mark <= max(k["wrong_pct"] for k in kills)
            else "That is more than any of the kills, so spacing from the bosses is costing the raid as a whole."
        ),
        "wm_top": names(
            f"{p} ({v['extra'] / 1e6:.0f}M, {100 * v['extra'] / v['mark']:.0f}% of their mark damage)"
            for p, v in wm_top
        ),
        "wm_top_rate": names(
            f"{p} {60 * v['extra'] / alive[p] / 1e6:.2f}M" for p, v in wm_top if alive.get(p)
        ),
        "wm_mark_top": names(
            f"{p} ({v['mark'] / 1e6:.0f}M)" for p, v in sorted(wm.items(), key=lambda kv: -kv[1]["mark"])[:3]
        ),
        "wm_mark_med": f"{med([v['mark'] for v in wm.values()]) / 1e6:.0f}",
        "wm_two": names(p for p, _ in wm_rank[:2]),
        "wm_kinds_top": names(
            f"{p}: {v['walk']} on the walk-out, {v['extended']} extending an old mark, {v['fresh']} fresh"
            for p, v in wm_rank[:2]
        ),
        "mark_share": round(100 * mark_dmg / taken_total) if taken_total else 0,
        "mark_peak": f"{peak_med:.0f}",
        "mark_deaths": len(mark_deaths),
        "mark_deaths_late": late_mark,
        "mark_deaths_solo": sum(1 for d in mark_deaths if d["solo"]),
        "mark_note": (
            "so they do not mostly kill at the end of a phase, when stacks are highest. They kill players "
            "who are already low."
            if mark_deaths and late_mark / len(mark_deaths) < 0.4
            else "so the marks do most of their killing as a phase runs long, when stacks are highest."
        ),
        # deaths
        "deaths_total": len(all_deaths),
        "solo_total": len(solo),
        "first_top": names(f"{label[k]} {c}" for k, c in first_groups.most_common(3)),
        "solo_top": names(f"{label[k]} {c}" for k, c in solo_groups.most_common(3)),
        # damage taken & defensives
        "maxdur": P["dtps"]["maxdur"],
        "n_nontank": len(P["dtps"]["players"]),
        "tank_names": names(P["dtps"]["tanks"]),
        "raid_reduced": round(100 * dt_tot["reduced"] / dt_inc),
        "raid_absorbed": round(100 * dt_tot["absorb"] / dt_inc),
        "n_spans": spans_total,
        "heavy_time_pct": round(100 * heavy_secs / fight_secs) if fight_secs else 0,
        "heavy_dmg_pct": round(100 * heavy_total / all_taken) if all_taken else 0,
        "majors_total": f"{sum(p['maj'] for p in mit):,}",
        "majors_heavy": sum(p["maj_heavy"] for p in mit),
        "majors_per_span": f"{sum(p['maj_heavy'] for p in mit) / spans_total:.1f}" if spans_total else "0",
        "stones": hs_total,
        "potions": pot_total,
        "consum_total": hs_total + pot_total,
        "hp_avg": round(statistics.mean(all_hp)) if all_hp else 0,
        "hp_median": round(statistics.median(all_hp)) if all_hp else 0,
        "hp_under40": sum(1 for x in all_hp if x < 40),
        "hp_under20": sum(1 for x in all_hp if x < 20),
        "hp_over80": sum(1 for x in all_hp if x >= 80),
        "never_hs_word_cap": word(len(never_hs)).capitalize(),
        "never_hs_names": names(never_hs),
        "stone_breakdown": names(f"{v} {k}" for k, v in stones.most_common() if k in spells.HEALTHSTONES),
        "potion_breakdown": names(f"{v} {k}" for k, v in stones.most_common() if k in spells.HEALTH_POTIONS),
        "early_no_def": early_nodef,
        "lust_note": (
            f"lust went out {min(lust):.0f} to {max(lust):.0f} seconds into every pull"
            if lust
            else "no lust was logged"
        ),
        "major_list": ", ".join(sorted(n for n in spells.MAJOR if a.ids_named(n))),
        "minor_list": ", ".join(sorted(n for n in spells.MINOR if a.ids_named(n))),
        "external_list": ", ".join(sorted(n for n in spells.EXTERNAL if a.ids_named(n))),
    }
    return t


def render(payload: dict, tok: dict, template: Path | None = None) -> str:
    html = (template or TEMPLATE).read_text(encoding="utf-8")
    for key, value in payload.items():
        html = html.replace(f"__PAYLOAD_{key.upper()}__", _json(value))

    def sub(m):
        name = m.group(1)
        if name not in tok:
            raise KeyError(f"template asks for {{{{{name}}}}}, which the builder does not compute")
        return _ascii(str(tok[name]))

    html = re.sub(r"\{\{(\w+)\}\}", sub, html)
    left = re.findall(r"__PAYLOAD_(\w+)__", html)
    if left:
        raise KeyError(f"no payload for {left}")
    return html


def _ascii(s: str) -> str:
    return "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in s)


def _json(value) -> str:
    # '</' would close the <script> the payload sits in
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, default=float).replace("</", "<\\/")
