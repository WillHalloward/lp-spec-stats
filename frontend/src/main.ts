import "./style.css";
import { fetchEvents, fetchBosses } from "./api";
import { normalizeEvents, attendingSignups, SEASONS, PATCHES, RAIDS, raidForEncounter } from "./normalize";
import { filterStore } from "./state";
import { CLASS_COLORS, ROLE_COLORS } from "./theme";
import { classIconUrl, indexSpecIcons } from "./icons";
import { renderClassDistribution } from "./charts/classDistribution";
import { renderSignupsOverTime } from "./charts/signupsOverTime";
import { renderDifficultyProgression } from "./charts/difficultyProgression";
import { renderClassConsistency } from "./charts/classConsistency";
import { renderRoleComp } from "./charts/roleComp";
import { renderSpecDistribution } from "./charts/specDistribution";
import { renderTopCharacters } from "./charts/topCharacters";
import { renderTopPlayers } from "./charts/topPlayers";
import { renderSeriesBreakdown } from "./charts/seriesBreakdown";
import { renderDayOfWeekHeatmap } from "./charts/dayOfWeekHeatmap";
import { renderCumulativeSeason } from "./charts/cumulativeSeason";
import { renderClassMetaOverTime } from "./charts/classMetaOverTime";
import { renderIlvlOverTime } from "./charts/ilvlOverTime";
import { renderIlvlByClass } from "./charts/ilvlByClass";
import { renderIlvlByClassOverTime } from "./charts/ilvlByClassOverTime";
import { renderSeriesDetail } from "./charts/seriesDetail";
import { renderCharacterDetail, findAltsByCharacter, buildSearchIndex, querySearchIndex } from "./charts/characterDetail";
import { renderBossProgression, renderFirstKillTimeline, renderBossCellDetail } from "./charts/bossProgression";
import type { Event, Role } from "./types";

const ROLE_ORDER: Role[] = ["Tank", "Healer", "Melee DPS", "Ranged DPS"];

const ICONS = {
  swords: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5"/><line x1="13" y1="19" x2="19" y2="13"/><line x1="16" y1="16" x2="20" y2="20"/><line x1="19" y1="21" x2="21" y2="19"/><polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5"/><line x1="5" y1="14" x2="9" y2="18"/><line x1="7" y1="17" x2="4" y2="20"/><line x1="3" y1="19" x2="5" y2="21"/></svg>',
  users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  userCheck: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><polyline points="17 11 19 13 23 9"/></svg>',
  award: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="6"/><polyline points="15.477 12.89 17 22 12 19 7 22 8.523 12.89"/></svg>',
};


