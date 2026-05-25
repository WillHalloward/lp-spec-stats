import * as Plot from "@observablehq/plot";
import type { Event, RawSignup } from "../types";
import { attendingSignups, isoWeek, stripRealm, RAIDS } from "../normalize";
import { classIconUrl } from "../icons";
import { CLASS_COLORS, DIFFICULTY_COLORS, THEME } from "../theme";
import { plotStyle } from "./_plotStyle";
import { fetchCharacterProgression } from "../api";

/** Given a character name, find all characters that share the same Discord userid. */
export function findAltsByCharacter(charName: string, allEvents: Event[]): string[] {
  const target = stripRealm(charName).toLowerCase();
  let uid: string | null = null;
  for (const [, s] of attendingSignups(allEvents)) {
    if (stripRealm(s.name).toLowerCase() === target) {
      uid = s.userid;
      break;
    }
  }
  if (!uid) return [charName];
  const out = new Set<string>();
  for (const [, s] of attendingSignups(allEvents)) {
    if (s.userid === uid) out.add(stripRealm(s.name));
  }
  return out.size ? Array.from(out) : [charName];
}


export type SearchEntry =
  | { kind: "character"; name: string; count: number; cls: string }
  | { kind: "player"; primaryName: string; altCount: number; count: number; alts: string[] };


/** Build a once-per-load search index of unique characters and unique players (by userid). */
export function buildSearchIndex(allEvents: Event[]): SearchEntry[] {
  // character name (stripped) -> { count, classFreq }
  const chars = new Map<string, { count: number; classFreq: Map<string, number> }>();
  // userid -> { nameFreq, count }
  const players = new Map<string, { nameFreq: Map<string, number>; count: number }>();

  for (const [, s] of attendingSignups(allEvents)) {
    const name = stripRealm(s.name);
    if (!chars.has(name)) chars.set(name, { count: 0, classFreq: new Map() });
    const c = chars.get(name)!;
    c.count++;
    c.classFreq.set(s.class, (c.classFreq.get(s.class) ?? 0) + 1);

    const uid = s.userid;
    if (!players.has(uid)) players.set(uid, { nameFreq: new Map(), count: 0 });
    const p = players.get(uid)!;
    p.nameFreq.set(name, (p.nameFreq.get(name) ?? 0) + 1);
    p.count++;
  }

  const out: SearchEntry[] = [];
  for (const [name, c] of chars) {
    const cls = Array.from(c.classFreq).sort((a, b) => b[1] - a[1])[0][0];
    out.push({ kind: "character", name, count: c.count, cls });
  }
  for (const [, p] of players) {
    const sorted = Array.from(p.nameFreq).sort((a, b) => b[1] - a[1]);
    const altCount = sorted.length - 1;
    if (altCount === 0) continue;  // single-character player is the same as the character entry
    out.push({
      kind: "player",
      primaryName: sorted[0][0],
      altCount,
      count: p.count,
      alts: sorted.map(([n]) => n),
    });
  }
  return out;
}


/** Filter the search index by a substring query, ranked by relevance + signup count. */
export function querySearchIndex(index: SearchEntry[], query: string, limit = 8): SearchEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const scored: { entry: SearchEntry; score: number }[] = [];
  for (const e of index) {
    const name = e.kind === "character" ? e.name : e.primaryName;
    const lower = name.toLowerCase();
    let score = 0;
    if (lower === q) score = 1000;
    else if (lower.startsWith(q)) score = 500;
    else if (lower.includes(q)) score = 200;
    else if (e.kind === "player" && e.alts.some(a => a.toLowerCase().includes(q))) score = 100;
    else continue;
    score += Math.min(e.count, 50);  // bias toward active raiders
    scored.push({ entry: e, score });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, limit).map(s => s.entry);
}

/**
 * Per-character or per-player (alt-aggregated) drill-down modal.
 *
 * If `names` is a string → single-character view (matches by stripped name).
 * If `names` is an array → multi-character / player view (matches any in the set).
 *   Header shows the most-frequent name as primary with "+N alts" suffix.
 */
