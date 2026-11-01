"""Turn one Warcraft Logs report into every number the Sszorak page shows.

The fight, as the Mythic log tells it:

- **Two damage phases a cycle, then Dig In.** Each phase one runs two Apex
  Predator combos (five tank casts each: two Ravage, two Mutilate, one Tempest),
  and each combo is followed by a Serpent's Fury pop, a Venomous Surge and a set
  of Raging Crosswinds. After the second set Sszorak casts Dig In and the
  intermission (phase 2 in the log) runs about 25 seconds.
- **Tempest** throws tornadoes that roam the room for most of the next minute.
  A tornado hit is a Tempest damage event without the tick flag; the ticks after
  it are the DoT it leaves.
- **Serpent's Fury** marks a player; fourteen have to stand in the circle before
  the boss reaches 100 rage. Everyone who soaked gets one of the two Virulence
  debuffs, so the soak count is read off those. A miss is Unbound Ferocity on the
  boss, and the raid does not survive it.
- **Venomous Surge** marks two players; when it runs out each drops a Viscous
  Cyst. Touching a cyst pops it: everyone near is knocked back and takes the
  cyst's DoT. In the intermission the raid pops them on purpose to ride the
  winds; in phase one a pop is an accident.
- **Raging Crosswinds** knocks eight players up along one of four arrows; two
  players with opposite arrows who meet cancel each other. Turbulent Gusts is
  the knock itself, and a cancelled one drops inside a second.
- **The edge.** The platform is about 60 yards across from the middle (no
  player who was still alive fifteen seconds later was ever logged past ~69).
  A fall leaves no killing blow, so a death whose last seconds run past
  `EDGE` yards is read as a fall and blamed on whatever moved the player there.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections import Counter, defaultdict

from . import spells as S
from .fetch import Fetcher

EDGE = 65  # yards from the middle; past this a player is off the platform
EDGE_LOOKBACK = 8_000  # ms before death in which a fall must have gone past EDGE
CAUSE_LOOKBACK = 7_000  # ms before leaving the platform in which a knock is blamed
FLUNG_MS = 1_500  # Turbulent Gusts longer than this: the knock-up was not cancelled
POP_GAP = 400  # ms; cyst knock hits this close are one cyst popping
TORNADO_GAP = 1_000  # ms; tornado hits on one player this close are one hit
CALL_WINDOW = 10_000  # ms; this many unforced falls inside it is a called wipe
CALL_FALLS = 3
# Hard minimum: fourteen beside the marked player, fifteen bodies in all. The log
# backs this: no pop went off with fewer than fifteen in the circle once a Beast
# Mastery pet (it stands in, but never gets Virulence) is counted, and pull 29
# sat on fourteen players for over a minute without popping.
FURY_NEED = 15
SAME_EVENT = 3_000  # ms; deaths this soon after going under were the same blow
# Battle resurrection: one charge at the pull and one more every 90/N minutes
# (4.5 minutes for twenty). Reincarnation is the shaman's own and costs nothing.
BREZ = {20484, 391054, 61999, 20707}  # Rebirth, Intercession, Raise Ally, Soulstone
SELF_RES = {21169}  # Reincarnation
BREZ_EVERY = 270_000
# Classes whose kit has no movement ability that cancels the Crosswinds knock-up;
# everyone else can solo it, so only these two depend on a partner.
NEEDS_PARTNER = {"Paladin", "Priest"}
# Movement that cancels the knock-up, and how soon after it has to be pressed (ms).
SOLO_MOVES = {
    "Shimmer", "Blink", "Alter Time", "Demonic Circle: Teleport", "Shadowstep", "Fel Rush",
    "Vengeful Retreat", "Glide", "Disengage", "Roll", "Chi Torpedo", "Charge", "Heroic Leap",
    "Intervene", "Shield Charge", "Wild Charge", "Feral Lunge", "Gust of Wind", "Burning Rush",
}
SOLO_WINDOW = (-500, 1_500)


def _hyp(dx: float, dy: float) -> float:
    return math.hypot(dx, dy) / 100  # the log's coordinates are hundredths of a yard


class Analysis:
    def __init__(
        self,
        code: str,
        encounter_id: int | None = None,
        difficulty: int | None = None,
        cache_root=None,
    ) -> None:
        self.f = Fetcher(code, cache_root)
        self.code = code
        self.meta = self.f.fights()
        enc = encounter_id or S.ENCOUNTER
        fights = [x for x in self.meta["fights"] if x.get("encounterID") == enc]
        if difficulty is None:
            difficulty = max(x["difficulty"] for x in fights)
        self.difficulty = difficulty
        self.fights = [x for x in fights if x["difficulty"] == difficulty]
        self.ids = [x["id"] for x in self.fights]
        self.F = {x["id"]: x for x in self.fights}
        self.actors = {a["id"]: a for a in self.f.actors()}
        self.abil = {a["gameID"]: a["name"] for a in self.f.abilities()}

        pd = self.f.player_details(self.ids)
        pd = pd.get("data", pd)
        pd = pd.get("playerDetails", pd)
        self.roles: dict[str, str] = {}
        self.cls: dict[str, str] = {}
        self.spec: dict[str, str] = {}
        for role, key in (("tank", "tanks"), ("healer", "healers"), ("dps", "dps")):
            for p in pd.get(key, []):
                self.roles[p["name"]] = role
                self.cls[p["name"]] = p["type"]
                self.spec[p["name"]] = (p.get("specs") or [{}])[0].get("spec", "")
        self.players = sorted(self.roles)

        def grouped(key, dt, **kw):
            out = defaultdict(list)
            for e in self.f.events(key, self.ids, dt, **kw):
                out[e["fight"]].append(e)
            return out

        self._taken = grouped("damage_taken_res", "DamageTaken", hostility="Friendlies", resources=True)
        self._debuffs = grouped("debuffs", "Debuffs", hostility="Friendlies")
        self._ecasts = grouped("enemy_casts", "Casts", hostility="Enemies")
        self._ebuffs = grouped("enemy_buffs", "Buffs", hostility="Enemies")
        self._deaths = grouped("deaths", "Deaths", hostility="Friendlies")
        self._pcasts = grouped("casts", "Casts", hostility="Friendlies")
        self.center = self._center()
        self._memo: dict = {}

    # ---- helpers ----

    def name(self, actor_id) -> str | None:
        a = self.actors.get(actor_id)
        return a["name"] if a else None

    def rel(self, fid: int, ts: float) -> float:
        return (ts - self.F[fid]["startTime"]) / 1000

    def dur(self, fid: int) -> float:
        return (self.F[fid]["endTime"] - self.F[fid]["startTime"]) / 1000

    def pull_no(self, fid: int) -> int:
        return self.ids.index(fid) + 1

    def _center(self) -> tuple[float, float]:
        """Middle of the platform: the midpoint of the 1st and 99th percentile of
        every position the log holds for a player, in each axis."""
        xs, ys = [], []
        for evs in self._taken.values():
            for e in evs:
                if e.get("resourceActor") == 2 and "x" in e:
                    xs.append(e["x"])
                    ys.append(e["y"])
        xs.sort()
        ys.sort()
        n = len(xs)
        return (xs[n // 100] + xs[-n // 100]) / 2, (ys[n // 100] + ys[-n // 100]) / 2

    def radius(self, e: dict) -> float:
        return _hyp(e["x"] - self.center[0], e["y"] - self.center[1])

    def track(self, fid: int) -> dict[str, list[tuple[float, float, float, float]]]:
        """Per player: (timestamp, radius, hp fraction, x, y) from every hit they took."""
        key = ("track", fid)
        if key not in self._memo:
            out = defaultdict(list)
            for e in self._taken[fid]:
                if e.get("type") != "damage" or e.get("resourceActor") != 2 or "x" not in e:
                    continue
                n = self.name(e["targetID"])
                hp = e["hitPoints"] / e["maxHitPoints"] if e.get("maxHitPoints") else None
                out[n].append((e["timestamp"], self.radius(e), hp, e["x"], e["y"]))
            for v in out.values():
                v.sort()
            self._memo[key] = out
        return self._memo[key]

    def hits(self, fid: int, ability: int, *, tick: bool | None = None) -> list[dict]:
        out = []
        for e in self._taken[fid]:
            if e.get("type") != "damage" or e["abilityGameID"] != ability:
                continue
            if tick is not None and bool(e.get("tick")) != tick:
                continue
            out.append(e)
        return out

    def debuff_events(self, fid: int, ability, types=("applydebuff",)) -> list[dict]:
        ab = {ability} if isinstance(ability, int) else set(ability)
        return [e for e in self._debuffs[fid] if e["abilityGameID"] in ab and e["type"] in types]

    def casts(self, fid: int, ability: int) -> list[float]:
        return sorted(
            e["timestamp"] for e in self._ecasts[fid] if e["abilityGameID"] == ability and e["type"] == "cast"
        )

    # ---- the clock ----

    def segments(self, fid: int) -> list[tuple[str, float, float]]:
        """('p1' | 'inter', start, end) in report ms."""
        f = self.F[fid]
        tr = f.get("phaseTransitions") or [{"id": 1, "startTime": f["startTime"]}]
        out = []
        for i, p in enumerate(tr):
            end = tr[i + 1]["startTime"] if i + 1 < len(tr) else f["endTime"]
            out.append(("inter" if p["id"] == 2 else "p1", p["startTime"], end))
        return out

    def in_inter(self, fid: int, ts: float) -> bool:
        return any(k == "inter" and a <= ts < b for k, a, b in self.segments(fid))

    def enrage_at(self, fid: int) -> float | None:
        ts = [
            e["timestamp"]
            for e in self._ebuffs[fid]
            if e["abilityGameID"] == S.UNBOUND_FEROCITY and e["type"] == "applybuff"
        ]
        return min(ts) if ts else None

    # ---- mechanics ----

    def cyst_pops(self, fid: int) -> list[dict]:
        """Each cyst going off: the knock hits (no tick flag) clustered in time."""
        key = ("pops", fid)
        if key in self._memo:
            return self._memo[key]
        hits = sorted(self.hits(fid, S.VISCOUS_CYST, tick=False), key=lambda e: e["timestamp"])
        pops: list[list[dict]] = []
        for e in hits:
            if pops and e["timestamp"] - pops[-1][-1]["timestamp"] <= POP_GAP:
                pops[-1].append(e)
            else:
                pops.append([e])
        out = [
            {
                "t": p[0]["timestamp"],
                "hit": sorted({self.name(e["targetID"]) for e in p}),
                "inter": self.in_inter(fid, p[0]["timestamp"]),
            }
            for p in pops
        ]
        self._memo[key] = out
        return out

    def knocks(self, fid: int) -> list[dict]:
        """Every Crosswinds knock-up: who, when, how long they were airborne."""
        key = ("knocks", fid)
        if key in self._memo:
            return self._memo[key]
        open_: dict[int, float] = {}
        out = []
        for e in sorted(self._debuffs[fid], key=lambda x: x["timestamp"]):
            if e["abilityGameID"] != S.TURBULENT_GUSTS:
                continue
            if e["type"] == "applydebuff":
                open_[e["targetID"]] = e["timestamp"]
            elif e["type"] == "removedebuff" and e["targetID"] in open_:
                a = open_.pop(e["targetID"])
                out.append({"t": a, "player": self.name(e["targetID"]), "air": e["timestamp"] - a})
        for tid, a in open_.items():  # died in the air
            out.append({"t": a, "player": self.name(tid), "air": None})
        out.sort(key=lambda k: k["t"])
        self._memo[key] = out
        return out

    def moves(self, fid: int) -> dict[str, list[tuple[float, str]]]:
        key = ("moves", fid)
        if key not in self._memo:
            out = defaultdict(list)
            for e in self._pcasts[fid]:
                ab = self.abil.get(e["abilityGameID"])
                if e["type"] == "cast" and ab in SOLO_MOVES:
                    out[self.name(e["sourceID"])].append((e["timestamp"], ab))
            self._memo[key] = out
        return self._memo[key]

    def crosswind_knocks(self, fid: int) -> list[dict]:
        """Every marked player's knock-up, and how it ended:
        solo (cancelled with their own movement), cancelled (by a partner or
        otherwise), late (flung, movement pressed too late), none (flung, no
        movement pressed), partner (flung, and the class has no solo answer)."""
        mv = self.moves(fid)
        out = []
        for s in self.crosswind_sets(fid):
            for k in self.knocks(fid):
                n = k["player"]
                if n not in s["marked"] or not 0 <= k["t"] - s["t"] <= 15_000:
                    continue
                flung = k["air"] is None or k["air"] > FLUNG_MS
                own = [(t - k["t"], ab) for t, ab in mv.get(n, []) if -500 <= t - k["t"] <= 4_000]
                quick = [o for o in own if SOLO_WINDOW[0] <= o[0] <= SOLO_WINDOW[1]]
                if not flung:
                    how = "solo" if quick else "cancelled"
                elif self.cls.get(n) in NEEDS_PARTNER:
                    how = "partner"
                elif own:
                    how = "late"
                else:
                    how = "none"
                out.append({"t": k["t"], "set": s["t"], "player": n, "how": how, "flung": flung,
                            "move": (quick or own or [(None, None)])[0][1]})
        return out

    def crosswind_sets(self, fid: int) -> list[dict]:
        """One row per Crosswinds set: the eight marked, and which were flung."""
        marks = sorted(self.debuff_events(fid, S.CROSSWINDS_DEBUFFS), key=lambda e: e["timestamp"])
        sets: list[dict] = []
        for e in marks:
            if not sets or e["timestamp"] - sets[-1]["t"] > 5_000:
                sets.append({"t": e["timestamp"], "marked": []})
            sets[-1]["marked"].append(self.name(e["targetID"]))
        kn = self.knocks(fid)
        for s in sets:
            mine = [k for k in kn if 0 <= k["t"] - s["t"] <= 15_000]
            s["knocked"] = [k["player"] for k in mine]
            s["flung"] = [k["player"] for k in mine if k["air"] is None or k["air"] > FLUNG_MS]
        return sets

    def tornado_hits(self, fid: int) -> list[dict]:
        """Tornado hits, one per player per second (a tornado can tag twice as it
        passes), each tied to the Tempest cast before it."""
        casts = self.casts(fid, S.TEMPEST_CAST)
        last: dict[str, float] = {}
        out = []
        for e in sorted(self.hits(fid, S.TEMPEST, tick=False), key=lambda x: x["timestamp"]):
            n = self.name(e["targetID"])
            if n in last and e["timestamp"] - last[n] < TORNADO_GAP:
                continue
            last[n] = e["timestamp"]
            i = bisect.bisect_right(casts, e["timestamp"] + 500) - 1
            out.append({"t": e["timestamp"], "player": n, "cast": i, "since": (e["timestamp"] - casts[i]) / 1000 if i >= 0 else None})
        return out

    def fury_pops(self, fid: int) -> list[dict]:
        """Each Serpent's Fury pop and how many stood in it."""
        drops = sorted(
            e["timestamp"] for e in self.debuff_events(fid, S.SERPENTS_FURY, ("removedebuff",))
        )
        vir = sorted(
            (e["timestamp"], self.name(e["targetID"]))
            for e in self.debuff_events(fid, S.VIRULENCE_DEBUFFS)
        )
        out = []
        deaths = sorted((d["timestamp"], self.name(d["targetID"])) for d in self._deaths[fid])
        for t in drops:
            soak = {n for ts, n in vir if 0 <= ts - t <= 1_500}
            if not soak:  # the mark moving on with the player's death, or the pull ending
                continue
            # the plan: every dps and both tanks stand in; healers only cover a dead one
            dead = {n for ts, n in deaths if ts < t}
            assigned = {n for n, r in self.roles.items() if r != "healer"}
            heal = sorted(n for n in soak if self.roles.get(n) == "healer")
            n_dead = len(assigned & dead)
            out.append(
                {
                    "t": t,
                    "soakers": len(soak),
                    "missing": sorted(assigned - dead - soak),
                    "healers": heal,
                    "assigned_dead": n_dead,
                    # healers beyond the dead dps/tanks they were covering
                    "extra_healers": max(0, len(heal) - n_dead),
                }
            )
        # second-hand Virulence: a line clipping someone after the soak
        clipped = []
        for ts, n in vir:
            if not any(0 <= ts - p["t"] <= 1_500 for p in out):
                clipped.append({"t": ts, "player": n})
        return out, clipped

    def mutilate(self, fid: int) -> list[dict]:
        """Mutilate soaks; a soaker already carrying Mutilated Gash soaked out of turn."""
        casts = self.casts(fid, S.MUTILATE_CAST)
        gash: dict[str, list[tuple[float, float]]] = defaultdict(list)
        open_: dict[str, float] = {}
        for e in sorted(self._debuffs[fid], key=lambda x: x["timestamp"]):
            if e["abilityGameID"] != S.MUTILATED_GASH_DEBUFF:
                continue
            n = self.name(e["targetID"])
            if e["type"] == "applydebuff":
                open_[n] = e["timestamp"]
            elif e["type"] == "removedebuff" and n in open_:
                gash[n].append((open_.pop(n), e["timestamp"]))
        for n, a in open_.items():
            gash[n].append((a, float("inf")))
        out = []
        hits = self.hits(fid, S.MUTILATE_HIT)
        for c in casts:
            mine = [e for e in hits if 0 <= e["timestamp"] - c <= 3_000]
            names = sorted({self.name(e["targetID"]) for e in mine})
            dbl = [n for n in names if any(a < c and b > c for a, b in gash.get(n, []))]
            out.append({"t": c, "soakers": names, "double": dbl})
        return out

    # ---- deaths ----

    def deaths(self, fid: int) -> list[dict]:
        key = ("deaths", fid)
        if key in self._memo:
            return self._memo[key]
        tr = self.track(fid)
        pops = self.cyst_pops(fid)
        kn = self.knocks(fid)
        enr = self.enrage_at(fid)
        out = []
        for d in sorted(self._deaths[fid], key=lambda x: x["timestamp"]):
            n = self.name(d["targetID"])
            if n not in self.roles:
                continue
            T = d["timestamp"]
            kab = d.get("killingAbilityGameID")
            path = [p for p in tr.get(n, []) if T - EDGE_LOOKBACK <= p[0] <= T]
            before = [p for p in tr.get(n, []) if p[0] <= T]
            hp = before[-1][2] if before else None
            rmax = max((p[1] for p in path), default=0)
            row = {"t": T, "player": n, "kab": kab, "hp": hp, "rmax": rmax, "inter": self.in_inter(fid, T)}
            if rmax >= EDGE and (not kab or kab in (S.FALLING, S.ULATEKS_PRESENCE)):
                # the moment they left the platform
                out_t = next((p[0] for p in path if p[1] >= 60), T)
                knock = [k for k in kn if k["player"] == n and 0 <= out_t - k["t"] <= CAUSE_LOOKBACK]
                pop = [p for p in pops if n in p["hit"] and 0 <= out_t - p["t"] <= CAUSE_LOOKBACK]
                if self.in_inter(fid, out_t):
                    cause = "edge_inter"
                elif knock and (not pop or knock[-1]["t"] >= pop[-1]["t"]):
                    cause = "edge_crosswinds"
                elif pop:
                    cause = "edge_cyst"
                else:
                    cause = "edge_walk"
                row["edge_out"] = out_t
            else:
                ab = kab
                if not ab:  # a DoT finished them: the last thing that hit them
                    last = [e for e in self._taken[fid] if e.get("targetID") == d["targetID"] and e["timestamp"] <= T and e.get("type") == "damage"]
                    last.sort(key=lambda e: e["timestamp"])
                    # skip their own self-damage and the rot to find the mechanic
                    for e in reversed(last[-8:]):
                        if e["abilityGameID"] in S.DEATH_GROUPS and e["abilityGameID"] != S.ULATEKS_PRESENCE:
                            ab = e["abilityGameID"]
                            break
                    row["dot"] = True
                cause = S.DEATH_GROUPS.get(ab, "other")
                row["ab"] = ab
            if enr and T >= enr:
                cause = "enrage"
            row["cause"] = cause
            out.append(row)
        # the call: the first of CALL_FALLS unforced falls inside CALL_WINDOW
        walks = [r["t"] for r in out if r["cause"] == "edge_walk"]
        called = None
        for i in range(len(walks) - CALL_FALLS + 1):
            if walks[i + CALL_FALLS - 1] - walks[i] <= CALL_WINDOW:
                called = walks[i]
                break
        under = self.under_at(fid)
        for r in out:
            # the death that takes the raid under the number still counts
            r["after_call"] = (called is not None and r["t"] >= called) or (under is not None and r["t"] > under + SAME_EVENT)
        self._memo[key] = out
        self._memo[("called", fid)] = called
        return out

    def alive_curve(self, fid: int) -> list[tuple[float, int, int]]:
        """(timestamp, players alive, battle-res charges ready) after each death or res."""
        key = ("alive", fid)
        if key in self._memo:
            return self._memo[key]
        st = self.F[fid]["startTime"]
        ev = []
        for d in self._deaths[fid]:
            if self.name(d["targetID"]) in self.roles:
                ev.append((d["timestamp"], -1, 0))
        for e in self._pcasts[fid]:
            if e["type"] != "cast":
                continue
            if e["abilityGameID"] in BREZ:
                ev.append((e["timestamp"], +1, 1))
            elif e["abilityGameID"] in SELF_RES:
                ev.append((e["timestamp"], +1, 0))
        ev.sort()
        alive, used, out = len(self.roles), 0, []
        for t, dv, b in ev:
            alive = min(len(self.roles), alive + dv)
            used += b
            charges = max(0, 1 + int((t - st) / BREZ_EVERY) - used)
            out.append((t, alive, charges))
        self._memo[key] = out
        return out

    def under_at(self, fid: int) -> float | None:
        """When the raid could no longer put FURY_NEED in the circle: fewer alive
        than that, counting a ready battle res as one more. The raid called the
        wipe at this point, so everything after it is the reset."""
        for t, alive, charges in self.alive_curve(fid):
            if alive + charges < FURY_NEED:
                return t
        return None

    def alive_at(self, fid: int, ts: float) -> int:
        n = len(self.roles)
        for t, alive, _ in self.alive_curve(fid):
            if t > ts:
                break
            n = alive
        return n

    def called_at(self, fid: int) -> float | None:
        """The end of the part of the pull that counts: under the soak number,
        or (failing that) the raid jumping off to reset."""
        self.deaths(fid)
        cands = [x for x in (self._memo[("called", fid)], self.under_at(fid)) if x is not None]
        return min(cands) if cands else None

    def pulls(self) -> list[dict]:
        rows = []
        for fid in self.ids:
            f = self.F[fid]
            segs = self.segments(fid)
            dts = self.deaths(fid)
            called = self.called_at(fid)
            enr = self.enrage_at(fid)
            under = self.under_at(fid)
            if enr and under is not None and under < enr:
                enr_forced = True  # already under the number: the enrage only finished it
            else:
                enr_forced = False
            cut = min(x for x in (called, enr, f["endTime"]) if x is not None)
            tor = [h for h in self.tornado_hits(fid) if h["t"] < cut]
            pops = [p for p in self.cyst_pops(fid) if p["t"] < cut]
            fury, clipped = self.fury_pops(fid)
            xw = [s for s in self.crosswind_sets(fid) if s["t"] < cut]
            mut = [m for m in self.mutilate(fid) if m["t"] < cut]
            live = [d for d in dts if not d["after_call"] and d["cause"] != "enrage"]
            rows.append(
                {
                    "pull": self.pull_no(fid),
                    "fid": fid,
                    "dur": round(self.dur(fid), 1),
                    "pct": f["fightPercentage"],
                    "inters": sum(1 for k, *_ in segs if k == "inter"),
                    "inters_done": sum(1 for i, (k, *_) in enumerate(segs) if k == "inter" and i + 1 < len(segs)),
                    "called": called and self.rel(fid, called),
                    "enrage": enr and self.rel(fid, enr),
                    "enrage_forced": enr_forced,
                    "under": under and self.rel(fid, under),
                    "tempests": len([c for c in self.casts(fid, S.TEMPEST_CAST) if c < cut]),
                    "tornado_hits": len(tor),
                    "cyst_pops_p1": [p for p in pops if not p["inter"]],
                    "cyst_pops_inter": [p for p in pops if p["inter"]],
                    "fury": [p for p in fury if p["t"] < cut],
                    "clipped": [c for c in clipped if c["t"] < cut],
                    "xw_sets": xw,
                    "mutilate": mut,
                    "deaths": dts,
                    "deaths_live": live,
                    "first_death": live[0] if live else None,
                }
            )
        return rows


