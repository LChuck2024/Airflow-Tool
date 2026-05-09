import type { Layout } from "plotly.js";

/** Plotly layout fragment aligned with app light/dark theme */
export function chartLayoutBase(dark: boolean, margin?: Partial<Layout["margin"]>): Partial<Layout> {
  const fg = dark ? "#e8ebf4" : "#0c1222";
  const bg = dark ? "#020617" : "rgba(255,255,255,0.98)";
  return {
    paper_bgcolor: bg,
    plot_bgcolor: bg,
    margin: { t: 16, r: 20, b: 56, l: 56, ...margin },
    font: { family: "Source Sans 3, sans-serif", size: 13, color: fg },
    title: { font: { size: 15, family: "Source Sans 3, sans-serif", color: fg } },
  };
}

/** 横向类目轴很长（DAG/Task 全名）时由 yaxis.automargin 吃满左侧，此处只留底线距 */
export function chartMarginsHorizontalBar(): Partial<Layout["margin"]> {
  return { t: 12, l: 12, r: 28, b: 48 };
}

export function chartMarginsTrend(): Partial<Layout["margin"]> {
  return { t: 12, l: 56, r: 24, b: 72 };
}

/** 横向条数 → 绘图高度，与 layout.height 一致，避免容器很高而图仍是默认高度、底部一大块空 */
export function plotHeightHorizontalBars(barCount: number): number {
  const n = Math.max(barCount, 1);
  const perBar = 22;
  const chrome = 88;
  return Math.round(Math.max(200, n * perBar + chrome));
}

export function chartAxisGrid(dark: boolean): { gridcolor: string; zerolinecolor: string; color?: string } {
  return {
    gridcolor: dark ? "rgba(255,255,255,0.11)" : "rgba(12, 18, 34, 0.09)",
    zerolinecolor: dark ? "rgba(255,255,255,0.16)" : "rgba(12, 18, 34, 0.12)",
    color: dark ? "#c7d0e4" : "#5c6578",
  };
}

export const THEME_STORAGE_KEY = "airflow-dashboard-theme";

export type UiTheme = "light" | "dark";

export function readStoredTheme(): UiTheme {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}
