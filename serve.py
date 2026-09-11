"""FastAPI web server.

Routes:
  GET /api/events       JSON list of every archived event, trimmed to the fields
                        the dashboard reads.
  GET /health           Plain-text health + DB event count.
  GET /legacy           Old Python-rendered Plotly page (kept for comparison).
  GET /reports          Index of one-off stat reports; /reports/{slug} serves one.
  GET /                 New TypeScript frontend (built into frontend/dist/).
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

import admin
import analyze
import boss_progression
import character_progression
import db
import reports as reports_mod
import wcl_synthesis


app = FastAPI()
# The events payload is ~1.5 MB of JSON and compresses to about a tenth of that.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.include_router(admin.router, prefix="/api/admin")


@app.on_event("startup")
def _ensure_schema_on_startup() -> None:
    """Run schema migrations when the web service boots so the override tables
    exist before any admin endpoint is hit (they would otherwise only be created
    by the next archiver cron run)."""
    if not os.environ.get("DATABASE_URL"):
        return
    try:
        with db.connect() as conn:
            db.ensure_schema(conn)
    except Exception as exc:
        print(f"Schema migration on startup failed: {exc}", flush=True)


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    return admin.admin_page()

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"


# The dashboard reads a handful of fields out of raid-helper's event payload and
# ignores the rest — comps, emotes, announcements, descriptions, permissions. The
# full payload is ~10.9 MB of JSON; these fields are about a sixth of that, and
# the browser parses what it keeps. `frontend/src/types.ts` (RawEvent, RawSignup)
# is the other half of this contract: add a field there, add it here.
EVENT_FIELDS = ("raidid", "unixtime", "leaderid", "leadername", "title", "displayTitle")
SIGNUP_FIELDS = ("userid", "name", "class", "spec", "role", "status", "signuptime")


def _slim_signup(s: dict) -> dict:
    out = {k: s[k] for k in SIGNUP_FIELDS if k in s}
    # Anything the server stamped on (_ilvl_min / _ilvl_max) rides along.
    out.update({k: v for k, v in s.items() if k.startswith("_")})
    return out


def _slim_event(ev: dict) -> dict:
    """Project a synthesized gap-fill event. Stored events are projected in SQL
    instead (db.load_slim_events) so the full payloads never reach Python."""
    out = {k: ev[k] for k in EVENT_FIELDS if k in ev}
    out.update({k: v for k, v in ev.items() if k.startswith("_")})
    out["signups"] = [_slim_signup(s) for s in ev.get("signups") or []]
    return out


@app.get("/api/events")
def api_events() -> JSONResponse:
    """All archived events, plus WCL gap-fill events for raids that were deleted from raid-helper.

    Raid-helper events take precedence; a WCL report that time-overlaps an
    already-linked report with a mostly-shared roster is treated as a duplicate
    upload of that raid and never synthesized (see wcl_synthesis).
    """
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"events": [], "count": 0, "error": "DATABASE_URL not set"})
    with db.connect() as conn:
        events = db.load_slim_events(conn, EVENT_FIELDS, SIGNUP_FIELDS)
        gap_fills = wcl_synthesis.load_gap_fill_events(conn)
        # Resolved once and handed down: each loader would otherwise rebuild the
        # link table, and that walks the whole events table for the duplicate map.
        excluded = wcl_synthesis.all_excluded_codes(conn)
        links = wcl_synthesis.effective_report_links(conn)
        ilvl_map = wcl_synthesis.load_ilvl_map(conn, links, excluded)
        enc_map = wcl_synthesis.load_event_encounters(conn, links, excluded)
        wcl_diff_map = wcl_synthesis.load_event_wcl_difficulty(conn, links, excluded)
        dup_map = wcl_synthesis.duplicate_event_map(conn)
        event_overrides = db.load_event_overrides(conn)
    wcl_synthesis.inject_ilvl(events, ilvl_map)

    # Apply event overrides: drop excluded, stamp override fields the frontend honors.
    visible: list[dict] = []
    for ev in events:
        rid = str(ev.get("raidid", ""))
        # Archive-channel re-posts of an event that still exists — serving both
        # double-counts every signup. effective_report_links() remaps WCL links
        # to the canonical copy, so dropping the duplicate loses nothing.
        if rid in dup_map:
            continue
        enc = enc_map.get(rid)
        if enc:
            ev["_encounter_ids"] = enc
        wcl_diff = wcl_diff_map.get(rid)
        if wcl_diff:
            ev["_wcl_difficulty"] = wcl_diff
        ov = event_overrides.get(rid)
        if ov:
            if ov.get("excluded"):
                continue
            if ov.get("difficulty"):
                ev["_override_difficulty"] = ov["difficulty"]
            if ov.get("series_suffix"):
                ev["_override_series_suffix"] = ov["series_suffix"]
        visible.append(ev)
    # Gap-fill events also respect their override (rare, but possible if someone
    # manually wants to hide a synthesized event).
    visible_gap_fills = []
    for ev in gap_fills:
        rid = str(ev.get("raidid", ""))
        ov = event_overrides.get(rid)
        if ov and ov.get("excluded"):
            continue
        if ov:
            if ov.get("difficulty"): ev["_override_difficulty"] = ov["difficulty"]
            if ov.get("series_suffix"): ev["_override_series_suffix"] = ov["series_suffix"]
        visible_gap_fills.append(ev)
    events = visible
    gap_fills = visible_gap_fills

    # Stored events came out of the database already projected; gap-fills are
    # synthesized in Python and still need trimming.
    merged = events + [_slim_event(e) for e in gap_fills]
    merged.sort(key=lambda e: e.get("unixtime", 0))

    return JSONResponse({
        "events": merged,
        "count": len(merged),
        "raid_helper_count": len(events),
        "wcl_gap_fill_count": len(gap_fills),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/character-progression")
def api_character_progression(names: str = "") -> JSONResponse:
    """First boss kills for a character (or comma-separated list of alts).

    Example: /api/character-progression?names=Akronnys
             /api/character-progression?names=Piian,Piikuv,Piipro
    """
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"kills": []})
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if not name_list:
        return JSONResponse({"kills": []})
    with db.connect() as conn:
        kills = character_progression.first_kills(conn, name_list)
    return JSONResponse({"kills": kills})


@app.get("/api/event-kills")
def api_event_kills() -> JSONResponse:
    """Per-event first-kill rows: one entry per (raid_id, encounter, difficulty).
    Frontend groups these by series to render per-series first-kill timelines.
    """
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"kills": []})
    with db.connect() as conn:
        kills = boss_progression.per_event_first_kills(conn)
    return JSONResponse({"kills": kills})


@app.get("/api/boss-attempts")
def api_boss_attempts(encounterID: int, difficulty: str) -> JSONResponse:
    """Chronological attempt log for one (encounterID, difficulty). Used by the
    boss-cell modal to show kills or the progression of wipes."""
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"attempts": [], "error": "DATABASE_URL not set"})
    with db.connect() as conn:
        attempts = boss_progression.attempts_for_boss(conn, encounterID, difficulty)
    return JSONResponse({"attempts": attempts})


@app.get("/api/bosses")
def api_bosses() -> JSONResponse:
    """Per-boss / per-difficulty progression stats from WCL fights data."""
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"bosses": [], "error": "DATABASE_URL not set"})
    with db.connect() as conn:
        agg = boss_progression.aggregate(conn)
    agg["generated_at"] = datetime.now(timezone.utc).isoformat()
    return JSONResponse(agg)


@app.get("/api/reports")
def api_reports() -> JSONResponse:
    """The one-off report index, for anything that wants to link them."""
    return JSONResponse({"reports": reports_mod.load_index()})


@app.get("/reports", response_class=HTMLResponse)
def reports_index() -> HTMLResponse:
    return HTMLResponse(reports_mod.index_page())


@app.get("/reports/{slug}", response_class=HTMLResponse)
def report(slug: str) -> HTMLResponse:
    """Serve a report page verbatim. Each one is a frozen, self-contained file."""
    path = reports_mod.report_file(slug)
    if path is None:
        return HTMLResponse(
            '<p style="font-family:system-ui;padding:40px">No such report. '
            '<a href="/reports">All reports</a></p>', status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/health", response_class=PlainTextResponse)
def health() -> PlainTextResponse:
    if os.environ.get("DATABASE_URL"):
        with db.connect() as conn:
            n = db.count_events(conn)
        return PlainTextResponse(f"ok\nevents: {n}\n")
    return PlainTextResponse("ok (no db configured)\n")


@app.get("/legacy", response_class=HTMLResponse)
def legacy() -> HTMLResponse:
    """Old Python-rendered Plotly page, kept while the TS frontend is in progress."""
    events = analyze.load_events()
    html = analyze.render_html_string(events)
    return HTMLResponse(html)


# Static frontend (must be mounted LAST so /api/* and named routes win).
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def _placeholder() -> HTMLResponse:
        return HTMLResponse(
            "<h1>lp-spec-stats</h1>"
            "<p>Frontend not built yet. Run <code>npm install && npm run build</code> in <code>frontend/</code>.</p>"
            "<p>Meanwhile: <a href=\"/legacy\">/legacy</a> · <a href=\"/health\">/health</a> · "
            "<a href=\"/api/events\">/api/events</a></p>"
        )
