"""Fill the template: payloads as JSON, everything the prose states as a token.

Every number the page says out loud is computed here, so a second prog night on
the same boss regenerates its own sentences rather than inheriting the first
night's figures.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

from . import spells

TEMPLATE = Path(__file__).parent / "template.html"

WORDS = {
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
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
    20: "twenty",
}


def word(n: int) -> str:
    return WORDS.get(n, f"{n:,}")


def names(items) -> str:
    items = list(items)
    if not items:
        return "nobody"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _wave_phase_note(wv: dict, deaths1: int, deaths2: int, p2_pulls: int, fights) -> str:
    """Wave counts per phase, and which phase does the damage.

    Which phase carries the hits is not fixed: a night that rarely reaches the
    second phase barely sees its waves, so the conclusion is read off the counts.
    """
    c1, c2 = wv["wave_casts_p1"], wv["wave_casts_p2"]
    h1, h2 = wv["wave_hits_nontank_p1"], wv["wave_hits_nontank_p2"]
    if not (c1 or c2):
        return "No waves were cast."
    v1 = sum(f["wave_volleys_p1"] for f in fights)
    per1 = word(round(c1 / v1)) if v1 else "no"
    def rate(hits: int, casts: int) -> str:
        return f"{hits / casts:.2f} a cast" if casts else "no casts"
    out = (
        f"The boss throws them in two phases. Phase one is {word(round(v1 / len(fights)))} volleys "
        f"of about {per1} waves a pull, {c1} casts across the night, catching non-tanks {h1} times, "
        f"{rate(h1, c1)}. Phase two is {c2} casts on the {word(p2_pulls)} "
        f"pull{'s' if p2_pulls != 1 else ''} that reached it, {h2} hits, {rate(h2, c2)}. "
        f"Deaths split {deaths1} to {deaths2}."
    )
    hits, deaths = h1 + h2, deaths1 + deaths2
    if hits:
        heavy, hh, hd = ("one", h1, deaths1) if h1 >= h2 else ("two", h2, deaths2)
        out += (
            f" Phase {heavy} accounts for {hh} of the {hits} non-tank hits"
            + (f" and {hd} of the {deaths} deaths." if deaths else ".")
        )
    return out


def _split_damage_note(sides: dict, split: dict, pulls: int) -> str:
    """The paragraph about comparing the two sides on damage.

    Some nights hand the sides the same number of adds and some do not, and the
    direction is not fixed either, so every claim here is checked against the
    numbers before it is made.
    """
    w, e = sides.get("west", {}), sides.get("east", {})
    wa, ea = w.get("adds", 0), e.get("adds", 0)
    if not (wa or ea) or not pulls:
        return ""
    shares = f"{w.get('phase_share', 0):.1f}/{e.get('phase_share', 0):.1f}"
    night = f"{w.get('night_share', 0):.1f}/{e.get('night_share', 0):.1f}"
    per_w, per_e = w.get("dmg_per_add", 0) / 1e6, e.get("dmg_per_add", 0) / 1e6
    heavy, light = ("west", "east") if wa >= ea else ("east", "west")
    hi, lo = max(wa, ea), min(wa, ea)
    lopsided = lo and hi / lo >= 1.25

    counts = (
        f"West is handed {wa} adds across the night against east's {ea}, "
        f"{round(wa / pulls)} a pull against {round(ea / pulls)}."
    )
    if not lopsided:
        return (
            f"Both sides were handed much the same work this night, {wa} adds against {ea}, "
            f"{round(wa / pulls)} a pull against {round(ea / pulls)}, so the {shares} phase damage "
            f"split is a fair comparison. Night-wide the two are {night}."
        )

    name = split.get("add_name", "")
    per_side = split.get("add_split", {}) or {}
    one_add = ""
    if name and per_side:
        plural = name if name.endswith("s") else name + "s"
        one_add = (
            f" Most of the difference is one add: {heavy} takes {per_side.get(heavy, 0)} {plural} to "
            f"{light}'s {per_side.get(light, 0)}."
        )
    reversal = ""
    bigger, smaller = (per_w, per_e) if per_w >= per_e else (per_e, per_w)
    if smaller and bigger / smaller >= 1.15:
        richer = "west" if per_w > per_e else "east"
        reversal = (
            f" Per add the order reverses, {per_w:.1f}M west against {per_e:.1f}M east, because "
            f"{richer}'s are the larger targets."
        )
    return (
        f"The sides are not comparable on damage this night. {counts}{one_add} The {shares} phase "
        f"damage split measures that workload, not throughput: night-wide the two sides are "
        f"{night}.{reversal} Compare them on deaths and on getting back to the middle instead."
    )


def tokens(a, built: dict, *, date_long: str, night_title: str) -> dict:
    """One entry per {{token}} in the template."""
    P = built["payloads"]
    raw = built["raw"]
    data, mit, split = P["data"], P["mit"], P["split"]
    fights, players = data["fights"], data["players"]
    meta = data["meta"]
    burn, waves, heavy = raw["burn"], raw["waves"], raw["heavy"]

    wins = data["windows"]
    max_idx = max((w["idx"] for w in wins), default=1)
    by_idx = {i: [w for w in wins if w["idx"] == i] for i in range(1, max_idx + 1)}
    w1, w2 = by_idx.get(1, []), by_idx.get(2, [])
    w1_avg = statistics.mean(w["dmg"] for w in w1) if w1 else 0
    w2_avg = statistics.mean(w["dmg"] for w in w2) if w2 else 0
    # a window the pull ended inside is short because the pull ended, not because
    # the raid lost it; the page says which rather than claiming "always full"
    full_len = max((w["dur"] for w in wins), default=0)
    cut = [w for w in wins if w["dur"] < full_len - 1]
    ordinals = {1: "First", 2: "Second", 3: "Third", 4: "Fourth", 5: "Fifth"}
    avg_bits = []
    for i in range(1, max_idx + 1):
        group = by_idx.get(i) or []
        if not group:
            continue
        avg = statistics.mean(w["dmg"] for w in group) / 1e6
        avg_bits.append(
            f"{ordinals.get(i, str(i))} windows landed {avg:.1f}M on average"
            if not avg_bits
            else f"{ordinals.get(i, str(i)).lower()} windows {avg:.1f}M"
        )
    windows_avgs = ", ".join(avg_bits) + "."

    # lust, measured against the first exposure
    lust_ids = set()
    for n in spells.LUST:
        lust_ids |= a.ids_named(n)
    offsets = []
    for fid in a.ids:
        ws = a.windows(fid)
        if not ws:
            continue
        for e in a.casts(fid):
            if e.get("type") == "cast" and e.get("abilityGameID") in lust_ids:
                offsets.append((ws[0][0] - e["timestamp"]) / 1000)
    lust = [o for o in offsets if 0 < o < 60]

    two_window = [f for f in fights if f["n_windows"] > 1]
    dps_players = [p for p in players if p["role"] == "dps" and p["burn_dmg"] > 0]
    by_heart = sorted(dps_players, key=lambda p: -(p["heart_pct"] or 0))
    spans_total = sum(len(v["spans"]) for v in heavy.values())
    heavy_secs = sum(b - aa + 1 for v in heavy.values() for aa, b in v["spans"])
    fight_secs = sum(v["dur"] for v in heavy.values())
    taken_total = sum(v["total"] for v in heavy.values())
    heavy_total = sum(v["heavy_total"] for v in heavy.values())

    hp = [p["hp_at_use"] for p in mit["players"] if p["hp_at_use"] is not None]
    all_hp = [x for p in a.players for x in raw["mit"]["per"][p]["hp"]]
    stones = raw["mit"]["stones"]
    hs_total = sum(v for k, v in stones.items() if k in spells.HEALTHSTONES)
    pot_total = sum(v for k, v in stones.items() if k in spells.HEALTH_POTIONS)
    never_hs = [p["player"] for p in mit["players"] if p["hs"] == 0]

    non_tank = [p for p in mit["players"] if p["role"] != "tank"]
    low_cov = sorted([p for p in non_tank if p["maj"] > 0], key=lambda p: p["coverage"])[:3]
    brew = max(mit["players"], key=lambda p: p["minor"])
    blood = max(mit["players"], key=lambda p: p["maj"])

    dt_tot = Counter()
    for pl in P["dtps"]["pulls"].values():
        for row, key in ((pl["taken"], "taken"), (pl["absorb"], "absorb"), (pl["reduced"], "reduced")):
            dt_tot[key] += sum(sum(r) for r in row)
    dt_inc = sum(dt_tot.values()) or 1

    sides = split.get("sides") or {}
    split_rows = split.get("pulls") or []
    phase_starts = [r["start"] for r in split_rows]
    phase_durs = [r["dur"] for r in split_rows]
    east_tank = west_tank = ""
    for s in ("west", "east"):
        for p in sides.get(s, {}).get("members", []):
            if split["roles"].get(p) == "tank":
                if s == "west":
                    west_tank = p
                else:
                    east_tank = p
    moves = split.get("moves", [])
    oneoffs = split.get("oneoffs", [])
    sizes = split.get("sizes", [])

    def shape(side: str) -> str:
        r = sides.get(side, {}).get("roles", {})
        bits = [
            f"{r.get('tank', 0)} tank{'s' if r.get('tank', 0) != 1 else ''}",
            f"{r.get('healer', 0)} healer{'s' if r.get('healer', 0) != 1 else ''}",
            f"{r.get('dps', 0)} damage",
        ]
        return ", ".join(bits)

    early = sum(p["early_deaths"] for p in mit["players"])
    early_nodef = sum(p["early_no_def"] for p in mit["players"])
    no_consum = 0
    for p in a.players:
        v = raw["mit"]["per"][p]
        pulls_with = v["pulls_consum"]
        for fid in a.ids:
            if fid in pulls_with:
                continue
            no_consum += sum(1 for d in a.deaths(fid) if a.player_of(d.get("targetID")) == p)

    # the boss throws waves on two patterns, before and after the split phase
    wv = {
        k: sum(f[k] for f in fights)
        for k in (
            "wave_casts_p1",
            "wave_casts_p2",
            "wave_volleys_p1",
            "wave_volleys_p2",
            "wave_hits_nontank_p1",
            "wave_hits_nontank_p2",
            "wave_hits_tank_p1",
            "wave_hits_tank_p2",
        )
    }
    p1_pulls = sum(1 for f in fights if f["wave_casts_p1"])
    p2_pulls = sum(1 for f in fights if f["wave_casts_p2"])
    wave_deaths_p1 = sum(1 for d in data["wave_deaths"] if d.get("phase") == 1)
    wave_deaths_p2 = sum(1 for d in data["wave_deaths"] if d.get("phase") == 2)

    boss_raid = sum(p["boss_total"] for p in players) or 1
    boss_rank = sorted(players, key=lambda p: -p["boss_total"])

    # does the whole-fight order actually differ from the burn-window one? Some
    # nights it does and some it does not, so the page checks before claiming
    dps_only = [p for p in players if p["role"] == "dps"]
    burn_pos = {p["player"]: i for i, p in enumerate(sorted(dps_only, key=lambda p: -p["burn_dmg"]))}
    boss_pos = {p["player"]: i for i, p in enumerate(sorted(dps_only, key=lambda p: -p["boss_total"]))}
    shifts = sorted(
        ((burn_pos[p] - boss_pos[p], p) for p in burn_pos), key=lambda x: -abs(x[0])
    )
    big = [(d, p) for d, p in shifts if abs(d) >= 3]
    if not shifts:
        boss_vs_burn = ""
    elif not big:
        worst = abs(shifts[0][0])
        boss_vs_burn = (
            " The damage dealers land in nearly the burn-window order this night, nobody moving more "
            f"than {word(worst)} place{'s' if worst != 1 else ''}."
            if worst
            else " The damage dealers land in exactly the burn-window order this night."
        )
    else:
        bits = names(
            f"{p} {word(abs(d))} place{'s' if abs(d) != 1 else ''} {'higher' if d > 0 else 'lower'}"
            for d, p in big[:3]
        )
        boss_vs_burn = f" The order differs from the burn windows: {bits} than the windows put them."

    expose_casts = 0
    for fid in a.ids:
        expose_casts += sum(
            1
            for e in a.enemy_casts(fid)
            if a.ability.get(e.get("abilityGameID")) == spells.EXPOSE and e.get("type") == "cast"
        )

    kill_pull = next((f["pull"] for f in fights if f["kill"]), 0)

    t = {
        "report": a.code,
        "zone": (a.meta.get("zone") or {}).get("name", ""),
        "outcome": (
            "all wipes"
            if not any(f["kill"] for f in fights)
            else f"{sum(1 for f in fights if f['kill'])} kill"
            f"{'s' if sum(1 for f in fights if f['kill']) != 1 else ''}"
        ),
        "deep_pull": min(fights, key=lambda f: f["boss_pct"])["pull"] if fights else 1,
        # a night that ends in a kill leads with the kill; a night that does not
        # leads with how close it got, so the same template reads right either way
        "kill_pull": kill_pull,
        "best_line": (
            f"Killed on pull {kill_pull} of {meta['pulls']}"
            if kill_pull
            else f"Best pull: {meta['best_pct']:.2f}% remaining"
            if meta["best_pct"] is not None
            else "Best pull: n/a"
        ),
        "tile_best_n": str(kill_pull) if kill_pull else f"{meta['best_pct']:.2f}<small>%</small>",
        "tile_best_lab": "the pull it died on" if kill_pull else "best pull, boss left",
        "pulls_caption_lead": (
            f"Boss health remaining at the end of each pull. Pull {kill_pull} was the kill."
            if kill_pull
            else "Boss health remaining at the wipe."
        ),
        "boss": a.fights[0]["name"] if a.fights else "the boss",
        "difficulty": spells.DIFFICULTY.get(a.difficulty, str(a.difficulty)),
        "date_long": date_long,
        "night_title": night_title,
        "pulls": meta["pulls"],
        "pulls_word": word(meta["pulls"]),
        "raiders": len(a.players),
        "raiders_word": word(len(a.players)),
        "best_pct": f"{meta['best_pct']:.2f}" if meta["best_pct"] is not None else "n/a",
        "n_windows": meta["n_windows"],
        "n_windows_word": word(meta["n_windows"]),
        "window_secs": meta["window_secs"],
        "window_len": round(statistics.median(w["dur"] for w in wins)) if wins else 20,
        "burn_total": f"{meta['total_burn'] / 1e9:.2f}",
        "heart_pct": round(100 * meta["total_heart"] / meta["total_burn"]) if meta["total_burn"] else 0,
        "boss_share_pct": round(100 * meta["total_boss"] / meta["total_burn"]) if meta["total_burn"] else 0,
        "w1_avg": f"{w1_avg / 1e6:.1f}",
        "max_windows": max_idx,
        "max_windows_word": word(max_idx),
        "window_avgs": windows_avgs,
        "window_full_note": (
            f"Every one ran the full {round(full_len)} seconds; no window was lost early."
            if not cut
            else (
                f"{word(len(cut)).capitalize()} of them ran short, at "
                + names(f"{w['dur']:.0f} seconds" for w in sorted(cut, key=lambda w: w["dur"]))
                + ", because the pull ended inside the window rather than the raid losing it."
            )
        ),
        "third_window_note": (
            ""
            if max_idx < 3
            else (
                f" {word(len(by_idx.get(3, []))).capitalize()} pull"
                f"{'s' if len(by_idx.get(3, [])) != 1 else ''} reached a third window "
                f"({names('pull ' + str(w['fight']) for w in by_idx.get(3, []))}). It is the window the "
                "boss dies in, and it reads low because it runs short with nothing left on cooldown."
            )
        ),
        # legends are built from the windows the night reached, not assumed
        "pull_legend": "".join(
            f'<span><i style="background:var(--s{i})"></i>'
            f'{word(i)} heart window{"s" if i != 1 else ""}</span>'
            for i in range(1, max_idx + 1)
        ),
        "window_legend": "".join(
            f'<span><i style="background:var(--s{i})"></i>window {i}: heart</span>'
            f'<span><i style="background:var(--s{i});opacity:.45"></i>window {i}: Ula&#39;tek</span>'
            for i in range(1, max_idx + 1)
        ),
        "w2_avg": f"{w2_avg / 1e6:.1f}",
        "drop_pct": round(100 * (1 - w2_avg / w1_avg)) if w1_avg else 0,
        "lust_lo": round(min(lust)) if lust else 0,
        "lust_hi": round(max(lust)) if lust else 0,
        "shelf_pct": round(max((f["boss_pct"] for f in two_window), default=0)),
        "heart_best": by_heart[0]["player"] if by_heart else "",
        "heart_best_pct": round(by_heart[0]["heart_pct"]) if by_heart else 0,
        "heart_worst": names(p["player"] for p in by_heart[-2:]) if len(by_heart) > 1 else "",
        "heart_worst_pct": round(by_heart[-1]["heart_pct"]) if by_heart else 0,
        # the shared health pool, whole fight
        "boss_dmg_total": (
            f"{sum(p['boss_total'] for p in players) / 1e9:.2f}B"
            if sum(p["boss_total"] for p in players) >= 1e9
            else f"{sum(p['boss_total'] for p in players) / 1e6:.0f}M"
        ),
        "boss_ulatek_pct": round(100 * sum(p["boss_ulatek"] for p in players) / boss_raid),
        "boss_heart_pct": round(100 * sum(p["boss_heart"] for p in players) / boss_raid),
        "boss_gore_pct": round(100 * sum(p["boss_gore"] for p in players) / boss_raid, 1),
        "boss_vs_burn": boss_vs_burn,
        "boss_top": boss_rank[0]["player"] if boss_rank else "",
        "boss_top_dmg": f"{boss_rank[0]['boss_total'] / 1e6:.0f}M" if boss_rank else "0M",
        "wave_casts": sum(f["wave_casts"] for f in fights),
        "wave_hits": sum(p["wave_hits"] for p in players),
        "wave_nontank": sum(p["wave_hits"] for p in players if p["role"] != "tank"),
        "wave_deaths": len(data["wave_deaths"]),
        "wave_phase_note": _wave_phase_note(wv, wave_deaths_p1, wave_deaths_p2, p2_pulls, fights),
        "wave_casts_p1": wv["wave_casts_p1"],
        "wave_casts_p2": wv["wave_casts_p2"],
        "wave_nontank_p1": wv["wave_hits_nontank_p1"],
        "wave_nontank_p2": wv["wave_hits_nontank_p2"],
        "wave_tank_p1": wv["wave_hits_tank_p1"],
        "wave_tank_p2": wv["wave_hits_tank_p2"],
        "wave_deaths_p1": wave_deaths_p1,
        "wave_deaths_p2": wave_deaths_p2,
        "wave_p1_pulls_word": word(p1_pulls),
        "wave_p2_pulls_word": word(p2_pulls),
        "wave_volleys_p1_typical": (
            round(statistics.median([f["wave_volleys_p1"] for f in fights if f["wave_volleys_p1"]]))
            if p1_pulls
            else 0
        ),
        "wave_volleys_p2_max": max((f["wave_volleys_p2"] for f in fights), default=0),
        "wave_per_volley_p1": (
            f"{wv['wave_casts_p1'] / sum(f['wave_volleys_p1'] for f in fights):.0f}"
            if sum(f["wave_volleys_p1"] for f in fights)
            else "0"
        ),
        "wave_per_volley_p2": (
            f"{wv['wave_casts_p2'] / sum(f['wave_volleys_p2'] for f in fights):.0f}"
            if sum(f["wave_volleys_p2"] for f in fights)
            else "0"
        ),
        "wave_miss_rate_p1": (
            round(100 * wv["wave_hits_nontank_p1"] / wv["wave_casts_p1"]) if wv["wave_casts_p1"] else 0
        ),
        "wave_miss_rate_p2": (
            round(100 * wv["wave_hits_nontank_p2"] / wv["wave_casts_p2"]) if wv["wave_casts_p2"] else 0
        ),
        "split_start_lo": min(phase_starts) if phase_starts else 0,
        "split_start_hi": max(phase_starts) if phase_starts else 0,
        "split_start_range": (
            f"{min(phase_starts)}s"
            if phase_starts and min(phase_starts) == max(phase_starts)
            else f"{min(phase_starts)} to {max(phase_starts)}s"
            if phase_starts
            else "n/a"
        ),
        "split_dur_range": (
            f"{min(phase_durs)}s"
            if phase_durs and min(phase_durs) == max(phase_durs)
            else f"{min(phase_durs)} to {max(phase_durs)} seconds"
            if phase_durs
            else "n/a"
        ),
        "split_dur_lo": min(phase_durs) if phase_durs else 0,
        "split_dur_hi": max(phase_durs) if phase_durs else 0,
        "split_pulls_word": word(len(split_rows)),
        "boss_back_avg": (
            round(statistics.median([r["boss_again"] for r in split_rows if r.get("boss_again") is not None]))
            if any(r.get("boss_again") is not None for r in split_rows)
            else 0
        ),
        "split_size": len(sides.get("west", {}).get("members", [])),
        "split_size_word": word(len(sides.get("west", {}).get("members", []))),
        "west_tank": west_tank,
        "east_tank": east_tank,
        "west_tank_class": a.players.get(west_tank, {}).get("subType", ""),
        "east_phase_share": f"{sides.get('east', {}).get('phase_share', 0):.1f}",
        "east_night_share": f"{sides.get('east', {}).get('night_share', 0):.1f}",
        "west_phase_share": f"{sides.get('west', {}).get('phase_share', 0):.1f}",
        "west_night_share": f"{sides.get('west', {}).get('night_share', 0):.1f}",
        # the sides are handed different amounts of work, so the damage split is
        # reported next to the add count that causes it
        "west_adds": sides.get("west", {}).get("adds", 0),
        "east_adds": sides.get("east", {}).get("adds", 0),
        "west_adds_per_pull": (
            round(sides.get("west", {}).get("adds", 0) / len(split_rows)) if split_rows else 0
        ),
        "east_adds_per_pull": (
            round(sides.get("east", {}).get("adds", 0) / len(split_rows)) if split_rows else 0
        ),
        "west_per_add": f"{sides.get('west', {}).get('dmg_per_add', 0) / 1e6:.1f}",
        "east_per_add": f"{sides.get('east', {}).get('dmg_per_add', 0) / 1e6:.1f}",
        # whether the sides can be compared on damage at all depends on whether
        # they were handed the same work, which varies night to night, so the
        # paragraph is built from the numbers rather than asserting last night's
        "split_damage_note": _split_damage_note(sides, split, len(split_rows)),
        "split_add_name": (
            split.get("add_name", "side adds") + ("" if split.get("add_name", "s").endswith("s") else "s")
        ),
        "split_add_west": split.get("add_split", {}).get("west", 0),
        "split_add_east": split.get("add_split", {}).get("east", 0),
        "split_clean_word": word(split.get("clean", 0)),
        "split_dead_word": word(len(split_rows) - split.get("clean", 0)),
        # the phase is reported, not policed: one side ran short, and the page says
        # which side and by how much rather than naming who walked the wrong way
        "split_shape": (
            f"west {len(sides.get('west', {}).get('members', []))} "
            f"({shape('west')}) and east {len(sides.get('east', {}).get('members', []))} "
            f"({shape('east')})"
            if sides
            else "one side each"
        ),
        "split_size_min": min((min(w, e) for w, e in sizes), default=0),
        "split_size_max": max((max(w, e) for w, e in sizes), default=0),
        # a side that changes for a run of pulls is a reassignment; a single odd
        # pull is someone walking the wrong way. The page reports both as counts.
        "split_change_sentence": (
            (
                f"{word(len(moves)).capitalize()} player{'s' if len(moves) != 1 else ''} moved to the other "
                f"side partway through, at "
                + names(f"pull {n}" for n in sorted({m["at"] for m in moves}))
                + ", so each pull is read on its own. "
                if moves
                else "Nobody changed sides all night. "
            )
            + (
                f"{word(len(oneoffs)).capitalize()} pull"
                f"{'s' if len(oneoffs) != 1 else ''} had somebody on the far side of their own assignment ("
                + names(f"pull {o['pull']}" for o in sorted(oneoffs, key=lambda o: o["pull"]))
                + "), which is what a wrong turn looks like."
                if oneoffs
                else "No pull had anyone standing on the far side of their own assignment."
            )
        ),
        "maxdur": P["dtps"]["maxdur"],
        "n_nontank": len(P["dtps"]["players"]),
        "tank_names": names(P["dtps"]["tanks"]),
        "raid_reduced": round(100 * dt_tot["reduced"] / dt_inc),
        "raid_absorbed": round(100 * dt_tot["absorb"] / dt_inc),
        "n_spans": spans_total,
        "heavy_time_pct": round(100 * heavy_secs / fight_secs) if fight_secs else 0,
        "heavy_dmg_pct": round(100 * heavy_total / taken_total) if taken_total else 0,
        "majors_total": f"{sum(p['maj'] for p in mit['players']):,}",
        "majors_heavy": sum(p["maj_heavy"] for p in mit["players"]),
        "majors_per_span": f"{sum(p['maj_heavy'] for p in mit['players']) / spans_total:.1f}"
        if spans_total
        else "0",
        "brew_player": brew["player"],
        "brew_spec": brew["spec"],
        "brew_count": brew["top_minor"][0][1] if brew["top_minor"] else brew["minor"],
        "brew_spell": brew["top_minor"][0][0] if brew["top_minor"] else "short-cooldown mitigation",
        "blood_player": blood["player"],
        "blood_spec": blood["spec"],
        "blood_majors": blood["maj"],
        "low_cov_names": names(p["player"] for p in low_cov),
        "stones": hs_total,
        "potions": pot_total,
        "consum_total": hs_total + pot_total,
        "hp_avg": round(statistics.mean(all_hp)) if all_hp else 0,
        "hp_median": round(statistics.median(all_hp)) if all_hp else 0,
        "hp_under40": sum(1 for x in all_hp if x < 40),
        "hp_under20": sum(1 for x in all_hp if x < 20),
        "hp_over80": sum(1 for x in all_hp if x >= 80),
        "never_hs_word": word(len(never_hs)),
        "never_hs_word_cap": word(len(never_hs)).capitalize(),
        "never_hs_names": names(never_hs),
        "stone_breakdown": names(f"{v} {k}" for k, v in stones.most_common() if k in spells.HEALTHSTONES),
        "potion_breakdown": names(f"{v} {k}" for k, v in stones.most_common() if k in spells.HEALTH_POTIONS),
        "early_deaths": early,
        "early_no_def": early_nodef,
        "deaths_no_consum": no_consum,
        "expose_casts": expose_casts,
        "no_window_pulls_word": word(sum(1 for f in fights if f["n_windows"] == 0)),
        "wave_name": spells.WAVE,
        "wave_dmg_ids": names(str(i) for i in sorted(a.ids_named(spells.WAVE))),
        "expose_name": spells.EXPOSE,
        "major_list": ", ".join(sorted(n for n in spells.MAJOR if a.ids_named(n))),
        "minor_list": ", ".join(sorted(n for n in spells.MINOR if a.ids_named(n))),
        "external_list": ", ".join(sorted(n for n in spells.EXTERNAL if a.ids_named(n))),
    }
    return t


def render(payloads: dict, tok: dict, template: Path | None = None) -> str:
    html = (template or TEMPLATE).read_text(encoding="utf-8")
    for key, value in payloads.items():
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
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, default=float)
