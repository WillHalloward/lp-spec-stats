import type { RawEvent } from "./types";

export interface ApiPayload {
  events: RawEvent[];
  count: number;
  generated_at: string;
  error?: string;
}

export async function fetchEvents(): Promise<ApiPayload> {
  const res = await fetch("/api/events");
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}


export interface BossStat {
  encounterID: number;
  name: string;
  difficulty: string;
  kills: number;
  wipes: number;
  first_kill_ms: number | null;
  first_kill_code: string | null;
  latest_kill_ms: number | null;
  total_duration_ms: number;
  /** Lowest boss HP % reached on a wipe (0..100, lower = closer to kill).
   *  null when no wipes have been logged with fightPercentage data. */
  best_pull_pct: number | null;
  best_pull_code: string | null;
  best_pull_fight_id: number | null;
}


export async function fetchBosses(): Promise<{ bosses: BossStat[] }> {
  const res = await fetch("/api/bosses");
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}


export interface BossAttempt {
  ts_ms: number;
  kill: boolean;
  fight_pct: number | null;   // 0..100, lower = closer to kill (null if unknown)
  duration_ms: number;
  report_code: string;
  fight_id: number | null;
  last_phase: number | null;
  /** raid-helper event id this WCL report is linked to (auto or overridden).
   *  Null for unmatched reports; in that case the frontend looks up the
   *  gap-fill event by raidid="wcl:<report_code>" instead. */
  raid_id: string | null;
}

export async function fetchBossAttempts(
  encounterID: number,
  difficulty: string,
): Promise<BossAttempt[]> {
  const qs = `encounterID=${encounterID}&difficulty=${encodeURIComponent(difficulty)}`;
  const res = await fetch(`/api/boss-attempts?${qs}`);
  if (!res.ok) return [];
  const body = await res.json();
  return body.attempts ?? [];
}


export interface CharacterKill {
  encounterID: number;
  name: string;
  difficulty: string;
  first_kill_ms: number;
  report_code?: string;
  fight_id?: number;
}

export async function fetchCharacterProgression(names: string[]): Promise<CharacterKill[]> {
  const qs = encodeURIComponent(names.join(","));
  const res = await fetch(`/api/character-progression?names=${qs}`);
  if (!res.ok) return [];
  const body = await res.json();
  return body.kills ?? [];
}


/** Per-event first-kill row. Lets the client narrow first-kills to any subset
 *  of events (e.g. one raid series) by joining on raid_id. */
export interface EventKill {
  raid_id: string;
  encounterID: number;
  name: string;
  difficulty: string;
  kill_ms: number;
  report_code: string;
  fight_id?: number;
}

let _eventKillsCache: Promise<EventKill[]> | null = null;
export function fetchEventKills(): Promise<EventKill[]> {
  if (!_eventKillsCache) {
    _eventKillsCache = fetch("/api/event-kills")
      .then(r => (r.ok ? r.json() : { kills: [] }))
      .then(body => body.kills ?? [])
      .catch(() => []);
  }
  return _eventKillsCache;
}
