# Sszorak prog-night report builder

Turns one Warcraft Logs report of Mythic Sszorak pulls into the page served at
`/reports/<slug>`. The page is about **what improved over the night**: every
mechanic is counted per pull and compared across the night's three thirds.

```bash
export WCL_CLIENT_ID=... WCL_CLIENT_SECRET=...
python -m report_builders.sszorak.build --report JzYT4kyLPfcRDXWA \
    --date 2026-11-01 --night "Piian's Mid-Pressure progression night" \
    --out /tmp/preview.html          # look first
python -m report_builders.sszorak.build --report <code> ... --publish
```

Same flags as the other builders (`--slug`, `--title`, `--summary`, `--team`,
`--encounter`, `--difficulty`). Everything is cached under `cache/<code>/`.

## Reading the log

- **Falls.** The platform edge is ~60 yd from the middle (centre = midpoint of
  the 1st/99th percentile of all player positions). A death whose last 8 s
  passed 65 yd with no killing blow is a fall, blamed on what moved the player
  in the 7 s before leaving the platform: Crosswinds launch, cyst pop,
  intermission winds, or nothing (walked/jumped). Three "nothing" falls inside
  10 s is a called wipe; deaths after it are excluded.
- **Tornado hits**: Tempest damage without the tick flag, one per player per second.
- **Cyst pops**: clusters of non-tick Viscous Cyst hits. Pops during Dig In or
  within 10 s after it are planned (3 per intermission at ~3.5/12/20.5 s, plus
  one just after); all others are accidental.
- **Serpent's Fury**: a pop is the mark dropping with Virulence on the soakers
  within 1.5 s. Plan: all dps + both tanks, healers only to cover a dead one.
  Rage refills ~57.7 s after an in-phase pop and ~82.3 s after the last pop
  before an intermission (read off the enrages), so pop 2 sets the deadline for
  the first post-intermission pop.
- **Crosswinds**: Turbulent Gusts > 1.5 s is a launch. Everyone but Paladins and
  Priests can cancel alone with a movement ability (`SOLO_MOVES`, cast from
  -0.5 to +1.5 s around the launch); launches are split into late / none /
  no-partner (Paladin or Priest).
