import * as Plot from "@observablehq/plot";
import type { Event } from "../types";
import type { FilterState } from "../state";
import { filteredSignups } from "../state";
import { stripRealm } from "../normalize";
import { CLASS_COLORS, THEME } from "../theme";
import { classIconUrl } from "../icons";
import { plotStyle, CHART_WIDTH } from "./_plotStyle";

export function renderTopPlayers(events: Event[], state: FilterState, topN = 30): SVGElement | HTMLElement {
  type P = { count: number; names: Map<string, number>; classes: Map<string, number> };
  const players = new Map<string, P>();
  for (const [, s] of filteredSignups(events, state)) {
    const uid = s.userid;
    if (!players.has(uid)) players.set(uid, { count: 0, names: new Map(), classes: new Map() });
    const p = players.get(uid)!;
    p.count++;
    const name = stripRealm(s.name);
    p.names.set(name, (p.names.get(name) ?? 0) + 1);
    p.classes.set(s.class, (p.classes.get(s.class) ?? 0) + 1);
  }

  function topKey<V>(m: Map<string, V>, cmp: (a: V, b: V) => number): string {
    return Array.from(m.entries()).sort((a, b) => cmp(b[1], a[1]))[0][0];
  }

  const rows = Array.from(players, ([_uid, p]) => {
    const topName = topKey(p.names, (a, b) => (a as number) - (b as number));
    const altCount = p.names.size - 1;
    const label = altCount === 0 ? topName : `${topName} (+${altCount} alt${altCount > 1 ? "s" : ""})`;
    const mainClass = topKey(p.classes, (a, b) => (a as number) - (b as number));
    return { label, count: p.count, cls: mainClass };
  }).sort((a, b) => b.count - a.count).slice(0, topN);

  if (rows.length === 0) {
    const el = document.createElement("div");
    el.style.color = THEME.textMuted;
    el.style.padding = "32px 12px";
    el.textContent = "No players match the current filter.";
    return el;
  }

  const fig = Plot.plot({
    width: CHART_WIDTH,
    height: 22 * rows.length + 60,
    marginLeft: 250,
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
        fill: d => CLASS_COLORS[d.cls] ?? THEME.blue,
        tip: true,
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
        src: d => classIconUrl(d.cls) ?? "",
        x: 0,
        y: "label",
        dx: -220,
        width: 18,
        height: 18,
      }),
      Plot.ruleX([0], { stroke: THEME.border }),
    ],
  });

  // Make label text clickable. Labels look like "Akronnys" or "Akronnys (+2 alts)".
  // We strip the "(+N alts)" suffix and mark the element as data-player so the
  // click handler opens the player view (aggregated across all that user's alts).
  for (const t of fig.querySelectorAll("text")) {
    const v = (t.textContent || "").trim();
    if (!v) continue;
    const baseName = v.replace(/\s*\(\+\d+\s+alts?\)\s*$/, "").trim();
    if (rows.some(r => r.label === v)) {
      (t as SVGElement).dataset.character = baseName;
      (t as SVGElement).dataset.player = "1";
      (t as SVGElement).style.cursor = "pointer";
    }
  }
  return fig;
}
