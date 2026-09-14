# Nek'zali Soulcoil Well report builder

Turns one Warcraft Logs report into the page served at `/reports/<slug>`. Where
the other builders describe a night's damage, this one is about a single
rotation: who dived into the Soulcoil Well, when their Soul Exhaustion expired,
and where those two collide.

```bash
export WCL_CLIENT_ID=... WCL_CLIENT_SECRET=...     # same credentials the site uses
python -m report_builders.nekzali.build \
    --report nVtMWTA7rCXag2h6 \
    --date 2026-09-14 \
    --night "Low Pressure progression night" \
    --out /tmp/preview.html        # look at it first
python -m report_builders.nekzali.build --report <code> ... --publish
```

`--publish` writes `reports/<slug>.html` and adds or replaces the row in
`reports/index.json`; commit and push and Railway serves it. The slug defaults to
`<boss>-<difficulty>-well-<date>`, so next week's night lands beside this one
rather than over it — pass `--slug` to overwrite an existing page.

Other flags: `--encounter` and `--difficulty` if the report holds more than one
boss or difficulty (otherwise the most-pulled one wins), `--team` for a night
where two teams raid the same boss.

## What it does

1. `fetch.py` pulls everything the page needs and caches the raw responses under
   `cache/<report code>/`. Queries are report-wide — every pull in one paged
   query per ability — so a fifteen-pull night is eight requests, not a hundred.
   A re-run after a template or wording change costs nothing; delete the
   directory to refetch. The cache is git-ignored.
2. `analyze.py` computes the numbers: dives (runs of Immortal Coil auras),
   lockouts (Soul Exhaustion windows), Echo windows (runs of Grasping Depths
   damage), early entries where those overlap, the +300% hits that prove it, the
   intermission, and where each pull's death cascade started.
3. `render.py` fills `template.html`: three JSON payloads for the charts, and one
   token per number the prose says out loud.
4. `build.py` wraps the result in a standalone document and publishes it.

## Reading the log

The encounter ships four separate abilities called **Immortal Coil**. Entering
the well applies them in sequence — roughly 1s, then 3s, then the sustained one
that actually ticks — so somebody clipping the edge picks up the first and drops
it without ever reaching the third. Only dives that reach the sustained stage
count as dives; the rest are people being dragged in by Grasping Depths' pull.
`analyze.dives` finds the sustained id by median duration rather than hard-coding
it, so a patch that re-issues the ids needs no change.

**Soul Exhaustion is applied on the way out**, not on the way in, and only to
divers who reached the sustained stage. An overlap shorter than
`spells.OVERLAP_FLOOR_SECONDS` is the aura falling off a fraction after the
debuff lands, not somebody walking back in while locked out.

An **early entry** is scored as a rotation problem only when the raid is still
alive — five or more already dead and it is the wipe dragging corpses into the
water. One early entry in a pull is a person's mistake; two or more is the
rotation running out of people, which is what the page counts.

## The comparison

`baseline.py` holds the four earliest public Mythic kills (2 September 2026) the
report measures a night against — a fixed reference rather than something the
builder refetches, because they are historical and the yardstick should not move
week to week. Its docstring has the rankings query for refreshing or extending
the set.

## Editing the page

`template.html` is the page itself — HTML, CSS and the chart code. Two rules:

- Data goes in through `__PAYLOAD_<NAME>__` (one per `<script type="application/json">`).
- Any number in the prose goes in as `{{token}}`, computed in `render.tokens()`.
  Rendering fails loudly on a token the builder doesn't compute, so a new
  sentence can't silently keep last night's figure.

`spells.py` holds the ability names the analysis keys off, plus the thresholds
(what counts as an overlap, a wave, a window gap). Names rather than ids, because
Blizzard re-issues ids between patches; `Analysis.ids_named` resolves every id
behind a name from the report's own ability table.

## Known limits

- Boss-specific: it assumes this encounter's shape — a well, a rotating dive
  team, a 60-second lockout.
- Team A and Team B are read off the first two dive waves of the deepest pull. A
  night that reshuffles its teams mid-pull will label the lanes by whoever went
  first.
- `--publish` on a kill night still works, but the prose is written for a night
  that ended in wipes; the arithmetic section reads oddly next to a kill.
