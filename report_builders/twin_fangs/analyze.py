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
from functools import cached_property

from . import spells as S
from .fetch import Fetcher

CASCADE_N = 4  # deaths ...
CASCADE_S = 8.0  # ... inside this many seconds start the wipe
BURST_CLUSTER_MS = 600  # globule explosion hits closer than this are one explosion
WAVE_S = 20.0  # a globule wave's window after Blood Torrent
WAVE_MIN_S = 10.0  # a wave cut off sooner than this by the wipe is not counted
FEAST_S = 15.0  # Feast plus its founts
ROUSE_S = 25.0  # a Rouse's window: every Broodling has surfaced and cast by then
EMERGE_S = 25.0

# killing ability -> death group
DEATH_GROUP = {
    "Visceral Burst": "burst",
    "Tainted Burst": "tainted",
    "Ravenous Feast": "feast",
    "Eternal Venom": "venom",
    "Caustic Globule": "globule",
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
    "venom": "Eternal Venom stacks",
    "globule": "Caustic Globule",
    "waves": "Stir the Depths waves",
    "snakes": "snakes",
    "ichor": "Coiling Ichor",
    "stone": "Stone Breaker",
    "tank": "tank damage",
    "flood": "Vile Flood",
    "attrition": "Toxic Fumes / attrition",
    "other": "other",
}


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


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

    def death_group(self, fid, pid, ts, killer) -> tuple[str, str | None]:
        name = self.ab.get(killer) if killer else None
        if name not in AMBIENT:
            return DEATH_GROUP.get(name, "other"), name
        # the biggest non-ambient hit in the five seconds before
        best, bname = 0, None
        for e in self.taken_by_player[(fid, pid)]:
            if ts - 5000 <= e["timestamp"] <= ts:
                n = self.ab.get(e["abilityGameID"])
                amt = e.get("amount", 0) + e.get("absorbed", 0)
                if n not in AMBIENT and n != "Eternal Venom" and n in DEATH_GROUP and amt > best:
                    best, bname = amt, n
        if bname:
            return DEATH_GROUP[bname], f"{name or 'killing blow'} after {bname}"
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
                        "ev": self.stack_at(fid, pid, d["timestamp"]),
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

    def alive(self, fid, name, ts) -> bool:
        return not any(d["player"] == name and d["ts"] <= ts for d in self.deaths[fid])

    def wipe_cause(self, fid) -> str | None:
        w = self.wipe[fid]
        if w is None:
            return None
        c = Counter(d["group"] for d in self.deaths[fid] if w <= d["ts"] <= w + CASCADE_S * 1000)
        return c.most_common(1)[0][0]

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
        for (fid, pid), series in self.stacks.items():
            prev = 0
            hits = self.taken_by_player[(fid, pid)]
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
                # not every globule gets a shield, so globules are counted off the drops
                drops = sum(
                    1
                    for e in self.enemy_casts[fid]
                    if e["abilityGameID"] == S.GLOBULE_DROP and e["type"] == "cast" and w <= e["timestamp"] < w + 15000
                )
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

            for t in self.casts(fid, S.FEAST):
                if t >= cut:
                    break
                end = t + FEAST_S * 1000
                fed = [
                    e
                    for e in deb
                    if e["abilityGameID"] == S.FEASTED and e["type"] == "applydebuff" and t <= e["timestamp"] < end
                ]
                # the three smashes
                hits = []
                for e in sorted(fed, key=lambda e: e["timestamp"]):
                    if hits and e["timestamp"] - hits[-1][0] < 1000:
                        hits[-1][1].append(self.name(e["targetID"]))
                    else:
                        hits.append([e["timestamp"], [self.name(e["targetID"])]])
                tburst = [
                    e["timestamp"]
                    for e in self.taken[fid]
                    if self.ab.get(e["abilityGameID"]) == "Tainted Burst" and t <= e["timestamp"] < end + 5000
                ]
                into = Counter()
                for h in heals.get(fid, []):
                    if not (t <= h["timestamp"] < end + 5000) or not h.get("absorbed"):
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
                        "hits": [{"t": round(self.rel(fid, a), 1), "who": w} for a, w in hits],
                        "soakers": sorted({n for _, w in hits for n in w}),
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
    def kick_spell(self) -> dict[str, int]:
        """Each kicker's interrupt, the one they used most this night."""
        c = defaultdict(Counter)
        for e in self.ev("casts", "Casts", hostility="Friendlies"):
            if e["type"] == "cast" and e["abilityGameID"] in S.KICK_CD and e.get("fight") in self.F:
                who = self.name(self.owner(e["sourceID"]))
                if who in self.roles:
                    c[who][e["abilityGameID"]] += 1
        return {n: cc.most_common(1)[0][0] for n, cc in c.items()}

    @cached_property
    def kick_uses(self) -> dict[tuple[int, str], list[float]]:
        out = defaultdict(list)
        for e in self.ev("casts", "Casts", hostility="Friendlies"):
            if e["type"] == "cast" and e["abilityGameID"] in S.KICK_CD and e.get("fight") in self.F:
                who = self.name(self.owner(e["sourceID"]))
                if who in self.kick_spell and e["abilityGameID"] == self.kick_spell[who]:
                    out[(e["fight"], who)].append(e["timestamp"])
        return out

    def kick_ready(self, fid, who, ts) -> bool:
        cd = S.KICK_CD[self.kick_spell[who]] * 1000
        return not any(ts - cd < u <= ts for u in self.kick_uses.get((fid, who), []))

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
                first = {}
                bursts = defaultdict(list)
                for e in ec:
                    if not (r <= e["timestamp"] < end):
                        continue
                    k = e.get("sourceInstance", 1)
                    if e["type"] == "begincast":
                        first.setdefault(k, e["timestamp"])
                    elif e["type"] == "cast" and e["abilityGameID"] == S.VISCERAL_BURST:
                        bursts[k].append(e["timestamp"])
                kicked = {}
                for e in kicks.get(fid, []):
                    if r <= e["timestamp"] < end and e.get("targetID") == bid:
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
                            "ready": ready,
                        }
                    )
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
                        "ended": bool(w and r <= w < end + 5000),
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
            side = Counter(a["spot"][0] for a in ks if a["spot"] != "?")
            top_spot, top_n = spots.most_common(1)[0] if spots else ("?", 0)
            known = sum(spots.values())
            spot_share = top_n / known if known else 0
            side_share = side.most_common(1)[0][1] / known if known else 0
            med = statistics.median(ranks) if ranks else None
            spread = (statistics.pstdev(ranks) if len(ranks) > 1 else 0) if ranks else None
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
                label = "filler, anywhere"
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
                end = t + EMERGE_S * 1000
                hits = [e for e in self.done[fid] if e.get("targetID") == sid and t <= e["timestamp"] < end]
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
