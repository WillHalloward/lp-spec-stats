# Rouse spawn pattern builder

Builds `/reports/twin-fangs-rouse-spawns`: where the ten Broodlings of each
Twin Fangs Rouse the Brood surface, read from the longest Mythic kills on
Warcraft Logs plus one of our own nights.

```bash
export WCL_CLIENT_ID=... WCL_CLIENT_SECRET=...
python -m report_builders.rouse_spawns.build --out /tmp/preview.html   # look first
python -m report_builders.rouse_spawns.build --publish
```

`--kills` (default 80) and `--night` (default `gfvXpCWVRj43anTH`). Everything is
cached under `cache/`; about 7 API points a kill.

## Reading the logs

- **Which kills**: each region's speed ranking, kills after the 15 September 2026
  hotfix (`fetch.SINCE_MS`: Rouse the Brood cut from 14 to 10, Visceral Burst
  0.5 s slower), longest first, one per guild, so each reaches the sixth Rouse
  (about 430 s). The global top 1000 ends before that; a region's list goes further.
- **Spots**: fixed room points in three places, the opening arc and the west and
  east corners the bosses surface in after each Submerge. The ten centres of each
  are learned (k-means) from every Broodling's first damaged position; positions
  land a median 0.5 yd from their spot. The arc keeps `twin_fangs.spells.SPOTS`'
  names; a corner's spots are ordered along the arc and the half nearer Vexhul is L.
- **Gone**: a kicked Broodling dives at once, so its kick; one nobody kicked, its last direct hit.
  Damage-over-time ticks log for a few seconds after the dive and are ignored.
- **Rouse number**: 1-6 through the fight, two per place.
