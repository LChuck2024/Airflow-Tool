import type { FactRow } from "./types";

export function parseDayFromExecutionDate(iso: string | null): string {
  if (!iso || typeof iso !== "string") return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
}

export function normalizeRows(raw: Record<string, unknown>[]): FactRow[] {
  return raw.map((r) => {
    const execution_date = typeof r.execution_date === "string" ? r.execution_date : null;
    const sec = Number(r.duration_sec);
    const duration_min = Number.isFinite(sec) ? sec / 60 : 0;
    return {
      dag_id: r.dag_id != null ? String(r.dag_id) : null,
      task_id: r.task_id != null ? String(r.task_id) : null,
      run_id: r.run_id != null ? String(r.run_id) : null,
      state: r.state != null ? String(r.state) : null,
      execution_date,
      start_date: r.start_date != null ? String(r.start_date) : null,
      end_date: r.end_date != null ? String(r.end_date) : null,
      duration_sec: Number.isFinite(sec) ? sec : null,
      try_number: r.try_number != null ? Number(r.try_number) : null,
      owner: r.owner != null ? String(r.owner) : null,
      domain: r.domain != null ? String(r.domain) : null,
      criticality: r.criticality != null ? String(r.criticality) : null,
      run_date: r.run_date != null ? String(r.run_date) : null,
      duration_min,
      run_day: parseDayFromExecutionDate(execution_date),
    };
  });
}

export function dateInRange(day: string, start: string, end: string): boolean {
  return day >= start && day <= end;
}
