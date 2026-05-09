import type { FactResponse, PipelineResponse } from "./types";

function apiPrefix(): string {
  const raw = import.meta.env.VITE_API_BASE_URL ?? "";
  return raw.replace(/\/$/, "");
}

const API_HINT =
  " 请在项目根目录执行 npm run dev（会同时启动 API 与前端），或另开终端执行 npm run dev:api。";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${apiPrefix()}${path}`;
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    if (e instanceof TypeError) {
      throw new Error(`无法连接 API（${path}）。${API_HINT}`);
    }
    throw e;
  }
  if (!res.ok) {
    const text = await res.text();
    const base = text || res.statusText || `HTTP ${res.status}`;
    const proxyBroken =
      res.status === 500 && /internal server error/i.test(base) && !apiPrefix();
    if (proxyBroken) {
      throw new Error(`${base} — 多为 Vite 代理目标 127.0.0.1:8000 未监听。${API_HINT}`);
    }
    throw new Error(base);
  }
  return res.json() as Promise<T>;
}

export function fetchFact(): Promise<FactResponse> {
  return fetchJson<FactResponse>("/api/fact");
}

export function runPipeline(body: { curl_text: string; dag_allowlist: string }): Promise<PipelineResponse> {
  return fetchJson<PipelineResponse>("/api/pipeline/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
