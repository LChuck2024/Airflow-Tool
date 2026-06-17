import type { DagEdgesResponse, FactResponse, PipelineResponse } from "./types";

function apiPrefix(): string {
  const raw = import.meta.env.VITE_API_BASE_URL ?? "";
  return raw.replace(/\/$/, "");
}

const API_HINT =
  " 请在项目根目录执行 npm run dev（会同时启动 API 与前端），或另开终端执行 npm run dev:api。";

const HTML_AS_JSON_HINT =
  " 静态页上的 /api 会落到站点的 index.html（HTML），不是 FastAPI。" +
  " 构建前端前设置环境变量 VITE_API_BASE_URL 为后端根地址（勿尾斜杠），再 npm run build；" +
  " 后端需在 CORS_ORIGINS 中加入本站点域名。";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const prefix = apiPrefix();
  const url = `${prefix}${path}`;
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    if (e instanceof TypeError) {
      throw new Error(`无法连接 API（${path}）。${API_HINT}`);
    }
    throw e;
  }
  const text = await res.text();
  if (!res.ok) {
    const base = text || res.statusText || `HTTP ${res.status}`;
    const proxyBroken =
      res.status === 500 && /internal server error/i.test(base) && !prefix;
    if (proxyBroken) {
      throw new Error(`${base} — 多为 Vite 代理目标 127.0.0.1:8000 未监听。${API_HINT}`);
    }
    throw new Error(base);
  }
  const trimmed = text.trimStart();
  if (trimmed.startsWith("<")) {
    throw new Error(
      (prefix
        ? `API 地址 ${prefix} 返回了 HTML，请检查 VITE_API_BASE_URL 是否指向 FastAPI 根地址。`
        : "未设置 VITE_API_BASE_URL：线上会请求当前站点下的 /api，得到的是 HTML 页面。") +
        HTML_AS_JSON_HINT,
    );
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`响应不是合法 JSON（前 120 字符）：${text.slice(0, 120)}`);
  }
}

export function fetchFact(): Promise<FactResponse> {
  return fetchJson<FactResponse>("/api/fact");
}

export function fetchDagEdges(): Promise<DagEdgesResponse> {
  return fetchJson<DagEdgesResponse>("/api/dag-edges");
}

export function runPipeline(body: { curl_text: string; dag_allowlist: string }): Promise<PipelineResponse> {
  return fetchJson<PipelineResponse>("/api/pipeline/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
