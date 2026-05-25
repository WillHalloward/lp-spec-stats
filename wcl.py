"""Warcraft Logs API client.

OAuth client-credentials flow → bearer token, used against the v2 GraphQL endpoint.
Token cached for the process lifetime (refreshed when within 60s of expiry).
"""

import base64
import os
import time
from typing import Any

import requests


TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
GRAPHQL_URL = "https://www.warcraftlogs.com/api/v2/client"


class WclClient:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None) -> None:
        self.client_id = client_id or os.environ["WCL_CLIENT_ID"]
        self.client_secret = client_secret or os.environ["WCL_CLIENT_SECRET"]
        self._token: str | None = None
        self._token_expires_at: float = 0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self._get_token()
        for attempt in range(3):
            resp = requests.post(
                GRAPHQL_URL,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"query": query, "variables": variables or {}},
                timeout=30,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "30"))
                print(f"  WCL rate-limited, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            body = resp.json()
            if body.get("errors"):
                raise RuntimeError(f"WCL GraphQL errors: {body['errors']}")
            return body["data"]
        raise RuntimeError("WCL request retries exhausted")


# ---- canned queries ----

GUILD_REPORTS_QUERY = """
query GuildReports($id: Int!, $page: Int!) {
  reportData {
    reports(guildID: $id, page: $page, limit: 25) {
      data {
        code
        startTime
        endTime
        title
        zone { name }
        owner { name }
      }
      total
      per_page
      current_page
      last_page
      has_more_pages
    }
  }
}
"""


REPORT_ROSTER_QUERY = """
query ReportRoster($code: String!) {
  reportData {
    report(code: $code) {
      code
      startTime
      endTime
      title
      zone { name }
      owner { name }
      masterData(translate: false) {
        actors(type: "Player") {
          id
          name
          type
          subType
          server
        }
      }
    }
  }
}
"""


def list_guild_reports(client: WclClient, guild_id: int) -> list[dict]:
    """Paginate through all reports for a guild."""
    out: list[dict] = []
    page = 1
    while True:
        data = client.query(GUILD_REPORTS_QUERY, {"id": guild_id, "page": page})
        block = data["reportData"]["reports"]
        out.extend(block["data"])
        if not block.get("has_more_pages"):
            break
        page += 1
    return out


def fetch_report_roster(client: WclClient, code: str) -> dict:
    """Fetch one report's full roster (actors filtered to Player)."""
    data = client.query(REPORT_ROSTER_QUERY, {"code": code})
    return data["reportData"]["report"]


CHARACTER_REPORTS_QUERY = """
query CharacterReports($name: String!, $server: String!, $region: String!, $limit: Int!) {
  characterData {
    character(name: $name, serverSlug: $server, serverRegion: $region) {
      id
      name
      recentReports(limit: $limit) {
        data {
          code
          startTime
          endTime
          title
          zone { name }
          owner { name }
        }
        total
      }
    }
  }
}
"""


REPORT_FIGHTS_QUERY = """
query ReportFights($code: String!) {
  reportData {
    report(code: $code) {
      startTime
      fights(killType: All) {
        id
        encounterID
        name
        difficulty
        kill
        startTime
        endTime
        fightPercentage
        lastPhase
      }
    }
  }
}
"""


def fetch_report_fights(client: WclClient, code: str) -> dict:
    """Return {report_start_ms, fights:[...]}. Fight times are relative to report start."""
    data = client.query(REPORT_FIGHTS_QUERY, {"code": code})
    report = ((data.get("reportData") or {}).get("report") or {})
    return {
        "report_start_ms": report.get("startTime"),
        "fights": report.get("fights") or [],
    }


REPORT_PLAYER_DETAILS_QUERY = """
query ReportPlayerDetails($code: String!, $endTime: Float!) {
  reportData {
    report(code: $code) {
      playerDetails(startTime: 0, endTime: $endTime, includeCombatantInfo: true)
    }
  }
}
"""


def fetch_report_player_details(client: WclClient, code: str, end_time_ms: float = 1.0e11) -> dict | None:
    """Fetch playerDetails for the whole report. endTime defaults to ~3 years (so it always covers the report)."""
    data = client.query(REPORT_PLAYER_DETAILS_QUERY, {"code": code, "endTime": end_time_ms})
    report = (data.get("reportData") or {}).get("report") or {}
    return report.get("playerDetails")


def fetch_character_reports(
    client: WclClient,
    name: str,
    server: str,
    region: str = "EU",
    limit: int = 100,
) -> list[dict]:
    """Return the character's recent reports (as raw report metadata)."""
    data = client.query(
        CHARACTER_REPORTS_QUERY,
        {"name": name, "server": server, "region": region, "limit": limit},
    )
    char = (data.get("characterData") or {}).get("character")
    if not char:
        return []
    return char["recentReports"]["data"]
