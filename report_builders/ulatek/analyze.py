"""Turn one Warcraft Logs report into every number the page shows.

Stages, in order, because each needs the one before it:
  actors/fights -> heart damage -> exposure windows -> everything else.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from . import spells
from .fetch import Fetcher

BIN = 20  # seconds of an exposure window, one bucket each
DTPS_BUCKET = 5  # seconds per bucket in the damage-taken table
HEAVY_FACTOR = 2  # a heavy second is this many times the pull's median rate
HEAVY_MIN_LEN = 3  # seconds; shorter spikes are noise
SPLIT_GAP = 5000  # coordinate units between the two halves during the split
CENTRE = 3000  # inside this of the middle counts as "back"
EARLY_DEATH = 15_000  # ms before the pull's last death for a death to be "isolated"


def _amount(e: dict) -> float:
    return (e.get("amount") or 0) + (e.get("absorbed") or 0)


class Analysis:
    def __init__(
        self, code: str, encounter_id: int | None = None, difficulty: int | None = None, cache_root=None
    ) -> None:
        self.f = Fetcher(code, cache_root)
        self.code = code
        self.meta = self.f.meta()
        self.actors = {a["id"]: a for a in self.meta["masterData"]["actors"]}
        self.ability = {a["gameID"]: a["name"] for a in self.meta["masterData"]["abilities"]}
        self.by_name = defaultdict(set)
        for gid, name in self.ability.items():
            self.by_name[name].add(gid)
        self._owner = {a["id"]: (a.get("petOwner") or a["id"]) for a in self.actors.values()}

        fights = [x for x in self.meta["fights"] if x.get("encounterID")]
        if encounter_id is None:
            encounter_id = Counter(x["encounterID"] for x in fights).most_common(1)[0][0]
        fights = [x for x in fights if x["encounterID"] == encounter_id]
        if difficulty is None:
            difficulty = Counter(x["difficulty"] for x in fights).most_common(1)[0][0]
        self.fights = [x for x in fights if x["difficulty"] == difficulty]
        self.encounter_id, self.difficulty = encounter_id, difficulty
        self.fight = {x["id"]: x for x in self.fights}
        self.ids = [x["id"] for x in self.fights]
        # Warcraft Logs numbers fights across the whole report, trash included, so
        # a 25-pull night can end on fight 31. The page counts pulls on this boss,
        # which is what the raid calls them.
        self.pull_no = {fid: n for n, fid in enumerate(self.ids, 1)}

        self.heart_id = self._npc(*spells.HEART)
        self.boss_ids = self._npcs(*spells.BOSS)
        self.viper_id = self._npc(*spells.VIPER)

        pd = self.f.player_details(self.ids)
        pd = pd.get("data", {}).get("playerDetails", pd) if isinstance(pd, dict) else pd
        self.role, self.spec = {}, {}
        for role, key in (("tank", "tanks"), ("healer", "healers"), ("dps", "dps")):
            for p in (pd or {}).get(key, []) or []:
                self.role[p["name"]] = role
                self.spec[p["name"]] = (p.get("specs") or [{}])[0].get("spec", "")
        self.players = {
            a["name"]: a for a in self.actors.values() if a["type"] == "Player" and a["name"] in self.role
        }
        self.tanks = sorted(p for p in self.players if self.role[p] == "tank")
        self._phases: tuple[dict, dict] | None = None

    # ---- small helpers ----

    def name(self, actor_id) -> str | None:
        a = self.actors.get(self._owner.get(actor_id, actor_id))
        return a["name"] if a else None

    def player_of(self, actor_id) -> str | None:
        n = self.name(actor_id)
        return n if n in self.players else None

    def _npc(self, name: str, game_id: int) -> int | None:
        ids = self._npcs(name, game_id)
        return ids[0] if ids else None

    def _npcs(self, name: str, game_id: int) -> list[int]:
        out = [
            a["id"]
            for a in self.actors.values()
            if a["type"] != "Player" and (a.get("gameID") == game_id or a["name"] == name)
        ]
        return sorted(out)

    def ids_named(self, name: str) -> set[int]:
        return self.by_name.get(name, set())

    def rel(self, fid: int, ts: float) -> float:
        return (ts - self.fight[fid]["startTime"]) / 1000

    # ---- raw events, fetched once ----

    def heart_events(self, fid):
        return self.f.events(f"heart_{fid}", fid, "DamageDone", target_id=self.heart_id)

    def casts(self, fid):
        return self.f.events(f"casts_{fid}", fid, "Casts", hostility="Friendlies", resources=True)

    def enemy_casts(self, fid):
        return self.f.events(f"ecasts_{fid}", fid, "Casts", hostility="Enemies")

    def taken(self, fid):
        return self.f.events(f"taken_{fid}", fid, "DamageTaken")

    def deaths(self, fid):
        return self.f.events(f"deaths_{fid}", fid, "Deaths")

    def vipers(self, fid):
        if self.viper_id is None:
            return []
        return self.f.events(f"viper_{fid}", fid, "DamageDone", target_id=self.viper_id)

    def damage_table(self, fid):
        return self.f.table(f"dmgtable_{fid}", fid, "DamageDone")

    # ---- windows ----

    def windows(self, fid) -> list[tuple[int, int]]:
        """Exposure windows, found by clustering damage on the heart and breaking
        at gaps over five seconds. Matches the boss's expose casts but survives a
        pull where the first hit lands late."""
        ts = sorted(e["timestamp"] for e in self.heart_events(fid))
        wins: list[list[int]] = []
        for t in ts:
            if wins and t - wins[-1][1] <= 5000:
                wins[-1][1] = t
            else:
                wins.append([t, t])
        return [(a, b) for a, b in wins if b - a > 1000]

    def boss_in_windows(self, fid):
        out = []
        for i, (a, b) in enumerate(self.windows(fid)):
            for tid in self.boss_ids:
                out += self.f.events(
                    f"boss_{fid}_{i}_{tid}", fid, "DamageDone", start=a, end=b + 1, target_id=tid
                )
        return out

    # ---- burn windows: the heart and the boss beside it ----

    def burn(self) -> dict:
        players, bins, fights_out, windows_out = {}, {}, [], []
        heart_tot = boss_tot = 0.0
        window_secs = 0.0
        for fid in self.ids:
            wins = self.windows(fid)
            per = [defaultdict(lambda: {"h": [0.0] * BIN, "b": [0.0] * BIN}) for _ in wins]
            wsum = [{"h": 0.0, "b": 0.0} for _ in wins]
            for key, short, evs in (
                ("heart", "h", self.heart_events(fid)),
                ("boss", "b", self.boss_in_windows(fid)),
            ):
                for e in evs:
                    p = self.name(e.get("sourceID"))
                    if not p:
                        continue
                    for i, (a, b) in enumerate(wins):
                        if a <= e["timestamp"] <= b:
                            k = min(BIN - 1, int((e["timestamp"] - a) / 1000))
                            per[i][p][short][k] += _amount(e)
                            wsum[i][short] += _amount(e)
                            slot = players.setdefault(p, {"heart": 0.0, "boss": 0.0})
                            slot["heart" if short == "h" else "boss"] += _amount(e)
                            break
            if wins:
                bins[self.pull_no[fid]] = [
                    {
                        p: {"h": [round(x) for x in v["h"]], "b": [round(x) for x in v["b"]]}
                        for p, v in w.items()
                    }
                    for w in per
                ]
            for i, (a, b) in enumerate(wins):
                window_secs += (b - a) / 1000
                windows_out.append(
                    {
                        "fight": self.pull_no[fid],
                        "idx": i + 1,
                        "dur": round((b - a) / 1000, 1),
                        "dmg": round(wsum[i]["h"] + wsum[i]["b"]),
                        "heart": round(wsum[i]["h"]),
                        "boss": round(wsum[i]["b"]),
                    }
                )
            heart_tot += sum(w["h"] for w in wsum)
            boss_tot += sum(w["b"] for w in wsum)
            fights_out.append(
                {
                    "pull": self.pull_no[fid],
                    "n_windows": len(wins),
                    "window_dmg": [round(w["h"] + w["b"]) for w in wsum],
                    "window_heart": [round(w["h"]) for w in wsum],
                    "window_boss": [round(w["b"]) for w in wsum],
                    "window_dur": [round((b - a) / 1000, 1) for a, b in wins],
                    "heart_total": round(sum(w["h"] for w in wsum)),
                    "burn_total": round(sum(w["h"] + w["b"] for w in wsum)),
                }
            )
        return {
            "players": players,
            "bins": bins,
            "fights": fights_out,
            "windows": windows_out,
            "heart": heart_tot,
            "boss": boss_tot,
            "secs": window_secs,
        }

    # ---- caustic waves ----

    def waves(self) -> dict:
        """Wave casts, hits and deaths, each one dated to a phase.

        The boss throws waves on two different patterns either side of the split
        phase, so a night's wave count is really two counts. Everything before
        the split is phase one, everything after it phase two; a wave inside the
        phase itself would count as phase two, but none has been seen.

        A pull that wipes before the phase has no phase of its own to date, and
        every wave in it is a phase one wave. The night's median start stands in
        for the boundary there: the phase opens at the same point every pull, so
        a pull that ended before it never reached phase two.
        """
        dmg_ids = self.ids_named(spells.WAVE)
        _, phases = self.phases()
        seen = [w[0] for w in phases.values() if w]
        fallback = statistics.median(seen) if seen else None
        per_player = defaultdict(
            lambda: {
                "hits": 0,
                "pulls": set(),
                "taken": 0.0,
                "raw": 0.0,
                "hits_p1": 0,
                "hits_p2": 0,
                "taken_p1": 0.0,
                "taken_p2": 0.0,
            }
        )
        per_pull, deaths = {}, []
        for fid in self.ids:

            def phase_of(ts, fid=fid) -> int:
                win = phases.get(fid)
                edge = win[0] if win else fallback
                return 1 if edge is not None and self.rel(fid, ts) < edge else 2

            hits = defaultdict(list)
            for e in self.taken(fid):
                if e.get("abilityGameID") in dmg_ids and self.player_of(e.get("targetID")):
                    hits[self.player_of(e["targetID"])].append(e)
            tank = nontank = 0
            tank_ph = {1: 0, 2: 0}
            nontank_ph = {1: 0, 2: 0}
            for p, evs in hits.items():
                evs.sort(key=lambda x: x["timestamp"])
                groups = []
                for e in evs:  # one wave sweeping a player = one hit
                    if groups and e["timestamp"] - groups[-1][-1]["timestamp"] <= 2000:
                        groups[-1].append(e)
                    else:
                        groups.append([e])
                per_player[p]["hits"] += len(groups)
                per_player[p]["pulls"].add(fid)
                per_player[p]["taken"] += sum(_amount(x) for x in evs)
                per_player[p]["raw"] += sum(x.get("unmitigatedAmount") or _amount(x) for x in evs)
                for g in groups:
                    ph = phase_of(g[0]["timestamp"])
                    per_player[p][f"hits_p{ph}"] += 1
                    per_player[p][f"taken_p{ph}"] += sum(_amount(x) for x in g)
                    if self.role.get(p) == "tank":
                        tank += 1
                        tank_ph[ph] += 1
                    else:
                        nontank += 1
                        nontank_ph[ph] += 1
            # "cast" only: the log carries a begincast for the same wave, and
            # counting both doubles every wave the page reports
            cast_ts = sorted(
                e["timestamp"]
                for e in self.enemy_casts(fid)
                if e.get("type") == "cast"
                and (
                    e.get("abilityGameID") in dmg_ids
                    or self.ability.get(e.get("abilityGameID")) == spells.WAVE
                )
            )
            casts = len(cast_ts)
            casts_ph = {1: 0, 2: 0}
            volleys_ph = {1: 0, 2: 0}
            last = None
            for ts in cast_ts:
                ph = phase_of(ts)
                casts_ph[ph] += 1
                # casts land in volleys a few seconds wide; a fresh volley is a
                # gap of more than ten seconds
                if last is None or ts - last > 10000:
                    volleys_ph[ph] += 1
                last = ts
            for d in self.deaths(fid):
                if self.ability.get(d.get("killingAbilityGameID")) == spells.WAVE:
                    p = self.player_of(d.get("targetID"))
                    if p:
                        deaths.append(
                            {
                                "fight": self.pull_no[fid],
                                "player": p,
                                "phase": phase_of(d["timestamp"]),
                            }
                        )
            instances = len({e.get("targetInstance", 1) for e in self.vipers(fid)})
            per_pull[fid] = {
                "casts": casts,
                "tank": tank,
                "nontank": nontank,
                "vipers": instances,
                "casts_p1": casts_ph[1],
                "casts_p2": casts_ph[2],
                "volleys_p1": volleys_ph[1],
                "volleys_p2": volleys_ph[2],
                "tank_p1": tank_ph[1],
                "tank_p2": tank_ph[2],
                "nontank_p1": nontank_ph[1],
                "nontank_p2": nontank_ph[2],
            }
        return {"per_player": per_player, "per_pull": per_pull, "deaths": deaths}

    # ---- heavy damage spans ----

    def heavy(self) -> dict:
        out = {}
        for fid in self.ids:
            f = self.fight[fid]
            dur = int((f["endTime"] - f["startTime"]) / 1000) + 1
            per_second = [0.0] * dur
            for e in self.taken(fid):
                if not self.player_of(e.get("targetID")):
                    continue
                s = int(self.rel(fid, e["timestamp"]))
                if 0 <= s < dur:
                    per_second[s] += _amount(e)
            live = [v for v in per_second if v > 0]
            threshold = HEAVY_FACTOR * (statistics.median(live) if live else 1)
            spans, cur = [], None
            for s, v in enumerate(per_second):
                if v >= threshold:
                    if cur and s - cur[1] <= 2:
                        cur[1] = s
                    else:
                        cur = [s, s]
                        spans.append(cur)
            spans = [sp for sp in spans if sp[1] - sp[0] >= HEAVY_MIN_LEN - 1]
            out[fid] = {
                "dur": dur,
                "spans": [tuple(sp) for sp in spans],
                "total": sum(per_second),
                "heavy_total": sum(sum(per_second[a : b + 1]) for a, b in spans),
            }
        return out

    # ---- defensives and consumables ----

    def kind_of(self, ability_id) -> str | None:
        n = self.ability.get(ability_id)
        if n in spells.MAJOR:
            return "maj"
        if n in spells.MINOR:
            return "min"
        if n in spells.EXTERNAL:
            return "ext"
        if n in spells.HEALTHSTONES:
            return "hs"
        if n in spells.HEALTH_POTIONS:
            return "pot"
        return None

    def consumable_heals(self) -> dict:
        """(fight, player, timestamp) -> effective healing, so health at use can be
        read as the value *before* the heal. WCL stamps hitPoints on both the cast
        and the heal as the figure after healing."""
        out = {}
        ids = set()
        for n in spells.HEALTHSTONES | spells.HEALTH_POTIONS:
            ids |= self.ids_named(n)
        for gid in sorted(ids):
            for e in self.f.events_all_fights(f"heal_{gid}", self.ids, "Healing", ability_id=float(gid)):
                if e.get("type") != "heal":
                    continue
                out.setdefault((e["fight"], e.get("targetID")), []).append(
                    (e["timestamp"], e.get("amount", 0))
                )
        return out

    def mitigation(self) -> dict:
        heavy = self.heavy()
        heals = self.consumable_heals()
        total_spans = sum(len(v["spans"]) for v in heavy.values())
        per = defaultdict(
            lambda: {
                "maj": 0,
                "maj_heavy": 0,
                "minor": 0,
                "minor_heavy": 0,
                "ext": 0,
                "ext_heavy": 0,
                "hs": 0,
                "pot": 0,
                "cov": set(),
                "hp": [],
                "minor_spells": Counter(),
                "taken": 0.0,
                "taken_heavy": 0.0,
                "spells": Counter(),
                "deaths": 0,
                "early": 0,
                "early_no_def": 0,
                "pulls_consum": set(),
            }
        )
        stones = Counter()
        for fid in self.ids:
            spans = heavy[fid]["spans"]

            def span_of(ts):
                s = self.rel(fid, ts)
                for i, (a, b) in enumerate(spans):
                    if a - 1 <= s <= b + 1:
                        return i
                return None

            majors_by_player = defaultdict(list)
            for e in self.casts(fid):
                if e.get("type") != "cast":
                    continue
                kind = self.kind_of(e.get("abilityGameID"))
                p = self.player_of(e.get("sourceID"))
                if not kind or not p:
                    continue
                name = self.ability.get(e["abilityGameID"], "")
                si = span_of(e["timestamp"])
                v = per[p]
                if kind == "maj":
                    v["maj"] += 1
                    v["spells"][name] += 1
                    majors_by_player[p].append(e["timestamp"])
                    if si is not None:
                        v["maj_heavy"] += 1
                        v["cov"].add((fid, si))
                elif kind == "min":
                    v["minor"] += 1
                    v["minor_spells"][name] += 1
                    v["minor_heavy"] += si is not None
                elif kind == "ext":
                    v["ext"] += 1
                    v["spells"][name] += 1
                    v["ext_heavy"] += si is not None
                else:
                    v[kind] += 1
                    stones[name] += 1
                    v["pulls_consum"].add(fid)
                    if e.get("maxHitPoints"):
                        near = [
                            (abs(t - e["timestamp"]), amt)
                            for t, amt in heals.get((fid, e.get("sourceID")), [])
                            if abs(t - e["timestamp"]) <= 1500
                        ]
                        healed = min(near)[1] if near else 0
                        before = max(0, e["hitPoints"] - healed)
                        v["hp"].append(100 * before / e["maxHitPoints"])
            for e in self.taken(fid):
                p = self.player_of(e.get("targetID"))
                if not p:
                    continue
                per[p]["taken"] += _amount(e)
                if span_of(e["timestamp"]) is not None:
                    per[p]["taken_heavy"] += _amount(e)
            ds = sorted(self.deaths(fid), key=lambda d: d["timestamp"])
            last = ds[-1]["timestamp"] if ds else 0
            for d in ds:
                p = self.player_of(d.get("targetID"))
                if not p:
                    continue
                per[p]["deaths"] += 1
                if last - d["timestamp"] > EARLY_DEATH:
                    per[p]["early"] += 1
                    if not any(0 <= d["timestamp"] - t <= 10000 for t in majors_by_player[p]):
                        per[p]["early_no_def"] += 1
        return {"per": per, "heavy": heavy, "total_spans": total_spans, "stones": stones}

    # ---- damage taken, per second and per five-second bucket ----

    def dtps(self, heavy) -> dict:
        non_tanks = sorted(p for p in self.players if self.role[p] != "tank")
        idx = {p: i for i, p in enumerate(non_tanks)}
        maxdur = max(v["dur"] for v in heavy.values())
        pulls = {}
        for fid in self.ids:
            f = self.fight[fid]
            dur = heavy[fid]["dur"]
            nb = (dur + DTPS_BUCKET - 1) // DTPS_BUCKET
            raid = [0.0] * dur
            taken = [[0.0] * nb for _ in non_tanks]
            absorb = [[0.0] * nb for _ in non_tanks]
            reduced = [[0.0] * nb for _ in non_tanks]
            for e in self.taken(fid):
                p = self.player_of(e.get("targetID"))
                if p not in idx:
                    continue
                s = int(self.rel(fid, e["timestamp"]))
                if not (0 <= s < dur):
                    continue
                raid[s] += e.get("amount", 0)
                i, b = idx[p], s // DTPS_BUCKET
                taken[i][b] += e.get("amount", 0)
                absorb[i][b] += e.get("absorbed") or 0
                reduced[i][b] += e.get("mitigated") or 0
            ev = []
            for e in self.casts(fid):
                if e.get("type") != "cast":
                    continue
                k = self.kind_of(e.get("abilityGameID"))
                p = self.player_of(e.get("sourceID"))
                if k and p in idx:
                    ev.append(
                        [
                            idx[p],
                            int(self.rel(fid, e["timestamp"])),
                            k,
                            self.ability.get(e["abilityGameID"], ""),
                        ]
                    )
            for d in self.deaths(fid):
                p = self.player_of(d.get("targetID"))
                if p in idx:
                    ev.append([idx[p], int(self.rel(fid, d["timestamp"])), "death", ""])
            pulls[self.pull_no[fid]] = {
                "dur": dur,
                "boss_pct": self.fight[fid]["bossPercentage"],
                "kill": self.fight[fid]["kill"],
                "raid": [round(v / 1000) for v in raid],
                "taken": [[round(v / 1000) for v in r] for r in taken],
                "absorb": [[round(v / 1000) for v in r] for r in absorb],
                "reduced": [[round(v / 1000) for v in r] for r in reduced],
                "ev": ev,
            }
        return {
            "players": non_tanks,
            "tanks": self.tanks,
            "bucket": DTPS_BUCKET,
            "maxdur": maxdur,
            "pulls": pulls,
        }

    # ---- the split phase ----

    def phases(self) -> tuple[dict, dict]:
        """Cast positions per pull, and the seconds the split phase runs.

        The raid sits in two clusters thousands of units apart only while the
        phase runs, so the coordinates date it without a phase-change event. The
        result is cached because both the split section and the wave split
        (phase one waves before it, phase two waves after) read it.
        """
        if self._phases is not None:
            return self._phases
        tracks, phases = {}, {}
        for fid in self.ids:
            pos = defaultdict(list)
            for e in self.casts(fid):
                p = self.player_of(e.get("sourceID"))
                if p is None or e.get("x") is None:
                    continue
                pos[p].append((self.rel(fid, e["timestamp"]), e["x"]))
            tracks[fid] = pos
            buckets = defaultdict(list)
            for p, pts in pos.items():
                for t, x in pts:
                    buckets[int(t / 5)].append(x)
            split_buckets = []
            for b, xs in buckets.items():
                if len(xs) < 6:
                    continue
                s = sorted(xs)
                gap = max(s[i + 1] - s[i] for i in range(len(s) - 1))
                if gap > SPLIT_GAP and s[0] < -CENTRE and s[-1] > CENTRE:
                    split_buckets.append(b)
            phases[fid] = (min(split_buckets) * 5, max(split_buckets) * 5 + 5) if split_buckets else None
        self._phases = (tracks, phases)
        return self._phases

    def split(self) -> dict:
        """The two teams either side of the split phase, and how each side did."""
        tracks, phases = self.phases()

        votes = defaultdict(Counter)
        per_pull = {}
        for fid, win in phases.items():
            if not win:
                per_pull[fid] = None
                continue
            sides = defaultdict(list)
            for p, pts in tracks[fid].items():
                for t, x in pts:
                    if win[0] <= t <= win[1]:
                        sides[p].append(x)
            per_pull[fid] = {"window": win, "x": {p: xs for p, xs in sides.items()}}
            for p, xs in sides.items():
                votes[p]["west" if statistics.median(xs) < 0 else "east"] += 1
        team = {p: c.most_common(1)[0][0] for p, c in votes.items()}

        rows, wrong = [], []
        for fid, v in sorted(per_pull.items()):
            if not v:
                continue
            win = v["window"]
            start_ms = self.fight[fid]["startTime"] + win[0] * 1000
            end_ms = self.fight[fid]["startTime"] + win[1] * 1000
            dmg = self.f.table(f"split_dmg_{fid}", fid, "DamageDone", start=start_ms, end=end_ms)
            heal = self.f.table(f"split_heal_{fid}", fid, "Healing", start=start_ms, end=end_ms)
            agg = {
                s: {
                    "dmg": 0.0,
                    "heal": 0.0,
                    "taken": 0.0,
                    "absorb": 0.0,
                    "reduced": 0.0,
                    "deaths": 0,
                    "iso": 0,
                }
                for s in ("west", "east")
            }
            for e in dmg.get("entries", []):
                s = team.get(e["name"])
                if s:
                    agg[s]["dmg"] += e["total"]
            for e in heal.get("entries", []):
                s = team.get(e["name"])
                if s:
                    agg[s]["heal"] += e["total"]
            for e in self.taken(fid):
                if not (start_ms <= e["timestamp"] <= end_ms):
                    continue
                s = team.get(self.player_of(e.get("targetID")))
                if s:
                    agg[s]["taken"] += e.get("amount", 0)
                    agg[s]["absorb"] += e.get("absorbed") or 0
                    agg[s]["reduced"] += e.get("mitigated") or 0
            ds = [d for d in self.deaths(fid) if start_ms <= d["timestamp"] <= end_ms]
            last = max((d["timestamp"] for d in ds), default=0)
            iso_players = Counter()
            for d in ds:
                s = team.get(self.player_of(d.get("targetID")))
                if not s:
                    continue
                agg[s]["deaths"] += 1
                if last - d["timestamp"] > EARLY_DEATH:
                    agg[s]["iso"] += 1
                    iso_players[self.player_of(d["targetID"])] += 1
            # the boss is untargetable through the phase; the first hit on it
            # afterwards is the moment being back actually starts to matter
            boss_again = None
            for tid in self.boss_ids:
                evs = self.f.events(
                    f"bossafter_{fid}_{tid}",
                    fid,
                    "DamageDone",
                    start=start_ms,
                    end=self.fight[fid]["endTime"],
                    target_id=tid,
                )
                for e in evs:
                    t = self.rel(fid, e["timestamp"])
                    if t > win[1] - 5 and (boss_again is None or t < boss_again):
                        boss_again = t
                        break

            # when each side walked back to the middle
            ret = {}
            for p, pts in tracks[fid].items():
                pts = sorted(pts)
                far = [t for t, x in pts if abs(x) > SPLIT_GAP + 1000 and win[0] <= t <= win[1] + 40]
                if not far:
                    continue
                back = [t for t, x in pts if t > max(far) and abs(x) < CENTRE]
                if back:
                    ret.setdefault(team.get(p), []).append(min(back))
            side_ret = {
                s: {"first": min(v), "median": statistics.median(v), "last": max(v)}
                for s, v in ret.items()
                if s and len(v) >= 4
            }
            stood = {p: ("west" if statistics.median(xs) < 0 else "east") for p, xs in v["x"].items()}
            for p, side in stood.items():
                if team.get(p) and side != team[p]:
                    wrong.append({"pull": fid, "player": p, "went": side, "samples": len(v["x"][p])})
            rows.append(
                {
                    "pull": fid,
                    "window": win,
                    "dur": win[1] - win[0],
                    "agg": agg,
                    "ret": side_ret,
                    "iso_players": dict(iso_players),
                    "boss_again": boss_again,
                    "stood": stood,
                    "sizes": {s: sum(1 for x in stood.values() if x == s) for s in ("west", "east")},
                }
            )
        moves, oneoffs = [], []
        for p in team:
            seq = [(r["pull"], r["stood"].get(p)) for r in rows if r["stood"].get(p)]
            runs: list[list] = []
            for pull, side in seq:
                if runs and runs[-1][0] == side:
                    runs[-1][1].append(pull)
                else:
                    runs.append([side, [pull]])
            # a single pull between two runs of the same side is a wrong turn;
            # anything that sticks is a reassignment
            for i, (side, pulls) in enumerate(runs):
                if len(pulls) == 1 and 0 < i < len(runs) - 1 and runs[i - 1][0] == runs[i + 1][0]:
                    oneoffs.append({"player": p, "pull": pulls[0], "went": side})
            kept = [
                r
                for i, r in enumerate(runs)
                if not (len(r[1]) == 1 and 0 < i < len(runs) - 1 and runs[i - 1][0] == runs[i + 1][0])
            ]
            merged: list[list] = []
            for side, pulls in kept:
                if merged and merged[-1][0] == side:
                    merged[-1][1] += pulls
                else:
                    merged.append([side, list(pulls)])
            for i in range(1, len(merged)):
                moves.append(
                    {
                        "player": p,
                        "from": merged[i - 1][0],
                        "to": merged[i][0],
                        "at": merged[i][1][0],
                        "pulls": len(merged[i][1]),
                    }
                )
        return {
            "team": team,
            "rows": rows,
            "wrong": wrong,
            "moves": moves,
            "oneoffs": oneoffs,
            "phases": {k: v for k, v in phases.items()},
        }

    # ---- everything the page needs ----

    def build(self) -> dict:
        burn = self.burn()
        waves = self.waves()
        mit = self.mitigation()
        heavy = mit["heavy"]
        dtps = self.dtps(heavy)
        split = self.split()

        overall = defaultdict(float)
        for fid in self.ids:
            for e in self.damage_table(fid).get("entries", []):
                overall[e["name"]] += e["total"]
        overall_tot = sum(overall.values())
        burn_tot = burn["heart"] + burn["boss"]

        players = []
        for p in sorted(self.players):
            b = burn["players"].get(p, {"heart": 0.0, "boss": 0.0})
            w = waves["per_player"].get(p)
            total = b["heart"] + b["boss"]
            players.append(
                {
                    "player": p,
                    "class": self.players[p]["subType"],
                    "spec": self.spec.get(p, ""),
                    "role": self.role.get(p, "dps"),
                    "burn_dmg": round(total),
                    "heart_dmg": round(b["heart"]),
                    "boss_dmg": round(b["boss"]),
                    "heart_pct": round(100 * b["heart"] / total, 1) if total else None,
                    "burn_share": round(100 * total / burn_tot, 2) if burn_tot else 0,
                    "burn_dps": round(total / burn["secs"]) if burn["secs"] else 0,
                    "overall_dmg": round(overall.get(p, 0)),
                    "overall_share": round(100 * overall.get(p, 0) / overall_tot, 2) if overall_tot else 0,
                    "delta": round(100 * total / burn_tot - 100 * overall.get(p, 0) / overall_tot, 2)
                    if burn_tot and overall_tot
                    else 0,
                    "wave_hits": w["hits"] if w else 0,
                    "wave_pulls": len(w["pulls"]) if w else 0,
                    "wave_dmg": round(w["taken"]) if w else 0,
                    "wave_raw": round(w["raw"]) if w else 0,
                    "wave_hits_p1": w["hits_p1"] if w else 0,
                    "wave_hits_p2": w["hits_p2"] if w else 0,
                    "wave_dmg_p1": round(w["taken_p1"]) if w else 0,
                    "wave_dmg_p2": round(w["taken_p2"]) if w else 0,
                }
            )

        fights = []
        by_no = {n: fid for fid, n in self.pull_no.items()}
        for f in burn["fights"]:
            fid = by_no[f["pull"]]
            wp = waves["per_pull"][fid]
            fights.append(
                {
                    **f,
                    "dur": round((self.fight[fid]["endTime"] - self.fight[fid]["startTime"]) / 1000),
                    "boss_pct": self.fight[fid]["bossPercentage"],
                    "kill": self.fight[fid]["kill"],
                    "wave_casts": wp["casts"],
                    "wave_hits_tank": wp["tank"],
                    "wave_hits_nontank": wp["nontank"],
                    "wave_casts_p1": wp["casts_p1"],
                    "wave_casts_p2": wp["casts_p2"],
                    "wave_volleys_p1": wp["volleys_p1"],
                    "wave_volleys_p2": wp["volleys_p2"],
                    "wave_hits_nontank_p1": wp["nontank_p1"],
                    "wave_hits_nontank_p2": wp["nontank_p2"],
                    "wave_hits_tank_p1": wp["tank_p1"],
                    "wave_hits_tank_p2": wp["tank_p2"],
                    "vipers": wp["vipers"],
                    "deaths": len(self.deaths(fid)),
                }
            )

        mit_players = []
        for p in sorted(self.players):
            v = mit["per"][p]
            mit_players.append(
                {
                    "player": p,
                    "class": self.players[p]["subType"],
                    "spec": self.spec.get(p, ""),
                    "role": self.role.get(p, "dps"),
                    "maj": v["maj"],
                    "maj_heavy": v["maj_heavy"],
                    "minor": v["minor"],
                    "minor_heavy": v["minor_heavy"],
                    "ext": v["ext"],
                    "ext_heavy": v["ext_heavy"],
                    "coverage": round(100 * len(v["cov"]) / mit["total_spans"], 1)
                    if mit["total_spans"]
                    else 0,
                    "hs": v["hs"],
                    "pot": v["pot"],
                    "consum": v["hs"] + v["pot"],
                    "hp_at_use": round(statistics.mean(v["hp"]), 1) if v["hp"] else None,
                    "taken": round(v["taken"]),
                    "taken_heavy": round(v["taken_heavy"]),
                    "deaths": v["deaths"],
                    "early_deaths": v["early"],
                    "early_no_def": v["early_no_def"],
                    "top_spells": v["spells"].most_common(4),
                    "top_minor": v["minor_spells"].most_common(1),
                }
            )

        split_payload = self._split_payload(split, overall)

        data = {
            "meta": {
                "report": self.code,
                "pulls": len(self.ids),
                "best_pct": min(f["boss_pct"] for f in fights) if fights else None,
                "window_secs": round(burn["secs"]),
                "n_windows": len(burn["windows"]),
                "total_burn": round(burn_tot),
                "total_heart": round(burn["heart"]),
                "total_boss": round(burn["boss"]),
            },
            "players": players,
            "fights": fights,
            "windows": burn["windows"],
            "wave_deaths": waves["deaths"],
        }
        return {
            "payloads": {
                "data": data,
                "bins": burn["bins"],
                "mit": {"players": mit_players, "total_spans": mit["total_spans"]},
                "dtps": dtps,
                "split": split_payload,
            },
            "raw": {
                "burn": burn,
                "waves": waves,
                "mit": mit,
                "heavy": heavy,
                "split": split,
                "overall": dict(overall),
            },
        }

    def _split_payload(self, split, overall) -> dict:
        team = split["team"]
        if not team:
            return {}
        secs = sum(r["dur"] for r in split["rows"])
        tot = {s: Counter() for s in ("west", "east")}
        iso_by_player = Counter()
        for r in split["rows"]:
            for s in ("west", "east"):
                for k, v in r["agg"][s].items():
                    tot[s][k] += v
            iso_by_player.update(r["iso_players"])
        night_tot = sum(overall.get(p, 0) for p in team)
        phase_tot = tot["west"]["dmg"] + tot["east"]["dmg"]
        sides = {}
        for s in ("west", "east"):
            mem = [p for p in team if team[p] == s]
            t = tot[s]
            inc = t["taken"] + t["absorb"] + t["reduced"]
            sides[s] = {
                "members": sorted(mem, key=lambda p: ({"tank": 0, "healer": 1}.get(self.role.get(p), 2), p)),
                "dps": t["dmg"] / secs,
                "hps": t["heal"] / secs,
                "taken_ps": t["taken"] / secs,
                "reduced": 100 * t["reduced"] / inc if inc else 0,
                "absorbed": 100 * t["absorb"] / inc if inc else 0,
                "deaths": int(t["deaths"]),
                "iso_deaths": int(t["iso"]),
                "night_share": 100 * sum(overall.get(p, 0) for p in mem) / night_tot if night_tot else 0,
                "phase_share": 100 * t["dmg"] / phase_tot if phase_tot else 0,
            }
        pulls, first, gaps = [], {"west": 0, "east": 0}, []
        late = {"west": 0, "east": 0}
        for r in split["rows"]:
            row = {
                "pull": self.pull_no[r["pull"]],
                "start": r["window"][0],
                "dur": r["dur"],
                "boss_again": (
                    round(r["boss_again"] - r["window"][0], 1) if r.get("boss_again") is not None else None
                ),
            }
            for s in ("west", "east"):
                ret = r["ret"].get(s)
                row[s] = {
                    "dps": r["agg"][s]["dmg"] / r["dur"],
                    "hps": r["agg"][s]["heal"] / r["dur"],
                    "deaths": r["agg"][s]["deaths"],
                    "first": round(ret["first"] - r["window"][0], 1) if ret else None,
                    "back": round(ret["median"] - r["window"][0], 1) if ret else None,
                    "last": round(ret["last"] - r["window"][0], 1) if ret else None,
                }
                if row[s]["back"] is not None and row["boss_again"] is not None:
                    # judged on the median: a healer trailing back after a res is
                    # not the side being late, the side is back when most of it is
                    row[s]["slack"] = round(row["boss_again"] - row[s]["back"], 1)
                    row[s]["slack_last"] = round(row["boss_again"] - row[s]["last"], 1)
                    if row[s]["slack"] < 0:
                        late[s] += 1
            if row["west"]["back"] is not None and row["east"]["back"] is not None:
                gaps.append(row["west"]["back"] - row["east"]["back"])
                first["west" if row["west"]["back"] < row["east"]["back"] else "east"] += 1
            pulls.append(row)
        for s in ("west", "east"):
            sides[s]["roles"] = Counter(self.role.get(p, "dps") for p in sides[s]["members"])
        sizes = [(r["sizes"]["west"], r["sizes"]["east"]) for r in split["rows"]]
        return {
            "sides": sides,
            "pulls": pulls,
            "secs": secs,
            "first": first,
            "late": late,
            "moves": [{**m, "at": self.pull_no.get(m["at"], m["at"])} for m in split.get("moves", [])],
            "oneoffs": [
                {**o, "pull": self.pull_no.get(o["pull"], o["pull"])} for o in split.get("oneoffs", [])
            ],
            "sizes": sizes,
            "median_gap": round(statistics.median(gaps), 1) if gaps else None,
            "clean": len(gaps),
            "roles": {p: self.role.get(p, "dps") for p in team},
            "spec": {p: self.spec.get(p, "") for p in team},
            "cls": {p: self.players[p]["subType"] for p in team},
            "iso_by_player": dict(iso_by_player),
            "wrong": split["wrong"],
        }
