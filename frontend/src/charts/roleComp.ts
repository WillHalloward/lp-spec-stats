import * as Plot from "@observablehq/plot";
import type { Event, Role } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { ROLE_COLORS, THEME } from "../theme";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

const ROLE_ORDER: Role[] = ["Tank", "Healer", "Melee DPS", "Ranged DPS"];

// Ideal mythic 20-player comp: 2T / 4.5H / 13.5 DPS → 10% / 22.5% / 67.5% (split 50/50 melee/ranged).
const IDEAL: Record<Role, number> = {
  Tank: 10,
  Healer: 22.5,
  "Melee DPS": 33.75,
  "Ranged DPS": 33.75,
};

export function renderRoleComp(events: Event[], state: FilterState): SVGElement | HTMLElement {
  const counts: Record<Role, number> = { Tank: 0, Healer: 0, "Melee DPS": 0, "Ranged DPS": 0 };
  for (const [, , role] of filteredSignups(events, state)) {
    if (role) counts[role]++;  // synthesized WCL signups have no role; skip them here
  }
  const total = ROLE_ORDER.reduce((a, r) => a + counts[r], 0) || 1;

  type Row = { group: string; role: Role; pct: number; label: string };
  const rows: Row[] = [];
  // Order matters here — Plot stacks in data order.
  for (const group of ["Actual", "Ideal mythic"] as const) {
    for (const r of ROLE_ORDER) {
      const pct = group === "Actual" ? (100 * counts[r]) / total : IDEAL[r];
      rows.push({ group, role: r, pct, label: `${r} ${pct.toFixed(0)}%` });
    }
  }

  return Plot.plot({
    width: CHART_WIDTH,
    height: 220,
    marginLeft: 110,
    marginRight: 30,
    marginTop: 20,
    marginBottom: 50,
    style: plotStyle,
    x: { label: null, grid: true, domain: [0, 100], tickFormat: d => `${d}%` },
    y: { label: null, domain: ["Actual", "Ideal mythic"] },
    color: {
      domain: ROLE_ORDER,
      range: ROLE_ORDER.map(r => ROLE_COLORS[r]),
      legend: true,
    },
    marks: [
      Plot.barX(rows, {
        x: "pct",
        y: "group",
        fill: "role",
        tip: true,
      }),
      Plot.text(rows, Plot.stackX({
        x: "pct",
        y: "group",
        z: "role",
        text: (d: Row) => (d.pct >= 6 ? d.label : ""),
        fill: "white",
        fontFamily: "Inter, sans-serif",
        fontSize: 11,
      })),
      Plot.ruleX([0], { stroke: THEME.border }),
    ],
  });
}
