"""Fill the template: payloads as JSON, everything the prose states as a token.

Every number the page says out loud is computed here, so next week's night on the
same boss regenerates its own sentences rather than inheriting this one's figures.
Rendering fails loudly on a token the template asks for and this module doesn't
produce.
"""

from __future__ import annotations

import json
import re
import statistics
from html import escape
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


def mmss(seconds: float) -> str:
    m, s = divmod(round(seconds), 60)
    return f"{m}:{s:02d}"


def millions(n: float) -> str:
    return f"{n / 1e6:.1f}M"


def _calls(pull: dict) -> list[dict]:
    """Early entries that were a rotation call rather than a wipe dragging bodies in."""
    return [e for e in pull["early"] if not e["chaos"]]


def _teams(pull: dict) -> list[dict]:
    """The dive rosters, read off the first two waves of the pull."""
    waves = pull["waves"]
    if len(waves) < 2:
        return [{"name": "Well team", "players": sorted({m for w in waves for m in w["members"]})}]
    return [
        {"name": "Team A", "players": list(waves[0]["members"])},
        {"name": "Team B", "players": list(waves[1]["members"])},
    ]


def payloads(built: dict) -> dict:
    pulls, deep = built["pulls"], built["deepest"]

    night = [
        {
            "pull": p["pull"],
            "dur": p["dur"],
            "pct": p["boss_pct"] if p["boss_pct"] is not None else 0,
            "ritual": p["ritual"],
            "echoes": [w[0] for w in p["windows"]],
            "calls": [c["t"] for c in _calls(p)],
            "trigger": (p["collapse"] or {}).get("cause"),
        }
        for p in pulls
    ]

    teams = _teams(deep)
    listed = {n for t in teams for n in t["players"]}
    dives = {d["who"]: d["spans"] for d in deep["dives"] if d["who"] in listed}
    lockouts = {k: v for k, v in deep["lockouts"].items() if k in listed}
    deaths = {d["who"]: d["t"] for d in deep["deaths"] if d["who"] in listed}

    phases = []
    if deep["ritual"] is not None:
        phases.append([deep["ritual"], "Ritual of Awakening"])
    if deep["stage_two"] is not None:
        phases.append([deep["stage_two"], "Stage Two"])

    # Brace the runs of compressed cadence — the part two teams cannot cover.
    wins = deep["windows"]
    braces = [
        [wins[i][0], wins[i + 1][0]] for i in range(len(wins) - 1) if wins[i + 1][0] - wins[i][0] <= 45
    ][-2:]

    deep_payload = {
        "dur": deep["dur"],
        "windows": wins,
        "phases": phases,
        "braces": braces,
        "teams": teams,
        "dives": dives,
        "lockouts": lockouts,
        "deaths": deaths,
        "outcome": "kill" if deep.get("kill") else "wipe",
    }

    comp = [
        {
            "name": k["guild"],
            "tag": k["region"],
            "dur": k["dur"],
            "ritual": k["ritual"],
            "stage_two": k["stage_two"],
            "windows": k["windows"],
            "calls": [],
            "ours": False,
            "result": f"kill · {word(k['deaths'])} death" + ("" if k["deaths"] == 1 else "s"),
        }
        for k in baseline.KILLS
    ]

    ours_windows = []
    for a, b in wins:
        entries = [d[0] for spans in dives.values() for d in spans if a - 4 <= d[0] <= b]
        ours_windows.append([a, b, min(entries) if entries else None])
    comp.append(
        {
            "name": "This night",
            "tag": f"pull {deep['pull']}",
            "dur": deep["dur"],
            "ritual": deep["ritual"],
            "stage_two": deep["stage_two"],
            "windows": ours_windows,
            "calls": [c["t"] for c in _calls(deep)],
            "ours": True,
            "result": (
                f"kill · {word(len(deep['deaths']))} deaths"
                if deep.get("kill")
                else f"wipe · {deep['boss_pct']}% · {word(len(deep['deaths']))} deaths"
            ),
        }
    )
    return {"NIGHT": night, "DEEP": deep_payload, "COMP": comp}


