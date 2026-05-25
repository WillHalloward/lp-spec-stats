import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { isoWeek } from "../normalize";
import { THEME } from "../theme";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

/**
 * Average ilvl across all signups that had ilvl data (from WCL playerDetails).
 * Bands show min..max range of individual ilvls within the week.
 */
export function renderIlvlOverTime(events: Event[], state: FilterState): SVGElement | HTMLElement {
  type WeekStats = { values: number[] };
  const byWeek = new Map<string, WeekStats>();
  for (const [event, signup] of filteredSignups(events, state)) {
    const ilvl = (signup as { _ilvl_max?: number })._ilvl_max;
    if (!ilvl || !Number.isFinite(ilvl)) continue;
    const wk = isoWeek(event.unixtime);
    if (!byWeek.has(wk)) byWeek.set(wk, { values: [] });
    byWeek.get(wk)!.values.push(ilvl);
  }

  const weeks = Array.from(byWeek.keys()).sort();
  if (weeks.length === 0) {
    const el = document.createElement("div");
    el.style.color = THEME.textMuted;
    el.style.padding = "32px 12px";
    el.textContent = "No ilvl data yet — WCL playerDetails needed.";
    return el;
  }

  const rows = weeks.map(wk => {
    const v = byWeek.get(wk)!.values;
    const sum = v.reduce((a, b) => a + b, 0);
    return {
      wk,
      avg: sum / v.length,
      min: Math.min(...v),
      max: Math.max(...v),
      n: v.length,
    };
  });

  return Plot.plot({
    width: CHART_WIDTH,
    height: 300,
    marginLeft: 60,
    marginBottom: 60,
    marginTop: 20,
    style: plotStyle,
    x: { domain: weeks, label: null, tickRotate: -35, tickPadding: 6 },
    y: { grid: true, nice: true, label: null },
    marks: [
      Plot.areaY(rows, {
        x: "wk", y1: "min", y2: "max",
        fill: THEME.gold, fillOpacity: 0.12, curve: "monotone-x",
      }),
      Plot.lineY(rows, {
        x: "wk", y: "avg",
        stroke: THEME.gold, strokeWidth: 2, curve: "monotone-x", tip: true,
      }),
      Plot.dot(rows, {
        x: "wk", y: "avg",
        fill: THEME.gold, r: 3,
      }),
      Plot.ruleY([rows[0].min], { stroke: THEME.borderSoft, strokeDasharray: "2,4" }),
    ],
  });
}
