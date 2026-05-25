import { THEME } from "./theme";

/** Tiny SVG sparkline showing a series of values. */
export function sparkline(values: number[], opts: { width?: number; height?: number; color?: string } = {}): string {
  const width = opts.width ?? 140;
  const height = opts.height ?? 28;
  const color = opts.color ?? THEME.gold;
  if (values.length === 0) return "";
  const n = values.length;
  const mx = Math.max(...values, 1);
  const pad = 3;
  if (n === 1) {
    const y = pad + (height - 2 * pad) * (1 - values[0] / mx);
    return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><circle cx="${width / 2}" cy="${y.toFixed(1)}" r="2" fill="${color}"/></svg>`;
  }
  const innerW = width - 2 * pad;
  const innerH = height - 2 * pad;
  const pts: string[] = [];
  for (let i = 0; i < n; i++) {
    const x = pad + (i / (n - 1)) * innerW;
    const y = pad + innerH * (1 - values[i] / mx);
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  const poly = pts.join(" ");
  const lastX = pad + innerW;
  const area = `M ${pts[0]} L ${pts.slice(1).join(" L ")} L ${lastX.toFixed(1)},${(height - pad).toFixed(1)} L ${pad},${(height - pad).toFixed(1)} Z`;
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <path d="${area}" fill="${color}" fill-opacity="0.18"/>
    <polyline points="${poly}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}


export function fmtNum(n: number): string {
  return n.toLocaleString("en-US");
}
