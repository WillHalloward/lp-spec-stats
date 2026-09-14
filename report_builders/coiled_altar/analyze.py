"""The numbers behind the page.

What this encounter is about, in the order the page tells it:

  progress    how far each pull got, phase by phase
  orbs        who carried, and how many detonated in each frontal
  veil        the flat absorb Malacrass hides behind, and the 15s to break it
  burn        the intermission, and how much of the serpent comes back
  edge        the falls, the largest single cause of death
  control     the two mind controls, and what the raid did about them
  souls       Gloombomb, and the three souls it leaves behind
  mitigation  defensives, externals and consumables

Everything keys off `spells.py` names resolved against the report's own
ability table, so a patch that re-issues ids does not break the build.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from . import spells as S
from .fetch import Fetcher


def _amount(e: dict) -> float:
    return (e.get("amount") or 0) + (e.get("absorbed") or 0)


class Analysis:
    def __init__(
        self, code: str, encounter_id: int | None = None, difficulty: int | None = None, cache_root=None
    ) -> None:
        self.code = code
        self.f = Fetcher(code, cache_root)
        self.meta = self.f.meta()
        self.actors = {a["id"]: a for a in self.meta["masterData"]["actors"]}
        self.abilities = {a["gameID"]: a["name"] for a in self.meta["masterData"]["abilities"]}
        ph = self.f.phases()
        # JSON object keys come back as strings once this is served from the
        # disk cache, which silently empties every phase lookup on a re-run.
        self._ph = {"defs": ph["defs"], "fights": {int(k): v for k, v in ph["fights"].items()}}

        want = encounter_id or S.ENCOUNTER_ID
        fights = [x for x in self.meta["fights"] if x["encounterID"] == want]
        if not fights:
            # Fall back to whichever encounter this report has the most pulls on.
            counts = Counter(x["encounterID"] for x in self.meta["fights"] if x["encounterID"])
            want = counts.most_common(1)[0][0]
            fights = [x for x in self.meta["fights"] if x["encounterID"] == want]
        if difficulty is not None:
            fights = [x for x in fights if x["difficulty"] == difficulty]
        else:
            common = Counter(x["difficulty"] for x in fights).most_common(1)[0][0]
            fights = [x for x in fights if x["difficulty"] == common]
        if not fights:
            raise SystemExit(f"no pulls found for encounter {want} in report {code}")

        self.encounter_id = want
        self._memo: dict = {}
        self._roster: dict | None = None
        self.fights = sorted(fights, key=lambda x: x["startTime"])
        self.difficulty = self.fights[0]["difficulty"]
        self.boss = self.fights[0]["name"]
        self.kill = next((x for x in self.fights if x["kill"]), None)

    # ---- small helpers ----

    def name(self, actor_id) -> str:
        return (self.actors.get(actor_id) or {}).get("name", "?")

    def is_player(self, actor_id) -> bool:
        return (self.actors.get(actor_id) or {}).get("type") == "Player"

    def ability(self, e: dict) -> str:
        return self.abilities.get(e.get("abilityGameID"), "")

    def stream(self, kind: str, fid: int) -> list[dict]:
        """One event stream per (kind, fight), memoised.

        The disk cache re-reads and re-parses on every call, which is fine once
        and expensive inside a per-window loop, so hold them here too.
        """
        key = (kind, fid)
        if key not in self._memo:
            self._memo[key] = getattr(self.f, kind)(fid)
        return self._memo[key]

    def owner_of(self, actor_id):
        """Pets bill to their owner, so a hunter's damage is not split in two."""
        a = self.actors.get(actor_id) or {}
        return a.get("petOwner") or actor_id

    def roster(self) -> dict[str, dict]:
        """name -> {class, spec, role} from playerDetails, for colour and labels."""
        if self._roster is not None:
            return self._roster
        out: dict[str, dict] = {}
        try:
            pd = self.f.player_details([x["id"] for x in self.fights])
        except Exception:
            pd = None
        while isinstance(pd, dict) and not any(k in pd for k in ("tanks", "healers", "dps")):
            if len(pd) != 1:
                break
            pd = next(iter(pd.values()))
        for group in ("tanks", "healers", "dps"):
            for p in (pd or {}).get(group) or []:
                specs = p.get("specs") or []
                spec = ""
                if specs and isinstance(specs[0], dict):
                    spec = max(specs, key=lambda s: s.get("count", 0)).get("spec", "")
                elif specs:
                    spec = specs[0]
                out[p.get("name", "")] = {
                    "class": p.get("type", ""),
                    "spec": spec,
                    "role": {"tanks": "Tank", "healers": "Healer"}.get(group, "DPS"),
                }
        self._roster = out
        return out

    def _rank(self, totals: Counter, extra=None) -> list[dict]:
        """Turn a name -> damage counter into rows the page can draw.

        Anything not in the roster is a guardian or unowned summon the log
        never billed to a player; it is a rounding error and it has no class to
        colour, so drop it rather than show a nameless bar.
        """
        roster = self.roster()
        totals = Counter({n: v for n, v in totals.items() if n in roster})
        grand = sum(totals.values()) or 1
        rows = []
        for name, amount in totals.most_common():
            info = roster.get(name, {})
            row = {
                "name": name,
                "class": info.get("class", ""),
                "spec": info.get("spec", ""),
                "role": info.get("role", ""),
                "damage": amount,
                "share": round(100 * amount / grand, 1),
            }
            if extra:
                row.update(extra(name, amount))
            rows.append(row)
        return rows

    def ids_named(self, name: str) -> set[int]:
        """Every gameID the report files under one ability name. Blizzard often
        ships a cast and its damage component as separate ids."""
        return {gid for gid, n in self.abilities.items() if n == name}

    def transitions(self, fid: int) -> list[dict]:
        return self._ph["fights"].get(fid) or []

    def phase_at(self, fid: int, ts: float) -> str:
        cur = 1
        for p in self.transitions(fid):
            if ts >= p["startTime"]:
                cur = p["id"]
        return S.PHASES.get(cur, "?")

    def phase_bounds(self, fid: int) -> dict[str, tuple[int, int]]:
        """{phase key: (start_ms, end_ms)} for one pull."""
        fight = next(x for x in self.fights if x["id"] == fid)
        tr = self.transitions(fid)
        out: dict[str, tuple[int, int]] = {}
        for i, p in enumerate(tr):
            start = p["startTime"]
            end = tr[i + 1]["startTime"] if i + 1 < len(tr) else fight["endTime"]
            out[S.PHASES.get(p["id"], "?")] = (start, end)
        return out

    def _max_hp(self, target: str, phase: str) -> float:
        """A target's max health during one phase. The serpent's changes between
        stage one and its resurrection, so it has to be read per phase."""
        for x in self.fights:
            bounds = self.phase_bounds(x["id"])
            if phase not in bounds:
                continue
            lo, hi = bounds[phase]
            for e in self.stream("done", x["id"]):
                if not (lo <= e["timestamp"] <= hi):
                    continue
                if self.name(e.get("targetID")) != target:
                    continue
                if e.get("resourceActor") == 2 and e.get("maxHitPoints"):
                    return e["maxHitPoints"]
        return 0

    def boss_health_at(self, fid: int, target: str, ts: float) -> float | None:
        """Target's health percent at a moment, read off the last damage event
        that landed on it at or before `ts`.

        These events carry `resourceActor: 2`, meaning the hit points on the
        event belong to the target rather than the caster.
        """
        best = None
        for e in self.stream("done", fid):
            if e["timestamp"] > ts:
                break
            if self.name(e.get("targetID")) != target:
                continue
            if e.get("resourceActor") != 2 or not e.get("maxHitPoints"):
                continue
            best = 100.0 * e["hitPoints"] / e["maxHitPoints"]
        return best

    def rel(self, fid: int, ts: float) -> float:
        fight = next(x for x in self.fights if x["id"] == fid)
        return (ts - fight["startTime"]) / 1000

    # ---- 1. progress ----

    def progress(self) -> list[dict]:
        """Per pull: how long each phase lasted and where it stopped."""
        rows = []
        for x in self.fights:
            bounds = self.phase_bounds(x["id"])
            rows.append(
                {
                    "pull": x["id"],
                    "kill": bool(x["kill"]),
                    "best": round(x["fightPercentage"], 2),
                    "duration": round((x["endTime"] - x["startTime"]) / 1000, 1),
                    "reached": max(bounds, key=lambda k: bounds[k][0]) if bounds else "P1",
                    "phases": {k: round((e - s) / 1000, 1) for k, (s, e) in bounds.items()},
                }
            )
        return rows

    # ---- 2. orbs ----

    def orbs(self) -> dict:
        """Carry duty, and how many orbs went off in each frontal.

        The carry debuff is a flat timer; the detonation is the frontal, and it
        stamps one stack of the burst DoT on the raid per orb caught in it. So
        the peak stack applied on a cleave *is* the orb count for that cleave.
        """
        carries: dict[str, Counter] = {p: Counter() for p in S.ORB_PHASES}
        cleaves: list[dict] = []
        carry_secs: list[float] = []
        pulse_total = 0.0
        burst_total = 0.0

        for x in self.fights:
            fid = x["id"]
            deb = sorted(self.f.debuffs(fid), key=lambda e: e["timestamp"])
            casts = self.f.enemy_casts(fid)

            open_at: dict[int, int] = {}
            for e in deb:
                if self.ability(e) != S.ORB_CARRY:
                    continue
                tid = e.get("targetID")
                if not self.is_player(tid):
                    continue
                if e["type"] == "applydebuff":
                    open_at[tid] = e["timestamp"]
                    ph = self.phase_at(fid, e["timestamp"])
                    if ph in carries:
                        carries[ph][self.name(tid)] += 1
                elif e["type"] == "removedebuff" and tid in open_at:
                    carry_secs.append((e["timestamp"] - open_at.pop(tid)) / 1000)

            bursts = [
                e
                for e in deb
                if self.ability(e) == S.ORB_BURST and e["type"] in ("applydebuff", "applydebuffstack")
            ]
            frontals = sorted(
                e["timestamp"] for e in casts if self.ability(e) in S.CLEAVE and e["type"] == "cast"
            )
            for ts in frontals:
                # Stacks land on the cast itself; take the peak inside a short window.
                peak = (
                    max((e.get("stack") or 1) for e in bursts if 0 <= e["timestamp"] - ts <= 1500)
                    if any(0 <= e["timestamp"] - ts <= 1500 for e in bursts)
                    else 0
                )
                cleaves.append(
                    {
                        "pull": fid,
                        "t": round(self.rel(fid, ts), 1),
                        "phase": self.phase_at(fid, ts),
                        "orbs": peak,
                    }
                )

            for e in self.f.taken(fid):
                a = self.ability(e)
                if a == S.ORB_PULSE:
                    pulse_total += _amount(e)
                elif a == S.ORB_BURST:
                    burst_total += _amount(e)

        per_carrier = Counter()
        for ph in carries:
            per_carrier.update(carries[ph])
        picked = sum(per_carrier.values())
        detonated = sum(c["orbs"] for c in cleaves)
        counts = [c["orbs"] for c in cleaves]

        return {
            "cleaves": cleaves,
            "carriers": [
                {
                    "name": n,
                    "p1": carries.get("P1", Counter())[n],
                    "p3": carries.get("P3", Counter())[n],
                    "total": t,
                    "share": round(100 * t / picked, 1) if picked else 0,
                }
                for n, t in per_carrier.most_common()
            ],
            "picked": picked,
            "detonated": detonated,
            "carry_seconds": round(statistics.median(carry_secs), 1) if carry_secs else 0,
            "cleave_count": len(cleaves),
            "dry_cleaves": sum(1 for c in cleaves if c["orbs"] == 0),
            "median_per_cleave": int(statistics.median(counts)) if counts else 0,
            "max_per_cleave": max(counts) if counts else 0,
            "distinct_carriers": len(per_carrier),
            "pulse_damage": pulse_total,
            "burst_damage": burst_total,
        }

    # ---- 3. the veil gate ----

    def veil(self) -> dict:
        """Every shield channel: how long it took to break, or what it cost."""
        channels = []
        shield_values = []
        nightfall_ids = self.ids_named(S.NIGHTFALL)
        per_player: Counter = Counter()
        appearances: Counter = Counter()
        by_pull: dict[int, Counter] = defaultdict(Counter)
        windows_by_pull: Counter = Counter()
        for x in self.fights:
            fid = x["id"]
            buffs = self.stream("enemy_buffs", fid)
            casts = self.stream("enemy_casts", fid)
            done = self.stream("done", fid)
            taken = self.stream("taken", fid)
            deaths = [d for d in self.stream("deaths", fid) if self.is_player(d.get("targetID"))]

            starts = sorted(
                {e["timestamp"] for e in buffs if self.ability(e) == S.VEIL and e["type"] == "applybuff"}
            )
            ends = sorted(
                {e["timestamp"] for e in buffs if self.ability(e) == S.VEIL and e["type"] == "removebuff"}
            )
            resolved_at = [
                e["timestamp"] for e in casts if self.ability(e) == S.NIGHTFALL and e["type"] == "cast"
            ]

            for s in starts:
                end = min((t for t in ends if t >= s), default=None)
                window_end = end if end else s + S.NIGHTFALL_WINDOW_SEC * 1000
                resolved = any(s <= t <= window_end + 1500 for t in resolved_at)
                absorbed = 0.0
                seen: set[str] = set()
                for e in done:
                    if self.name(e.get("targetID")) != S.USURPER:
                        continue
                    if not (s <= e["timestamp"] <= window_end):
                        continue
                    absorbed += e.get("absorbed") or 0
                    # Everything landing on the shield counts towards breaking
                    # it, absorbed or not, so credit the whole hit.
                    who = self.name(self.owner_of(e.get("sourceID")))
                    if who != "?":
                        per_player[who] += _amount(e)
                        by_pull[fid][who] += _amount(e)
                        seen.add(who)
                for who in seen:
                    appearances[who] += 1
                windows_by_pull[fid] += 1
                cost = sum(
                    _amount(e)
                    for e in taken
                    if self.ability(e) == S.NIGHTFALL and s <= e["timestamp"] <= s + 20000
                )
                # Attribute by killing blow rather than by "died near the
                # channel". Plenty of other things kill people in that window.
                died = sum(
                    1
                    for d in deaths
                    if (d.get("killingAbilityGameID") or 0) in nightfall_ids
                    and s <= d["timestamp"] <= s + 20000
                )
                if not resolved and absorbed:
                    shield_values.append(absorbed)
                channels.append(
                    {
                        "pull": fid,
                        "t": round(self.rel(fid, s), 1),
                        "phase": self.phase_at(fid, s),
                        "break_seconds": round((window_end - s) / 1000, 1),
                        "resolved": resolved,
                        "absorbed": absorbed,
                        "raid_damage": cost,
                        "deaths": died,
                    }
                )
        broken = [c for c in channels if not c["resolved"]]
        resolved = [c for c in channels if c["resolved"]]
        times = sorted(c["break_seconds"] for c in broken)
        players = self._rank(
            per_player,
            lambda n, a: {
                "windows": appearances[n],
                "per_window": round(a / appearances[n]) if appearances[n] else 0,
                "by_pull": {str(p): round(c[n]) for p, c in by_pull.items() if c[n]},
            },
        )
        return {
            "channels": channels,
            "players": players,
            "windows_by_pull": {str(p): n for p, n in windows_by_pull.items()},
            "total": len(channels),
            "broken": len(broken),
            "resolved": len(resolved),
            "deaths": sum(c["deaths"] for c in resolved),
            "shield": int(statistics.median(shield_values)) if shield_values else 0,
            "median_break": round(statistics.median(times), 1) if times else 0,
            "fastest_break": times[0] if times else 0,
        }

    # ---- 4. the burn window ----

    # Stage two ends on a fixed damage threshold into Malacrass, not on a clock:
    # the damage dealt by the handover is identical to three significant figures
    # in every pull. So the handover time is purely a choice about stage two
    # damage. Push with cooldowns and cross early, or hold and cross late with
    # the cooldowns still banked for the burn window. The constant below is only
    # the reporting line between the two, not a mechanic.
    EARLY_TRANSITION_SEC = 250.0

    def burn(self) -> dict:
        """The intermission: serpent takes double, usurper hides behind 99%."""
        rows = []
        per_player: Counter = Counter()
        per_player_p1: Counter = Counter()
        by_pull: dict[int, Counter] = defaultdict(Counter)
        by_pull_p1: dict[int, Counter] = defaultdict(Counter)
        pull_seconds: dict[int, tuple[float, float]] = {}
        int_seconds = 0.0
        p1_seconds = 0.0
        for x in self.fights:
            fid = x["id"]
            bounds = self.phase_bounds(fid)
            if "INT" not in bounds or "P1" not in bounds:
                continue
            done = self.stream("done", fid)

            # Per-player damage into the serpent, in the burn window and in
            # stage one, so the page can show who actually lifts when it counts.
            for e in done:
                if self.name(e.get("targetID")) != S.SERPENT:
                    continue
                who = self.name(self.owner_of(e.get("sourceID")))
                if who == "?":
                    continue
                ts = e["timestamp"]
                if bounds["INT"][0] <= ts <= bounds["INT"][1]:
                    per_player[who] += _amount(e)
                    by_pull[fid][who] += _amount(e)
                elif bounds["P1"][0] <= ts <= bounds["P1"][1]:
                    per_player_p1[who] += _amount(e)
                    by_pull_p1[fid][who] += _amount(e)
            isec = (bounds["INT"][1] - bounds["INT"][0]) / 1000
            psec = (bounds["P1"][1] - bounds["P1"][0]) / 1000
            pull_seconds[fid] = (isec, psec)
            int_seconds += isec
            p1_seconds += psec

            def rate(target: str, span) -> float:
                s, e = span
                secs = max((e - s) / 1000, 1)
                return (
                    sum(
                        _amount(ev)
                        for ev in done
                        if self.name(ev.get("targetID")) == target and s <= ev["timestamp"] <= e
                    )
                    / secs
                )

            base = rate(S.SERPENT, bounds["P1"])
            during = rate(S.SERPENT, bounds["INT"])
            s, e2 = bounds["INT"]
            e = e2
            usurper = sum(
                _amount(ev)
                for ev in done
                if self.name(ev.get("targetID")) == S.USURPER and s <= ev["timestamp"] <= e
            )
            serpent = sum(
                _amount(ev)
                for ev in done
                if self.name(ev.get("targetID")) == S.SERPENT and s <= ev["timestamp"] <= e
            )

            lust_at = None
            for ev in self.f.player_casts(fid):
                if self.ability(ev) in S.LUST and ev["type"] == "cast":
                    off = (ev["timestamp"] - s) / 1000
                    if lust_at is None or abs(off) < abs(lust_at):
                        lust_at = round(off, 1)

            # One raid-wide blast per ghost the raid body-blocked.
            volley: Counter = Counter()
            blast_damage = 0.0
            for ev in self.stream("taken", fid):
                if self.ability(ev) != S.INT_AURA:
                    continue
                if not (s - 2000 <= ev["timestamp"] <= e2 + 2000):
                    continue
                volley[round(ev["timestamp"] / 100)] += 1
                blast_damage += _amount(ev)
            blocked = sum(1 for _, n in volley.items() if n >= S.GHOST_BLAST_MIN_TARGETS)
            reclaims = [
                e
                for e in self.stream("enemy_heals", fid)
                if self.ability(e) == S.RECLAIM
                and self.name(e.get("targetID")) == S.SERPENT
                and s - 2000 <= e["timestamp"] <= e2 + 2000
            ]
            transition = (s - x["startTime"]) / 1000
            p2s, p2e = bounds["P2"]
            gate = sum(
                _amount(ev)
                for ev in done
                if self.name(ev.get("targetID")) == S.USURPER and p2s <= ev["timestamp"] <= p2e
            )
            p2_secs = max((p2e - p2s) / 1000, 1)
            rows.append(
                {
                    "pull": fid,
                    "kill": bool(x["kill"]),
                    "best": round(x["fightPercentage"], 2),
                    "base_dps": base,
                    "burn_dps": during,
                    "ratio": round(during / base, 2) if base else 0,
                    "shielded_share": round(usurper / serpent, 4) if serpent else 0,
                    "lust_offset": lust_at,
                    "seconds": round((e - s) / 1000, 1),
                    # When stage two handed over. The gate is a damage threshold, so
                    # this time is a choice: push with cooldowns and cross early, or
                    # hold damage and cross late with the cooldowns still banked.
                    "transition": round(transition, 1),
                    "transition_mmss": f"{int(transition // 60)}:{int(transition % 60):02d}",
                    "band": "early" if transition < self.EARLY_TRANSITION_SEC else "late",
                    "p2_seconds": round(p2_secs, 1),
                    # The handover threshold, and the rate the raid met it at.
                    "gate_damage": round(gate),
                    "p2_dps": round(gate / p2_secs),
                    # What the burn window actually achieved: the serpent's health
                    # when the intermission handed over to stage three.
                    "serpent_hp_end": self.boss_health_at(fid, S.SERPENT, e),
                    "serpent_hp_start": self.boss_health_at(fid, S.SERPENT, s),
                    "reclaims": len(reclaims),
                    "reclaimed": sum(ev.get("amount") or 0 for ev in reclaims),
                    "blocked": blocked,
                    "ghosts": blocked + len(reclaims),
                    "blast_damage": blast_damage,
                }
            )

        # How long the serpent actually heals, and for how much. Measured from
        # the heal events themselves rather than the buff, which lingers past
        # the last tick and overstates the window.
        heal_rate, heal_seconds, heal_total = 0.0, 0.0, 0.0
        if self.kill:
            fid = self.kill["id"]
            heals = [
                e
                for e in self.stream("enemy_heals", fid)
                if self.ability(e) == S.REGEN and e["type"] == "heal"
            ]
            if heals:
                heal_rate = statistics.median(e.get("amount") or 0 for e in heals)
                heal_seconds = round(
                    (max(e["timestamp"] for e in heals) - min(e["timestamp"] for e in heals)) / 1000, 1
                )
                heal_total = sum(e.get("amount") or 0 for e in heals)

        ratios = [r["ratio"] for r in rows if r["ratio"]]
        offsets = [r["lust_offset"] for r in rows if r["lust_offset"] is not None]

        def _burn_extra(name: str, amount: float) -> dict:
            burn_dps = amount / int_seconds if int_seconds else 0
            base_dps = per_player_p1[name] / p1_seconds if p1_seconds else 0
            per_pull = {}
            for fid, counter in by_pull.items():
                if not counter[name]:
                    continue
                isec, psec = pull_seconds.get(fid, (0, 0))
                pdps = counter[name] / isec if isec else 0
                pbase = by_pull_p1[fid][name] / psec if psec else 0
                per_pull[str(fid)] = {
                    "damage": round(counter[name]),
                    "dps": round(pdps),
                    "multiple": round(pdps / pbase, 2) if pbase else 0,
                }
            return {
                "dps": burn_dps,
                "base_dps": base_dps,
                "multiple": round(burn_dps / base_dps, 2) if base_dps else 0,
                "by_pull": per_pull,
            }

        bands = {b: [r for r in rows if r["band"] == b] for b in ("early", "late")}
        return {
            "rows": rows,
            "players": self._rank(per_player, _burn_extra),
            "int_seconds": round(int_seconds, 1),
            "split_at": self.EARLY_TRANSITION_SEC,
            "bands": {
                b: {
                    "pulls": [r["pull"] for r in g],
                    "count": len(g),
                    "median_transition": (statistics.median(r["transition"] for r in g) if g else 0),
                    "median_ratio": (statistics.median(r["ratio"] for r in g) if g else 0),
                    "median_p2_dps": (statistics.median(r["p2_dps"] for r in g) if g else 0),
                    "best": (min((r["best"] for r in g), default=0)),
                    "kills": sum(1 for r in g if r["kill"]),
                }
                for b, g in bands.items()
            },
            # The serpent fights stage one on one health pool and comes back
            # in the intermission on a much larger one.
            "pool_one": self._max_hp(S.SERPENT, "P1"),
            "pool_three": self._max_hp(S.SERPENT, "P3"),
            # Identical in every pull, which is what proves the handover is a
            # damage threshold rather than a clock.
            "gate_damage": (statistics.median(r["gate_damage"] for r in rows) if rows else 0),
            "blocked_total": sum(r["blocked"] for r in rows),
            "ghosts_median": (
                statistics.median([r["ghosts"] for r in rows if r["ghosts"] > 20])
                if any(r["ghosts"] > 20 for r in rows)
                else 0
            ),
            "blast_each": (
                statistics.median([r["blast_damage"] / r["blocked"] for r in rows if r["blocked"]])
                if rows
                else 0
            ),
            "reclaim_total": sum(r["reclaims"] for r in rows),
            "reclaim_healed": sum(r["reclaimed"] for r in rows),
            "reclaim_each": (
                statistics.median([r["reclaimed"] / r["reclaims"] for r in rows if r["reclaims"]])
                if rows
                else 0
            ),
            "gate_spread": (
                round(max(r["gate_damage"] for r in rows) / min(r["gate_damage"] for r in rows), 3)
                if rows
                else 0
            ),
            "median_ratio": round(statistics.median(ratios), 2) if ratios else 0,
            "best": max(rows, key=lambda r: r["ratio"]) if rows else None,
            "heal_rate": heal_rate,
            "heal_seconds": heal_seconds,
            "heal_total": heal_total,
            "lust_window": (min(offsets), max(offsets)) if offsets else None,
            "lust_late": sum(1 for o in offsets if o >= 0),
            "lust_count": len(offsets),
        }

    # ---- 5. the edge ----

    # Going off the platform logs with no killing ability and no killer. So do
    # two other things: the wipe reset despawning the raid, and players jumping
    # deliberately to reset a lost pull. Both arrive once the pull is already
    # gone, so the test is how much of the raid was dead at that moment rather
    # than how close to the end it was. A knockback death is a real failure
    # even if the raid wipes ninety seconds later.
    RESET_DEAD_SHARE = 0.5
    # A death in the last seconds of a wipe is part of the collapse whatever was
    # on the victim at the time, and the dead-share test alone is a knife edge in
    # the middle of one: on this log two people died a millisecond apart either
    # side of it. So a fall also counts as collapse if the pull ended within this
    # long afterwards. Ten seconds is deliberate: it clears the collapse noise
    # without touching a single knockback or ghost-catch death, while fifteen
    # starts eating real knockback deaths, which land ninety-odd seconds before
    # the end of a pull. The kill is exempt, since it "ends" by winning.
    # The knockback fires when Malacrass reaches zero, which is exactly the
    # logged stage-two handover. Deaths cluster hard at +4s; this band holds the
    # spike without reaching into unrelated falls either side of it.
    COLLAPSE_TAIL_SEC = 10.0
    KNOCKBACK_BAND = (2.0, 8.0)
    # A possession counts as the cause if it was up at the moment of death, or
    # broke within this long before it: the shield coming down does not save
    # somebody who is already over the edge, and the log has clear cases of a
    # possession broken four or five seconds before the victim still landed.
    # The bucket counts are flat from 5s to 10s, so this is not sitting on a
    # slope, and widening it further changes nothing.
    CONTROL_GRACE_MS = 5000

    def edge(self) -> dict:
        """Deaths off the platform, split by what put people there.

        Falls that happen while the pull is still viable are the ones that cost
        anything; falls taken once `RESET_DEAD_SHARE` of the raid is already
        down are reset jumps and collapse, and are reported separately rather
        than folded into the headline.
        """
        buckets = Counter()
        per_pull = Counter()
        victims = Counter()
        rows = []
        total_deaths = 0
        reset_falls = 0
        reset_causes = Counter()
        knockback_offsets = []

        for x in self.fights:
            fid = x["id"]
            bounds = self.phase_bounds(fid)
            int_start = bounds["INT"][0] if "INT" in bounds else None
            deb = sorted(self.stream("debuffs", fid), key=lambda e: e["timestamp"])
            sources = self.march_sources(fid)
            deaths = sorted(
                (d for d in self.stream("deaths", fid) if self.is_player(d.get("targetID"))),
                key=lambda d: d["timestamp"],
            )
            # Raid size for this pull, from whoever actually took a hit in it.
            present = {
                e.get("targetID") for e in self.stream("taken", fid) if self.is_player(e.get("targetID"))
            }
            size = max(len(present), 1)

            for i, d in enumerate(deaths):
                tid = d.get("targetID")
                total_deaths += 1
                if (d.get("killingAbilityGameID") or 0) != 0:
                    continue
                ts = d["timestamp"]
                already = sum(1 for e in deaths if e["timestamp"] < ts)
                dying = not x["kill"] and (x["endTime"] - ts) / 1000 <= self.COLLAPSE_TAIL_SEC
                lost = already >= self.RESET_DEAD_SHARE * size or dying
                control = self._control_at(deb, tid, ts, sources)
                offset = (ts - int_start) / 1000 if int_start else None
                lo, hi = self.KNOCKBACK_BAND
                if offset is not None and lo <= offset <= hi:
                    cause = "knockback"
                elif f"{S.MARCH}:touch" in control:
                    cause = "caught"
                elif f"{S.MARCH}:cast" in control or f"{S.MARCH}:unknown" in control:
                    cause = "march"
                else:
                    # A ghost merely chasing somebody has no way to push them
                    # off; only the possession does. A fixation with no
                    # possession behind it is a coincidence.
                    cause = "unexplained"
                if lost:
                    reset_falls += 1
                    reset_causes["reset or collapse" if cause == "unexplained" else cause] += 1
                    continue
                if cause == "knockback":
                    knockback_offsets.append(round(offset, 1))
                buckets[cause] += 1
                per_pull[fid] += 1
                victims[self.name(tid)] += 1
                rows.append(
                    {
                        "pull": fid,
                        "t": round(self.rel(fid, ts), 1),
                        "who": self.name(tid),
                        "phase": self.phase_at(fid, ts),
                        "cause": cause,
                    }
                )

        falls = sum(buckets.values())
        counted = total_deaths - reset_falls
        return {
            "rows": rows,
            "buckets": dict(buckets),
            "falls": falls,
            "total_deaths": total_deaths,
            "reset_falls": reset_falls,
            "reset_causes": dict(reset_causes),
            "counted_deaths": counted,
            "share": round(100 * falls / counted, 1) if counted else 0,
            "per_pull": dict(per_pull),
            "worst_pull": per_pull.most_common(1)[0] if per_pull else (0, 0),
            "victims": victims.most_common(8),
            "knockback_at": round(statistics.median(knockback_offsets), 1) if knockback_offsets else 0,
        }

    def march_sources(self, fid: int) -> dict[tuple[int, int], str]:
        """(target, timestamp) -> "cast" or "touch" for every Dreadmarch applied.

        Malacrass's cast lands on several people at once and is unavoidable; a
        ghost catching somebody applies the same debuff to one person as their
        fixation ends. They read identically in the debuff stream, so the source
        has to be reconstructed from what happened around them.
        """
        key = ("march_src", fid)
        if key in self._memo:
            return self._memo[key]
        deb = self.stream("debuffs", fid)
        casts = [
            e["timestamp"]
            for e in self.stream("enemy_casts", fid)
            if self.ability(e) == S.MARCH and e["type"] == "cast"
        ]
        released: dict[int, list[int]] = defaultdict(list)
        for e in deb:
            if self.ability(e) == S.FIXATE and e["type"] == "removedebuff":
                released[e.get("targetID")].append(e["timestamp"])
        out: dict[tuple[int, int], str] = {}
        for e in deb:
            if self.ability(e) != S.MARCH or e["type"] != "applydebuff":
                continue
            ts, tid = e["timestamp"], e.get("targetID")
            if any(0 <= ts - c <= S.MARCH_CAST_GRACE_MS for c in casts):
                out[(tid, ts)] = "cast"
            elif any(abs(ts - r) <= S.MARCH_TOUCH_GRACE_MS for r in released.get(tid, [])):
                out[(tid, ts)] = "touch"
            else:
                out[(tid, ts)] = "unknown"
        self._memo[key] = out
        return out

    def _control_at(self, deb: list[dict], tid: int, ts: float, sources: dict | None = None) -> set[str]:
        """Which mind control was on this player when they died.

        A control counts if it was active at the moment of death, or dropped
        within `CONTROL_GRACE_MS` of it. Dreadmarch usually logs its removal on
        the death itself, so the grace only catches the handful that do not.
        Dreadmarch resolves to its source, since the two mean different things.
        """
        out: set[str] = set()
        for name in (S.MARCH, S.FIXATE):
            active = False
            origin = "cast"
            for e in deb:
                if e["timestamp"] > ts:
                    break
                if e.get("targetID") != tid or self.ability(e) != name:
                    continue
                if e["type"] in ("applydebuff", "refreshdebuff", "applydebuffstack"):
                    active = True
                    if name == S.MARCH and e["type"] == "applydebuff" and sources:
                        origin = sources.get((tid, e["timestamp"]), "cast")
                elif e["type"] == "removedebuff":
                    active = ts - e["timestamp"] <= self.CONTROL_GRACE_MS
            if active:
                out.add(f"{name}:{origin}" if name == S.MARCH else name)
        return out

    def _debuffs_at(self, deb: list[dict], tid: int, ts: float) -> set[str]:
        """Boss debuffs active on one player at one moment."""
        active: set[str] = set()
        for e in deb:
            if e["timestamp"] > ts:
                break
            if e.get("targetID") != tid or self.is_player(e.get("sourceID")):
                continue
            a = self.ability(e)
            if e["type"] in ("applydebuff", "refreshdebuff", "applydebuffstack"):
                active.add(a)
            elif e["type"] == "removedebuff":
                active.discard(a)
        return active

    # ---- 6. mind control ----

    # A spawn wave fixates this many targets within the cluster window;
    # anything smaller is the ghost re-picking between waves.
    FIXATE_WAVE_MIN = 5
    FIXATE_CLUSTER_MS = 3000

    def mind_control(self) -> dict:
        """The two sources, and what the raid did about them."""
        march_casts = 0
        march_origin: Counter = Counter()
        caught_died = 0
        caught_fell = 0
        batches: list[tuple[int, int]] = []
        spawn_ratio: list[float] = []
        spawn_lag: list[float] = []
        break_attempts: list[float] = []
        breakers_shield: Counter = Counter()
        march_targets: Counter = Counter()
        march_secs = []
        fixate_waves = []
        fixate_apps = 0
        fixate_kind: Counter = Counter()
        fixate_after_death: Counter = Counter()
        offwave_gap: list[float] = []
        offwave_phase: Counter = Counter()
        cc_targeted = Counter()
        cc_ground = Counter()
        break_damage = Counter()
        broken_players = set()

        for x in self.fights:
            fid = x["id"]
            deb = sorted(self.f.debuffs(fid), key=lambda e: e["timestamp"])
            casts = self.f.enemy_casts(fid)

            sources = self.march_sources(fid)
            for origin in sources.values():
                march_origin[origin] += 1
            for e in casts:
                if self.ability(e) == S.MARCH and e["type"] == "cast":
                    march_casts += 1
                    hit = sum(
                        1
                        for d in deb
                        if self.ability(d) == S.MARCH
                        and d["type"] == "applydebuff"
                        and 0 <= d["timestamp"] - e["timestamp"] <= 2000
                    )
                    if hit:
                        march_targets[hit] += 1

            open_at: dict[int, int] = {}
            for e in deb:
                a = self.ability(e)
                if a == S.MARCH:
                    tid = e.get("targetID")
                    if e["type"] == "applydebuff":
                        open_at[tid] = e["timestamp"]
                    elif e["type"] == "removedebuff" and tid in open_at:
                        march_secs.append((e["timestamp"] - open_at.pop(tid)) / 1000)

            # Fixations arrive either in a spawn wave (many at once) or singly
            # between waves. The off-wave ones are the ghost picking a new
            # target, so they are counted apart and tested against deaths.
            app_ev = sorted(
                (e for e in deb if self.ability(e) == S.FIXATE and e["type"] == "applydebuff"),
                key=lambda e: e["timestamp"],
            )
            fixate_apps += len(app_ev)
            deaths = sorted(
                (d["timestamp"] for d in self.stream("deaths", fid) if self.is_player(d.get("targetID")))
            )
            clusters: list[list[dict]] = []
            cluster: list[dict] = []
            for e in app_ev:
                if cluster and e["timestamp"] - cluster[-1]["timestamp"] <= self.FIXATE_CLUSTER_MS:
                    cluster.append(e)
                else:
                    if cluster:
                        clusters.append(cluster)
                    cluster = [e]
            if cluster:
                clusters.append(cluster)
            wave_starts = [c[0]["timestamp"] for c in clusters if len(c) >= self.FIXATE_WAVE_MIN]
            for c in clusters:
                wave = len(c) >= self.FIXATE_WAVE_MIN
                if wave:
                    fixate_waves.append(len(c))
                for e in c:
                    ts = e["timestamp"]
                    after_death = any(0 <= ts - t <= 6000 for t in deaths)
                    key = "wave" if wave else "offwave"
                    fixate_kind[key] += 1
                    if after_death:
                        fixate_after_death[key] += 1
                    if not wave:
                        prev = [t for t in wave_starts if t <= ts]
                        if prev:
                            offwave_gap.append((ts - max(prev)) / 1000)
                        offwave_phase[self.phase_at(fid, ts)] += 1

            for e in self.stream("player_casts", fid):
                if e["type"] != "cast":
                    continue
                a = self.ability(e)
                if (
                    a in S.CC_TARGETED
                    and self.is_player(e.get("targetID"))
                    and e.get("targetID") != e.get("sourceID")
                ):
                    cc_targeted[a] += 1
                elif a in S.CC_GROUND:
                    cc_ground[a] += 1

            # Two ghosts emerge from each possessed player when Dreadmarch ends,
            # so a catch feeds the next one. Removals that expire together are
            # one batch (a Malacrass cast drops off as a group).
            rem = sorted(
                e["timestamp"] for e in deb if self.ability(e) == S.MARCH and e["type"] == "removedebuff"
            )
            fixes = sorted(
                e["timestamp"] for e in deb if self.ability(e) == S.FIXATE and e["type"] == "applydebuff"
            )
            batch: list[int] = []
            for t in rem:
                if batch and t - batch[-1] <= 1500:
                    batch.append(t)
                else:
                    if batch:
                        batches.append((len(batch), batch[-1]))
                    batch = [t]
            if batch:
                batches.append((len(batch), batch[-1]))
            # Count the ghosts that appear in the 8s after each batch ended.
            for size, end in batches:
                if not any(abs(end - t) < 1 for t in rem):
                    continue
                born = sum(1 for f in fixes if 0 <= f - end <= 8000)
                if born:
                    spawn_ratio.append(born / size)
                    spawn_lag.extend((f - end) / 1000 for f in fixes if 0 <= f - end <= 8000)

            # How far the possession shield was chewed down. Damage that the
            # shield eats produces no damage event at all; it logs as an
            # `absorbed` record in the healing stream, so the depletion has to
            # be read from there, and the contributors from `attackerID`.
            windows: dict[int, list[tuple[int, int]]] = defaultdict(list)
            open_m: dict[int, int] = {}
            for e in deb:
                if self.ability(e) != S.MARCH:
                    continue
                tid2 = e.get("targetID")
                if e["type"] == "applydebuff":
                    open_m[tid2] = e["timestamp"]
                elif e["type"] == "removedebuff" and tid2 in open_m:
                    windows[tid2].append((open_m.pop(tid2), e["timestamp"]))
            acc: dict[tuple, float] = defaultdict(float)
            for e in self.stream("heals", fid):
                if self.ability(e) != S.MARCH or e["type"] != "absorbed":
                    continue
                tgt2 = e.get("targetID")
                attacker = e.get("attackerID")
                # The boss that applied the shield also shows up as an attacker
                # on a handful of possessions, double-counting the whole shield.
                # Only the raid can actually break it, so only the raid counts.
                owner = self.owner_of(attacker)
                if not self.is_player(owner):
                    continue
                for s0, e0 in windows.get(tgt2, []):
                    if s0 <= e["timestamp"] <= e0 + 500:
                        acc[(tgt2, s0)] += e.get("amount") or 0
                        breakers_shield[self.name(owner)] += e.get("amount") or 0
            break_attempts.extend(acc.values())

            # Did being caught by a ghost kill them?
            pdeaths = [d for d in self.stream("deaths", fid) if self.is_player(d.get("targetID"))]
            for (tid, applied), origin in sources.items():
                if origin != "touch":
                    continue
                after = [
                    d for d in pdeaths if d.get("targetID") == tid and 0 <= d["timestamp"] - applied <= 30000
                ]
                if after:
                    caught_died += 1
                    if (after[0].get("killingAbilityGameID") or 0) == 0:
                        caught_fell += 1

            for e in self.stream("taken", fid):
                src, tgt = e.get("sourceID"), e.get("targetID")
                if not (self.is_player(src) and self.is_player(tgt) and src != tgt):
                    continue
                if self.ability(e) in S.NOT_A_BREAK:
                    continue
                break_damage[self.name(src)] += _amount(e)
                broken_players.add(self.name(tgt))

        # A cast late in a dying pull can only reach whoever is still standing,
        # so a target count seen exactly once is an artefact of the raid being
        # dead, not the spell's real fan-out. Ignore the singletons.
        typical = [n for n, seen in march_targets.items() if seen > 1] or list(march_targets)
        return {
            "march_casts": march_casts,
            "march_from_cast": march_origin["cast"],
            "caught_by_ghost": march_origin["touch"],
            "march_unknown": march_origin["unknown"],
            "caught_died": caught_died,
            "caught_fell": caught_fell,
            "spawn_ratio": round(statistics.median(spawn_ratio), 1) if spawn_ratio else 0,
            "spawn_lag": round(statistics.median(spawn_lag), 1) if spawn_lag else 0,
            "possessions_measured": len(break_attempts),
            "breaks_completed": sum(1 for v in break_attempts if v >= S.MARCH_ABSORB * 0.98),
            "break_median": (statistics.median(break_attempts) if break_attempts else 0),
            "shield_breakers": breakers_shield.most_common(12),
            "march_per_cast": (min(typical), max(typical)) if typical else (0, 0),
            "march_spread": dict(sorted(march_targets.items())),
            "march_seconds": round(statistics.median(march_secs), 1) if march_secs else 0,
            "fixate_apps": fixate_apps,
            "fixate_waves": len(fixate_waves),
            "fixate_wave_size": int(statistics.median(fixate_waves)) if fixate_waves else 0,
            "fixate_offwave": fixate_kind["offwave"],
            "fixate_in_wave": fixate_kind["wave"],
            "offwave_gap": round(statistics.median(offwave_gap)) if offwave_gap else 0,
            "offwave_phases": dict(offwave_phase),
            # Share of each kind that lands within 6s of somebody dying. The
            # off-wave rate running well above the in-wave rate is the only
            # evidence in the log that the ghost re-picks when its target dies.
            "offwave_after_death": (
                round(100 * fixate_after_death["offwave"] / fixate_kind["offwave"])
                if fixate_kind["offwave"]
                else 0
            ),
            "wave_after_death": (
                round(100 * fixate_after_death["wave"] / fixate_kind["wave"]) if fixate_kind["wave"] else 0
            ),
            "cc_targeted": cc_targeted.most_common(),
            "cc_ground": cc_ground.most_common(),
            "cc_targeted_total": sum(cc_targeted.values()),
            "cc_ground_total": sum(cc_ground.values()),
            "breakers": break_damage.most_common(8),
            "ever_controlled": len(broken_players),
        }

    # Gravebound damage is two populations with a gap between them: routine soul
    # pickups land around a tenth of a health bar, the punishment for leaving one
    # uncollected lands around six tenths. Anything at or above this is the
    # punishment.
    FAILURE_HIT_SHARE = 40.0

    def souls(self) -> dict:
        """Gloombomb selection, and the three souls Gravebound leaves behind.

        Malacrass bombs three players; everyone the blast damages is left
        Gravebound at three stacks, and each stack is a soul to collect. Every
        collection costs a tick of health, so the mechanic kills two ways:
        collecting while already low, or not collecting at all.
        """
        gloom_casts = 0
        selected: Counter = Counter()
        blasted: Counter = Counter()
        blast_share: list[float] = []
        applications = 0
        bound: Counter = Counter()
        pickup_share: list[float] = []
        failure_share: list[float] = []
        collected: Counter = Counter()
        deaths: list[dict] = []
        gb_ids = self.ids_named(S.TANK_STACK)

        for x in self.fights:
            fid = x["id"]
            deb = sorted(self.stream("debuffs", fid), key=lambda e: e["timestamp"])
            taken = self.stream("taken", fid)

            for e in self.stream("enemy_casts", fid):
                if self.ability(e) == S.CIRCLES and e["type"] == "cast":
                    gloom_casts += 1
            for e in deb:
                n = self.ability(e)
                if n == S.CIRCLES and e["type"] == "applydebuff":
                    selected[self.name(e.get("targetID"))] += 1
                elif n == S.TANK_STACK and e["type"] == "applydebuff":
                    applications += 1
                    bound[self.name(e.get("targetID"))] += 1
                elif n == S.TANK_STACK and e["type"] == "removedebuffstack":
                    collected[self.name(e.get("targetID"))] += 1

            for e in taken:
                n = self.ability(e)
                mx, amt = e.get("maxHitPoints") or 0, e.get("amount") or 0
                if not (mx and amt):
                    continue
                share = 100.0 * amt / mx
                if n == S.CIRCLES:
                    blasted[self.name(e.get("targetID"))] += 1
                    blast_share.append(share)
                elif n == S.TANK_STACK:
                    (failure_share if share >= self.FAILURE_HIT_SHARE else pickup_share).append(share)

            for d in self.stream("deaths", fid):
                if (d.get("killingAbilityGameID") or 0) not in gb_ids:
                    continue
                tid, ts = d.get("targetID"), d["timestamp"]
                hit = [
                    e
                    for e in taken
                    if self.ability(e) == S.TANK_STACK
                    and e.get("targetID") == tid
                    and 0 <= ts - e["timestamp"] <= 1500
                ]
                share = None
                if hit and hit[-1].get("maxHitPoints"):
                    share = 100.0 * (hit[-1].get("amount") or 0) / hit[-1]["maxHitPoints"]
                deaths.append(
                    {
                        "pull": fid,
                        "t": round(self.rel(fid, ts), 1),
                        "who": self.name(tid),
                        "share": round(share, 1) if share else None,
                        "mode": (
                            "left a soul"
                            if share and share >= self.FAILURE_HIT_SHARE
                            else "collecting while low"
                        ),
                    }
                )

        roster = self.roster()
        rows = []
        for who, n in bound.most_common():
            info = roster.get(who, {})
            rows.append(
                {
                    "name": who,
                    "class": info.get("class", ""),
                    "spec": info.get("spec", ""),
                    "role": info.get("role", ""),
                    "selected": selected[who],
                    "bound": n,
                    "collected": collected[who],
                    "deaths": sum(1 for d in deaths if d["who"] == who),
                }
            )
        return {
            "rows": rows,
            "gloom_casts": gloom_casts,
            "gloom_per_cast": round(sum(selected.values()) / gloom_casts, 1) if gloom_casts else 0,
            "gloom_selected": selected.most_common(),
            "gloom_hit_players": len(blasted),
            "blast_share": statistics.median(blast_share) if blast_share else 0,
            "applications": applications,
            "pickups": len(pickup_share),
            "pickup_share": statistics.median(pickup_share) if pickup_share else 0,
            "failures": len(failure_share),
            "failure_share": statistics.median(failure_share) if failure_share else 0,
            "deaths": deaths,
            "died_collecting": sum(1 for d in deaths if d["mode"] == "collecting while low"),
            "died_failing": sum(1 for d in deaths if d["mode"] == "left a soul"),
        }

    # ---- 7. mitigation and consumables ----

    def pressure_windows(self, fid: int) -> list[tuple[int, int]]:
        """The spans this fight actually asks you to press something for: each
        shield channel, and the whole intermission."""
        spans: list[tuple[int, int]] = []
        for e in self.stream("enemy_buffs", fid):
            if self.ability(e) == S.VEIL and e["type"] == "applybuff":
                spans.append((e["timestamp"], e["timestamp"] + int(S.NIGHTFALL_WINDOW_SEC * 1000)))
        bounds = self.phase_bounds(fid)
        if "INT" in bounds:
            spans.append(bounds["INT"])
        return sorted(spans)

    def _consumable_heals(self) -> dict:
        """(fight, player) -> [(timestamp, amount)] for stones and potions.

        WCL stamps `hitPoints` on the cast as the value *after* the heal lands,
        so the heal has to be subtracted to recover health at the moment of use.
        """
        out: dict = defaultdict(list)
        ids: set[int] = set()
        for n in S.HEALTHSTONES | S.HEALTH_POTIONS:
            ids |= self.ids_named(n)
        if not ids:
            return out
        for fid in [x["id"] for x in self.fights]:
            for e in self.stream("heals", fid):
                if e.get("type") != "heal":
                    continue
                if e.get("abilityGameID") in ids:
                    out[(fid, e.get("targetID"))].append((e["timestamp"], e.get("amount") or 0))
        return out

    def kind_of(self, ability_id, spec: str = "") -> str | None:
        n = self.abilities.get(ability_id)
        # Raid-wide is checked first: a few of these also sit in the shared
        # MAJOR set (Rallying Cry, say), and a cooldown dropped on the whole
        # raid is not a personal save whichever list it appears on.
        if n in S.RAID_WIDE:
            return "raidwide"
        if n in S.MAJOR:
            if spec and spec in S.NOT_DEFENSIVE_FOR_SPEC.get(n, ()):
                return None
            return "major"
        if n in S.MINOR:
            return "minor"
        if n in S.EXTERNAL:
            return "external"
        if n in S.HEALTHSTONES:
            return "stone"
        if n in S.HEALTH_POTIONS:
            return "potion"
        return None

    def mitigation(self) -> dict:
        """Who pressed what, and whether they pressed it when it mattered."""
        heals = self._consumable_heals()
        roster = self.roster()
        per: dict[str, dict] = defaultdict(
            lambda: {
                "major": 0,
                "major_pressure": 0,
                "minor": 0,
                "external": 0,
                "raidwide": 0,
                "stone": 0,
                "potion": 0,
                "hp_at_use": [],
                "spells": Counter(),
                "raid_spells": Counter(),
                "taken": 0.0,
                "deaths": 0,
                "pulls_with_consumable": set(),
            }
        )
        spell_use: Counter = Counter()
        windows = 0

        for x in self.fights:
            fid = x["id"]
            spans = self.pressure_windows(fid)
            windows += len(spans)

            def in_pressure(ts: float) -> bool:
                return any(s - 1000 <= ts <= e + 1000 for s, e in spans)

            for e in self.stream("player_casts", fid):
                if e.get("type") != "cast":
                    continue
                who = self.name(self.owner_of(e.get("sourceID")))
                info = roster.get(who)
                if not info or info.get("role") in S.MITIGATION_SKIP_ROLES:
                    continue
                kind = self.kind_of(e.get("abilityGameID"), info.get("spec", ""))
                if not kind:
                    continue
                name = self.ability(e)
                v = per[who]
                spell_use[name] += 1
                # An external cast on yourself is a personal cooldown, not
                # something given to anybody, so it bills as a major instead.
                if kind == "external":
                    target = self.name(self.owner_of(e.get("targetID")))
                    if target == who or not self.roster().get(target):
                        kind = "major"
                v[kind] += 1
                if kind in ("major", "external"):
                    v["spells"][name] += 1
                    if kind == "major" and in_pressure(e["timestamp"]):
                        v["major_pressure"] += 1
                elif kind == "raidwide":
                    v["raid_spells"][name] += 1
                elif kind in ("stone", "potion"):
                    v["pulls_with_consumable"].add(fid)
                    if e.get("maxHitPoints"):
                        near = [
                            (abs(t - e["timestamp"]), amt)
                            for t, amt in heals.get((fid, e.get("sourceID")), [])
                            if abs(t - e["timestamp"]) <= 1500
                        ]
                        healed = min(near)[1] if near else 0
                        before = max(0, (e.get("hitPoints") or 0) - healed)
                        v["hp_at_use"].append(100 * before / e["maxHitPoints"])

            for e in self.stream("taken", fid):
                who = self.name(e.get("targetID"))
                if who in per:
                    per[who]["taken"] += _amount(e)
            for d in self.stream("deaths", fid):
                who = self.name(d.get("targetID"))
                if who in per:
                    per[who]["deaths"] += 1

        rows = []
        for name, v in per.items():
            info = roster.get(name, {})
            hp = sorted(v["hp_at_use"])
            rows.append(
                {
                    "name": name,
                    "class": info.get("class", ""),
                    "spec": info.get("spec", ""),
                    "role": info.get("role", ""),
                    "major": v["major"],
                    "major_pressure": v["major_pressure"],
                    "minor": v["minor"],
                    "external": v["external"],
                    "raidwide": v["raidwide"],
                    "raid_spells": v["raid_spells"].most_common(3),
                    "stone": v["stone"],
                    "potion": v["potion"],
                    "consumables": v["stone"] + v["potion"],
                    "pulls_with_consumable": len(v["pulls_with_consumable"]),
                    "hp_at_use": round(statistics.median(hp), 1) if hp else None,
                    "taken": v["taken"],
                    "deaths": v["deaths"],
                    "top_spells": v["spells"].most_common(3),
                }
            )
        rows.sort(key=lambda r: -(r["major"] + r["external"]))
        return {
            "rows": rows,
            "windows": windows,
            "spells": spell_use.most_common(),
            "majors": sum(r["major"] for r in rows),
            "majors_pressure": sum(r["major_pressure"] for r in rows),
            "externals": sum(r["external"] for r in rows),
            "raidwides": sum(r["raidwide"] for r in rows),
            "stones": sum(r["stone"] for r in rows),
            "potions": sum(r["potion"] for r in rows),
            "never_consumed": [r["name"] for r in rows if r["consumables"] == 0],
            "skipped_roles": sorted(S.MITIGATION_SKIP_ROLES),
            "skipped": sorted(
                n for n, i in self.roster().items() if i.get("role") in S.MITIGATION_SKIP_ROLES
            ),
        }

    # ---- assemble ----

    def build(self) -> dict:
        progress = self.progress()
        orbs = self.orbs()
        veil = self.veil()
        burn = self.burn()
        edge = self.edge()
        mc = self.mind_control()
        mit = self.mitigation()
        souls = self.souls()

        payloads = {
            "progress": progress,
            "orbs": {"cleaves": orbs["cleaves"], "carriers": orbs["carriers"]},
            "veil": veil["channels"],
            "veil_players": veil["players"],
            "veil_windows": veil["windows_by_pull"],
            "burn": burn["rows"],
            "burn_players": burn["players"],
            "edge": {"buckets": edge["buckets"], "rows": edge["rows"], "per_pull": edge["per_pull"]},
            "control": {
                "cc_targeted": mc["cc_targeted"],
                "cc_ground": mc["cc_ground"],
                "breakers": mc["breakers"],
            },
            "mitigation": mit["rows"],
            "souls": souls["rows"],
        }
        return {
            "progress": progress,
            "orbs": orbs,
            "veil": veil,
            "burn": burn,
            "edge": edge,
            "control": mc,
            "mitigation": mit,
            "souls": souls,
            "payloads": payloads,
        }
