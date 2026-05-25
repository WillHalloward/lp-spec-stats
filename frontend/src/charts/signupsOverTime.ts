import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { isoWeek } from "../normalize";
import { DIFFICULTY_COLORS, THEME } from "../theme";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

const DIFF_ORDER = ["Mythic", "Heroic", "Normal", "LFR", "Other", "M+", "Achievement", "Mount"];

export function renderSignupsOverTime(events: Event[], state: FilterState): SVGElement | HTMLElement {
  const byWeekDiff = new Map<string, Map<string, number>>();
  for (const [event] of filteredSignups(events, state)) {
    const wk = isoWeek(event.unixtime);
    const diff = event.category === "Raid" ? event.difficulty : event.category;
    if (!byWeekDiff.has(wk)) byWeekDiff.set(wk, new Map());
    const m = byWeekDiff.get(wk)!;
    m.set(diff, (m.get(diff) ?? 0) + 1);
  }

  const rows: { wk: string; diff: string; count: number }[] = [];
  for (const [wk, m] of byWeekDiff) {
    for (const [diff, count] of m) rows.push({ wk, diff, count });
  }
  // Sort so Plot's stack follows our intended order (mythic on top, etc).
  rows.sort((a, b) =>
    a.wk.localeCompare(b.wk) || DIFF_ORDER.indexOf(a.diff) - DIFF_ORDER.indexOf(b.diff),
  );
  const weeks = Array.from(byWeekDiff.keys()).sort();
  const usedDiffs = DIFF_ORDER.filter(d => rows.some(r => r.diff === d));

  return Plot.plot({
    width: CHART_WIDTH,
    height: 360,
    marginLeft: 50,
    marginBottom: 70,
    marginTop: 30,
    style: plotStyle,
    x: { domain: weeks, label: null, tickRotate: -35, tickPadding: 6 },
    y: { label: null, grid: true, nice: true },
    color: {
      domain: usedDiffs,
      range: usedDiffs.map(d => DIFFICULTY_COLORS[d] ?? "#888"),
      legend: true,
    },
    marks: [
      Plot.barY(rows, {
        x: "wk",
        y: "count",
        fill: "diff",
        tip: true,
      }),
      Plot.ruleY([0], { stroke: THEME.border }),
    ],
  });
}
