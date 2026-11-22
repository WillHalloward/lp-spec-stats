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

Sections: the pulls, then stage one (axes, orb runners and explosions, orbs per
Sever, Guillotine soaks, Sever deaths) and stage two (axes, the Veil burn, the
Soulcoiler, Soul Sever deaths). Stage three appears inside those tables with its
stage marked until a night gets there more than once.

Pass `--soak-plan plans/<file>.json` to check each stage-one Guillotine against
the night's soak teams (team "1" takes the 48s axe, team "2" the 133s one;
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
- **Guillotine**: one per window. The marking cast is the one with a player
  target; soakers are everyone hit within 0.6s of the landing. Execution in the
  same instant means a miss. Every soaker gets a 100s `Guillotine` debuff and
  the axes are 85s apart, so a team member still carrying it (marked for, or
  joined, the earlier axe) is "had the debuff", not absent.
- **Veil**: broken = removed with no Eternal Nightfall `cast`; resolved = the
  cast fired (about 17s after the Veil). Shields that go up after the wipe are
  shown but not credited to players.
- **Soulcoiler**: keyed by Spiritcackle cast (instance ids recycle). Killed when
  a hit reads `hitPoints == 0` with `resourceActor == 2`.
