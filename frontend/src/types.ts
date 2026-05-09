export interface FactRow {
  dag_id: string | null;
  task_id: string | null;
  run_id?: string | null;
  state: string | null;
  execution_date: string | null;
  start_date?: string | null;
  end_date?: string | null;
  duration_sec: number | null;
  try_number?: number | null;
  owner?: string | null;
  domain?: string | null;
  criticality?: string | null;
  run_date?: string | null;
  duration_min: number;
  run_day: string;
}

export interface FactResponse {
  rows: Record<string, unknown>[];
  columns: string[];
  count: number;
}

export interface PipelineResponse {
  ok: boolean;
  returncode: number;
  stdout: string;
  message: string;
}
