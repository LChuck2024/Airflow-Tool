import type { FactRow } from "./types";

export interface DagEdge {
  dag_id: string;
  task_id: string;
  upstream_task_id: string;
}

export interface TaskTiming {
  task_id: string;
  start_ms: number;
  end_ms: number;
}

/** 由 Airflow 依赖或当日运行起止时间推断：task_id → 直接上游列表 */
export function buildUpstreamMap(
  dagId: string,
  edges: DagEdge[],
  focusDayRows: FactRow[],
): { map: Map<string, string[]>; source: "airflow" | "timing" | "mixed" } {
  const map = new Map<string, string[]>();
  const dagEdges = edges.filter((e) => e.dag_id === dagId);
  for (const e of dagEdges) {
    if (!map.has(e.task_id)) map.set(e.task_id, []);
    const ups = map.get(e.task_id)!;
    if (!ups.includes(e.upstream_task_id)) ups.push(e.upstream_task_id);
  }
  const timingMap = inferUpstreamFromTiming(focusDayRows.filter((r) => r.dag_id === dagId));
  if (!map.size) {
    return { map: timingMap, source: "timing" };
  }
  for (const [taskId, ups] of timingMap) {
    if (!map.has(taskId)) map.set(taskId, ups);
  }
  return { map, source: dagEdges.length ? "mixed" : "timing" };
}

/** 参考日运行顺序：结束时间不晚于本 Task 开始、且最晚结束的 Task 视为直接上游 */
export function inferUpstreamFromTiming(rows: FactRow[]): Map<string, string[]> {
  const byTask = new Map<string, TaskTiming>();
  for (const r of rows) {
    if (!r.task_id) continue;
    const s = parseIsoMs(r.start_date);
    const e = parseIsoMs(r.end_date);
    if (s == null || e == null) continue;
    const prev = byTask.get(r.task_id);
    if (!prev) {
      byTask.set(r.task_id, { task_id: r.task_id, start_ms: s, end_ms: e });
    } else {
      prev.start_ms = Math.min(prev.start_ms, s);
      prev.end_ms = Math.max(prev.end_ms, e);
    }
  }
  const timings = [...byTask.values()];
  const upstream = new Map<string, string[]>();
  for (const t of timings) {
    const preds = timings.filter(
      (u) => u.task_id !== t.task_id && u.end_ms <= t.start_ms + 60_000,
    );
    if (!preds.length) {
      upstream.set(t.task_id, []);
      continue;
    }
    const maxEnd = Math.max(...preds.map((p) => p.end_ms));
    upstream.set(
      t.task_id,
      preds.filter((p) => p.end_ms >= maxEnd - 1000).map((p) => p.task_id),
    );
  }
  return upstream;
}

function parseIsoMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

/** 沿上游追溯：若上游耗时增幅更大，则继续向上，直到找到「源头」Task */
export function traceSlowdownRoot(
  taskId: string,
  deltaMinMap: Map<string, number>,
  upstreamMap: Map<string, string[]>,
  threshold = 0.5,
  visited = new Set<string>(),
): string {
  if (visited.has(taskId)) return taskId;
  visited.add(taskId);
  const delta = deltaMinMap.get(taskId) ?? 0;
  const ups = upstreamMap.get(taskId) ?? [];
  if (!ups.length || delta <= threshold) return taskId;

  let bestUp: string | null = null;
  let bestDelta = 0;
  for (const u of ups) {
    const du = deltaMinMap.get(u) ?? 0;
    if (du > bestDelta) {
      bestDelta = du;
      bestUp = u;
    }
  }
  if (bestUp && bestDelta >= Math.max(threshold, delta * 0.4)) {
    return traceSlowdownRoot(bestUp, deltaMinMap, upstreamMap, threshold, visited);
  }
  return taskId;
}

export function buildUpstreamPath(
  taskId: string,
  rootId: string,
  upstreamMap: Map<string, string[]>,
): string {
  if (taskId === rootId) return rootId;
  const chain: string[] = [taskId];
  let cur = taskId;
  for (let i = 0; i < 24 && cur !== rootId; i++) {
    const ups = upstreamMap.get(cur) ?? [];
    if (!ups.length) break;
    const next =
      ups.find((u) => u === rootId) ??
      ups.find((u) => upstreamReachable(u, rootId, upstreamMap)) ??
      ups[0];
    chain.unshift(next);
    cur = next;
  }
  return chain.join(" → ");
}

