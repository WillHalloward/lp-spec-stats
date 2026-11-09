"""The numbers behind the Twin Fangs page, read out of the cached event streams.

Every pull of Mythic Twin Fangs runs to the same script (Blood Torrent and the
globules at 9s, Stone Breaker at 24s, Rouse the Brood and the snakes at 36s,
Ravenous Feast at 61s, the second globule wave at 70s, and so on), so most of
what follows is "what happened at this mechanic, pull by pull, player by
player".

Wipe rule: the wipe starts at the first death of the first cascade, meaning four player
deaths within eight seconds. Deaths from there on are the wipe and are not
held against anyone; everything before it is a "pre-wipe" death.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from itertools import product
from functools import cached_property

from . import spells as S
from .fetch import Fetcher

CASCADE_N = 4  # deaths ...
CASCADE_S = 8.0  # ... inside this many seconds start the wipe
BURST_CLUSTER_MS = 600  # globule explosion hits closer than this are one explosion
WAVE_S = 20.0  # a globule wave's window after Blood Torrent
DEATH_DROP_MS = (1850, 2100)  # a dead player's globules land about 2 s after the death (1.88-2.04 s seen)
WAVE_MIN_S = 7.5  # a wave cut off sooner than this by the wipe is not counted (its drops end at ~7 s)
RAID_SMASH = 12  # a Feast smash hitting this many players went out to the raid: too few were in it
FEAST_S = 15.0  # Feast plus its founts
ROUSE_S = 25.0  # a Rouse's window: every Broodling has surfaced and cast by then
EMERGE_S = 25.0

# killing ability -> death group
DEATH_GROUP = {
    "Visceral Burst": "burst",
    "Tainted Burst": "tainted",
    "Ravenous Feast": "feast",
    "Eternal Venom": "venom",
    "Caustic Globule": "globule",  # the explosion; a soak death is told apart by spell id
    "Barbed Bulwark": "globule",
    "Stir the Depths": "waves",
    "Corrosive Spit": "snakes",
    "Venomous Emergence": "snakes",
    "Coiling Ichor": "ichor",
    "Stone Breaker": "stone",
    "Caustic Deluge": "tank",
    "Melee": "tank",
    "Clotted Bolt": "tank",
    "Concentrated Spittle": "tank",
    "Vile Flood": "flood",
}
# a kill by these says nothing on its own: blame the biggest hit just before
AMBIENT = {"Toxic Fumes", "Rouse the Brood", "Stagger", None}
GROUP_LABEL = {
    "burst": "Visceral Burst (missed kick)",
    "tainted": "Tainted Burst (fount not healed)",
    "feast": "Ravenous Feast",
    "venom": "Eternal Venom ticks",
    "globule": "Caustic Globule explosion",
    "soak": "Caustic Globule soak",
    "waves": "Stir the Depths waves",
    "snakes": "snakes",
    "ichor": "Coiling Ichor",
    "stone": "Stone Breaker",
    "tank": "tank damage",
    "flood": "Vile Flood",
    "attrition": "attrition from Toxic Fumes",
    "other": "other",
}


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# The side sequences a Rouse can run, from the 80 kills on the rouse_spawns
# page: the first Rouse in a place (1, 3, 5) uses each spot on a side once, the
# second (2, 4, 6) runs one of five. Letters are spots in order of first use.
FIRST_SEQS = ("ABCDE",)
SECOND_SEQS = ("ABCDE", "ABCDA", "ABCDB", "ABCAD", "ABCAB")


def _letters(spots: list[str]) -> str:
    seen: dict[str, str] = {}
    return "".join(seen.setdefault(x, "ABCDE"[len(seen)]) for x in spots)


def infer_spots(adds: list[dict], n: int) -> None:
    """Give every Broodling a side, and place the ones with no position.

    A Broodling kicked before it was hit or finished a Burst has no position in
    the log. Sides alternate in spawn order, so its side is known from any
    placed Broodling. Its spot is filled in when exactly one spot fits the
    side sequences above; those get `inferred`. The rest keep spot "?".
    """
    order = sorted(adds, key=lambda a: a["spawn_rank"])
    known = next((j for j, a in enumerate(order) if a["spot"] != "?"), None)
    for a in order:
        a["side"], a["inferred"] = None, False
    if known is None:
        return
    flip = {"L": "R", "R": "L"}
    k_side = order[known]["spot"][0]
    for j, a in enumerate(order):
        a["side"] = k_side if (j - known) % 2 == 0 else flip[k_side]
    seqs = FIRST_SEQS if n % 2 else SECOND_SEQS
    for side in "LR":
        mine = [a for a in order if a["side"] == side]
        unk = [j for j, a in enumerate(mine) if a["spot"] == "?"]
        if not unk or len(unk) > 3:
            continue
        names = [f"{side}{x}" for x in range(1, 6)]
        fits: list[tuple[str, ...]] = []
        for combo in product(names, repeat=len(unk)):
            spots = [a["spot"] for a in mine]
            for j, x in zip(unk, combo):
                spots[j] = x
            if any(q.startswith(_letters(spots)) for q in seqs):
                fits.append(combo)
        for pos, j in enumerate(unk):
            options = {c[pos] for c in fits}
            if len(options) == 1:
                mine[j]["spot"], mine[j]["inferred"] = options.pop(), True


class Analysis:
    def __init__(self, code: str, encounter: int | None = None, difficulty: int | None = None) -> None:
        self.code = code
        self.f = Fetcher(code)
        self.meta = self.f.fights()
        enc = encounter or 3421
        diff = difficulty or 5
        self.encounter, self.difficulty = enc, diff
        self.F = {
            x["id"]: x
            for x in self.meta["fights"]
            if x["encounterID"] == enc and x["difficulty"] == diff
        }
        self.ids = sorted(self.F)
        self.pull_no = {fid: i + 1 for i, fid in enumerate(self.ids)}
        self.ab = {a["gameID"]: a["name"] for a in self.f.abilities()}
        self.actors = {a["id"]: a for a in self.f.actors()}

    # ---- plumbing ----

    def ev(self, key: str, data_type: str, **kw) -> list[dict]:
        return self.f.events(key, self.ids, data_type, **kw)

    def rel(self, fid: int, ts: float) -> float:
        return (ts - self.F[fid]["startTime"]) / 1000

    def dur(self, fid: int) -> float:
        return self.rel(fid, self.F[fid]["endTime"])

    def name(self, aid) -> str | None:
        a = self.actors.get(aid)
        return a and a["name"]

    def owner(self, aid):
        """Players stand for their pets, so a felhunter's kick is its warlock's."""
        a = self.actors.get(aid)
        if a and a.get("petOwner"):
            return a["petOwner"]
        return aid

    def by_fight(self, events, pred=None):
        out = defaultdict(list)
        for e in events:
            if e.get("fight") in self.F and (pred is None or pred(e)):
                out[e["fight"]].append(e)
        for v in out.values():
            v.sort(key=lambda e: e["timestamp"])
        return out

    # ---- raid ----

    @cached_property
    def details(self) -> dict:
        pd = self.f.player_details(self.ids)
        pd = pd.get("data", pd)
        return pd.get("playerDetails", pd)

    @cached_property
    def roles(self) -> dict[str, str]:
        role = {"tanks": "tank", "healers": "healer", "dps": "dps"}
        return {p["name"]: role[r] for r, L in self.details.items() for p in L}

    @cached_property
    def cls(self) -> dict[str, str]:
        return {p["name"]: p["type"] for L in self.details.values() for p in L}

    @cached_property
    def spec(self) -> dict[str, str]:
        out = {}
        for L in self.details.values():
            for p in L:
                specs = p.get("specs") or [{}]
                out[p["name"]] = specs[0].get("spec", "")
        return out

    @cached_property
    def pid(self) -> dict[str, int]:
        return {a["name"]: a["id"] for a in self.actors.values() if a["type"] == "Player" and a["name"] in self.roles}

    def is_player(self, aid) -> bool:
        return self.name(aid) in self.roles and self.actors.get(aid, {}).get("type") == "Player"

    @cached_property
    def present(self) -> dict[int, set[str]]:
        """Who was in each pull: anyone who cast something in it."""
        out = defaultdict(set)
        for e in self.ev("casts", "Casts", hostility="Friendlies"):
            if e.get("fight") in self.F and self.is_player(e.get("sourceID")):
                out[e["fight"]].add(self.name(e["sourceID"]))
        return out

    # ---- boss script ----

    @cached_property
    def enemy_casts(self):
        return self.by_fight(self.ev("enemy_casts", "Casts", hostility="Enemies"))

    def casts(self, fid: int, ability: int, kind: str = "cast") -> list[float]:
        return [e["timestamp"] for e in self.enemy_casts[fid] if e["abilityGameID"] == ability and e["type"] == kind]

    def marks(self, fid: int) -> list[dict]:
        """The boss script of one pull, for the timeline. Stone Breaker's three
        soaks are one mark."""
        kinds = [
            (S.BLOOD_TORRENT, "globules"),
            (S.STONE_BREAKER, "stone"),
            (S.ROUSE, "rouse"),
            (S.COILING_ICHOR, "ichor"),
            (S.STIR, "waves"),
            (S.FEAST, "feast"),
            (S.SANGUINE_STORM, "storm"),
            (S.VILE_FLOOD, "flood"),
        ]
        out = []
        for ab, k in kinds:
            last = -1e9
            for t in self.casts(fid, ab):
                if t - last > 10000:  # Stone Breaker casts three times in seven seconds
                    out.append({"t": round(self.rel(fid, t), 1), "k": k})
                last = t
        return sorted(out, key=lambda m: m["t"])

    # ---- boss health ----

    @cached_property
    def done(self):
        return self.by_fight(self.ev("damage_done", "DamageDone", hostility="Friendlies", resources=True))

    @cached_property
    def boss_hp(self) -> dict[int, dict[str, float]]:
        out = {}
        for fid in self.ids:
            hp = {}
            for e in self.done[fid]:
                n = self.name(e.get("targetID"))
                if n in ("Vexhul", "Ithraz") and e.get("maxHitPoints"):
                    hp[n] = 100 * e["hitPoints"] / e["maxHitPoints"]
            out[fid] = {k: round(v, 1) for k, v in hp.items()}
        return out

    # ---- deaths ----

    @cached_property
    def taken(self):
        return self.by_fight(self.ev("damage_taken", "DamageTaken", hostility="Friendlies", resources=True))

    @cached_property
    def taken_by_player(self):
        out = defaultdict(list)
        for fid, L in self.taken.items():
            for e in L:
                out[(fid, e.get("targetID"))].append(e)
        return out

    @staticmethod
    def _group_of(aid, name) -> str:
        # both Caustic Globule spells share a name: the soak and the explosion
        if aid == S.GLOBULE_SOAK:
            return "soak"
        return DEATH_GROUP.get(name, "other")

    def death_group(self, fid, pid, ts, killer) -> tuple[str, str | None]:
        name = self.ab.get(killer) if killer else None
        if name not in AMBIENT:
            return self._group_of(killer, name), name
        # the biggest non-ambient hit in the five seconds before
        best, bname, bid = 0, None, None
        for e in self.taken_by_player[(fid, pid)]:
            if ts - 5000 <= e["timestamp"] <= ts:
                n = self.ab.get(e["abilityGameID"])
                amt = e.get("amount", 0) + e.get("absorbed", 0)
                if n not in AMBIENT and n != "Eternal Venom" and n in DEATH_GROUP and amt > best:
                    best, bname, bid = amt, n, e["abilityGameID"]
        if bname:
            return self._group_of(bid, bname), f"{name or 'killing blow'} after {bname}"
        return "attrition", name

    @cached_property
    def deaths(self) -> dict[int, list[dict]]:
        out = {}
        raw = self.by_fight(self.ev("deaths", "Deaths", hostility="Friendlies"), lambda e: self.is_player(e.get("targetID")))
        for fid in self.ids:
            L = []
            for d in raw.get(fid, []):
                pid = d["targetID"]
                g, why = self.death_group(fid, pid, d["timestamp"], d.get("killingAbilityGameID"))
                L.append(
                    {
                        "ts": d["timestamp"],
                        "t": round(self.rel(fid, d["timestamp"]), 1),
                        "player": self.name(pid),
                        "group": g,
                        "why": why,
                        "ev": self.stacks_before(fid, pid, d["timestamp"]),
                    }
                )
            out[fid] = L
        return out

    @cached_property
    def wipe(self) -> dict[int, float | None]:
        """Report-clock ms where the wipe starts, None for a kill or no cascade."""
        out = {}
        for fid in self.ids:
            ts = [d["ts"] for d in self.deaths[fid]]
            start = None
            for i, t in enumerate(ts):
                if bisect_right(ts, t + CASCADE_S * 1000) - i >= CASCADE_N:
                    start = t
                    break
            out[fid] = None if self.F[fid].get("kill") else start
        return out

    def cut(self, fid) -> float:
        """Where counting stops in a pull: the wipe, or the end."""
        return self.wipe[fid] or self.F[fid]["endTime"]

    @cached_property
    def _cast_times(self) -> dict[tuple[int, str], list[float]]:
        out = defaultdict(list)
        for e in self.ev("casts", "Casts", hostility="Friendlies"):
            if e.get("fight") in self.F and self.is_player(e.get("sourceID")):
                out[(e["fight"], self.name(e["sourceID"]))].append(e["timestamp"])
        for v in out.values():
            v.sort()
        return out

    @cached_property
    def dead_spans(self) -> dict[tuple[int, str], list[tuple[float, float]]]:
        """(fight, player) -> [(died, back)]. A battle rez shows up as the
        player casting again; with no cast after a death they stay dead."""
        out = defaultdict(list)
        for fid in self.ids:
            for d in self.deaths[fid]:
                casts = self._cast_times.get((fid, d["player"]), [])
                i = bisect_right(casts, d["ts"] + 500)
                out[(fid, d["player"])].append((d["ts"], casts[i] if i < len(casts) else float("inf")))
        return out

    def alive(self, fid, name, ts) -> bool:
        return not any(a <= ts < b for a, b in self.dead_spans.get((fid, name), []))

    def wipe_cause(self, fid) -> str | None:
        w = self.wipe[fid]
        if w is None:
            return None
        # the first death of the cascade: what started it, not what killed most
        # people once it was going (a Feast finishing a broken raid)
        return next(d["group"] for d in self.deaths[fid] if d["ts"] == w)

    # ---- Eternal Venom ----

    @cached_property
    def debuffs(self):
        return self.by_fight(self.ev("debuffs", "Debuffs", hostility="Friendlies"))

    @cached_property
    def stacks(self) -> dict[tuple[int, int], list[tuple[float, int]]]:
        """(fight, player) -> [(ts, stacks after)] for Eternal Venom."""
        out = defaultdict(list)
        cur = defaultdict(int)
        for fid in self.ids:
            for e in self.debuffs[fid]:
                if e["abilityGameID"] != S.ETERNAL_VENOM:
                    continue
                k = (fid, e["targetID"])
                t = e["type"]
                if t == "applydebuff":
                    cur[k] = 1
                elif t in ("applydebuffstack", "removedebuffstack"):
                    cur[k] = e.get("stack", cur[k])
                elif t == "removedebuff":
                    cur[k] = 0
                else:
                    continue
                out[k].append((e["timestamp"], cur[k]))
        return out

    def stacks_before(self, fid, pid, ts) -> int:
        """Eternal Venom stacks a player had going into a death. The debuff is
        removed a few ms before the death event, so read the most stacks in the
        1.5 s before, or what they carried into that window."""
        win = [v for t, v in self.stacks.get((fid, pid), []) if ts - 1500 <= t <= ts]
        return max(win + [self.stack_at(fid, pid, ts - 1500)])

    def stack_at(self, fid, pid, ts) -> int:
        s = 0
        for t, v in self.stacks.get((fid, pid), []):
            if t > ts:
                break
            s = v
        return s

    @cached_property
    def stack_gains(self) -> list[dict]:
        """Every Eternal Venom stack gained, with the hit that gave it."""
        out = []
        # A Stir the Depths wave gives its stack with a debuff, mostly with no
        # damage event, so its applications count as hits too.
        waves = defaultdict(list)
        for fid in self.ids:
            for e in self.debuffs[fid]:
                if e["abilityGameID"] == S.STIR_DEBUFF and e["type"] == "applydebuff":
                    waves[(fid, e["targetID"])].append(e)
        for (fid, pid), series in self.stacks.items():
            prev = 0
            hits = self.taken_by_player[(fid, pid)] + waves[(fid, pid)]
            for ts, v in series:
                if v > prev:
                    src = "other"
                    best = None
                    for e in hits:
                        dtm = abs(e["timestamp"] - ts)
                        if dtm <= 150 and e["abilityGameID"] in S.EV_SOURCES and (best is None or dtm < best):
                            best, src = dtm, S.EV_SOURCES[e["abilityGameID"]]
                    out.append({"fight": fid, "player": self.name(pid), "ts": ts, "n": v - prev, "src": src})
                prev = v
        return out

    # ---- globules ----

    @cached_property
    def enemy_buffs(self):
        return self.by_fight(self.ev("enemy_buffs", "Buffs", hostility="Enemies"))

    @cached_property
    def enemy_debuffs(self):
        return self.by_fight(self.ev("enemy_debuffs", "Debuffs", hostility="Enemies"))

    def explosions(self, fid) -> list[float]:
        """Unsoaked globules going off, one entry per explosion."""
        hits = sorted(e["timestamp"] for e in self.taken[fid] if e["abilityGameID"] == S.GLOBULE_BURST)
        out = []
        for t in hits:
            if out and t - out[-1][-1] < BURST_CLUSTER_MS:
                out[-1].append(t)
            else:
                out.append([t])
        return [c[0] for c in out if len(c) >= 3]

    @cached_property
    def death_events(self) -> dict[int, list[dict]]:
        return self.by_fight(self.ev("deaths", "Deaths", hostility="Friendlies"), lambda e: self.is_player(e.get("targetID")))

    @cached_property
    def waves(self) -> list[dict]:
        """One row per globule wave that opened before the wipe."""
        bulwark_id = next((a["id"] for a in self.actors.values() if a["name"] == S.BULWARK), None)
        rows = []
        for fid in self.ids:
            buffs = [e for e in self.enemy_buffs[fid] if e["abilityGameID"] == S.BARBED_BULWARK]
            cc = [
                e
                for e in self.enemy_debuffs[fid]
                if e.get("targetID") == bulwark_id
                and e["type"] == "applydebuff"
                and self.ab.get(e["abilityGameID"]) in S.SHIELD_CC
            ]
            soaks = [e for e in self.taken[fid] if e["abilityGameID"] == S.GLOBULE_SOAK]
            booms = self.explosions(fid)
            cut = self.cut(fid)
            for i, w in enumerate(self.casts(fid, S.BLOOD_TORRENT)):
                if cut - w < WAVE_MIN_S * 1000:  # the wipe came before the globules landed
                    break
                end = min(w + WAVE_S * 1000, cut)
                # not every globule gets a shield, so globules are counted off the
                # drops. A player who dies drops up to three more, 2.0 s after the
                # death, through the same spell; those are kept apart.
                dropped = [
                    e["timestamp"]
                    for e in self.enemy_casts[fid]
                    if e["abilityGameID"] == S.GLOBULE_DROP and e["type"] == "cast" and w <= e["timestamp"] < min(w + 15000, cut)
                ]
                died = [
                    (e["timestamp"], self.name(e["targetID"]))
                    for e in self.death_events.get(fid, [])
                    if any(DEATH_DROP_MS[0] <= t - e["timestamp"] <= DEATH_DROP_MS[1] for t in dropped)
                ]
                from_deaths = [
                    t for t in dropped if any(DEATH_DROP_MS[0] <= t - d <= DEATH_DROP_MS[1] for d, _ in died)
                ]
                drops = len(dropped) - len(from_deaths)
                inst = {e["targetInstance"] for e in buffs if e["type"] == "applybuff" and w <= e["timestamp"] < w + 15000}
                strips = []
                for e in buffs:
                    if e["type"] == "removebuff" and e["targetInstance"] in inst:
                        near = [
                            c
                            for c in cc
                            if c["targetInstance"] == e["targetInstance"] and -400 <= c["timestamp"] - e["timestamp"] <= 50
                        ]
                        if near:
                            c = max(near, key=lambda c: c["timestamp"])
                            who = self.name(self.owner(c["sourceID"]))
                            strips.append(
                                {
                                    "spell": self.ab.get(c["abilityGameID"]),
                                    "player": who,
                                    "cls": self.cls.get(who, "?"),
                                }
                            )
                per = Counter(self.name(e["targetID"]) for e in soaks if w <= e["timestamp"] < end and self.is_player(e["targetID"]))
                wave_booms = [b for b in booms if w <= b < end]
                rows.append(
                    {
                        "fight": fid,
                        "pull": self.pull_no[fid],
                        "wave": i + 1,
                        "ts": w,
                        "t": round(self.rel(fid, w), 1),
                        "globules": drops,
                        "death_globules": len(from_deaths),
                        "death_droppers": [n for _, n in died],
                        "shielded": len(inst),
                        "stripped": len(strips),
                        "strips": strips,
                        "soaks": sum(per.values()),
                        "soakers": dict(per),
                        "booms": [round(self.rel(fid, b), 1) for b in wave_booms],
                        "boom_ts": wave_booms,
                        # who could have taken one: alive at the explosion and had
                        # not soaked in this wave by then
                        "idle": sorted(
                            {
                                n
                                for b in wave_booms
                                for n in self.present[fid]
                                if self.alive(fid, n, b)
                                and not any(
                                    self.name(e["targetID"]) == n and w <= e["timestamp"] <= b for e in soaks
                                )
                            }
                        ),
                    }
                )
        return rows

    @cached_property
    def loose_globules(self) -> dict:
        """Globules before the wipe that no counted wave holds: dropped by deaths
        away from a wave, or by a wave the wipe cut short. Their soaks and
        explosions are counted here so the night's totals add up."""
        out = {"globules": 0, "death_globules": 0, "soaks": 0, "booms": []}
        for fid in self.ids:
            cut = self.cut(fid)
            mine = [w for w in self.waves if w["fight"] == fid]
            drop_win = [(w["ts"], w["ts"] + 15000) for w in mine]
            soak_win = [(w["ts"], min(w["ts"] + WAVE_S * 1000, cut)) for w in mine]

            def outside(t, wins):
                return not any(a <= t < b for a, b in wins)

            drops = [
                e["timestamp"]
                for e in self.enemy_casts[fid]
                if e["abilityGameID"] == S.GLOBULE_DROP and e["type"] == "cast" and e["timestamp"] < cut
                and outside(e["timestamp"], drop_win)
            ]
            deaths = [d["ts"] for d in self.deaths[fid]]
            dd = [t for t in drops if any(DEATH_DROP_MS[0] <= t - d <= DEATH_DROP_MS[1] for d in deaths)]
            out["globules"] += len(drops)
            out["death_globules"] += len(dd)
            out["soaks"] += sum(
                1
                for e in self.taken[fid]
                if e["abilityGameID"] == S.GLOBULE_SOAK and self.is_player(e["targetID"]) and e["timestamp"] < cut
                and outside(e["timestamp"], soak_win)
            )
            for b in self.explosions(fid):
                if b < cut and outside(b, soak_win):
                    # a dead player's globules go off about 12 s after the death
                    dead = [d for d in self.deaths[fid] if 8000 <= b - d["ts"] <= 16000]
                    out["booms"].append({
                        "pull": self.pull_no[fid],
                        "t": round(self.rel(fid, b), 1),
                        "from": dead[0]["player"] if dead else None,
                        "killed": sum(1 for d in self.deaths[fid] if 0 <= d["ts"] - b <= 1500),
                    })
        return out

    def booms_after_wipe(self) -> int:
        return sum(1 for fid in self.ids if self.wipe[fid] for b in self.explosions(fid) if b >= self.wipe[fid])

    # ---- Ravenous Feast and Tainted Blood ----

    @cached_property
    def feasts(self) -> list[dict]:
        rows = []
        heals = self.by_fight(self.ev("heals", "Healing", hostility="Friendlies"))
        for fid in self.ids:
            cut = self.cut(fid)
            deb = self.debuffs[fid]
            # Tainted Blood and Blood Torrent windows per player
            tb, bt = defaultdict(list), defaultdict(list)
            open_ = {}
            for e in deb:
                a = e["abilityGameID"]
                if a not in (S.TAINTED_BLOOD, 1303235, S.BLOOD_TORRENT):
                    continue
                k = (a, e["targetID"])
                if e["type"] == "applydebuff":
                    open_[k] = e["timestamp"]
                elif e["type"] == "removedebuff" and k in open_:
                    (tb if a == S.TAINTED_BLOOD else bt)[e["targetID"]].append((open_.pop(k), e["timestamp"]))

            def inside(win, pid, ts):
                return any(a <= ts <= b + 50 for a, b in win.get(pid, []))

            # a smash in the second after the wipe started is the one that started
            # it, but only when the Feast is what started it
            smash_cut = cut + (1000 if self.wipe_cause(fid) in ("feast", "tainted") else 0)
            for t in self.casts(fid, S.FEAST):
                if t >= cut:
                    break
                end = t + FEAST_S * 1000
                # the three smashes, by who the smash damage landed on: the
                # Feasted debuff misses soakers the smash killed
                hits = []
                landed = sorted(
                    (e["timestamp"], self.name(e["targetID"]))
                    for e in self.taken[fid]
                    if e["abilityGameID"] == S.FEAST_HIT and t <= e["timestamp"] < min(end, smash_cut + 1)
                    and self.is_player(e["targetID"])
                )
                for ts, who in landed:
                    if hits and ts - hits[-1][0] < 1000:
                        if who not in hits[-1][1]:
                            hits[-1][1].append(who)
                    else:
                        hits.append([ts, [who]])
                tburst = [
                    e["timestamp"]
                    for e in self.taken[fid]
                    if self.ab.get(e["abilityGameID"]) == "Tainted Burst" and t <= e["timestamp"] < end + 5000
                    and e["timestamp"] <= cut
                ]
                into = Counter()
                for h in heals.get(fid, []):
                    if not (t <= h["timestamp"] < min(end + 5000, cut)) or not h.get("absorbed"):
                        continue
                    if h["type"] != "heal":
                        continue
                    tid = h["targetID"]
                    if inside(tb, tid, h["timestamp"]) and not inside(bt, tid, h["timestamp"]):
                        into[self.name(self.owner(h["sourceID"]))] += h["absorbed"]
                rows.append(
                    {
                        "fight": fid,
                        "pull": self.pull_no[fid],
                        "t": round(self.rel(fid, t), 1),
                        "ts": t,
                        "hits": [{"t": round(self.rel(fid, a), 1), "who": w, "raid": len(w) >= RAID_SMASH} for a, w in hits],
                        # soaking means going into a smash that had enough people
                        "soakers": sorted({n for _, w in hits if len(w) < RAID_SMASH for n in w}),
                        "cut": len(hits) < 3,
                        "burst": bool(tburst),
                        "burst_t": round(self.rel(fid, min(tburst)), 1) if tburst else None,
                        "healed": {k: v for k, v in into.items() if k},
                    }
                )
        return rows

    # ---- Rouse the Brood ----

    @cached_property
    def broodling_pos(self) -> dict[tuple[int, int], tuple[int, int]]:
        bid = next(a["id"] for a in self.actors.values() if a["name"] == S.BROODLING)
        pos = {}
        for fid in self.ids:
            for e in self.done[fid]:
                if e.get("targetID") == bid and "x" in e:
                    pos.setdefault((fid, e.get("targetInstance", 1)), (e["x"], e["y"]))
        for e in self.ev("enemy_casts_res", "Casts", hostility="Enemies", resources=True):
            if e.get("sourceID") == bid and "x" in e:
                pos.setdefault((e["fight"], e.get("sourceInstance", 1)), (e["x"], e["y"]))
        return pos

    @staticmethod
    def _frame(vex, ith):
        """Midpoint and unit axis Vexhul -> Ithraz."""
        m = ((vex[0] + ith[0]) / 2, (vex[1] + ith[1]) / 2)
        d = _dist(vex, ith) or 1
        return m, ((ith[0] - vex[0]) / d, (ith[1] - vex[1]) / d)

    @staticmethod
    def _to(p, frame, turn=1):
        """Into the bosses' frame. turn=-1 turns it half way round."""
        (mx, my), (ax, ay) = frame
        dx, dy = p[0] - mx, p[1] - my
        return (turn * (dx * ax + dy * ay), turn * (-dx * ay + dy * ax))

    @cached_property
    def spot_ref(self) -> dict[str, tuple[float, float]]:
        f = self._frame(S.BOSSES_AT_SPOTS["Vexhul"], S.BOSSES_AT_SPOTS["Ithraz"])
        return {k: self._to(p, f) for k, p in S.SPOTS.items()}

    def boss_at(self, fid, ts) -> dict[str, tuple[int, int]]:
        out = {}
        for nm in ("Vexhul", "Ithraz"):
            near = None
            for e in self.done[fid]:
                if self.name(e.get("targetID")) == nm and "x" in e:
                    if near is None or abs(e["timestamp"] - ts) < abs(near["timestamp"] - ts):
                        near = e
            if near:
                out[nm] = (near["x"], near["y"])
        return out

    def spots_for(self, fid, ts, positions: dict) -> dict:
        """Name the spot of each Broodling in one Rouse. Once the bosses have
        moved, the raid can end up on the other side of them, so the arc is
        tried both ways round and the better fit wins. It is a half turn, not a
        mirror: the raid's left stays its left, so kickers keep their side."""
        b = self.boss_at(fid, ts)
        if len(b) < 2:
            return {k: "?" for k in positions}
        f = self._frame(b["Vexhul"], b["Ithraz"])
        best = None
        for turn in (1, -1):
            names, cost = {}, 0.0
            for k, p in positions.items():
                if not p:
                    names[k] = "?"
                    continue
                q = self._to(p, f, turn)
                n, c = min(self.spot_ref.items(), key=lambda kv: _dist(kv[1], q))
                dd = _dist(c, q)
                cost += min(dd, 3000)
                names[k] = n if dd <= S.SPOT_RADIUS else "?"
            if best is None or cost < best[0]:
                best = (cost, names)
        return best[1]

    @cached_property
    def _kick_events(self) -> list[tuple[int, str, int, float]]:
        """(fight, kicker, spell, ts) for every interrupt used. Casts, plus the
        interrupts that landed with no cast logged: a pet's own Spell Lock can
        log only the interrupt (Niydra's felhunter on 8 Nov)."""
        out = []
        for e in self.ev("casts", "Casts", hostility="Friendlies"):
            if e["type"] == "cast" and e["abilityGameID"] in S.KICK_CD and e.get("fight") in self.F:
                out.append((e["fight"], self.name(self.owner(e["sourceID"])), e["abilityGameID"], e["timestamp"]))
        cast_at = defaultdict(list)
        for fid, who, _, ts in out:
            cast_at[(fid, who)].append(ts)
        for e in self.ev("interrupts", "Interrupts", hostility="Friendlies"):
            fid, ab = e.get("fight"), e.get("abilityGameID")
            if fid not in self.F or ab not in S.KICK_CD:
                continue
            who = self.name(self.owner(e["sourceID"]))
            if not any(abs(e["timestamp"] - t) <= 300 for t in cast_at[(fid, who)]):
                out.append((fid, who, ab, e["timestamp"]))
        return out

    @cached_property
    def kick_aims(self) -> dict[tuple[int, int, int], list[tuple[float, str]]]:
        """(fight, target, instance) -> [(ts, kicker)] for every kick aimed at
        an enemy, landed or not. A kick that lands just after the cast
        finished does nothing, so this is where the near misses show."""
        out = defaultdict(list)
        for kind, name in (("casts", "Casts"), ("interrupts", "Interrupts")):
            for e in self.ev(kind, name, hostility="Friendlies"):
                if e.get("fight") not in self.F or e.get("abilityGameID") not in S.KICK_CD:
                    continue
                if kind == "casts" and e["type"] != "cast":
                    continue
                key = (e["fight"], e.get("targetID"), e.get("targetInstance", 1))
                out[key].append((e["timestamp"], self.name(self.owner(e["sourceID"]))))
        for v in out.values():
            v.sort()
        return out

    @cached_property
    def kick_spell(self) -> dict[str, int]:
        """Each kicker's interrupt, the one they used most this night."""
        c = defaultdict(Counter)
        for _, who, ab, _ in self._kick_events:
            if who in self.roles:
                c[who][ab] += 1
        return {n: cc.most_common(1)[0][0] for n, cc in c.items()}

    @cached_property
    def kick_uses(self) -> dict[tuple[int, str], list[float]]:
        # Spell Lock is one cooldown whichever way it is pressed
        same = {19647: 119910, 119910: 19647}
        out = defaultdict(list)
        for fid, who, ab, ts in self._kick_events:
            mine = self.kick_spell.get(who)
            if mine is not None and (ab == mine or same.get(ab) == mine):
                out[(fid, who)].append(ts)
        for v in out.values():
            v.sort()
        return out

    def kick_ready(self, fid, who, ts) -> bool:
        cd = S.KICK_CD[self.kick_spell[who]] * 1000
        return not any(ts - cd < u <= ts for u in self.kick_uses.get((fid, who), []))

    def kick_plan(self, plan: dict) -> dict:
        """Every placed Broodling against the night's kick plan.

        In each pair of spots the first Broodling to surface is the early
        kicker's, the second the late kicker's, any more the backup's. A
        Broodling whose kicker is dead (or not in the pull) goes to the backup,
        then to the first living centre backup. "?" Broodlings have no spot, so
        they are left out and counted per kicker as `unplaced`.
        """
        pair_of = {sp: g for g in plan["groups"] for sp in g["spots"]}
        roles: dict[str, str] = {}
        member: dict[str, str] = {}  # a flexible pair's kickers -> its shared row
        for g in plan["groups"]:
            if g.get("flex"):
                row = " + ".join(g["flex"])
                roles[row] = f"shared {'+'.join(sorted(g['spots']))}"
                member.update({n: row for n in g["flex"]})
            for r in ("early", "late", "backup"):
                if g.get(r):
                    roles.setdefault(g[r], f"{r} {'+'.join(sorted(g['spots']))}")
            for c in g.get("centre") or []:
                roles.setdefault(c, "centre backup")
        P = defaultdict(lambda: defaultdict(int))
        lost = defaultdict(Counter)
        helped = defaultdict(Counter)
        react = defaultdict(list)
        skipped = 0
        for r in self.rouses:
            fid = r["fight"]
            t0 = self.F[fid]["startTime"] + r["t"] * 1000
            seen = Counter()
            blind = set()  # sides where an unplaced Broodling has surfaced
            for b in sorted(r["adds"], key=lambda b: b["spawn_rank"]):
                k = b["kicker"]
                if b["spot"] == "?":
                    if k:
                        P[member.get(k, k)]["unplaced"] += 1
                    blind |= {b["side"]} if b["side"] else {"L", "R"}
                    continue
                g = pair_of.get(b["spot"])
                if not g:
                    continue
                if any(sp[0] in blind for sp in g["spots"]):
                    # it may have been this pair's first, so who is early and who
                    # late from here on is a guess; leave these out
                    skipped += 1
                    continue
                key = tuple(g["spots"])
                i = seen[key]
                seen[key] += 1
                role = ("early", "late")[i] if i < 2 else "backup"
                spawn = t0 + b["spawn"] * 1000

                def up(n):
                    return bool(n) and n in self.present[fid] and self.alive(fid, n, spawn)

                if g.get("flex"):
                    # either of them, in whatever order they sort it out
                    alive = any(up(m) for m in g["flex"])
                    owner = " + ".join(g["flex"]) if alive else None
                else:
                    owner = g.get(role)
                    alive = up(owner)
                if not alive:
                    owner = g.get("backup") if up(g.get("backup")) else next((c for c in g.get("centre") or [] if up(c)), None)
                if not owner:
                    continue
                o = P[owner]
                o["theirs"] += 1
                if b["bursts"]:
                    o["off"] += 1
                if k == owner or member.get(k) == owner:
                    o["kicked"] += 1
                    react[owner].append(b["kick"] - b["spawn"])
                elif k:
                    o["taken"] += 1
                    lost[owner][k] += 1
                    helped[member.get(k, k)][owner] += 1
                    P[member.get(k, k)]["helped"] += 1
                    kt = t0 + b["kick"] * 1000
                    mates = g["flex"] if g.get("flex") and owner == " + ".join(g["flex"]) else [owner]
                    if any(m in self.kick_spell and self.alive(fid, m, kt) and self.kick_ready(fid, m, kt) for m in mates):
                        o["taken_ready"] += 1
        rows = []
        for n in sorted(set(P) | set(roles), key=lambda n: (list(roles).index(n) if n in roles else 99, n)):
            c = P[n]
            rows.append(
                {
                    "player": n,
                    "role": roles.get(n, "not in the plan"),
                    "theirs": c["theirs"],
                    "kicked": c["kicked"],
                    "taken": c["taken"],
                    "taken_ready": c["taken_ready"],
                    "off": c["off"],
                    "helped": c["helped"],
                    "unplaced": c["unplaced"],
                    "react": round(statistics.median(react[n]), 1) if react[n] else None,
                    "lost_to": lost[n].most_common(3),
                    "helped_who": helped[n].most_common(3),
                }
            )
        return {"rows": [r for r in rows if r["role"] != "not in the plan" or r["helped"] or r["unplaced"]],
                "note": plan.get("note", ""), "skipped": skipped, "groups": plan["groups"]}

    @cached_property
    def rouses(self) -> list[dict]:
        bid = next(a["id"] for a in self.actors.values() if a["name"] == S.BROODLING)
        kicks = self.by_fight(self.ev("interrupts", "Interrupts", hostility="Friendlies"))
        rows = []
        for fid in self.ids:
            ec = [e for e in self.enemy_casts[fid] if e.get("sourceID") == bid]
            for i, r in enumerate(self.casts(fid, S.ROUSE)):
                if self.wipe[fid] and r >= self.wipe[fid]:
                    break
                end = r + ROUSE_S * 1000
                # nothing after the wipe started counts: Broodlings that surface,
                # Bursts that land and kicks that go out once the raid is dying
                # (a Burst that starts a wipe is cast 0.2-2 s before its first death,
                # so it is inside this)
                lim = min(end, self.wipe[fid] or end)
                first = {}
                bursts = defaultdict(list)
                for e in ec:
                    if not (r <= e["timestamp"] < lim):
                        continue
                    k = e.get("sourceInstance", 1)
                    if e["type"] == "begincast":
                        first.setdefault(k, e["timestamp"])
                    elif e["type"] == "cast" and e["abilityGameID"] == S.VISCERAL_BURST:
                        bursts[k].append(e["timestamp"])
                kicked = {}
                for e in kicks.get(fid, []):
                    if r <= e["timestamp"] < lim and e.get("targetID") == bid and e.get("targetInstance", 1) in first:
                        kicked.setdefault(
                            e.get("targetInstance", 1),
                            (e["timestamp"], self.name(self.owner(e["sourceID"])), self.ab.get(e["abilityGameID"])),
                        )
                spawn_rank = {k: j + 1 for j, k in enumerate(sorted(first, key=first.get))}
                spot_of = self.spots_for(fid, r, {k: self.broodling_pos.get((fid, k)) for k in first})
                kick_rank = {k: j + 1 for j, k in enumerate(sorted(kicked, key=lambda k: kicked[k][0]))}
                adds = []
                for k in sorted(first, key=first.get):
                    kt = kicked.get(k)
                    b = bursts.get(k, [])
                    ready = []
                    if b:
                        bt = b[0]
                        ready = sorted(
                            n
                            for n in self.kick_spell
                            if n in self.present[fid] and self.alive(fid, n, bt) and self.kick_ready(fid, n, bt)
                        )
                    adds.append(
                        {
                            "inst": k,
                            "spot": spot_of[k],
                            "spawn": round((first[k] - r) / 1000, 1),
                            "spawn_rank": spawn_rank[k],
                            "kicker": kt and kt[1],
                            "spell": kt and kt[2],
                            "kick": kt and round((kt[0] - r) / 1000, 1),
                            "kick_rank": kick_rank.get(k),
                            "bursts": len(b),
                            "burst_t": b and round((b[0] - r) / 1000, 1),
                            # the first kick aimed at it once the Burst was close:
                            # +0.05 s is a near miss, +3 s a kick sent after the
                            # Burst was noticed (it lands on the next cast)
                            "try": next(
                                (
                                    {"who": w, "late": round((t - b[0]) / 1000, 2)}
                                    for t, w in self.kick_aims.get((fid, bid, k), [])
                                    if t >= b[0] - 500 and t < lim
                                ),
                                None,
                            )
                            if b
                            else None,
                            "ready": ready,
                        }
                    )
                if not adds:  # the wipe started before the first one surfaced
                    continue
                infer_spots(adds, i + 1)
                w = self.wipe[fid]
                rows.append(
                    {
                        "fight": fid,
                        "pull": self.pull_no[fid],
                        "n": i + 1,
                        "t": round(self.rel(fid, r), 1),
                        "adds": adds,
                        "kicked": sum(1 for a in adds if a["kicker"]),
                        "bursts": sum(a["bursts"] for a in adds),
                        # a missed kick ended the pull: the wipe started inside this
                        # Rouse and its first death was a Visceral Burst
                        "ended": bool(w and r <= w < end and self.wipe_cause(fid) == "burst"),
                        "cut": bool(w and w < end),
                    }
                )
        return rows

    def kick_patterns(self) -> list[dict]:
        per = defaultdict(list)
        rouses_alive = Counter()
        for r in self.rouses:
            fid = r["fight"]
            for n in self.kick_spell:
                if n in self.present[fid] and self.alive(fid, n, self.F[fid]["startTime"] + r["t"] * 1000):
                    rouses_alive[n] += 1
            for a in r["adds"]:
                if a["kicker"]:
                    per[a["kicker"]].append(a)
        out = []
        for n in sorted(self.kick_spell, key=lambda n: -len(per[n])):
            ks = per[n]
            spots = Counter(a["spot"] for a in ks if a["spot"] != "?")
            ranks = [a["kick_rank"] for a in ks]
            side = Counter(a["side"] for a in ks if a["side"])
            top_spot, top_n = spots.most_common(1)[0] if spots else ("?", 0)
            known = sum(spots.values())
            spot_share = top_n / known if known else 0
            side_share = side.most_common(1)[0][1] / sum(side.values()) if side else 0
            med = statistics.median(ranks) if ranks else None
            spread = statistics.pstdev(ranks) if len(ranks) > 1 else None
            # the label: fixed spot first, then fixed side, then fixed order
            if len(ks) < 4:
                label = "too few kicks"
            elif spot_share >= 0.6:
                label = f"fixed spot ({top_spot})"
            elif side_share >= 0.8 and med is not None and med <= 3.5:
                label = f"{'left' if side.most_common(1)[0][0] == 'L' else 'right'} side, early"
            elif side_share >= 0.8:
                label = f"{'left' if side.most_common(1)[0][0] == 'L' else 'right'} side, any spot"
            elif med is not None and med <= 3:
                label = "first in"
            elif med is not None and med >= 8:
                label = "last in"
            elif spread is not None and spread >= 2.5:
                label = "any order, any spot"
            else:
                label = "mid-order, anywhere"
            out.append(
                {
                    "player": n,
                    "cls": self.cls.get(n),
                    "role": self.roles.get(n),
                    "spell": self.ab.get(self.kick_spell[n]),
                    "kicks": len(ks),
                    "rouses": rouses_alive[n],
                    "spots": dict(spots),
                    "top_spot": top_spot,
                    "spot_share": round(spot_share, 2),
                    "side_share": round(side_share, 2),
                    "rank_med": med,
                    "rank_sd": spread is not None and round(spread, 1),
                    "label": label,
                }
            )
        return out

    # ---- snakes ----

    @cached_property
    def snakes(self) -> list[dict]:
        sid = next(a["id"] for a in self.actors.values() if a["name"] == S.SPAWN)
        rows = []
        for fid in self.ids:
            cut = self.cut(fid)
            for i, t in enumerate(self.casts(fid, S.EMERGENCE)):
                if t >= cut:
                    break
                end = min(t + EMERGE_S * 1000, cut)
                hits = [e for e in self.done[fid] if e.get("targetID") == sid and t <= e["timestamp"] < end]
                if not hits:  # the wipe came before anyone touched them
                    continue
                death = {}
                for e in hits:
                    if e.get("hitPoints") == 0:
                        death.setdefault(e.get("targetInstance", 1), e["timestamp"])
                inst = sorted({e.get("targetInstance", 1) for e in hits})
                spits = Counter(
                    e.get("sourceInstance", 1)
                    for e in self.enemy_casts[fid]
                    if e.get("sourceID") == sid and e["abilityGameID"] == S.CORROSIVE_SPIT and e["type"] == "cast"
                    and t <= e["timestamp"] < end
                )
                first_dead = min(death, key=death.get) if death else None
                last = max(death.values()) if len(death) == len(inst) and death else end
                dmg = defaultdict(lambda: {"snake": 0, "focus": 0, "all": 0, "first": None})
                for e in self.done[fid]:
                    if not (t <= e["timestamp"] < last):
                        continue
                    who = self.name(self.owner(e.get("sourceID")))
                    if who not in self.roles:
                        continue
                    amt = e.get("amount", 0) + e.get("absorbed", 0)
                    d = dmg[who]
                    d["all"] += amt
                    if e.get("targetID") == sid:
                        d["snake"] += amt
                        if e.get("targetInstance", 1) == first_dead and e["timestamp"] <= death.get(first_dead, end):
                            d["focus"] += amt
                        if d["first"] is None:
                            d["first"] = round((e["timestamp"] - t) / 1000, 1)
                rows.append(
                    {
                        "fight": fid,
                        "pull": self.pull_no[fid],
                        "n": i + 1,
                        "t": round(self.rel(fid, t), 1),
                        "deaths": sorted(round((v - t) / 1000, 1) for v in death.values()),
                        "alive_after": len(inst) - len(death),
                        "spits": sum(spits.values()),
                        "window": round((last - t) / 1000, 1),
                        "dmg": dict(dmg),
                    }
                )
        return rows

    # ---- the per-pull view ----

    def pull_rows(self) -> list[dict]:
        out = []
        for fid in self.ids:
            st = self.F[fid]["startTime"]
            soaks = defaultdict(list)
            for e in self.taken[fid]:
                if e["abilityGameID"] == S.GLOBULE_SOAK and self.is_player(e["targetID"]):
                    soaks[self.name(e["targetID"])].append(round(self.rel(fid, e["timestamp"]), 1))
            kicks = defaultdict(list)
            for r in self.rouses:
                if r["fight"] == fid:
                    for a in r["adds"]:
                        if a["kicker"]:
                            kicks[a["kicker"]].append(round(r["t"] + a["kick"], 1))
            bursts = [
                round(r["t"] + a["burst_t"], 1)
                for r in self.rouses
                if r["fight"] == fid
                for a in r["adds"]
                if a["bursts"]
            ]
            fed = defaultdict(list)
            for e in self.debuffs[fid]:
                if e["abilityGameID"] == S.FEASTED and e["type"] == "applydebuff":
                    fed[self.name(e["targetID"])].append(round(self.rel(fid, e["timestamp"]), 1))
            w = self.wipe[fid]
            hp = self.boss_hp[fid]
            out.append(
                {
                    "pull": self.pull_no[fid],
                    "dur": round(self.dur(fid), 1),
                    "pct": self.F[fid]["fightPercentage"],
                    "vex": hp.get("Vexhul"),
                    "ith": hp.get("Ithraz"),
                    "kill": bool(self.F[fid].get("kill")),
                    "wipe": w and round(self.rel(fid, w), 1),
                    "wipe_cause": self.wipe_cause(fid),
                    "rouses": sum(1 for t in self.casts(fid, S.ROUSE) if t < self.cut(fid)),
                    "marks": self.marks(fid),
                    "deaths": [{k: d[k] for k in ("t", "player", "group", "why", "ev")} for d in self.deaths[fid]],
                    "soaks": dict(soaks),
                    "kicks": dict(kicks),
                    "fed": dict(fed),
                    "bursts": bursts,
                    "booms": [round(self.rel(fid, b), 1) for b in self.explosions(fid)],
                    "roster": sorted(self.present[fid]),
                }
            )
        return out
