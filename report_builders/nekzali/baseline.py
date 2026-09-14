"""The day-one Mythic kills this report measures a prog night against.

These are public logs from 2 September 2026, the first day Mythic opened, taken
from the encounter's speed rankings. They are a fixed reference rather than
something the builder refetches: they are historical, they do not change, and a
prog night is more interesting held against the same yardstick each week.

To refresh or extend the set, pull the rankings and re-run the same analysis:

    query{worldData{encounter(id:3470){fightRankings(difficulty:5,metric:speed,page:1)}}}

then feed each (code, fightID) through `analyze.Analysis` — the numbers below
are exactly what it computes, plus the per-target damage split from the damage
table. `windows` is [start, end, first_diver_entry_or_null] per Echo; a null
entry is an Echo nobody dived, which for three of these four is how the fight
ends — they burn the boss down through it.
"""

from __future__ import annotations

KILLS = [
    {
        "guild": "Snowblind",
        "comp": (2, 4, 14),
        "region": "US",
        "date": "2026-09-02",
        "code": "haCGP2q1rgNKdBpA",
        "fight": 18,
        "dur": 418,
        "deaths": 1,
        "teams": 2,
        "team_shape": "4 DPS + 1 healer",
        "ritual": 156.6,
        "stage_two": 288.8,
        "lust": 302,
        "ilvl_median": 317,
        "raid_dps": 2.66e6,
        "uptime": 0.968,
        "gd_per_player": 2.6e6,
        "curse_cast": 15,
        "curse_landed": 0,
        "windows": [
            [43.5, 70.5, 42.7],
            [114.5, 139.5, 114.5],
            [204.1, 228.1, 206.3],
            [263.0, 288.0, 263.9],
            [317.3, 341.3, 318.2],
            [357.3, 388.3, 359.7],
            [397.3, 417.3, None],
        ],
    },
    {
        "guild": "Epoch",
        "comp": (2, 4, 14),
        "region": "EU",
        "date": "2026-09-02",
        "code": "3DkvhAgmBxV6TfPW",
        "fight": 6,
        "dur": 415,
        "deaths": 0,
        "teams": 2,
        "team_shape": "3 DPS + 1 healer",
        "ritual": 154.0,
        "stage_two": 283.1,
        "lust": 293,
        "ilvl_median": 318,
        "raid_dps": 2.62e6,
        "uptime": 0.944,
        "gd_per_player": 3.0e6,
        "curse_cast": 18,
        "curse_landed": 0,
        "windows": [
            [43.5, 72.5, 43.6],
            [114.6, 148.6, 117.0],
            [201.4, 233.5, 203.1],
            [262.6, 282.6, 263.9],
            [311.6, 333.6, 314.4],
            [351.6, 390.6, 355.8],
        ],
    },
    {
        "guild": "Shattered",
        "comp": (2, 4, 14),
        "region": "EU",
        "date": "2026-09-02",
        "code": "zmPJg7T9YcWFBbdD",
        "fight": 44,
        "dur": 414,
        "deaths": 0,
        "teams": 2,
        "team_shape": "4 DPS + 1 healer",
        "ritual": 155.0,
        "stage_two": 285.7,
        "lust": 290,
        "ilvl_median": 318,
        "raid_dps": 2.67e6,
        "uptime": 0.936,
        "gd_per_player": 2.2e6,
        "curse_cast": 14,
        "curse_landed": 0,
        "windows": [
            [43.5, 66.5, 43.3],
            [114.6, 134.6, 114.3],
            [202.5, 226.5, 204.3],
            [261.8, 284.8, 263.4],
            [314.2, 340.2, 316.5],
            [354.2, 378.2, 354.4],
            [394.2, 413.2, None],
        ],
    },
    {
        "guild": "The Hex Pistols",
        "comp": (2, 3, 15),
        "region": "EU",
        "date": "2026-09-02",
        "code": "q14TZfypBFVva93W",
        "fight": 38,
        "dur": 415,
        "deaths": 2,
        "teams": 2,
        "team_shape": "4 DPS + 1 healer",
        "ritual": 159.8,
        "stage_two": 288.9,
        "lust": 301,
        "ilvl_median": 317,
        "raid_dps": 2.62e6,
        "uptime": 0.856,
        "gd_per_player": 2.6e6,
        "curse_cast": 13,
        "curse_landed": 0,
        "windows": [
            [43.5, 63.5, 42.6],
            [114.5, 145.5, 116.4],
            [207.3, 232.3, 208.1],
            [265.3, 288.3, 266.4],
            [317.4, 336.4, 317.1],
            [357.4, 390.4, 358.4],
            [397.4, 414.4, None],
        ],
    },
]

# Health pools that do not move, which makes them a stopwatch: every raid above
# did exactly these numbers, so the only variable is how long it took them.
JAWAE_POOL = 198.9e6
BOSS_POOL = 697.1e6


def mean(key: str) -> float:
    return sum(k[key] for k in KILLS) / len(KILLS)


def intermission() -> float:
    """How long the Ritual of Awakening took them, start to last Jawae death."""
    return sum(k["stage_two"] - k["ritual"] for k in KILLS) / len(KILLS)
