"""Airflow 看板 API：供 React 静态前端与轻量云服务器部署。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard_shared import (  # noqa: E402
    default_db_url,
    default_edges_csv_path,
    default_edges_table,
    default_fact_table,
    extract_base_url_from_curl,
    extract_dag_allowlist_from_curl,
    load_dag_edges,
    load_fact_data,
    project_root,
)
from update_cookie import parse_curl_auth  # noqa: E402

load_dotenv(ROOT / ".env")


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(title="Airflow Task Duration API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PipelineRunBody(BaseModel):
    curl_text: str = Field(default="", description="浏览器 Network Copy as cURL")
    dag_allowlist: str = Field(default="", description="逗号分隔的 DAG 列表")


class PipelineRunResponse(BaseModel):
    ok: bool
    returncode: int
    stdout: str
    message: str = ""


@app.get("/api/health")
def health():
    return {"status": "ok", "root": str(ROOT)}


@app.get("/api/fact")
def get_fact():
    db_url = default_db_url()
    fact_table = default_fact_table()
    try:
        df = load_fact_data(db_url=db_url, fact_table=fact_table)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if df.empty:
        return {"rows": [], "columns": [], "count": 0}

    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return {"rows": records, "columns": list(df.columns), "count": len(records)}


@app.get("/api/dag-edges")
def get_dag_edges():
    db_url = default_db_url()
    edges_table = default_edges_table()
    edges_csv = str(project_root() / default_edges_csv_path())
    try:
        df = load_dag_edges(db_url=db_url, edges_table=edges_table, edges_csv_path=edges_csv)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if df.empty:
        return {"edges": [], "count": 0}

    for col in ["dag_id", "task_id", "upstream_task_id"]:
        if col not in df.columns:
            df[col] = None
    records = json.loads(df[["dag_id", "task_id", "upstream_task_id"]].to_json(orient="records"))
    return {"edges": records, "count": len(records)}


@app.post("/api/pipeline/run", response_model=PipelineRunResponse)
def run_pipeline(body: PipelineRunBody):
    curl_text = (body.curl_text or "").strip()
    dag_allowlist_value = (body.dag_allowlist or "").strip()
    runtime_base_url = ""

    runtime_cookie = ""
    runtime_csrf = ""
    base_url_source = ""
    dag_allowlist_source = "手动输入"

    if curl_text:
        auth = parse_curl_auth(curl_text)
        if not auth.get("cookie"):
            raise HTTPException(status_code=400, detail="cURL 中未解析到 Cookie")
        runtime_cookie = auth["cookie"]
        runtime_csrf = auth.get("csrf", "") or ""
        parsed_base = extract_base_url_from_curl(curl_text)
        if parsed_base:
            runtime_base_url = parsed_base
            base_url_source = "cURL 自动解析"
        parsed_dags = extract_dag_allowlist_from_curl(curl_text)
        if parsed_dags and not dag_allowlist_value:
            dag_allowlist_value = parsed_dags
            dag_allowlist_source = "cURL 自动解析"
    else:
        raise HTTPException(status_code=400, detail="请提供 curl_text（含 Cookie 的 Airflow 请求 cURL）")

    if not runtime_base_url:
        raise HTTPException(status_code=400, detail="未能解析 AIRFLOW_BASE_URL")
    if not dag_allowlist_value:
        raise HTTPException(status_code=400, detail="请提供 dag_allowlist")

    run_env = os.environ.copy()
    run_env["AIRFLOW_BASE_URL"] = runtime_base_url
    run_env["AIRFLOW_COOKIE_HEADER"] = runtime_cookie
    run_env["AIRFLOW_X_CSRFTOKEN"] = runtime_csrf
    run_env["DAG_ALLOWLIST"] = dag_allowlist_value
    dag_count = len([x for x in dag_allowlist_value.split(",") if x.strip()])
    # 尊重 .env / 进程环境变量中的 WEB_MAX；仅在未配置时使用保守默认值（此前会强行覆盖为 15，导致日更 DAG + 长回溯只见少量 Run）
    if not str(run_env.get("WEB_MAX_DAGRUNS_PER_DAG", "") or "").strip():
        run_env["WEB_MAX_DAGRUNS_PER_DAG"] = "5" if dag_count > 20 else "15"

    info_prefix = (
        f"BASE_URL={base_url_source}，DAG_ALLOWLIST={dag_allowlist_source}；"
        f"DAG 数={dag_count}，WEB_MAX_DAGRUNS_PER_DAG={run_env['WEB_MAX_DAGRUNS_PER_DAG']}\n"
    )

    proc = subprocess.run(
        [sys.executable, "run_pipeline.py"],
        cwd=str(project_root()),
        text=True,
        capture_output=True,
        env=run_env,
        timeout=420,
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    ok = proc.returncode == 0
    return PipelineRunResponse(
        ok=ok,
        returncode=proc.returncode,
        stdout=info_prefix + out.strip(),
        message="success" if ok else "ETL 失败",
    )
