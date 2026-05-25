import type { Event } from "../types";
import { attendingSignups, stripRealm, RAIDS, raidForEncounter } from "../normalize";
import { classIconUrl } from "../icons";
import { THEME, DIFFICULTY_COLORS } from "../theme";
import { fetchEventKills, type EventKill } from "../api";

/** Build the detail panel (DOM) for one raid series. */
export function renderSeriesDetail(seriesLabel: string, allEvents: Event[]): HTMLElement {
  const seriesEvents = allEvents
    .filter(e => e.seriesLabel === seriesLabel)
    .sort((a, b) => b.unixtime - a.unixtime);

  // Per-character counts + dominant class
  type CharStat = { count: number; cls: string };
  const charStats = new Map<string, CharStat>();
  let totalSignups = 0;
  let ilvlSum = 0;
  let ilvlN = 0;
  for (const [, s] of attendingSignups(seriesEvents)) {
    const name = stripRealm(s.name);
    if (!charStats.has(name)) charStats.set(name, { count: 0, cls: s.class });
    charStats.get(name)!.count++;
    totalSignups++;
    const ilvl = (s as { _ilvl_max?: number })._ilvl_max;
    if (ilvl && Number.isFinite(ilvl)) { ilvlSum += ilvl; ilvlN++; }
  }

  const avgPerEvent = seriesEvents.length > 0 ? totalSignups / seriesEvents.length : 0;
  const avgIlvl = ilvlN > 0 ? ilvlSum / ilvlN : null;

  // Per-event attending counts (raid-level)
  function eventStats(e: Event) {
    let n = 0;
    for (const s of e.signups) {
      const role = s.role ?? "";
      const cls = s.class ?? "";
      if (["Absence", "Tentative", "Bench", "Late"].includes(role)) continue;
      if (["Absence", "Tentative", "Bench", "Late"].includes(cls)) continue;
      if (["Dps", "Tanks", "Healer", "Tank", "Melee", "Ranged"].includes(cls)) continue;
      n++;
    }
    return { n };
  }

  const root = document.createElement("div");
  root.className = "series-detail";

  const leader = seriesLabel.includes(" — ") ? seriesLabel.split(" — ")[0] : seriesLabel;
  const category = seriesLabel.includes(" — ") ? seriesLabel.split(" — ", 2)[1] : "";

  root.innerHTML = `
    <h3>${leader}</h3>
    <div class="meta">${category} · ${seriesEvents.length} events</div>
    <div class="grid">
      <div class="stat primary"><div class="label">Events</div><div class="value">${seriesEvents.length}</div></div>
      <div class="stat"><div class="label">Total signups</div><div class="value">${totalSignups}</div></div>
      <div class="stat"><div class="label">Avg per event</div><div class="value">${avgPerEvent.toFixed(1)}</div></div>
      <div class="stat"><div class="label">Avg ilvl</div><div class="value">${avgIlvl !== null ? avgIlvl.toFixed(1) : "—"}</div></div>
    </div>

    <h4>Raids (most recent first)</h4>
    <div class="raids">
      ${seriesEvents.map(e => {
        const { n } = eventStats(e);
        const dt = new Date(e.unixtime * 1000);
        const date = dt.toISOString().slice(0, 10);
        const day = dt.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
        const diffColor = DIFFICULTY_COLORS[e.difficulty] || THEME.textMuted;
        // Synthesized WCL events have raidId="wcl:<code>" and no raid-helper page;
        // link those straight to WCL. Real raid-helper events keep their event page.
        const isWcl = e.raidId.startsWith("wcl:");
        const href = isWcl
          ? `https://www.warcraftlogs.com/reports/${e.raidId.slice(4)}`
          : `https://raid-helper.xyz/event/${e.raidId}`;
        const linkTitle = isWcl ? "Open WCL report" : "Open in raid-helper";
        return `<a class="raid-row" href="${href}" target="_blank" rel="noopener" title="${linkTitle}">
          <span class="date">${date}</span>
          <span class="day">${day}</span>
          <span class="diff" style="border-left:3px solid ${diffColor}">${e.difficulty}</span>
          <span class="count">${n}</span>
          <span class="title" title="${e.title}">${e.title.slice(0, 80)}</span>
        </a>`;
      }).join("")}
    </div>

    <h4>First kills <span class="muted">(scoped to this series)</span></h4>
    <div class="series-firstkills"><div class="loading muted">Loading…</div></div>

    <h4>Top regulars (${charStats.size} unique characters)</h4>
    <div class="regulars">
      ${Array.from(charStats)
        .sort((a, b) => b[1].count - a[1].count)
        .slice(0, 20)
        .map(([name, st]) => {
          const icon = classIconUrl(st.cls);
          return `<div class="regular">
            ${icon ? `<img class="class-icon" src="${icon}" alt="${st.cls}" width="16" height="16">` : ""}
            <span class="name">${name}</span>
            <span class="count">${st.count}</span>
          </div>`;
        }).join("")}
    </div>
  `;

  // Populate series-scoped first kills asynchronously. We join per-event kill
  // rows from /api/event-kills to the events in THIS series via raid_id, then
  // pick the earliest kill per (encounter, difficulty).
  const seriesRaidIds = new Set(seriesEvents.map(e => e.raidId));
  const firstKillsContainer = root.querySelector(".series-firstkills") as HTMLElement;
  fetchEventKills().then((allKills: EventKill[]) => {
    const scoped = allKills.filter(k => seriesRaidIds.has(k.raid_id));
    // Earliest per (encounter, difficulty)
    const earliest = new Map<string, EventKill>();
    for (const k of scoped) {
      const key = `${k.encounterID}::${k.difficulty}`;
      const existing = earliest.get(key);
      if (!existing || k.kill_ms < existing.kill_ms) earliest.set(key, k);
    }
    if (earliest.size === 0) {
      firstKillsContainer.innerHTML = `<div class="muted">No kills logged for this series yet.</div>`;
      return;
    }
    // Group kills by raid (Voidspire / Dreamrift / MQD), sorted in RAIDS order
    type Row = EventKill & { raidId: string | null };
    const rows: Row[] = Array.from(earliest.values()).map(k => ({
      ...k,
      raidId: raidForEncounter(k.encounterID)?.id ?? null,
    }));
    const raidOrder = new Map(RAIDS.map((r, i) => [r.id, i]));
    rows.sort((a, b) => {
      const ra = a.raidId !== null ? raidOrder.get(a.raidId) ?? 999 : 999;
      const rb = b.raidId !== null ? raidOrder.get(b.raidId) ?? 999 : 999;
      if (ra !== rb) return ra - rb;
      return a.kill_ms - b.kill_ms;
    });
    let lastRaid: string | null = "__none__";
    const parts: string[] = [`<div class="firstkill-list series">`];
    for (const r of rows) {
      const raidName = r.raidId
        ? RAIDS.find(x => x.id === r.raidId)?.name ?? "Other"
        : "Other";
      if (r.raidId !== lastRaid) {
        if (lastRaid !== "__none__") parts.push(`</div>`);
        parts.push(`<div class="firstkill-raid-group"><div class="firstkill-raid-head">${raidName}</div>`);
        lastRaid = r.raidId;
      }
      const date = new Date(r.kill_ms).toISOString().slice(0, 10);
      const diffColor = DIFFICULTY_COLORS[r.difficulty] ?? THEME.gold;
      const href = `https://www.warcraftlogs.com/reports/${r.report_code}${r.fight_id ? `#fight=${r.fight_id}` : ""}`;
      parts.push(`<div class="firstkill-row">
        <div class="fk-date"><a href="${href}" target="_blank" rel="noopener" title="Open in Warcraft Logs">${date}</a></div>
        <div class="fk-diff" style="--diff:${diffColor}">${r.difficulty}</div>
        <div class="fk-name">${r.name}</div>
      </div>`);
    }
    if (lastRaid !== "__none__") parts.push(`</div>`);
    parts.push(`</div>`);
    firstKillsContainer.innerHTML = parts.join("");
  });

  return root;
}
