"""The numbers behind the Mythic Coiled Altar page.

Sections, in page order:

  pulls       how far each pull got and where its wipe started
  axes        spinning axes eaten, per pull and per player, P1 and P2 apart
  orbs        who carried the green and the purple orbs, and the explosions
  guillotine  soakers per Guillotine, the misses and the deaths
  frontals    deaths to Sever / Soul Sever / Blighted Sever
  veil        the P2/P3 shield burn, per window and per player
  adds        damage into the Soulcoiler, before and after its shield

The paging, caching, roster and phase helpers come from the heroic builder.
"""

from __future__ import annotations

import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from functools import cached_property

from report_builders.coiled_altar.analyze import Analysis as _Base

from . import spells as S


def _amount(e: dict) -> float:
    return (e.get("amount") or 0) + (e.get("absorbed") or 0)


class Analysis(_Base):
    # ---- the pulls -------------------------------------------------------

    @cached_property
    def num(self) -> dict[int, int]:
        """Fight id -> pull number within the boss (1..n)."""
        return {x["id"]: i + 1 for i, x in enumerate(self.fights)}

    @cached_property
    def F(self) -> dict[int, dict]:
        return {x["id"]: x for x in self.fights}

    def ids_of(self, *names: str) -> set[int]:
        out: set[int] = set()
        for n in names:
            out |= self.ids_named(n)
        return out

    @cached_property
    def deaths(self) -> dict[int, list[dict]]:
        """Player deaths per pull: {ts, player, ability}."""
        out = {}
        for fid in self.F:
            L = []
            for e in self.stream("deaths", fid):
                if e.get("type") != "death" or not self.is_player(e.get("targetID")):
                    continue
                L.append(
                    {
                        "ts": e["timestamp"],
                        "player": self.name(e["targetID"]),
                        "ability": self.abilities.get(e.get("killingAbilityGameID"), ""),
                    }
                )
            out[fid] = sorted(L, key=lambda d: d["ts"])
        return out

    @cached_property
    def reset(self) -> set[int]:
        """Pulls being reset: short, with Malacrass's Unworthy on them."""
        ids = self.ids_named(S.RESET)
        out = set()
        for fid, x in self.F.items():
            short = (x["endTime"] - x["startTime"]) / 1000 <= S.RESET_MAX_SEC
            hit = any(e.get("abilityGameID") in ids for e in self.stream("taken", fid))
            if short and hit:
                out.add(fid)
        return out

    @cached_property
    def wipe(self) -> dict[int, float | None]:
        out = {}
        for fid in self.F:
            ts = [d["ts"] for d in self.deaths[fid]]
            end = self.F[fid]["endTime"]
            start = None
            for i, t in enumerate(ts):
                if bisect_right(ts, t + S.CASCADE_S * 1000) - i < S.CASCADE_N:
                    continue
                # A cluster the raid plays on through is not the wipe: on this
                # boss four can die to one frontal or one soak and the pull
                # carries on for minutes. It is the wipe only if the deaths keep
                # coming, no quiet stretch of RECOVER_S, until the pull ends.
                rest = ts[i:] + [end]
                if all(b - a < S.RECOVER_S * 1000 for a, b in zip(rest, rest[1:])):
                    start = t
                    break
            out[fid] = None if self.F[fid].get("kill") else start
        return out

    def cut(self, fid) -> float:
        return self.wipe[fid] or self.F[fid]["endTime"]

    @cached_property
    def _cast_times(self) -> dict[tuple[int, str], list[float]]:
        out = defaultdict(list)
        for fid in self.F:
            for e in self.stream("player_casts", fid):
                if self.is_player(e.get("sourceID")):
                    out[(fid, self.name(e["sourceID"]))].append(e["timestamp"])
        for v in out.values():
            v.sort()
        return out

    @cached_property
    def dead_spans(self) -> dict[tuple[int, str], list[tuple[float, float]]]:
        """A battle rez shows up as the player casting again."""
        out = defaultdict(list)
        for fid in self.F:
            for d in self.deaths[fid]:
                casts = self._cast_times.get((fid, d["player"]), [])
                i = bisect_right(casts, d["ts"] + 500)
                out[(fid, d["player"])].append((d["ts"], casts[i] if i < len(casts) else float("inf")))
        return out

    def alive(self, fid, name, ts) -> bool:
        return not any(a <= ts < b for a, b in self.dead_spans.get((fid, name), []))

    def alive_ms(self, fid, name, lo, hi) -> float:
        """Milliseconds of [lo, hi) the player spent alive."""
        if hi <= lo:
            return 0.0
        dead = sum(max(0.0, min(b, hi) - max(a, lo)) for a, b in self.dead_spans.get((fid, name), []))
        return (hi - lo) - dead

    @cached_property
    def players(self) -> dict[int, list[str]]:
        out = {}
        for fid, x in self.F.items():
            out[fid] = [self.name(i) for i in x.get("friendlyPlayers") or [] if self.is_player(i)]
        return out

    @cached_property
    def pull_roles(self) -> dict[int, dict[str, tuple[str, str]]]:
        """Fight id -> name -> (role, spec) for that pull alone.

        A player can swap spec mid-night (a balance druid going resto), so the
        night's single roster role is wrong for some of their pulls. Warcraft
        Logs' playerDetails per fight carries the spec each pull was played in.
        """
        q = """query($c:String!,$f:[Int]!){reportData{report(code:$c){playerDetails(fightIDs:$f)}}}"""
        out = {}
        for fid in self.F:
            pd = self.f.cached(
                f"player_details-{fid}",
                lambda fid=fid: self.f._q(q, {"c": self.code, "f": [fid]})["reportData"]["report"]["playerDetails"],
            )
            while isinstance(pd, dict) and not any(k in pd for k in ("tanks", "healers", "dps")) and len(pd) == 1:
                pd = next(iter(pd.values()))
            m = {}
            for group, role in (("tanks", "Tank"), ("healers", "Healer"), ("dps", "DPS")):
                for p in (pd or {}).get(group) or []:
                    specs = p.get("specs") or []
                    spec = specs[0].get("spec", "") if specs and isinstance(specs[0], dict) else (specs[0] if specs else "")
                    m[p.get("name", "")] = (role, spec)
            out[fid] = m
        return out

    def role_in(self, fid, name) -> str:
        return (self.pull_roles.get(fid, {}).get(name) or (self.role(name), ""))[0]

    def swaps(self) -> dict[str, list[list]]:
        """name -> [[first pull, role, spec], ...] for anyone whose spec changed."""
        seq: dict[str, list] = defaultdict(list)
        for fid in sorted(self.F, key=lambda k: self.num[k]):
            for n, (role, spec) in self.pull_roles[fid].items():
                if not seq[n] or seq[n][-1][2] != spec:
                    seq[n].append([self.num[fid], role, spec])
        return {n: v for n, v in seq.items() if len(v) > 1}

    def role(self, name) -> str:
        return (self.roster().get(name) or {}).get("role", "")

    def pulls(self) -> list[dict]:
        rows = []
        for fid, x in self.F.items():
            bounds = self.phase_bounds(fid)
            reached = max(bounds, key=lambda k: bounds[k][0]) if bounds else "P1"
            w = self.wipe[fid]
            first = next((d for d in self.deaths[fid] if d["ts"] == w), None) if w else None
            rows.append(
                {
                    "pull": self.num[fid],
                    "dur": round((x["endTime"] - x["startTime"]) / 1000, 1),
                    "pct": round(x["fightPercentage"], 1),
                    "reached": reached,
                    "phases": {k: [round(self.rel(fid, s), 1), round(self.rel(fid, e), 1)] for k, (s, e) in bounds.items()},
                    "wipe": round(self.rel(fid, w), 1) if w else None,
                    "wipe_by": first["ability"] if first else None,
                    "reset": fid in self.reset,
                    "kill": bool(x["kill"]),
                }
            )
        return rows

    def counted(self) -> list[int]:
        """Pulls that count toward rates: everything but the resets."""
        return [fid for fid in self.F if fid not in self.reset]

    # ---- spinning axes ----------------------------------------------------

    def _march_spans(self, fid) -> dict[str, list[tuple[float, float]]]:
        ids = self.ids_named(S.DREADMARCH)
        out = defaultdict(list)
        open_: dict[str, float] = {}
        for e in self.stream("debuffs", fid):
            if e.get("abilityGameID") not in ids:
                continue
            n = self.name(e["targetID"])
            if e["type"] == "applydebuff":
                open_[n] = e["timestamp"]
            elif e["type"] == "removedebuff" and n in open_:
                out[n].append((open_.pop(n), e["timestamp"]))
        for n, t in open_.items():
            out[n].append((t, float("inf")))
        return out

    def axes(self) -> dict:
        """Ticks and axes eaten, normalised by time alive, P1 and P2 apart.

        Only ticks on a living player, before the wipe, count. In P2 a player
        walked by Dreadmarch is not in control, so their ticks are dropped.
        `index` is ticks against what the night's average would give for the
        same seconds of the phase (1.0 = night average), which keeps a long
        pull from looking worse just for reaching the dense part of P1.
        """
        ids = self.ids_named(S.AXE)
        B = S.AXE_BUCKET_MS
        out = {}
        for ph in ("P1", "P2"):
            # (fid, name) -> list of tick ts ; (fid, name) -> {bucket: alive ms}
            ticks: dict[tuple[int, str], list[float]] = defaultdict(list)
            dmg: Counter = Counter()
            expo: dict[tuple[int, str], Counter] = defaultdict(Counter)
            for fid in self.counted():
                bounds = self.phase_bounds(fid)
                if ph not in bounds:
                    continue
                lo, hi = bounds[ph]
                hi = min(hi, self.cut(fid))
                if hi <= lo:
                    continue
                march = self._march_spans(fid) if ph == "P2" else {}
                for n in self.players[fid]:
                    b = 0
                    while lo + b * B < hi:
                        a = lo + b * B
                        expo[(fid, n)][b] += self.alive_ms(fid, n, a, min(a + B, hi))
                        b += 1
                for e in self.stream("taken", fid):
                    if e.get("type") != "damage" or e.get("abilityGameID") not in ids:
                        continue
                    t = e["timestamp"]
                    if not (lo <= t < hi) or not self.is_player(e.get("targetID")):
                        continue
                    n = self.name(e["targetID"])
                    if not self.alive(fid, n, t):
                        continue
                    if any(a <= t <= z for a, z in march.get(n, [])):
                        continue
                    ticks[(fid, n)].append(t)
                    dmg[(fid, n)] += _amount(e)

            # the night's curve: ticks per alive-second in each bucket
            bt: Counter = Counter()
            bs: Counter = Counter()
            for (fid, n), ts in ticks.items():
                lo = self.phase_bounds(fid)[ph][0]
                for t in ts:
                    bt[int((t - lo) // B)] += 1
            for k, c in expo.items():
                for b, ms in c.items():
                    bs[b] += ms
            rate = {b: (bt[b] / (bs[b] / 1000)) if bs[b] else 0 for b in bs}

            def bouts(ts):
                ts = sorted(ts)
                return sum(1 for i, t in enumerate(ts) if i == 0 or t - ts[i - 1] > S.AXE_BOUT_GAP_MS)

            per_pull = []
            per_player: dict[str, dict] = defaultdict(lambda: defaultdict(float))
            by_pull_player: dict[str, dict] = defaultdict(dict)
            for fid in self.counted():
                if ph not in self.phase_bounds(fid):
                    continue
                pt = pb = pa = pe = pd = 0.0
                for n in self.players[fid]:
                    ts = ticks.get((fid, n), [])
                    alive_s = sum(expo[(fid, n)].values()) / 1000
                    exp = sum(ms / 1000 * rate.get(b, 0) for b, ms in expo[(fid, n)].items())
                    bo = bouts(ts)
                    pt += len(ts)
                    pb += bo
                    pa += alive_s
                    pe += exp
                    pd += dmg[(fid, n)]
                    if alive_s <= 0:
                        continue
                    P = per_player[n]
                    P["ticks"] += len(ts)
                    P["bouts"] += bo
                    P["alive"] += alive_s
                    P["exp"] += exp
                    P["dmg"] += dmg[(fid, n)]
                    P["pulls"] += 1
                    by_pull_player[n][self.num[fid]] = [len(ts), bo, round(alive_s), round(exp, 1)]
                if pa <= 0:
                    continue
                per_pull.append(
                    {
                        "pull": self.num[fid],
                        "ticks": int(pt),
                        "bouts": int(pb),
                        "alive_min": round(pa / 60, 1),
                        "per_min": round(pt / (pa / 60), 2),
                        "bouts_per_min": round(pb / (pa / 60), 2),
                        "index": round(pt / pe, 2) if pe else None,
                        "expected": round(pe, 1),
                        "dmg": round(pd),
                    }
                )
            rows = []
            for n, P in per_player.items():
                if P["alive"] < 30:
                    continue
                pulls = sorted(by_pull_player[n])
                half = len(pulls) // 2

                def idx(sel):
                    t = sum(by_pull_player[n][p][0] for p in sel)
                    e = sum(by_pull_player[n][p][3] for p in sel)
                    return round(t / e, 2) if e else None

                rows.append(
                    {
                        "name": n,
                        "role": self.role(n),
                        "cls": (self.roster().get(n) or {}).get("class", ""),
                        "ticks": int(P["ticks"]),
                        "bouts": int(P["bouts"]),
                        "alive_min": round(P["alive"] / 60, 1),
                        "per_min": round(P["ticks"] / (P["alive"] / 60), 2),
                        "bouts_per_min": round(P["bouts"] / (P["alive"] / 60), 2),
                        "index": round(P["ticks"] / P["exp"], 2) if P["exp"] else None,
                        "first_half": idx(pulls[:half]) if half else None,
                        "second_half": idx(pulls[half:]) if half else None,
                        "dmg": round(P["dmg"]),
                        "by_pull": by_pull_player[n],
                    }
                )
            rows.sort(key=lambda r: -(r["index"] or 0))
            tot_t = sum(r["ticks"] for r in per_pull)
            tot_a = sum(r["alive_min"] for r in per_pull)
            out[ph] = {
                "pulls": per_pull,
                "players": rows,
                "curve": [
                    {"t": b * B / 1000, "per_min": round(rate[b] * 60, 2), "alive_min": round(bs[b] / 60000, 1)}
                    for b in sorted(rate)
                    if bs[b] >= 60_000
                ],
                "ticks": tot_t,
                "bouts": sum(r["bouts"] for r in per_pull),
                "per_min": round(tot_t / tot_a, 2) if tot_a else 0,
                "dmg": sum(r["dmg"] for r in per_pull),
            }
        return out

    # ---- orbs -----------------------------------------------------------

    def orbs(self) -> dict:
        green = self.ids_named(S.GREEN)
        purple = self.ids_named(S.PURPLE)
        rupture = self.ids_named(S.RUPTURE)
        carry: dict[str, dict] = defaultdict(lambda: defaultdict(list))
        by_pull: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        explosions = []
        severs = []
        for fid in self.counted():
            cut = self.cut(fid)
            deb = self.stream("debuffs", fid)
            # carries: apply -> remove per player and colour
            open_: dict[tuple[str, str], float] = {}
            spans: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
            for e in deb:
                gid = e.get("abilityGameID")
                kind = "green" if gid in green else "purple" if gid in purple else None
                if not kind or not self.is_player(e.get("targetID")):
                    continue
                n = self.name(e["targetID"])
                if e["type"] == "applydebuff":
                    open_[(n, kind)] = e["timestamp"]
                elif e["type"] == "removedebuff" and (n, kind) in open_:
                    a = open_.pop((n, kind))
                    spans[n].append((a, e["timestamp"], kind))
            for (n, kind), a in open_.items():
                spans[n].append((a, a, kind))
            for n, L in spans.items():
                for a, z, kind in L:
                    if a >= cut:
                        continue
                    carry[n][kind].append(round((z - a) / 1000, 1))
                    by_pull[n][self.num[fid]][0 if kind == "green" else 1] += 1

            # Rupture bursts: group stack gains within 0.7s and read each
            # player's jump from their running stack count. Removals reset the
            # count, so a frontal starting from zero reads as its own orbs.
            evs = sorted(
                (e for e in deb if e.get("abilityGameID") in rupture
                 and e["type"] in ("applydebuff", "applydebuffstack", "removedebuff", "removedebuffstack")),
                key=lambda e: e["timestamp"],
            )
            stack: dict[int, int] = defaultdict(int)
            gains = []  # (ts, target, gained)
            for e in evs:
                tid = e["targetID"]
                if e["type"] == "removedebuff":
                    stack[tid] = 0
                    continue
                new = e.get("stack") or 1
                if e["type"] == "removedebuffstack":
                    stack[tid] = new
                    continue
                if e["type"] == "applydebuff":
                    gained = new
                else:
                    gained = max(1, new - stack[tid])
                stack[tid] = new
                gains.append((e["timestamp"], tid, gained))
            groups, cur = [], []
            for x in gains:
                if cur and x[0] - cur[0][0] > 700:
                    groups.append(cur)
                    cur = []
                cur.append(x)
            if cur:
                groups.append(cur)
            deluge_ids = self.ids_named(S.DELUGE)
            deluges = [
                e["timestamp"]
                for e in self.stream("enemy_casts", fid)
                if e["type"] == "cast" and e.get("abilityGameID") in deluge_ids
            ]
            frontal_ids = self.ids_of(*S.FRONTALS)
            frontal_ts = [
                e["timestamp"]
                for e in self.stream("enemy_casts", fid)
                if e["type"] == "cast" and e.get("abilityGameID") in frontal_ids
            ]
            p2 = self.phase_bounds(fid).get("P2", (None,))[0]
            rup_deaths = [d["ts"] for d in self.deaths[fid] if d["ability"] == S.RUPTURE]
            for g in groups:
                t = g[0][0]
                per: Counter = Counter()
                for _, tid, gained in g:
                    per[tid] += gained
                jumps = list(per.values())
                if not jumps:
                    continue
                jump = int(statistics.median(jumps))
                ph = self.phase_at(fid, t)
                # A frontal's stacks land on its cast; the push lands as stage
                # two starts. A gain anywhere else is an explosion even when it
                # reads small: on a raid with no stacks it logs as a plain
                # applydebuff, which carries no stack count.
                on_frontal = any(0 <= t - c <= S.FRONTAL_GRACE_MS for c in frontal_ts)
                on_push = p2 is not None and -2000 <= t - p2 <= 3000
                if max(jumps) >= S.EXPLOSION_STACKS or not (on_frontal or on_push):
                    holders = sorted(
                        {
                            n
                            for n, L in spans.items()
                            for a, z, kind in L
                            if kind == "purple" and a <= t + 300 and z >= t - S.EXPLOSION_HOLD_MS
                        }
                    )
                    # A Mutation still on the ground when the next Deluge is
                    # cast blows up on the cast, with nobody carrying it.
                    left = any(abs(t - d) <= S.DELUGE_GRACE_MS for d in deluges)
                    explosions.append(
                        {
                            "how": "left" if left else "touched",
                            "pull": self.num[fid],
                            "t": round(self.rel(fid, t), 1),
                            "phase": ph,
                            "stacks": max(jumps) if max(jumps) >= S.EXPLOSION_STACKS else None,
                            "with_frontal": on_frontal,
                            "killed": sum(1 for d in rup_deaths if 0 <= d - t <= 2500),
                            "holders": holders,
                            # the explosion that kills the wipe's first player
                            # lands a hair after that death is logged
                            "before_wipe": t <= cut + 1500,
                        }
                    )
                elif t <= cut:
                    severs.append({"pull": self.num[fid], "t": round(self.rel(fid, t)), "phase": ph, "stacks": jump})

        rows = []
        for n, k in carry.items():
            g, p = k.get("green", []), k.get("purple", [])
            rows.append(
                {
                    "name": n,
                    "role": self.role(n),
                    "cls": (self.roster().get(n) or {}).get("class", ""),
                    "green": len(g),
                    "purple": len(p),
                    "green_hold": round(statistics.median(g), 1) if g else None,
                    "purple_hold": round(statistics.median(p), 1) if p else None,
                    "by_pull": {str(k2): v for k2, v in sorted(by_pull[n].items())},
                }
            )
        rows.sort(key=lambda r: -(r["green"] + r["purple"]))
        return {"carriers": rows, "explosions": explosions, "severs": severs}

    # ---- Guillotine -----------------------------------------------------

    plan: dict | None = None

    def _guillotine_debuffed(self, fid: int, ts: int) -> set[str]:
        """Players carrying a Guillotine debuff (100s, from soaking an earlier
        axe) at ts. They cannot soak again, so the 133s axe can't ask it of
        whoever was under the 48s one: the marked player or a team-2 extra."""
        ids = self.ids_named("Guillotine") | self.ids_named("Grim Guillotine")
        on: dict[int, bool] = {}
        for e in sorted(self.stream("debuffs", fid), key=lambda e: e["timestamp"]):
            if e["timestamp"] >= ts - 200:
                break
            if e.get("abilityGameID") not in ids:
                continue
            if e["type"] in ("applydebuff", "refreshdebuff"):
                on[e.get("targetID")] = True
            elif e["type"] == "removedebuff":
                on[e.get("targetID")] = False
        return {self.name(k) for k, v in on.items() if v}

    def guillotine(self) -> dict:
        plan_rows: dict[str, dict] = defaultdict(
            lambda: {"soaked": 0, "absent": 0, "dead": 0, "locked": 0, "extra": 0, "absent_at": []}
        )
        windows = []
        per_player: dict[str, Counter] = defaultdict(Counter)
        deaths = []
        for fid in self.counted():
            casts = self.stream("enemy_casts", fid)
            taken = self.stream("taken", fid)
            for kind in S.GUILLOTINES:
                ids = self.ids_named(kind)
                ex_ids = self.ids_named(S.EXECUTIONS[kind])
                # the targeted cast (onto the marked player) is the one with a player target
                marks = [
                    e
                    for e in casts
                    if e["type"] == "cast" and e.get("abilityGameID") in ids and self.is_player(e.get("targetID"))
                ]
                for i, m in enumerate(marks):
                    t = m["timestamp"]
                    land = [
                        e
                        for e in taken
                        if e.get("type") == "damage"
                        and e.get("abilityGameID") in (ids | ex_ids)
                        and t <= e["timestamp"] <= t + 6000
                        and self.is_player(e.get("targetID"))
                    ]
                    if not land:
                        continue
                    t0 = min(e["timestamp"] for e in land)
                    hits = [e for e in land if e["timestamp"] - t0 <= 600]
                    soak = sorted({self.name(e["targetID"]) for e in hits if e["abilityGameID"] in ids})
                    exe = {self.name(e["targetID"]) for e in hits if e["abilityGameID"] in ex_ids}
                    alive = [n for n in self.players[fid] if self.alive(fid, n, t0 - 1)]
                    died = [
                        d
                        for d in self.deaths[fid]
                        if t0 - 100 <= d["ts"] <= t0 + 3000 and d["ability"] in (kind, S.EXECUTIONS[kind])
                    ]
                    after_wipe = self.wipe[fid] is not None and t0 > self.wipe[fid]
                    # against the soak teams, when the night had them: the
                    # marked player soaks whoever they are, tanks are extras
                    # Grim Guillotines use the same two teams, alternating:
                    # 1, 2, then 1 again (its debuff is gone by the third)
                    team = (self.plan or {}).get("guillotine", {}).get(
                        str(i + 1) if kind == "Guillotine" else ("1" if i % 2 == 0 else "2")
                    )
                    flex = set((self.plan or {}).get("flex", []))
                    target = self.name(m["targetID"])
                    absent = dead_before = extra = locked = None
                    if team is not None:
                        debuffed = self._guillotine_debuffed(fid, t0)
                        locked = [n for n in team if n in alive and n not in soak and n in debuffed]
                        absent = [n for n in team if n in alive and n not in soak and n not in debuffed]
                        dead_before = [n for n in team if n in self.players[fid] and n not in alive]
                        extra = [n for n in soak if n not in team and n not in flex and n != target]
                        if not after_wipe:
                            for n in team:
                                if n not in self.players[fid]:
                                    continue
                                P = plan_rows[n]
                                if n not in alive:
                                    P["dead"] += 1
                                elif n in soak:
                                    P["soaked"] += 1
                                elif n in locked:
                                    P["locked"] += 1
                                else:
                                    P["absent"] += 1
                                    P["absent_at"].append(
                                        f"{self.num[fid]}" + (" (Grim)" if kind != "Guillotine" else "")
                                    )
                            for n in extra:
                                plan_rows[n]["extra"] += 1
                    windows.append(
                        {
                            "pull": self.num[fid],
                            "kind": kind,
                            "n": i + 1,
                            "t": round(self.rel(fid, t0), 1),
                            "target": self.name(m["targetID"]),
                            "soakers": soak,
                            "alive": len(alive),
                            "missed": bool(exe),
                            "exec_hits": len(exe),
                            "deaths": [d["player"] for d in died],
                            "after_wipe": after_wipe,
                            "absent": absent,
                            "dead_before": dead_before,
                            "locked": locked,
                            "extra": extra,
                        }
                    )
                    if not after_wipe:
                        for n in soak:
                            per_player[n][f"{kind} {i + 1}"] += 1
                            per_player[n]["total"] += 1
                        for d in died:
                            deaths.append(
                                {"pull": self.num[fid], "t": round(self.rel(fid, d["ts"]), 1), "player": d["player"],
                                 "by": d["ability"], "soaked": d["player"] in soak}
                            )
        rows = [
            {"name": n, "role": self.role(n), "cls": (self.roster().get(n) or {}).get("class", ""), **dict(c)}
            for n, c in per_player.items()
        ]
        rows.sort(key=lambda r: -r["total"])
        team_of = {n: k for k, L in ((self.plan or {}).get("guillotine") or {}).items() for n in L}
        plan = [
            {"name": n, "team": team_of.get(n), "role": self.role(n), **v}
            for n, v in plan_rows.items()
        ]
        plan.sort(key=lambda r: (r["team"] or "9", -r["absent"], -r["extra"], r["name"]))
        return {"windows": windows, "players": rows, "deaths": deaths, "plan": plan if self.plan else None}

    # ---- frontals --------------------------------------------------------

    def frontals(self) -> dict:
        rows = []
        caught: dict[str, Counter] = defaultdict(Counter)
        for fid in self.counted():
            cut = self.cut(fid)
            for kind in S.FRONTALS:
                ids = self.ids_named(kind)
                for e in self.stream("taken", fid):
                    if e.get("type") != "damage" or e.get("abilityGameID") not in ids or e.get("tick"):
                        continue
                    if e.get("abilityGameID") in S.FRONTAL_DOTS:
                        continue
                    if not self.is_player(e.get("targetID")) or e["timestamp"] > cut:
                        continue
                    n = self.name(e["targetID"])
                    if self.role(n) != "Tank":
                        caught[n][kind] += 1
                deb = [e for e in self.stream("debuffs", fid) if e.get("abilityGameID") in ids]
                for d in self.deaths[fid]:
                    if d["ability"] != kind:
                        continue
                    # still carrying the previous frontal's vulnerability when
                    # this one landed (a missed swap, or a second frontal)
                    had = False
                    for e in deb:
                        if self.name(e.get("targetID")) != d["player"] or e["timestamp"] >= d["ts"] - 300:
                            continue
                        had = e["type"] in ("applydebuff", "applydebuffstack", "refreshdebuff")
                    rows.append(
                        {
                            "pull": self.num[fid],
                            "t": round(self.rel(fid, d["ts"]), 1),
                            "phase": self.phase_at(fid, d["ts"]),
                            "player": d["player"],
                            "tank": self.role(d["player"]) == "Tank",
                            "kind": kind,
                            "had_vuln": had,
                            "before_wipe": d["ts"] <= cut,
                            "wipe_start": self.wipe[fid] == d["ts"],
                        }
                    )
        hit_rows = [
            {"name": n, "role": self.role(n), "cls": (self.roster().get(n) or {}).get("class", ""), **dict(c),
             "total": sum(c.values())}
            for n, c in caught.items()
        ]
        hit_rows.sort(key=lambda r: -r["total"])
        return {"deaths": rows, "caught": hit_rows}

    # ---- the shield burn -------------------------------------------------

    def veil(self) -> dict:
        windows = []
        per_player: Counter = Counter()
        appear: Counter = Counter()
        by_pull: dict[str, dict] = defaultdict(dict)
        veil_ids = self.ids_named(S.VEIL)
        nf_ids = self.ids_named(S.NIGHTFALL)
        for fid in self.counted():
            buffs = self.stream("enemy_buffs", fid)
            casts = self.stream("enemy_casts", fid)
            done = self.stream("done", fid)
            starts = sorted({e["timestamp"] for e in buffs if e.get("abilityGameID") in veil_ids and e["type"] == "applybuff"})
            ends = sorted({e["timestamp"] for e in buffs if e.get("abilityGameID") in veil_ids and e["type"] == "removebuff"})
            resolved_at = [e["timestamp"] for e in casts if e.get("abilityGameID") in nf_ids and e["type"] == "cast"]
            for k, s in enumerate(starts):
                end = min((t for t in ends if t >= s), default=None)
                if end is None:
                    end = min(self.F[fid]["endTime"], s + 17_500)
                    finished = False
                else:
                    finished = True
                resolved = any(s <= t <= end + 1500 for t in resolved_at)
                cut = self.wipe[fid]
                cutoff = cut is not None and cut < end and not resolved
                into: Counter = Counter()
                absorbed = 0.0
                for e in done:
                    if not (s <= e["timestamp"] <= end) or e.get("type") != "damage":
                        continue
                    if self.name(e.get("targetID")) != S.USURPER:
                        continue
                    absorbed += e.get("absorbed") or 0
                    who = self.name(self.owner_of(e.get("sourceID")))
                    if who in self.roster():
                        into[who] += _amount(e)
                after_wipe = cut is not None and s > cut
                nf_deaths = sum(1 for d in self.deaths[fid] if d["ability"] == S.NIGHTFALL and s <= d["ts"] <= end + 3000)
                windows.append(
                    {
                        "pull": self.num[fid],
                        "n": k + 1,
                        "phase": self.phase_at(fid, s),
                        "t": round(self.rel(fid, s), 1),
                        "secs": round((end - s) / 1000, 1),
                        "broken": finished and not resolved,
                        "resolved": resolved,
                        "open": not finished,
                        "after_wipe": after_wipe,
                        "absorbed": round(absorbed),
                        "deaths": nf_deaths,
                        "alive": sum(1 for n in self.players[fid] if self.alive(fid, n, s)),
                        "top": [[n, round(v)] for n, v in into.most_common(3)],
                    }
                )
                if after_wipe:
                    continue
                for n, v in into.items():
                    # a healer's stray damage is not a share of the burn
                    if self.role_in(fid, n) == "Healer":
                        continue
                    per_player[n] += v
                    appear[n] += 1
                    by_pull[n][f"{self.num[fid]}.{k + 1}"] = round(v)
        rows = self._rank(per_player, lambda n, a: {"windows": appear[n], "per_window": round(a / appear[n]),
                                                    "by_window": by_pull[n]})
        return {"windows": windows, "players": rows}

    # ---- the Soulcoiler --------------------------------------------------

    def adds(self) -> dict:
        sc_ids = {i for i, a in self.actors.items() if a.get("name") == S.SOULCOILER}
        call_ids = self.ids_named(S.SPIRITCACKLE)
        shield_ids = self.ids_named(S.SPIRIT_SHIELD)
        adds = []
        pre: Counter = Counter()
        post: Counter = Counter()
        appear: Counter = Counter()
        for fid in self.counted():
            casts = self.stream("enemy_casts", fid)
            calls = sorted({e["timestamp"] for e in casts if e["type"] == "cast" and e.get("abilityGameID") in call_ids})
            buffs = [e for e in self.stream("enemy_buffs", fid) if e.get("abilityGameID") in shield_ids]
            done = [
                e
                for e in self.stream("done", fid)
                if e.get("type") == "damage" and e.get("targetID") in sc_ids
            ]
            end_fight = self.F[fid]["endTime"]
            prev_keys: set = set()
            for i, c in enumerate(calls):
                nxt = calls[i + 1] if i + 1 < len(calls) else end_fight
                up = next((e["timestamp"] for e in buffs if c <= e["timestamp"] < nxt and e["type"] == "applybuff"), None)
                down = next((e["timestamp"] for e in buffs if c <= e["timestamp"] < nxt and e["type"] == "removebuff"), None)
                hits = [e for e in done if c <= e["timestamp"] < nxt]
                if not hits:
                    continue
                # an earlier add can still be alive in this window; follow the
                # one this call made, which is the first one hit after it
                key = min(hits, key=lambda e: e["timestamp"])
                key = next(
                    (
                        (e["targetID"], e.get("targetInstance"))
                        for e in sorted(hits, key=lambda e: e["timestamp"])
                        if (e["targetID"], e.get("targetInstance")) not in prev_keys
                    ),
                    (key["targetID"], key.get("targetInstance")),
                )
                prev_keys.add(key)
                hits = [e for e in hits if (e["targetID"], e.get("targetInstance")) == key]
                # the add dies on its last hit; a still-healthy one at the end of
                # the window was not killed
                # resourceActor 2 means the hit points on the event are the add's
                dead = [e for e in hits if e.get("resourceActor") == 2 and e.get("hitPoints") == 0]
                lastb = min(dead, key=lambda e: e["timestamp"]) if dead else None
                killed = lastb is not None
                dmg_pre: Counter = Counter()
                dmg_post: Counter = Counter()
                for e in hits:
                    who = self.name(self.owner_of(e.get("sourceID")))
                    if who not in self.roster() or self.role_in(fid, who) == "Healer":
                        continue
                    (dmg_pre if down is None or e["timestamp"] < down else dmg_post)[who] += _amount(e)
                cut = self.wipe[fid]
                if not (cut is not None and c > cut):
                    for n in set(dmg_pre) | set(dmg_post):
                        appear[n] += 1
                    pre.update(dmg_pre)
                    post.update(dmg_post)
                adds.append(
                    {
                        "pull": self.num[fid],
                        "n": i + 1,
                        "phase": self.phase_at(fid, c),
                        "t": round(self.rel(fid, c), 1),
                        "shield_secs": round((down - up) / 1000, 1) if up and down else None,
                        "ttk": round((lastb["timestamp"] - c) / 1000, 1) if killed else None,
                        "after_strip": round((lastb["timestamp"] - down) / 1000, 1) if killed and down else None,
                        "killed": killed,
                        "after_wipe": cut is not None and c > cut,
                        "top": [[n, round(v)] for n, v in (dmg_pre + dmg_post).most_common(3)],
                    }
                )
        tot = pre + post
        rows = self._rank(tot, lambda n, a: {"pre": round(pre[n]), "post": round(post[n]), "adds": appear[n]})
        return {"adds": adds, "players": rows}

    # ---- the intermission ------------------------------------------------

    def intermission(self) -> dict:
        """Stage two into stage three: Zul'jan rises and the fragments walk.

        Zul'jan comes back on 1 HP and Ghastly Regeneration heals him 2% a
        second; the raid's damage is what holds him down. Every Fragment of
        Malacrass is either body-blocked (a Spirit Erasure hit on each living
        player) or reaches him (Reclaim Essence: 10% on Zul'jan and a smaller
        heal on Malacrass, logged as one heal on each). Whatever he has when
        the intermission ends is what stage three starts with.
        """
        reclaim_ids = self.ids_named(S.RECLAIM)
        regen_ids = self.ids_named(S.REGEN)
        erasure_ids = self.ids_named(S.INT_AURA)
        lust_ids = self.ids_of(*S.LUST)
        rows = []
        dmg: Counter = Counter()
        secs: Counter = Counter()
        appear: Counter = Counter()
        stacks_max: dict[str, int] = defaultdict(int)
        erasure_dmg: Counter = Counter()
        int_deaths: Counter = Counter()
        # name -> pull -> {damage, dps, stacks, erasure, died}, for the per-pull view
        per_pull: dict[str, dict] = defaultdict(dict)
        by_pull: dict[str, dict] = defaultdict(dict)
        for fid in self.counted():
            b = self.phase_bounds(fid)
            if "INT" not in b:
                continue
            s, e = b["INT"]
            wipe = self.wipe[fid]
            # a wipe that starts inside the intermission takes it with it: the
            # fragments walk in unopposed and the regen runs unchecked
            after_wipe = wipe is not None and wipe <= e
            done = self.stream("done", fid)

            # Zul'jan's health through the window, from the hit points on
            # damage events (resourceActor 2 = the target's). One point per
            # half-second; the regen tick lands on the handover itself, so the
            # stage-three start is read a second after it.
            trace: dict[int, float] = {}
            max_hp = 0
            for ev in done:
                t = ev["timestamp"]
                if not (s <= t <= e + 1500) or self.name(ev.get("targetID")) != S.SERPENT:
                    continue
                if ev.get("resourceActor") != 2 or not ev.get("maxHitPoints"):
                    continue
                max_hp = ev["maxHitPoints"]
                trace[int((t - s) // 500)] = round(100 * ev["hitPoints"] / ev["maxHitPoints"], 1)
            m_max = next((ev["maxHitPoints"] for ev in done if self.name(ev.get("targetID")) == S.USURPER
                          and ev.get("resourceActor") == 2 and ev.get("maxHitPoints") and ev["timestamp"] >= s), 0)
            z_end = self.boss_health_at(fid, S.SERPENT, e + 1500)
            m_end = self.boss_health_at(fid, S.USURPER, e + 1500)

            heals = self.stream("enemy_heals", fid)
            regen = sum(
                ev.get("amount") or 0
                for ev in heals
                if ev.get("abilityGameID") in regen_ids and self.name(ev.get("targetID")) == S.SERPENT
                and s <= ev["timestamp"] <= e + 500
            )
            # Reclaims keep landing after the handover if fragments are still
            # walking, so the window runs to the end of the pull.
            reclaims = []
            for ev in heals:
                if ev.get("abilityGameID") not in reclaim_ids or ev.get("type") != "heal":
                    continue
                if self.name(ev.get("targetID")) != S.SERPENT or ev["timestamp"] < s:
                    continue
                t = ev["timestamp"]
                malac = next(
                    (x.get("amount") or 0 for x in heals if x.get("abilityGameID") in reclaim_ids
                     and x["timestamp"] == t and self.name(x.get("targetID")) == S.USURPER),
                    0,
                )
                reclaims.append(
                    {
                        "t": round((t - s) / 1000, 1),
                        "healed": ev.get("amount") or 0,
                        "pct": round(100 * (ev.get("amount") or 0) / max_hp, 1) if max_hp else None,
                        "malacrass": malac,
                        "malacrass_pct": round(100 * malac / m_max, 1) if m_max else None,
                        "in_int": t <= e,
                        "after_wipe": wipe is not None and t > wipe,
                    }
                )

            # Body-blocked fragments: a Spirit Erasure hit on everyone alive.
            # Two can land in the same instant (forty hits on twenty players),
            # so count hits against the living rather than volleys.
            hits = [ev for ev in self.stream("taken", fid)
                    if ev.get("abilityGameID") in erasure_ids and ev.get("type") == "damage"
                    and s - 1000 <= ev["timestamp"] <= e + 1000 and self.is_player(ev.get("targetID"))]
            vol: dict[int, Counter] = defaultdict(Counter)
            for ev in hits:
                vol[int(ev["timestamp"] // 100)][ev["targetID"]] += 1
            blocks = []
            for k in sorted(vol):
                c = vol[k]
                if len(c) < S.GHOST_BLAST_MIN_TARGETS:
                    continue
                n = round(sum(c.values()) / len(c))
                t = k * 100
                blocks.extend([round((t - s) / 1000, 1)] * n)

            deb = [ev for ev in self.stream("debuffs", fid) if ev.get("abilityGameID") in erasure_ids
                   and s - 1000 <= ev["timestamp"] <= e + 1000]
            pull_max = 0
            p_stacks: Counter = Counter()
            for ev in deb:
                st = ev.get("stack") or 1
                pull_max = max(pull_max, st)
                if not after_wipe and (wipe is None or ev["timestamp"] <= wipe):
                    n = self.name(ev.get("targetID"))
                    stacks_max[n] = max(stacks_max[n], st)
                    p_stacks[n] = max(p_stacks[n], st)

            into: Counter = Counter()
            for ev in done:
                if ev.get("type") != "damage" or not (s <= ev["timestamp"] <= e):
                    continue
                if self.name(ev.get("targetID")) != S.SERPENT:
                    continue
                into[self.name(self.owner_of(ev.get("sourceID")))] += _amount(ev)
            raid_dmg = sum(v for n, v in into.items() if n in self.roster())

            lust = None
            for ev in self.stream("player_casts", fid):
                if ev.get("type") == "cast" and ev.get("abilityGameID") in lust_ids:
                    off = round((ev["timestamp"] - s) / 1000, 1)
                    if lust is None or abs(off) < abs(lust):
                        lust = off

            died = [d for d in self.deaths[fid] if s <= d["ts"] <= e]
            int_secs = (e - s) / 1000
            if not after_wipe:
                p_erasure: Counter = Counter()
                p_died: Counter = Counter()
                for ev in hits:
                    if wipe is None or ev["timestamp"] <= wipe:
                        p_erasure[self.name(ev["targetID"])] += _amount(ev)
                for d in died:
                    if wipe is None or d["ts"] <= wipe:
                        p_died[d["player"]] += 1
                erasure_dmg.update(p_erasure)
                int_deaths.update(p_died)
                for n in self.players[fid]:
                    dealer = self.role_in(fid, n) != "Healer"
                    v = into.get(n, 0) if dealer else 0
                    alive_s = self.alive_ms(fid, n, s, e) / 1000
                    if dealer and v:
                        dmg[n] += v
                        secs[n] += alive_s
                        appear[n] += 1
                        by_pull[n][str(self.num[fid])] = round(v)
                    per_pull[n][str(self.num[fid])] = {
                        "damage": round(v) if dealer else None,
                        "dps": round(v / alive_s) if dealer and alive_s else None,
                        "alive": round(alive_s, 1),
                        "stacks": p_stacks.get(n, 0),
                        "erasure": round(p_erasure.get(n, 0)),
                        "died": p_died.get(n, 0),
                    }

            missed = [r for r in reclaims if not r["after_wipe"]]
            rows.append(
                {
                    "pull": self.num[fid],
                    "start": round(self.rel(fid, s), 1),
                    "secs": round(int_secs, 1),
                    "alive": sum(1 for n in self.players[fid] if self.alive(fid, n, s)),
                    "after_wipe": after_wipe,
                    "wipe": round((wipe - s) / 1000, 1) if wipe is not None else None,
                    "z_end": round(z_end, 1) if z_end is not None else None,
                    "m_end": round(m_end, 1) if m_end is not None else None,
                    "max_hp": max_hp,
                    "trace": [[k / 2, v] for k, v in sorted(trace.items())],
                    "regen": round(regen),
                    "regen_pct": round(100 * regen / max_hp, 1) if max_hp else None,
                    "damage": round(raid_dmg),
                    "damage_pct": round(100 * raid_dmg / max_hp, 1) if max_hp else None,
                    "dps": round(raid_dmg / int_secs) if int_secs else 0,
                    "blocked": len(blocks),
                    "blocks": blocks,
                    "reclaims": reclaims,
                    "missed": len(missed),
                    "missed_pct": round(sum(r["pct"] or 0 for r in missed), 1),
                    "erasure_max": pull_max,
                    "lust": lust,
                    "deaths": [[round((d["ts"] - s) / 1000, 1), d["player"], d["ability"]] for d in died],
                    "top": [[n, round(v)] for n, v in into.most_common(3) if n in self.roster()],
                }
            )
        names = set(dmg) | set(stacks_max) | set(int_deaths) | set(per_pull)
        players = []
        grand = sum(dmg.values()) or 1
        for n in names:
            if n not in self.roster():
                continue
            players.append(
                {
                    "name": n,
                    "damage": round(dmg[n]),
                    "share": round(100 * dmg[n] / grand, 1),
                    "dps": round(dmg[n] / secs[n]) if secs[n] else None,
                    "ints": appear[n],
                    "stacks": stacks_max.get(n, 0),
                    "erasure": round(erasure_dmg[n]),
                    "deaths": int_deaths[n],
                    "by_pull": by_pull[n],
                    "pulls": per_pull[n],
                }
            )
        players.sort(key=lambda r: -r["damage"])

        # Best theoretical: every damage dealer's best intermission stacked into
        # one, with no fragment getting through. Regen is a fixed 2% a second,
        # so Zul'jan would go into stage three on regen minus that damage.
        clean = [r for r in rows if not r["after_wipe"]]
        best = None
        if clean:
            picks = []
            for p in players:
                c = [(v["damage"], k, v["dps"]) for k, v in p["pulls"].items() if v.get("damage")]
                if c:
                    dmg_, pull, dps = max(c)
                    picks.append({"name": p["name"], "pull": int(pull), "damage": dmg_, "dps": dps})
            picks.sort(key=lambda x: -x["damage"])
            total = sum(x["damage"] for x in picks)
            hp = statistics.median(r["max_hp"] for r in clean)
            regen = statistics.median(r["regen_pct"] for r in clean)
            for x in picks:
                x["share"] = round(100 * x["damage"] / total, 1) if total else 0
            top = max(clean, key=lambda r: r["damage"])
            best = {
                "players": picks,
                "damage": total,
                "damage_pct": round(100 * total / hp, 1),
                "regen_pct": regen,
                "z_end": round(max(0.0, regen - 100 * total / hp), 1),
                "best_real_pull": top["pull"],
                "best_real_damage_pct": top["damage_pct"],
                "best_real_z_end": top["z_end"],
            }
        return {"rows": rows, "players": players, "best": best}

    def build(self) -> dict:
        return {
            "swaps": self.swaps(),
            "pulls": self.pulls(),
            "axes": self.axes(),
            "orbs": self.orbs(),
            "guillotine": self.guillotine(),
            "frontals": self.frontals(),
            "veil": self.veil(),
            "adds": self.adds(),
            "intermission": self.intermission(),
        }
