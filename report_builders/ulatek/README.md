# Ula'tek prog-night report builder

Turns one Warcraft Logs report into the page served at `/reports/<slug>`.

```bash
export WCL_CLIENT_ID=... WCL_CLIENT_SECRET=...     # same credentials the site uses
python -m report_builders.ulatek.build \
    --report 8Tt6dBX3GkZwNC4Y \
    --date 2026-09-10 \
    --night "Ragz Raiders progression night" \
    --out /tmp/preview.html        # look at it first
python -m report_builders.ulatek.build --report <code> ... --publish
```

`--publish` writes `reports/<slug>.html` and adds or replaces the row in
`reports/index.json`; commit and push and Railway serves it. The slug defaults to
`<boss>-<difficulty>-prog-<date>`, so a second night on the same boss lands beside
the first rather than over it — pass `--slug` to overwrite an existing page.

Other flags: `--encounter` and `--difficulty` if the report holds more than one
boss or difficulty (otherwise the most-pulled one wins), `--title` and
`--summary` to write the reports-index row yourself.

## What it does

1. `fetch.py` pulls everything the page needs from the v2 API and caches the raw
   responses under `cache/<report code>/`. A re-run after a template or wording
   change costs nothing; delete the directory to refetch. The cache is large
   (hundreds of MB for a full night) and git-ignored.
2. `analyze.py` computes the numbers: exposure windows (by clustering damage on
   the heart), the burn split between the heart and the boss, wave hits, heavy
   damage spans, defensive and consumable use, per-second damage taken, and the
   two split-phase teams (read off player coordinates).

   Two things the page follows the log on rather than assuming:

   - **However many heart windows a pull reached.** A pull that lives long
     enough opens a third; the charts, the table columns and the prose all
     count what is there. `--s1`/`--s2`/`--s3` is one hue per window.
   - **Waves belong to a phase.** `Analysis.phases()` dates the split phase off
     the coordinates, and `waves()` calls everything before it phase one and
     everything after it phase two. The boss throws them on two different
     patterns, so a single wave count hides more than it tells.
3. `render.py` fills `template.html`: five JSON payloads for the charts, and one
   token per number the prose says out loud, so the sentences describe *this*
   night rather than the first one.
4. `build.py` wraps the result in a standalone document and publishes it.

## Editing the page

`template.html` is the page itself — HTML, CSS and the chart code. Two rules:

- Data goes in through `__PAYLOAD_<NAME>__` (one per `<script type="application/json">`).
- Any number in the prose goes in as `{{token}}`, computed in `render.tokens()`.
  Rendering fails loudly on a token the builder doesn't compute, so a new
  sentence can't silently keep last night's figure.

`spells.py` holds the names the analysis keys off — the wave, the expose cast,
the healthstone and potion names, and the defensive tiers. Names rather than ids,
because Blizzard re-issues ids between patches; the report's own ability table
resolves whatever names are in that log. A new tier list entry (say a spell added
in a patch) only needs adding there.

## Known limits

- Boss-specific: it assumes this encounter's shape — an exposed heart, waves, a
  two-sided split phase. Another boss needs another template.
- A pull that wipes before the split phase has no phase of its own to date, so
  the wave split falls back to the night's median phase start. If no pull all
  night reached the phase there is no boundary at all, and every wave counts as
  phase two.
- The split phase is detected geometrically (two clusters of players thousands of
  units apart). A fight without one yields an empty section rather than an error.
- Health at use subtracts the effective heal from the cast event's hitPoints,
  because WCL reports both as the value *after* the heal lands.
