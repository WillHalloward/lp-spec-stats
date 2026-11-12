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

Pass `--kick-plan` if the night had assignments (below). Same flags as the other builders (`--slug`, `--title`, `--summary`, `--team`,
`--encounter`, `--difficulty`). Everything is cached under `cache/<code>/`.
Pulls are numbered 1..n within the boss, not by Warcraft Logs fight id.

## Kick plan (optional)

`--kick-plan plans/<file>.json` adds "Against the kick plan" to the Rouse
section: each placed Broodling against the night's assignments. Per pair of
spots: `early` takes the first Broodling to surface there, `late` the second,
`backup` a third (a repeat) or one whose kicker is dead; `centre` backups come
after that. A pair whose kickers sort it out between them (the tanks on the
front) takes `flex: [names]` instead and is one shared row. Spawn order is how the raid reads it, and it fits the kicks better
than spot did (e.g. 80 of 84 vs 52 on L1+L2, 8 Nov). See
`plans/piian-2026-11-08.json`. Without the flag the block is hidden.

The plan also drives "Why they went off, by group" (`analyze.burst_causes`):
each Broodling that finished a Burst, on its plan group, with why the kicker it
belonged to didn't stop it: dead, kick just too late (aimed -0.5..+1.5 s
around the Burst), kicked before it began casting (the interrupt landed on it
before its begincast, so it hit nothing), or, with the kick on cooldown at the
Burst, where that kick went: pair-mate's Broodling, another group's, a double
kick, the boss, a snake. "Out of kicks" (the kick went on an earlier Broodling
of their own) passes it to the backup and the row says what the backups did.

## Reading the log

- **Wipe start and cause**: the wipe starts at the first death of the first run
  of 4 deaths within 8 s. What started it is that first death's cause, not the
  commonest cause in the cascade (a Feast often finishes a raid already falling).
- **After the wipe**: nothing after the wipe start counts, also inside a Rouse,
  Feast or Emergence that opened before it (the Burst that is the wipe's first
  death lands in the same ms, so Rouses keep 0.5 s of grace).
- **Alive**: dead from a death until the player next casts something, so a
  battle rez brings them back (`dead_spans`).
- **Stacks at death**: Eternal Venom is removed a few ms before the death event,
  so a death's stacks are the most in the 1.5 s before (`stacks_before`).
- **Feast smashes**: counted by who the smash damage (`FEAST_HIT`) landed on;
  the Feasted debuff misses soakers the smash killed. A smash hitting
  `RAID_SMASH` (12) or more went out to the whole raid: too few were in it.
- **Globule deaths**: a death to the soak spell (`GLOBULE_SOAK`) is its own
  group, apart from an explosion; both spells are called Caustic Globule.
- **Globules outside waves**: drops before the wipe that no counted wave holds
  (deaths away from a wave, waves cut short) are in `loose_globules` and in the
  night's totals.
- **The lead**: `--previous <code> --previous-date "5 November"` adds the
  comparison with the last night on the boss.


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
- **First try** (kick grid, red cells): the first interrupt *cast* aimed at that
  Broodling from 0.5 s before its Burst until the wipe (`analyze.kick_aims`,
  cast `targetInstance`, landed or not). Under ~0.5 s is a kick that just
  missed; from ~2.2 s on, it went out after the Burst and landed on the next
  cast. Nothing aimed at it shows as "no kick".
- **Globules**: 15 a wave on Mythic, dropped one every 0.33 s from 2 to 7 s after
  Blood Torrent, counted off Vexhul's `1289994` casts (one per globule). A
  player who dies drops one to three more through the same spell, exactly 2.00 s after
  the death; those are counted apart (`death_globules`), so every wave is 15.
  Only some get a Barbed Bulwark (10-15 a wave here), one actor
  instance per shielded globule, so shields are not a globule count.
  `1289201` hits are soaks (one player), `1290338` hitting 3+ players inside
  0.6 s is an explosion. A shield strip is the Bulwark dropping within 0.4 s
  of a `SHIELD_CC` debuff on that instance; credited to the caster's class.
- **Death globules soaked**: no globule id is logged and a dead player's
  globules land among the wave's, so soaks are split by timing
  (`analyze._death_soaks`). In a wave with death drops, a player's 2nd+ soak
  after the first death drop is a death globule, in time order, up to the
  number dropped. Outside a wave, a soak 1.9-15 s after a death is one
  (`death_soaks_loose`). "Soaked", "Globules per wave" and "Waves with 2+"
  count wave globules only.
- **Spit target vs cleave**: Corrosive Spit is a beam locked onto one player,
  who carries the `SPIT_TARGET` debuff (1293979). A spit stack on that player
  is "spit target" (not dodgeable); on anyone else it is "spit cleave".
  The dodging list counts waves and cleave only.
- **Eternal Venom sources**: each stack gain is matched to a hit from 0.35 s before to 0.15 s after it (under load the stack trails its hit)
  (`spells.EV_SOURCES`). A Stir the Depths wave mostly gives its stack with
  its debuff (`STIR_DEBUFF`) and no damage event, so that debuff counts as a
  hit too. 1289994 is the hit as a globule drops onto someone (anyone, not
  only tanks). Only a handful of stacks a night match nothing ("other").
- **Tainted Blood**: healing `absorbed` on a player while they carry Tainted
  Blood, excluding anyone also under Blood Torrent's heal absorb.
- **Snakes**: each dps's damage into Spawn of Vexhul while any were alive,
  over their total in that window; "on the first to die" is the share of their
  snake damage that went into the first one killed (about 33% means an even cleave).
- **Double soaks**: a damaging `GLOBULE_SOAK` hit within `DOUBLE_SOAK_S` (3 s)
  of that player's previous damaging one (immunity soaks log 0 and are
  skipped). A soak death with one of those before the killing soak is a
  double-soak death (`analyze.double_soaks`).
- **Side sequences**: second Rouse in a place (2, 4, 6), one side at a time,
  its five spots lettered by first use (ABCDA = the 5th came back to the 1st's
  spot). A "?" Broodling's side comes from the alternation; a side with one is
  not lettered. The grey reference marks are the 80-kill shares from the
  `rouse_spawns` page, typed into the template (`KILLS`); update them if that
  page is rebuilt with different kills.
