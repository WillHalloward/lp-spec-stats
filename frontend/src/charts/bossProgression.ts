import { fetchBossAttempts, type BossStat, type BossAttempt } from "../api";
import type { FilterState } from "../state";
import { DIFFICULTY_COLORS, THEME } from "../theme";
import { RAIDS, raidForEncounter } from "../normalize";

const DIFFICULTY_ORDER = ["Mythic", "Heroic", "Normal", "LFR"];

function fmtDate(ms: number | null): string {
  if (!ms) return "—";
  return new Date(ms).toISOString().slice(0, 10);
}

function applyRaidFilter(bosses: BossStat[], state?: FilterState): BossStat[] {
  if (!state || state.raids.size === 0) return bosses;
  return bosses.filter(b => {
    const raid = raidForEncounter(b.encounterID);
    return raid ? state.raids.has(raid.id) : false;
  });
}


/** Renders the boss progression grid: rows = bosses, columns = difficulties. */
export function renderBossProgression(bosses: BossStat[], state?: FilterState): HTMLElement {
  bosses = applyRaidFilter(bosses, state);
  const wrap = document.createElement("div");
  if (bosses.length === 0) {
    wrap.style.color = THEME.textMuted;
    wrap.style.padding = "32px 12px";
    wrap.textContent = "No fight data yet.";
    return wrap;
  }

  // Group by encounterID; keep the row order = first kill chronological (then encounter id).
  type BossRow = { encounterID: number; name: string; byDiff: Map<string, BossStat>; firstKill: number };
  const rowMap = new Map<number, BossRow>();
  for (const b of bosses) {
    if (!rowMap.has(b.encounterID)) {
      rowMap.set(b.encounterID, { encounterID: b.encounterID, name: b.name, byDiff: new Map(), firstKill: Infinity });
    }
    const r = rowMap.get(b.encounterID)!;
    r.byDiff.set(b.difficulty, b);
    if (b.first_kill_ms && b.first_kill_ms < r.firstKill) r.firstKill = b.first_kill_ms;
  }

  // Sort rows so they appear grouped by raid in the order defined in RAIDS,
  // with bosses within each raid in the order RAIDS.encounters lists them.
  // Bosses we can't map fall to the end.
  const raidIndexFor = new Map<number, number>();
  const bossOrderFor = new Map<number, number>();
  RAIDS.forEach((r, ri) => {
    r.encounters.forEach((eid, ei) => {
      raidIndexFor.set(eid, ri);
      bossOrderFor.set(eid, ei);
    });
  });
  const rows = Array.from(rowMap.values()).sort((a, b) => {
    const ra = raidIndexFor.get(a.encounterID) ?? 999;
    const rb = raidIndexFor.get(b.encounterID) ?? 999;
    if (ra !== rb) return ra - rb;
    const oa = bossOrderFor.get(a.encounterID) ?? 999;
    const ob = bossOrderFor.get(b.encounterID) ?? 999;
    if (oa !== ob) return oa - ob;
    return a.encounterID - b.encounterID;
  });

  const used = new Set<string>();
  for (const b of bosses) used.add(b.difficulty);
  const cols = DIFFICULTY_ORDER.filter(d => used.has(d));

  const totalKills = rows.reduce((acc, r) => acc + Array.from(r.byDiff.values()).reduce((a, b) => a + b.kills, 0), 0);
  const totalWipes = rows.reduce((acc, r) => acc + Array.from(r.byDiff.values()).reduce((a, b) => a + b.wipes, 0), 0);

  wrap.innerHTML = `
    <div class="boss-summary">
      <div class="stat-mini"><span class="label">Bosses encountered</span><span class="value">${rows.length}</span></div>
      <div class="stat-mini"><span class="label">Total kills</span><span class="value">${totalKills}</span></div>
      <div class="stat-mini"><span class="label">Total wipes</span><span class="value">${totalWipes}</span></div>
      <div class="stat-mini"><span class="label">Kill rate</span><span class="value">${(100 * totalKills / Math.max(1, totalKills + totalWipes)).toFixed(0)}%</span></div>
    </div>
    <table class="boss-table">
      <thead>
        <tr>
          <th>Boss</th>
          ${cols.map(d => `<th style="border-bottom-color:${DIFFICULTY_COLORS[d] ?? THEME.gold}">${d}</th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${(() => {
          // Render rows grouped by raid with a section header row separating each raid.
          let lastRaidIdx: number | null = null;
          return rows.map(r => {
            const ri = raidIndexFor.get(r.encounterID);
            const raid = ri !== undefined ? RAIDS[ri] : null;
            const headerHtml = (ri !== lastRaidIdx)
              ? `<tr class="boss-raid-row"><th colspan="${1 + cols.length}">${raid ? raid.name : "Other"}</th></tr>`
              : "";
            lastRaidIdx = ri ?? null;
            const cells = cols.map(d => {
              const stat = r.byDiff.get(d);
              if (!stat) return `<td class="empty">—</td>`;
              const killed = stat.kills > 0;
              const hasAttempts = stat.kills > 0 || stat.wipes > 0;
              const cellClass = killed ? "killed" : (stat.wipes > 0 ? "wiping" : "empty");
              const cellAttrs = hasAttempts
                ? ` class="${cellClass} clickable" data-boss-cell="1" data-encounter="${stat.encounterID}" data-difficulty="${stat.difficulty}" data-boss-name="${stat.name.replace(/"/g, "&quot;")}"`
                : ` class="${cellClass}"`;
              const first = stat.first_kill_ms ? fmtDate(stat.first_kill_ms) : null;
              let metaHtml = `<div class="first dim">no kill</div>`;
              if (first) {
                if (stat.first_kill_code) {
                  const href = `https://www.warcraftlogs.com/reports/${stat.first_kill_code}`;
                  metaHtml = `<div class="first"><a href="${href}" target="_blank" rel="noopener" title="Open in Warcraft Logs">first ${first}</a></div>`;
                } else {
                  metaHtml = `<div class="first">first ${first}</div>`;
                }
              } else if (stat.wipes > 0 && stat.best_pull_pct !== null) {
                // Progress boss: surface the lowest wipe %. Link to the specific pull when we have it.
                const pctTxt = `${stat.best_pull_pct.toFixed(1)}%`;
                if (stat.best_pull_code) {
                  const href = stat.best_pull_fight_id !== null
                    ? `https://www.warcraftlogs.com/reports/${stat.best_pull_code}#fight=${stat.best_pull_fight_id}`
                    : `https://www.warcraftlogs.com/reports/${stat.best_pull_code}`;
                  metaHtml = `<div class="first best-pull"><a href="${href}" target="_blank" rel="noopener" title="Best pull on Warcraft Logs">best ${pctTxt}</a></div>`;
                } else {
                  metaHtml = `<div class="first best-pull">best ${pctTxt}</div>`;
                }
              }
              return `<td${cellAttrs}>
                <div class="kc">${stat.kills}<span class="sep">/</span><span class="wipes">${stat.wipes}</span></div>
                ${metaHtml}
              </td>`;
            }).join("");
            return `${headerHtml}<tr>
              <td class="bname">${r.name}</td>
              ${cells}
            </tr>`;
          }).join("");
        })()}
      </tbody>
    </table>
    <div class="boss-legend">
      <span>kills <span class="sep">/</span> <span class="wipes">wipes</span></span>
      <span class="dot killed"></span> killed
      <span class="dot wiping"></span> attempted, no kill
      <span class="dot empty"></span> not attempted
      <span class="best-pull-legend">best % = lowest boss HP reached on a wipe</span>
    </div>
  `;
  return wrap;
}


/** Modal: every attempt (kill or wipe) on one (boss, difficulty), oldest first.
 *  Lazy-loads via /api/boss-attempts. Returns a container immediately and swaps
 *  in the loaded content when the fetch resolves.
 */
export function renderBossCellDetail(
  encounterID: number,
  difficulty: string,
  bossName: string,
): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "boss-cell-detail";
  wrap.innerHTML = `
    <div class="bcd-header">
      <div class="bcd-title">${bossName}</div>
      <div class="bcd-sub" style="--diff:${DIFFICULTY_COLORS[difficulty] ?? THEME.gold}">${difficulty}</div>
    </div>
    <div class="bcd-body"><div class="loading">Loading attempts…</div></div>
  `;
  const body = wrap.querySelector(".bcd-body") as HTMLElement;

  fetchBossAttempts(encounterID, difficulty).then(attempts => {
    body.replaceChildren(renderAttemptList(attempts));
  }).catch(err => {
    body.innerHTML = `<div class="loading">Failed to load: ${String(err)}</div>`;
  });

  return wrap;
}


function fmtTs(ms: number): string {
  return new Date(ms).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

function fmtDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}

function renderAttemptList(attempts: BossAttempt[]): HTMLElement {
  const out = document.createElement("div");
  if (attempts.length === 0) {
    out.className = "bcd-empty";
    out.textContent = "No attempts logged.";
    return out;
  }

  const kills = attempts.filter(a => a.kill);
  const wipes = attempts.filter(a => !a.kill);
  // A kill is effectively a 0% pull — once the boss has died, no wipe can
  // "break the record". The "best wipe %" stat is only meaningful before the
  // first kill, so compute it from pre-kill wipes only.
  const firstKillIdx = attempts.findIndex(a => a.kill);
  const preKillWipes = firstKillIdx === -1 ? wipes : attempts.slice(0, firstKillIdx).filter(a => !a.kill);
  const bestPct = preKillWipes.reduce<number | null>(
    (acc, a) => a.fight_pct != null && (acc == null || a.fight_pct < acc) ? a.fight_pct : acc,
    null,
  );
  const totalTimeMs = attempts.reduce((acc, a) => acc + a.duration_ms, 0);

  // Annotate each attempt with its running-best and overall-best status, then
  // we can flip between the two display modes without re-computing. Kills are
  // a hard floor — anything after the first kill can't be an improvement.
  let runningBest: number | null = null;
  let killed = false;
  const annotated = attempts.map((a, i) => {
    let improved = false;
    if (a.kill) {
      killed = true;
    } else if (!killed && a.fight_pct != null) {
      if (runningBest === null || a.fight_pct < runningBest) {
        runningBest = a.fight_pct;
        improved = true;
      }
    }
    return {
      a,
      origIdx: i + 1,
      improved,
      isOverallBest: !a.kill && bestPct !== null && a.fight_pct === bestPct && (firstKillIdx === -1 || i < firstKillIdx),
    };
  });

  // Header summary
  const summary = document.createElement("div");
  summary.className = "bcd-summary";
  summary.innerHTML = [
    `<div class="bcd-stat"><div class="label">Attempts</div><div class="value">${attempts.length}</div></div>`,
    `<div class="bcd-stat"><div class="label">Kills</div><div class="value">${kills.length}</div></div>`,
    `<div class="bcd-stat"><div class="label">Wipes</div><div class="value">${wipes.length}</div></div>`,
    // Best-pull stat: pre-kill wipe% if no kill yet; otherwise the boss is dead,
    // which is more useful info than "best pre-kill wipe was 4%".
    kills.length === 0 && bestPct !== null
      ? `<div class="bcd-stat"><div class="label">Best pull</div><div class="value">${bestPct.toFixed(1)}%</div></div>`
      : "",
    `<div class="bcd-stat"><div class="label">Time on boss</div><div class="value">${fmtDuration(totalTimeMs)}</div></div>`,
  ].join("");
  out.appendChild(summary);

  // Toggle: default to record-breakers only (terser, matches the "lowest %" intent
  // of the feature). Users who want the full play-by-play can flip it.
  const controls = document.createElement("div");
  controls.className = "bcd-controls";
  controls.innerHTML = `
    <label class="bcd-toggle">
      <input type="checkbox" class="bcd-show-all">
      <span>Show all pulls</span>
    </label>
    <span class="bcd-toggle-hint">Default: kills and record-breaking wipes only.</span>
  `;
  out.appendChild(controls);

  const tableHost = document.createElement("div");
  out.appendChild(tableHost);

  function paint(showAll: boolean): void {
    const visible = showAll
      ? annotated
      : annotated.filter(r => r.a.kill || r.improved);
    tableHost.replaceChildren(buildTable(visible, showAll));
  }
  paint(false);

  const checkbox = controls.querySelector(".bcd-show-all") as HTMLInputElement;
  checkbox.addEventListener("change", () => paint(checkbox.checked));

  return out;
}


type AnnotatedAttempt = {
  a: BossAttempt;
  origIdx: number;
  improved: boolean;
  isOverallBest: boolean;
};

function buildTable(rows: AnnotatedAttempt[], showAll: boolean): HTMLElement {
  const table = document.createElement("div");
  table.className = "bcd-table";
  if (rows.length === 0) {
    table.innerHTML = `<div class="bcd-empty">Nothing to show.</div>`;
    return table;
  }
  table.innerHTML = `
    <div class="bcd-row head">
      <div>#</div>
      <div>When</div>
      <div>Result</div>
      <div>Wipe %</div>
      <div>Duration</div>
      <div>Log</div>
    </div>
    ${rows.map(row => {
      const { a, origIdx, improved, isOverallBest } = row;
      const href = a.fight_id != null
        ? `https://www.warcraftlogs.com/reports/${a.report_code}#fight=${a.fight_id}`
        : `https://www.warcraftlogs.com/reports/${a.report_code}`;
      const resultCell = a.kill
        ? `<div class="result kill">KILL</div>`
        : `<div class="result wipe">wipe</div>`;
      const pctCell = a.kill
        ? `<div class="pct">—</div>`
        : a.fight_pct != null
          ? `<div class="pct${isOverallBest ? " best" : improved ? " improved" : ""}">${a.fight_pct.toFixed(1)}%${improved && !isOverallBest ? " ↓" : ""}${isOverallBest ? " ★" : ""}</div>`
          : `<div class="pct dim">—</div>`;
      const classes = [
        "bcd-row",
        a.kill ? "is-kill" : "is-wipe",
        isOverallBest ? "is-best" : "",
        improved && !isOverallBest ? "is-improved" : "",
      ].filter(Boolean).join(" ");
      // In "record-breakers only" mode the original pull number is useful context.
      // In "show all" the row index already matches the original index, so use it directly.
      const idxLabel = showAll ? origIdx : `#${origIdx}`;
      return `<div class="${classes}">
        <div class="idx">${idxLabel}</div>
        <div class="ts">${fmtTs(a.ts_ms)}</div>
        ${resultCell}
        ${pctCell}
        <div class="dur">${fmtDuration(a.duration_ms)}</div>
        <div class="log"><a href="${href}" target="_blank" rel="noopener">${a.report_code}</a></div>
      </div>`;
    }).join("")}
  `;
  return table;
}


/** First-kill timeline as a list. */
export function renderFirstKillTimeline(bosses: BossStat[], state?: FilterState): HTMLElement {
  bosses = applyRaidFilter(bosses, state);
  const kills = bosses
    .filter(b => b.first_kill_ms !== null)
    .sort((a, b) => (a.first_kill_ms ?? 0) - (b.first_kill_ms ?? 0));

  const wrap = document.createElement("div");
  if (kills.length === 0) {
    wrap.style.color = THEME.textMuted;
    wrap.style.padding = "16px";
    wrap.textContent = "No kills recorded yet.";
    return wrap;
  }

  wrap.innerHTML = `<div class="firstkill-list">
    ${kills.map(b => `
      <div class="firstkill-row">
        <div class="fk-date">${fmtDate(b.first_kill_ms)}</div>
        <div class="fk-diff" style="--diff:${DIFFICULTY_COLORS[b.difficulty] ?? THEME.gold}">${b.difficulty}</div>
        <div class="fk-name">${b.name}</div>
      </div>
    `).join("")}
  </div>`;
  return wrap;
}
