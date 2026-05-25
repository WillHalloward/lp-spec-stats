import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { isoWeek } from "../normalize";
import { DIFFICULTY_COLORS, THEME } from "../theme";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

const DIFF_ORDER = ["Mythic", "Heroic", "Normal", "LFR", "Other"];

/**
 * Raid count per week by difficulty. Event-level chart so class/role filters
 * don't apply; only the difficulty filter narrows it.
 */
export function renderDifficultyProgression(events: Event[], state: FilterState): SVGElement | HTMLElement {
  const byWeekDiff = new Map<string, Map<string, number>>();
  for (const e of events) {
    if (e.category !== "Raid") continue;
    // Event-level filters: season + patch + difficulty all apply. Class/role
    // are signup-level so they are intentionally ignored here.
    if (state.seasons.size > 0 && !state.seasons.has(e.season)) continue;
    if (state.patches.size > 0 && !state.patches.has(e.patch)) continue;
    if (state.raids.size > 0 && !e.raids.some(r => state.raids.has(r))) continue;
    if (state.raidSeries.size > 0 && !state.raidSeries.has(e.seriesLabel)) continue;
    if (state.difficulties.size > 0 && !state.difficulties.has(e.difficulty)) continue;
    const wk = isoWeek(e.unixtime);
    if (!byWeekDiff.has(wk)) byWeekDiff.set(wk, new Map());
    const m = byWeekDiff.get(wk)!;
    m.set(e.difficulty, (m.get(e.difficulty) ?? 0) + 1);
  }

  const rows: { wk: string; diff: string; count: number }[] = [];
  for (const [wk, m] of byWeekDiff) {
    for (const [diff, count] of m) rows.push({ wk, diff, count });
  }
  rows.sort((a, b) =>
    a.wk.localeCompare(b.wk) || DIFF_ORDER.indexOf(a.diff) - DIFF_ORDER.indexOf(b.diff),
  );
  const weeks = Array.from(byWeekDiff.keys()).sort();
  const usedDiffs = DIFF_ORDER.filter(d => rows.some(r => r.diff === d));

  return Plot.plot({
    width: CHART_WIDTH,
    height: 300,
    marginLeft: 50,
    marginBottom: 70,
    marginTop: 30,
    style: plotStyle,
    x: { domain: weeks, label: null, tickRotate: -35, tickPadding: 6 },
    y: { label: null, grid: true, nice: true, tickFormat: "d" },
    color: {
      domain: usedDiffs,
      range: usedDiffs.map(d => DIFFICULTY_COLORS[d] ?? "#888"),
      legend: true,
    },
    marks: [
      Plot.barY(rows, { x: "wk", y: "count", fill: "diff", tip: true }),
      Plot.ruleY([0], { stroke: THEME.border }),
    ],
  });
}
