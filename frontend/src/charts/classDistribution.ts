import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import { filteredSignups } from "../state";
import type { FilterState } from "../state";
import { CLASS_COLORS, THEME } from "../theme";
import { classIconUrl } from "../icons";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

export function renderClassDistribution(events: Event[], state: FilterState): SVGElement | HTMLElement {
  const counts = new Map<string, number>();
  for (const [, s] of filteredSignups(events, state)) {
    counts.set(s.class, (counts.get(s.class) ?? 0) + 1);
  }

  const data = Array.from(counts, ([cls, count]) => ({ cls, count }))
    .sort((a, b) => b.count - a.count);

  return Plot.plot({
    width: CHART_WIDTH,
    height: 360,
    marginLeft: 50,
    marginRight: 30,
    marginBottom: 70,
    marginTop: 30,
    style: plotStyle,
    x: { label: null, tickPadding: 30, tickSize: 0 },  // tickPadding makes room for icon below
    y: { label: null, grid: true, nice: true },
    marks: [
      Plot.barY(data, {
        x: "cls",
        y: "count",
        fill: d => CLASS_COLORS[d.cls] ?? "#888",
        sort: { x: "y", reverse: true },
        tip: true,
        channels: { class: "cls" },
      }),
      Plot.text(data, {
        x: "cls",
        y: "count",
        text: d => String(d.count),
        dy: -10,
        fill: THEME.text,
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
        sort: { x: "y", reverse: true },
      }),
      // Class icon underneath the bar, just above the x-axis label.
      Plot.image(data, {
        src: d => classIconUrl(d.cls) ?? "",
        x: "cls",
        y: 0,
        dy: 16,
        width: 22,
        height: 22,
        sort: { x: "y", reverse: true },
      }),
      Plot.ruleY([0], { stroke: THEME.border }),
    ],
  });
}
