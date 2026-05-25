import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { isoWeek } from "../normalize";
import { THEME } from "../theme";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function renderDayOfWeekHeatmap(events: Event[], state: FilterState): SVGElement | HTMLElement {
  const cells = new Map<string, number>();
  const weeks = new Set<string>();

  for (const [event] of filteredSignups(events, state)) {
    const dt = new Date(event.unixtime * 1000);
    const dow = (dt.getUTCDay() + 6) % 7;  // 0=Mon..6=Sun
    const wk = isoWeek(event.unixtime);
    weeks.add(wk);
    const key = `${wk}|${dow}`;
    cells.set(key, (cells.get(key) ?? 0) + 1);
  }

  const data: { wk: string; day: string; dayIdx: number; count: number }[] = [];
  const sortedWeeks = Array.from(weeks).sort();
  for (const wk of sortedWeeks) {
    for (let d = 0; d < 7; d++) {
      data.push({ wk, day: DAY_NAMES[d], dayIdx: d, count: cells.get(`${wk}|${d}`) ?? 0 });
    }
  }

  return Plot.plot({
    width: CHART_WIDTH,
    height: 240,
    marginLeft: 50,
    marginBottom: 70,
    marginTop: 20,
    style: plotStyle,
    x: { domain: sortedWeeks, label: null, tickRotate: -35, tickPadding: 6 },
    y: { domain: DAY_NAMES, label: null, reverse: false },
    color: {
      type: "linear",
      range: ["rgba(224,165,38,0.08)", THEME.gold],
      legend: true,
      label: "signups",
    },
    marks: [
      Plot.cell(data, {
        x: "wk",
        y: "day",
        fill: "count",
        inset: 1,
        tip: true,
        channels: { signups: "count" },
      }),
      Plot.text(
        data.filter(d => d.count > 0),
        {
          x: "wk", y: "day", text: "count",
          fill: THEME.text, fontSize: 10,
          fontFamily: "JetBrains Mono, monospace",
        },
      ),
    ],
  });
}
