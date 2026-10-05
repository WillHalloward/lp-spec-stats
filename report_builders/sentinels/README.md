# Entombed Sentinels prog-night report builder

Turns one Warcraft Logs report into the page served at `/reports/<slug>`.

```bash
export WCL_CLIENT_ID=... WCL_CLIENT_SECRET=...     # same credentials the site uses
python -m report_builders.sentinels.build \
    --report bPn4fjq6Tkg7wKCy \
    --date 2026-10-04 \
    --night "Low Pressure progression night" \
    --out /tmp/preview.html        # look at it first
python -m report_builders.sentinels.build --report <code> ... --publish
```

Flags as in the Ula'tek builder: `--publish` writes `reports/<slug>.html` and
updates `reports/index.json`; `--slug`, `--title`, `--summary`, `--team`,
`--encounter`, `--difficulty`. Credentials are only needed when something is
not yet cached.

## What it does

1. `fetch.py` pulls everything report-wide (one paged query per data type for
   every pull) and caches it under `cache/<report code>/`. Phase-windowed damage
   tables are the only per-pull requests.
2. `analyze.py` computes the numbers, one method per mechanic. The module
   docstring describes how the fight reads in the log.
3. `render.py` builds the chart payloads and one token per number the prose
   states. Every conclusion that could go either way on another night is
   computed (`inter_typical_note`, `blast_note`, `mark_note`, `burst_note`...)
   rather than written into the template.
4. `build.py` wraps the result in a standalone document and publishes it.

## Reading the log

- **The clock.** Stasis opens at 46s and then 91s after the previous one *ends*;
  berserk is at 420s. Intermission length is the only part of the timeline the
  raid controls.
- **The heal.** Vitriolic Stasis healing events on the bosses, summed per
  intermission. Boss health for the race chart comes from the bosses' own cast
  events, which carry `hitPoints` when `includeResources` is on.
- **Teams** come from the marks: Mark of Acid lands only near Breath, Mark of
  Blood only near Blood. A team is the set of players who share a side most
  often (not a boss: the raid swaps bosses after every intermission). That core
  fixes each team's side per phase; every player is then placed with a team
  pull by pull (`pull_team`), and a change that holds for three pulls is a move
  (`moves`). The page splits the night at the moves and compares the stretches.
- **Where the gap comes from.** `Analysis.imbalance()` splits each phase that
  ends in Stasis into team-vs-team damage on their own bosses, cross-room damage
  onto the other team's boss, and damage dealers not placed with a team that pull. The three sum to the
  heal (to within the cast-sampling noise).
- **The puzzle.** Read over the Helical Toxins debuff's own ~28 seconds, because
  Stasis does not wait for it: unsolved players keep the debuff after Stasis
  ends and take Cultivated Burst when it runs out. Any stack increase is a wrong
  pairing (1+1 into two 2s is as wrong as 3+3 into two 6s). Each intermission is
  `solved`, `wrong`, `deaths` (players holding the debuff died before the first
  wrong pairing, i.e. the raid going down or the wipe being called), or `kill`.
  The solve time is the last clear, not Stasis's length.
- **Missed droplets** are clusters of Noxious Blast hits within 100 ms, 14–15 s
  after a Toxic Droplets cast.
- **Who soaks.** Every set is twenty droplets and each is either one Toxic
  Droplets hit on one player or a Noxious Blast, so `Analysis.soakers()` counts
  droplets exactly rather than estimating.
- **Protovenom.** Pairs are two marked players' debuffs dropping together.
  Eruption hits are fetched with positions (`erupt_res_<id>` in the cache). For
  each clean player hit, the carrier is the nearest player whose debuff was up
  at that instant, placed by their own hit or their nearest cast within 1.5s;
  the nearest clean player to a carrier is the one they touched, the rest were
  caught in it. A burst of hits can be two eruptions in two places, so this is
  done per clean player, not per burst. A player who had already cleared counts
  as clean again.
- **Living Venom.** `Analysis.living_venom()` groups ticks on one player within a
  second as one hit, files each hit under the side the player stood on (from
  the marks), and sets hits against time alive in damage phases.

## The comparison

`baseline.py` holds six public kills measured by `Analysis.pull_summary`, the
same method the night's pulls go through. Its docstring has the rankings query
and the two lines that refresh it. The rankings API only returns the thousand
fastest kills, so nothing slower than about 6:17 is available.

## Known limits

- Boss-specific: two bosses, Stasis, the marks.
- Boss health between casts is interpolated by the chart; the heal figures do
  not depend on it.
- A wipe inside an intermission is excluded from solve times and gap figures.
