"""Turn one Warcraft Logs report into every number the Entombed Sentinels page shows.

The fight, as the log tells it:

- **Two bosses, two health bars.** Breath of Ula'tek (green) and Blood of
  Ula'tek (red), 40 yards apart or both take 99% less damage (Ula'tek's
  Dominance, which the log writes as a buff on each of them).
- **Vitriolic Stasis** is the intermission. It opens at 46 seconds and then 91
  seconds after the previous one *ends*, so the clock between them is fixed and
  only the intermission's own length moves. During it the lower boss is healed,
  a tick a second, until it matches the higher one: every point of imbalance
  going in is handed back. The heal is in the log as Vitriolic Stasis healing
  events on the boss, so what it cost is measured rather than estimated.
- **Helical Toxins** is the puzzle inside it. Every player gets the debuff; a
  pair that totals four clears together, so a cleared pair is two removals
  sharing a timestamp. Stasis ends about half a second after the last pair
  clears, which makes the intermission's length the puzzle's solve time.
- **Berserk** at 420 seconds, whatever happened before it.

Every query is report-wide (one paged request per data type for all pulls), and
everything below is grouped back into pulls here.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict

from . import spells
from .fetch import Fetcher

DTPS_BUCKET = 5  # seconds per bucket in the damage-taken table
HEAVY_FACTOR = 2  # a heavy second is this many times the pull's median rate
HEAVY_MIN_LEN = 3  # seconds; shorter spikes are noise
# A death counts as solo when the raid was still standing and nobody went down
# beside them (same rule as the Ula'tek page).
SOLO_CLUSTER = 3_000  # ms either side; deaths this close together are one event
SOLO_MASS = 3  # that many in the window means a mechanic killed them, not a mistake
SOLO_ALIVE = 0.70  # this much of the roster still up, or the raid is already going
SPIRIT_OF_REDEMPTION = 27827.0  # holy priest: the death that does not log a death
SPIRIT_GRACE = 5_000  # ms after the buff drops that a logged death is the same one
PAIR_GAP = 150  # ms; two Helical Toxins removals this close are one pair clearing
BLAST_GAP = 100  # ms; Noxious Blast hits this close are one droplet going off
DROPLET_WINDOW = 17_000  # ms after a Toxic Droplets cast; unsoaked ones blow 14.2-15.1s after it
WALKOUT = 15  # seconds after Stasis ends that Dominance is the bosses walking apart
# A puzzle counts as still being played only if it opened with this much of the
# raid up (at most two of twenty dead). Below that the wipe is as good as called,
# and wrong pairings are as likely to be the deliberate kind that end Stasis so
# the bosses can be kited out and reset.
PUZZLE_ALIVE = 0.85


def _amount(e: dict) -> float:
    return (e.get("amount") or 0) + (e.get("absorbed") or 0)


def _clusters(events: list[dict], gap: float) -> list[list[dict]]:
    out: list[list[dict]] = []
    for e in sorted(events, key=lambda x: x["timestamp"]):
        if out and e["timestamp"] - out[-1][-1]["timestamp"] <= gap:
            out[-1].append(e)
        else:
            out.append([e])
    return out


class Analysis:
    def __init__(
        self,
        code: str,
        encounter_id: int | None = None,
        difficulty: int | None = None,
        fight_ids: list[int] | None = None,
        cache_root=None,
    ) -> None:
        self.f = Fetcher(code, cache_root)
        self.code = code
        self.meta = self.f.fights()
        self.actors = {a["id"]: a for a in self.f.actors()}
        self.ability = {a["gameID"]: a["name"] for a in self.f.abilities()}
        self.by_name = defaultdict(set)
        for gid, name in self.ability.items():
            self.by_name[name].add(gid)
        self._owner = {a["id"]: (a.get("petOwner") or a["id"]) for a in self.actors.values()}

        fights = [x for x in self.meta["fights"] if x.get("encounterID")]
        if fight_ids:
            fights = [x for x in fights if x["id"] in fight_ids]
        if encounter_id is None:
            encounter_id = Counter(x["encounterID"] for x in fights).most_common(1)[0][0]
        fights = [x for x in fights if x["encounterID"] == encounter_id]
        if difficulty is None:
            difficulty = Counter(x["difficulty"] for x in fights).most_common(1)[0][0]
        self.fights = [x for x in fights if x["difficulty"] == difficulty]
        self.encounter_id, self.difficulty = encounter_id, difficulty
        self.fight = {x["id"]: x for x in self.fights}
        self.ids = [x["id"] for x in self.fights]
        # Warcraft Logs numbers fights across the whole report, trash included.
        # The page counts pulls on this boss, which is what the raid calls them.
        self.pull_no = {fid: n for n, fid in enumerate(self.ids, 1)}

        self.breath_ids = self._npcs(*spells.BREATH)
        self.blood_ids = self._npcs(*spells.BLOOD)
        self.boss_of = {i: "breath" for i in self.breath_ids} | {i: "blood" for i in self.blood_ids}

        pd = self.f.player_details(self.ids)
        pd = pd.get("data", {}).get("playerDetails", pd) if isinstance(pd, dict) else pd
        self.role, self.spec, self.ilvl = {}, {}, {}
        for role, key in (("tank", "tanks"), ("healer", "healers"), ("dps", "dps")):
            for p in (pd or {}).get(key, []) or []:
                self.role[p["name"]] = role
                self.spec[p["name"]] = (p.get("specs") or [{}])[0].get("spec", "")
                self.ilvl[p["name"]] = p.get("maxItemLevel") or p.get("minItemLevel")
        self.players = {
            a["name"]: a for a in self.actors.values() if a["type"] == "Player" and a["name"] in self.role
        }
        self.tanks = sorted(p for p in self.players if self.role[p] == "tank")
        self._ev: dict = {}
        self._cache: dict = {}

    # ---- small helpers ----

    def name(self, actor_id) -> str | None:
        a = self.actors.get(self._owner.get(actor_id, actor_id))
        return a["name"] if a else None

    def player_of(self, actor_id) -> str | None:
        n = self.name(actor_id)
        return n if n in self.players else None

    def _npcs(self, name: str, game_id: int) -> list[int]:
        return sorted(
            a["id"]
            for a in self.actors.values()
            if a["type"] != "Player" and (a.get("gameID") == game_id or a["name"] == name)
        )

    def ids_named(self, *names: str) -> set[int]:
        out: set[int] = set()
        for n in names:
            out |= self.by_name.get(n, set())
        return out

    def rel(self, fid: int, ts: float) -> float:
        return (ts - self.fight[fid]["startTime"]) / 1000

    def dur(self, fid: int) -> float:
        return (self.fight[fid]["endTime"] - self.fight[fid]["startTime"]) / 1000

    def memo(self, key, build):
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    # ---- raw events, fetched once for every pull and grouped back ----

    def _grouped(self, key: str, data_type: str, **kw) -> dict[int, list[dict]]:
        if key not in self._ev:
            out: dict[int, list[dict]] = defaultdict(list)
            for e in self.f.events(key, self.ids, data_type, **kw):
                if e.get("fight") in self.fight:
                    out[e["fight"]].append(e)
            self._ev[key] = out
        return self._ev[key]

    def casts(self, fid):
        return self._grouped("casts", "Casts", hostility="Friendlies", resources=True)[fid]

    def enemy_casts(self, fid):
        return self._grouped("ecasts", "Casts", hostility="Enemies", resources=True)[fid]

    def enemy_buffs(self, fid):
        return self._grouped("ebuffs", "Buffs", hostility="Enemies")[fid]

    def enemy_heals(self, fid):
        return self._grouped("eheal", "Healing", hostility="Enemies")[fid]

    def debuffs(self, fid):
        return self._grouped("debuffs", "Debuffs", hostility="Friendlies")[fid]

    def taken(self, fid):
        return self._grouped("taken", "DamageTaken", hostility="Friendlies")[fid]

    def deaths(self, fid):
        return [d for d in self._grouped("deaths", "Deaths")[fid] if self.player_of(d.get("targetID"))]

    def dispels(self, fid):
        return self._grouped("dispels", "Dispels", hostility="Friendlies")[fid]

    def spirit(self, fid):
        return self._grouped("sor", "Buffs", ability_id=SPIRIT_OF_REDEMPTION)[fid]

    def damage_table(self, fid: int, start: float | None = None, end: float | None = None) -> dict:
        """Per-player damage with its per-target split, pets rolled into owners."""
        key = f"dmg_{fid}" + (f"_{int(start)}_{int(end)}" if start is not None else "")
        return self.f.table(key, [fid], "DamageDone", start=start, end=end, hostility="Friendlies")

    def ability_events(self, fid, source: str, *names: str, types: tuple = ()) -> list[dict]:
        ids = self.ids_named(*names)
        evs = getattr(self, source)(fid)
        return [e for e in evs if e.get("abilityGameID") in ids and (not types or e.get("type") in types)]

    # ---- the clock: Stasis, phases, berserk ----

    def stasis(self, fid) -> list[tuple[float, float]]:
        """Each Vitriolic Stasis as (start, end) in log milliseconds. One boss's
        buff is enough; both go up and come down together."""
        ids = self.ids_named(spells.STASIS)
        boss = self.blood_ids[0] if self.blood_ids else None
        out: list[list] = []
        for e in self.enemy_buffs(fid):
            if e.get("abilityGameID") not in ids or e.get("targetID") != boss:
                continue
            if e["type"] == "applybuff":
                out.append([e["timestamp"], None])
            elif e["type"] == "removebuff" and out and out[-1][1] is None:
                out[-1][1] = e["timestamp"]
        end = self.fight[fid]["endTime"]
        return [(a, b if b is not None else end) for a, b in out]

    def phases(self, fid) -> list[tuple[float, float]]:
        """The damage phases: the stretches between intermissions."""
        out, at = [], self.fight[fid]["startTime"]
        for a, b in self.stasis(fid):
            out.append((at, a))
            at = b
        if at < self.fight[fid]["endTime"] - 1000:
            out.append((at, self.fight[fid]["endTime"]))
        return out

    def phase_of(self, fid, ts) -> int | None:
        """1-based damage phase a timestamp falls in; None inside an intermission."""
        for i, (a, b) in enumerate(self.phases(fid), 1):
            if a <= ts <= b:
                return i
        return None

    def berserk(self, fid) -> float | None:
        ids = self.ids_named(spells.BERSERK)
        ts = [
            e["timestamp"]
            for e in self.enemy_casts(fid)
            if e.get("abilityGameID") in ids and e["type"] == "cast"
        ]
        return self.rel(fid, min(ts)) if ts else None

    def clock(self) -> dict:
        """Per pull: when each intermission ran, and how much of the pull was spent
        in one rather than damaging the bosses."""
        rows = []
        for fid in self.ids:
            st = [(round(self.rel(fid, a), 1), round(self.rel(fid, b), 1)) for a, b in self.stasis(fid)]
            # an intermission the pull ended inside is not a solve time
            complete = [
                (a, b)
                for (a, b), (_, raw_b) in zip(st, self.stasis(fid))
                if raw_b < self.fight[fid]["endTime"] - 200
            ]
            rows.append(
                {
                    "pull": self.pull_no[fid],
                    "dur": round(self.dur(fid), 1),
                    "boss_pct": self.fight[fid]["bossPercentage"],
                    "kill": self.fight[fid]["kill"],
                    "stasis": st,
                    "solved": [round(b - a, 1) for a, b in complete],
                    "inter_secs": round(sum(b - a for a, b in st), 1),
                    "berserk": self.berserk(fid),
                }
            )
        return {"pulls": rows}

    # ---- health: the two bars and what Stasis hands back ----

    def health(self) -> dict:
        """Boss health off the bosses' own casts, which carry hit points and
        energy, and the Stasis heal off the heal events themselves.

        A cast lands every few seconds per boss, which is plenty for a health
        line. The heal is exact: Vitriolic Stasis healing on the boss, summed
        inside each intermission."""
        heal_ids = self.ids_named(spells.STASIS)
        out, max_hp = {}, None
        for fid in self.ids:
            samples = {"breath": [], "blood": []}
            for e in self.enemy_casts(fid):
                side = self.boss_of.get(e.get("sourceID"))
                if not side or e.get("type") != "cast" or not e.get("maxHitPoints"):
                    continue
                max_hp = e["maxHitPoints"]
                samples[side].append(
                    [
                        round(self.rel(fid, e["timestamp"]), 1),
                        round(100 * e["hitPoints"] / e["maxHitPoints"], 2),
                    ]
                )
            per_stasis = []
            for a, b in self.stasis(fid):
                at = {}
                for side in ("breath", "blood"):
                    # the Stasis cast itself carries the health it went in at
                    pts = [v for t, v in samples[side] if abs(t - self.rel(fid, a)) <= 1.0]
                    if not pts:
                        before = [v for t, v in samples[side] if t <= self.rel(fid, a)]
                        pts = before[-1:]
                    at[side] = pts[0] if pts else None
                healed = {"breath": 0.0, "blood": 0.0}
                for e in self.enemy_heals(fid):
                    side = self.boss_of.get(e.get("targetID"))
                    if side and e.get("abilityGameID") in heal_ids and a <= e["timestamp"] <= b + 1500:
                        healed[side] += e.get("amount") or 0
                per_stasis.append(
                    {
                        "start": round(self.rel(fid, a), 1),
                        "end": round(self.rel(fid, b), 1),
                        "breath": at["breath"],
                        "blood": at["blood"],
                        "gap": round(abs(at["breath"] - at["blood"]), 2)
                        if at["breath"] is not None and at["blood"] is not None
                        else None,
                        "healed": round(healed["breath"] + healed["blood"]),
                        "healed_side": max(healed, key=healed.get) if any(healed.values()) else None,
                        "cut_short": b >= self.fight[fid]["endTime"] - 200,
                    }
                )
            final = {s: (v[-1][1] if v else None) for s, v in samples.items()}
            out[self.pull_no[fid]] = {"samples": samples, "stasis": per_stasis, "final": final}
        return {"pulls": out, "max_hp": max_hp}

    # ---- Ula'tek's Dominance: the bosses too close together ----

    def dominance(self) -> dict:
        """Seconds each pull the bosses spent inside 25 yards of each other, outside
        an intermission (inside one they are already at 99% reduction and it
        costs nothing). The buff refreshes while they stay close, so runs of it
        are merged."""
        ids = self.ids_named(spells.DOMINANCE)
        out = {}
        for fid in self.ids:
            boss = self.breath_ids[0] if self.breath_ids else None
            spans, cur = [], None
            for e in sorted(self.enemy_buffs(fid), key=lambda x: x["timestamp"]):
                if e.get("abilityGameID") not in ids or e.get("targetID") != boss:
                    continue
                if e["type"] == "applybuff" and cur is None:
                    cur = e["timestamp"]
                elif e["type"] == "removebuff" and cur is not None:
                    spans.append((cur, e["timestamp"]))
                    cur = None
            if cur is not None:
                spans.append((cur, self.fight[fid]["endTime"]))
            ends = [b for _, b in self.stasis(fid)]
            rows = []
            for a, b in spans:
                if self.phase_of(fid, a) is None:
                    continue
                after = [a - e for e in ends if 0 <= a - e <= WALKOUT * 1000]
                kind = "walkout" if after else "midphase"
                rows.append(
                    {
                        "t": round(self.rel(fid, a), 1),
                        "secs": round((b - a) / 1000, 1),
                        "kind": kind,
                        "phase": self.phase_of(fid, a),
                    }
                )
            out[self.pull_no[fid]] = rows
        return out

    # ---- teams: who stood on which boss, phase by phase ----

    def teams(self) -> dict:
        """Each player's boss in each damage phase, read off which mark they were
        collecting. The marks only go on players within 40 yards of their boss,
        so they say where a player stood without any coordinates.

        A team is not a boss: the raid opened some pulls with a group on Breath
        and others with the same group on Blood, and every group changes boss
        after every intermission. So a team is the people who stand together,
        found by counting, for every pair of players, the phases they shared a
        side against the phases they did not."""

        def build():
            acid = self.ids_named(spells.MARK_ACID)
            blood = self.ids_named(spells.MARK_BLOOD)
            per_pull = {}
            for fid in self.ids:
                counts = defaultdict(lambda: defaultdict(Counter))
                for e in self.debuffs(fid):
                    if e.get("type") not in ("applydebuff", "applydebuffstack"):
                        continue
                    gid = e.get("abilityGameID")
                    if gid not in acid and gid not in blood:
                        continue
                    p = self.player_of(e.get("targetID"))
                    ph = self.phase_of(fid, e["timestamp"])
                    if p and ph:
                        counts[p][ph]["breath" if gid in acid else "blood"] += 1
                stood = {}
                for p, by_phase in counts.items():
                    stood[p] = {}
                    for ph, c in by_phase.items():
                        side, n = c.most_common(1)[0]
                        # a few stacks of the other mark are the walk across, not a side
                        if n >= 3 and n >= 0.7 * sum(c.values()):
                            stood[p][ph] = side
                per_pull[self.pull_no[fid]] = stood

            together = defaultdict(int)
            seen = Counter()
            for stood in per_pull.values():
                for p in stood:
                    seen[p] += len(stood[p])
                for p in stood:
                    for q in stood:
                        if p >= q:
                            continue
                        for ph, side in stood[p].items():
                            other = stood[q].get(ph)
                            if other:
                                together[(p, q)] += 1 if other == side else -1
            anchor = seen.most_common(1)[0][0] if seen else None

            def with_anchor(p):
                if p == anchor:
                    return 1
                return together.get(tuple(sorted((p, anchor))), 0)

            team = {}
            for p in seen:
                team[p] = "A" if with_anchor(p) >= 0 else "B"
            # whoever never commits to a side (stands between the two, or swaps
            # back and forth) goes in neither
            loose = []
            for p in list(team):
                score = abs(with_anchor(p)) if p != anchor else seen[p]
                if score < 0.4 * seen[p]:
                    loose.append(p)
                    del team[p]

            # each team's side per pull-phase, and who stood on the other one
            sides, off = {}, []
            for n, stood in per_pull.items():
                sides[n] = {}
                phases = sorted({ph for v in stood.values() for ph in v})
                for ph in phases:
                    for t in ("A", "B"):
                        c = Counter(stood[p][ph] for p in stood if team.get(p) == t and ph in stood[p])
                        if c:
                            sides[n].setdefault(ph, {})[t] = c.most_common(1)[0][0]
            # Each player's team pull by pull. The core above fixes which side each
            # team was on; a player belongs to a team in a pull when three in four
            # of their readable phases put them on its side. This is what catches a
            # reassignment partway through the night, which a single night-long
            # vote would read as belonging to neither.
            pull_team = {}
            for n, stood in per_pull.items():
                pull_team[n] = {}
                for p, by_phase in stood.items():
                    votes = Counter()
                    for ph, side in by_phase.items():
                        for t, ts in sides[n].get(ph, {}).items():
                            if ts == side:
                                votes[t] += 1
                    if votes:
                        t, k = votes.most_common(1)[0]
                        if k >= 0.75 * sum(votes.values()):
                            pull_team[n][p] = t
                for p, by_phase in stood.items():
                    t = pull_team[n].get(p)
                    for ph, side in by_phase.items():
                        want = sides[n].get(ph, {}).get(t)
                        if t and want and side != want:
                            off.append({"pull": n, "player": p, "phase": ph, "went": side})

            # A change of team that holds for three pulls or more is a move; a
            # shorter run is noise or a one-pull experiment and is left alone.
            moves, loose = [], []
            night_team = {}
            for p in seen:
                seq = [(n, pull_team[n][p]) for n in sorted(pull_team) if p in pull_team[n]]
                read = len(seq)
                appeared = sum(1 for n in per_pull if p in per_pull[n])
                runs: list[list] = []
                for n, t in seq:
                    if runs and runs[-1][0] == t:
                        runs[-1][1].append(n)
                    else:
                        runs.append([t, [n]])
                # three pulls makes a move; a log shorter than that (a single kill)
                # can only ask for what it has
                held = [r for r in runs if len(r[1]) >= min(3, len(per_pull))]
                merged: list[list] = []
                for t, ns in held:
                    if merged and merged[-1][0] == t:
                        merged[-1][1] += ns
                    else:
                        merged.append([t, list(ns)])
                if not merged or read < 0.6 * appeared or len(merged) > 2:
                    loose.append(p)  # never settles on a team
                    continue
                night_team[p] = Counter(t for _, t in seq).most_common(1)[0][0]
                for i in range(1, len(merged)):
                    moves.append(
                        {"player": p, "from": merged[i - 1][0], "to": merged[i][0], "at": merged[i][1][0]}
                    )
            # a mover's team in the pulls between their runs follows the run it sits in
            return {
                "team": night_team,
                "pull_team": pull_team,
                "loose": sorted(loose),
                "moves": moves,
                "per_pull": per_pull,
                "sides": sides,
                "off": off,
            }

        return self.memo("teams", build)

    def boss_damage(self) -> dict:
        """Damage onto each boss per player, per pull and per damage phase, from
        the damage table (which credits pets to their owners)."""
        out, per_phase = {}, {}
        for fid in self.ids:
            n = self.pull_no[fid]
            rows = {}
            for e in self.damage_table(fid).get("entries", []):
                if e["name"] not in self.players:
                    continue
                t = {x["name"]: x.get("total", 0) for x in e.get("targets", [])}
                rows[e["name"]] = [
                    round(t.get(spells.BREATH[0], 0)),
                    round(t.get(spells.BLOOD[0], 0)),
                    round(t.get(spells.SLIME[0], 0)),
                    round(e.get("total", 0)),
                ]
            out[n] = rows
            per_phase[n] = []
            for i, (a, b) in enumerate(self.phases(fid), 1):
                tab = self.damage_table(fid, a, b)
                ph = {}
                for e in tab.get("entries", []):
                    if e["name"] not in self.players:
                        continue
                    t = {x["name"]: x.get("total", 0) for x in e.get("targets", [])}
                    ph[e["name"]] = [round(t.get(spells.BREATH[0], 0)), round(t.get(spells.BLOOD[0], 0))]
                per_phase[n].append({"phase": i, "secs": round((b - a) / 1000, 1), "players": ph})
        return {"pulls": out, "phases": per_phase}

    def imbalance(self) -> dict:
        """Where the gap between the bosses comes from, phase by phase.

        Only phases that end in an intermission count, because that is the only
        moment the gap is billed. For each one the damage onto each team's own
        boss is split three ways: the team standing on it, the other team
        reaching across the room, and the players who belong to neither. The
        difference between the two bosses is then the sum of three
        differences, which is what the page reports."""
        tm = self.teams()
        bd = self.boss_damage()
        rows = []
        own, cross = Counter(), Counter()
        for fid in self.ids:
            n = self.pull_no[fid]
            ends_in = len(self.stasis(fid))
            for ph in bd["phases"][n]:
                sides = tm["sides"].get(n, {}).get(ph["phase"], {})
                if ph["phase"] > ends_in or "A" not in sides or "B" not in sides:
                    continue
                part = {k: 0.0 for k in ("A_own", "B_own", "A_cross", "B_cross", "float_A", "float_B")}
                for p, (br, bl) in ph["players"].items():
                    on = {"breath": br, "blood": bl}
                    t = tm["pull_team"].get(n, {}).get(p)  # the team they were on this pull
                    a_side, b_side = sides["A"], sides["B"]
                    if t == "A":
                        part["A_own"] += on[a_side]
                        part["A_cross"] += on[b_side]
                        own[p] += on[a_side]
                        cross[p] += on[b_side]
                    elif t == "B":
                        part["B_own"] += on[b_side]
                        part["B_cross"] += on[a_side]
                        own[p] += on[b_side]
                        cross[p] += on[a_side]
                    else:
                        part["float_A"] += on[a_side]
                        part["float_B"] += on[b_side]
                # positive = B's boss took more, so B's boss is the one healed
                rows.append(
                    {
                        "pull": n,
                        "phase": ph["phase"],
                        "secs": ph["secs"],
                        "sides": sides,
                        **{k: round(v) for k, v in part.items()},
                        "teams": round(part["B_own"] - part["A_own"]),
                        "cross": round(part["A_cross"] - part["B_cross"]),
                        "float": round(part["float_B"] - part["float_A"]),
                    }
                )
        return {"rows": rows, "own": dict(own), "cross": dict(cross)}

    # ---- the intermission puzzle ----

    def puzzle(self) -> dict:
        """Helical Toxins, intermission by intermission, read over the debuff's own
        life rather than Stasis's.

        Stasis does not wait for the puzzle. The debuff lasts about 28 seconds and
        keeps going after Stasis ends; whoever still holds it when it runs out
        takes Cultivated Burst. So a solve is every player clearing before the
        debuff expires, and the solve time is the moment the last of them did.

        A clear is any removal before the debuff's expiry that is not that player
        dying. A wrong pairing is any merge that does not make exactly four: the
        only valid touch clears both players on the spot, so a stack going up at
        all (1+1 into two 2s, 1+2 into two 3s, 3+3 into two 6s) is two players
        spending orbs somebody else needed. Two players who went wrong can
        still rescue it (two 2s making four), so an intermission where everyone
        cleared counts as solved, and its wrong pairings are still counted.
        When they do not, the players left holding the debuff are recorded as
        stranded: their partners' orbs were spent, so the failure lands on them
        (Cultivated Burst when it runs out) for a touch they were not part of.
        Every intermission that is not solved gets one of three outcomes, in this
        order:

        - **deaths**: players still holding the debuff died before clearing, and
          the first death came before any wrong pairing; or the intermission
          opened with more than two of the raid dead. Either way the raid was
          going down or the wipe had been called (wrong pairings then are often
          deliberate, to end Stasis so the bosses can be kited out and reset). The raid went down
          mid-puzzle, killed or called, and the puzzle never got its chance.
        - **wrong**: a wrong pairing, before anyone died, and not everyone cleared.
        - **unpaired**: nobody paired wrong and nobody died, but somebody never
          found a partner and held the debuff until it ran out.

        Only the last two are failed solves."""
        hel = self.ids_named(spells.HELICAL)
        burst_debuff = self.ids_named(spells.BURST)
        rows = []
        per_player = defaultdict(
            lambda: {
                "times": [],
                "last": 0,
                "wrong": 0,
                "broke": 0,
                "after": 0,
                "unpaired": 0,
                "stranded": 0,
                "died": 0,
                "solved_in": 0,
            }
        )
        for fid in self.ids:
            downs = self.downs(fid)
            for k, (a, b) in enumerate(self.stasis(fid), 1):
                w_end = a + 31_000
                holders, over, burst, removed, merges = set(), {}, {}, [], []
                for e in sorted(self.debuffs(fid), key=lambda x: x["timestamp"]):
                    if not (a - 1000 <= e["timestamp"] <= w_end + 2000):
                        continue
                    p = self.player_of(e.get("targetID"))
                    if not p:
                        continue
                    gid = e.get("abilityGameID")
                    if gid in hel:
                        if e["type"] == "applydebuff":
                            holders.add(p)
                        elif e["type"] == "applydebuffstack":
                            over.setdefault(p, e["timestamp"])  # any merge that did not clear
                            merges.append(e)
                        elif e["type"] == "removedebuff":
                            removed.append(e)
                    elif gid in burst_debuff and e["type"] == "applydebuff":
                        burst.setdefault(p, e["timestamp"])
                died = {}
                for d in downs:
                    # a death at the debuff's expiry is the burst it ends in, the
                    # result of going unpaired rather than something that broke it
                    if a <= d["t"] <= a + 26_000:
                        died.setdefault(d["player"], d["t"])
                # A clear comes off in a pair: two removals within PAIR_GAP of each
                # other, before the debuff runs out. That holds for corpses too,
                # which keep their counter and can still be bumped and resolved,
                # so a death on its own neither clears nor ends a player's part.
                cleared = {}
                early = [e for e in removed if e["timestamp"] - a <= 26_000]
                for c in _clusters(early, PAIR_GAP):
                    if len(c) >= 2:
                        for e in c:
                            cleared.setdefault(self.player_of(e["targetID"]), e["timestamp"])
                # dead and never resolved: the corpse drops the failure at expiry
                died_holding = {p: t for p, t in died.items() if p in holders and p not in cleared}
                unpaired = sorted(
                    p for p in holders if p not in cleared and p not in over and p not in died_holding
                )
                first_over = min(over.values()) if over else None
                first_death = min(died_holding.values()) if died_holding else None
                if holders and all(p in cleared for p in holders):
                    outcome = "solved"
                elif self.fight[fid]["kill"] and self.fight[fid]["endTime"] < a + 26_000:
                    outcome = "kill"  # the boss died with the puzzle still running
                elif len(holders) < PUZZLE_ALIVE * len(self.players):
                    outcome = "deaths"  # it opened with the raid already going down
                elif died_holding and (first_over is None or first_death < first_over):
                    outcome = "deaths"
                elif over:
                    outcome = "wrong"
                elif unpaired:
                    outcome = "unpaired"
                else:
                    outcome = "deaths"
                # pairs, for the chart: clears landing together
                pairs = []
                for c in _clusters(
                    [e for e in removed if self.player_of(e["targetID"]) in cleared], PAIR_GAP
                ):
                    who = sorted({self.player_of(x["targetID"]) for x in c})
                    pairs.append({"t": round((c[0]["timestamp"] - a) / 1000, 1), "players": who})
                solve = round((max(cleared.values()) - a) / 1000, 1) if outcome == "solved" else None
                for p, t in cleared.items():
                    per_player[p]["times"].append(round((t - a) / 1000, 1))
                if outcome == "solved":
                    last_t = max(cleared.values())
                    for p, t in cleared.items():
                        per_player[p]["solved_in"] += 1
                        if t >= last_t - PAIR_GAP:
                            per_player[p]["last"] += 1
                # The first wrong pairing broke the puzzle only if it was still
                # solvable: the intermission opened with the raid up and nobody
                # had died unresolved before it. Every merge after that, and every
                # merge in a puzzle already lost, is put down as after the fact:
                # that covers a called wipe (pairing wrong on purpose to end Stasis
                # so the bosses can be kited out and reset) and a cascade alike,
                # which the log cannot tell apart.
                solvable = (
                    len(holders) >= PUZZLE_ALIVE * len(self.players)
                    and first_over is not None
                    and (first_death is None or first_over < first_death)
                )
                broke = {p for p, t in over.items() if solvable and t - first_over <= PAIR_GAP}
                for p in over:
                    per_player[p]["wrong"] += 1
                    per_player[p]["broke" if p in broke else "after"] += 1
                # after a wrong pairing, whoever never cleared was left without the
                # orbs they needed: they take the failure for somebody else's touch
                stranded = unpaired if over else []
                for p in unpaired:
                    per_player[p]["stranded" if over else "unpaired"] += 1
                for p in died_holding:
                    per_player[p]["died"] += 1
                rows.append(
                    {
                        "pull": self.pull_no[fid],
                        "idx": k,
                        "start": round(self.rel(fid, a), 1),
                        "len": round((b - a) / 1000, 1),
                        "outcome": outcome,
                        "solve": solve,
                        "players": len(holders),
                        "cleared": len(cleared),
                        "pairs": pairs,
                        "over": sorted(over),
                        "rescued": sorted(p for p in over if p in cleared),
                        "broke": sorted(broke),
                        # every merge, for the detail view: who touched, when, and the stacks it left
                        "merges": [
                            {
                                "t": round((c[0]["timestamp"] - a) / 1000, 1),
                                "players": sorted({self.player_of(x["targetID"]) for x in c}),
                                "stack": max(x.get("stack", 0) for x in c),
                            }
                            for c in _clusters(merges, PAIR_GAP)
                        ],
                        "died_t": {p: round((t - a) / 1000, 1) for p, t in died_holding.items()},
                        "stranded": stranded,
                        "first_over": round((first_over - a) / 1000, 1) if first_over else None,
                        "unpaired": unpaired,
                        "died": sorted(died_holding),
                        "first_death": round((first_death - a) / 1000, 1) if first_death else None,
                        "burst": sorted(burst),
                        "pull_end": round((self.fight[fid]["endTime"] - a) / 1000, 1),
                        "half": round(
                            statistics.median(sorted(cleared.values()))
                            and (statistics.median(sorted(cleared.values())) - a) / 1000,
                            1,
                        )
                        if cleared
                        else None,
                    }
                )
        return {"rows": rows, "per_player": per_player}

    # ---- Breath's side: droplets, slime, living venom ----

    def droplets(self) -> dict:
        """Toxic Droplets casts and what became of them. A soak is a Toxic Droplets
        damage hit; a droplet nobody ran over is one Noxious Blast going off,
        which hits the whole raid at once, so a blast is a cluster of hits.

        Each set also records how many players were up when its first blast
        landed and how many the blasts killed. A blast kills several people in
        the same instant, so the solo-death rule (fewer than three down within
        three seconds) never counts one; whether the raid was standing has to be
        read off the set itself. `to_stasis` is how long after the cast the next
        Stasis opened: the set cast just before one blows up while the raid is
        moving to the middle."""
        cast_ids = self.ids_named(spells.DROPLETS)
        blast_ids = self.ids_named(spells.NOXIOUS)
        rows, soaks = [], Counter()
        for fid in self.ids:
            casts = sorted(
                e["timestamp"]
                for e in self.enemy_casts(fid)
                if e.get("type") == "cast"
                and e.get("abilityGameID") in cast_ids
                and self.boss_of.get(e.get("sourceID"))
            )
            soak_ev = [
                e
                for e in self.taken(fid)
                if e.get("abilityGameID") in cast_ids and self.player_of(e.get("targetID"))
            ]
            blast_ev = [
                e
                for e in self.taken(fid)
                if e.get("abilityGameID") in blast_ids and self.player_of(e.get("targetID"))
            ]
            blasts = _clusters(blast_ev, BLAST_GAP)
            downs = self.downs(fid)
            roster = len(self.players) or 1
            stasis_starts = [a for a, _ in self.stasis(fid)]
            for i, c in enumerate(casts):
                nxt = casts[i + 1] if i + 1 < len(casts) else c + DROPLET_WINDOW
                end = min(c + DROPLET_WINDOW, nxt)
                mine_s = [e for e in soak_ev if c <= e["timestamp"] < end]
                mine_b = [bl for bl in blasts if c <= bl[0]["timestamp"] < end]
                for e in mine_s:
                    soaks[self.player_of(e["targetID"])] += 1
                alive = killed = None
                if mine_b:
                    b0, b1 = mine_b[0][0]["timestamp"], mine_b[-1][-1]["timestamp"]
                    alive = roster - len({d["player"] for d in downs if d["t"] < b0 - 200})
                    killed = sum(
                        1 for d in downs if b0 - 200 <= d["t"] <= b1 + 1500 and d["ability"] == spells.NOXIOUS
                    )
                nxt_stasis = [a for a in stasis_starts if a > c]
                rows.append(
                    {
                        "pull": self.pull_no[fid],
                        "t": round(self.rel(fid, c), 1),
                        "phase": self.phase_of(fid, c),
                        "soaks": len(mine_s),
                        "soakers": len({e["targetID"] for e in mine_s}),
                        "blasts": len(mine_b),
                        "blast_dmg": round(sum(_amount(e) for bl in mine_b for e in bl)),
                        "alive": alive,
                        "killed": killed,
                        "to_stasis": round((nxt_stasis[0] - c) / 1000, 1) if nxt_stasis else None,
                        "pull_end": round((self.fight[fid]["endTime"] - c) / 1000, 1),
                    }
                )
        return {"casts": rows, "soaks": dict(soaks)}

    def soakers(self) -> dict:
        """Who ran over the droplets, and how quickly.

        Every set is twenty droplets, and every one of them is accounted for:
        either somebody runs it over (one Toxic Droplets hit on one player, never
        shared) or it goes off as Noxious Blast. Soak hits plus blasts come to
        twenty on every complete set, in this night and in the kill logs alike,
        so a hit *is* a droplet and nothing here is estimated.

        A set counts towards a player's opportunities only if they were alive
        when it was cast and the pull lasted long enough for it to blow."""
        cast_ids = self.ids_named(spells.DROPLETS)
        blast_ids = self.ids_named(spells.NOXIOUS)
        per = defaultdict(lambda: {"pre": 0, "other": 0, "sets": 0, "times": []})
        sets = []
        for fid in self.ids:
            n = self.pull_no[fid]
            downs = self.downs(fid)
            starts = [a for a, _ in self.stasis(fid)]
            casts = sorted(
                e["timestamp"]
                for e in self.enemy_casts(fid)
                if e.get("type") == "cast"
                and e.get("abilityGameID") in cast_ids
                and self.boss_of.get(e.get("sourceID"))
            )
            soak = [
                e
                for e in self.taken(fid)
                if e.get("abilityGameID") in cast_ids and self.player_of(e.get("targetID"))
            ]
            blasts = _clusters(
                [
                    e
                    for e in self.taken(fid)
                    if e.get("abilityGameID") in blast_ids and self.player_of(e.get("targetID"))
                ],
                BLAST_GAP,
            )
            for c in casts:
                if self.fight[fid]["endTime"] - c < DROPLET_WINDOW:
                    continue  # the pull ended before this set could blow
                nxt = [a for a in starts if a > c]
                pre = bool(nxt) and nxt[0] - c <= 15_000
                gone = {d["player"] for d in downs if d["t"] < c}
                for p in self.players:
                    if p not in gone:
                        per[p]["sets"] += 1
                mine = [e for e in soak if c <= e["timestamp"] < c + DROPLET_WINDOW]
                for e in mine:
                    p = self.player_of(e["targetID"])
                    per[p]["pre" if pre else "other"] += 1
                    per[p]["times"].append(round((e["timestamp"] - c) / 1000, 2))
                sets.append(
                    {
                        "pull": n,
                        "t": round(self.rel(fid, c), 1),
                        "pre": pre,
                        "alive": len(self.players) - len(gone),
                        "soaked": len(mine),
                        "blasts": sum(1 for b in blasts if c <= b[0]["timestamp"] < c + DROPLET_WINDOW),
                        "times": sorted(round((e["timestamp"] - c) / 1000, 2) for e in mine),
                        "phase": self.phase_of(fid, c),
                        "who": [self.player_of(e["targetID"]) for e in mine],
                    }
                )
        return {"per": per, "sets": sets}

    # ---- Blood's side: miasma, blighted blood, the pools ----

    def miasma(self) -> list[dict]:
        """Each Unstable Miasma going off: how many shared it and what each took."""
        ids = self.ids_named(spells.MIASMA)
        out = []
        for fid in self.ids:
            hits = [
                e
                for e in self.taken(fid)
                if e.get("abilityGameID") in ids and self.player_of(e.get("targetID"))
            ]
            for c in _clusters(hits, 500):
                amounts = [_amount(e) for e in c]
                out.append(
                    {
                        "pull": self.pull_no[fid],
                        "t": round(self.rel(fid, c[0]["timestamp"]), 1),
                        "soakers": len({e["targetID"] for e in c}),
                        "per": round(statistics.mean(amounts)),
                        "players": sorted({self.player_of(e["targetID"]) for e in c}),
                    }
                )
        return out

    def blighted(self) -> dict:
        """Blighted Blood from landing to dispel, and who dispelled it."""
        ids = self.ids_named(spells.BLIGHTED)
        rows, by_dispeller = [], Counter()
        for fid in self.ids:
            on = {}
            disp = {}
            for e in self.dispels(fid):
                if e.get("extraAbilityGameID") in ids:
                    disp[(e.get("targetID"), round(e["timestamp"] / 100))] = self.player_of(e.get("sourceID"))
            for e in sorted(self.debuffs(fid), key=lambda x: x["timestamp"]):
                if e.get("abilityGameID") not in ids:
                    continue
                if e["type"] == "applydebuff":
                    on[e["targetID"]] = e["timestamp"]
                elif e["type"] == "removedebuff" and e["targetID"] in on:
                    t0 = on.pop(e["targetID"])
                    who = None
                    for dt in (0, -1, 1):
                        who = who or disp.get((e["targetID"], round(e["timestamp"] / 100) + dt))
                    if who:
                        by_dispeller[who] += 1
                    rows.append(
                        {
                            "pull": self.pull_no[fid],
                            "secs": round((e["timestamp"] - t0) / 1000, 1),
                            "dispelled": bool(who),
                            "by": who,
                            "on": self.player_of(e["targetID"]),
                        }
                    )
        return {"rows": rows, "by_dispeller": dict(by_dispeller)}

    def avoidable(self) -> dict:
        """Per-player hits from the things a player can step out of or around."""
        names = {
            "living": spells.LIVING_VENOM,
            "pool": spells.BLOOD_VENOM,
            "eruption": spells.ERUPTION,
            "blast": spells.NOXIOUS,
        }
        per = defaultdict(lambda: {k: 0 for k in names} | {f"{k}_dmg": 0.0 for k in names})
        for fid in self.ids:
            for key, nm in names.items():
                ids = self.ids_named(nm)
                if key == "pool":
                    # the pools tick as a debuff; standing in one is the application
                    for e in self.debuffs(fid):
                        if e.get("abilityGameID") in ids and e["type"] == "applydebuff":
                            p = self.player_of(e.get("targetID"))
                            if p:
                                per[p]["pool"] += 1
                    for e in self.taken(fid):
                        if e.get("abilityGameID") in ids:
                            p = self.player_of(e.get("targetID"))
                            if p:
                                per[p]["pool_dmg"] += _amount(e)
                    continue
                for e in self.taken(fid):
                    if e.get("abilityGameID") in ids:
                        p = self.player_of(e.get("targetID"))
                        if p:
                            per[p][key] += 1
                            per[p][f"{key}_dmg"] += _amount(e)
        return per

    def living_venom(self) -> dict:
        """Living Venom, per player: hits, where they stood when hit, and what the
        hits led to.

        A hit is a Living Venom damage event, ticks on one player within a second
        grouped as one. The side is read off the marks (`teams()`), so a hit is
        filed under the boss the player was standing on in that phase. Hits are
        also set against time alive in damage phases, so a player who died early
        on most pulls is not made to look careful by having had less time to be
        hit. `then_died` counts a hit followed by that player's death within
        five seconds, whatever the killing blow."""
        ids = self.ids_named(spells.LIVING_VENOM)
        tm = self.teams()
        per = defaultdict(
            lambda: {
                "hits": 0,
                "breath": 0,
                "blood": 0,
                "unknown": 0,
                "alive": 0.0,
                "killed": 0,
                "then_died": 0,
                "dmg": 0.0,
            }
        )
        per_pull, per_phase, phase_secs = {}, Counter(), Counter()
        for fid in self.ids:
            n = self.pull_no[fid]
            for i, (a, b) in enumerate(self.phases(fid), 1):
                phase_secs[i] += (b - a) / 1000
            downs = self.downs(fid)
            died = {}
            for d in downs:
                died.setdefault(d["player"], d["t"])
            for p in self.players:
                end = died.get(p, self.fight[fid]["endTime"])
                per[p]["alive"] += sum(max(0, min(b, end) - a) for a, b in self.phases(fid)) / 1000
            raw = defaultdict(list)
            for e in self.taken(fid):
                if e.get("abilityGameID") in ids:
                    p = self.player_of(e.get("targetID"))
                    if p:
                        raw[p].append(e)
            count = 0
            for p, evs in raw.items():
                for g in _clusters(evs, 1000):
                    t = g[0]["timestamp"]
                    ph = self.phase_of(fid, t)
                    side = tm["per_pull"].get(n, {}).get(p, {}).get(ph) if ph else None
                    v = per[p]
                    v["hits"] += 1
                    v[side or "unknown"] += 1
                    v["dmg"] += sum(_amount(e) for e in g)
                    if ph:
                        per_phase[ph] += 1
                    if p in died and 0 <= died[p] - t <= 5000:
                        v["then_died"] += 1
                    count += 1
            for d in downs:
                if d["ability"] == spells.LIVING_VENOM:
                    per[d["player"]]["killed"] += 1
            per_pull[n] = count
        return {
            "per": per,
            "per_pull": per_pull,
            "per_phase": dict(per_phase),
            # hits per minute of each phase, so a long phase two is not read as a worse one
            "phase_rate": {
                k: round(60 * per_phase[k] / phase_secs[k], 2) for k in per_phase if phase_secs[k]
            },
        }

    # ---- Shifting Protovenom ----

    def protovenom(self) -> dict:
        """Each Shifting Protovenom: who carried it, which pairs met cleanly, and
        every Protovenom Eruption, pinned to the carrier who caused it and the
        clean player they ran into.

        Who was marked at the moment of an eruption is read off the debuff, not
        off the set: a player who has already cleared is clean again and can be
        the one walked into. The eruption hits are fetched with positions. For
        each clean player an eruption hit, the carrier is the nearest player
        still marked, placed by their own eruption hit or, when the eruption
        missed them, by their nearest cast within a second and a half. The
        clean player nearest each carrier is the one they touched; anyone else
        clean it hit was caught in it. A burst of hits can be two eruptions in
        two corners of the room, which is why this works per clean player
        rather than per burst."""
        debuff = self.ids_named(spells.PROTOVENOM)
        erupt = self.ids_named(spells.ERUPTION)
        erupt_ev = []
        for gid in sorted(erupt):
            erupt_ev += self.f.events(
                f"erupt_res_{gid}",
                self.ids,
                "DamageTaken",
                ability_id=float(gid),
                hostility="Friendlies",
                resources=True,
            )
        by_fight = defaultdict(list)
        for e in erupt_ev:
            if e.get("fight") in self.fight and self.player_of(e.get("targetID")):
                by_fight[e["fight"]].append(e)

        rows = []
        carriers, touched, caught, times_marked = Counter(), Counter(), Counter(), Counter()
        pairs_out = Counter()
        unattributed = 0
        for fid in self.ids:
            spans = defaultdict(list)
            sets = []
            for e in sorted(self.debuffs(fid), key=lambda x: x["timestamp"]):
                if e.get("abilityGameID") not in debuff:
                    continue
                p = self.player_of(e.get("targetID"))
                if not p:
                    continue
                if e["type"] == "applydebuff":
                    if not sets or e["timestamp"] - sets[-1]["t0"] > 5000:
                        sets.append({"t0": e["timestamp"], "players": set(), "removed": []})
                    sets[-1]["players"].add(p)
                    spans[p].append([e["timestamp"], None])
                    times_marked[p] += 1
                elif e["type"] == "removedebuff":
                    if spans[p] and spans[p][-1][1] is None:
                        spans[p][-1][1] = e["timestamp"]
                    if sets:
                        sets[-1]["removed"].append(e)

            def marked_at(p, t, spans=spans):
                for s0, s1 in spans.get(p, []):
                    if s0 <= t + 50 and (s1 is None or s1 >= t - 50):
                        return s0
                return None

            casts_pos = defaultdict(list)
            for e in self.casts(fid):
                q = self.player_of(e.get("sourceID"))
                if q and e.get("x") is not None:
                    casts_pos[q].append((e["timestamp"], e["x"], e["y"]))

            def where(p, t, hit_pos, casts_pos=casts_pos):
                if p in hit_pos:
                    return hit_pos[p]
                near = [(abs(ts - t), x, y) for ts, x, y in casts_pos.get(p, []) if abs(ts - t) <= 1500]
                return (min(near)[1], min(near)[2]) if near else None

            collisions = []
            for c in _clusters([e for e in by_fight[fid] if e.get("x") is not None], 300):
                t = c[0]["timestamp"]
                hit_pos = {}
                for e in c:
                    hit_pos.setdefault(self.player_of(e["targetID"]), (e["x"], e["y"]))
                live = {p: s0 for p in spans if (s0 := marked_at(p, t)) is not None}
                clean = [p for p in hit_pos if p not in live]
                if not clean:
                    continue  # only marked players hit: the same eruption's carrier side
                places = {p: where(p, t, hit_pos) for p in live}
                by_carrier = defaultdict(list)
                for q in clean:
                    near = sorted(
                        (math.dist(hit_pos[q], xy), p) for p, xy in places.items() if xy is not None
                    )
                    if near and near[0][0] <= 1500:
                        by_carrier[near[0][1]].append((near[0][0], q))
                    else:
                        unattributed += 1
                        collisions.append({"t": t, "carrier": None, "touched": q, "caught": [], "dist": None})
                for p, qs in by_carrier.items():
                    qs.sort()
                    collisions.append(
                        {
                            "t": t,
                            "carrier": p,
                            "touched": qs[0][1],
                            "caught": [q for _, q in qs[1:]],
                            "dist": round(qs[0][0] / 100, 1),
                            "marked_for": round((t - live[p]) / 1000, 1),
                        }
                    )

            for s in sets:
                done = [c for c in _clusters(s["removed"], PAIR_GAP) if len(c) == 2]
                mine = [c for c in collisions if s["t0"] <= c["t"] <= s["t0"] + 15000]
                for c in mine:
                    if c["carrier"]:
                        carriers[c["carrier"]] += 1
                        pairs_out[(c["carrier"], c["touched"])] += 1
                    touched[c["touched"]] += 1
                    for q in c["caught"]:
                        caught[q] += 1
                rows.append(
                    {
                        "pull": self.pull_no[fid],
                        "t": round(self.rel(fid, s["t0"]), 1),
                        "marked": len(s["players"]),
                        "pairs": len(done),
                        "pair_secs": round(
                            statistics.median([(c[0]["timestamp"] - s["t0"]) / 1000 for c in done]), 1
                        )
                        if done
                        else None,
                        "eruptions": [
                            {**c, "t": round(self.rel(fid, c["t"]), 1), "phase": self.phase_of(fid, c["t"])}
                            for c in mine
                        ],
                    }
                )
        return {
            "rows": rows,
            "carriers": dict(carriers),
            "victims": dict(touched),
            "caught": dict(caught),
            "marked": dict(times_marked),
            "pairs": [[p, q, n] for (p, q), n in pairs_out.most_common()],
            "unattributed": unattributed,
        }

    # ---- the marks ----

    def marks(self) -> dict:
        """Mark of Acid and Mark of Blood: damage, peak stacks and deaths, per player."""
        acid = self.ids_named(spells.MARK_ACID)
        blood = self.ids_named(spells.MARK_BLOOD)
        per = defaultdict(lambda: {"dmg": 0.0, "peak": 0, "deaths": 0})
        peaks_by_phase = defaultdict(list)  # phase number -> peak stack per player-phase
        for fid in self.ids:
            peak = defaultdict(int)
            for e in self.debuffs(fid):
                gid = e.get("abilityGameID")
                if gid not in acid and gid not in blood:
                    continue
                p = self.player_of(e.get("targetID"))
                if not p:
                    continue
                s = e.get("stack", 1) if e["type"] == "applydebuffstack" else 1
                ph = self.phase_of(fid, e["timestamp"])
                if ph:
                    peak[(p, ph)] = max(peak[(p, ph)], s)
                per[p]["peak"] = max(per[p]["peak"], s)
            for (p, ph), s in peak.items():
                peaks_by_phase[ph].append(s)
            for e in self.taken(fid):
                if e.get("abilityGameID") in acid or e.get("abilityGameID") in blood:
                    p = self.player_of(e.get("targetID"))
                    if p:
                        per[p]["dmg"] += _amount(e)
            for d in self.deaths(fid):
                if d.get("killingAbilityGameID") in acid or d.get("killingAbilityGameID") in blood:
                    per[self.player_of(d["targetID"])]["deaths"] += 1
        return {"per": per, "peaks_by_phase": {k: statistics.median(v) for k, v in peaks_by_phase.items()}}

    def wrong_marks(self) -> dict:
        """Mark stacks from the boss a player's team was not on, and the damage
        they added.

        The marks are not cleared by Stasis; each simply runs out forty seconds
        after it was last applied, so after every swap a player carries their
        old boss's stacks for twenty-odd seconds. That part is the fight and is
        not counted. What is counted is any new application from the old boss,
        or from the other boss in phase one, which only happens within forty
        yards of it: it restarts the timer and adds a stack.

        Each one is one of three kinds: during the walk-out (within ten seconds
        of Stasis ending, while everyone is crossing over), extending an old
        mark still running later in the phase, or a fresh mark picked up from
        the other boss (standing in the middle, or going over). The extra damage
        is the wrong mark's actual damage from the first wrong application to
        the next phase, less what the old stacks would have done had they been
        left to run out (the last tick before it, repeated until the old mark's
        expiry). Tick damage climbs faster than the stack count, so a few extra
        stacks late in a phase cost more than the count suggests."""
        tm = self.teams()
        marks = {"breath": self.ids_named(spells.MARK_ACID), "blood": self.ids_named(spells.MARK_BLOOD)}
        per = defaultdict(
            lambda: {"walk": 0, "extended": 0, "fresh": 0, "phases": 0, "extra": 0.0, "mark": 0.0}
        )
        events = []
        for fid in self.ids:
            n = self.pull_no[fid]
            phases = self.phases(fid)
            ends = [b for _, b in self.stasis(fid)]
            for p in self.players:
                team = tm["pull_team"].get(n, {}).get(p)
                for side, ids in marks.items():
                    auras = sorted(
                        (
                            e
                            for e in self.debuffs(fid)
                            if e.get("abilityGameID") in ids and self.player_of(e.get("targetID")) == p
                        ),
                        key=lambda e: e["timestamp"],
                    )
                    apps = [e for e in auras if e["type"] in ("applydebuff", "applydebuffstack")]
                    ticks = sorted(
                        (
                            e
                            for e in self.taken(fid)
                            if e.get("abilityGameID") in ids and self.player_of(e.get("targetID")) == p
                        ),
                        key=lambda e: e["timestamp"],
                    )
                    per[p]["mark"] += sum(_amount(e) for e in ticks)
                    for i, (ps, pe) in enumerate(phases, 1):
                        sides = tm["sides"].get(n, {}).get(i, {})
                        own = sides.get(team) if team else tm["per_pull"].get(n, {}).get(p, {}).get(i)
                        if own is None or own == side:
                            continue
                        bad = [e for e in apps if ps <= e["timestamp"] <= pe]
                        if not bad:
                            continue
                        for e in bad:
                            since = min(
                                ((e["timestamp"] - x) / 1000 for x in ends if x <= e["timestamp"]),
                                default=None,
                            )
                            if since is not None and since <= 10:
                                kind = "walk"
                            elif e["type"] == "applydebuffstack":
                                kind = "extended"
                            else:
                                kind = "fresh"
                            per[p][kind] += 1
                            events.append(
                                {
                                    "pull": n,
                                    "phase": i,
                                    "t": round(self.rel(fid, e["timestamp"]), 1),
                                    "into": round((e["timestamp"] - ps) / 1000, 1),
                                    "player": p,
                                    "kind": kind,
                                    "stack": e.get("stack", 1),
                                }
                            )
                        first = bad[0]["timestamp"]
                        window_end = phases[i][0] if i < len(phases) else self.fight[fid]["endTime"]
                        legit = [e for e in apps if e["timestamp"] < ps]
                        expiry = legit[-1]["timestamp"] + 40_000 if legit else first
                        before = [e for e in ticks if e["timestamp"] < first]
                        last = _amount(before[-1]) if before and expiry > first else 0
                        win = [e for e in ticks if first <= e["timestamp"] < window_end]
                        actual = sum(_amount(e) for e in win)
                        would = sum(last for e in win if e["timestamp"] <= expiry)
                        per[p]["extra"] += max(0.0, actual - would)
                        per[p]["phases"] += 1
        return {"per": per, "events": events}

    # ---- deaths ----

    def downs(self, fid: int) -> list[dict]:
        """Every time a player went down in a pull, in order. Spirit of Redemption
        counts as the moment a holy priest died, because the log writes a death
        only when the buff runs out, and none at all if the pull ends first."""
        spans, out = [], []
        for e in self.spirit(fid):
            p = self.player_of(e.get("targetID"))
            if not p:
                continue
            if e.get("type") == "applybuff":
                spans.append([p, e["timestamp"], None])
                out.append({"player": p, "t": e["timestamp"], "spirit": True, "ability": None})
            elif e.get("type") == "removebuff":
                for span in spans:
                    if span[0] == p and span[2] is None:
                        span[2] = e["timestamp"]
        for d in self.deaths(fid):
            p = self.player_of(d.get("targetID"))
            if any(
                sp == p and start <= d["timestamp"] <= (end or start) + SPIRIT_GRACE
                for sp, start, end in spans
            ):
                # the same incident; keep the killing blow the death names
                for o in out:
                    if o["player"] == p and o["spirit"] and o["ability"] is None:
                        o["ability"] = self.ability.get(d.get("killingAbilityGameID"))
                continue
            out.append(
                {
                    "player": p,
                    "t": d["timestamp"],
                    "spirit": False,
                    "ability": self.ability.get(d.get("killingAbilityGameID")),
                }
            )
        return sorted(out, key=lambda x: x["t"])

    def solo_downs(self, fid: int) -> list[dict]:
        """The ones that were not the raid falling over."""
        ds = self.downs(fid)
        roster = len(self.players) or 1
        out = []
        for i, d in enumerate(ds):
            together = sum(1 for o in ds if abs(o["t"] - d["t"]) <= SOLO_CLUSTER)
            gone = len({o["player"] for o in ds[:i]})
            if together < SOLO_MASS and (roster - gone) / roster >= SOLO_ALIVE:
                out.append(d)
        return out

    def death_summary(self) -> dict:
        """Killing blows per pull, the first death of every pull, and what each
        player died to across the night."""
        per_pull, firsts, per_player = {}, [], defaultdict(Counter)
        for fid in self.ids:
            ds = self.downs(fid)
            solo = {(d["player"], d["t"]) for d in self.solo_downs(fid)}
            per_pull[self.pull_no[fid]] = [
                {
                    "player": d["player"],
                    "t": round(self.rel(fid, d["t"]), 1),
                    "ability": d["ability"] or "Spirit of Redemption",
                    "solo": (d["player"], d["t"]) in solo,
                }
                for d in ds
            ]
            for d in ds:
                per_player[d["player"]][d["ability"] or "Spirit of Redemption"] += 1
            if ds:
                d = ds[0]
                firsts.append(
                    {
                        "pull": self.pull_no[fid],
                        "player": d["player"],
                        "t": round(self.rel(fid, d["t"]), 1),
                        "ability": d["ability"] or "Spirit of Redemption",
                        "phase": self.phase_of(fid, d["t"]),
                    }
                )
        return {"per_pull": per_pull, "firsts": firsts, "per_player": per_player}

    # ---- heavy damage spans, defensives, consumables, damage taken ----

    def heavy(self) -> dict:
        def build():
            out = {}
            for fid in self.ids:
                dur = int(self.dur(fid)) + 1
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

        return self.memo("heavy", build)

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
        """(fight, player) -> [(timestamp, effective heal)], so health at use can be
        read as the value *before* the heal. WCL stamps hitPoints on the cast as
        the figure after healing."""
        ids = self.ids_named(*(spells.HEALTHSTONES | spells.HEALTH_POTIONS))
        out = {}
        for gid in sorted(ids):
            for e in self.f.events(
                f"heal_{gid}", self.ids, "Healing", ability_id=float(gid), hostility="Friendlies"
            ):
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
                "spells": Counter(),
                "deaths": 0,
                "early": 0,
                "early_no_def": 0,
                "spirit": 0,
                "early_spirit": 0,
                "pulls_consum": set(),
            }
        )
        stones = Counter()
        for fid in self.ids:
            spans = heavy[fid]["spans"]

            def span_of(ts, fid=fid, spans=spans):
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
            for d in self.downs(fid):
                per[d["player"]]["deaths"] += 1
                if d["spirit"]:
                    per[d["player"]]["spirit"] += 1
            for d in self.solo_downs(fid):
                p = d["player"]
                per[p]["early"] += 1
                if d["spirit"]:
                    per[p]["early_spirit"] += 1
                if not any(0 <= d["t"] - t <= 10000 for t in majors_by_player[p]):
                    per[p]["early_no_def"] += 1
        return {"per": per, "heavy": heavy, "total_spans": total_spans, "stones": stones}

    def dtps(self) -> dict:
        heavy = self.heavy()
        non_tanks = sorted(p for p in self.players if self.role[p] != "tank")
        idx = {p: i for i, p in enumerate(non_tanks)}
        maxdur = max(v["dur"] for v in heavy.values())
        pulls = {}
        tm = self.teams()
        drop_ids = self.ids_named(spells.DROPLETS)
        for fid in self.ids:
            dur = heavy[fid]["dur"]
            nb = (dur + DTPS_BUCKET - 1) // DTPS_BUCKET
            raid = [0.0] * dur
            n = self.pull_no[fid]

            def side_at(p, ts, n=n, fid=fid):
                """The boss a player stood beside at this moment: their team's side
                that phase, or their own marks when they had no team that pull.
                None in an intermission, when everybody is in the middle."""
                ph = self.phase_of(fid, ts)
                if ph is None:
                    return None
                team = tm["pull_team"].get(n, {}).get(p)
                if team:
                    return tm["sides"].get(n, {}).get(ph, {}).get(team)
                return tm["per_pull"].get(n, {}).get(p, {}).get(ph)

            by_side = {"breath": [0.0] * dur, "blood": [0.0] * dur}
            # each non-tank's side per bucket: B Breath, R Blood, . neither
            side_str = []
            for p in non_tanks:
                chars = []
                for b in range(nb):
                    sd = side_at(p, self.fight[fid]["startTime"] + (b * DTPS_BUCKET + DTPS_BUCKET / 2) * 1000)
                    chars.append({"breath": "B", "blood": "R"}.get(sd, "."))
                side_str.append("".join(chars))
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
                sd = side_at(p, e["timestamp"])
                if sd:
                    by_side[sd][s] += e.get("amount", 0)
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
                "stasis": [[round(self.rel(fid, a)), round(self.rel(fid, b))] for a, b in self.stasis(fid)],
                "raid": [round(v / 1000) for v in raid],
                "raid_breath": [round(v / 1000) for v in by_side["breath"]],
                "raid_blood": [round(v / 1000) for v in by_side["blood"]],
                "side": side_str,
                # what each side's spikes are: Breath's droplet sets, Blood's Miasma going off
                "marks": {
                    "drop": sorted(
                        round(self.rel(fid, e["timestamp"]), 1)
                        for e in self.enemy_casts(fid)
                        if e.get("type") == "cast"
                        and e.get("abilityGameID") in drop_ids
                        and self.boss_of.get(e.get("sourceID"))
                    ),
                    "miasma": [m["t"] for m in self.memo("miasma", self.miasma) if m["pull"] == n],
                },
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

    def lust(self) -> list[float]:
        ids = self.ids_named(*spells.LUST)
        out = []
        for fid in self.ids:
            ts = [
                e["timestamp"]
                for e in self.casts(fid)
                if e.get("type") == "cast" and e.get("abilityGameID") in ids
            ]
            if ts:
                out.append(round(self.rel(fid, min(ts)), 1))
        return out

    # ---- one pull in a line, the same for a prog pull and a public kill ----

    def pull_summary(self, fid: int) -> dict:
        """The figures the comparison with public kills is made on, measured the
        same way for both, so a kill log and a prog night are read identically."""
        n = self.pull_no[fid]
        clock = next(r for r in self.clock()["pulls"] if r["pull"] == n)
        hp = self.memo("health", self.health)
        heal = sum(s["healed"] for s in hp["pulls"][n]["stasis"])
        dom = self.memo("dominance", self.dominance)[n]
        drops = [c for c in self.memo("droplets", self.droplets)["casts"] if c["pull"] == n]
        pv = [r for r in self.memo("protovenom", self.protovenom)["rows"] if r["pull"] == n]
        boss = 0.0
        for e in self.damage_table(fid).get("entries", []):
            for x in e.get("targets", []):
                if x["name"] in (spells.BREATH[0], spells.BLOOD[0]):
                    boss += x.get("total", 0)
        phase_secs = sum((b - a) / 1000 for a, b in self.phases(fid))
        # boss damage per second phase by phase, so a kill and a wipe can be
        # compared on the same stretch rather than on whole-pull averages that
        # a wipe's dead last minute drags down
        phase_dps = []
        for a, b in self.phases(fid):
            dmg = 0.0
            for e in self.damage_table(fid, a, b).get("entries", []):
                for x in e.get("targets", []):
                    if x["name"] in (spells.BREATH[0], spells.BLOOD[0]):
                        dmg += x.get("total", 0)
            phase_dps.append(round(dmg / ((b - a) / 1000)) if b > a else 0)
        early = self.fight[fid]["startTime"] + 150_000
        ilvls = [self.ilvl[p] for p in self.players if self.ilvl.get(p)]
        comp = Counter(self.role[p] for p in self.players)
        return {
            "dur": round(self.dur(fid), 1),
            "kill": self.fight[fid]["kill"],
            "boss_pct": self.fight[fid]["bossPercentage"],
            "stasis": len(self.stasis(fid)),
            "solved": clock["solved"],
            "inter_secs": clock["inter_secs"],
            "phase_secs": round(phase_secs, 1),
            "healed": round(heal),
            "gaps": [s["gap"] for s in hp["pulls"][n]["stasis"]],
            "dom_secs": round(sum(r["secs"] for r in dom), 1),
            "droplet_casts": len(drops),
            "blasts": sum(c["blasts"] for c in drops),
            "pv_sets": len(pv),
            "pv_pairs": sum(r["pairs"] for r in pv),
            "eruptions": sum(len(r["eruptions"]) for r in pv),
            "deaths": len(self.downs(fid)),
            "deaths_150": sum(1 for d in self.downs(fid) if d["t"] <= early),
            "phase_dps": phase_dps,
            "boss_dmg": round(boss),
            "boss_dps": round(boss / phase_secs) if phase_secs else 0,
            "max_hp": hp["max_hp"],
            "ilvl_median": round(statistics.median(ilvls)) if ilvls else None,
            "comp": [comp.get("tank", 0), comp.get("healer", 0), comp.get("dps", 0)],
        }
