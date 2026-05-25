import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { isoWeek } from "../normalize";
import { CLASS_COLORS, THEME } from "../theme";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";
import { withHoverLegend } from "./_hoverLegend";

/**
 * Stacked area: weekly class composition. Shows how meta share shifts over time.
 */
export function renderClassMetaOverTime(events: Event[], state: FilterState): SVGElement | HTMLElement {
  const byWeekClass = new Map<string, Map<string, number>>();
  for (const [event, signup] of filteredSignups(events, state)) {
    const wk = isoWeek(event.unixtime);
    if (!byWeekClass.has(wk)) byWeekClass.set(wk, new Map());
    const m = byWeekClass.get(wk)!;
    m.set(signup.class, (m.get(signup.class) ?? 0) + 1);
  }

  // Build dense data so the stacked area doesn't have gaps.
  const totalByClass = new Map<string, number>();
  for (const m of byWeekClass.values()) {
    for (const [cls, n] of m) totalByClass.set(cls, (totalByClass.get(cls) ?? 0) + n);
  }
  // Order classes by total signups so the stack is visually stable.
  const classOrder = Array.from(totalByClass.keys()).sort((a, b) =>
    (totalByClass.get(b) ?? 0) - (totalByClass.get(a) ?? 0),
  );
  const weeks = Array.from(byWeekClass.keys()).sort();

  const rows: { wk: string; cls: string; count: number }[] = [];
  for (const wk of weeks) {
    const m = byWeekClass.get(wk)!;
    for (const cls of classOrder) rows.push({ wk, cls, count: m.get(cls) ?? 0 });
  }

  const fig = Plot.plot({
    width: CHART_WIDTH,
    height: 320,
    marginLeft: 50,
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
      Plot.areaY(rows, {
        x: "wk", y: "count", fill: "cls",
        order: classOrder,
        curve: "monotone-x",
        tip: true,
      }),
      Plot.ruleY([0], { stroke: THEME.border }),
    ],
  });

  return withHoverLegend(
    fig,
    new Map(classOrder.map(c => [c, CLASS_COLORS[c] ?? "#888"])),
  );
}
