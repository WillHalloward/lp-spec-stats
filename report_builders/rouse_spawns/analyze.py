"""Where Broodlings surface in each Rouse the Brood, across many logs.

Each Rouse puts up ten Broodlings (fourteen during the race, before a hotfix),
one a second from 1.5 s, five each side. The spots are fixed points in the
room, in three places: the opening arc, and the west and east corners the
bosses surface in after each Submerge (a kill visits both, in either order).
The ten spot centres of each place are learned from every Broodling's first
damaged position across all the logs, so the corners need no guessing.

Sides: the five spots nearest Vexhul are "L", as on the opening arc, where
L1..L5 run from the far end in to the bosses (`twin_fangs.spells.SPOTS`).
Broodlings never log a death or a 0 hp hit, so a Broodling is "gone" at the
last damage it took (on the Piian night a median 2.4 s after its kick).

A Rouse is numbered 1-6 through the fight: two per corner, three corners.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from functools import cached_property

from report_builders.twin_fangs import spells as S

from .fetch import BROODLING, KillFetcher

ROUSE_S = 25.0  # every Broodling of a Rouse has surfaced by then
SIDE_SPOTS = {"L": ["L1", "L2", "L3", "L4", "L5"], "R": ["R5", "R4", "R3", "R2", "R1"]}
SPOTS = SIDE_SPOTS["L"] + SIDE_SPOTS["R"]
ARC_Y = 63000  # opening-arc spots sit north of this; the corners south of it
PLACES = {"arc": "opening arc", "west": "west corner", "east": "east corner"}


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _mean(ps):
    return (sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps))


def read_fight(data: dict) -> list[dict]:
    """The Rouses of one fight, each with its Broodlings in spawn order and
    where each first took damage, in room coordinates."""
    acts = {a["id"]: a["name"] for a in data["actors"]}
    f0 = data["fight"]["startTime"]
    casts, hits = data["casts"], data["hits"]

    rouse_ts = [e["timestamp"] for e in casts if e["type"] == "cast" and e["abilityGameID"] == S.ROUSE]
    vex = [(e["timestamp"], (e["x"], e["y"])) for e in casts
           if acts.get(e.get("sourceID")) == "Vexhul" and "x" in e and e.get("resourceActor", 1) == 1]

    spawn = {}  # instance -> first begincast
    for e in casts:
        if acts.get(e.get("sourceID")) == BROODLING and e["type"] == "begincast":
            spawn.setdefault(e.get("sourceInstance", 1), e["timestamp"])
    first_hit, gone = {}, {}
    for e in hits:
        k = e.get("targetInstance", 1)
        gone[k] = max(gone.get(k, 0), e["timestamp"])
        if "x" in e and e.get("resourceActor", 2) == 2:
            first_hit.setdefault(k, (e["timestamp"], (e["x"], e["y"])))

    rouses = []
    for n, r in enumerate(rouse_ts, 1):
        mine = sorted((t, k) for k, t in spawn.items() if r <= t < r + ROUSE_S * 1000)
        if not mine:
            continue
        adds = []
        for o, (t, k) in enumerate(mine, 1):
            fh = first_hit.get(k)
            d = gone.get(k)
            adds.append({
                "o": o,
                "t": round((t - r) / 1000, 1),
                "d": round((d - r) / 1000, 1) if d else None,
                "pos": fh[1] if fh and fh[0] >= t - 2000 else None,
            })
        v = min(vex, key=lambda p: abs(p[0] - r))[1] if vex else None
        rouses.append({"n": n, "at": round((r - f0) / 1000, 1), "vex": v, "adds": adds})
    return rouses


def place_of(r: dict) -> str | None:
    ps = [a["pos"] for a in r["adds"] if a["pos"]]
    if not ps:
        return None
    m = _mean(ps)
    return "arc" if m[1] > ARC_Y else "west" if m[0] < 0 else "east"


def _kmeans(points, centres, rounds=30):
    for _ in range(rounds):
        groups = defaultdict(list)
        for p in points:
            groups[min(range(len(centres)), key=lambda i: _dist(p, centres[i]))].append(p)
        new = [_mean(groups[i]) if groups[i] else centres[i] for i in range(len(centres))]
        if new == centres:
            break
        centres = new
    return centres


def _farthest_init(points, k):
    c = [max(points, key=lambda p: p[1])]
    while len(c) < k:
        c.append(max(points, key=lambda p: min(_dist(p, q) for q in c)))
    return c


def fit_spots(rouses: list[dict]) -> dict[str, dict[str, tuple[float, float]]]:
    """Ten named spot centres per place, learned from every first-hit position.

    The opening arc starts from `spells.SPOTS` and keeps its names. A corner's
    ten centres are put in order along the arc (from one far end to the
    other), split five and five, and the half nearer Vexhul is L."""
    pts, vex = defaultdict(list), defaultdict(list)
    for r in rouses:
        pl = place_of(r)
        if not pl:
            continue
        pts[pl] += [a["pos"] for a in r["adds"] if a["pos"]]
        if r.get("vex"):
            vex[pl].append(r["vex"])
    out = {}
    for pl, ps in pts.items():
        if pl == "arc":
            names = list(S.SPOTS)
            cs = _kmeans(ps, [S.SPOTS[n] for n in names])
            out[pl] = dict(zip(names, cs))
            continue
        cs = _kmeans(ps, _farthest_init(ps, 10))
        # order along the arc: from one end of the farthest pair, nearest next
        a, _ = max(((p, q) for p in cs for q in cs), key=lambda pq: _dist(*pq))
        chain, left = [a], [c for c in cs if c != a]
        while left:
            nxt = min(left, key=lambda c: _dist(c, chain[-1]))
            chain.append(nxt)
            left.remove(nxt)
        halves = [chain[:5], chain[5:][::-1]]  # each runs outer end -> inner
        v = _mean(vex[pl]) if vex[pl] else (0, 0)
        if _dist(_mean(halves[1]), v) < _dist(_mean(halves[0]), v):
            halves.reverse()
        out[pl] = {f"L{i + 1}": c for i, c in enumerate(halves[0])} | {f"R{i + 1}": c for i, c in enumerate(halves[1])}
    return out


def name_spots(r: dict, model: dict) -> None:
    """Stamp each Broodling with its spot and side (in place)."""
    pl = place_of(r)
    r["place"] = pl
    cs = model.get(pl, {})
    for a in r["adds"]:
        a["s"], a["side"], a["off"] = "?", None, None
        if not a["pos"] or not cs:
            continue
        n, c = min(cs.items(), key=lambda kv: _dist(kv[1], a["pos"]))
        dd = _dist(c, a["pos"])
        a["off"] = round(dd)
        a["side"] = n[0]
        if dd <= S.SPOT_RADIUS:
            a["s"] = n


class Study:
    """Every Rouse in a set of fights, and the patterns across them."""

    def __init__(self, fights: list[dict]) -> None:
        # fights: [{"code", "fid", "label", "kill", "data"}]
        self.fights = []
        for f in fights:
            rs = read_fight(f["data"])
            self.fights.append({**{k: v for k, v in f.items() if k != "data"}, "rouses": rs})
        self.model = fit_spots([r for f in self.fights for r in f["rouses"] if len(r["adds"]) == 10])
        for f in self.fights:
            for r in f["rouses"]:
                name_spots(r, self.model)

    @cached_property
    def rouses(self) -> list[dict]:
        out = []
        for f in self.fights:
            for r in f["rouses"]:
                out.append(_facts({**r, "code": f["code"], "fid": f["fid"], "label": f["label"], "kill": f["kill"]}))
        return out

    def kill_rouses(self) -> list[dict]:
        return [r for r in self.rouses if r["kill"] and r["label"] != NIGHT_LABEL]

    def by_n(self, rouses: list[dict] | None = None) -> list[dict]:
        rows = []
        pool = self.kill_rouses() if rouses is None else rouses
        for n in range(1, 7):
            rs = [r for r in pool if r["n"] == n]
            if not rs:
                continue
            known = [r for r in rs if r["mapped"] >= 8]
            rep = [r for r in known if r["reps"]]
            pairs = [p for r in known for p in r["reps"]]
            rows.append({
                "n": n,
                "corner": (n + 1) // 2,
                "rouses": len(rs),
                "mapped": len(known),
                "alt": sum(r["alt"] for r in rs),
                "sided": sum(1 for r in rs if all(a["side"] for a in r["adds"])),
                "five": sum(r["five"] for r in rs),
                "with_rep": len(rep),
                "pairs": len(pairs),
                "max_on_spot": max((r["max_on_spot"] for r in known), default=0),
                "freed": sum(1 for p in pairs if p["freed"]),
                "gap": dict(Counter(round(p["gap"]) for p in pairs)),
                "opens_left": sum(1 for r in rs if r["adds"][0]["side"] == "L"),
                "expected": round(sum(r["expected"] for r in known), 1),
                "on_living": sum(r["on_living"] for r in known),
            })
        return rows


    def by_order(self) -> list[dict]:
        """Rouses 2, 4 and 6: how often the k-th Broodling on a side lands on a
        spot that side already used, against picking any spot with no
        Broodling still up."""
        acc = defaultdict(lambda: [0, 0, 0.0])
        for r in self.kill_rouses():
            if r["n"] % 2:
                continue
            for i, a in enumerate(r["adds"]):
                if a["s"] == "?":
                    continue
                before = [b for b in r["adds"][:i] if b["side"] == a["side"]]
                if any(b["s"] == "?" for b in before):
                    continue
                living = {b["s"] for b in before if b["d"] is None or b["d"] > a["t"]}
                used = {b["s"] for b in before}
                free = [x for x in SIDE_SPOTS[a["side"]] if x not in living]
                o = acc[len(before) + 1]
                o[0] += 1
                o[1] += a["s"] in used
                o[2] += sum(1 for x in free if x in used) / len(free) if free else 0
        return [{"k": k, "n": v[0], "rep": v[1], "random": round(v[2], 1)} for k, v in sorted(acc.items())]

    def payload(self) -> dict:
        def slim(r):
            return {"n": r["n"], "at": r["at"], "place": r["place"],
                    "adds": [{"o": a["o"], "s": a["s"], "side": a["side"], "t": a["t"], "d": a["d"]} for a in r["adds"]]}

        logs = []
        for f in self.fights:
            if f["label"] == NIGHT_LABEL:
                continue
            logs.append({"label": f["label"], "region": f.get("region"), "code": f["code"], "fid": f["fid"],
                         "dur": f.get("dur"), "date": f.get("date"), "rouses": [slim(r) for r in f["rouses"]]})
        night = []
        for i, f in enumerate([f for f in self.fights if f["label"] == NIGHT_LABEL], 1):
            night += [{**slim(r), "pull": i, "kill": f["kill"]} for r in f["rouses"]]
        kr = self.kill_rouses()
        return {
            "by_n": self.by_n(),
            "night_by_n": self.by_n([r for r in self.rouses if r["label"] == NIGHT_LABEL]),
            "by_order": self.by_order(),
            "kills": len(logs),
            "rouses": len(kr),
            "dates": [min(f["date"] for f in logs), max(f["date"] for f in logs)] if logs else None,
            "regions": dict(Counter(f.get("region") for f in logs)),
            "spots": {pl: {k: [round(v[0]), round(v[1])] for k, v in cs.items()} for pl, cs in self.model.items()},
            "offset_median": sorted(a["off"] for r in kr for a in r["adds"] if a["off"] is not None)[
                len([1 for r in kr for a in r["adds"] if a["off"] is not None]) // 2],
            "logs": logs,
            "night": night,
        }


NIGHT_LABEL = "Piian's Mid-Pressure"


def _facts(r: dict) -> dict:
    adds = r["adds"]
    known = [a for a in adds if a["s"] != "?"]
    r["mapped"] = len(known)
    sides = [a["side"] for a in adds]
    r["count"] = len(adds)
    r["alt"] = all(sides[i] != sides[i - 1] for i in range(1, len(adds)) if sides[i] and sides[i - 1])
    c = Counter(a["side"] for a in adds if a["side"])
    r["five"] = sum(c.values()) == len(adds) and abs(c["L"] - c["R"]) <= len(adds) % 2
    by = defaultdict(list)
    for a in known:
        by[a["s"]].append(a)
    r["by"] = by
    r["max_on_spot"] = max((len(v) for v in by.values()), default=0)
    r["reps"] = [
        {"spot": s, "first": v[i - 1]["o"], "second": v[i]["o"], "gap": round(v[i]["t"] - v[i - 1]["t"], 1),
         "freed": v[i - 1]["d"] is not None and v[i - 1]["d"] <= v[i]["t"]}
        for s, v in by.items() for i in range(1, len(v))
    ]
    # If a Broodling picked any spot on its side with no living Broodling on it,
    # how many repeats would this Rouse have had? And did one ever land on a
    # spot whose Broodling was still alive?
    exp, on_living = 0.0, 0
    for i, a in enumerate(adds):
        if a["s"] == "?" or not a["side"]:
            continue
        before = [b for b in adds[:i] if b["side"] == a["side"]]
        if any(b["s"] == "?" for b in before):
            continue
        living = {b["s"] for b in before if b["d"] is None or b["d"] > a["t"]}
        used = {b["s"] for b in before}
        free = [s for s in SIDE_SPOTS[a["side"]] if s not in living]
        if free:
            exp += sum(1 for s in free if s in used) / len(free)
        on_living += a["s"] in living
    r["expected"] = exp
    r["on_living"] = on_living
    return r


def load(kills: list[dict], night: dict | None = None) -> Study:
    fights = []
    for k in kills:
        code, fid = k["report"]["code"], k["report"]["fightID"]
        try:
            data = KillFetcher(code).kill(fid)
        except Exception:  # noqa: BLE001 — a log that will not load is left out
            continue
        fights.append({"code": code, "fid": fid, "label": (k.get("guild") or {}).get("name", "?"),
                       "region": (k.get("server") or {}).get("region"), "kill": True,
                       "dur": round(k["duration"] / 1000), "date": _day(k["startTime"]), "data": data})
    if night:
        f = KillFetcher(night)
        for x in f.fights()["fights"]:
            if x.get("encounterID") == S_ENCOUNTER and x.get("difficulty") == 5:
                fights.append({"code": night, "fid": x["id"], "label": NIGHT_LABEL, "region": "EU",
                               "kill": bool(x.get("kill")), "data": f.kill(x["id"])})
    return Study(fights)


def _day(ms: float) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d")


S_ENCOUNTER = 3421
