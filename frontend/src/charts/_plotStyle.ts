import { THEME } from "../theme";

/** Style applied to every Plot.plot() call so they share the dashboard theme. */
export const plotStyle = {
  background: "transparent",
  color: THEME.text,
  fontFamily: "Inter, sans-serif",
  fontSize: "12px",
} as const;

export const CHART_WIDTH = 1100;
