"""Fill the template: JSON payloads for the charts, tokens for the prose.

Every number a sentence says out loud arrives as a {{token}} computed here, so
the prose describes *this* night rather than the one before it. Rendering fails
loudly on a token the builder does not compute, so a new sentence cannot
silently keep last night's figure.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from . import spells as S

TEMPLATE = Path(__file__).parent / "template.html"

_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
          "nine", "ten", "eleven", "twelve"]


def word(n: int) -> str:
    return _WORDS[n] if 0 <= n < len(_WORDS) else f"{n:,}"


def names(items) -> str:
    items = list(items)
    if not items:
        return "nobody"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def millions(n: float) -> str:
    """9,138,105 -> '9.1M'. Big numbers read better than they count."""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}bn"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return f"{n:,.0f}"


def mmss(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def tokens(a, built: dict, *, date_long: str, night_title: str) -> dict:
    progress, orbs = built["progress"], built["orbs"]
    veil, burn, edge, mc = built["veil"], built["burn"], built["edge"], built["control"]
    mit = built["mitigation"]
    souls = built["souls"]

    kill = next((p for p in progress if p["kill"]), None)
    wipes = [p for p in progress if not p["kill"]]
    best_wipes = sorted(wipes, key=lambda p: p["best"])[:3]
    reached_p3 = [p for p in progress if "P3" in p["phases"]]

    tok = {
        "boss": a.boss,
        "difficulty": S.DIFFICULTY.get(a.difficulty, str(a.difficulty)),
        "date_long": date_long,
        "night": night_title,
        "code": a.code,
        "pulls": len(progress),
        "pulls_word": word(len(progress)),
        "killed": "yes" if kill else "no",
        "kill_pull": kill["pull"] if kill else 0,
        "kill_length": mmss(kill["duration"]) if kill else "—",
        "reached_p3": len(reached_p3),
        "past_eight": word(sum(1 for p in progress if p["duration"] > 480)),
        "longest_pull": mmss(max((p["duration"] for p in progress), default=0)),
        "best_wipe": f"{best_wipes[0]['best']:g}%" if best_wipes else "—",
        "best_wipe_pull": best_wipes[0]["pull"] if best_wipes else 0,
        "near_misses": names(f"{p['best']:g}%" for p in best_wipes),

        # --- stage timings (they barely move, which is the point) ---
        "p1_seconds": _median_phase(progress, "P1"),
        "p2_seconds": _median_phase(progress, "P2"),
        "int_seconds": _median_phase(progress, "INT"),

        # --- orbs ---
        "orb_carry": f"{orbs['carry_seconds']:g}",
        "orbs_picked": f"{orbs['picked']:,}",
        "orbs_detonated": f"{orbs['detonated']:,}",
        "orb_cleaves": orbs["cleave_count"],
        "orb_dry": word(orbs["dry_cleaves"]),
        "orbs_per_cleave": orbs["median_per_cleave"],
        "orbs_max_cleave": orbs["max_per_cleave"],
        "orb_carriers": orbs["distinct_carriers"],
        "orb_top3": names(c["name"] for c in orbs["carriers"][:3]),
        "orb_top3_share": f"{sum(c['share'] for c in orbs['carriers'][:3]):.0f}%",
        "orb_top_carrier": orbs["carriers"][0]["name"] if orbs["carriers"] else "—",
        "orb_top_count": orbs["carriers"][0]["total"] if orbs["carriers"] else 0,
        "orb_pulse_damage": millions(orbs["pulse_damage"]),
        "orb_burst_damage": millions(orbs["burst_damage"]),

        # --- the veil gate ---
        "veil_total": veil["total"],
        "veil_broken": veil["broken"],
        "veil_resolved": word(veil["resolved"]),
        "veil_deaths": veil["deaths"],
        "veil_shield": millions(veil["shield"]),
        "veil_seconds": f"{S.NIGHTFALL_WINDOW_SEC:g}",
        "veil_median_break": f"{veil['median_break']:g}",
        "veil_fastest": f"{veil['fastest_break']:g}",
        "veil_dps_needed": millions(veil["shield"] / S.NIGHTFALL_WINDOW_SEC) if veil["shield"] else "—",
        "veil_total_damage": millions(sum(p["damage"] for p in veil["players"])),
        "veil_top3": names(p["name"] for p in veil["players"][:3]),
        "veil_top3_share": f"{sum(p['share'] for p in veil['players'][:3]):.0f}%",

        # --- the burn window ---
        "burn_ratio": f"{burn['median_ratio']:g}",
        "burn_best": f"{burn['best']['ratio']:g}" if burn["best"] else "—",
        "burn_best_pull": burn["best"]["pull"] if burn["best"] else 0,
        "heal_rate": millions(burn["heal_rate"]),
        "heal_seconds": f"{burn['heal_seconds']:g}",
        "heal_total": millions(burn["heal_total"]),
        "lust_from": f"{burn['lust_window'][0]:+g}" if burn["lust_window"] else "—",
        "lust_to": f"{burn['lust_window'][1]:+g}" if burn["lust_window"] else "—",
        "lust_count": burn["lust_count"],
        "int_total_seconds": f"{burn['int_seconds']:g}",
        "band_early_n": burn["bands"]["early"]["count"],
        "band_late_n": burn["bands"]["late"]["count"],
        "band_early_at": mmss(burn["bands"]["early"]["median_transition"]),
        "band_late_at": mmss(burn["bands"]["late"]["median_transition"]),
        "band_early_ratio": f"{burn['bands']['early']['median_ratio']:g}",
        "band_late_ratio": f"{burn['bands']['late']['median_ratio']:g}",
        "earliest_transition": mmss(min((r["transition"] for r in burn["rows"]), default=0)),
        "band_split": f"{burn['split_at']:g}",
        "band_split_mmss": mmss(burn["split_at"]),
        "gate_damage": millions(burn["gate_damage"]),
        "gate_spread": f"{burn['gate_spread']:g}",
        "band_early_dps": millions(burn["bands"]["early"]["median_p2_dps"]) + "/s",
        "band_late_dps": millions(burn["bands"]["late"]["median_p2_dps"]) + "/s",
        "serpent_pool_one": millions(burn["pool_one"]),
        "serpent_pool_three": millions(burn["pool_three"]),
        "ghosts_each": word(int(round(burn["ghosts_median"]))),
        "ghosts_blocked": burn["blocked_total"],
        "ghosts_through": burn["reclaim_total"],
        "blast_each": millions(burn["blast_each"]),
        "reclaim_each": millions(burn["reclaim_each"]),
        "reclaim_healed": millions(burn["reclaim_healed"]),
        "reclaim_pct": (f"{100 * burn['reclaim_each'] / burn['pool_three']:.0f}%"
                        if burn["pool_three"] else "—"),
        "best_hp_end": _hp_extreme(burn["rows"], min),
        "worst_hp_end": _hp_extreme(burn["rows"], max),
        "burn_top_player": burn["players"][0]["name"] if burn["players"] else "—",
        "burn_top_damage": millions(burn["players"][0]["damage"]) if burn["players"] else "—",
        "burn_amp_player": _amp(burn["players"])["name"],
        "burn_amp_multiple": f"{_amp(burn['players'])['multiple']:g}",
        "burn_healer_multiple": _healer_multiple(burn["players"]),

        # --- the edge ---
        "falls": edge["falls"],
        "deaths_total": edge["total_deaths"],
        "deaths_counted": edge["counted_deaths"],
        "reset_falls": edge["reset_falls"],
        "reset_jumps": edge["reset_causes"].get("reset or collapse", 0),
        "falls_share": f"{edge['share']:g}%",
        "fall_knockback": edge["buckets"].get("knockback", 0),
        "fall_march": edge["buckets"].get("march", 0),
        "fall_unexplained": edge["buckets"].get("unexplained", 0),
        "knockback_at": f"{edge['knockback_at']:g}",
        "control_grace": f"{a.CONTROL_GRACE_MS / 1000:g}",
        "worst_fall_pull": edge["worst_pull"][0],
        "worst_fall_count": edge["worst_pull"][1],

        # --- mind control ---
        "march_casts": mc["march_casts"],
        "march_from_cast": mc["march_from_cast"],
        "caught_by_ghost": mc["caught_by_ghost"],
        "caught_died": mc["caught_died"],
        "caught_fell": mc["caught_fell"],
        "spawn_ratio": f"{mc['spawn_ratio']:g}",
        "spawn_lag": f"{mc['spawn_lag']:g}",
        "march_absorb": f"{S.MARCH_ABSORB:,}",
        "march_windows": mc["march_from_cast"] + mc["caught_by_ghost"],
        "breaks_done": mc["breaks_completed"],
        "possessions": mc["possessions_measured"],
        "breaks_pct": (f"{100 * mc['breaks_completed'] / mc['possessions_measured']:.0f}%"
                       if mc["possessions_measured"] else "—"),
        "break_median": f"{mc['break_median']:,.0f}",
        "shield_top": names(n for n, _ in mc["shield_breakers"][:3]),
        "fall_caught": edge["buckets"].get("caught", 0),
        "march_low": mc["march_per_cast"][0],
        "march_high": mc["march_per_cast"][1],
        "march_seconds": f"{mc['march_seconds']:g}",
        "fixate_apps": f"{mc['fixate_apps']:,}",
        "fixate_waves": mc["fixate_waves"],
        "fixate_size": mc["fixate_wave_size"],
        "fixate_offwave": mc["fixate_offwave"],
        "fixate_in_wave": mc["fixate_in_wave"],
        "offwave_gap": mc["offwave_gap"],
        "offwave_after_death": f"{mc['offwave_after_death']}%",
        "wave_after_death": f"{mc['wave_after_death']}%",
        "offwave_p3": mc["offwave_phases"].get("P3", 0),
        "offwave_p2": mc["offwave_phases"].get("P2", 0),
        "grips": dict(mc["cc_targeted"]).get("Death Grip", 0),
        "cc_targeted": mc["cc_targeted_total"],
        "cc_ground": mc["cc_ground_total"],
        "controlled": mc["ever_controlled"],

        # --- defensives ---
        "mit_windows": mit["windows"],
        "mit_majors": f"{mit['majors']:,}",
        "mit_in_window": mit["majors_pressure"],
        "mit_externals": mit["externals"],
        "mit_raidwides": mit["raidwides"],
        "mit_stones": mit["stones"],
        "mit_potions": mit["potions"],
        "mit_hp": _median_hp(mit["rows"]),
        "mit_skipped": names(mit["skipped"]),

        # --- gloombomb and the souls ---
        "gloom_casts": souls["gloom_casts"],
        "gloom_per_cast": word(int(round(souls["gloom_per_cast"]))),
        "blast_share": f"{souls['blast_share']:.0f}%",
        "pickup_share": f"{souls['pickup_share']:.0f}%",
        "pickup_hits": f"{souls['pickups']:,}",
        "failure_share": f"{souls['failure_share']:.0f}%",
        "failure_hits": souls["failures"],
        "soul_deaths": len(souls["deaths"]),
        "died_failing": souls["died_failing"],
        "died_collecting": souls["died_collecting"],
    }
    return {k: (v if isinstance(v, str) else v) for k, v in tok.items()}


def _hp_extreme(rows: list[dict], pick) -> str:
    """Best or worst resurrection the raid allowed, as a percentage."""
    vals = [r["serpent_hp_end"] for r in rows if r.get("serpent_hp_end") is not None]
    return f"{pick(vals):.0f}%" if vals else "—"


def _median_hp(rows: list[dict]) -> str:
    """Median health across every stone and potion pressed on the night."""
    vals = [r["hp_at_use"] for r in rows if r.get("hp_at_use") is not None]
    if not vals:
        return "—"
    vals.sort()
    return f"{vals[len(vals) // 2]:.0f}%"


def _amp(players: list[dict]) -> dict:
    """Steepest lift from stage one to the burn window, among the damage roles.
    A healer who does almost nothing in both phases can post a silly ratio."""
    pool = [p for p in players if p.get("role") == "DPS" and p.get("multiple")]
    if not pool:
        return {"name": "—", "multiple": 0}
    return max(pool, key=lambda p: p["multiple"])


def _healer_multiple(players: list[dict]) -> str:
    heals = [p["multiple"] for p in players if p.get("role") == "Healer" and p.get("multiple")]
    if not heals:
        return "1"
    return f"{sum(heals) / len(heals):.1f}"


def _median_phase(progress: list[dict], key: str) -> str:
    vals = sorted(p["phases"][key] for p in progress if key in p["phases"])
    if not vals:
        return "—"
    return f"{vals[len(vals) // 2]:.0f}"


def render(payloads: dict, tok: dict, template: Path | None = None) -> str:
    html = (template or TEMPLATE).read_text(encoding="utf-8")
    for key, value in payloads.items():
        html = html.replace(f"__PAYLOAD_{key.upper()}__", _json(value))

    def sub(m):
        key = m.group(1)
        if key not in tok:
            raise KeyError(f"template asks for {{{{{key}}}}} but the builder does not compute it")
        return str(tok[key])

    html = re.sub(r"\{\{(\w+)\}\}", sub, html)

    left = re.findall(r"__PAYLOAD_(\w+)__", html)
    if left:
        raise KeyError(f"template has payload slots with no data: {sorted(set(left))}")
    return html


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s)


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