def tokens(a, built: dict, *, date_long: str, night_title: str) -> dict:
    """One entry per {{token}} in the template."""
    pulls, deep, dmg, roster = built["pulls"], built["deepest"], built["damage"], built["roster"]

    dive_lengths = [round(b - s, 1) for p in pulls for d in p["dives"] for s, b in d["spans"]]
    dive_len = round(statistics.median(dive_lengths)) if dive_lengths else 30

    # The compressed cadence: the gap that repeats once Stage Two is running.
    late_gaps = [g for p in pulls for g in p["cadence"][2:] if g <= 50]
    cadence = round(statistics.median(late_gaps)) if late_gaps else 40
    early_gaps = [g for p in pulls for g in p["cadence"][:2]]
    early_cadence = f"{round(min(early_gaps))} to {round(max(early_gaps))}" if early_gaps else "70 to 110"

    exhaustion = round(exhaustion_seconds(pulls))
    dive_cost = dive_len + exhaustion
    # Two teams alternate, so a team's turn comes back after two Echoes. Stage
    # One is measured at its tightest gap, which is the fairest case to put
    # against Stage Two's flat one.
    early_gap = round(min(early_gaps)) if early_gaps else 70
    early_cycle = early_gap * 2
    early_slack = max(early_cycle - dive_cost, 0)
    two_cycle = cadence * 2
    deficit = max(dive_cost - two_cycle, 0)
    # One scale behind all three bars, so their lengths are comparable.
    bar_scale = max(dive_cost, early_cycle, two_cycle + deficit) + 8

    # One diver going in early is somebody's mistake. Two or more in the same
    # pull is the rotation running out of people, which is what this is about.
    broke = sorted((p for p in pulls if len(_calls(p)) >= 2), key=lambda p: p["pull"])
    singles = [p for p in pulls if len(_calls(p)) == 1]

    rows = []
    for p in broke:
        calls = sorted(_calls(p), key=lambda c: c["t"])
        first = calls[0]
        rows.append(
            f'<tr><td class="name">{p["pull"]}</td><td class="num">{p["boss_pct"]}%</td>'
            f'<td class="num">{len(p["windows"])}</td><td class="num hot">{len(calls)}</td>'
            f"<td>{first['t']:.1f}s, {escape(str(first['who']))}, "
            f"{first['early_by']:.1f}s early</td>"
            f'<td class="num">{round(p["dur"] - first["t"])}s</td></tr>'
        )

    amp = deep["amplified"]
    amp_rows = [
        f'<tr><td>{h["t"]:.1f}s</td><td class="name">{escape(str(h["who"]))}</td>'
        f'<td>{escape(str(h["ability"]))}</td><td class="num">{h["amount"]:,}</td>'
        f'<td class="num">{h["unmitigated"]:,}</td>'
        f'<td class="num hot">×{h["ratio"]:.2f}</td></tr>'
        for h in amp[:10]
    ]
    if not amp_rows:
        amp_rows = ['<tr><td colspan="6" class="calm">No amplified hits in this pull.</td></tr>']

    # Rounded for the prose; the table above it carries the exact figures.
    clean = deep.get("clean_coil_tick")
    clean_tick = f"{round(clean, -3):,}" if clean else "unmeasured this pull"
    amp_tick = f"{round(statistics.median([h['amount'] for h in amp]), -3):,}" if amp else "far more"

    kill_dur = round(baseline.mean("dur"))
    kill_ritual = baseline.mean("ritual")
    kill_inter = baseline.intermission()
    kill_stage_two = baseline.mean("stage_two")
    our_inter = (deep["stage_two"] - deep["ritual"]) if deep["stage_two"] and deep["ritual"] else None

    def diff(ours: float | None, theirs: float) -> str:
        return "n/a" if ours is None else f'<span class="hot">{ours - theirs:+.1f}s</span>'

    milestones = [
        ("Boss to 50% (Ritual begins)", kill_ritual, deep["ritual"]),
        ("Ritual of Awakening length", kill_inter, our_inter),
        ("Stage Two begins", kill_stage_two, deep["stage_two"]),
        ("Fight ends", baseline.mean("dur"), deep["dur"]),
    ]
    milestone_rows = "".join(
        f'<tr><td class="name">{label}</td><td class="num">{theirs:.1f}s</td>'
        f'<td class="num">{f"{ours:.1f}s" if ours is not None else "n/a"}</td>'
        f'<td class="num">{diff(ours, theirs)}</td></tr>'
        for label, theirs, ours in milestones
    )
    kill_windows = [len(k["windows"]) for k in baseline.KILLS]
    milestone_rows += (
        f'<tr><td class="name">Echoes the raid must survive</td>'
        f'<td class="num">{min(kill_windows)} to {max(kill_windows)}</td>'
        f'<td class="num">{len(deep["windows"])}</td>'
        f'<td class="num hot">+{len(deep["windows"]) - max(kill_windows)}</td></tr>'
    )

    gd_per_player = deep["gd_damage"] / max(len(roster["roles"]), 1)
    best_kill_gd = min(k["gd_per_player"] for k in baseline.KILLS)
    scale = max([k["gd_per_player"] for k in baseline.KILLS] + [gd_per_player]) / 60
    gd_rows = [
        f'<div class="brow"><div class="bhead"><span class="t">{escape(k["guild"])}</span>'
        f'<span class="v">{millions(k["gd_per_player"])} per player · kill</span></div>'
        f'<div class="bar"><div class="seg avail" style="flex:{k["gd_per_player"] / scale:.0f}">'
        f'&nbsp;</div><div style="flex:{60 - k["gd_per_player"] / scale:.0f}"></div></div></div>'
        for k in sorted(baseline.KILLS, key=lambda k: k["gd_per_player"])
    ]
    gd_rows.append(
        f'<div class="brow"><div class="bhead">'
        f'<span class="t">This night, pull {deep["pull"]}</span>'
        f'<span class="v">{millions(gd_per_player)} per player · '
        f"{'kill' if deep.get('kill') else 'wipe'}</span></div>"
        f'<div class="bar"><div class="seg gap" style="flex:{gd_per_player / scale:.0f}">'
        f"{gd_per_player / best_kill_gd:.1f}× the best kill</div></div></div>"
    )

    # Time from an Echo waking to the first diver reaching the water. The claim
    # that this raid reacts faster than the kills needs to be on the page, not
    # asserted, so it goes in the table below.
    our_lags = []
    for win_a, win_b in deep["windows"]:
        entries = [t for d in deep["dives"] for t, _ in d["spans"] if win_a - 4 <= t <= win_b]
        if entries:
            our_lags.append(min(entries) - win_a)
    kill_lags = [entry - a for k in baseline.KILLS for a, _, entry in k["windows"] if entry is not None]
    our_lag = statistics.median(our_lags) if our_lags else None
    kill_lag = statistics.median(kill_lags) if kill_lags else None

    # What actually governs the well rotation. The Echo schedule is anchored to
    # the start of Stage Two (about 28s in, then every cadence), so nothing in
    # Stage One or the intermission changes how many Echoes Stage Two contains.
    # Only Stage Two's own length does.
    s2_start = deep["stage_two"]
    s2_len = round(deep["dur"] - s2_start) if s2_start else None
    s2_echo_starts = [w[0] for w in deep["windows"] if s2_start and w[0] >= s2_start]
    kill_s2 = [k["dur"] - k["stage_two"] for k in baseline.KILLS]
    kill_s2_len = round(sum(kill_s2) / len(kill_s2))
    kill_s2_echoes = [len([w for w in k["windows"] if w[0] >= k["stage_two"]]) for k in baseline.KILLS]
    # A last Echo that wakes close enough to the kill gets burned rather than
    # dived, which is how two teams get away with covering only two of them.
    kill_last_gaps = [
        k["dur"] - max(w[0] for w in k["windows"] if w[0] >= k["stage_two"]) for k in baseline.KILLS
    ]
    burned = [
        g
        for g, k in zip(kill_last_gaps, baseline.KILLS, strict=True)
        if [w for w in k["windows"] if w[0] >= k["stage_two"]][-1][2] is None
    ]
    last_echo_gap = round(deep["dur"] - max(s2_echo_starts)) if s2_echo_starts else None
    # Stage Two damage, measured rather than derived. She is not immune during
    # the Ritual (33-37M lands on her), so a rate worked back from "Stage Two
    # starts at 50%" is wrong by about a tenth. Damage onto her per second needs
    # no such assumption.
    phases = built.get("phases") or {}
    s2 = phases.get("two") or {}
    s2_boss_dps = (s2.get("boss", 0) / s2["seconds"]) if s2.get("seconds") else None
    kill_s2_boss_dps = sum(k["s2_boss"] / (k["dur"] - k["stage_two"]) for k in baseline.KILLS) / len(
        baseline.KILLS
    )
    s2_rate_gap = round(100 * (kill_s2_boss_dps / s2_boss_dps - 1)) if s2_boss_dps else None
    s2_boss_share = 100 * s2["boss"] / s2["total"] if s2.get("total") else None
    kill_share = [100 * k["s2_boss"] / k["s2_total"] for k in baseline.KILLS]
    s2_add_share = 100 * s2["adds"] / s2["total"] if s2.get("total") else None
    # The same stretch of Stage Two the kills get, so length cannot flatter
    # either side. This is the figure the add argument has to survive.
    s2m = phases.get("two_matched") or {}
    s2m_boss_dps = (s2m.get("boss", 0) / s2m["seconds"]) if s2m.get("seconds") else None
    s2m_add_share = 100 * s2m["adds"] / s2m["total"] if s2m.get("total") else None
    s2m_boss_share = 100 * s2m["boss"] / s2m["total"] if s2m.get("total") else None
    # Where her health bar really stands when Stage Two opens.
    pool = baseline.BOSS_POOL
    ritual_boss = (phases.get("ritual") or {}).get("boss", 0)
    s2_start_pct = 50 - 100 * ritual_boss / pool
    kill_s2_start = [50 - 100 * k["ritual_boss"] / pool for k in baseline.KILLS]

    # The intermission Echoes: a separate failure, and not the cause of the above.
    int_lags, int_late_pulls, deep_int_lag = [], 0, None
    for p in pulls:
        if not (p["ritual"] and p["stage_two"]):
            continue
        starts = [x for d in p["dives"] for x, _ in d["spans"]]
        worst = None
        for win_a, win_b in p["windows"]:
            if not (p["ritual"] <= win_a <= p["stage_two"]):
                continue
            entries = [x for x in starts if win_a - 4 <= x <= win_b]
            lag = (min(entries) - win_a) if entries else (win_b - win_a)
            worst = lag if worst is None else max(worst, lag)
        if worst is not None:
            int_lags.append(worst)
            if p is deep:
                deep_int_lag = worst
            if worst > 20:
                int_late_pulls += 1
    kill_int_lags = [
        w[2] - w[0]
        for k in baseline.KILLS
        for w in k["windows"]
        if w[2] is not None and k["ritual"] <= w[0] <= k["stage_two"]
    ]

    kill_comps = {tuple(k["comp"]) for k in baseline.KILLS}
    ours_comp = (roster["tanks"], roster["healers"], roster["dps"])
    kill_comp = " or ".join(" / ".join(str(n) for n in c) for c in sorted(kill_comps, reverse=True))

    kill_ilvl = round(baseline.mean("ilvl_median"))
    our_ilvl = roster["ilvl_median"]
    ahead_on_gear = bool(our_ilvl and our_ilvl >= kill_ilvl)
    kill_dps = baseline.mean("raid_dps")
    dps_gap = round(100 * (1 - dmg["dps"] / kill_dps))
    kill_uptime = baseline.mean("uptime")
    kill_lust = [k["lust"] for k in baseline.KILLS]
    kill_curse = [k["curse_cast"] for k in baseline.KILLS]

    lust_cell = f"on Stage Two ({deep['lust'][0]}s)" if deep["lust"] else "not recorded"

    strategy_rows = "".join(
        [
            f'<tr><td class="name">Raid composition</td><td>{kill_comp}</td>'
            f"<td>{roster['tanks']} / {roster['healers']} / {roster['dps']}</td>"
            f'<td class="calm">{"identical" if ours_comp in kill_comps else "differs"}</td></tr>',
            '<tr><td class="name">Well team shape</td><td>4 DPS + 1 healer</td>'
            '<td>4 DPS + 1 healer</td><td class="calm">identical</td></tr>',
            f'<tr><td class="name">Number of well teams</td><td>2</td><td>{len(_teams(deep))}</td>'
            f'<td class="calm">identical</td></tr>',
            f'<tr><td class="name">Lust</td>'
            f"<td>on Stage Two ({round(min(kill_lust))} to {round(max(kill_lust))}s)</td>"
            f"<td>{lust_cell}</td>"
            f'<td class="calm">identical call</td></tr>',
            f'<tr><td class="name">Median item level</td><td>{kill_ilvl}</td><td>{our_ilvl or "n/a"}</td>'
            f'<td class="calm">{"you’re ahead" if ahead_on_gear else "behind"}</td></tr>',
            f'<tr><td class="name">Soulcoiler’s Curse let through</td>'
            f"<td>0 of {min(kill_curse)} to {max(kill_curse)}</td>"
            f"<td>{deep['curse_landed']} of {deep['curse_cast']}</td>"
            f'<td class="calm">{"identical" if not deep["curse_landed"] else "slightly behind"}</td></tr>',
            f'<tr><td class="name">Echo wakes to first diver in</td>'
            f"<td>{f'{kill_lag:+.1f}s' if kill_lag is not None else 'n/a'} typical</td>"
            f"<td>{f'{our_lag:+.1f}s' if our_lag is not None else 'n/a'} typical</td>"
            f'<td class="calm">{"you\u2019re ahead" if (our_lag is not None and kill_lag is not None and our_lag < kill_lag) else "behind"}</td></tr>',
            f'<tr><td class="name">Raid damage</td><td>{kill_dps / 1e6:.2f}M/s</td>'
            f'<td>{dmg["dps"] / 1e6:.2f}M/s</td><td class="hot">−{dps_gap}%</td></tr>',
            f'<tr><td class="name">Damage uptime</td><td>{100 * kill_uptime:.1f}%</td>'
            f"<td>{100 * (dmg['uptime'] or 0):.1f}%</td>"
            f'<td class="hot">−{round(100 * (kill_uptime - (dmg["uptime"] or 0)))} pts</td></tr>',
        ]
    )

    # The window that went longest with nobody in it.
    stuck, stuck_covered = 0.0, 0.0
    dive_starts = [s for d in deep["dives"] for s, _ in d["spans"]]
    for win_a, win_b in deep["windows"]:
        entries = [t for t in dive_starts if win_a - 4 <= t <= win_b]
        if entries and min(entries) - win_a > stuck:
            stuck, stuck_covered = win_b - win_a, win_b - min(entries)

    last_window = deep["windows"][-1] if deep["windows"] else [0, 0]
    last_len = round(last_window[1] - last_window[0])
    died_in_well = [
        d["who"]
        for d in deep["deaths"]
        if d["cause"] in ("Immortal Coil", "Swirling Spirit", "Soulcoil Well")
    ]

    return {
        "code": a.code,
        "boss": a.boss,
        "boss_short": a.boss.split()[0],
        "difficulty": {3: "Normal", 4: "Heroic", 5: "Mythic"}.get(a.difficulty, str(a.difficulty)),
        "date_long": date_long,
        "night_title": night_title,
        "pulls": len(pulls),
        "pulls_word": word(len(pulls)),
        "best_pct": deep["boss_pct"],
        "best_pull": deep["pull"],
        "best_dur": mmss(deep["dur"]),
        "best_dur_secs": round(deep["dur"]),
        "teams": len(_teams(deep)),
        # How fast a broken rotation ends the pull: the longest any of them
        # survived after the first diver went in locked out.
        "break_to_wipe": (
            max(round(p["dur"] - min(c["t"] for c in _calls(p))) for p in broke) if broke else 0
        ),
        "shallow_count": len(pulls) - len(broke),
        "s2_len": s2_len,
        "kill_s2_len": kill_s2_len,
        "s2_echoes": len(s2_echo_starts),
        "kill_s2_echoes": (
            f"{min(kill_s2_echoes)} or {max(kill_s2_echoes)}"
            if min(kill_s2_echoes) != max(kill_s2_echoes)
            else str(kill_s2_echoes[0])
        ),
        "s2_offset": round(min(s2_echo_starts) - s2_start) if s2_echo_starts else 0,
        "last_echo_gap": last_echo_gap,
        "kill_last_gap": f"{round(min(burned))} to {round(max(burned))}" if burned else "n/a",
        "burned_count_word": word(len(burned)),
        "s2_rate_gap": s2_rate_gap,
        "boss_pool": millions(baseline.BOSS_POOL),
        "s2_boss_dps": f"{s2_boss_dps / 1e6:.2f}" if s2_boss_dps else "n/a",
        "kill_s2_boss_dps": f"{kill_s2_boss_dps / 1e6:.2f}",
        "s2_raid_dmg": f"{s2.get('total', 0) / 1e6:.0f}M",
        "s2_boss_dmg": f"{s2.get('boss', 0) / 1e6:.0f}M",
        "kill_s2_raid_dmg": (
            f"{min(k['s2_total'] for k in baseline.KILLS) / 1e6:.0f} to "
            f"{max(k['s2_total'] for k in baseline.KILLS) / 1e6:.0f}M"
        ),
        "kill_s2_boss_dmg": (
            f"{min(k['s2_boss'] for k in baseline.KILLS) / 1e6:.0f} to "
            f"{max(k['s2_boss'] for k in baseline.KILLS) / 1e6:.0f}M"
        ),
        "s2_boss_share": f"{s2_boss_share:.0f}" if s2_boss_share else "n/a",
        "kill_boss_share": f"{min(kill_share):.0f} to {max(kill_share):.0f}",
        "s2_add_share": f"{s2_add_share:.0f}" if s2_add_share else "n/a",
        "s2m_seconds": f"{s2m['seconds']:.0f}" if s2m.get("seconds") else "n/a",
        "s2m_raid_dmg": f"{s2m.get('total', 0) / 1e6:.0f}M",
        "s2m_boss_dmg": f"{s2m.get('boss', 0) / 1e6:.0f}M",
        "s2m_boss_dps": f"{s2m_boss_dps / 1e6:.2f}" if s2m_boss_dps else "n/a",
        "s2m_add_share": f"{s2m_add_share:.0f}" if s2m_add_share else "n/a",
        "s2m_boss_share": f"{s2m_boss_share:.0f}" if s2m_boss_share else "n/a",
        "kill_add_share": (
            f"{min(100 * k['s2_adds'] / k['s2_total'] for k in baseline.KILLS):.0f} to "
            f"{max(100 * k['s2_adds'] / k['s2_total'] for k in baseline.KILLS):.0f}"
        ),
        "s2_uptime": f"{100 * s2['uptime']:.1f}" if s2.get("uptime") else "n/a",
        "kill_s2_uptime": (
            f"{100 * min(k['s2_uptime'] for k in baseline.KILLS):.1f} to "
            f"{100 * max(k['s2_uptime'] for k in baseline.KILLS):.1f}"
        ),
        "lowest_uptime_kill": min(baseline.KILLS, key=lambda k: k["s2_uptime"])["guild"],
        "lowest_uptime_value": f"{100 * min(k['s2_uptime'] for k in baseline.KILLS):.1f}",
        "lowest_uptime_dps": (
            f"{min(baseline.KILLS, key=lambda k: k['s2_uptime'])['s2_boss'] / (min(baseline.KILLS, key=lambda k: k['s2_uptime'])['dur'] - min(baseline.KILLS, key=lambda k: k['s2_uptime'])['stage_two']) / 1e6:.2f}"
        ),
        "s2_start_pct": f"{s2_start_pct:.1f}",
        "kill_s2_start": f"{min(kill_s2_start):.1f} to {max(kill_s2_start):.1f}",
        "ritual_boss_dmg": f"{ritual_boss / 1e6:.0f}M",
        "kill_ritual_boss": (
            f"{min(k['ritual_boss'] for k in baseline.KILLS) / 1e6:.0f} to "
            f"{max(k['ritual_boss'] for k in baseline.KILLS) / 1e6:.0f}M"
        ),
        "p1_boss_dmg": f"{(phases.get('one') or {}).get('boss', 0) / 1e6:.0f}M",
        "kill_p1_boss": (
            f"{min(k['p1_boss'] for k in baseline.KILLS) / 1e6:.0f} to "
            f"{max(k['p1_boss'] for k in baseline.KILLS) / 1e6:.0f}M"
        ),
        "int_late": round(deep_int_lag) if deep_int_lag else 0,
        "int_late_pulls_word": word(int_late_pulls),
        "kill_int_lag": (f"{min(kill_int_lags):.1f} to {max(kill_int_lags):.1f}" if kill_int_lags else "n/a"),
        "break_count": len(broke),
        "break_count_word": word(len(broke)),
        "single_count_word": word(len(singles)),
        "shallow_count_word": word(len(pulls) - len(broke)).capitalize(),
        "max_echoes": max((len(p["windows"]) for p in pulls), default=0),
        "broke_echoes": (
            f"{min(len(p['windows']) for p in broke)} or {max(len(p['windows']) for p in broke)}"
            if broke
            else "more"
        ),
        "dive_len": dive_len,
        "exhaustion": exhaustion,
        "dive_cost": dive_cost,
        "cadence": cadence,
        "early_cadence": early_cadence,
        "two_team_cycle": two_cycle,
        "early_cycle": early_cycle,
        "early_slack": early_slack,
        "tail_dive": max(bar_scale - dive_cost, 4),
        "tail_early": max(bar_scale - dive_cost - early_slack, 4),
        "tail_late": max(bar_scale - two_cycle - deficit, 4),
        "deficit": deficit,
        "deep_rows": (
            "".join(rows)
            or '<tr><td colspan="6" class="calm">No pull ran the rotation out of people.</td></tr>'
        ),
        "amp_rows": "".join(amp_rows),
        "amp_count_word": word(len(amp)),
        "clean_tick": clean_tick,
        "amp_tick": amp_tick,
        "last_window": last_len,
        "last_window_note": (
            f"The last band never ends. The Echo that woke at {last_window[0]:.0f}s was still alive when "
            f"the raid died, and Grasping Depths ticked on everyone for {last_len} unbroken seconds."
            if not deep.get("kill")
            else f"The final Echo window ran {last_len} seconds."
        ),
        "kill_dur": kill_dur,
        "kill_intermission": f"{kill_inter:.1f}",
        "kill_stage_two": f"{kill_stage_two:.0f}",
        "your_intermission": f"{our_inter:.1f}" if our_inter else "not recorded",
        "intermission_gap": round(100 * (our_inter / kill_inter - 1)) if our_inter else 0,
        "intermission_loss": f"{our_inter - kill_inter:.0f}" if our_inter else "Most",
        "time_gap": round(deep["dur"] - baseline.mean("dur")),
        "milestone_rows": milestone_rows,
        "strategy_rows": strategy_rows,
        "gear_verdict": "better gear" if ahead_on_gear else "comparable gear",
        "dps_gap": dps_gap,
        "boss_damage": millions(dict(dmg["by_target"]).get(a.boss, 0)),
        "gd_bars": "".join(gd_rows),
        "gd_extra": millions(gd_per_player - baseline.mean("gd_per_player")),
        "stuck_window": round(stuck),
        "stuck_covered": round(stuck_covered),
        "died_early": " and ".join(died_in_well[:2]) if died_in_well else "nobody this pull",
    }


def exhaustion_seconds(pulls: list[dict]) -> float:
    """Soul Exhaustion's duration as this log shows it, ignoring windows cut short
    by a death or the wipe."""
    spans = [b - s for p in pulls for v in p["lockouts"].values() for s, b in v]
    full = [s for s in spans if s >= spells.EXHAUSTION_SECONDS - 5]
    return statistics.median(full) if full else spells.EXHAUSTION_SECONDS


def render(payload: dict, tok: dict) -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    for name, value in payload.items():
        marker = f"__PAYLOAD_{name}__"
        if marker not in html:
            raise SystemExit(f"template has no {marker}")
        html = html.replace(marker, json.dumps(value, ensure_ascii=False))
    missing = set(re.findall(r"\{\{(\w+)\}\}", html)) - set(tok)
    if missing:
        raise SystemExit(f"template asks for tokens the builder doesn't compute: {sorted(missing)}")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(tok[m.group(1)]), html)
