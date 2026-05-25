import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { CLASS_COLORS, THEME } from "../theme";
import { classIconUrl } from "../icons";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

/**
 * Average ilvl per class across the season, sorted descending.
 */
export function renderIlvlByClass(events: Event[], state: FilterState): SVGElement | HTMLElement {
  type Acc = { sum: number; n: number; min: number; max: number };
  const byClass = new Map<string, Acc>();
  for (const [, signup] of filteredSignups(events, state)) {
    const ilvl = (signup as { _ilvl_max?: number })._ilvl_max;
    if (!ilvl || !Number.isFinite(ilvl)) continue;
    if (!byClass.has(signup.class)) byClass.set(signup.class, { sum: 0, n: 0, min: Infinity, max: -Infinity });
    const a = byClass.get(signup.class)!;
    a.sum += ilvl; a.n++;
    if (ilvl < a.min) a.min = ilvl;
    if (ilvl > a.max) a.max = ilvl;
  }

  const rows = Array.from(byClass, ([cls, a]) => ({
    cls, avg: a.sum / a.n, n: a.n, min: a.min, max: a.max,
  })).sort((x, y) => y.avg - x.avg);

  if (rows.length === 0) {
    const el = document.createElement("div");
    el.style.color = THEME.textMuted;
    el.style.padding = "32px 12px";
    el.textContent = "No ilvl data yet.";
    return el;
  }

  const minIlvl = Math.min(...rows.map(r => r.avg));
  const xMin = Math.floor(minIlvl - 3);
  const xMax = Math.ceil(Math.max(...rows.map(r => r.avg)) + 1);

  return Plot.plot({
    width: CHART_WIDTH,
    height: Math.max(280, 30 * rows.length + 60),
    marginLeft: 130,
    marginRight: 80,
    marginTop: 20,
    marginBottom: 50,
    style: plotStyle,
    x: { domain: [xMin, xMax], grid: true, label: null },
    y: { label: null, domain: rows.map(r => r.cls) },
    marks: [
      Plot.barX(rows, {
        x1: xMin, x2: "avg", y: "cls",
        fill: d => CLASS_COLORS[d.cls] ?? "#888",
        tip: true,
        channels: {
          "avg ilvl": (d: { avg: number }) => d.avg.toFixed(1),
          characters: "n",
          range: (d: { min: number; max: number }) => `${d.min}-${d.max}`,
        },
      }),
      Plot.text(rows, {
        x: "avg", y: "cls",
        text: d => d.avg.toFixed(1),
        dx: 6,
        textAnchor: "start",
        fill: THEME.text,
        fontFamily: "JetBrains Mono, monospace",
      }),
      Plot.image(rows, {
        src: d => classIconUrl(d.cls) ?? "",
        x: xMin, y: "cls",
        dx: -90, width: 22, height: 22,
      }),
      Plot.ruleX([xMin], { stroke: THEME.border }),
    ],
  });
}
