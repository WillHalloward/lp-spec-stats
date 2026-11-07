"""Kill logs for Mythic Twin Fangs off the Warcraft Logs rankings, and the few
events per kill the Rouse spawn pattern needs. Cached on disk under cache/.

Per kill it is the report's fight list plus two event queries limited to the
kill's own window: enemy casts with positions (bosses and Broodlings), and
damage into Broodlings with positions (where each one surfaced, and the hit
that left it on 0 hp). Broodlings write no death events.
"""

from __future__ import annotations

from pathlib import Path

from report_builders.sszorak.fetch import Fetcher as _Base

CACHE_ROOT = Path(__file__).parent / "cache"
ENCOUNTER = 3421
# The last change to Broodlings that bears on where they spawn: Rouse the Brood
# cut from 14 to 10 and Visceral Burst's cast 0.5 s longer (hotfix of
# 15 September 2026). Kills before it run a different fight and are left out.
# (The 5 November cut to Visceral Burst damage changes nothing about spawns.)
SINCE_MS = 1789516800000  # 2026-09-16 00:00 UTC
BROODLING = "Broodling of Ithraz"


class Rankings(_Base):
    """The encounter's kill list, cached like a report under cache/_rankings."""

    def __init__(self) -> None:
        super().__init__("_rankings", CACHE_ROOT)

    def page(self, n: int, difficulty: int = 5, metric: str = "speed", region: str | None = None) -> dict:
        """One page of 50 kills, one per guild. `speed` lists only the fastest
        1000 (20 pages), and those end before the sixth Rouse; a region's own
        list runs further into the slow kills. `progress` orders by kill date,
        which is the race and an older version of the fight."""

        def build():
            q = """query($e:Int!,$d:Int!,$p:Int!,$r:String){worldData{encounter(id:$e){
                     fightRankings(difficulty:$d,page:$p,metric:%s,serverRegion:$r)}}}""" % metric
            v = {"e": ENCOUNTER, "d": difficulty, "p": n, "r": region}
            return self._q(q, v)["worldData"]["encounter"]["fightRankings"]

        key = f"page_{difficulty}_{n}" if metric == "speed" else f"page_{metric}_{difficulty}_{n}"
        if region:
            key += f"_{region}"
        return self.cached(key, build)

    def slow_kills(self, min_s: float, regions=("EU", "US", "CN", "KR", "TW")) -> list[dict]:
        """Every kill at least `min_s` long on the regions' speed lists."""
        out = []
        for reg in regions:
            for n in range(1, 21):
                pg = self.page(n, region=reg)
                out += [r for r in pg.get("rankings", [])
                        if r["duration"] >= min_s * 1000 and r["report"].get("code") and r["startTime"] >= SINCE_MS]
                if not pg.get("hasMorePages"):
                    break
        return out

    def kills(self, n: int, metric: str = "progress") -> list[dict]:
        """The first `n` kills with a public log, one per guild."""
        out, seen, p = [], set(), 1
        while len(out) < n and p <= 20:
            pg = self.page(p, metric=metric)
            for r in pg.get("rankings", []):
                g = (r.get("guild") or {}).get("id")
                if g in seen or not r["report"].get("code"):  # race kills can hide the log
                    continue
                seen.add(g)
                out.append(r)
            if not pg.get("hasMorePages"):
                break
            p += 1
        return out[:n]

    def longest(self, n: int, min_s: float = 370) -> list[dict]:
        """The `n` longest kills on the regions' lists, one per guild: the ones
        that see the most Rouses (the sixth needs about 430 s)."""
        out, seen = [], set()
        for r in sorted(self.slow_kills(min_s), key=lambda r: -r["duration"]):
            g = (r.get("guild") or {}).get("id")
            if g not in seen:
                seen.add(g)
                out.append(r)
        return out[:n]

    def points(self) -> dict:
        return self._q("{rateLimitData{limitPerHour pointsSpentThisHour pointsResetIn}}", {})["rateLimitData"]


class KillFetcher(_Base):
    def __init__(self, code: str) -> None:
        super().__init__(code, CACHE_ROOT)

    def window(self, key: str, fid: int, start: float, end: float, data_type: str, **kw) -> list[dict]:
        """`events` restricted to one fight's window. The base pages from 0, so
        the start time is passed through the filter instead."""
        return self.cached(f"{key}_{fid}", lambda: self._paged(fid, start, end, data_type, **kw))

    def _paged(self, fid, start, end, data_type, hostility=None, filter_expr=None, resources=False):
        q = """
        query($c:String!,$f:[Int]!,$t:EventDataType!,$st:Float!,$en:Float!,$h:HostilityType,
              $fe:String,$res:Boolean){
          reportData{report(code:$c){
            events(fightIDs:$f,dataType:$t,startTime:$st,endTime:$en,limit:10000,
                   hostilityType:$h,filterExpression:$fe,includeResources:$res){data nextPageTimestamp}}}}"""
        out, st = [], float(start)
        while True:
            block = self._q(q, {"c": self.code, "f": [fid], "t": data_type, "st": st, "en": float(end),
                                "h": hostility, "fe": filter_expr, "res": resources})["reportData"]["report"]["events"]
            if block is None:
                return out
            out += block["data"]
            if not block.get("nextPageTimestamp"):
                return out
            st = block["nextPageTimestamp"]

    def kill(self, fid: int) -> dict:
        """The ranking's own times are the kill's end, so the window comes off
        the report's fight list."""
        f = next(x for x in self.fights()["fights"] if x["id"] == fid)
        start, end = f["startTime"], f["endTime"]
        src = f'source.name in ("{BROODLING}", "Ithraz", "Vexhul")'
        return {
            "fight": f,
            "actors": self.actors(),
            "casts": self.window("casts", fid, start, end, "Casts", hostility="Enemies",
                                 filter_expr=src, resources=True),
            "hits": self.window("hits", fid, start, end, "DamageDone", hostility="Friendlies",
                                filter_expr=f'target.name = "{BROODLING}"', resources=True),
        }