# ---- the night, mechanic by mechanic ----------------------------------------

# Deaths folded into the groups the page talks about.
GROUP_OF = {
    "tornado": "tornado",
    "edge_cyst": "cyst_p1",
    "cyst_p1": "cyst_p1",
    "edge_inter": "inter",
    "cyst_inter": "inter",
    "edge_crosswinds": "crosswinds",
    "crosswinds": "crosswinds",
    "virulence": "virulence",
    "mutilate": "mutilate",
    "ravage": "ravage",
    "tank": "tank",
    "surge": "surge",
    "floor": "floor",
    "rot": "other",
    "other": "other",
    "edge_walk": "other",
    "cyst": "cyst_p1",
}
GROUP_LABEL = {
    "tornado": "Tornadoes",
    "cyst_p1": "Cyst popped in phase one",
    "inter": "Intermission (winds and cysts)",
    "crosswinds": "Crosswinds",
    "virulence": "Virulence",
    "mutilate": "Mutilate",
    "ravage": "Ravage frontal",
    "tank": "Tank deaths",
    "surge": "Venomous Surge",
    "floor": "Caustic puddles",
    "other": "Other",
}
PLANNED_AFTER = 10_000  # ms after an intermission ends: the last cyst is popped on purpose


def _planned(a: "Analysis", fid: int, ts: float) -> bool:
    return any(
        k == "inter" and (s <= ts < e or 0 <= ts - e <= PLANNED_AFTER) for k, s, e in a.segments(fid)
    )


