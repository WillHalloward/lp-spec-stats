"""FastAPI web server.

Routes:
  GET /api/events       JSON list of every archived event, trimmed to the fields
                        the dashboard reads.
  GET /health           Plain-text health + DB event count.
  GET /legacy           Old Python-rendered Plotly page (kept for comparison).
  GET /reports          Index of one-off stat reports; /reports/{slug} serves one.
  GET /                 New TypeScript frontend (built into frontend/dist/).
"""

import hashlib
import json
import os
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse, Response
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
    by the next archiver cron run). Also opens the connection pool, so requests
    don't each pay a Postgres handshake."""
    if not os.environ.get("DATABASE_URL"):
        return
    try:
        db.init_pool()
    except Exception as exc:
        print(f"Connection pool failed to open, falling back to per-request connections: {exc}", flush=True)
    try:
        with db.session() as conn:
            db.ensure_schema(conn)
    except Exception as exc:
        print(f"Schema migration on startup failed: {exc}", flush=True)


@app.on_event("shutdown")
def _close_pool_on_shutdown() -> None:
    db.close_pool()


# ---------------------------------------------------------------------------
# Response cache.
#
# The archiver writes once every 15 minutes, and the read endpoints spend
# seconds aggregating JSONB that hasn't changed since the last cron run. So
# each response is built once per data version and then served from memory:
# `db.data_version()` is a single round trip that changes exactly when the
# underlying tables do, which makes the cache self-invalidating rather than
# time-based — an admin override shows up on the next request, not 60s later.
#
# Entries are keyed by endpoint + parameters and capped, so the parameterised
# endpoints (character progression, boss attempts) can't grow without bound.
# No lock: a race just builds the same payload twice and stores the same bytes.
# ---------------------------------------------------------------------------
_CACHE_MAX_ENTRIES = 128
_cache: "OrderedDict[str, tuple[tuple, bytes, str]]" = OrderedDict()


def _cached_json(
    request: Request,
    cache_key: str,
    build: Callable[[psycopg.Connection], dict[str, Any]],
) -> Response:
    """Serve `build(conn)` as JSON, reusing the previous result while the data
    behind it is unchanged. Sends an ETag so a repeat visit gets a 304."""
    with db.session() as conn:
        version = db.data_version(conn)
        entry = _cache.get(cache_key)
        if entry is None or entry[0] != version:
            body = json.dumps(build(conn)).encode()
            entry = (version, body, '"' + hashlib.md5(body).hexdigest() + '"')
            _cache[cache_key] = entry
            _cache.move_to_end(cache_key)
            while len(_cache) > _CACHE_MAX_ENTRIES:
                _cache.popitem(last=False)
        else:
            _cache.move_to_end(cache_key)

    _version, body, etag = entry
    # max-age is short: the ETag is what saves the bytes, and a stale tab should
    # pick up a fresh archiver run without a hard reload.
    headers = {"ETag": etag, "Cache-Control": "public, max-age=60"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


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
def api_events(request: Request) -> Response:
    """All archived events, plus WCL gap-fill events for raids that were deleted from raid-helper.

    Raid-helper events take precedence; a WCL report that time-overlaps an
    already-linked report with a mostly-shared roster is treated as a duplicate
    upload of that raid and never synthesized (see wcl_synthesis).
    """
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"events": [], "count": 0, "error": "DATABASE_URL not set"})
    return _cached_json(request, "events", _build_events)


def _build_events(conn: psycopg.Connection) -> dict:
    events = db.load_slim_events(conn, EVENT_FIELDS, SIGNUP_FIELDS)
    # Resolved once and handed down: each loader would otherwise rebuild the
    # link table, and that walks the whole events table for the duplicate map.
    excluded = wcl_synthesis.all_excluded_codes(conn)
    links = wcl_synthesis.effective_report_links(conn)
    gap_fills = wcl_synthesis.load_gap_fill_events(conn, links, excluded)
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

    return {
        "events": merged,
        "count": len(merged),
        "raid_helper_count": len(events),
        "wcl_gap_fill_count": len(gap_fills),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/character-progression")
def api_character_progression(request: Request, names: str = "") -> Response:
    """First boss kills for a character (or comma-separated list of alts).

    Example: /api/character-progression?names=Akronnys
             /api/character-progression?names=Piian,Piikuv,Piipro
    """
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"kills": []})
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if not name_list:
        return JSONResponse({"kills": []})
    key = "character-progression:" + ",".join(sorted(n.lower() for n in name_list))
    return _cached_json(
        request, key,
        lambda conn: {"kills": character_progression.first_kills(conn, name_list)},
    )


@app.get("/api/event-kills")
def api_event_kills(request: Request) -> Response:
    """Per-event first-kill rows: one entry per (raid_id, encounter, difficulty).
    Frontend groups these by series to render per-series first-kill timelines.
    """
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"kills": []})
    return _cached_json(
        request, "event-kills",
        lambda conn: {"kills": boss_progression.per_event_first_kills(conn)},
    )


@app.get("/api/boss-attempts")
def api_boss_attempts(request: Request, encounterID: int, difficulty: str) -> Response:
    """Chronological attempt log for one (encounterID, difficulty). Used by the
    boss-cell modal to show kills or the progression of wipes."""
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"attempts": [], "error": "DATABASE_URL not set"})
    return _cached_json(
        request, f"boss-attempts:{encounterID}:{difficulty}",
        lambda conn: {"attempts": boss_progression.attempts_for_boss(conn, encounterID, difficulty)},
    )


@app.get("/api/bosses")
def api_bosses(request: Request) -> Response:
    """Per-boss / per-difficulty progression stats from WCL fights data."""
    if not os.environ.get("DATABASE_URL"):
        return JSONResponse({"bosses": [], "error": "DATABASE_URL not set"})

    def build(conn: psycopg.Connection) -> dict:
        agg = boss_progression.aggregate(conn)
        agg["generated_at"] = datetime.now(timezone.utc).isoformat()
        return agg

    return _cached_json(request, "bosses", build)


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
        with db.session() as conn:
            n = db.count_events(conn)
        return PlainTextResponse(f"ok\nevents: {n}\n")
    return PlainTextResponse("ok (no db configured)\n")


@app.get("/legacy", response_class=HTMLResponse)
def legacy() -> HTMLResponse:
    """Old Python-rendered Plotly page, kept while the TS frontend is in progress."""
    events = analyze.load_events()
    html = analyze.render_html_string(events)
    return HTMLResponse(html)


class _HashedStaticFiles(StaticFiles):
    """StaticFiles that lets browsers keep the build output.

    Vite writes a content hash into every filename under /assets, so those files
    can never change meaning — cache them for a year. index.html carries the
    references to them and must stay revalidated, or a deploy would never reach
    anyone.
    """

    def file_response(self, full_path, *args, **kwargs) -> Response:
        response = super().file_response(full_path, *args, **kwargs)
        if "/assets/" in str(full_path).replace("\\", "/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


# Static frontend (must be mounted LAST so /api/* and named routes win).
if FRONTEND_DIST.exists():
    app.mount("/", _HashedStaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def _placeholder() -> HTMLResponse:
        return HTMLResponse(
            "<h1>lp-spec-stats</h1>"
            "<p>Frontend not built yet. Run <code>npm install && npm run build</code> in <code>frontend/</code>.</p>"
            "<p>Meanwhile: <a href=\"/legacy\">/legacy</a> · <a href=\"/health\">/health</a> · "
            "<a href=\"/api/events\">/api/events</a></p>"
        )
