"""The numbers behind the Soulcoil Well report.

The whole encounter turns on one relationship: a dive lasts until the Drowned
Echo dies, leaving lasts 60 seconds of Soul Exhaustion, and Grasping Depths
comes back on its own clock. Everything here measures those three against each
other.

Reading the log:

- **A dive** is a run of Immortal Coil auras on one player. The aura ramps
  through three ids — roughly 1s, then 3s, then the sustained one that actually
  ticks — so a player who clips the edge of the well picks up the first and
  drops it without ever reaching the third. Only dives that reach the sustained
  stage count; the rest are somebody being dragged in by the pull.
- **A lockout** is a Soul Exhaustion window, applied on the way *out*.
- **An early entry** is a dive that starts inside the diver's own lockout. The
  log shows it twice over: as the overlap, and as damage taken at ~3.5x the
  unmitigated value.
- **An Echo window** is a run of Grasping Depths damage. It opens when the Echo
  wakes and closes when it dies — or when the raid does.
"""

from __future__ import annotations

import collections
import statistics
from collections.abc import Iterable

from . import spells
from .fetch import Fetcher

NEKZALI_ENCOUNTER = 3470
DIFFICULTY_NAMES = {3: "Normal", 4: "Heroic", 5: "Mythic"}


def _windows(stamps: Iterable[float], gap: float) -> list[list[float]]:
    """Cluster sorted timestamps into [start, end] runs separated by `gap`."""
    stamps = sorted(set(stamps))
    if not stamps:
        return []
    out: list[list[float]] = []
    start = prev = stamps[0]
    for t in stamps[1:]:
        if t - prev > gap:
            out.append([start, prev])
            start = t
        prev = t
    out.append([start, prev])
    return out


def _seconds_into(fight: dict, timestamp: float) -> float:
    """A log timestamp as seconds into its pull."""
    return round((timestamp - fight["startTime"]) / 1000, 1)


