# Mythic Coiled Altar prog-night report builder

```bash
export WCL_CLIENT_ID=... WCL_CLIENT_SECRET=...
python -m report_builders.coiled_altar_mythic.build --report 3aw7TmPX2t6Zfr4g \
    --date 2026-11-19 --night "Piian's Mid-Pressure progression night" --out /tmp/preview.html
python -m report_builders.coiled_altar_mythic.build --report <code> ... --publish
```

Subclasses the heroic builder's `Analysis` (paging, cache, roster, phases) and
shares its cache under `coiled_altar/cache/`. Styling is lifted from the Twin
Fangs template at render time. Research and the nerf timeline are in
`../coiled_altar/MYTHIC.md`.

Sections: the pulls, what ended them (one cause per wipe, and every death before it by mechanic), then stage one (axes, orb runners and explosions, orbs per
Sever, Guillotine soaks, Sever deaths) and stage two (axes, the Veil burn, the
Soulcoiler, Soul Sever deaths), then the intermission (Zul'jan's health through it,
fragments blocked and missed, damage into Zul'jan per player). Stage three appears inside those tables with its
stage marked until a night gets there more than once.

Pass `--soak-plan plans/<file>.json` to check each stage-one Guillotine against
the night's soak teams (team "1" takes the 48s axe, team "2" the 133s one; the stage-three Grim Guillotines alternate 1, 2, 1;
`flex` players, the tanks, are never counted missing). See
`plans/piian-2026-11-19.json`.

## Rules worth knowing

- **Wipe**: first death of the first run of 4 deaths in 8s (Twin Fangs rule) that
  the raid never recovers from: no 20s gap without a death until the pull ends.
  Nothing after it counts unless a table marks the row "after the wipe started".
- **Reset pulls** carry Malacrass's `Unworthy` and end inside 35s. Unworthy is not
  the Guillotine fail; it lands at ~10s, before any Guillotine.
- **Axes**: a tick is one Axegrinder hit (every 0.25s while standing in it); an
  axe eaten is a run of ticks with no gap over 0.75s. Only living players, before
  the wipe, and in P2 not while under Dreadmarch. Axes pile up through P1, so
  `index` compares ticks to the night's own per-10s-of-phase rate for the same
  seconds the player was alive; 1.0 = night average.
- **Orbs per Sever** read each player's Venom Rupture jump from a running stack
  count (removals reset it). A jump of 15+ is a purple explosion; one within 1.5s
  of a Toxic Deluge cast is a Mutation left on the ground, otherwise "touched".
  The holders list is proximity in time, not proof of contact.
- **Contact (who made it)**: from orb positions. The spawner actors
  (`Coalesced Venom Stalker` green, `Virulent Mutation` purple) log every orb
  that appears as a `cast` with x/y: on a Deluge, and where a carry ends.
  `Fetcher.source_events` pulls them by `sourceID` (the API ignores `targetID`
  there). `_orb_world` replays the pull: a pickup takes the nearest live orb of
  its colour within 6 yd (92% of pickups match; 99.9% of carry ends match a
  drop), a frontal removes the N orbs nearest its tank where N is its Rupture
  jump (never all: 233 orbs lay through a frontal and were picked up later),
  and the push removes everything. A contact is a carried purple reaching any
  ground orb, or a carried green reaching a ground purple, within 6 yd at the
  explosion, having been further 0.7s before. Ground orbs do not set each other
  off (they sit within 6 yd in half of all stage-one seconds) and two carried
  orbs never meet at an explosion, so neither is looked at. Over 19-26 Nov it
  names someone in 17 of 36 touched explosions before a wipe (16 one person);
  9.1% of quiet 0.7s windows with a purple out show a contact anyway
  (`CONTACT_FALSE_RATE`, quoted on the page; 23.7% without the frontal
  removal). Deluge explosions name nobody. Checked against a POV recording:
  26 Nov pulls 6 and 12 (Aeonara, purple into a green) are both right.
- **What does not work** (tested 19-26 Nov, don't rebuild): an orb debuff
  dropping on the explosion's millisecond (31 of the 33 it named died in it;
  debuffs come off 3-50ms before a logged death), a carry cut short with the
  carrier alive (2 of ~2,900 land on an explosion), and pickups or time-outs
  just before (some signal, too many names).
- **Guillotine**: one per window. The marking cast is the one with a player
  target; soakers are everyone hit within 0.6s of the landing. Execution in the
  same instant means a miss. Every soaker gets a 100s `Guillotine` debuff and
  the axes are 85s apart, so a team member still carrying it (marked for, or
  joined, the earlier axe) is "had the debuff", not absent.
- **Veil**: broken = removed with no Eternal Nightfall `cast`; resolved = the
  cast fired (about 17s after the Veil). Shields that go up after the wipe are
  shown but not credited to players.
- **Intermission**: missed fragment = a `Reclaim Essence` heal on Zul'jan (10%;
  a twin heal lands on Malacrass, not counted twice). Blocked = Spirit Erasure
  hits ÷ players hit, per 100ms bucket of ≥8 players (two can land at once). An
  intermission with the wipe starting inside it is marked and left out of totals.
  Zul'jan's P3 start is read 1.5s after the handover (the last regen tick lands on it).
- **What ended the pull**: the cause is what kills the wipe's first 8s. A purple
  explosion (a row in `orbs()`) or a missed Guillotine from 2.5s before the
  wipe's first death to the end of the opening names it when it did most of
  that opening's killing (a Guillotine that only killed soakers is "Guillotine soakers died"); 3+
  Eternal Nightfall deaths is the shield. An opening that is at least half
  unexplained falls is a **called reset**, and its reason is whoever died before
  the first jump. Otherwise the commonest mechanic in the opening; a plain fall
  loses ties. Deaths with no killing blow go through the heroic `edge()` logic
  (handover knockback band, Dreadmarch cast or ghost catch, else a fall), and a
  death logged twice with no return in between counts once.
- **Soulcoiler**: keyed by Spiritcackle cast (instance ids recycle). Killed when
  a hit reads `hitPoints == 0` with `resourceActor == 2`.
