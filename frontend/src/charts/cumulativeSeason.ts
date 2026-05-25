import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { isoWeek, stripRealm } from "../normalize";
import { THEME } from "../theme";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

/**
 * Three running totals across the season: signups, unique characters, unique players.
 * Plot doesn't have native dual-axis support, so we render three small-multiples
 * stacked in one figure via facetY.
 */
export function renderCumulativeSeason(events: Event[], state: FilterState): SVGElement | HTMLElement {
  type Bucket = { signups: number; chars: Set<string>; players: Set<string> };
  const byWeek = new Map<string, Bucket>();
  for (const [event, signup] of filteredSignups(events, state)) {
    const wk = isoWeek(event.unixtime);
    if (!byWeek.has(wk)) byWeek.set(wk, { signups: 0, chars: new Set(), players: new Set() });
    const b = byWeek.get(wk)!;
    b.signups++;
    b.chars.add(stripRealm(signup.name));
    b.players.add(signup.userid);
  }

  const weeks = Array.from(byWeek.keys()).sort();
  const seenChars = new Set<string>();
  const seenPlayers = new Set<string>();
  let cumSignups = 0;

  type Row = { wk: string; metric: "Signups" | "Characters" | "Players"; value: number };
  const rows: Row[] = [];
  for (const wk of weeks) {
    const b = byWeek.get(wk)!;
    cumSignups += b.signups;
    for (const c of b.chars) seenChars.add(c);
    for (const p of b.players) seenPlayers.add(p);
    rows.push({ wk, metric: "Signups", value: cumSignups });
    rows.push({ wk, metric: "Characters", value: seenChars.size });
    rows.push({ wk, metric: "Players", value: seenPlayers.size });
  }

  return Plot.plot({
    width: CHART_WIDTH,
    height: 380,
    marginLeft: 60,
    marginBottom: 60,
    marginTop: 20,
    style: plotStyle,
    fy: { domain: ["Signups", "Characters", "Players"], label: null },
    x: { domain: weeks, label: null, tickRotate: -35, tickPadding: 6 },
    y: { grid: true, nice: true, label: null },
    color: {
      domain: ["Signups", "Characters", "Players"],
      range: [THEME.gold, THEME.blue, "#a855f7"],
    },
    marks: [
      Plot.areaY(rows, {
        x: "wk", y: "value", fy: "metric",
        fill: "metric", fillOpacity: 0.15, curve: "monotone-x",
      }),
      Plot.lineY(rows, {
        x: "wk", y: "value", fy: "metric",
        stroke: "metric", strokeWidth: 2, curve: "monotone-x", tip: true,
      }),
      Plot.ruleY([0], { stroke: THEME.border }),
    ],
  });
}
