import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { stripRealm } from "../normalize";
import { CLASS_COLORS, THEME } from "../theme";
import { classIconUrl } from "../icons";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

export function renderTopCharacters(events: Event[], state: FilterState, topN = 30): SVGElement | HTMLElement {
  const counts = new Map<string, { count: number; cls: string }>();
  for (const [, s] of filteredSignups(events, state)) {
    const name = stripRealm(s.name);
    const existing = counts.get(name);
    if (existing) existing.count++;
    else counts.set(name, { count: 1, cls: s.class });
  }
  const rows = Array.from(counts, ([name, v]) => ({ name, count: v.count, cls: v.cls }))
    .sort((a, b) => b.count - a.count)
    .slice(0, topN);

  if (rows.length === 0) {
    const el = document.createElement("div");
    el.style.color = THEME.textMuted;
    el.style.padding = "32px 12px";
    el.textContent = "No characters match the current filter.";
    return el;
  }

  const fig = Plot.plot({
    width: CHART_WIDTH,
    height: 22 * rows.length + 60,
    marginLeft: 210,
    marginRight: 80,
    marginTop: 20,
    marginBottom: 50,
    style: plotStyle,
    x: { label: null, grid: true, nice: true },
    y: { label: null, domain: rows.map(r => r.name) },
    marks: [
      Plot.barX(rows, {
        x: "count",
        y: "name",
        fill: d => CLASS_COLORS[d.cls] ?? THEME.gold,
        tip: true,
      }),
      Plot.text(rows, {
        x: "count",
        y: "name",
        text: d => String(d.count),
        dx: 6,
        textAnchor: "start",
        fill: THEME.text,
        fontFamily: "JetBrains Mono, monospace",
      }),
      Plot.image(rows, {
        src: d => classIconUrl(d.cls) ?? "",
        x: 0,
        y: "name",
        dx: -180,
        width: 18,
        height: 18,
      }),
      Plot.ruleX([0], { stroke: THEME.border }),
    ],
  });

  // Tag y-axis tick text elements that match character names so a delegated
  // click handler in main.ts can open the per-character detail modal.
  const nameSet = new Set(rows.map(r => r.name));
  for (const t of fig.querySelectorAll("text")) {
    const v = (t.textContent || "").trim();
    if (nameSet.has(v)) {
      (t as SVGElement).dataset.character = v;
      (t as SVGElement).style.cursor = "pointer";
    }
  }
  return fig;
}
