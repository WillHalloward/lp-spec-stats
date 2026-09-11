"""Everything this report needs out of the Warcraft Logs v2 API, cached on disk.

Raw responses are cached per report code, so a re-run after a template or stats
change costs nothing and a half-finished run resumes where it stopped. Delete
the cache directory to force a refetch.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import wcl

CACHE_ROOT = Path(__file__).parent / "cache"


class Fetcher:
    def __init__(self, code: str, cache_root: Path | None = None) -> None:
        self.code = code
        self.client = wcl.WclClient()
        self.dir = (cache_root or CACHE_ROOT) / code
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- cache ----

    def cached(self, key: str, build: Callable[[], Any]) -> Any:
        path = self.dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        value = build()
        path.write_text(json.dumps(value), encoding="utf-8")
        return value

    # ---- queries ----

    def _q(self, query: str, variables: dict) -> dict:
        return self.client.query(query, variables)

    def meta(self) -> dict:
        """Fights, actors and the report's ability names."""
        def build():
            q = """
            query($c:String!){reportData{report(code:$c){
              title startTime endTime
              zone{id name}
              fights{id name encounterID difficulty kill bossPercentage fightPercentage
                     startTime endTime friendlyPlayers}
              masterData{
                actors{id name type subType petOwner gameID}
                abilities{gameID name}
              }
            }}}"""
            return self._q(q, {"c": self.code})["reportData"]["report"]
        return self.cached("meta", build)

    def player_details(self, fight_ids: list[int]) -> dict:
        def build():
            q = """query($c:String!,$f:[Int]!){reportData{report(code:$c){
                     playerDetails(fightIDs:$f)}}}"""
            return self._q(q, {"c": self.code, "f": fight_ids})["reportData"]["report"]["playerDetails"]
        return self.cached("player_details", build)

    def events(self, key: str, fight_id: int, data_type: str, *, start: float | None = None,
               end: float = 1e11, ability_id: float | None = None, target_id: int | None = None,
               hostility: str | None = None, resources: bool = False) -> list[dict]:
        """One paged events query, cached under `key`."""
        def build():
            q = """
            query($c:String!,$f:[Int]!,$t:EventDataType!,$st:Float!,$en:Float!,
                  $ab:Float,$tid:Int,$h:HostilityType,$res:Boolean!){
              reportData{report(code:$c){
                events(fightIDs:$f,dataType:$t,startTime:$st,endTime:$en,limit:10000,
                       abilityID:$ab,targetID:$tid,hostilityType:$h,includeResources:$res){
                  data nextPageTimestamp}}}}"""
            out: list[dict] = []
            st = float(start) if start is not None else 0.0
            while True:
                r = self._q(q, {"c": self.code, "f": [fight_id], "t": data_type, "st": st, "en": float(end),
                                "ab": ability_id, "tid": target_id, "h": hostility, "res": resources}
                            )["reportData"]["report"]["events"]
                out += r["data"]
                if r.get("nextPageTimestamp"):
                    st = r["nextPageTimestamp"]
                else:
                    return out
        return self.cached(key, build)

    def events_all_fights(self, key: str, fight_ids: list[int], data_type: str,
                          *, ability_id: float | None = None) -> list[dict]:
        def build():
            q = """
            query($c:String!,$f:[Int]!,$t:EventDataType!,$st:Float!,$ab:Float){
              reportData{report(code:$c){
                events(fightIDs:$f,dataType:$t,startTime:$st,endTime:100000000,limit:10000,
                       abilityID:$ab,hostilityType:Friendlies,includeResources:true){
                  data nextPageTimestamp}}}}"""
            out: list[dict] = []
            st = 0.0
            while True:
                r = self._q(q, {"c": self.code, "f": fight_ids, "t": data_type, "st": st, "ab": ability_id}
                            )["reportData"]["report"]["events"]
                out += r["data"]
                if r.get("nextPageTimestamp"):
                    st = r["nextPageTimestamp"]
                else:
                    return out
        return self.cached(key, build)

    def table(self, key: str, fight_id: int, data_type: str, *, start: float | None = None,
              end: float | None = None) -> dict:
        def build():
            q = """
            query($c:String!,$f:[Int]!,$t:TableDataType!,$st:Float,$en:Float){
              reportData{report(code:$c){table(dataType:$t,fightIDs:$f,startTime:$st,endTime:$en)}}}"""
            return self._q(q, {"c": self.code, "f": [fight_id], "t": data_type,
                               "st": start, "en": end})["reportData"]["report"]["table"]["data"]
        return self.cached(key, build)
