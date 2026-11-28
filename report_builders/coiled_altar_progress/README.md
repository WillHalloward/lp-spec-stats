# Mythic Coiled Altar progress page

```bash
python -m report_builders.coiled_altar_progress.build --out /tmp/preview.html
python -m report_builders.coiled_altar_progress.build --publish
```

Compares every night in `nights.json` side by side. Each night is run through
the Mythic night builder's own `Analysis` (cached under `coiled_altar/cache/`),
so this page and the night pages always agree. After a new prog night: build
its night page first (that fetches and caches it), add a row to `nights.json`,
then rebuild this one. It keeps one slug, `the-coiled-altar-mythic-progress`,
dated by the latest night.

Everything that grows with the size of a night is a rate (per pull, per minute
of the stage played before the wipe, per window), because the nights run 18 to
35 pulls. Only what happened before each wipe counts. The arrows in the table
compare with the night before; each row declares which direction is better.

Sections: every pull, the checkpoint funnel (past the opening orbs at 25s, each
stage-one Guillotine, stage two, the first shield broken, the intermission,
stage three; only the first shield, since Malacrass often dies before a
second), the night-by-night table, wipe causes, deaths before the wipe, who set
off the purple explosions (from the night builder's `set_off`), and a player
table with a picker: deaths, stage-one axe index, Guillotine absences, damage
per shield and per Soulcoiler, intermission DPS, explosions set off.