def death_group(a: "Analysis", fid: int, d: dict) -> str:
    c = d["cause"]
    if c == "cyst":
        c = "cyst_inter" if _planned(a, fid, d["t"]) else "cyst_p1"
    if c == "edge_cyst" and _planned(a, fid, d["t"]):
        c = "edge_inter"
    if c == "tank" and a.roles.get(d["player"]) != "tank":
        c = "ravage"
    return GROUP_OF.get(c, "other")


def accidental_pops(a: "Analysis", fid: int) -> list[dict]:
    out = []
    drops = sorted(e["timestamp"] for e in a.debuff_events(fid, S.SURGE_DEBUFF, ("removedebuff",)))
    for p in a.cyst_pops(fid):
        if _planned(a, fid, p["t"]):
            continue
        age = [p["t"] - t for t in drops if t <= p["t"]]
        out.append({**p, "age": min(age) / 1000 if age else None})
    return out


def intermissions(a: "Analysis", fid: int) -> list[dict]:
    """Each Dig In: the cysts popped inside it and what it cost."""
    out = []
    dts = a.deaths(fid)
    for k, s, e in a.segments(fid):
        if k != "inter":
            continue
        pops = [p for p in a.cyst_pops(fid) if s <= p["t"] < e]
        gaps = [(pops[i + 1]["t"] - pops[i]["t"]) / 1000 for i in range(len(pops) - 1)]
        died = [d for d in dts if s <= d["t"] < e + 3_000 and not d["after_call"]]
        alive_in = len(a.roles) - sum(1 for d in dts if d["t"] < s)
        finished = e < a.F[fid]["endTime"] - 1_000
        out.append(
            {
                "start": a.rel(fid, s),
                "pops": [round((p["t"] - s) / 1000, 1) for p in pops],
                "double": sum(1 for g in gaps if g < 2),
                "died": len(died),
                "fell": sum(1 for d in died if d["cause"].startswith("edge")),
                "alive_in": alive_in,
                "survived": finished,
            }
        )
    return out


