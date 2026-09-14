"""Everything this report needs out of the Warcraft Logs v2 API, cached on disk.

Raw responses are cached per report code, so a re-run after a template or stats
change costs nothing and a half-finished run resumes where it stopped. Delete
the cache directory to force a refetch.

Queries are report-wide (every pull in one paged query per ability) rather than
per-fight: a fifteen-pull night is eight requests instead of a hundred.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

import wcl

CACHE_ROOT = Path(__file__).parent / "cache"

# This endpoint throws gateway errors under load, and 504s outright when fights
# and masterData are asked for together — hence the retries and the split queries.
RETRY_STATUS = (429, 502, 503, 504)


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

    # ---- transport ----

    def _q(self, query: str, variables: dict) -> dict:
        """One GraphQL call, retrying the gateway errors this endpoint throws."""
        last: Exception | None = None
        for attempt in range(4):
            try:
                token = self.client._get_token()
                resp = requests.post(
                    wcl.GRAPHQL_URL,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"query": query, "variables": variables},
                    timeout=180,
                )
                if resp.status_code in RETRY_STATUS:
                    time.sleep(5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                body = resp.json()
                if body.get("errors"):
                    raise RuntimeError(f"WCL GraphQL errors: {body['errors']}")
                return body["data"]
            except requests.RequestException as exc:  # transport, not GraphQL
                last = exc
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"WCL request failed after retries: {last}")

    # ---- queries ----

    def fights(self) -> dict:
        def build():
            q = """
            query($c:String!){reportData{report(code:$c){
              title startTime endTime visibility
              owner{name} guild{name} zone{id name}
              fights{id name encounterID difficulty kill bossPercentage fightPercentage
                     startTime endTime}}}}"""
            return self._q(q, {"c": self.code})["reportData"]["report"]
        return self.cached("fights", build)

    def actors(self) -> list[dict]:
        def build():
            q = """query($c:String!){reportData{report(code:$c){
                     masterData{actors{id name type subType}}}}}"""
            return self._q(q, {"c": self.code})["reportData"]["report"]["masterData"]["actors"]
        return self.cached("actors", build)

    def abilities(self) -> list[dict]:
        def build():
            q = """query($c:String!){reportData{report(code:$c){
                     masterData{abilities{gameID name}}}}}"""
            return self._q(q, {"c": self.code})["reportData"]["report"]["masterData"]["abilities"]
        return self.cached("abilities", build)

    def player_details(self, fight_ids: list[int]) -> Any:
        def build():
            q = """query($c:String!,$f:[Int]!){reportData{report(code:$c){
                     playerDetails(fightIDs:$f, includeCombatantInfo:true)}}}"""
            return self._q(q, {"c": self.code, "f": fight_ids})["reportData"]["report"]["playerDetails"]
        return self.cached("player_details", build)

    def damage_table(self, fight_ids: list[int]) -> dict:
        """Per-player damage with its per-target split and active time."""
        def build():
            q = """query($c:String!,$f:[Int]!){reportData{report(code:$c){
                     table(dataType:DamageDone,fightIDs:$f,startTime:0,endTime:100000000000,
                           hostilityType:Friendlies)}}}"""
            return self._q(q, {"c": self.code, "f": fight_ids})["reportData"]["report"]["table"]["data"]
        return self.cached("damage_table", build)

    def events(self, key: str, fight_ids: list[int], data_type: str, *,
               ability_id: float | None = None, hostility: str | None = None) -> list[dict]:
        """One paged events query across every pull, cached under `key`."""
        def build():
            q = """
            query($c:String!,$f:[Int]!,$t:EventDataType!,$st:Float!,$ab:Float,$h:HostilityType){
              reportData{report(code:$c){
                events(fightIDs:$f,dataType:$t,startTime:$st,endTime:100000000000,limit:10000,
                       abilityID:$ab,hostilityType:$h){data nextPageTimestamp}}}}"""
            out: list[dict] = []
            st = 0.0
            while True:
                block = self._q(q, {"c": self.code, "f": fight_ids, "t": data_type,
                                    "st": st, "ab": ability_id, "h": hostility}
                                )["reportData"]["report"]["events"]
                if block is None:  # no events of this type in these fights
                    return out
                out += block["data"]
                if not block.get("nextPageTimestamp"):
                    return out
                st = block["nextPageTimestamp"]
        return self.cached(key, build)
