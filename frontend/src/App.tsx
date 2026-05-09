import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement, type ReactNode } from "react";
import Plot from "react-plotly.js";
import type { Data, Layout } from "plotly.js";
import { fetchFact, runPipeline } from "./api";
import {
  chartAxisGrid,
  chartLayoutBase,
  chartMarginsHorizontalBar,
  chartMarginsTrend,
  plotHeightHorizontalBars,
  readStoredTheme,
  THEME_STORAGE_KEY,
  type UiTheme,
} from "./chartTheme";
import { dateInRange, normalizeRows } from "./normalize";
import type { FactRow } from "./types";
import { formatIsoToBeijing } from "./beijingTime";
import "./App.css";

function uniqSorted<T>(arr: T[]): T[] {
  return [...new Set(arr)].sort() as T[];
}

function formatYmd(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseYmd(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function addDaysYmd(ymd: string, delta: number): string {
  const dt = parseYmd(ymd);
  dt.setUTCDate(dt.getUTCDate() + delta);
  return formatYmd(dt);
}

/** ISO 日期字符串比较（YYYY-MM-DD） */
function maxYmd(a: string, b: string): string {
  if (!a) return b;
  if (!b) return a;
  return a >= b ? a : b;
}

/** 当前 Asia/Shanghai 日历日 YYYY-MM-DD（与 fact 中 run_day 口径一致；须补零以适配 input[type=date]） */
function todayYmdShanghai(): string {
  return new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
}

function quantileSorted(sortedAsc: number[], q: number): number {
  if (!sortedAsc.length) return 0;
  const clamped = Math.min(1, Math.max(0, q));
  const pos = (sortedAsc.length - 1) * clamped;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sortedAsc[lo];
  return sortedAsc[lo] + (sortedAsc[hi] - sortedAsc[lo]) * (pos - lo);
}

function quantileNs(values: number[], q: number): number {
  if (!values.length) return 0;
  return quantileSorted([...values].sort((a, b) => a - b), q);
}

function stdSample(values: number[]): number {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const v = values.reduce((s, x) => s + (x - mean) ** 2, 0) / (values.length - 1);
  return Math.sqrt(v);
}

function groupMeanByKey(rows: FactRow[], keyFn: (r: FactRow) => string): Map<string, number[]> {
  const m = new Map<string, number[]>();
  for (const r of rows) {
    const k = keyFn(r);
    if (!k) continue;
    if (!m.has(k)) m.set(k, []);
    m.get(k)!.push(r.duration_min);
  }
  return m;
}

function riskFromCv(cv: number): "高风险" | "中风险" | "低风险" {
  if (cv > 0.6) return "高风险";
  if (cv > 0.3) return "中风险";
  return "低风险";
}

function RiskPill({ level }: { level: "高风险" | "中风险" | "低风险" }) {
  const c = level === "高风险" ? "high" : level === "中风险" ? "mid" : "low";
  return <span className={`risk-pill risk-pill--${c}`}>{level}</span>;
}

function AnomalyPill({ high }: { high: boolean }) {
  return (
    <span className={`risk-pill ${high ? "risk-pill--high" : "risk-pill--mid"}`}>{high ? "高异常" : "中异常"}</span>
  );
}

function IconCalendar() {
  return (
    <svg className="sidebar-icon" width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </svg>
  );
}

function IconLayers() {
  return (
    <svg className="sidebar-icon" width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <polygon points="12 2 2 7 12 12 22 7 12 2" />
      <polyline points="2 17 12 22 22 17" />
      <polyline points="2 12 12 17 22 12" />
    </svg>
  );
}

function IconActivity() {
  return (
    <svg className="sidebar-icon" width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  );
}

function IconGrid() {
  return (
    <svg className="sidebar-icon" width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
    </svg>
  );
}

function IconSearch() {
  return (
    <svg className="sidebar-icon" width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

function IconSliders() {
  return (
    <svg className="sidebar-icon" width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6" />
    </svg>
  );
}

function IconLayoutDashboard() {
  return (
    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </svg>
  );
}

function IconAlertTriangle() {
  return (
    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function IconTable() {
  return (
    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18" />
    </svg>
  );
}

function IconClock() {
  return (
    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

function IconChartBar() {
  return (
    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  );
}

function rowsToCsv(rows: FactRow[]): string {
  if (!rows.length) return "";
  const keys = Object.keys(rows[0]) as (keyof FactRow)[];
  const esc = (v: unknown) => {
    if (v == null) return "";
    const s = String(v);
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  return [keys.join(","), ...rows.map((r) => keys.map((k) => esc(r[k])).join(","))].join("\n");
}

function ThemeToggleGlyph({ dark }: { dark: boolean }) {
  if (dark) {
    return (
      <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden>
        <circle cx="12" cy="12" r="5" />
        <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
      </svg>
    );
  }
  return (
    <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function StatCard({
  label,
  value,
  smallIcon,
  watermarkIcon,
}: {
  label: string;
  value: ReactNode;
  smallIcon: ReactNode;
  watermarkIcon: ReactNode;
}) {
  return (
    <div className="stat-card">
      <div className="stat-card__watermark">{watermarkIcon}</div>
      <div className="stat-card__label">
        {smallIcon}
        {label}
      </div>
      <div className="stat-card__value">{value}</div>
    </div>
  );
}

export default function App() {
  const [rawRows, setRawRows] = useState<FactRow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"overview" | "task" | "anomaly" | "detail">("overview");

  const [curlText, setCurlText] = useState("");
  const [dagAllowInput, setDagAllowInput] = useState("");
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineLog, setPipelineLog] = useState<string | null>(null);
  const [pipelineErr, setPipelineErr] = useState<string | null>(null);

  const [startDay, setStartDay] = useState("");
  const [endDay, setEndDay] = useState("");
  const [dagMulti, setDagMulti] = useState<string[]>([]);
  const [stateMulti, setStateMulti] = useState<string[]>([]);
  const [domainMulti, setDomainMulti] = useState<string[]>([]);
  const [taskKeyword, setTaskKeyword] = useState("");
  const [topN, setTopN] = useState(20);

  const [volLookback, setVolLookback] = useState(14);
  const [volMinSamples, setVolMinSamples] = useState(3);

  const [selectedTask, setSelectedTask] = useState("");
  const [lookbackDays, setLookbackDays] = useState(7);
  const [metricMode, setMetricMode] = useState<"mean" | "p95" | "max">("mean");
  const [alertRatio, setAlertRatio] = useState(1.3);
  const [theme, setTheme] = useState<UiTheme>(() => readStoredTheme());
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [copyToast, setCopyToast] = useState<string | null>(null);

  const initFilters = useRef(false);

  const copyPlain = useCallback(async (text: string, okMsg: string) => {
    const t = text.trim();
    if (!t) return;
    try {
      await navigator.clipboard.writeText(t);
      setCopyToast(okMsg);
      window.setTimeout(() => setCopyToast(null), 1800);
    } catch {
      setCopyToast("复制失败，请直接在下方文本框中选中文本复制");
      window.setTimeout(() => setCopyToast(null), 2800);
    }
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 961px)");
    const onChange = () => {
      if (mq.matches) setMobileFiltersOpen(false);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await fetchFact();
      setRawRows(normalizeRows(res.rows));
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
      setRawRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const dagOptions = useMemo(
    () => uniqSorted(rawRows.map((r) => r.dag_id).filter((x): x is string => !!x)),
    [rawRows],
  );
  const stateOptions = useMemo(
    () => uniqSorted(rawRows.map((r) => r.state).filter((x): x is string => !!x)),
    [rawRows],
  );
  const domainOptions = useMemo(
    () => uniqSorted(rawRows.map((r) => r.domain).filter((x): x is string => !!x)),
    [rawRows],
  );

  const dayBounds = useMemo(() => {
    const days = rawRows.map((r) => r.run_day).filter(Boolean).sort();
    if (!days.length) return { min: "", max: "" };
    return { min: days[0], max: days[days.length - 1] };
  }, [rawRows]);

  /** 日历控件可选范围：下限仍为数据集最小 run_day；上限至少到上海「今天」，避免数据滞后时无法选今日 */
  const datePickerBounds = useMemo(() => {
    if (!dayBounds.min || !dayBounds.max) return { min: "", max: "" };
    const today = todayYmdShanghai();
    return { min: dayBounds.min, max: maxYmd(dayBounds.max, today) };
  }, [dayBounds]);

  useEffect(() => {
    if (!dayBounds.min || !dayBounds.max) return;
    if (!startDay || !endDay) {
      const defStart = addDaysYmd(dayBounds.max, -6);
      const s = defStart < dayBounds.min ? dayBounds.min : defStart;
      setStartDay(s);
      setEndDay(dayBounds.max);
    }
  }, [dayBounds, startDay, endDay]);

  useEffect(() => {
    if (!initFilters.current && dagOptions.length && !dagMulti.length) {
      initFilters.current = true;
      setDagMulti(dagOptions.slice(0, Math.min(6, dagOptions.length)));
      setStateMulti(stateOptions);
      setDomainMulti(domainOptions);
    }
  }, [dagOptions, dagMulti.length, stateOptions, domainOptions]);

  const filtered = useMemo(() => {
    const sd = startDay || dayBounds.min;
    const ed = endDay || dayBounds.max;
    if (!sd || !ed) return [];
    let out = rawRows.filter((r) => r.run_day && dateInRange(r.run_day, sd, ed));
    if (dagMulti.length) out = out.filter((r) => r.dag_id && dagMulti.includes(r.dag_id));
    if (stateMulti.length) out = out.filter((r) => r.state && stateMulti.includes(r.state));
    if (domainMulti.length) out = out.filter((r) => r.domain && domainMulti.includes(r.domain));
    const kw = taskKeyword.trim().toLowerCase();
    if (kw) out = out.filter((r) => (r.task_id || "").toLowerCase().includes(kw));
    return out;
  }, [rawRows, startDay, endDay, dayBounds, dagMulti, stateMulti, domainMulti, taskKeyword]);

  const filteredDisplay = useMemo(() => {
    return filtered.map((r) => ({
      ...r,
      execution_date: formatIsoToBeijing(r.execution_date) || (r.execution_date ?? ""),
      start_date: formatIsoToBeijing(r.start_date ?? null) || (r.start_date ?? ""),
      end_date: formatIsoToBeijing(r.end_date ?? null) || (r.end_date ?? ""),
    }));
  }, [filtered]);

  const volatilityRows = useMemo(() => {
    if (!filtered.length) return [];
    const days = filtered.map((r) => r.run_day).filter(Boolean).sort();
    const maxDay = days[days.length - 1];
    if (!maxDay) return [];
    const volStart = addDaysYmd(maxDay, -(volLookback - 1));
    const recent = filtered.filter((r) => r.run_day && r.run_day >= volStart);
    const byTaskDay = new Map<string, Map<string, number[]>>();
    for (const r of recent) {
      if (!r.dag_id || !r.task_id || !r.run_day) continue;
      const tk = `${r.dag_id}\t${r.task_id}`;
      if (!byTaskDay.has(tk)) byTaskDay.set(tk, new Map());
      const m = byTaskDay.get(tk)!;
      if (!m.has(r.run_day)) m.set(r.run_day, []);
      m.get(r.run_day)!.push(r.duration_min);
    }
    const rows: {
      dag_id: string;
      task_id: string;
      valid_days: number;
      avg_min: number;
      std_min: number;
      cv: number;
      range_min: number;
      min_min: number;
      max_min: number;
      risk_level: "高风险" | "中风险" | "低风险";
    }[] = [];
    for (const [tk, dayMap] of byTaskDay) {
      const dailyMeans: number[] = [];
      for (const [, vals] of dayMap) {
        dailyMeans.push(vals.reduce((a, b) => a + b, 0) / vals.length);
      }
      const valid_days = dailyMeans.length;
      if (valid_days < volMinSamples) continue;
      const avg_min = dailyMeans.reduce((a, b) => a + b, 0) / dailyMeans.length;
      const std_min = stdSample(dailyMeans);
      const min_min = Math.min(...dailyMeans);
      const max_min = Math.max(...dailyMeans);
      const cv = avg_min > 0 ? std_min / avg_min : 0;
      const [dag_id, task_id] = tk.split("\t");
      rows.push({
        dag_id,
        task_id,
        valid_days,
        avg_min,
        std_min,
        cv,
        range_min: max_min - min_min,
        min_min,
        max_min,
        risk_level: riskFromCv(cv),
      });
    }
    return rows
      .sort((a, b) => b.cv - a.cv || b.std_min - a.std_min || b.range_min - a.range_min)
      .slice(0, topN);
  }, [filtered, volLookback, volMinSamples, topN]);

  const taskOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of filtered) {
      if (r.dag_id && r.task_id) set.add(`${r.dag_id} / ${r.task_id}`);
    }
    return [...set].sort();
  }, [filtered]);

  useEffect(() => {
    if (taskOptions.length && !selectedTask) setSelectedTask(taskOptions[0]);
    else if (selectedTask && !taskOptions.includes(selectedTask) && taskOptions[0]) {
      setSelectedTask(taskOptions[0]);
    }
  }, [taskOptions, selectedTask]);

  const onRunPipeline = async () => {
    setPipelineErr(null);
    setPipelineLog(null);
    setPipelineRunning(true);
    try {
      const res = await runPipeline({ curl_text: curlText, dag_allowlist: dagAllowInput.trim() });
      setPipelineLog(res.stdout);
      if (res.ok) await reload();
      else setPipelineErr(res.message || "ETL 失败");
    } catch (e) {
      setPipelineErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPipelineRunning(false);
    }
  };

  const barData = useMemo(() => {
    const g = groupMeanByKey(filtered, (r) =>
      r.dag_id && r.task_id ? `${r.dag_id}|||${r.task_id}` : "",
    );
    const rows = [...g.entries()]
      .map(([k, vals]) => {
        const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
        const [dag_id, task_id] = k.split("|||");
        return { dag_id, task_id, duration_min: mean, dag_task: `${dag_id} / ${task_id}` };
      })
      .sort((a, b) => b.duration_min - a.duration_min)
      .slice(0, topN);
    const qs = rows.map((r) => r.duration_min).sort((a, b) => a - b);
    const q5 = quantileSorted(qs, 0.5);
    const q8 = quantileSorted(qs, 0.8);
    return rows.map((r) => {
      let risk: "低耗时" | "中耗时" | "高耗时" = "低耗时";
      if (r.duration_min > q8) risk = "高耗时";
      else if (r.duration_min > q5) risk = "中耗时";
      return { ...r, 耗时风险: risk };
    });
  }, [filtered, topN]);

  const volPlainText = useMemo(() => {
    if (!volatilityRows.length) return "";
    const header = "排名\t变异系数\t风险等级\tDAG / Task";
    const rows = [...volatilityRows].sort(
      (a, b) => b.cv - a.cv || b.std_min - a.std_min || b.range_min - a.range_min || `${b.dag_id}`.localeCompare(`${a.dag_id}`),
    );
    const body = rows
      .map((r, i) => `${i + 1}\t${r.cv.toFixed(4)}\t${r.risk_level}\t${r.dag_id} / ${r.task_id}`)
      .join("\n");
    return `${header}\n${body}`;
  }, [volatilityRows]);

  const barPlainText = useMemo(() => {
    const header = "排名\t平均耗时(分)\t分档\tDAG / Task";
    const body = barData
      .map((r, i) => `${i + 1}\t${r.duration_min.toFixed(2)}\t${r.耗时风险}\t${r.dag_task}`)
      .join("\n");
    return barData.length ? `${header}\n${body}` : "";
  }, [barData]);

  const lineData = useMemo(() => {
    const gm = groupMeanByKey(filtered, (r) => r.run_day);
    return [...gm.entries()]
      .map(([run_day, vals]) => ({
        run_day,
        duration_min: vals.reduce((a, b) => a + b, 0) / vals.length,
      }))
      .sort((a, b) => a.run_day.localeCompare(b.run_day));
  }, [filtered]);

  const abnormal = useMemo(() => {
    const q = quantileNs(
      filtered.map((r) => r.duration_min),
      0.95,
    );
    return filtered
      .filter((r) => r.duration_min > q)
      .map((r) => ({
        ...r,
        异常等级高: r.duration_min >= q * 1.5,
        threshold: q,
      }))
      .sort((a, b) => b.duration_min - a.duration_min);
  }, [filtered]);

  const p95Threshold = useMemo(
    () => quantileNs(filtered.map((r) => r.duration_min), 0.95),
    [filtered],
  );

  const taskCompare = useMemo(() => {
    if (!selectedTask) return null;
    const ix = selectedTask.indexOf(" / ");
    if (ix < 0) return null;
    const dag_id = selectedTask.slice(0, ix);
    const task_id = selectedTask.slice(ix + 3);
    const taskRows = filtered.filter((r) => r.dag_id === dag_id && r.task_id === task_id);
    const byDay = new Map<string, number[]>();
    for (const r of taskRows) {
      if (!r.run_day) continue;
      if (!byDay.has(r.run_day)) byDay.set(r.run_day, []);
      byDay.get(r.run_day)!.push(r.duration_min);
    }
    const daily = [...byDay.entries()]
      .map(([run_day, vals]) => {
        const sorted = [...vals].sort((a, b) => a - b);
        const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
        const max = Math.max(...vals);
        const p95 = quantileSorted(sorted, 0.95);
        let primary = mean;
        if (metricMode === "p95") primary = p95;
        else if (metricMode === "max") primary = max;
        return { run_day, mean, max, p95, primary };
      })
      .sort((a, b) => a.run_day.localeCompare(b.run_day));
    const tail = daily.slice(-(lookbackDays + 1));
    if (tail.length < 1) return { dag_id, task_id, daily: tail, baseline: 0, today: null as null | (typeof tail)[0], metricLabel: "" };
    const todayRow = tail[tail.length - 1];
    const baselineRows = tail.slice(0, -1);
    const baseline =
      baselineRows.length > 0 ? baselineRows.reduce((s, x) => s + x.primary, 0) / baselineRows.length : 0;
    const metricLabel = metricMode === "p95" ? "95% 分位" : metricMode === "max" ? "最大值" : "均值";
    return { dag_id, task_id, daily: tail, baseline, today: todayRow, metricLabel };
  }, [filtered, selectedTask, lookbackDays, metricMode]);

  const isDark = theme === "dark";

  const volChartFixed = useMemo(() => {
    if (!volatilityRows.length) return null;
    const bySeverity = [...volatilityRows].sort(
      (a, b) => b.cv - a.cv || b.std_min - a.std_min || b.range_min - a.range_min || `${a.dag_id}`.localeCompare(`${b.dag_id}`),
    );
    const rankLabels = bySeverity.map((_, i) => `#${i + 1}`);
    const data: Data[] = [
      {
        type: "bar",
        orientation: "h",
        x: bySeverity.map((r) => r.cv),
        y: rankLabels,
        marker: {
          color: bySeverity.map((r) =>
            r.risk_level === "高风险" ? "#dc2626" : r.risk_level === "中风险" ? "#f59e0b" : "#16a34a",
          ),
        },
        hovertext: bySeverity.map(
          (r) =>
            `${r.dag_id} / ${r.task_id}<br>${r.risk_level} · 标准差 ${r.std_min.toFixed(2)} 分 · 极差 ${r.range_min.toFixed(2)} 分 · 日均 ${r.avg_min.toFixed(2)} 分 · ${r.valid_days} 天`,
        ),
        hovertemplate: "%{hovertext}<br>变异系数 = %{x:.4f}<extra></extra>",
      },
    ];
    const h = plotHeightHorizontalBars(bySeverity.length);
    const layout: Partial<Layout> = {
      ...chartLayoutBase(isDark, chartMarginsHorizontalBar()),
      height: h,
      autosize: false,
      showlegend: false,
      xaxis: {
        ...chartAxisGrid(isDark),
        title: { text: "变异系数（标准差 ÷ 日均分钟，无单位）", standoff: 12 },
        zeroline: true,
      },
      yaxis: {
        ...chartAxisGrid(isDark),
        title: { text: "排名（越靠上越严重，第 1 名波动最大）", standoff: 6 },
        automargin: true,
        tickfont: { size: 12 },
        autorange: "reversed",
      },
    };
    return { data, layout };
  }, [volatilityRows, isDark]);

  const barChart = useMemo(() => {
    const colorMap: Record<string, string> = { 高耗时: "#dc2626", 中耗时: "#f59e0b", 低耗时: "#16a34a" };
    const bySeverity = [...barData];
    const rankLabels = bySeverity.map((_, i) => `#${i + 1}`);
    const data: Data[] = [
      {
        type: "bar",
        orientation: "h",
        x: bySeverity.map((r) => r.duration_min),
        y: rankLabels,
        marker: { color: bySeverity.map((r) => colorMap[r.耗时风险]) },
        hovertext: bySeverity.map((r) => `${r.dag_task}<br>${r.耗时风险}`),
        hovertemplate: "%{hovertext}<br>平均耗时 %{x:.2f} 分钟<extra></extra>",
      },
    ];
    const h = plotHeightHorizontalBars(bySeverity.length);
    const layout: Partial<Layout> = {
      ...chartLayoutBase(isDark, chartMarginsHorizontalBar()),
      height: h,
      autosize: false,
      showlegend: false,
      xaxis: {
        ...chartAxisGrid(isDark),
        title: { text: "算术平均耗时（分钟）", standoff: 10 },
      },
      yaxis: {
        ...chartAxisGrid(isDark),
        title: { text: "排名（靠上越慢，第 1 名平均耗时最长）", standoff: 6 },
        automargin: true,
        tickfont: { size: 12 },
        autorange: "reversed",
      },
    };
    return { data, layout };
  }, [barData, isDark]);

  const lineChart = useMemo(() => {
    const data: Data[] = [
      {
        type: "scatter",
        mode: "lines+markers",
        x: lineData.map((r) => r.run_day),
        y: lineData.map((r) => r.duration_min),
        line: { color: isDark ? "#60a5fa" : "#2563eb", width: 3 },
        marker: { size: 7 },
        hovertemplate: "日期 %{x}<br>当日样本平均耗时 %{y:.2f} 分<extra></extra>",
      },
    ];
    const layout: Partial<Layout> = {
      ...chartLayoutBase(isDark, chartMarginsTrend()),
      showlegend: false,
      xaxis: {
        ...chartAxisGrid(isDark),
        title: { text: "运行日（run_day）", standoff: 10 },
        tickangle: -40,
        automargin: true,
      },
      yaxis: { ...chartAxisGrid(isDark), title: { text: "平均耗时（分钟）", standoff: 8 } },
    };
    return { data, layout };
  }, [lineData, isDark]);

  const compareChart = useMemo(() => {
    if (!taskCompare || !taskCompare.today) return null;
    const { daily, baseline, metricLabel, task_id } = taskCompare;
    const barTrace: Data = {
      type: "bar",
      x: daily.map((d) => d.run_day),
      y: daily.map((d) => d.primary),
      name: `${metricLabel}(柱状)`,
      marker: {
        color: isDark ? "rgba(56, 189, 248, 0.42)" : "rgba(37, 99, 235, 0.55)",
        line: { color: isDark ? "rgba(125, 211, 252, 0.85)" : "#1d4ed8", width: 1 },
      },
    };
    const trendDaily = [...daily].sort((a, b) => a.run_day.localeCompare(b.run_day));
    const lineW = isDark ? 2.75 : 2.25;
    const mk = isDark ? 9 : 7;
    /* 单 Y 轴：柱与折线单位同为「分钟」，原先 y/y2 各自 autorange 会导致像素错位，图例上的折线像「消失」 */
    const traces: Data[] = [
      barTrace,
      {
        type: "scatter",
        mode: "lines+markers",
        x: trendDaily.map((d) => d.run_day),
        y: trendDaily.map((d) => d.mean),
        name: "均值",
        line: { color: isDark ? "#e2e8f0" : "#475569", width: lineW, shape: "spline", smoothing: 0.35 },
        marker: { size: mk, color: isDark ? "#f1f5f9" : "#475569", line: { width: 0 } },
      },
      {
        type: "scatter",
        mode: "lines+markers",
        x: trendDaily.map((d) => d.run_day),
        y: trendDaily.map((d) => d.p95),
        name: "95% 分位",
        line: { color: isDark ? "#fbbf24" : "#b45309", width: lineW, shape: "spline", smoothing: 0.35 },
        marker: { size: mk, color: isDark ? "#fcd34d" : "#b45309", line: { width: 0 } },
      },
      {
        type: "scatter",
        mode: "lines+markers",
        x: trendDaily.map((d) => d.run_day),
        y: trendDaily.map((d) => d.max),
        name: "最大值",
        line: { color: isDark ? "#fb7185" : "#dc2626", width: lineW, shape: "spline", smoothing: 0.35 },
        marker: { size: mk, color: isDark ? "#fda4af" : "#dc2626", line: { width: 0 } },
      },
    ];
    const fg = isDark ? "#e8ebf4" : "#0c1222";
    const layout: Partial<Layout> = {
      ...chartLayoutBase(isDark, { t: 24, r: 28, b: 92, l: 56 }),
      title: `${task_id} 每日${metricLabel}耗时对比(分钟)`,
      xaxis: { ...chartAxisGrid(isDark), title: "运行日期", tickformat: "%Y-%m-%d" },
      yaxis: {
        ...chartAxisGrid(isDark),
        title: `${metricLabel}(柱) · 均值 / P95 / 最大值（线）`,
        rangemode: "tozero",
      },
      legend: {
        orientation: "h",
        yanchor: "top",
        y: -0.2,
        xanchor: "center",
        x: 0.5,
        font: { size: 12, color: fg },
        bgcolor: isDark ? "rgba(15, 23, 42, 0.82)" : "rgba(255,255,255,0.92)",
        bordercolor: isDark ? "rgba(148,163,184,0.35)" : "rgba(15,23,42,0.08)",
        borderwidth: 1,
      },
      shapes:
        baseline > 0
          ? [
              {
                type: "line",
                xref: "paper",
                yref: "y",
                x0: 0,
                x1: 1,
                y0: baseline,
                y1: baseline,
                line: {
                  dash: "dash",
                  width: 2,
                  color: isDark ? "rgba(251, 191, 36, 0.85)" : "#ca8a04",
                },
              },
            ]
          : [],
    };
    return { data: traces, layout };
  }, [taskCompare, isDark]);

  let taskStatusMsg: ReactElement | null = null;
  if (taskCompare && taskCompare.today && taskCompare.baseline > 0) {
    const slow = taskCompare.today.primary / taskCompare.baseline;
    if (slow >= alertRatio) {
      taskStatusMsg = (
        <div className="msg-error">
          状态: 红色告警 | 今日为基线 {slow.toFixed(2)}x，阈值 {alertRatio}x
        </div>
      );
    } else if (slow >= alertRatio * 0.85) {
      taskStatusMsg = (
        <div className="msg-warn">
          状态: 黄色预警 | 倍率 {slow.toFixed(2)}x
        </div>
      );
    } else {
      taskStatusMsg = <div className="msg-ok">状态: 绿色正常 | 倍率 {slow.toFixed(2)}x</div>;
    }
  }

  if (loading && !rawRows.length) {
    return (
      <div className="app-shell">
        <div className="loading-screen">
          <div className="loading-screen__spin" aria-hidden />
          <p className="loading-screen__text">加载指标数据中…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__main">
          <div className="app-header__brand">
            <div className="app-header__logo" aria-hidden>
              <IconLayoutDashboard />
            </div>
            <div className="app-header__titles">
              <h1 className="app-header__title">
                任务耗时看板
                <span className="app-header__title-pipe">|</span>
                <span className="app-header__title-muted">Airflow 运维</span>
              </h1>
              <p className="app-header__sub">对比 DAG/Task 耗时分布与波动，优先收敛高变异、高尾延迟任务。</p>
            </div>
          </div>
          <div className="header-meta">
            <span className="tech-pill">React · FastAPI · Plotly</span>
            <button
              type="button"
              className="theme-toggle"
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
              title={theme === "dark" ? "切换浅色" : "切换深色"}
              aria-label={theme === "dark" ? "切换浅色主题" : "切换深色主题"}
            >
              <ThemeToggleGlyph dark={theme === "dark"} />
            </button>
          </div>
        </div>
      </header>

      {copyToast ? (
        <div className="copy-toast" role="status" aria-live="polite">
          {copyToast}
        </div>
      ) : null}

      <details className="card card--session" open>
        <summary className="card__head">
          <div>
            <h2 className="card__title">数据源会话</h2>
            <p className="card__hint">粘贴浏览器 Network 中的「Copy as cURL」以刷新 Cookie 与抓取范围</p>
          </div>
        </summary>
        <div className="card__body">
          <label className="form-label">cURL</label>
          <textarea
            className="textarea-curl"
            placeholder="从 Airflow 页面请求复制 cURL，粘贴到此处"
            value={curlText}
            onChange={(e) => setCurlText(e.target.value)}
          />
          <label className="form-label">DAG 白名单（逗号分隔）</label>
          <input
            type="text"
            className="input-text"
            value={dagAllowInput}
            onChange={(e) => setDagAllowInput(e.target.value)}
            placeholder="例如 D_PARTNER_DAILY_NEW, D_PARTNER_WEEKLY"
          />
          <div className="row-actions">
            <button type="button" className="btn-primary" disabled={pipelineRunning} onClick={() => void onRunPipeline()}>
              {pipelineRunning ? "正在拉取 ETL…" : "运行管线并刷新"}
            </button>
          </div>
          {pipelineErr ? <div className="msg-error">{pipelineErr}</div> : null}
          {pipelineLog ? <pre className="pipeline-log">{pipelineLog}</pre> : null}
        </div>
      </details>

      {loadError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          无法读取事实表：{loadError}
        </div>
      ) : null}

      {!filtered.length && rawRows.length ? (
        <div className="empty-banner">当前筛选条件下没有数据，请放宽时间范围或 DAG / 状态条件。</div>
      ) : null}

      {!rawRows.length && !loading ? (
        <div className="empty-banner">尚未加载到任务实例数据。请在上方运行采集管线，或确认后端已写入 SQLite。</div>
      ) : null}

      {rawRows.length > 0 ? (
        <>
          <div className="layout-toolbar">
            <button type="button" className="btn-ghost layout-toolbar__btn" onClick={() => setMobileFiltersOpen(true)}>
              <IconSliders />
              筛选条件
            </button>
          </div>
          {mobileFiltersOpen ? (
            <button
              type="button"
              className="sidebar-backdrop"
              aria-label="关闭筛选"
              onClick={() => setMobileFiltersOpen(false)}
            />
          ) : null}
          <div className="layout">
            <aside className={`sidebar${mobileFiltersOpen ? " sidebar--open" : ""}`}>
            <h3 className="sidebar__title">筛选</h3>
            <p className="card__hint" style={{ margin: "0 0 0.5rem" }}>
              先缩小范围，再查看图表与导出明细。
            </p>
            <label className="form-label form-label--inline">
              <IconCalendar />
              开始日期
            </label>
            <input
              type="date"
              value={startDay}
              min={datePickerBounds.min}
              max={datePickerBounds.max}
              onChange={(e) => setStartDay(e.target.value)}
            />
            <label className="form-label form-label--inline">
              <IconCalendar />
              结束日期
            </label>
            <input
              type="date"
              value={endDay}
              min={datePickerBounds.min}
              max={datePickerBounds.max}
              onChange={(e) => setEndDay(e.target.value)}
            />
            <p className="card__hint" style={{ margin: "0.35rem 0 0", fontSize: "0.72rem" }}>
              数据当前覆盖至 <strong>{dayBounds.max || "—"}</strong>；日历可选至「今日」以便对齐采集区间（区间内若无跑批则图表为空）。
            </p>
            <div className="sidebar__divider" />
            <label className="form-label form-label--inline">
              <IconLayers />
              DAG（多选）
            </label>
            <select
              multiple
              size={Math.min(8, Math.max(4, dagOptions.length))}
              value={dagMulti}
              onChange={(e) => setDagMulti([...e.target.selectedOptions].map((o) => o.value))}
            >
              {dagOptions.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <label className="form-label form-label--inline">
              <IconActivity />
              状态
            </label>
            <select
              multiple
              size={Math.min(6, Math.max(3, stateOptions.length))}
              value={stateMulti}
              onChange={(e) => setStateMulti([...e.target.selectedOptions].map((o) => o.value))}
            >
              {stateOptions.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <label className="form-label form-label--inline">
              <IconGrid />
              业务域
            </label>
            <select
              multiple
              size={Math.min(6, Math.max(3, domainOptions.length))}
              value={domainMulti}
              onChange={(e) => setDomainMulti([...e.target.selectedOptions].map((o) => o.value))}
            >
              {domainOptions.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <div className="sidebar__divider" />
            <label className="form-label form-label--inline">
              <IconSearch />
              Task 关键词
            </label>
            <input type="text" value={taskKeyword} onChange={(e) => setTaskKeyword(e.target.value)} placeholder="如 extract、load" />
            <div className="range-row">
              <div className="range-row__top">
                <span className="range-label range-label--icon">
                  <IconSliders />
                  Top N
                </span>
                <span className="range-value">{topN}</span>
              </div>
              <input type="range" min={5} max={50} step={5} value={topN} onChange={(e) => setTopN(Number(e.target.value))} />
            </div>
            <button type="button" className="btn-ghost" style={{ marginTop: "0.85rem", width: "100%" }} onClick={() => window.location.reload()}>
              重置页面
            </button>
            <button
              type="button"
              className="btn-primary sidebar__close-mobile"
              onClick={() => setMobileFiltersOpen(false)}
            >
              应用并关闭
            </button>
          </aside>

          <main className="main-panel">
            <div className="filter-summary">
              <span>
                区间 <strong>{startDay}</strong> — <strong>{endDay}</strong>
              </span>
              <span>
                任务实例 <strong>{filtered.length.toLocaleString()}</strong> 条
              </span>
            </div>
            <div className="tab-rail" role="tablist" aria-label="看板分区">
              {(
                [
                  ["overview", "总览", <IconLayoutDashboard key="i" />] as const,
                  ["task", "单任务对比", <IconActivity key="i" />] as const,
                  ["anomaly", "异常候选", <IconAlertTriangle key="i" />] as const,
                  ["detail", "明细与导出", <IconTable key="i" />] as const,
                ] as const
              ).map(([k, label, icon]) => (
                <button
                  key={k}
                  type="button"
                  role="tab"
                  aria-selected={tab === k}
                  className={tab === k ? "tab-rail__active" : ""}
                  onClick={() => setTab(k)}
                >
                  {icon}
                  {label}
                </button>
              ))}
            </div>

            {tab === "overview" && filtered.length ? (
              <section className="content-section">
                <span className="section-chip">Overview</span>
                <div className="panel-title">核心指标与优化优先级</div>
                <div className="stat-grid">
                  <StatCard
                    label="任务实例"
                    value={filtered.length.toLocaleString()}
                    smallIcon={<IconActivity />}
                    watermarkIcon={<IconActivity />}
                  />
                  <StatCard
                    label="DAG 覆盖"
                    value={uniqSorted(filtered.map((r) => r.dag_id).filter(Boolean) as string[]).length}
                    smallIcon={<IconLayers />}
                    watermarkIcon={<IconLayers />}
                  />
                  <StatCard
                    label="平均耗时（分）"
                    value={(filtered.reduce((s, r) => s + r.duration_min, 0) / filtered.length).toFixed(2)}
                    smallIcon={<IconClock />}
                    watermarkIcon={<IconClock />}
                  />
                  <StatCard
                    label="95% 分位（分）"
                    value={quantileNs(filtered.map((r) => r.duration_min), 0.95).toFixed(2)}
                    smallIcon={<IconChartBar />}
                    watermarkIcon={<IconChartBar />}
                  />
                </div>
                <h3 className="subsection-title">波动最大的 Task</h3>
                <div className="range-row">
                  <div className="range-row__top">
                    <span className="range-label">统计窗口（天）</span>
                    <span className="range-value">{volLookback}</span>
                  </div>
                  <input type="range" min={3} max={30} value={volLookback} onChange={(e) => setVolLookback(Number(e.target.value))} />
                </div>
                <div className="range-row">
                  <div className="range-row__top">
                    <span className="range-label">最少有效天数</span>
                    <span className="range-value">{volMinSamples}</span>
                  </div>
                  <input
                    type="range"
                    min={2}
                    max={10}
                    value={volMinSamples}
                    onChange={(e) => setVolMinSamples(Number(e.target.value))}
                  />
                </div>
                {volatilityRows.length ? (
                  <>
                    <div className="stat-grid stat-grid--3" style={{ marginTop: "0.85rem" }}>
                      <StatCard
                        label="高风险"
                        value={volatilityRows.filter((r) => r.risk_level === "高风险").length}
                        smallIcon={<IconAlertTriangle />}
                        watermarkIcon={<IconAlertTriangle />}
                      />
                      <StatCard
                        label="中风险"
                        value={volatilityRows.filter((r) => r.risk_level === "中风险").length}
                        smallIcon={<IconActivity />}
                        watermarkIcon={<IconActivity />}
                      />
                      <StatCard
                        label="低风险"
                        value={volatilityRows.filter((r) => r.risk_level === "低风险").length}
                        smallIcon={<IconGrid />}
                        watermarkIcon={<IconGrid />}
                      />
                    </div>
                    <div className="table-wrap" style={{ maxHeight: 280 }}>
                      <table>
                        <thead>
                          <tr>
                            <th>风险</th>
                            <th>DAG</th>
                            <th>Task</th>
                            <th>天数</th>
                            <th>日均</th>
                            <th>标准差</th>
                            <th>变异系数</th>
                            <th>极差</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[...volatilityRows]
                            .sort((a, b) => b.cv - a.cv)
                            .map((r) => (
                              <tr key={`${r.dag_id}-${r.task_id}`}>
                                <td>
                                  <RiskPill level={r.risk_level} />
                                </td>
                                <td>{r.dag_id}</td>
                                <td>{r.task_id}</td>
                                <td>{r.valid_days}</td>
                                <td>{r.avg_min.toFixed(2)}</td>
                                <td>{r.std_min.toFixed(2)}</td>
                                <td>{r.cv.toFixed(3)}</td>
                                <td>{r.range_min.toFixed(2)}</td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                    {volChartFixed ? (
                      <div className="chart-shell">
                        <div className="chart-shell__meta">
                          <h3 className="chart-shell__title">波动最大的 Task（按变异系数）</h3>
                          <p className="chart-shell__lede">
                            纵轴 <strong>第 1 名在最上方</strong>，表示变异系数最大、波动最严重；悬停可看完整 DAG/Task。下方文本框可复制全名。
                          </p>
                          <ul className="chart-shell__legend" aria-label="风险颜色说明">
                            <li>
                              <span className="chart-shell__swatch chart-shell__swatch--high" /> 高风险
                            </li>
                            <li>
                              <span className="chart-shell__swatch chart-shell__swatch--mid" /> 中风险
                            </li>
                            <li>
                              <span className="chart-shell__swatch chart-shell__swatch--low" /> 低风险
                            </li>
                          </ul>
                          <details className="chart-shell__more">
                            <summary>计算说明（展开）</summary>
                            <p className="chart-shell__desc chart-shell__desc--tight">
                              窗口 <strong>{volLookback}</strong> 天、有效日 ≥ <strong>{volMinSamples}</strong> 时，对每个 DAG+Task
                              的「按日平均耗时」求标准差与均值，<strong>变异系数 = 标准差 ÷ 均值</strong>（无单位，反映日间起伏）。颜色为风险档，可与上表对照。
                            </p>
                          </details>
                        </div>
                        <div className="chart-shell__plot">
                          <Plot
                            data={volChartFixed.data}
                            layout={volChartFixed.layout}
                            style={{
                              width: "100%",
                              height: typeof volChartFixed.layout.height === "number" ? volChartFixed.layout.height : 420,
                            }}
                            useResizeHandler={false}
                            config={{ responsive: true, displaylogo: false }}
                          />
                        </div>
                        <div className="chart-shell__copyblock">
                          <div className="chart-shell__copyhead">
                            <span className="chart-shell__copylabel">完整名称（制表符分隔，可粘贴到 Excel）</span>
                            <button
                              type="button"
                              className="btn-ghost btn-ghost--sm chart-shell__copybtn"
                              onClick={() => void copyPlain(volPlainText, "已复制波动榜单（含表头）")}
                            >
                              复制全部
                            </button>
                          </div>
                          <textarea
                            className="chart-shell__copyarea"
                            readOnly
                            rows={Math.min(14, Math.max(4, volatilityRows.length))}
                            value={volPlainText}
                            aria-label="波动榜单全文，可选中复制"
                          />
                        </div>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <p className="section-note" style={{ marginTop: "0.75rem" }}>
                    可尝试降低「最少有效天数」以纳入更多 Task。
                  </p>
                )}
                <div className="chart-shell">
                  <div className="chart-shell__meta">
                    <h3 className="chart-shell__title">平均单次耗时最高的 Task（Top {barData.length}）</h3>
                    <p className="chart-shell__lede">
                      <strong>第 1 名在最上方</strong>（平均耗时最长）；颜色为当前 Top N <strong>内部</strong>分档。完整 DAG/Task 见下方文本框。
                    </p>
                    <ul className="chart-shell__legend" aria-label="耗时分档颜色">
                      <li>
                        <span className="chart-shell__swatch chart-shell__swatch--high" /> 高耗时档
                      </li>
                      <li>
                        <span className="chart-shell__swatch chart-shell__swatch--mid" /> 中耗时档
                      </li>
                      <li>
                        <span className="chart-shell__swatch chart-shell__swatch--low" /> 低耗时档
                      </li>
                    </ul>
                    <details className="chart-shell__more">
                      <summary>计算说明（展开）</summary>
                      <p className="chart-shell__desc chart-shell__desc--tight">
                        当前筛选下按 DAG+Task 聚合，对每次实例耗时取<strong>算术平均</strong>（分钟），取最高的 <strong>{topN}</strong>{" "}
                        条。分档按这 {barData.length} 条内部的中位与 80% 分位划分，仅作视觉分层。
                      </p>
                    </details>
                  </div>
                  <div className="chart-shell__plot">
                    <Plot
                      data={barChart.data}
                      layout={barChart.layout}
                      style={{
                        width: "100%",
                        height: typeof barChart.layout.height === "number" ? barChart.layout.height : 280,
                      }}
                      useResizeHandler={false}
                      config={{ responsive: true, displaylogo: false }}
                    />
                  </div>
                  <div className="chart-shell__copyblock">
                    <div className="chart-shell__copyhead">
                      <span className="chart-shell__copylabel">完整名称（制表符分隔）</span>
                      <button
                        type="button"
                        className="btn-ghost btn-ghost--sm chart-shell__copybtn"
                        onClick={() => void copyPlain(barPlainText, "已复制耗时榜单（含表头）")}
                      >
                        复制全部
                      </button>
                    </div>
                    <textarea
                      className="chart-shell__copyarea"
                      readOnly
                      rows={Math.min(14, Math.max(4, barData.length))}
                      value={barPlainText}
                      aria-label="平均耗时榜单全文，可选中复制"
                    />
                  </div>
                </div>
                <div className="chart-shell">
                  <div className="chart-shell__meta">
                    <h3 className="chart-shell__title">每日整体平均耗时趋势</h3>
                    <p className="chart-shell__lede">按运行日对<strong>当日全部实例</strong>求平均（分钟），看整体是否逐日变慢。</p>
                    <details className="chart-shell__more">
                      <summary>口径说明（展开）</summary>
                      <p className="chart-shell__desc chart-shell__desc--tight">
                        非单个 DAG；若当天样本少，均值波动会变大，需结合筛选区间理解。
                      </p>
                    </details>
                  </div>
                  <div className="chart-shell__plot">
                    <Plot
                      data={lineChart.data}
                      layout={lineChart.layout}
                      style={{ width: "100%", minHeight: 360 }}
                      useResizeHandler
                      config={{ responsive: true, displaylogo: false }}
                    />
                  </div>
                </div>
              </section>
            ) : null}

            {tab === "task" && filtered.length ? (
              <section className="content-section">
                <h3 className="subsection-title">单日对比历史基线</h3>
                <label className="form-label">Task</label>
                <select
                  value={selectedTask}
                  onChange={(e) => setSelectedTask(e.target.value)}
                  style={{ marginBottom: "0.75rem" }}
                >
                  {taskOptions.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <div className="range-row">
                  <div className="range-row__top">
                    <span className="range-label">对比回溯天数</span>
                    <span className="range-value">{lookbackDays}</span>
                  </div>
                  <input type="range" min={3} max={30} value={lookbackDays} onChange={(e) => setLookbackDays(Number(e.target.value))} />
                </div>
                <div className="radio-group">
                  <span style={{ fontWeight: 700, fontSize: "0.72rem", color: "var(--ink-muted)", width: "100%" }}>指标</span>
                  {(["mean", "p95", "max"] as const).map((m) => (
                    <label key={m}>
                      <input type="radio" name="mm" checked={metricMode === m} onChange={() => setMetricMode(m)} />
                      {m === "mean" ? "均值" : m === "p95" ? "95% 分位" : "最大"}
                    </label>
                  ))}
                </div>
                <div className="range-row">
                  <div className="range-row__top">
                    <span className="range-label">变慢告警倍率</span>
                    <span className="range-value">{alertRatio.toFixed(2)}×</span>
                  </div>
                  <input
                    type="range"
                    min={1.05}
                    max={2}
                    step={0.05}
                    value={alertRatio}
                    onChange={(e) => setAlertRatio(Number(e.target.value))}
                  />
                </div>
                {taskCompare && taskCompare.today && taskCompare.baseline > 0 ? (
                  <div className="stat-grid stat-grid--3">
                    <StatCard
                      label={`当日 ${taskCompare.metricLabel}`}
                      value={taskCompare.today.primary.toFixed(2)}
                      smallIcon={<IconClock />}
                      watermarkIcon={<IconClock />}
                    />
                    <StatCard
                      label="基线"
                      value={taskCompare.baseline.toFixed(2)}
                      smallIcon={<IconChartBar />}
                      watermarkIcon={<IconChartBar />}
                    />
                    <StatCard
                      label="Δ / 幅度"
                      value={
                        <>
                          {(taskCompare.today.primary - taskCompare.baseline).toFixed(2)}（
                          {taskCompare.baseline > 0
                            ? `${(((taskCompare.today.primary - taskCompare.baseline) / taskCompare.baseline) * 100).toFixed(1)}%`
                            : "0%"}
                          ）
                        </>
                      }
                      smallIcon={<IconActivity />}
                      watermarkIcon={<IconActivity />}
                    />
                  </div>
                ) : (
                  <p className="section-note">当前条件下缺少足够日历粒度数据。</p>
                )}
                {taskStatusMsg}
                {compareChart ? (
                  <div className="chart-shell">
                    <Plot
                      data={compareChart.data}
                      layout={compareChart.layout}
                      style={{ width: "100%", height: 440 }}
                      useResizeHandler
                      config={{ responsive: true, displaylogo: false }}
                    />
                  </div>
                ) : null}
                {taskCompare && taskCompare.daily.length ? (
                  <div className="table-wrap" style={{ maxHeight: 220 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>日期</th>
                          <th>{taskCompare.metricLabel}（分钟）</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...taskCompare.daily]
                          .sort((a, b) => b.run_day.localeCompare(a.run_day))
                          .map((d) => (
                            <tr key={d.run_day}>
                              <td>{d.run_day}</td>
                              <td>{d.primary.toFixed(2)}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </section>
            ) : null}

            {tab === "anomaly" && filtered.length ? (
              <section className="content-section">
                <h3 className="subsection-title">超过全局 95% 分位的异常候选</h3>
                <div className="stat-grid stat-grid--2">
                  <StatCard
                    label="95% 分位（分）"
                    value={p95Threshold.toFixed(2)}
                    smallIcon={<IconChartBar />}
                    watermarkIcon={<IconChartBar />}
                  />
                  <StatCard
                    label="异常样本"
                    value={abnormal.length.toLocaleString()}
                    smallIcon={<IconAlertTriangle />}
                    watermarkIcon={<IconAlertTriangle />}
                  />
                </div>
                <div className="table-wrap table-wrap--viewport">
                  <table>
                    <thead>
                      <tr>
                        <th>等级</th>
                        <th>DAG</th>
                        <th>Task</th>
                        <th>状态</th>
                        <th>执行时间</th>
                        <th>耗时(分)</th>
                        <th>负责人</th>
                        <th>域</th>
                        <th>关键级</th>
                      </tr>
                    </thead>
                    <tbody>
                      {abnormal.map((r, i) => (
                        <tr key={`${r.run_id ?? ""}-${i}`}>
                          <td>
                            <AnomalyPill high={r.异常等级高} />
                          </td>
                          <td>{r.dag_id}</td>
                          <td>{r.task_id}</td>
                          <td>{r.state}</td>
                          <td>{formatIsoToBeijing(r.execution_date) || r.execution_date}</td>
                          <td>{r.duration_min.toFixed(2)}</td>
                          <td>{r.owner}</td>
                          <td>{r.domain}</td>
                          <td>{r.criticality}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}

            {tab === "detail" && filtered.length ? (
              <section className="content-section">
                <h3 className="subsection-title">明细</h3>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    const blob = new Blob([rowsToCsv(filteredDisplay)], { type: "text/csv;charset=utf-8" });
                    const a = document.createElement("a");
                    a.href = URL.createObjectURL(blob);
                    a.download = "airflow_filtered_detail.csv";
                    a.click();
                    URL.revokeObjectURL(a.href);
                  }}
                >
                  下载筛选结果 CSV
                </button>
                <div className="table-wrap table-wrap--viewport">
                  <table>
                    <thead>
                      <tr>
                        <th>DAG</th>
                        <th>Task</th>
                        <th>状态</th>
                        <th>执行时间</th>
                        <th>开始</th>
                        <th>结束</th>
                        <th>耗时(分)</th>
                        <th>负责人</th>
                        <th>域</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredDisplay.map((r, i) => (
                        <tr key={`${r.run_id ?? ""}-${i}`}>
                          <td>{r.dag_id}</td>
                          <td>{r.task_id}</td>
                          <td>{r.state}</td>
                          <td>{r.execution_date}</td>
                          <td>{r.start_date}</td>
                          <td>{r.end_date}</td>
                          <td>{r.duration_min.toFixed(2)}</td>
                          <td>{r.owner}</td>
                          <td>{r.domain}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}
          </main>
        </div>
        </>
      ) : null}
    </div>
  );
}