function fmtDate(unixtime: number): string {
  return new Date(unixtime * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}


function renderHeader(events: Event[]): HTMLElement {
  const el = document.createElement("header");
  const first = events.length ? fmtDate(events[0].unixtime) : "—";
  const last = events.length ? fmtDate(events[events.length - 1].unixtime) : "—";
  el.innerHTML = `
    <h1>Low Pressure</h1>
    <span class="underline"></span>
    <div class="sub"><b>${events.length}</b> raids · <b>${first}</b> to <b>${last}</b></div>
  `;
  return el;
}


function renderSummary(events: Event[]): HTMLElement {
  let totalSignups = 0;
  const players = new Set<string>();
  const chars = new Set<string>();
  for (const [, s] of attendingSignups(events)) {
    totalSignups++;
    players.add(s.userid);
    chars.add(s.name);
  }
  const card = (icon: string, label: string, value: number | string, primary = false) =>
    `<div class="stat${primary ? " primary" : ""}">
      <div class="row">
        <div class="icon">${icon}</div>
        <div><div class="label">${label}</div><div class="value">${value}</div></div>
      </div>
    </div>`;
  const el = document.createElement("div");
  el.className = "summary";
  el.innerHTML = [
    card(ICONS.swords, "Events", events.length, true),
    card(ICONS.users, "Attending signups", totalSignups),
    card(ICONS.userCheck, "Unique characters", chars.size),
    card(ICONS.award, "Unique players", players.size),
  ].join("");
  return el;
}


function renderGlobalFilters(events: Event[], bosses: { encounterID: number }[]): HTMLElement {
  // Collect all classes that appear in the data
  const classes = new Set<string>();
  for (const [, s] of attendingSignups(events)) classes.add(s.class);
  const classList = Array.from(classes).sort();

  // Only show raid chips for raids we actually have boss data for, so the row
  // doesn't list zones the guild hasn't touched yet.
  const presentRaids = new Set<string>();
  for (const b of bosses) {
    const raid = raidForEncounter(b.encounterID);
    if (raid) presentRaids.add(raid.id);
  }

  const el = document.createElement("div");
  el.className = "global-filters";

  function chipsRow(label: string, chips: string, resetType: string): string {
    return `
      <div class="gf-group">
        <div class="gf-label">${label}</div>
        <div class="gf-row">${chips}<button class="chip reset" data-reset="${resetType}">Reset</button></div>
      </div>`;
  }

  // Build season chips. Only show seasons we actually have data for, to keep the
  // selector lean (a freshly-deployed dashboard for a new server doesn't need a
  // years-old season listed).
  const presentSeasons = new Set<string>();
  const presentPatches = new Set<string>();
  for (const e of events) { presentSeasons.add(e.season); presentPatches.add(e.patch); }
  const seasonChips = SEASONS
    .filter(s => presentSeasons.has(s.id))
    .map(s => `<button class="chip season" data-season="${s.id}">${s.label}${s.current ? " <span class=\"chip-tag\">current</span>" : ""}</button>`)
    .join("");
  const patchChips = PATCHES
    .filter(p => presentPatches.has(p.id))
    .map(p => `<button class="chip patch" data-patch="${p.id}">${p.label}</button>`)
    .join("");

  const raidChips = RAIDS
    .filter(r => presentRaids.has(r.id))
    .map(r => `<button class="chip raid" data-raid="${r.id}">${r.name}</button>`)
    .join("");

  // Build raid-series controls: one dropdown per leader, with each suffix
  // (difficulty for Raid events, category otherwise) listed as a checkbox.
  // This keeps the row short even when many leaders run many flavors.
  type SeriesGroup = { leader: string; total: number; suffixes: { label: string; full: string; count: number }[] };
  const byLeader = new Map<string, SeriesGroup>();
  for (const e of events) {
    const label = e.seriesLabel;
    const dash = label.indexOf(" — ");
    const leader = dash === -1 ? label : label.slice(0, dash);
    const suffix = dash === -1 ? "" : label.slice(dash + 3);
    if (!byLeader.has(leader)) byLeader.set(leader, { leader, total: 0, suffixes: [] });
    const g = byLeader.get(leader)!;
    g.total++;
    let s = g.suffixes.find(x => x.label === suffix);
    if (!s) {
      s = { label: suffix || "—", full: label, count: 0 };
      g.suffixes.push(s);
    }
    s.count++;
  }
  // Sort leaders by activity, sort each leader's suffixes by activity too.
  const seriesGroups = Array.from(byLeader.values()).sort((a, b) => b.total - a.total);
  for (const g of seriesGroups) g.suffixes.sort((a, b) => b.count - a.count);

  const seriesChips = seriesGroups.map(g => {
    const opts = g.suffixes.map(s => {
      const safe = s.full.replace(/"/g, "&quot;");
      return `<label class="series-opt">
        <input type="checkbox" class="series-check" data-raid-series="${safe}">
        <span class="series-opt-label">${s.label}</span>
        <span class="series-opt-count">${s.count}</span>
      </label>`;
    }).join("");
    const safeLeader = g.leader.replace(/"/g, "&quot;");
    return `<details class="chip series-dd" data-leader="${safeLeader}">
      <summary>
        <span class="series-dd-name">${g.leader}</span>
        <span class="series-dd-badge" hidden>0</span>
        <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </summary>
      <div class="series-dd-panel">${opts}</div>
    </details>`;
  }).join("");

  const roleChips = ROLE_ORDER.map(r =>
    `<button class="chip role" data-role="${r}" style="--chip-color:${ROLE_COLORS[r]}"><span class="swatch"></span>${r}</button>`
  ).join("");

  const classChips = classList.map(c => {
    const url = classIconUrl(c);
    const icon = url
      ? `<img class="chip-icon" src="${url}" alt="" width="14" height="14">`
      : `<span class="swatch" style="--chip-color:${CLASS_COLORS[c] ?? "#888"}"></span>`;
    return `<button class="chip class" data-class="${c}">${icon}${c}</button>`;
  }).join("");

  const searchRow = `
    <div class="gf-group">
      <div class="gf-label">Find</div>
      <div class="gf-row search-row">
        <div class="search-input-wrap">
          <input type="text" class="char-search" placeholder="Type a name…" autocomplete="off">
          <div class="search-suggestions" hidden></div>
        </div>
        <label class="alts-toggle">
          <input type="checkbox" class="alts-checkbox">
          <span>include alts (player view)</span>
        </label>
      </div>
    </div>`;

  const bodyHtml = chipsRow("Season", seasonChips, "seasons")
    + chipsRow("Patch", patchChips, "patches")
    + (raidChips ? chipsRow("Raid", raidChips, "raids") : "")
    + (seriesChips ? chipsRow("Series", seriesChips, "raidSeries") : "")
    + chipsRow("Role", roleChips, "roles")
    + chipsRow("Class", classChips, "classes")
    + searchRow;
  el.innerHTML = `
    <div class="gf-head">
      <div class="gf-summary"></div>
      <button class="gf-toggle" type="button" aria-label="Toggle filters" title="Collapse filters">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
    </div>
    <div class="gf-body">${bodyHtml}</div>
  `;

  // Wire interactions
  el.querySelectorAll<HTMLButtonElement>(".chip.season").forEach(btn => {
    btn.addEventListener("click", () => filterStore.toggleSeason(btn.dataset.season!));
  });
  el.querySelectorAll<HTMLButtonElement>(".chip.patch").forEach(btn => {
    btn.addEventListener("click", () => filterStore.togglePatch(btn.dataset.patch!));
  });
  el.querySelectorAll<HTMLButtonElement>(".chip.raid").forEach(btn => {
    btn.addEventListener("click", () => filterStore.toggleRaid(btn.dataset.raid!));
  });
  el.querySelectorAll<HTMLInputElement>(".series-check").forEach(input => {
    input.addEventListener("change", () => {
      filterStore.toggleRaidSeries(input.dataset.raidSeries!);
    });
  });
  // Close any other open series dropdown when one is toggled open.
  el.querySelectorAll<HTMLDetailsElement>(".series-dd").forEach(dd => {
    dd.addEventListener("toggle", () => {
      if (dd.open) {
        el.querySelectorAll<HTMLDetailsElement>(".series-dd").forEach(other => {
          if (other !== dd) other.open = false;
        });
      }
    });
  });
  // Click outside the filter bar closes any open dropdown.
  document.addEventListener("click", e => {
    if (!el.contains(e.target as Node)) {
      el.querySelectorAll<HTMLDetailsElement>(".series-dd[open]").forEach(d => { d.open = false; });
    }
  });
  el.querySelectorAll<HTMLButtonElement>(".chip.role").forEach(btn => {
    btn.addEventListener("click", () => filterStore.toggleRole(btn.dataset.role as Role));
  });
  el.querySelectorAll<HTMLButtonElement>(".chip.class").forEach(btn => {
    btn.addEventListener("click", () => filterStore.toggleClass(btn.dataset.class!));
  });
  el.querySelectorAll<HTMLButtonElement>(".chip.reset").forEach(btn => {
    btn.addEventListener("click", () => {
      const which = btn.dataset.reset;
      if (which === "roles") filterStore.clearRoles();
      else if (which === "classes") filterStore.clearClasses();
      else if (which === "seasons") filterStore.clearSeasons();
      else if (which === "patches") filterStore.clearPatches();
      else if (which === "raids") filterStore.clearRaids();
      else if (which === "raidSeries") filterStore.clearRaidSeries();
    });
  });

  // Reflect state changes
  filterStore.subscribe(state => {
    el.querySelectorAll<HTMLButtonElement>(".chip.season").forEach(c =>
      c.classList.toggle("active", state.seasons.has(c.dataset.season!)));
    el.querySelectorAll<HTMLButtonElement>(".chip.patch").forEach(c =>
      c.classList.toggle("active", state.patches.has(c.dataset.patch!)));
    el.querySelectorAll<HTMLButtonElement>(".chip.raid").forEach(c =>
      c.classList.toggle("active", state.raids.has(c.dataset.raid!)));
    el.querySelectorAll<HTMLInputElement>(".series-check").forEach(c =>
      c.checked = state.raidSeries.has(c.dataset.raidSeries!));
    el.querySelectorAll<HTMLDetailsElement>(".series-dd").forEach(dd => {
      const checks = dd.querySelectorAll<HTMLInputElement>(".series-check");
      let n = 0;
      checks.forEach(c => { if (c.checked) n++; });
      const badge = dd.querySelector(".series-dd-badge") as HTMLElement;
      badge.textContent = String(n);
      badge.hidden = n === 0;
      dd.classList.toggle("active", n > 0);
    });
    el.querySelectorAll<HTMLButtonElement>(".chip.role").forEach(c =>
      c.classList.toggle("active", state.roles.has(c.dataset.role as Role)));
    el.querySelectorAll<HTMLButtonElement>(".chip.class").forEach(c =>
      c.classList.toggle("active", state.classes.has(c.dataset.class!)));
  });

  // Initial reflect — set the default-active chips on first paint
  el.querySelectorAll<HTMLButtonElement>(".chip.season").forEach(c =>
    c.classList.toggle("active", filterStore.state.seasons.has(c.dataset.season!)));
  el.querySelectorAll<HTMLButtonElement>(".chip.patch").forEach(c =>
    c.classList.toggle("active", filterStore.state.patches.has(c.dataset.patch!)));

  // Collapse-on-scroll: thin sticky bar showing only active filters once the
  // user scrolls past the hero. User can manually expand/collapse via the chevron,
  // which then sticks until they scroll back near the top.
  const summaryEl = el.querySelector(".gf-summary") as HTMLElement;
  const toggleBtn = el.querySelector(".gf-toggle") as HTMLButtonElement;

  function buildSummary(state: typeof filterStore.state): string {
    const seasonById = new Map(SEASONS.map(s => [s.id, s.label]));
    const patchById = new Map(PATCHES.map(p => [p.id, p.label]));
    const raidById = new Map(RAIDS.map(r => [r.id, r.name]));
    const parts: string[] = [];
    const push = (cls: string, label: string) =>
      parts.push(`<span class="gf-pill ${cls}">${label}</span>`);
    state.seasons.forEach(id => push("season", seasonById.get(id) ?? id));
    state.patches.forEach(id => push("patch", patchById.get(id) ?? id));
    state.raids.forEach(id => push("raid", raidById.get(id) ?? id));
    state.raidSeries.forEach(s => push("raid-series", s));
    state.roles.forEach(r => push("role", r));
    state.classes.forEach(c => push("class", c));
    state.difficulties.forEach(d => push("difficulty", d));
    if (parts.length === 0) parts.push(`<span class="gf-pill empty">No filters</span>`);
    return `<span class="gf-summary-label">Filters</span>${parts.join("")}`;
  }
  const refreshSummary = () => { summaryEl.innerHTML = buildSummary(filterStore.state); };
  refreshSummary();
  filterStore.subscribe(refreshSummary);

  let manualOverride: "open" | "closed" | null = null;
  const SCROLL_THRESHOLD = 220;
  function applyCollapse() {
    const scrolled = window.scrollY > SCROLL_THRESHOLD;
    const collapsed = manualOverride === "closed"
      ? true
      : manualOverride === "open"
        ? false
        : scrolled;
    el.classList.toggle("collapsed", collapsed);
    toggleBtn.setAttribute("title", collapsed ? "Expand filters" : "Collapse filters");
    toggleBtn.classList.toggle("flipped", collapsed);
  }
  applyCollapse();
  window.addEventListener("scroll", () => {
    // Reset manual override once user scrolls back near the top, so the bar
    // returns to its default expanded state there.
    if (window.scrollY <= 40) manualOverride = null;
    applyCollapse();
  }, { passive: true });
  toggleBtn.addEventListener("click", () => {
    const isCollapsed = el.classList.contains("collapsed");
    manualOverride = isCollapsed ? "open" : "closed";
    applyCollapse();
  });
  // Click anywhere on the summary row to expand (matches user expectation).
  summaryEl.addEventListener("click", () => {
    if (el.classList.contains("collapsed")) {
      manualOverride = "open";
      applyCollapse();
    }
  });

  return el;
}


function renderChartCard(title: string, sub: string, build: () => Element): HTMLElement {
  const card = document.createElement("div");
  card.className = "chart-card";
  card.innerHTML = `<div class="chart-title">${title}</div><div class="chart-sub">${sub}</div>`;
  const slot = document.createElement("div");
  slot.className = "chart-plot";
  card.appendChild(slot);

  const draw = () => {
    try {
      slot.replaceChildren(build());
    } catch (err) {
      const el = document.createElement("pre");
      el.style.color = "#ef4444";
      el.style.background = "rgba(239,68,68,0.06)";
      el.style.padding = "12px";
      el.style.borderRadius = "8px";
      el.style.fontSize = "12px";
      el.style.whiteSpace = "pre-wrap";
      el.textContent = `Chart failed:\n${err instanceof Error ? err.stack ?? err.message : String(err)}`;
      slot.replaceChildren(el);
      console.error(`[${title}]`, err);
    }
  };
  draw();
  filterStore.subscribe(draw);
  return card;
}


function openModal(content: HTMLElement): void {
  let overlay = document.getElementById("modal-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "modal-overlay";
    overlay.className = "modal-overlay";
    overlay.addEventListener("click", e => {
      if (e.target === overlay) closeModal();
    });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape") closeModal();
    });
    document.body.appendChild(overlay);
  }
  overlay.innerHTML = "";
  const panel = document.createElement("div");
  panel.className = "modal-panel";
  const close = document.createElement("button");
  close.className = "modal-close";
  close.setAttribute("aria-label", "Close");
  close.innerHTML = "&times;";
  close.addEventListener("click", closeModal);
  panel.appendChild(close);
  panel.appendChild(content);
  overlay.appendChild(panel);
  overlay.classList.add("open");
  document.body.style.overflow = "hidden";
}

function closeModal(): void {
  const overlay = document.getElementById("modal-overlay");
  if (overlay) overlay.classList.remove("open");
  document.body.style.overflow = "";
}


async function main(): Promise<void> {
  const app = document.getElementById("app")!;
  app.innerHTML = `<div class="loading">Loading raid data…</div>`;

  let payload;
  let bossesPayload: Awaited<ReturnType<typeof fetchBosses>> = { bosses: [] };
  try {
    [payload, bossesPayload] = await Promise.all([fetchEvents(), fetchBosses()]);
  } catch (e) {
    app.innerHTML = `<div class="loading">Failed to load: ${String(e)}</div>`;
    return;
  }

  indexSpecIcons(payload.events);
  const events = normalizeEvents(payload.events);
  const bosses = bossesPayload.bosses;

  const wrap = document.createElement("div");
  wrap.className = "wrap";

  wrap.appendChild(renderHeader(events));
  wrap.appendChild(renderSummary(events));
  wrap.appendChild(renderGlobalFilters(events, bosses));

  // Sections — each chart re-renders on filter change via renderChartCard
  const section = (id: string, title: string, sub: string, cards: HTMLElement[]) => {
    const s = document.createElement("section");
    s.id = id;
    s.innerHTML = `<div class="section-head"><h2>${title}</h2><div class="section-sub">${sub}</div></div>`;
    for (const c of cards) s.appendChild(c);
    return s;
  };

  wrap.appendChild(section("trends", "Trends", "Signups and raids over time.", [
    renderChartCard("Weekly attending signups by difficulty",
      "Stacked by raid difficulty / event category.",
      () => renderSignupsOverTime(events, filterStore.state)),
    renderChartCard("Raid count per week by difficulty",
      "Event-level view. Class/role filters don't apply here — only the difficulty filter.",
      () => renderDifficultyProgression(events, filterStore.state)),
    renderChartCard("Day-of-week activity heatmap",
      "Each cell = attending signups for that (week, day-of-week). Brighter = busier night.",
      () => renderDayOfWeekHeatmap(events, filterStore.state)),
    renderChartCard("Cumulative season growth",
      "Running totals across the season. Top: signups. Middle: unique characters. Bottom: unique players (Discord IDs, collapses alts).",
      () => renderCumulativeSeason(events, filterStore.state)),
  ]));

  wrap.appendChild(section("composition", "Composition", "Who shows up, in what role, with what spec.", [
    renderChartCard("Signups by class",
      "Attending signups, filtered by the global selection.",
      () => renderClassDistribution(events, filterStore.state)),
    renderChartCard("Class meta over time",
      "Stacked area of class signups per week. Watch for shifts in which classes dominate as the season progresses.",
      () => renderClassMetaOverTime(events, filterStore.state)),
    renderChartCard("Player commitment by class",
      "Average events attended per unique character of each class.",
      () => renderClassConsistency(events, filterStore.state)),
    renderChartCard("Role composition · actual vs ideal mythic",
      "Bar 1 is what's actually signing up. Bar 2 is the theoretical ideal mythic 20-player split (2T / 4.5H / 13.5 DPS).",
      () => renderRoleComp(events, filterStore.state)),
    renderChartCard("Signups by class + spec",
      "Sorted globally by signup count — top of chart is most popular, bottom is least.",
      () => renderSpecDistribution(events, filterStore.state)),
  ]));

  wrap.appendChild(section("progression", "Progression", "Per-boss kills, wipes, and first-kill timeline (sourced from WCL fights).", [
    renderChartCard("Boss progression",
      "Each row = boss, ordered by when first killed. Columns = difficulty. Cell = kills / wipes.",
      () => renderBossProgression(bosses, filterStore.state)),
    renderChartCard("First kills timeline",
      "Chronological list of when each (boss, difficulty) was first defeated.",
      () => renderFirstKillTimeline(bosses, filterStore.state)),
  ]));

  wrap.appendChild(section("gear", "Gear", "Item-level progression sourced from Warcraft Logs.", [
    renderChartCard("Average ilvl over time",
      "Per-week average ilvl across all characters that appeared in WCL logs. Shaded band shows the min-max range of individual ilvls each week.",
      () => renderIlvlOverTime(events, filterStore.state)),
    renderChartCard("Ilvl progression by class",
      "Per-class weekly average ilvl. Each line is one class; gaps mean no signups with ilvl data that week.",
      () => renderIlvlByClassOverTime(events, filterStore.state)),
    renderChartCard("Average ilvl by class",
      "Season-wide average. Note: weighted by signup count, so an inactive character who logged once at low ilvl still contributes that data point.",
      () => renderIlvlByClass(events, filterStore.state)),
  ]));

  wrap.appendChild(section("roster", "Roster & series", "Recurring leaders, characters, and players.", [
    renderChartCard("Raid series breakdown",
      "One row per (leader, type). Sparkline = weekly attending signups across the season.",
      () => renderSeriesBreakdown(events, filterStore.state)),
    renderChartCard("Top 30 most consistent characters",
      "Counted by character name (realm stripped). Bar colored by the character's class.",
      () => renderTopCharacters(events, filterStore.state)),
    renderChartCard("Top 30 most consistent players",
      "Counted by Discord userid (collapses alts). Bar colored by the player's main class.",
      () => renderTopPlayers(events, filterStore.state)),
  ]));

  const footer = document.createElement("footer");
  footer.innerHTML = `Archived every 15 min from raid-helper.xyz · <a href="/legacy">legacy view</a> · <a href="/health">status</a>`;
  wrap.appendChild(footer);

  app.replaceChildren(wrap);

  // Delegated click → open per-series detail modal
  document.addEventListener("click", e => {
    const target = e.target as HTMLElement;
    const bossCell = target.closest<HTMLElement>("[data-boss-cell]");
    if (bossCell) {
      // Don't hijack clicks on links inside the cell (the first-kill / best-pull link).
      if (!target.closest("a")) {
        const eid = parseInt(bossCell.dataset.encounter ?? "", 10);
        const diff = bossCell.dataset.difficulty ?? "";
        const name = bossCell.dataset.bossName ?? "";
        if (eid && diff) {
          openModal(renderBossCellDetail(eid, diff, name));
          return;
        }
      }
    }
    const row = target.closest("[data-series]");
    if (row instanceof HTMLElement && row.dataset.series) {
      openModal(renderSeriesDetail(row.dataset.series, events));
      return;
    }
    // Character name in Plot SVGs (top characters / top players)
    const charEl = target.closest("[data-character]");
    if (charEl) {
      const el = charEl as HTMLElement;
      const charName = el.dataset.character ?? charEl.getAttribute("data-character");
      if (!charName) return;
      // data-player="1" means this came from the top-players chart → show aggregated alts.
      if (el.dataset.player === "1" || charEl.getAttribute("data-player") === "1") {
        openModal(renderCharacterDetail(findAltsByCharacter(charName, events), events));
      } else {
        openModal(renderCharacterDetail(charName, events));
      }
    }
  });

  // Find-character search input + alts toggle + autocomplete suggestions
  const searchInput = wrap.querySelector(".char-search") as HTMLInputElement | null;
  const altsCheckbox = wrap.querySelector(".alts-checkbox") as HTMLInputElement | null;
  const suggestionsEl = wrap.querySelector(".search-suggestions") as HTMLDivElement | null;
  const searchIndex = buildSearchIndex(events);
  let activeSuggestion = -1;
  let currentResults: ReturnType<typeof querySearchIndex> = [];

  function openForName(name: string, altsMode: boolean): void {
    if (altsMode) {
      openModal(renderCharacterDetail(findAltsByCharacter(name, events), events));
    } else {
      openModal(renderCharacterDetail(name, events));
    }
  }

  function renderSuggestions(): void {
    if (!searchInput || !suggestionsEl) return;
    const q = searchInput.value.trim();
    if (!q) { suggestionsEl.hidden = true; return; }
    currentResults = querySearchIndex(searchIndex, q, 8);
    if (currentResults.length === 0) { suggestionsEl.hidden = true; return; }
    suggestionsEl.innerHTML = currentResults.map((r, i) => {
      if (r.kind === "character") {
        const icon = classIconUrl(r.cls);
        return `<button class="search-suggestion${i === activeSuggestion ? " active" : ""}" data-i="${i}">
          ${icon ? `<img class="class-icon" src="${icon}" width="14" height="14">` : ""}
          <span class="name">${r.name}</span>
          <span class="tag">character</span>
          <span class="count">${r.count}</span>
        </button>`;
      } else {
        return `<button class="search-suggestion${i === activeSuggestion ? " active" : ""}" data-i="${i}">
          <span class="name">${r.primaryName} <span class="alts-suffix">+${r.altCount} alt${r.altCount === 1 ? "" : "s"}</span></span>
          <span class="tag player">player</span>
          <span class="count">${r.count}</span>
        </button>`;
      }
    }).join("");
    suggestionsEl.hidden = false;
  }

  function pickSuggestion(i: number): void {
    if (i < 0 || i >= currentResults.length) return;
    const r = currentResults[i];
    if (r.kind === "character") openForName(r.name, !!altsCheckbox?.checked);
    else openModal(renderCharacterDetail(r.alts, events));
    if (searchInput) searchInput.value = "";
    if (suggestionsEl) suggestionsEl.hidden = true;
    activeSuggestion = -1;
  }

  if (searchInput && suggestionsEl) {
    searchInput.addEventListener("input", () => { activeSuggestion = -1; renderSuggestions(); });
    searchInput.addEventListener("focus", () => { renderSuggestions(); });
    searchInput.addEventListener("blur", () => {
      // small delay so click events on suggestions fire before we hide
      setTimeout(() => { suggestionsEl.hidden = true; }, 150);
    });
    searchInput.addEventListener("keydown", e => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeSuggestion = Math.min(currentResults.length - 1, activeSuggestion + 1);
        renderSuggestions();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeSuggestion = Math.max(-1, activeSuggestion - 1);
        renderSuggestions();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (activeSuggestion >= 0) pickSuggestion(activeSuggestion);
        else {
          const name = searchInput.value.trim();
          if (name) openForName(name, !!altsCheckbox?.checked);
        }
      } else if (e.key === "Escape") {
        suggestionsEl.hidden = true;
        activeSuggestion = -1;
      }
    });
    suggestionsEl.addEventListener("click", e => {
      const btn = (e.target as HTMLElement).closest(".search-suggestion") as HTMLElement | null;
      if (!btn) return;
      pickSuggestion(parseInt(btn.dataset.i ?? "-1", 10));
    });
  }
}

main();
