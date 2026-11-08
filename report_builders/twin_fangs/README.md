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
  Broodlings kicked before anything hit them have no position. Their side
  comes from the alternation, and their spot is filled in (`inferred`, dotted
  underline) when only one spot fits the side sequences from the
  `rouse_spawns` page (`analyze.infer_spots`). The rest stay `?`, with a side.
  The side-sequence chart treats inferred spots as `?`, so it isn't counting
  its own assumption.
- **Kick ready**: alive, and their most-used interrupt off cooldown
  (`spells.KICK_CD`) when the Burst completed. No range check. "On that side"
  means a kicker whose main spot is on the Broodling's side.
- **Globules**: 15 a wave on Mythic, dropped one every 0.33 s from 2 to 7 s after
  Blood Torrent, counted off Vexhul's `1289994` casts (one per globule). A
  player who dies drops one to three more through the same spell, exactly 2.00 s after
  the death; those are counted apart (`death_globules`), so every wave is 15.
  Only some get a Barbed Bulwark (10-15 a wave here), one actor
  instance per shielded globule, so shields are not a globule count.
  `1289201` hits are soaks (one player), `1290338` hitting 3+ players inside
  0.6 s is an explosion. A shield strip is the Bulwark dropping within 0.4 s
  of a `SHIELD_CC` debuff on that instance; credited to the caster's class.
- **Eternal Venom sources**: each stack gain is matched to a hit within 0.15 s
  (`spells.EV_SOURCES`). A Stir the Depths wave mostly gives its stack with
  its debuff (`STIR_DEBUFF`) and no damage event, so that debuff counts as a
  hit too. 1289994 is the hit as a globule drops onto someone (anyone, not
  only tanks). Only a handful of stacks a night match nothing ("other").
- **Tainted Blood**: healing `absorbed` on a player while they carry Tainted
  Blood, excluding anyone also under Blood Torrent's heal absorb.
- **Snakes**: each dps's damage into Spawn of Vexhul while any were alive,
  over their total in that window; "on the first to die" is the share of their
  snake damage that went into the first one killed (about 33% means an even cleave).
- **Side sequences**: second Rouse in a place (2, 4, 6), one side at a time,
  its five spots lettered by first use (ABCDA = the 5th came back to the 1st's
  spot). A "?" Broodling's side comes from the alternation; a side with one is
  not lettered. The grey reference marks are the 80-kill shares from the
  `rouse_spawns` page, typed into the template (`KILLS`); update them if that
  page is rebuilt with different kills.