def fury_clock(a: "Analysis", fid: int) -> dict:
    """Pop times, and where the next enrage deadline fell."""
    pops, clipped = a.fury_pops(fid)
    ts = [p["t"] for p in pops]
    enr = a.enrage_at(fid)
    return {
        "pops": [round(a.rel(fid, t), 1) for t in ts],
        "soakers": [p["soakers"] for p in pops],
        "enrage": enr and round(a.rel(fid, enr), 1),
        "enrage_after": enr and ts and round((enr - max(t for t in ts if t < enr)) / 1000, 1),
        "clipped": len(clipped),
        "missing": [len(p["missing"]) for p in pops],
        "extra_healers": [p["extra_healers"] for p in pops],
    }


def night(a: "Analysis") -> list[dict]:
    rows = []
    for p in a.pulls():
        fid = p["fid"]
        live = p["deaths_live"]
        groups = Counter(death_group(a, fid, d) for d in live)
        acc = [x for x in accidental_pops(a, fid) if x["t"] < (a.called_at(fid) or 1e18)]
        sets = p["xw_sets"]
        flung = [len([n for n in s["flung"] if n in s["marked"]]) for s in sets if len(s["marked"]) >= 6]
        ravage_raid = [
            e for e in a.hits(fid, S.RAVAGE_HIT) if a.roles.get(a.name(e["targetID"])) != "tank"
        ]
        cut = min(x for x in (a.called_at(fid), a.enrage_at(fid), a.F[fid]["endTime"]) if x)
        ravage_raid = [e for e in ravage_raid if e["timestamp"] < cut]
        # what ended it: the enrage, or the mechanic behind most of the deaths
        # in the 20 seconds before the pull broke
        if p["enrage"] is not None and not p["enrage_forced"]:
            ended = "enrage"
        else:
            # the mechanic behind most of the deaths in the 20 seconds that
            # took the raid under the number (or before it broke otherwise)
            tail = [d for d in live if cut - d["t"] <= 20_000]
            c = Counter(death_group(a, fid, d) for d in tail)
            ended = c.most_common(1)[0][0] if c else "other"
        rows.append(
            {
                "pull": p["pull"],
                "dur": p["dur"],
                "pct": p["pct"],
                "inters": p["inters"],
                "inters_done": p["inters_done"],
                "called": p["called"],
                "enrage": p["enrage"],
                "enrage_forced": p["enrage_forced"],
                "under": p["under"],
                "walked": a._memo[("called", fid)] is not None
                and (a.under_at(fid) is None or a._memo[("called", fid)] < a.under_at(fid)),
                "ended": ended,
                "tempests": p["tempests"],
                "tornado_hits": p["tornado_hits"],
                "acc_pops": len(acc),
                "acc_hit": sum(len(x["hit"]) for x in acc),
                "acc_fresh": sum(1 for x in acc if x["age"] is not None and x["age"] <= 10),
                "xw_sets": len(flung),
                "xw_flung": sum(flung),
                **{
                    f"xw_{h}": sum(1 for k in a.crosswind_knocks(fid) if k["set"] < cut and k["how"] == h)
                    for h in ("solo", "cancelled", "late", "none", "partner")
                },
                "fury": fury_clock(a, fid),
                "inter": intermissions(a, fid),
                "mut_double": sum(len(m["double"]) for m in p["mutilate"]),
                "ravage_raid": len(ravage_raid),
                "deaths": dict(groups),
                "deaths_live": len(live),
                "first": p["first_death"]
                and {
                    "t": round(a.rel(fid, p["first_death"]["t"]), 1),
                    "player": p["first_death"]["player"],
                    "group": death_group(a, fid, p["first_death"]),
                },
            }
        )
    return rows


