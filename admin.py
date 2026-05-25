"""Admin API + page for manually overriding event/WCL categorization.

Auth: a single shared ADMIN_TOKEN env var. Clients send it as a Bearer token in
the Authorization header. The /admin page prompts for it once and stashes it in
localStorage.

Endpoints (all under /api/admin):
  GET    /events                   List events with their current overrides
  POST   /events/{raid_id}         Upsert override for one event
  DELETE /events/{raid_id}         Remove override for one event
  GET    /wcl-reports              List WCL reports with their current overrides
  POST   /wcl-reports/{code}       Upsert override for one report
  DELETE /wcl-reports/{code}       Remove override for one report
"""

import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import db


router = APIRouter()


def _require_token(authorization: str | None) -> None:
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured on server")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid token")


class EventOverrideBody(BaseModel):
    difficulty: str | None = None
    series_suffix: str | None = None
    excluded: bool = False
    wcl_codes: list[str] = []
    notes: str | None = None


class WclOverrideBody(BaseModel):
    excluded: bool = False
    forced_raid_id: str | None = None
    notes: str | None = None


@router.get("/events")
def list_events(authorization: str | None = Header(None)) -> JSONResponse:
    _require_token(authorization)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.raid_id, e.unixtime, e.title, e.leader_id,
                       (e.data->>'leadername') AS leader_name,
                       o.difficulty, o.series_suffix, o.excluded, o.wcl_codes, o.notes
                FROM events e
                LEFT JOIN event_overrides o ON o.raid_id = e.raid_id
                ORDER BY e.unixtime DESC
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
    return JSONResponse({"events": rows})


@router.post("/events/{raid_id}")
def upsert_event(raid_id: str, body: EventOverrideBody, authorization: str | None = Header(None)) -> JSONResponse:
    _require_token(authorization)
    with db.connect() as conn:
        db.upsert_event_override(
            conn, raid_id,
            difficulty=body.difficulty or None,
            series_suffix=body.series_suffix or None,
            excluded=body.excluded,
            wcl_codes=body.wcl_codes,
            notes=body.notes,
        )
    return JSONResponse({"ok": True})


@router.delete("/events/{raid_id}")
def delete_event(raid_id: str, authorization: str | None = Header(None)) -> JSONResponse:
    _require_token(authorization)
    with db.connect() as conn:
        db.delete_event_override(conn, raid_id)
    return JSONResponse({"ok": True})


@router.get("/wcl-reports")
def list_wcl_reports(authorization: str | None = Header(None)) -> JSONResponse:
    _require_token(authorization)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.code, r.start_time_ms, r.title, r.zone_name, r.owner_name,
                       r.raid_id AS auto_raid_id, r.difficulty AS auto_difficulty,
                       jsonb_array_length(r.roster) AS roster_size,
                       o.excluded, o.forced_raid_id, o.notes
                FROM wcl_reports r
                LEFT JOIN wcl_report_overrides o ON o.code = r.code
                ORDER BY r.start_time_ms DESC
                LIMIT 500
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
    return JSONResponse({"reports": rows})


@router.post("/wcl-reports/{code}")
def upsert_wcl(code: str, body: WclOverrideBody, authorization: str | None = Header(None)) -> JSONResponse:
    _require_token(authorization)
    with db.connect() as conn:
        db.upsert_wcl_override(
            conn, code,
            excluded=body.excluded,
            forced_raid_id=body.forced_raid_id or None,
            notes=body.notes,
        )
    return JSONResponse({"ok": True})


@router.delete("/wcl-reports/{code}")
def delete_wcl(code: str, authorization: str | None = Header(None)) -> JSONResponse:
    _require_token(authorization)
    with db.connect() as conn:
        db.delete_wcl_override(conn, code)
    return JSONResponse({"ok": True})


ADMIN_HTML_PATH = Path(__file__).parent / "admin.html"


def admin_page() -> HTMLResponse:
    if not ADMIN_HTML_PATH.exists():
        return HTMLResponse("<h1>admin.html missing</h1>", status_code=500)
    return HTMLResponse(ADMIN_HTML_PATH.read_text())
