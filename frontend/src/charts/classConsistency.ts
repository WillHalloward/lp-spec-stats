import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { CLASS_COLORS, THEME } from "../theme";
import { classIconUrl } from "../icons";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

/**
 * Per-class commitment: average events per unique character.
 * Hover shows median, character count, total signups.
 */
export function renderClassConsistency(events: Event[], state: FilterState): SVGElement | HTMLElement {
  const perChar = new Map<string, Map<string, number>>();
  for (const [, s] of filteredSignups(events, state)) {
    if (!perChar.has(s.class)) perChar.set(s.class, new Map());
    const m = perChar.get(s.class)!;
    m.set(s.name, (m.get(s.name) ?? 0) + 1);
  }

  type Row = { cls: string; mean: number; median: number; n: number; total: number; top: number };
  const rows: Row[] = [];
  for (const [cls, chars] of perChar) {
    const counts = Array.from(chars.values()).sort((a, b) => a - b);
    if (counts.length === 0) continue;
    const total = counts.reduce((a, b) => a + b, 0);
    const mean = total / counts.length;
    const median = counts[Math.floor(counts.length / 2)];
    rows.push({ cls, mean, median, n: counts.length, total, top: counts[counts.length - 1] });
  }
  rows.sort((a, b) => b.mean - a.mean);

  return Plot.plot({
    width: CHART_WIDTH,
    height: Math.max(280, 30 * rows.length + 60),
    marginLeft: 130,
    marginRight: 80,
    marginTop: 20,
    marginBottom: 50,
    style: plotStyle,
    x: { label: null, grid: true, nice: true },
    y: { label: null, domain: rows.map(r => r.cls) },
    marks: [
      Plot.barX(rows, {
        x: "mean",
        y: "cls",
        fill: (d: Row) => CLASS_COLORS[d.cls] ?? "#888",
        tip: true,
        channels: {
          "characters": (d: Row) => d.n,
          "total signups": (d: Row) => d.total,
          "median": (d: Row) => d.median,
        },
      }),
      Plot.text(rows, {
        x: "mean",
        y: "cls",
        text: (d: Row) => d.mean.toFixed(1),
        dx: 6,
        textAnchor: "start",
        fill: THEME.text,
        fontFamily: "JetBrains Mono, monospace",
      }),
      // Class icon to the left of the y-axis label.
      Plot.image(rows, {
        src: (d: Row) => classIconUrl(d.cls) ?? "",
        x: 0,
        y: "cls",
        dx: -90,
        width: 22,
        height: 22,
      }),
      Plot.ruleX([0], { stroke: THEME.border }),
    ],
  });
}
