# CLAUDE.md

Working notes for AI assistants editing this repo. Keep this short — the code is
the source of truth; this file just orients you so you don't have to re-read
everything every time.

## What this is

A stats site for the **Low Pressure** WoW Discord. Pulls events from
raid-helper.xyz every 15 min, cross-references them with Warcraft Logs reports
(rosters, fights, playerDetails), and serves a TypeScript dashboard.

Two Railway services share one Postgres: an `archiver` cron and a `web` service.
See `README.md` for the deploy layout.

## Architecture in one paragraph

`archive.py` (cron) → upserts raid-helper events to `events`, then
`enrich_wcl_auto.py` pulls WCL reports into `wcl_reports` and tries to match
each to a raid-helper event by start-time proximity. `serve.py` exposes JSON
APIs that merge `events` with synthesized "gap-fill" events from orphan WCL
reports (`wcl_synthesis.py`) and apply admin overrides (`event_overrides`,
`wcl_report_overrides`). The TS frontend in `frontend/` consumes those APIs and
renders ~20 chart cards across five sections.

## Code map

- `archive.py` — cron entrypoint. Calls raid-helper, then WCL enrichment.
- `enrich_wcl_auto.py` — the WCL enrichment driver used in production.
  Other `enrich_wcl_*.py` files are earlier ad-hoc scripts; prefer editing
  `_auto` unless you specifically need the one-off behaviour.
- `wcl.py` — OAuth + GraphQL client. Canned queries at the bottom.
- `wcl_synthesis.py` — orphan-WCL-report → synthetic-event logic, ilvl map,
  effective report→event link resolution. Also holds the hard-coded
  `EXCLUDED_CODES` set (false-positive WCL reports). Admin DB exclusions are
  unioned with this set in `all_excluded_codes()`.
- `boss_progression.py` — boss kill/wipe aggregation and per-event first kills.
  `MIN_ATTEMPTS = 50` filters out M+ / non-LP encounters that leak into raid logs.
- `character_progression.py` — first kills attributed to a character (or alt list).
- `serve.py` — FastAPI routes. The `StaticFiles` mount at `/` is last so
  named routes (`/api/*`, `/admin`, `/legacy`, `/health`) win.
- `admin.py` + `admin.html` — token-gated overrides UI/API.
- `db.py` — schema + queries. Schema is idempotent (`CREATE TABLE IF NOT EXISTS`
  + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`). `ensure_schema()` runs on web
  startup and at the top of `archive.py`.
- `analyze.py` — the old Plotly page served at `/legacy`. Don't extend it; new
  charts go in `frontend/src/charts/`.

Frontend (`frontend/src/`):
- `main.ts` — page composition, modal, search.
- `api.ts`, `normalize.ts`, `state.ts`, `types.ts`, `theme.ts`, `icons.ts`, `format.ts`.
- `charts/*.ts` — one file per chart card. Observable Plot + D3.

## Conventions worth knowing

- **Python 3.13.** `psycopg` v3 with `dict_row`. Connections via `db.connect()`,
  always inside `with` blocks.
- **JSONB everywhere.** Raw raid-helper and WCL payloads are stored verbatim in
  JSONB columns. Parsing happens at read time so we can re-derive things
  without re-fetching.
- **Idempotent upserts.** Both archive and enrichment are designed to be safely
  re-run. `ON CONFLICT DO UPDATE` with `COALESCE(EXCLUDED.x, target.x)` so
  partial failures don't wipe out previously-fetched data.
- **Override priority:** `event_overrides.wcl_codes[]` > `wcl_report_overrides.forced_raid_id` >
  `wcl_reports.raid_id` (auto-matched). See `wcl_synthesis.effective_report_links()`.
- **Excluded codes** come from two places: the `EXCLUDED_CODES` set in
  `wcl_synthesis.py` (hard-coded historical false positives) and
  `wcl_report_overrides.excluded = TRUE` (admin-managed). Use
  `all_excluded_codes(conn)` to combine them.
- **Season / patch tables** live on the frontend (`normalize.ts`). The one
  exception is `SEASON_START_TS` in `wcl_synthesis.py`, which gates gap-fill
  candidates at the SQL level.
- **No tests.** There's no test runner wired up. Verify changes by running
  `archive.py` against a scratch DB or by hitting the API locally.

## Common edits

- **Add a chart:** new file under `frontend/src/charts/`, import + call in
  `main.ts` inside the appropriate `section(...)` block. If it needs new data,
  add a route in `serve.py` and a fetcher in `frontend/src/api.ts`.
- **Adjust filters:** logic lives in `state.ts` (store) and the chart files
  (they each consume `filterStore.state`). The chip UI is in
  `renderGlobalFilters` in `main.ts`.
- **Add a season/patch/raid:** edit `SEASONS` / `PATCHES` / `RAIDS` in
  `frontend/src/normalize.ts`. The frontend only renders chips for entries that
  have data, so you can add future seasons safely.
- **Mark a WCL log as not-LP:** prefer the `/admin` UI (`wcl_report_overrides`).
  Only add to the hard-coded `EXCLUDED_CODES` set if it's an early/bootstrap
  case you want to ship in code.
- **Re-link a misattributed WCL log:** admin UI → set `forced_raid_id` on the
  WCL report, OR set `wcl_codes[]` on the target event override.
- **New WCL field:** add the column with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  in the `SCHEMA` block, extend the query in `wcl.py`, persist in
  `enrich_wcl_auto._enrich_one()`. The `ON CONFLICT` `COALESCE` pattern means
  old rows get backfilled lazily on next refresh.

## Gotchas

- The two-stage Dockerfile means **frontend changes require a rebuild** to
  appear in the deployed `web` service. For local dev use `npm run dev` in
  `frontend/`.
- `serve.py`'s static mount at `/` swallows unknown paths — when adding a new
  API route, name it under `/api/...` so it isn't shadowed.
- `_unwrap_player_details` in `enrich_wcl_auto.py` and a mirror in
  `wcl_synthesis._unwrap` exist because WCL inconsistently nests
  `playerDetails` under `{data: {playerDetails: {...}}}`. If you touch
  player-details handling, unwrap defensively.
- Boss attempt counts (`MIN_ATTEMPTS = 50`) and roster size filters
  (`8 ≤ size ≤ 50` for progression, `8 ≤ size ≤ 40` for gap-fill candidates)
  are heuristics tuned to keep M+ and pool-log noise out. Adjust together if
  you adjust at all.
- `wcl_synthesis.SEASON_START_TS` is a Unix timestamp constant; update it when
  the next season starts so gap-fill stops pulling old logs.