class Analysis:
    def __init__(self, code: str, encounter: int | None = None, difficulty: int | None = None) -> None:
        self.code = code
        self.f = Fetcher(code)
        self.report = self.f.fights()
        self.actors = self.f.actors()
        self.names = {a["id"]: a["name"] for a in self.actors}
        self.abilities = self.f.abilities()
        self._by_name: dict[str, set[int]] = collections.defaultdict(set)
        for a in self.abilities:
            if a.get("name"):
                self._by_name[a["name"]].add(a["gameID"])
        self.ability_name = {a["gameID"]: a.get("name") for a in self.abilities}

        fights = [x for x in self.report["fights"] if x.get("encounterID")]
        if encounter is None:
            counts = collections.Counter(x["encounterID"] for x in fights)
            encounter = counts.most_common(1)[0][0] if counts else NEKZALI_ENCOUNTER
        fights = [x for x in fights if x["encounterID"] == encounter]
        if difficulty is None:
            counts = collections.Counter(x["difficulty"] for x in fights)
            difficulty = counts.most_common(1)[0][0] if counts else 5
        self.encounter = encounter
        self.difficulty = difficulty
        self.pulls = sorted(
            (x for x in fights if x["difficulty"] == difficulty), key=lambda x: x["startTime"]
        )
        if not self.pulls:
            raise SystemExit(f"no encounter {encounter} difficulty {difficulty} pulls in report {code}")
        self.ids = [x["id"] for x in self.pulls]
        self.boss = self.pulls[0]["name"]

    # ---- helpers ----

    def ids_named(self, name: str) -> set[int]:
        return set(self._by_name.get(name, ()))

    def _events(
        self, key: str, data_type: str, *, name: str | None = None, hostility: str | None = None
    ) -> list[dict]:
        """Every event of a type across every pull. `name` fans out over each id
        behind that ability name and merges the results."""
        if name is None:
            return self.f.events(key, self.ids, data_type, hostility=hostility)
        out: list[dict] = []
        for aid in sorted(self.ids_named(name)):
            out += self.f.events(f"{key}_{aid}", self.ids, data_type, ability_id=aid, hostility=hostility)
        out.sort(key=lambda e: e["timestamp"])
        return out

    def _in(self, events: list[dict], fight: dict) -> list[dict]:
        return [e for e in events if fight["startTime"] <= e["timestamp"] <= fight["endTime"]]

    # ---- the well ----

    def _sustained_id(self, coil_events: list[dict], fight: dict) -> int | None:
        """Which Immortal Coil id is the stage that actually ticks: the one that
        stays on longest. Found rather than hard-coded, so a patch that re-issues
        the ids needs no change here."""
        spans: dict[int, list[float]] = collections.defaultdict(list)
        opened: dict[tuple[int, int], float] = {}
        for e in self._in(coil_events, fight):
            key = (e["targetID"], e["abilityGameID"])
            if e["type"] == "applydebuff":
                opened[key] = e["timestamp"]
            elif key in opened:
                spans[e["abilityGameID"]].append(e["timestamp"] - opened.pop(key))
        if not spans:
            return None
        return max(spans, key=lambda a: statistics.median(spans[a]))

    def dives(self, coil_events: list[dict], fight: dict) -> dict[int, list[list]]:
        """player id -> [[enter, leave, reached_sustained], ...] for one pull."""
        sustained = self._sustained_id(coil_events, fight)
        active: dict[int, set[int]] = collections.defaultdict(set)
        open_dive: dict[int, list] = {}
        trips: dict[int, list[list]] = collections.defaultdict(list)
        for e in self._in(coil_events, fight):
            tid, aid = e["targetID"], e["abilityGameID"]
            t = _seconds_into(fight, e["timestamp"])
            if e["type"] == "applydebuff":
                if not active[tid]:
                    open_dive[tid] = [t, None, False]
                active[tid].add(aid)
                if aid == sustained:
                    open_dive[tid][2] = True
            else:
                active[tid].discard(aid)
                if not active[tid] and tid in open_dive:
                    open_dive[tid][1] = t
                    trips[tid].append(open_dive.pop(tid))
        end = _seconds_into(fight, fight["endTime"])
        for tid, dive in open_dive.items():
            dive[1] = end
            trips[tid].append(dive)

        merged: dict[int, list[list]] = {}
        for tid, lst in trips.items():
            rows: list[list] = []
            for a, b, sust in sorted(lst):
                if rows and a - rows[-1][1] < spells.DIVE_MERGE_SECONDS:
                    rows[-1][1] = b
                    rows[-1][2] = rows[-1][2] or sust
                else:
                    rows.append([a, b, sust])
            merged[tid] = rows
        return merged

    def lockouts(self, se_events: list[dict], fight: dict) -> dict[int, list[list[float]]]:
        """player id -> [[applied, expired], ...]. Soul Exhaustion lands on the
        way out of the well, so these start where a dive ends."""
        end = _seconds_into(fight, fight["endTime"])
        out: dict[int, list[list[float]]] = collections.defaultdict(list)
        opened: dict[int, float] = {}
        for e in self._in(se_events, fight):
            tid = e["targetID"]
            t = _seconds_into(fight, e["timestamp"])
            if e["type"] == "applydebuff":
                opened[tid] = t
            elif tid in opened:
                out[tid].append([opened.pop(tid), t])
        for tid, t in opened.items():
            out[tid].append([t, end])
        return dict(out)

    # ---- the whole night ----

    def build(self, matched_window: float | None = None) -> dict:
        coil = self._events("coil", "Debuffs", name=spells.IMMORTAL_COIL)
        se = self._events("exhaustion", "Debuffs", name=spells.SOUL_EXHAUSTION)
        gd = self._events("grasping", "DamageTaken", name=spells.GRASPING_DEPTHS)
        coil_dmg = self._events("coil_dmg", "DamageTaken", name=spells.IMMORTAL_COIL)
        well_dmg = self._events("well_dmg", "DamageTaken", name=spells.SOULCOIL_WELL)
        deaths = self._events("deaths", "Deaths", hostility="Friendlies")
        enemy_deaths = self._events("enemy_deaths", "Deaths", hostility="Enemies")
        ritual = self._events("ritual", "Casts", name=spells.RITUAL_OF_AWAKENING, hostility="Enemies")
        curse = self._events("curse", "Casts", name=spells.SOULCOILERS_CURSE, hostility="Enemies")
        lust: list[dict] = []
        for n in spells.LUST:
            if self.ids_named(n):
                lust += self._events(f"lust_{n.replace(' ', '_')}", "Buffs", name=n, hostility="Friendlies")

        pulls = [
            self._pull(i, fight, coil, se, gd, coil_dmg, well_dmg, deaths, enemy_deaths, ritual, curse, lust)
            for i, fight in enumerate(self.pulls, 1)
        ]

        deepest = min(pulls, key=lambda p: p["boss_pct"] if p["boss_pct"] is not None else 100)
        phases = {}
        if deepest["ritual"] and deepest["stage_two"]:
            phases = {
                "one": self.phase_damage(deepest, 0, deepest["ritual"]),
                "ritual": self.phase_damage(deepest, deepest["ritual"], deepest["stage_two"]),
                "two": self.phase_damage(deepest, deepest["stage_two"], deepest["dur"]),
            }
            # The same stretch of Stage Two a kill gets. Comparing whole stages
            # is circular: a longer stage meets more adds by definition, so the
            # add share would look worse even if nothing else differed.
            if matched_window:
                phases["two_matched"] = self.phase_damage(
                    deepest,
                    deepest["stage_two"],
                    min(deepest["stage_two"] + matched_window, deepest["dur"]),
                )
        return {
            "pulls": pulls,
            "deepest": deepest,
            "phases": phases,
            "damage": self.damage_split(deepest),
            "roster": self.roster([deepest["fight"]]),
        }

    def _pull(
        self,
        index: int,
        fight: dict,
        coil,
        se,
        gd,
        coil_dmg,
        well_dmg,
        deaths,
        enemy_deaths,
        ritual,
        curse,
        lust,
    ) -> dict:
        dur = _seconds_into(fight, fight["endTime"])
        trips = self.dives(coil, fight)
        locks = self.lockouts(se, fight)
        real = {tid: [d for d in ds if d[2]] for tid, ds in trips.items()}

        windows = _windows(
            (_seconds_into(fight, e["timestamp"]) for e in self._in(gd, fight)), spells.WINDOW_GAP_SECONDS
        )

        waves: list[dict] = []
        for t, tid in sorted((d[0], tid) for tid, ds in real.items() for d in ds):
            if waves and t - waves[-1]["last"] <= spells.WAVE_SECONDS:
                waves[-1]["members"].append(self.names.get(tid, tid))
                waves[-1]["last"] = t
            else:
                waves.append({"t": t, "last": t, "members": [self.names.get(tid, tid)]})
        for w in waves:
            w["members"] = sorted(set(w["members"]))
            del w["last"]

        deaths_here = sorted(
            (
                _seconds_into(fight, e["timestamp"]),
                self.names.get(e["targetID"]),
                self.ability_name.get(e.get("killingAbilityGameID")),
            )
            for e in self._in(deaths, fight)
        )
        death_times = [d[0] for d in deaths_here]

        early = []
        for tid, ds in real.items():
            for a, b, _ in ds:
                for sa, sb in locks.get(tid, []):
                    overlap = min(b, sb) - max(a, sa)
                    if overlap > spells.OVERLAP_FLOOR_SECONDS and a >= sa:
                        dead_by_then = sum(1 for t in death_times if t < a)
                        early.append(
                            {
                                "who": self.names.get(tid),
                                "t": round(a, 1),
                                "early_by": round(sb - a, 1),
                                "chaos": dead_by_then >= spells.COLLAPSE_DEATHS,
                            }
                        )

        amplified, clean_ticks = [], []
        for e in self._in(coil_dmg, fight) + self._in(well_dmg, fight):
            unmit = e.get("unmitigatedAmount") or 0
            amount = e.get("amount") or 0
            if not unmit:
                continue
            if amount / unmit > 2:
                amplified.append(
                    {
                        "who": self.names.get(e.get("targetID")),
                        "t": _seconds_into(fight, e["timestamp"]),
                        "amount": amount,
                        "unmitigated": unmit,
                        "ratio": round(amount / unmit, 2),
                        "ability": self.ability_name.get(e.get("abilityGameID")),
                    }
                )
            elif self.ability_name.get(e.get("abilityGameID")) == spells.IMMORTAL_COIL:
                clean_ticks.append(amount)
        amplified.sort(key=lambda x: x["t"])

        rit = [
            _seconds_into(fight, e["timestamp"]) for e in self._in(ritual, fight) if e["type"] == "begincast"
        ]
        jawae = [
            _seconds_into(fight, e["timestamp"])
            for e in self._in(enemy_deaths, fight)
            if spells.ECHO_OF_JAWAE in str(self.names.get(e.get("targetID")))
        ]
        amani = sum(
            1
            for e in self._in(enemy_deaths, fight)
            if spells.RESTLESS_AMANI in str(self.names.get(e.get("targetID")))
        )
        curse_here = self._in(curse, fight)

        # The cascade that ends the pull: the first death followed by a pile-up.
        collapse = None
        for t, who, cause in deaths_here:
            if sum(1 for x in death_times if t <= x <= t + 30) >= 6:
                collapse = {"t": t, "who": who, "cause": cause}
                break

        return {
            "pull": index,
            "fight": fight["id"],
            "dur": dur,
            "boss_pct": fight.get("bossPercentage"),
            "kill": fight.get("kill"),
            "windows": [[round(a, 1), round(b, 1)] for a, b in windows],
            "cadence": [round(windows[j + 1][0] - windows[j][0], 1) for j in range(len(windows) - 1)],
            "waves": waves,
            "dives": [
                {"who": self.names.get(tid), "spans": [[a, b] for a, b, _ in ds]}
                for tid, ds in sorted(real.items(), key=lambda kv: self.names.get(kv[0], ""))
            ],
            "lockouts": {self.names.get(tid): v for tid, v in locks.items()},
            "early": early,
            "amplified": amplified,
            "clean_coil_tick": round(statistics.median(clean_ticks)) if clean_ticks else None,
            "deaths": [{"t": t, "who": w, "cause": c} for t, w, c in deaths_here],
            "collapse": collapse,
            "ritual": rit[0] if rit else None,
            "stage_two": max(jawae) if jawae else None,
            "amani_killed": amani,
            "curse_cast": sum(1 for e in curse_here if e["type"] == "begincast"),
            "curse_landed": sum(1 for e in curse_here if e["type"] == "cast"),
            "lust": sorted(
                {
                    round(_seconds_into(fight, e["timestamp"]))
                    for e in self._in(lust, fight)
                    if e["type"] == "applybuff"
                }
            ),
            "gd_damage": sum(e.get("amount") or 0 for e in self._in(gd, fight)),
        }

    # ---- roster and damage ----

    def roster(self, fight_ids: list[int] | None = None) -> dict:
        """Who was in the raid, and in what role. Scoped to one pull by default:
        across a whole night a healer who went DPS for a pull, or anybody swapped
        in and out, is counted twice and the raid comes out at 21 people."""
        details = self.f.player_details(fight_ids or self.ids)
        while isinstance(details, dict) and "data" in details:
            details = details["data"]
        if isinstance(details, dict) and "playerDetails" in details:
            details = details["playerDetails"]
        details = details or {}
        ilvls, roles = [], {}
        for role in ("tanks", "healers", "dps"):
            for p in details.get(role) or []:
                roles[p["name"]] = "healer" if role == "healers" else ("tank" if role == "tanks" else "dps")
                if p.get("maxItemLevel"):
                    ilvls.append(p["maxItemLevel"])
        return {
            "roles": roles,
            "tanks": sum(1 for v in roles.values() if v == "tank"),
            "healers": sum(1 for v in roles.values() if v == "healer"),
            "dps": sum(1 for v in roles.values() if v == "dps"),
            "ilvl_median": round(statistics.median(ilvls)) if ilvls else None,
        }

    def phase_damage(self, pull: dict, a: float, b: float) -> dict:
        """The damage table for one slice of a pull, split by target.

        Used to measure Stage Two on its own terms rather than inferring it from
        boss health percentages: the boss is not immune during the Ritual, so a
        phase's damage is the only figure that needs no assumption about where
        her health bar stood when it began."""
        fight = next(f for f in self.pulls if f["id"] == pull["fight"])
        base = fight["startTime"]
        table = self.f.damage_table([pull["fight"]], start=base + a * 1000, end=base + b * 1000)
        secs = (table.get("totalTime") or 1) / 1000
        by_target: collections.Counter = collections.Counter()
        total, uptime = 0, []
        for entry in table.get("entries", []):
            total += entry.get("total", 0)
            if table.get("totalTime"):
                uptime.append(entry.get("activeTime", 0) / table["totalTime"])
            for t in entry.get("targets", []) or []:
                by_target[t["name"]] += t.get("total", 0)
        boss = sum(v for k, v in by_target.items() if k.startswith(self.boss.split()[0]))
        adds = sum(v for k, v in by_target.items() if spells.RESTLESS_AMANI in k)
        return {
            "seconds": secs,
            "total": total,
            "boss": boss,
            "adds": adds,
            "uptime": (sum(uptime) / len(uptime)) if uptime else None,
            "by_target": by_target.most_common(6),
        }

    def damage_split(self, pull: dict) -> dict:
        """Where the raid's damage went on one pull, and how much of the fight
        each player spent actually doing it."""
        table = self.f.damage_table([pull["fight"]])
        by_target: collections.Counter = collections.Counter()
        total = 0
        uptime = []
        for entry in table.get("entries", []):
            total += entry.get("total", 0)
            if table.get("totalTime"):
                uptime.append(entry.get("activeTime", 0) / table["totalTime"])
            for t in entry.get("targets", []) or []:
                by_target[t["name"]] += t.get("total", 0)
        secs = (table.get("totalTime") or 1) / 1000
        return {
            "total": total,
            "dps": total / secs,
            "uptime": (sum(uptime) / len(uptime)) if uptime else None,
            "by_target": by_target.most_common(8),
            "seconds": secs,
        }
