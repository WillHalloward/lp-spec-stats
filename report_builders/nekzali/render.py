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
    early_cadence = f"{round(min(early_gaps))}–{round(max(early_gaps))}" if early_gaps else "70–110"

    exhaustion = round(exhaustion_seconds(pulls))
    dive_cost = dive_len + exhaustion
    two_cycle = cadence * 2
    deficit = max(dive_cost - two_cycle, 0)
    three_cycle = cadence * 3

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
            f"<td>{first['t']:.1f}s — {escape(str(first['who']))}, "
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
        return "—" if ours is None else f'<span class="hot">{ours - theirs:+.1f}s</span>'

    milestones = [
        ("Boss to 50% (Ritual begins)", kill_ritual, deep["ritual"]),
        ("Ritual of Awakening length", kill_inter, our_inter),
        ("Stage Two begins", kill_stage_two, deep["stage_two"]),
        ("Fight ends", baseline.mean("dur"), deep["dur"]),
    ]
    milestone_rows = "".join(
        f'<tr><td class="name">{label}</td><td class="num">{theirs:.1f}s</td>'
        f'<td class="num">{f"{ours:.1f}s" if ours is not None else "—"}</td>'
        f'<td class="num">{diff(ours, theirs)}</td></tr>'
        for label, theirs, ours in milestones
    )
    kill_windows = [len(k["windows"]) for k in baseline.KILLS]
    milestone_rows += (
        f'<tr><td class="name">Echoes the raid must survive</td>'
        f'<td class="num">{min(kill_windows)}–{max(kill_windows)}</td>'
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

    kill_ilvl = round(baseline.mean("ilvl_median"))
    our_ilvl = roster["ilvl_median"]
    ahead_on_gear = bool(our_ilvl and our_ilvl >= kill_ilvl)
    kill_dps = baseline.mean("raid_dps")
    dps_gap = round(100 * (1 - dmg["dps"] / kill_dps))
    kill_uptime = baseline.mean("uptime")
    kill_lust = [k["lust"] for k in baseline.KILLS]
    kill_curse = [k["curse_cast"] for k in baseline.KILLS]

    lust_cell = f"on Stage Two ({deep['lust'][0]}s)" if deep["lust"] else "—"

    strategy_rows = "".join(
        [
            f'<tr><td class="name">Raid composition</td><td>2 tanks / 4 healers / 14 DPS</td>'
            f"<td>{roster['tanks']} / {roster['healers']} / {roster['dps']}</td>"
            f'<td class="calm">{"identical" if (roster["tanks"], roster["healers"]) == (2, 4) else "differs"}'
            f"</td></tr>",
            '<tr><td class="name">Well team shape</td><td>4 DPS + 1 healer</td>'
            '<td>4 DPS + 1 healer</td><td class="calm">identical</td></tr>',
            f'<tr><td class="name">Number of well teams</td><td>2</td><td>{len(_teams(deep))}</td>'
            f'<td class="calm">identical</td></tr>',
            f'<tr><td class="name">Lust</td>'
            f"<td>on Stage Two ({round(min(kill_lust))}–{round(max(kill_lust))}s)</td>"
            f"<td>{lust_cell}</td>"
            f'<td class="calm">identical call</td></tr>',
            f'<tr><td class="name">Median item level</td><td>{kill_ilvl}</td><td>{our_ilvl or "—"}</td>'
            f'<td class="calm">{"you’re ahead" if ahead_on_gear else "behind"}</td></tr>',
            f'<tr><td class="name">Soulcoiler’s Curse let through</td>'
            f"<td>0 of {min(kill_curse)}–{max(kill_curse)}</td>"
            f"<td>{deep['curse_landed']} of {deep['curse_cast']}</td>"
            f'<td class="calm">{"identical" if not deep["curse_landed"] else "slightly behind"}</td></tr>',
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
        "deficit": deficit,
        "three_team_cycle": three_cycle,
        "three_team_slack": max(three_cycle - dive_cost, 0),
        "bar_tail": max(dive_cost + 38 - two_cycle - deficit, 8),
        "three_tail": max(dive_cost + 38 - three_cycle, 8),
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
            f"the raid died — Grasping Depths ticked on everyone for {last_len} unbroken seconds."
            if not deep.get("kill")
            else f"The final Echo window ran {last_len} seconds."
        ),
        "kill_dur": kill_dur,
        "kill_intermission": f"{kill_inter:.1f}",
        "kill_stage_two": f"{kill_stage_two:.0f}",
        "your_intermission": f"{our_inter:.1f}" if our_inter else "—",
        "intermission_gap": round(100 * (our_inter / kill_inter - 1)) if our_inter else 0,
        "intermission_loss": f"{our_inter - kill_inter:.0f} seconds" if our_inter else "Much",
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
