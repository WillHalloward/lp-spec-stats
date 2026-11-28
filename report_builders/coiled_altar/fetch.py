"""Everything this report needs out of the Warcraft Logs v2 API, cached on disk.

The paging/caching machinery is generic, so it is reused from the Ula'tek
builder rather than copied; only the queries this encounter needs live here.
Raw responses are cached per report code under `cache/`, so a re-run after a
template or wording change costs nothing. Delete the directory to refetch.
"""

from __future__ import annotations

from pathlib import Path

from report_builders.ulatek.fetch import Fetcher as _BaseFetcher

CACHE_ROOT = Path(__file__).parent / "cache"


class Fetcher(_BaseFetcher):
    """Base fetcher plus the two things this encounter needs that Ula'tek did not:
    phase transitions per pull, and the boss-side buff stream."""

    def __init__(self, code: str, cache_root: Path | None = None) -> None:
        super().__init__(code, cache_root or CACHE_ROOT)

    def phases(self) -> dict:
        """Phase definitions plus each fight's transition timestamps.

        Returned as {"defs": {encounterID: [{id, name, isIntermission}]},
                     "fights": {fightID: [{id, startTime}]}}.
        """

        def build():
            q = """
            query($c:String!){reportData{report(code:$c){
              phases{encounterID phases{id name isIntermission}}
              fights(killType:All){id startTime endTime kill fightPercentage
                                   phaseTransitions{id startTime}}
            }}}"""
            r = self._q(q, {"c": self.code})["reportData"]["report"]
            return {
                "defs": {p["encounterID"]: p["phases"] for p in (r["phases"] or [])},
                "fights": {x["id"]: (x["phaseTransitions"] or []) for x in r["fights"]},
            }

        return self.cached("phases", build)

    def enemy_buffs(self, fight_id: int) -> list[dict]:
        """Buffs on the bosses and their adds: the shield, the bind, the regen."""
        return self.events(f"enemy_buffs-{fight_id}", fight_id, "Buffs", hostility="Enemies")

    def enemy_casts(self, fight_id: int) -> list[dict]:
        return self.events(f"enemy_casts-{fight_id}", fight_id, "Casts", hostility="Enemies")

    def player_casts(self, fight_id: int) -> list[dict]:
        """With resources, so a healthstone cast carries the caster's hit points
        and health at the moment of use can be recovered."""
        return self.events(
            f"player_casts_r-{fight_id}", fight_id, "Casts", hostility="Friendlies", resources=True
        )

    def player_buffs(self, fight_id: int) -> list[dict]:
        return self.events(f"player_buffs-{fight_id}", fight_id, "Buffs", hostility="Friendlies")

    def debuffs(self, fight_id: int) -> list[dict]:
        return self.events(f"debuffs-{fight_id}", fight_id, "Debuffs", hostility="Friendlies")

    def taken(self, fight_id: int) -> list[dict]:
        """Damage taken by the raid, with resources so we get hit points and position."""
        return self.events(
            f"taken-{fight_id}", fight_id, "DamageTaken", hostility="Friendlies", resources=True
        )

    def done(self, fight_id: int) -> list[dict]:
        """Damage the raid dealt, for the shield break and the burn window.

        With resources: on these events `resourceActor` is 2, so `hitPoints` and
        `maxHitPoints` belong to the *target*, which is how boss health is read.
        """
        return self.events(
            f"done_r-{fight_id}", fight_id, "DamageDone", hostility="Friendlies", resources=True
        )

    def deaths(self, fight_id: int) -> list[dict]:
        return self.events(f"deaths-{fight_id}", fight_id, "Deaths", hostility="Friendlies")

    def enemy_heals(self, fight_id: int) -> list[dict]:
        """Healing done by the bosses: the regeneration, the soul reclaims, and
        the shield absorbs, which log here rather than as damage."""
        return self.events(f"enemy_heal-{fight_id}", fight_id, "Healing", hostility="Enemies")

    def heals(self, fight_id: int) -> list[dict]:
        """Healing on the raid, used to recover health at the moment a healthstone
        or potion was pressed."""
        return self.events(f"heals-{fight_id}", fight_id, "Healing", hostility="Friendlies")

    def source_events(self, fight_id: int, source_id: int) -> list[dict]:
        """Every event one actor is the source of in a fight, with positions.

        The orb spawners (Coalesced Venom Stalker, Virulent Mutation) log each
        orb as a cast with x/y; nothing else this builder fetches carries them.
        The API ignores `targetID` here but honours `sourceID`.
        """

        def build():
            q = """
            query($c:String!,$f:[Int]!,$st:Float!,$en:Float!,$sid:Int){reportData{report(code:$c){
              events(fightIDs:$f,dataType:All,startTime:$st,endTime:$en,limit:10000,
                     sourceID:$sid,includeResources:true){data nextPageTimestamp}}}}"""
            fight = next(x for x in self.meta()["fights"] if x["id"] == fight_id)
            out: list[dict] = []
            st = float(fight["startTime"])
            while True:
                r = self._q(q, {"c": self.code, "f": [fight_id], "st": st,
                                "en": float(fight["endTime"]), "sid": source_id})["reportData"]["report"]["events"]
                out += r["data"]
                if not r.get("nextPageTimestamp"):
                    return out
                st = r["nextPageTimestamp"]

        return self.cached(f"src{source_id}-{fight_id}", build)