function upstreamReachable(from: string, target: string, upstreamMap: Map<string, string[]>): boolean {
  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const n = stack.pop()!;
    if (n === target) return true;
    if (seen.has(n)) continue;
    seen.add(n);
    for (const u of upstreamMap.get(n) ?? []) stack.push(u);
  }
  return false;
}

export interface SlowdownAttribution {
  root_task_id: string;
  root_dag_task: string;
  is_root: boolean;
  root_reason: "自身变慢" | "上游传导";
  upstream_path: string;
  dep_source: "airflow" | "timing" | "mixed";
}

export function attributeSlowdownRoots<T extends { dag_id: string; task_id: string; dag_task: string; delta_min: number }>(
  rows: T[],
  edges: DagEdge[],
  focusDayRows: FactRow[],
): (T & SlowdownAttribution)[] {
  const byDag = new Map<string, T[]>();
  for (const r of rows) {
    if (!byDag.has(r.dag_id)) byDag.set(r.dag_id, []);
    byDag.get(r.dag_id)!.push(r);
  }

  const out: (T & SlowdownAttribution)[] = [];
  for (const [dagId, dagRows] of byDag) {
    const { map: upstreamMap, source: dep_source } = buildUpstreamMap(dagId, edges, focusDayRows);
    const deltaMap = new Map<string, number>();
    for (const r of dagRows) deltaMap.set(r.task_id, r.delta_min);

    for (const r of dagRows) {
      const rootId = traceSlowdownRoot(r.task_id, deltaMap, upstreamMap);
      const is_root = rootId === r.task_id;
      out.push({
        ...r,
        root_task_id: rootId,
        root_dag_task: `${dagId} / ${rootId}`,
        is_root,
        root_reason: is_root ? "自身变慢" : "上游传导",
        upstream_path: buildUpstreamPath(r.task_id, rootId, upstreamMap),
        dep_source,
      });
    }
  }
  return out.sort((a, b) => b.delta_min - a.delta_min || a.dag_id.localeCompare(b.dag_id));
}

export interface SlowdownRootSummary {
  dag_id: string;
  root_task_id: string;
  root_dag_task: string;
  root_delta_min: number;
  affected_count: number;
  affected_tasks: string[];
  dep_source: "airflow" | "timing" | "mixed";
}

export function summarizeSlowdownRoots(
  attributed: (SlowdownAttribution & { dag_id: string; task_id: string; delta_min: number })[],
): SlowdownRootSummary[] {
  const rootDelta = new Map<string, number>();
  for (const r of attributed) {
    if (r.task_id === r.root_task_id) {
      rootDelta.set(`${r.dag_id}\t${r.root_task_id}`, r.delta_min);
    }
  }

  const groups = new Map<string, SlowdownRootSummary & { taskSet: Set<string> }>();
  for (const r of attributed) {
    if (r.delta_min <= 0.5 && r.task_id !== r.root_task_id) continue;
    const key = `${r.dag_id}\t${r.root_task_id}`;
    const rd = rootDelta.get(key) ?? (r.task_id === r.root_task_id ? r.delta_min : 0);
    if (rd <= 0.5) continue;

    if (!groups.has(key)) {
      groups.set(key, {
        dag_id: r.dag_id,
        root_task_id: r.root_task_id,
        root_dag_task: r.root_dag_task,
        root_delta_min: rd,
        affected_count: 0,
        affected_tasks: [],
        dep_source: r.dep_source,
        taskSet: new Set<string>(),
      });
    }
    const g = groups.get(key)!;
    g.root_delta_min = rd;
    if (r.task_id !== r.root_task_id && !g.taskSet.has(r.task_id)) {
      g.taskSet.add(r.task_id);
      g.affected_tasks.push(r.task_id);
      g.affected_count = g.taskSet.size;
    }
  }
  return [...groups.values()]
    .map(({ taskSet: _t, ...rest }) => rest)
    .sort((a, b) => b.root_delta_min - a.root_delta_min || b.affected_count - a.affected_count);
}