export function renderCharacterDetail(names: string | string[], allEvents: Event[]): HTMLElement {
  const nameList = Array.isArray(names) ? names : [names];
  const targets = new Set(nameList.map(n => stripRealm(n).toLowerCase()));
  const isPlayerView = nameList.length > 1;

  // All signups whose stripped name is in the target set
  const sigs: { event: Event; signup: RawSignup }[] = [];
  for (const [event, signup] of attendingSignups(allEvents)) {
    if (targets.has(stripRealm(signup.name).toLowerCase())) {
      sigs.push({ event, signup });
    }
  }

  const root = document.createElement("div");
  root.className = "char-detail";

  if (sigs.length === 0) {
    root.innerHTML = `<h3>${nameList[0]}</h3><div class="meta">No signups found.</div>`;
    return root;
  }

  // Determine the headline display name (most-used among matched names).
  const nameFreq = new Map<string, number>();
  for (const { signup } of sigs) {
    const n = stripRealm(signup.name);
    nameFreq.set(n, (nameFreq.get(n) ?? 0) + 1);
  }
  const sortedNames = Array.from(nameFreq).sort((a, b) => b[1] - a[1]);
  const displayName = sortedNames[0][0];
  const altCount = sortedNames.length - 1;
  // Determine main class by attendance frequency
  const classCounts = new Map<string, number>();
  const specCounts = new Map<string, number>();
  const leaderCounts = new Map<string, number>();
  let ilvlSum = 0, ilvlN = 0;
  for (const { event, signup } of sigs) {
    classCounts.set(signup.class, (classCounts.get(signup.class) ?? 0) + 1);
    const spec = (signup.spec || "").replace(/\d+$/, "");
    if (spec) specCounts.set(`${signup.class} ${spec}`, (specCounts.get(`${signup.class} ${spec}`) ?? 0) + 1);
    leaderCounts.set(event.leaderName, (leaderCounts.get(event.leaderName) ?? 0) + 1);
    const ilvl = (signup as { _ilvl_max?: number })._ilvl_max;
    if (ilvl && Number.isFinite(ilvl)) { ilvlSum += ilvl; ilvlN++; }
  }
  const mainClass = Array.from(classCounts).sort((a, b) => b[1] - a[1])[0][0];
  const avgIlvl = ilvlN > 0 ? ilvlSum / ilvlN : null;

  // For the ilvl card subtitle: peak ilvl + how many distinct characters had ilvl data.
  let peakIlvl = -Infinity;
  const ilvlChars = new Set<string>();
  for (const { signup } of sigs) {
    const ilvl = (signup as { _ilvl_max?: number })._ilvl_max;
    if (ilvl && Number.isFinite(ilvl)) {
      if (ilvl > peakIlvl) peakIlvl = ilvl;
      ilvlChars.add(stripRealm(signup.name));
    }
  }
  const peakIlvlStr = peakIlvl === -Infinity ? null : peakIlvl;

  // Attendance ratio
  const totalEvents = allEvents.length;
  const myEvents = sigs.length;
  const attendancePct = (100 * myEvents) / totalEvents;

  // Percentile rank: how does this entity stack up against all others on attendance?
  // For player view we rank against other unique players (collapsed by userid).
  // For single character view we rank against other unique characters.
  const counts = new Map<string, number>();
  for (const [, s] of attendingSignups(allEvents)) {
    const key = isPlayerView ? s.userid : stripRealm(s.name).toLowerCase();
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const allCounts = Array.from(counts.values());
  const above = allCounts.filter(c => c > myEvents).length;
  const totalEntities = allCounts.length;
  const rank = above + 1;
  const percentileRaw = (rank / Math.max(1, totalEntities)) * 100;
  const percentileLabel = percentileRaw < 1
    ? "Top <1%"
    : `Top ${Math.round(percentileRaw)}%`;

  const iconUrl = classIconUrl(mainClass);

  // Build header + stats
  const altsTag = isPlayerView && altCount > 0
    ? ` <span class="chip-tag">+${altCount} alt${altCount === 1 ? "" : "s"}</span>`
    : "";
  root.innerHTML = `
    <h3 class="char-head">
      ${iconUrl ? `<img class="class-icon big" src="${iconUrl}" alt="${mainClass}" width="32" height="32">` : ""}
      <span>${displayName}${altsTag}</span>
    </h3>
    <div class="meta">${mainClass} · ${myEvents} raids${isPlayerView ? " (player view)" : ""}</div>
    <div class="grid">
      <div class="stat primary"><div class="label">Raids attended</div><div class="value">${myEvents}</div></div>
      <div class="stat"><div class="label">Attendance</div><div class="value">${attendancePct.toFixed(0)}%</div></div>
      <div class="stat" title="Rank ${rank} of ${totalEntities} ${isPlayerView ? "players" : "characters"}"><div class="label">Percentile</div><div class="value">${percentileLabel}</div><div class="sub">${rank} of ${totalEntities}</div></div>
      <div class="stat"><div class="label">Avg ilvl</div>
        <div class="value">${avgIlvl !== null ? avgIlvl.toFixed(0) : "—"}</div>
        ${avgIlvl !== null ? `<div class="sub">${isPlayerView ? `across ${ilvlChars.size} char${ilvlChars.size === 1 ? "" : "s"} · ` : ""}peak ${peakIlvlStr}</div>` : ""}
      </div>
    </div>
  `;

  // Attendance heatmap: weeks × days
  const cells = new Map<string, number>();
  const weeksSeen = new Set<string>();
  for (const { event } of sigs) {
    const dt = new Date(event.unixtime * 1000);
    const dow = (dt.getUTCDay() + 6) % 7;
    const wk = isoWeek(event.unixtime);
    weeksSeen.add(wk);
    cells.set(`${wk}|${dow}`, (cells.get(`${wk}|${dow}`) ?? 0) + 1);
  }
  // Use all weeks in the data for x-axis so absence shows up
  const allWeeks = new Set<string>();
  for (const e of allEvents) allWeeks.add(isoWeek(e.unixtime));
  const sortedWeeks = Array.from(allWeeks).sort();
  const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const heatData: { wk: string; day: string; count: number }[] = [];
  for (const wk of sortedWeeks) {
    for (let d = 0; d < 7; d++) {
      heatData.push({ wk, day: DAY_NAMES[d], count: cells.get(`${wk}|${d}`) ?? 0 });
    }
  }
  const heatTitle = document.createElement("h4");
  heatTitle.textContent = "Attendance heatmap";
  root.appendChild(heatTitle);
  root.appendChild(Plot.plot({
    width: 860,
    height: 200,
    marginLeft: 50,
    marginBottom: 60,
    marginTop: 10,
    style: plotStyle,
    x: { domain: sortedWeeks, label: null, tickRotate: -35, tickPadding: 6 },
    y: { domain: DAY_NAMES, label: null },
    color: {
      type: "linear",
      range: ["rgba(224,165,38,0.06)", THEME.gold],
      legend: false,
    },
    marks: [
      Plot.cell(heatData, { x: "wk", y: "day", fill: "count", inset: 1, tip: true }),
    ],
  }));

  // Ilvl curve (if data)
  const ilvlByWeek = new Map<string, number[]>();
  for (const { event, signup } of sigs) {
    const ilvl = (signup as { _ilvl_max?: number })._ilvl_max;
    if (!ilvl) continue;
    const wk = isoWeek(event.unixtime);
    if (!ilvlByWeek.has(wk)) ilvlByWeek.set(wk, []);
    ilvlByWeek.get(wk)!.push(ilvl);
  }
  if (ilvlByWeek.size > 1) {
    const ilvlData = Array.from(ilvlByWeek)
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([wk, vs]) => ({ wk, ilvl: vs.reduce((a, b) => a + b, 0) / vs.length }));
    const t = document.createElement("h4");
    t.textContent = "Ilvl curve";
    root.appendChild(t);
    root.appendChild(Plot.plot({
      width: 860,
      height: 200,
      marginLeft: 60,
      marginBottom: 60,
      marginTop: 10,
      style: plotStyle,
      x: { domain: sortedWeeks, label: null, tickRotate: -35, tickPadding: 6 },
      y: { grid: true, nice: true, label: null },
      marks: [
        Plot.lineY(ilvlData, { x: "wk", y: "ilvl",
          stroke: CLASS_COLORS[mainClass] ?? THEME.gold,
          strokeWidth: 2, curve: "monotone-x" }),
        Plot.dot(ilvlData, { x: "wk", y: "ilvl",
          fill: CLASS_COLORS[mainClass] ?? THEME.gold, r: 3, tip: true }),
      ],
    }));
  }

  // Alts breakdown (only shown for player view)
  if (isPlayerView && sortedNames.length > 1) {
    const altsTitle = document.createElement("h4");
    altsTitle.textContent = `Characters (${sortedNames.length})`;
    root.appendChild(altsTitle);
    const altsList = document.createElement("div");
    altsList.className = "pill-grid";
    altsList.innerHTML = sortedNames.map(([n, c]) =>
      `<div class="pill"><span>${n}</span><span class="count">${c}</span></div>`,
    ).join("");
    root.appendChild(altsList);
  }

  // First boss kills — async fetch from /api/character-progression
  const killsTitle = document.createElement("h4");
  killsTitle.textContent = "First boss kills";
  root.appendChild(killsTitle);
  const killsBox = document.createElement("div");
  killsBox.className = "firstkill-list";
  killsBox.innerHTML = `<div class="meta" style="padding:8px 14px;">Loading…</div>`;
  root.appendChild(killsBox);

  const namesForApi = isPlayerView ? Array.from(nameFreq.keys()) : [displayName];
  fetchCharacterProgression(namesForApi).then(kills => {
    if (kills.length === 0) {
      killsBox.innerHTML = `<div class="meta" style="padding:8px 14px;">No WCL-logged kills found for this ${isPlayerView ? "player" : "character"}.</div>`;
      return;
    }
    // Group by boss; show difficulties achieved (keep full kill record for linking).
    type KillCell = { ts: number; code?: string; fightId?: number };
    type Row = { name: string; encounterID: number; diffs: Map<string, KillCell> };
    const rows = new Map<number, Row>();
    for (const k of kills) {
      if (!rows.has(k.encounterID)) {
        rows.set(k.encounterID, { name: k.name, encounterID: k.encounterID, diffs: new Map() });
      }
      rows.get(k.encounterID)!.diffs.set(k.difficulty, {
        ts: k.first_kill_ms,
        code: k.report_code,
        fightId: k.fight_id,
      });
    }
    const DIFFS = ["Mythic", "Heroic", "Normal"] as const;

    function bossRowHtml(r: Row): string {
      const diffCells = DIFFS.map(d => {
        const cell = r.diffs.get(d);
        if (!cell) return `<span class="firstkill-cell empty">${d}: —</span>`;
        const date = new Date(cell.ts).toISOString().slice(0, 10);
        const inner = `<span class="firstkill-diff">${d}</span><span class="firstkill-date">${date}</span>`;
        if (cell.code) {
          const fightPart = cell.fightId ? `#fight=${cell.fightId}` : "";
          const href = `https://www.warcraftlogs.com/reports/${cell.code}${fightPart}`;
          return `<a class="firstkill-cell" href="${href}" target="_blank" rel="noopener" title="Open in Warcraft Logs" style="--diff:${DIFFICULTY_COLORS[d] ?? THEME.gold}">${inner}</a>`;
        }
        return `<span class="firstkill-cell" style="--diff:${DIFFICULTY_COLORS[d] ?? THEME.gold}">${inner}</span>`;
      }).join("");
      return `<div class="firstkill-boss">
        <div class="firstkill-name">${r.name}</div>
        <div class="firstkill-cells">${diffCells}</div>
      </div>`;
    }

    // Render grouped by raid (in the order defined in RAIDS), with bosses
    // ordered within their raid as listed in RAIDS.encounters. Any bosses we
    // don't know how to map go under an "Other" group at the end.
    const html: string[] = [];
    const seen = new Set<number>();
    for (const raid of RAIDS) {
      const bossesInRaid = raid.encounters
        .map(eid => rows.get(eid))
        .filter((r): r is Row => r !== undefined);
      if (bossesInRaid.length === 0) continue;
      html.push(`<div class="firstkill-raid">
        <div class="firstkill-raid-header">${raid.name}</div>
        ${bossesInRaid.map(bossRowHtml).join("")}
      </div>`);
      for (const b of bossesInRaid) seen.add(b.encounterID);
    }
    const unmapped = Array.from(rows.values()).filter(r => !seen.has(r.encounterID));
    if (unmapped.length > 0) {
      html.push(`<div class="firstkill-raid">
        <div class="firstkill-raid-header">Other</div>
        ${unmapped.sort((a, b) => a.encounterID - b.encounterID).map(bossRowHtml).join("")}
      </div>`);
    }
    killsBox.innerHTML = html.join("");
  }).catch(() => {
    killsBox.innerHTML = `<div class="meta" style="padding:8px 14px;">Failed to load kill data.</div>`;
  });

  // Spec + leader breakdowns
  const specsHtml = Array.from(specCounts).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([k, n]) => {
    const [, spec] = k.split(" ", 2);
    return `<div class="pill"><span>${spec}</span><span class="count">${n}</span></div>`;
  }).join("");
  const leadersHtml = Array.from(leaderCounts).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, n]) => `
    <div class="pill"><span>${name}</span><span class="count">${n}</span></div>
  `).join("");

  const grid = document.createElement("div");
  grid.className = "char-detail-grid";
  grid.innerHTML = `
    <div>
      <h4>Specs played</h4>
      <div class="pill-grid">${specsHtml || `<div class="meta">No spec data</div>`}</div>
    </div>
    <div>
      <h4>Top raid leaders</h4>
      <div class="pill-grid">${leadersHtml}</div>
    </div>
  `;
  root.appendChild(grid);

  return root;
}
