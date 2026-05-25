"""FastAPI web server.

Routes:
  GET /api/events       JSON list of every archived event (raw raid-helper payload).
  GET /health           Plain-text health + DB event count.
  GET /legacy           Old Python-rendered Plotly page (kept for comparison).
  GET /                 New TypeScript frontend (built into frontend/dist/).
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import admin
import analyze
import boss_progression
import character_progression
import db
import wcl_synthesis


app = FastAPI()
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


@app.get("/api/events")
def api_events() -> JSONResponse:
    """All archived events, plus WCL gap-fill events for raids that were deleted from raid-helper.

    Raid-helper events take precedence; WCL events are only added when no raid-helper
    record exists in the same hour-bucket.
    """
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"events": [], "count": 0, "error": "DATABASE_URL not set"})
    with db.connect() as conn:
        events = db.load_all_events(conn)
        gap_fills = wcl_synthesis.load_gap_fill_events(conn)
        ilvl_map = wcl_synthesis.load_ilvl_map(conn)
        enc_map = wcl_synthesis.load_event_encounters(conn)
        event_overrides = db.load_event_overrides(conn)
    wcl_synthesis.inject_ilvl(events, ilvl_map)

    # Apply event overrides: drop excluded, stamp override fields the frontend honors.
    visible: list[dict] = []
    for ev in events:
        rid = str(ev.get("raidid", ""))
        enc = enc_map.get(rid)
        if enc:
            ev["_encounter_ids"] = enc
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

    merged = events + gap_fills
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
