import type { Event, RawEvent, RawSignup, Role, SignupClassification } from "./types";

/** WoW raid seasons we can filter by, in chronological order (most recent first). */
export interface Season {
  id: string;
  label: string;
  start: string;      // YYYY-MM-DD (inclusive)
  end?: string;       // YYYY-MM-DD (exclusive); omit for the open-ended current season
  current?: boolean;
}

export const SEASONS: Season[] = [
  { id: "midnight-s1",  label: "Midnight S1",            start: "2026-03-16", current: true },
  { id: "manaforge",    label: "Manaforge Omega",        start: "2025-09-23", end: "2026-03-16" },
  { id: "undermine",    label: "Liberation of Undermine", start: "2025-03-04", end: "2025-09-23" },
  { id: "nerub-ar",     label: "Nerub-ar Palace",        start: "2024-09-10", end: "2025-03-04" },
];

function _tsFor(date: string): number {
  return Math.floor(new Date(date + "T00:00:00Z").getTime() / 1000);
}

export function eventSeason(unixtime: number): string {
  for (const s of SEASONS) {
    const start = _tsFor(s.start);
    const end = s.end ? _tsFor(s.end) : Infinity;
    if (unixtime >= start && unixtime < end) return s.id;
  }
  return "other";
}


/** WoW patches in real-world release order (newest first). Used for fine-grained filtering. */
export interface Patch {
  id: string;
  label: string;
  start: string;
  end?: string;
}

export const PATCHES: Patch[] = [
  // Midnight (12.x). Sources: wowhead.com, blizzardwatch.com (May 2026).
  { id: "12.0.7", label: "12.0.7 Revelations",      start: "2026-06-16" },
  { id: "12.0.5", label: "12.0.5 Lingering Shadows", start: "2026-04-21", end: "2026-06-16" },
  { id: "12.0.0", label: "12.0 Midnight",            start: "2026-03-02", end: "2026-04-21" },
  // TWW (11.x). Dates approximate based on Blizzard's typical ~8-week schedule.
  { id: "11.2.7", label: "11.2.7", start: "2026-02-17", end: "2026-03-02" },
  { id: "11.2.5", label: "11.2.5", start: "2025-12-02", end: "2026-02-17" },
  { id: "11.2.0", label: "11.2.0", start: "2025-09-23", end: "2025-12-02" },
  { id: "11.1.7", label: "11.1.7", start: "2025-06-17", end: "2025-09-23" },
  { id: "11.1.5", label: "11.1.5", start: "2025-04-22", end: "2025-06-17" },
  { id: "11.1.0", label: "11.1.0", start: "2025-03-04", end: "2025-04-22" },
  { id: "11.0.7", label: "11.0.7", start: "2024-12-17", end: "2025-03-04" },
  { id: "11.0.5", label: "11.0.5", start: "2024-10-22", end: "2024-12-17" },
  { id: "11.0.0", label: "11.0.0", start: "2024-08-22", end: "2024-10-22" },
];

export function eventPatch(unixtime: number): string {
  for (const p of PATCHES) {
    const start = _tsFor(p.start);
    const end = p.end ? _tsFor(p.end) : Infinity;
    if (unixtime >= start && unixtime < end) return p.id;
  }
  return "other";
}


/** Boss → raid grouping for Midnight Season 1 (LP guild's current zones).
 * Order here is the order rendered top-to-bottom in the boss-kill UI.
 *
 * To re-organize: drop encounter IDs into a different raid's `encounters`
 * array. To re-order raids: shuffle the entries below.
 */
export interface Raid {
  id: string;
  name: string;
  encounters: number[];  // WCL encounterIDs
}

export const RAIDS: Raid[] = [
  {
    id: "voidspire",
    name: "Voidspire",
    encounters: [
      3176,  // Imperator Averzian
      3177,  // Vorasius
      3179,  // Fallen-King Salhadaar
      3178,  // Vaelgor & Ezzorak
      3180,  // Lightblinded Vanguard
      3181,  // Crown of the Cosmos
    ],
  },
  {
    id: "dreamrift",
    name: "Dreamrift",
    encounters: [3306],                      // Chimaerus, the Undreamt God
  },
  {
    id: "mqd",
    name: "March on Quel'Danas",
    encounters: [3182, 3183],                // Belo'ren, Child of Al'ar / Midnight Falls
  },
];

