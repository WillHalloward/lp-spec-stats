# lp-spec-stats

Stats dashboard for the **Low Pressure** WoW Discord — raid signups (raid-helper.xyz)
cross-referenced with Warcraft Logs reports, rendered as a single-page TypeScript app.

## What it does

1. **Archives** every raid-helper event on the Low Pressure server's calendar.
2. **Enriches** archived raids with WCL data: rosters, per-fight kill/wipe records,
   difficulty, and per-character item-level / spec from `playerDetails`.
3. **Synthesizes** raid-helper-shaped events from WCL reports when an event was
   deleted from raid-helper before the archiver caught it (gap-fill).
4. **Serves** a JSON API + a built TypeScript frontend that renders the dashboard:
   trends, composition, boss progression, gear, roster.
5. **Admin overrides** let a maintainer correct categorization the auto-detection
   gets wrong (excluded events, wrong difficulty, manually pin a WCL log to an event).

## Layout

### Python backend

- `archive.py` — Railway cron entrypoint. Runs raid-helper archive, then WCL enrichment.
  Idempotent; runs every 15 min.
- `enrich_wcl_auto.py` — WCL enrichment driver. Pulls reports from the guild feed
  + each known raid leader's character feed, fetches roster / fights / playerDetails
  for any unseen codes, refreshes anything started in the last 24h.
- `wcl.py` — OAuth + GraphQL client for warcraftlogs.com.
- `wcl_synthesis.py` — gap-fill: turns orphan WCL reports into synthetic raid-helper
  events; also derives the per-event ilvl map and the WCL-derived encounter-id list.
- `boss_progression.py` — per-boss, per-difficulty kill/wipe aggregation +
  per-event first kills (for the series-scoped first-kill timeline).
- `character_progression.py` — first kills attributed to a specific character
  (or a list of alts) by scanning WCL `playerDetails`.
- `serve.py` — FastAPI app. Routes:
  - `GET /api/events` — merged raid-helper + WCL gap-fill events, with overrides applied.
  - `GET /api/bosses` — boss progression aggregate.
  - `GET /api/event-kills` — per-event first kills (used for series-scoped timelines).
  - `GET /api/character-progression?names=A,B,C` — first kills for a character + alts.
  - `GET /admin` — admin page (HTML); `POST /api/admin/...` — override CRUD.
  - `GET /health` — health + DB event count.
  - `GET /legacy` — old Plotly-rendered Python page, kept for comparison.
  - `GET /` — built TS frontend (mounted from `frontend/dist/`).
- `admin.py` + `admin.html` — token-gated admin UI for `event_overrides` and
  `wcl_report_overrides` rows.
- `db.py` — Postgres schema + query helpers (`psycopg`, `dict_row`).
- `migrate.py` — one-off bootstrap: loads any `cache/events/*.json` into Postgres.
- `analyze.py` — legacy Plotly-rendered page (served at `/legacy`).
- `enrich_wcl*.py` (the non-`_auto` variants), `fetch*.py` — earlier ad-hoc scripts,
  kept for reference.

### Frontend (`frontend/`)

Vanilla TypeScript + Vite + Observable Plot + D3. Built into `frontend/dist/`,
which the FastAPI app mounts at `/`.

- `src/main.ts` — page composition (header, summary, global filters, sections).
- `src/api.ts` — fetches `/api/events` + `/api/bosses`.
- `src/normalize.ts` — seasons/patches/raids tables, signup classification.
- `src/state.ts` — global filter store (seasons, patches, raids, series, roles, classes).
- `src/charts/*.ts` — one file per chart card (~20 charts across 5 sections).
- `src/theme.ts`, `src/icons.ts`, `src/format.ts` — class/role colors, WoW
  spec icon URLs, formatting helpers.

### Postgres tables (`db.py`)

- `events` — raid-helper payload (JSONB), keyed by `raid_id`.
- `wcl_reports` — WCL report metadata + `roster`, `fights`, `player_details`, `difficulty`.
- `event_overrides` — admin overrides on raid-helper events (difficulty, series
  suffix, excluded, manually-pinned `wcl_codes[]`, notes).
- `wcl_report_overrides` — admin overrides on WCL reports (excluded,
  `forced_raid_id` to manually pin a report to an event when auto-match missed).

## Local development

```bash
uv sync
cp .env.example .env  # then fill in the secrets

# Without a DB: analyze.py reads cache/events/*.json (legacy path)
uv run analyze.py
open infographic.html

# With a DB:
export DATABASE_URL=postgres://...
uv run migrate.py                # one-time, copies cache/ into the DB
uv run archive.py                # incremental archive + WCL enrichment

# Web server (serves API + built frontend)
cd frontend && npm install && npm run build && cd ..
uv run uvicorn serve:app --reload

# Frontend dev mode (Vite HMR; expects the API at http://localhost:8000)
cd frontend && npm run dev
```

## Environment variables

| Var                          | Required | Notes |
|------------------------------|----------|-------|
| `DATABASE_URL`               | yes (prod) | Railway injects this when Postgres is attached. |
| `RAID_HELPER_ACCESS_TOKEN`   | yes      | raid-helper.xyz API token. |
| `RAID_HELPER_SERVER_ID`      | no       | Defaults to the Low Pressure server. |
| `WCL_CLIENT_ID`              | yes      | Warcraft Logs OAuth client. |
| `WCL_CLIENT_SECRET`          | yes      | Warcraft Logs OAuth secret. |
| `WCL_GUILD_ID`               | no       | Defaults to the LP guild id. |
| `ADMIN_TOKEN`                | yes (admin) | Bearer token for `/admin` and `/api/admin/*`. |
| `ARCHIVE_LEAD_TIME_SEC`      | no       | How far before event start to begin archiving (default 900). |
| `ARCHIVE_REFRESH_WINDOW_SEC` | no       | How long after event start to keep refreshing (default 86400). |
| `WCL_REFRESH_WINDOW_SEC`     | no       | How long to keep re-fetching live WCL reports (default 86400). |
| `WCL_MATCH_WINDOW_SEC`       | no       | Time window to match a WCL report to a raid-helper event (default 10800). |
| `WCL_LEADER_FEED_LIMIT`      | no       | How many recent reports to pull per leader feed (default 30). |
| `PORT`                       | no       | uvicorn bind port (Railway sets this). |

## Railway deployment

Two services in one Railway project, both deploying from this repo, plus a Postgres add-on shared between them.

1. **Create a Railway project** and attach Postgres. Railway exposes `DATABASE_URL`
   automatically to attached services.
2. **Set shared variables** at the project level (see table above).
3. **Service 1 — `archiver`** (cron):
   - Source: this repo
   - Start command: `python archive.py`
   - Cron schedule: `*/15 * * * *`
   - No public networking
4. **Service 2 — `web`** (stats page + API):
   - Source: this repo (uses `Dockerfile` per `railway.json`)
   - Start command: `uvicorn serve:app --host 0.0.0.0 --port ${PORT:-8000}`
   - Expose a public domain
5. **One-time bootstrap** (only if you have a `cache/events/*.json` snapshot to import):
   `railway run python migrate.py` from a local checkout with `DATABASE_URL` set.

The `Dockerfile` is a two-stage build: stage 1 builds the TS frontend with Node 20;
stage 2 is a Python 3.13 slim image with the built `frontend/dist/` stapled in.

After deploy: the archiver fills the DB incrementally, the web service serves
fresh stats. Visit `/admin` (token-gated) to correct any miscategorized events.
