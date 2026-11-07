# Twin Fangs prog-night report builder

Turns one Warcraft Logs report of Mythic Twin Fangs pulls into the page served
at `/reports/<slug>`. The page is about **where the pulls broke**: every pull
on one clock, then the mechanics that end them.

```bash
export WCL_CLIENT_ID=... WCL_CLIENT_SECRET=...
python -m report_builders.twin_fangs.build --report gfvXpCWVRj43anTH \
    --date 2026-11-05 --night "Piian's Mid-Pressure progression night" \
    --out /tmp/preview.html          # look first
python -m report_builders.twin_fangs.build --report <code> ... --publish
```

Same flags as the other builders (`--slug`, `--title`, `--summary`, `--team`,
`--encounter`, `--difficulty`). Everything is cached under `cache/<code>/`.
Pulls are numbered 1..n within the boss, not by Warcraft Logs fight id.

## Reading the log

- **Wipe**: starts at the first death of the first run of 4 deaths within 8 s.
  Deaths and mechanics from there on are not held against anyone. A kill has none.
- **Death cause**: the killing ability. Toxic Fumes / Rouse the Brood / Stagger
  kills are blamed on the biggest real hit in the 5 s before.
- **Broodling spots**: ten fixed spots, five per side (`spells.SPOTS`). They
  move with the bosses (after Submerge the pair sits in a corner), so a
  Broodling's first-damaged position is put in the frame the two bosses make
  at that Rouse, tried both ways round (a half turn, not a mirror, so the
  raid's left stays left), and matched to the nearest spot within 7 yd.
  Broodlings kicked before anything hit them have no position: spot `?`.
- **Kick ready**: alive, and their most-used interrupt off cooldown
  (`spells.KICK_CD`) when the Burst completed. No range check. "On that side"
  means a kicker whose main spot is on the Broodling's side.
- **Globules**: one Barbed Bulwark actor instance per globule.
  `1289201` hits are soaks (one player), `1290338` hitting 3+ players inside
  0.6 s is an explosion. A shield strip is the Bulwark dropping within 0.4 s
  of a `SHIELD_CC` debuff on that instance; credited to the caster's class.
- **Eternal Venom sources**: each stack gain is matched to a hit within 0.15 s
  (`spells.EV_SOURCES`). About 6% have no matching hit and show as "other".
- **Tainted Blood**: healing `absorbed` on a player while they carry Tainted
  Blood, excluding anyone also under Blood Torrent's heal absorb.
- **Snakes**: each dps's damage into Spawn of Vexhul while any were alive,
  over their total in that window; "on the first to die" is the share of their
  snake damage that went into the first one killed (about 33% means an even cleave).
