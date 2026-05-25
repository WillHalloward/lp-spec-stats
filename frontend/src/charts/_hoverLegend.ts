/**
 * Wrap a Plot.plot() SVG with a custom chip-style legend that highlights
 * the corresponding series on hover by dimming non-matching SVG elements.
 *
 * Works for any Plot mark where the SVG element's stroke or fill color
 * matches one of the colors in `colorMap`.
 *
 * Usage:
 *   const fig = Plot.plot({ ..., color: { domain, range } });
 *   return withHoverLegend(fig, new Map(domain.map((c, i) => [c, range[i]])));
 */
export function withHoverLegend(
  fig: SVGElement | HTMLElement,
  colorMap: Map<string, string>,
): HTMLElement {
  // Build a reverse lookup: lowercased color → category name.
  const byColor = new Map<string, string>();
  for (const [cls, color] of colorMap) byColor.set(color.toLowerCase(), cls);

  // Tag every SVG element whose fill/stroke matches a known color.
  for (const el of fig.querySelectorAll("path, circle, rect, line")) {
    const stroke = (el.getAttribute("stroke") || "").toLowerCase();
    const fill = (el.getAttribute("fill") || "").toLowerCase();
    const cls = byColor.get(stroke) ?? byColor.get(fill);
    if (cls) (el as SVGElement).dataset.cls = cls;
  }

  function setHighlight(active: string | null): void {
    for (const el of fig.querySelectorAll<SVGElement>("[data-cls]")) {
      const isActive = !active || el.dataset.cls === active;
      el.style.opacity = isActive ? "1" : "0.12";
    }
  }

  const legend = document.createElement("div");
  legend.className = "ilvl-legend";
  for (const [cls, color] of colorMap) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "ilvl-legend-item";
    item.innerHTML = `<span class="swatch" style="background:${color}"></span>${cls}`;
    item.addEventListener("mouseenter", () => setHighlight(cls));
    item.addEventListener("mouseleave", () => setHighlight(null));
    legend.appendChild(item);
  }

  const wrap = document.createElement("div");
  wrap.className = "ilvl-byclass-wrap";
  wrap.appendChild(legend);
  wrap.appendChild(fig);
  return wrap;
}