def players(a: "Analysis") -> list[dict]:
    """Per player, over the part of each pull before it was called or enraged."""
    st = {
        n: Counter() for n in a.players
    }
    groups = {n: Counter() for n in a.players}
    for fid in a.ids:
        cut = min(x for x in (a.called_at(fid), a.enrage_at(fid), a.F[fid]["endTime"]) if x)
        dts = a.deaths(fid)
        died = {d["player"]: d["t"] for d in reversed(dts)}  # first death per player
        tcasts = [c for c in a.casts(fid, S.TEMPEST_CAST) if c < cut]
        for n in a.players:
            end = min(died.get(n, 1e18), cut)
            st[n]["tempests"] += sum(1 for c in tcasts if c < end)
            st[n]["alive_s"] += max(0, (end - a.F[fid]["startTime"]) / 1000)
        for h in a.tornado_hits(fid):
            if h["t"] < cut and h["player"] in st:
                st[h["player"]]["tornado"] += 1
        for k in a.crosswind_knocks(fid):
            if k["set"] >= cut or k["player"] not in st:
                continue
            st[k["player"]]["xw_marked"] += 1
            st[k["player"]]["xw_" + k["how"]] += 1
            if k["flung"]:
                st[k["player"]]["xw_flung"] += 1
        for pop in a.fury_pops(fid)[0]:
            if pop["t"] >= cut:
                continue
            for n in pop["missing"]:
                if n in st:
                    st[n]["fury_missed"] += 1
            if pop["extra_healers"]:
                for n in pop["healers"]:
                    st[n]["fury_extra"] += 1
            for n in pop["healers"]:
                st[n]["fury_in"] += 1

        for c in a.fury_pops(fid)[1]:
            if c["t"] < cut and c["player"] in st:
                st[c["player"]]["clipped"] += 1
        for e in a.hits(fid, S.RAVAGE_HIT):
            n = a.name(e["targetID"])
            if e["timestamp"] < cut and a.roles.get(n) != "tank" and n in st:
                st[n]["ravage"] += 1
        for d in dts:
            if d["after_call"] or d["cause"] == "enrage":
                continue
            st[d["player"]]["deaths"] += 1
            groups[d["player"]][death_group(a, fid, d)] += 1
    out = []
    for n in a.players:
        s = st[n]
        out.append(
            {
                "player": n,
                "role": a.roles[n],
                "cls": a.cls[n],
                "spec": a.spec[n],
                "tornado": s["tornado"],
                "tempests": s["tempests"],
                "tornado_rate": round(s["tornado"] / s["tempests"], 2) if s["tempests"] else 0,
                "xw_marked": s["xw_marked"],
                "xw_flung": s["xw_flung"],
                "xw_solo": s["xw_solo"],
                "xw_cancelled": s["xw_cancelled"],
                "xw_late": s["xw_late"],
                "xw_none": s["xw_none"],
                "xw_partner": s["xw_partner"],
                "fury_missed": s["fury_missed"],
                "fury_in": s["fury_in"],
                "fury_extra": s["fury_extra"],
                "clipped": s["clipped"],
                "ravage": s["ravage"],
                "deaths": s["deaths"],
                "alive_min": round(s["alive_s"] / 60, 1),
                "groups": dict(groups[n]),
            }
        )
    return out
