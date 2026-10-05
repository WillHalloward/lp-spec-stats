"""The public Mythic kills a prog night is measured against.

Six kills from the encounter's speed rankings (encounter 3445): the two earliest
in the list, Wisp and Blur on 2 and 3 September at item level 320, and four from
the slow end of the list in late September and early October at 326-327, the
same gear a Low Pressure roster brings. They are a fixed reference rather than
something the builder refetches: they are historical, they do not change, and a
prog night reads better against the same yardstick each week.

Every number is what `analyze.Analysis.pull_summary` returns for that kill, so a
kill and a prog pull are measured by the same code. To refresh or extend the
set, pull the rankings and feed each (code, fightID) through it:

    query{worldData{encounter(id:3445){fightRankings(difficulty:5,metric:speed,page:1)}}}

    a = Analysis(code, fight_ids=[fight]); a.pull_summary(fight)

The list only reaches the thousand fastest kills (everything slower than 6:17
is cut), so "slow" here means slow among those.

`healed` is what Vitriolic Stasis gave back across the kill (raw health on one
boss or the other), `phase_dps` boss damage per second in each damage phase,
`solved` each intermission's length, `blasts` droplets nobody soaked.
"""

from __future__ import annotations

KILLS = [
    {
        "guild": "Wisp",
        "region": "EU",
        "date": "2026-09-02",
        "code": "NKfjbtHrXnJpLdG9",
        "fight": 48,
        "dur": 368.6,
        "ilvl_median": 320,
        "comp": [2, 4, 14],
        "stasis": 3,
        "solved": [13.0, 13.0, 12.0],
        "inter_secs": 38.0,
        "phase_secs": 330.6,
        "healed": 29584095,
        "gaps": [1.0, 2.15, 7.99],
        "dom_secs": 3.0,
        "blasts": 0,
        "pv_sets": 7,
        "pv_pairs": 26,
        "eruptions": 0,
        "deaths": 3,
        "deaths_150": 1,
        "boss_dmg": 898658732,
        "boss_dps": 2718513,
        "phase_dps": [4535593, 2418037, 2127140, 2651015],
        "wrong_extra": 7154828,
        "wrong_apps": 42,
        "wrong_pct": 2.2,
        "puzzle_solve": [12.9, 12.3, 11.4],
        "puzzle_outcomes": ["solved", "solved", "solved"],
        "puzzle_wrong": 0,
        "lust": 4.5,
    },
    {
        "guild": "Blur",
        "region": "US",
        "date": "2026-09-03",
        "code": "8fgAPrnqHRKdazmc",
        "fight": 13,
        "dur": 367.8,
        "ilvl_median": 320,
        "comp": [2, 4, 14],
        "stasis": 4,
        "solved": [11.0, 11.0, 13.0, 11.0],
        "inter_secs": 46.0,
        "phase_secs": 321.8,
        "healed": 22047034,
        "gaps": [1.75, 3.81, 1.48, 1.79],
        "dom_secs": 0,
        "blasts": 1,
        "pv_sets": 7,
        "pv_pairs": 22,
        "eruptions": 0,
        "deaths": 3,
        "deaths_150": 0,
        "boss_dmg": 891121473,
        "boss_dps": 2769514,
        "phase_dps": [4677803, 2495206, 2126766, 2707469, 1350221],
        "wrong_extra": 45105223,
        "wrong_apps": 110,
        "wrong_pct": 12.1,
        "puzzle_solve": [10.0, 10.9, 12.4, None],
        "puzzle_outcomes": ["solved", "solved", "solved", "kill"],
        "puzzle_wrong": 1,
        "lust": 0.1,
    },
    {
        "guild": "The Revengers",
        "region": "EU",
        "date": "2026-10-01",
        "code": "yDhFVnYCag7MkcbR",
        "fight": 26,
        "dur": 376.9,
        "ilvl_median": 326,
        "comp": [2, 4, 14],
        "stasis": 3,
        "solved": [9.1, 10.0, 9.0],
        "inter_secs": 28.1,
        "phase_secs": 348.9,
        "healed": 58608163,
        "gaps": [8.71, 3.03, 3.46],
        "dom_secs": 0,
        "blasts": 1,
        "pv_sets": 7,
        "pv_pairs": 26,
        "eruptions": 4,
        "deaths": 7,
        "deaths_150": 0,
        "boss_dmg": 927710635,
        "boss_dps": 2659202,
        "phase_dps": [4364868, 2559330, 2367766, 2274992],
        "wrong_extra": 27052140,
        "wrong_apps": 64,
        "wrong_pct": 7.4,
        "puzzle_solve": [8.1, 9.1, 8.3],
        "puzzle_outcomes": ["solved", "solved", "solved"],
        "puzzle_wrong": 0,
        "lust": 0.9,
    },
    {
        "guild": "Skyhold",
        "region": "US",
        "date": "2026-10-03",
        "code": "wN6kPTJMHWr3f19q",
        "fight": 27,
        "dur": 376.5,
        "ilvl_median": 327,
        "comp": [2, 4, 14],
        "stasis": 4,
        "solved": [15.1, 14.0, 9.1, 12.0],
        "inter_secs": 50.2,
        "phase_secs": 326.4,
        "healed": 16568991,
        "gaps": [4.25, 0.51, 0.82, 0.29],
        "dom_secs": 0,
        "blasts": 1,
        "pv_sets": 7,
        "pv_pairs": 26,
        "eruptions": 2,
        "deaths": 4,
        "deaths_150": 1,
        "boss_dmg": 885652634,
        "boss_dps": 2713122,
        "phase_dps": [4393724, 2523094, 2320755, 2468124, 1803024],
        "wrong_extra": 34256096,
        "wrong_apps": 70,
        "wrong_pct": 9.2,
        "puzzle_solve": [14.5, 13.7, 8.5, 11.9],
        "puzzle_outcomes": ["solved", "solved", "solved", "solved"],
        "puzzle_wrong": 0,
        "lust": 0.4,
    },
    {
        "guild": "Lucid",
        "region": "US",
        "date": "2026-10-02",
        "code": "fvC7DNhGxPFBjcLM",
        "fight": 3,
        "dur": 376.9,
        "ilvl_median": 327,
        "comp": [2, 4, 14],
        "stasis": 3,
        "solved": [12.0, 13.0, 12.9],
        "inter_secs": 37.9,
        "phase_secs": 338.9,
        "healed": 9163849,
        "gaps": [0.64, 0.38, 2.23],
        "dom_secs": 0,
        "blasts": 2,
        "pv_sets": 7,
        "pv_pairs": 21,
        "eruptions": 0,
        "deaths": 5,
        "deaths_150": 1,
        "boss_dmg": 878101056,
        "boss_dps": 2590811,
        "phase_dps": [4249167, 2572174, 2333027, 2107572],
        "wrong_extra": 31644635,
        "wrong_apps": 78,
        "wrong_pct": 8.9,
        "puzzle_solve": [12.0, 12.8, 12.0],
        "puzzle_outcomes": ["solved", "solved", "solved"],
        "puzzle_wrong": 0,
        "lust": 2.3,
    },
    {
        "guild": "The Extendables",
        "region": "EU",
        "date": "2026-09-23",
        "code": "mh1DAv6aBtnPF7qg",
        "fight": 15,
        "dur": 377.0,
        "ilvl_median": 326,
        "comp": [2, 4, 14],
        "stasis": 3,
        "solved": [14.0, 16.0, 12.0],
        "inter_secs": 42.0,
        "phase_secs": 335.0,
        "healed": 22019190,
        "gaps": [3.78, 1.91, 1.11],
        "dom_secs": 0,
        "blasts": 1,
        "pv_sets": 7,
        "pv_pairs": 23,
        "eruptions": 0,
        "deaths": 2,
        "deaths_150": 0,
        "boss_dmg": 891105512,
        "boss_dps": 2660199,
        "phase_dps": [4155135, 2363750, 2381803, 2468956],
        "wrong_extra": 41436145,
        "wrong_apps": 66,
        "wrong_pct": 11.1,
        "puzzle_solve": [14.0, 15.5, 11.9],
        "puzzle_outcomes": ["solved", "solved", "solved"],
        "puzzle_wrong": 0,
        "lust": 1.0,
    },
]

BOSS_HP = 434552938  # each Sentinel; the two pools are the same and never move


def mean(key: str) -> float:
    return sum(k[key] for k in KILLS) / len(KILLS)


def lo(key: str) -> float:
    return min(k[key] for k in KILLS)


def hi(key: str) -> float:
    return max(k[key] for k in KILLS)


def phase_dps(i: int) -> list[float]:
    """Each kill's boss damage per second in damage phase i (1-based)."""
    return [k["phase_dps"][i - 1] for k in KILLS if len(k["phase_dps"]) >= i]