/** Returns the raid an encounter belongs to (or null if it's not mapped). */
export function raidForEncounter(encounterID: number): Raid | null {
  for (const r of RAIDS) {
    if (r.encounters.includes(encounterID)) return r;
  }
  return null;
}

/** Title keyword fallback for raid-series classification when an event has no
 *  WCL encounter data attached. Order matters: longer/more specific phrases first. */
const RAID_TITLE_PATTERNS: { id: string; patterns: RegExp[] }[] = [
  { id: "dreamrift", patterns: [/dreamrift/i, /chimaerus/i, /undreamt/i] },
  { id: "mqd",       patterns: [/march on quel/i, /\bmoqd\b/i, /quel[' ]?danas/i, /belo[' ]?ren/i, /midnight falls/i, /child of al[' ]?ar/i] },
  { id: "voidspire", patterns: [/voidspire/i, /imperator averzian/i, /vorasius/i, /salhadaar/i, /vaelgor/i, /lightblinded/i, /crown of the cosmos/i] },
];

function raidsFromTitle(title: string): string[] {
  const out = new Set<string>();
  for (const { id, patterns } of RAID_TITLE_PATTERNS) {
    if (patterns.some(p => p.test(title))) out.add(id);
  }
  return Array.from(out);
}

const ABSENCE_ROLES = new Set(["Absence", "Tentative", "Bench", "Late"]);
const GENERIC_CLASSES = new Set(["Dps", "Tanks", "Healer", "Tank", "Melee", "Ranged"]);

const ROLE_NORMALIZE: Record<string, Role> = {
  Tanks: "Tank",
  Healers: "Healer",
  Melee: "Melee DPS",
  Ranged: "Ranged DPS",
};

const RAID_KEYWORDS = [
  "Voidspire", "Dreamrift", "Crown of the Cosmos", "MoQD",
  "MFO", "Ansurek", "Gallywix",
  "Sargeras", "Hellfire", "Legion", "Draenor", "Orgrimmar", "Midnight", "ToV", "EN",
];


function detectCategory(title: string): Event["category"] {
  const t = title.toLowerCase();
  if (t.includes("m+") || t.includes("mythic+") || t.includes("mythic plus")) return "M+";
  if (t.includes("glory") || t.includes("achiev")) return "Achievement";
  if (t.includes("mount run") || t.includes("mount raid")) return "Mount";
  return "Raid";
}

function detectDifficulty(title: string): Event["difficulty"] {
  const t = title.toLowerCase();
  if (/\bmythic\b/.test(t)) return "Mythic";
  if (/\bheroic\b/.test(t) || /\bhc\b/.test(t)) return "Heroic";
  if (/\bnormal\b/.test(t)) return "Normal";
  if (/\blfr\b/.test(t)) return "LFR";
  return "Other";
}

function detectRaidName(title: string): string {
  const lower = title.toLowerCase();
  for (const kw of RAID_KEYWORDS) {
    if (lower.includes(kw.toLowerCase())) return kw;
  }
  return "";
}

function normalizeLeaderName(name: string): string {
  if (!name) return "";
  return name.split(" - ")[0].split("-")[0].trim();
}

function buildLeaderNameMap(events: RawEvent[]): Map<string, string> {
  const counters = new Map<string, Map<string, number>>();
  for (const e of events) {
    const lid = e.leaderid;
    if (!counters.has(lid)) counters.set(lid, new Map());
    const counter = counters.get(lid)!;
    counter.set(e.leadername, (counter.get(e.leadername) ?? 0) + 1);
  }
  const out = new Map<string, string>();
  for (const [lid, counter] of counters) {
    let best = "";
    let bestN = -1;
    for (const [name, n] of counter) {
      if (n > bestN) { best = name; bestN = n; }
    }
    out.set(lid, normalizeLeaderName(best) || best || lid);
  }
  return out;
}


/** Filter to past (non-future) events and normalize each. Season filtering happens
 *  at the UI layer via the filter store so users can switch between seasons.
 */
export function normalizeEvents(raw: RawEvent[]): Event[] {
  const nowTs = Math.floor(Date.now() / 1000);
  const filtered = raw.filter(e => {
    const ts = e.unixtime;
    return ts <= nowTs;
  });

  const leaderNames = buildLeaderNameMap(filtered);

  const events: Event[] = filtered.map(d => {
    const title = d.displayTitle || d.title || "";
    const category = detectCategory(title);
    // Admin override wins over auto-detection (e.g. "Piian's Medium Pressure"
    // is Heroic but the title doesn't say so).
    const autoDifficulty = category === "Raid" ? detectDifficulty(title) : "Other";
    const difficulty = (d._override_difficulty as Event["difficulty"] | undefined) ?? autoDifficulty;
    const raidName = category === "Raid" ? detectRaidName(title) : "";
    const leaderId = d.leaderid;
    const leader = leaderNames.get(leaderId) ?? "?";

    // For raids, split the series by difficulty so "Piian Mythic" and "Piian Heroic"
    // count as distinct runs (different commitment, different boss progression).
    // Non-raid categories (M+, Achievement, Mount) keep the category as the suffix.
    // Admin can override the suffix directly when neither auto-detection works.
    const seriesSuffix = d._override_series_suffix
      ?? (category === "Raid" ? difficulty : category);
    const seriesKey = `${leaderId}::${seriesSuffix}`;
    const seriesLabel = `${leader} — ${seriesSuffix}`;

    // Derive raid-series ids: prefer WCL-attached encounter IDs (authoritative);
    // fall back to title keywords for events without WCL data.
    const raidSet = new Set<string>();
    for (const enc of d._encounter_ids ?? []) {
      const r = raidForEncounter(enc);
      if (r) raidSet.add(r.id);
    }
    if (raidSet.size === 0) {
      for (const id of raidsFromTitle(title)) raidSet.add(id);
    }

    return {
      raidId: String(d.raidid),
      title,
      unixtime: d.unixtime,
      leaderId,
      leaderName: leader,
      category,
      difficulty,
      raidName,
      seriesKey,
      seriesLabel,
      signups: d.signups ?? [],
      season: eventSeason(d.unixtime),
      patch: eventPatch(d.unixtime),
      raids: Array.from(raidSet),
    };
  });

  events.sort((a, b) => a.unixtime - b.unixtime);
  return events;
}


export function classifySignup(s: RawSignup): SignupClassification {
  const role = s.role ?? "";
  const cls = s.class ?? "";
  if (ABSENCE_ROLES.has(role) || ABSENCE_ROLES.has(cls)) return { kind: "absence" };
  if (GENERIC_CLASSES.has(cls)) return { kind: "generic" };
  const normRole = ROLE_NORMALIZE[role];
  return { kind: "attending", role: normRole };
}


/** Strip realm suffix from a signup name ("Akronnys-Karazhan" -> "Akronnys"). */
export function stripRealm(name: string): string {
  if (!name) return name;
  const i = name.indexOf("-");
  return (i === -1 ? name : name.slice(0, i)).trim();
}


/** Strip raid-helper's trailing disambiguation digit ("Protection1" -> "Protection")
 *  and normalize casing so the same spec from different sources (raid-helper vs WCL)
 *  doesn't show up as separate entries like "Beastmastery" + "BeastMastery". */
export function cleanSpec(spec: string): string {
  if (!spec) return spec;
  const trimmed = spec.replace(/\d+$/, "").trim();
  if (!trimmed) return trimmed;
  return trimmed[0].toUpperCase() + trimmed.slice(1).toLowerCase();
}


/** ISO week label "2026-W12" from a unix timestamp (UTC). */
export function isoWeek(unixtime: number): string {
  const d = new Date(unixtime * 1000);
  // ISO week calc (Monday-anchored)
  const tmp = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dayNum = tmp.getUTCDay() || 7;
  tmp.setUTCDate(tmp.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((tmp.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return `${tmp.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}


/** Iterate attending signups across all events.
 * Role may be undefined for synthesized WCL signups (class is known, spec/role isn't).
 */
export function* attendingSignups(events: Event[]): Generator<[Event, RawSignup, Role | undefined]> {
  for (const e of events) {
    for (const s of e.signups) {
      const c = classifySignup(s);
      if (c.kind === "attending") yield [e, s, c.role];
    }
  }
}
