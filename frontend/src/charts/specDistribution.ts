import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { cleanSpec } from "../normalize";
import { CLASS_COLORS, THEME } from "../theme";
import { classIconUrl, specIconUrl } from "../icons";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

/**
 * Sorted horizontal bar of all (class, spec) signup counts, colored by class.
 * The global filter bar takes care of class/role narrowing.
 */
export function renderSpecDistribution(events: Event[], state: FilterState): SVGElement | HTMLElement {
  const counts = new Map<string, { cls: string; spec: string; count: number }>();
  for (const [, s] of filteredSignups(events, state)) {
    const spec = cleanSpec(s.spec);
    if (!spec) continue;  // synthesized WCL signups have no spec
    const key = `${s.class}::${spec}`;
    const existing = counts.get(key);
    if (existing) existing.count++;
    else counts.set(key, { cls: s.class, spec, count: 1 });
  }
  const rows = Array.from(counts.values())
    .map(r => ({ ...r, label: `${r.spec}  ·  ${r.cls}` }))
    .sort((a, b) => b.count - a.count);

  if (rows.length === 0) {
    const el = document.createElement("div");
    el.style.color = THEME.textMuted;
    el.style.padding = "32px 12px";
    el.textContent = "No specs match the current filter.";
    return el;
  }

  return Plot.plot({
    width: CHART_WIDTH,
    height: Math.max(400, 22 * rows.length + 60),
    marginLeft: 230,
    marginRight: 80,
    marginTop: 20,
    marginBottom: 50,
    style: plotStyle,
    x: { label: null, grid: true, nice: true },
    y: { label: null, domain: rows.map(r => r.label) },
    marks: [
      Plot.barX(rows, {
        x: "count",
        y: "label",
        fill: d => CLASS_COLORS[d.cls] ?? "#888",
        tip: true,
        channels: { class: "cls", spec: "spec" },
      }),
      Plot.text(rows, {
        x: "count",
        y: "label",
        text: d => String(d.count),
        dx: 6,
        textAnchor: "start",
        fill: THEME.text,
        fontFamily: "JetBrains Mono, monospace",
      }),
      Plot.image(rows, {
        src: d => specIconUrl(d.cls, d.spec) ?? classIconUrl(d.cls) ?? "",
        x: 0,
        y: "label",
        dx: -200,
        width: 20,
        height: 20,
      }),
      Plot.ruleX([0], { stroke: THEME.border }),
    ],
  });
}
