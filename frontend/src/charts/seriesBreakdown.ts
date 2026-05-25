import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { isoWeek } from "../normalize";
import { THEME } from "../theme";
import { DIFFICULTY_COLORS } from "../theme";
import { sparkline } from "../format";

const CATEGORY_COLOR: Record<string, string> = {
  Raid: THEME.gold,
  Achievement: DIFFICULTY_COLORS["Achievement"]!,
  "M+": DIFFICULTY_COLORS["M+"]!,
  Mount: DIFFICULTY_COLORS["Mount"]!,
};

export function renderSeriesBreakdown(events: Event[], state: FilterState): HTMLElement {
  // Per-series aggregates
  type Bucket = { events: Set<string>; signups: number; category: string; suffix: string; weekly: Map<string, number> };
  const byLabel = new Map<string, Bucket>();
  const allWeeks = new Set<string>();

  for (const [event, , ] of filteredSignups(events, state)) {
    allWeeks.add(isoWeek(event.unixtime));
    if (!byLabel.has(event.seriesLabel)) {
      // seriesLabel format: "${leader} — ${suffix}" where suffix is the difficulty
      // for Raid events and the category otherwise (M+, Achievement, Mount).
      const dash = event.seriesLabel.indexOf(" — ");
      const suffix = dash === -1 ? event.category : event.seriesLabel.slice(dash + 3);
      byLabel.set(event.seriesLabel, {
        events: new Set(),
        signups: 0,
        category: event.category,
        suffix,
        weekly: new Map(),
      });
    }
    const b = byLabel.get(event.seriesLabel)!;
    b.events.add(event.raidId);
    b.signups++;
    const wk = isoWeek(event.unixtime);
    b.weekly.set(wk, (b.weekly.get(wk) ?? 0) + 1);
  }

  const weeks = Array.from(allWeeks).sort();
  const rows = Array.from(byLabel.entries())
    .map(([label, b]) => ({
      label,
      events: b.events.size,
      signups: b.signups,
      avg: b.signups / Math.max(1, b.events.size),
      category: b.category,
      suffix: b.suffix,
      weekly: weeks.map(w => b.weekly.get(w) ?? 0),
    }))
    .sort((a, b) => b.events - a.events);

  const wrap = document.createElement("div");
  if (rows.length === 0) {
    wrap.style.color = THEME.textMuted;
    wrap.style.padding = "32px 12px";
    wrap.textContent = "No series match the current filter.";
    return wrap;
  }

  wrap.innerHTML = `
    <table class="series-table">
      <thead><tr>
        <th>Leader</th>
        <th>Type</th>
        <th class="num">Events</th>
        <th class="num">Signups</th>
        <th class="num">Avg / event</th>
        <th class="spark-cell">Weekly trend</th>
      </tr></thead>
      <tbody>
        ${rows.map(r => {
          const leader = r.label.includes(" — ") ? r.label.split(" — ")[0] : r.label;
          const color = CATEGORY_COLOR[r.category] ?? THEME.gold;
          const safeLabel = r.label.replace(/"/g, "&quot;");
          return `<tr data-series="${safeLabel}" class="series-row clickable" title="Click for details">
            <td><div class="leader-cell"><span class="leader-dot" style="background:${color}"></span><span class="leader-name">${leader}</span></div></td>
            <td><span class="series-chip">${r.suffix}</span></td>
            <td class="num">${r.events}</td>
            <td class="num">${r.signups}</td>
            <td class="num strong">${r.avg.toFixed(1)}</td>
            <td class="spark-cell">${sparkline(r.weekly, { color })}</td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>
  `;
  return wrap;
}
