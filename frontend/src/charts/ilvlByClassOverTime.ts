import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { isoWeek } from "../normalize";
import { CLASS_COLORS, THEME } from "../theme";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";
import { withHoverLegend } from "./_hoverLegend";

/**
 * Average ilvl per week, broken out by class. One line per class.
 * Weeks without any ilvl data for that class are skipped (gaps in line).
 */
export function renderIlvlByClassOverTime(events: Event[], state: FilterState): SVGElement | HTMLElement {
  type WC = { sum: number; n: number };
  const byWeekClass = new Map<string, Map<string, WC>>();

  for (const [event, signup] of filteredSignups(events, state)) {
    const ilvl = (signup as { _ilvl_max?: number })._ilvl_max;
    if (!ilvl || !Number.isFinite(ilvl)) continue;
    const wk = isoWeek(event.unixtime);
    if (!byWeekClass.has(wk)) byWeekClass.set(wk, new Map());
    const m = byWeekClass.get(wk)!;
    if (!m.has(signup.class)) m.set(signup.class, { sum: 0, n: 0 });
    const c = m.get(signup.class)!;
    c.sum += ilvl;
    c.n++;
  }

  const weeks = Array.from(byWeekClass.keys()).sort();
  if (weeks.length === 0) {
    const el = document.createElement("div");
    el.style.color = THEME.textMuted;
    el.style.padding = "32px 12px";
    el.textContent = "No ilvl data yet.";
    return el;
  }

  // Build long-format rows. Only include rows where we have data, so lines have gaps for missing weeks.
  const allClasses = new Set<string>();
  for (const m of byWeekClass.values()) for (const c of m.keys()) allClasses.add(c);

  type Row = { wk: string; cls: string; avg: number };
  const rows: Row[] = [];
  for (const wk of weeks) {
    const m = byWeekClass.get(wk)!;
    for (const cls of allClasses) {
      const c = m.get(cls);
      if (c && c.n > 0) rows.push({ wk, cls, avg: c.sum / c.n });
    }
  }

  const classOrder = Array.from(allClasses).sort();

  const fig = Plot.plot({
    width: CHART_WIDTH,
    height: 340,
    marginLeft: 60,
    marginBottom: 70,
    marginTop: 20,
    style: plotStyle,
    x: { domain: weeks, label: null, tickRotate: -35, tickPadding: 6 },
    y: { grid: true, nice: true, label: null },
    color: {
      domain: classOrder,
      range: classOrder.map(c => CLASS_COLORS[c] ?? "#888"),
    },
    marks: [
      Plot.lineY(rows, {
        x: "wk", y: "avg",
        stroke: "cls", z: "cls",
        strokeWidth: 2.2, curve: "monotone-x",
        tip: true,
      }),
      Plot.dot(rows, {
        x: "wk", y: "avg",
        fill: "cls", r: 2.6,
      }),
    ],
  });

  return withHoverLegend(
    fig,
    new Map(classOrder.map(c => [c, CLASS_COLORS[c] ?? "#888"])),
  );
}
