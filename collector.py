import os
import ssl
import json
import re
import subprocess
from io import StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote, urlparse

import pandas as pd
import requests
import urllib3
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from sqlalchemy import create_engine


def _log(message: str) -> None:
    print(f"[collector] {message}")


def _decode_subprocess_output(raw: bytes) -> str:
    """
    Decode curl output in a cross-platform safe way.
    Windows often defaults to gbk for text=True, while page content is utf-8.
    """
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _run_curl_and_get_text(command: List[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True)
    return _decode_subprocess_output(result.stdout)


def _build_auth_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    cookie_header = os.getenv("AIRFLOW_COOKIE_HEADER", "").strip()
    if cookie_header:
        headers["Cookie"] = cookie_header
    csrf_token = os.getenv("AIRFLOW_X_CSRFTOKEN", "").strip()
    if csrf_token:
        headers["x-csrftoken"] = csrf_token
    origin = os.getenv("AIRFLOW_ORIGIN", "").strip()
    if origin:
        headers["origin"] = origin
    referer = os.getenv("AIRFLOW_REFERER", "").strip()
    if referer:
        headers["referer"] = referer
    return headers


def _to_bool(value: str, default: bool = True) -> bool:
    text = (value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _resolve_verify_setting():
    ca_bundle = os.getenv("AIRFLOW_CA_BUNDLE", "").strip()
    if ca_bundle:
        return ca_bundle
    verify_ssl = _to_bool(os.getenv("AIRFLOW_VERIFY_SSL", "true"), default=True)
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return verify_ssl


def _to_json_with_curl(
    url: str,
    method: str,
    payload: Dict[str, object] | None,
    query: Dict[str, object] | None,
    headers: Dict[str, str],
    auth,
    verify_setting,
) -> Dict[str, object]:
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--request",
        method.upper(),
        url,
        "--header",
        "Content-Type: application/json",
        "--max-time",
        "60",
    ]
    if payload is not None:
        command.extend(["--data", json.dumps(payload)])
    if query:
        for key, value in query.items():
            command.extend(["--get", "--data-urlencode", f"{key}={value}"])
    if headers.get("Authorization"):
        command.extend(["--header", f"Authorization: {headers['Authorization']}"])
    if auth and auth[0]:
        command.extend(["--user", f"{auth[0]}:{auth[1]}"])
    if verify_setting is False:
        command.append("--insecure")
    elif isinstance(verify_setting, str) and verify_setting:
        command.extend(["--cacert", verify_setting])

    stdout_text = _run_curl_and_get_text(command)
    return json.loads(stdout_text)


def _form_post_json_with_curl(
    url: str,
    form_fields: List[tuple[str, str]],
    headers: Dict[str, str],
    auth,
    verify_setting,
) -> Dict[str, object]:
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--request",
        "POST",
        url,
        "--header",
        "accept: application/json,*/*",
        "--header",
        "content-type: application/x-www-form-urlencoded;charset=UTF-8",
        "--max-time",
        "60",
    ]
    for key, value in headers.items():
        command.extend(["--header", f"{key}: {value}"])
    if auth and auth[0]:
        command.extend(["--user", f"{auth[0]}:{auth[1]}"])
    for key, value in form_fields:
        command.extend(["--data-urlencode", f"{key}={value}"])
    if verify_setting is False:
        command.append("--insecure")
    elif isinstance(verify_setting, str) and verify_setting:
        command.extend(["--cacert", verify_setting])

    stdout_text = _run_curl_and_get_text(command)
    return json.loads(stdout_text)


def _fetch_task_instances_from_web_list(
    base_url: str,
    headers: Dict[str, str],
    auth,
    verify_setting,
    dag_ids: List[str],
    start_date: datetime,
) -> pd.DataFrame:
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--request",
        "GET",
        f"{base_url}/taskinstance/list/",
        "--max-time",
        "120",
    ]
    for key, value in headers.items():
        command.extend(["--header", f"{key}: {value}"])
    if auth and auth[0]:
        command.extend(["--user", f"{auth[0]}:{auth[1]}"])
    if verify_setting is False:
        command.append("--insecure")
    elif isinstance(verify_setting, str) and verify_setting:
        command.extend(["--cacert", verify_setting])

    html = _run_curl_and_get_text(command)
    tables = pd.read_html(StringIO(html))
    if not tables:
        return pd.DataFrame()

    raw = tables[0].copy()
    rename_map = {
        "Dag Id": "dag_id",
        "Task Id": "task_id",
        "Run Id": "run_id",
        "State": "state",
        "Logical Date": "execution_date",
        "Start Date": "start_date",
        "End Date": "end_date",
        "Try Number": "try_number",
        "Duration": "duration",
    }
    raw = raw.rename(columns=rename_map)
    required = ["dag_id", "task_id", "run_id", "state", "execution_date", "start_date", "end_date", "try_number"]
    for col in required:
        if col not in raw.columns:
            raw[col] = None

    raw["dag_id"] = raw["dag_id"].astype(str).str.strip()
    raw = raw[raw["dag_id"].isin(dag_ids)]
    raw["start_date"] = pd.to_datetime(raw["start_date"], format="mixed", errors="coerce", utc=True)
    raw = raw[raw["start_date"] >= start_date]
    raw["execution_date"] = pd.to_datetime(raw["execution_date"], format="mixed", errors="coerce", utc=True)
    raw["end_date"] = pd.to_datetime(raw["end_date"], format="mixed", errors="coerce", utc=True)

    selected = raw[required + ["duration"]].copy()
    return selected.reset_index(drop=True)


_RUN_ID_ISO_CHUNK = re.compile(
    r"(20\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)",
)


def _pick_logical_date_column(columns: list[str]) -> str | None:
    """
    必须优先锁定「逻辑日期 / Logical Date」，避免「执行日期」等泛词匹配到错误列，
    或小序号列被当成时间后解析出公元元年一类垃圾值。
    """
    pairs = [(c, c.strip().lower()) for c in columns]

    def exact(*needles: str) -> str | None:
        for want in needles:
            w = want.lower()
            for c, cl in pairs:
                if cl == w:
                    return c
        return None

    hit = exact("logical date", "逻辑日期", "logical_date")
    if hit:
        return hit

    for needle in ("logical date", "逻辑日期", "logical"):
        for c, cl in pairs:
            if needle in cl and "duration" not in cl:
                return c

    for needle in ("execution date", "执行日期"):
        for c, cl in pairs:
            if needle in cl:
                return c
    return None


def _sanitize_logical_timestamps(ts: pd.Series) -> pd.Series:
    """剔除明显非法年份（常见于误列 / 序号被 read_html 当成日期）。"""
    out = pd.to_datetime(ts, format="mixed", errors="coerce", utc=True)
    year = out.dt.year
    return out.where(year.between(1990, 2100, inclusive="both"))


def _flatten_html_columns(columns: object) -> list[str]:
    """pd.read_html 可能产出多级 columns；统一成单层可读字符串。"""
    flat: list[str] = []
    for c in list(columns):
        if isinstance(c, tuple):
            parts = [str(x).strip() for x in c if x is not None and str(x).strip().lower() not in {"", "nan"}]
            flat.append(" ".join(parts).strip() or "_".join(str(x) for x in c))
        else:
            flat.append(str(c).strip())
    return flat


def _canonical_dagrun_list_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Airflow UI 语言不同时列表页表头不同（Logical Date / 逻辑日期 等）。
    仅用英文字段 rename 会导致 execution_date 全空 → NaT → 全部被日期过滤。
    """
    out = df.copy()
    out.columns = _flatten_html_columns(out.columns)

    def pick_col(*candidates: str) -> str | None:
        lower_cols = {c.lower(): c for c in out.columns}
        for cand in candidates:
            key = cand.lower()
            if key in lower_cols:
                return lower_cols[key]
        # 列名包含关键词（适配「Logical Date (UTC)」等）
        for col in out.columns:
            cl = col.lower()
            for cand in candidates:
                if cand.lower() in cl:
                    return col
        return None

    renames: Dict[str, str] = {}
    dag_src = pick_col("dag id", "dag_id", "dagid")
    if dag_src:
        renames[dag_src] = "dag_id"
    run_src = pick_col("run id", "run_id", "runid", "运行 id", "运行id")
    if run_src:
        renames[run_src] = "run_id"
    logical_src = _pick_logical_date_column(list(out.columns))
    if logical_src:
        renames[logical_src] = "execution_date"
    start_src = pick_col("start date", "start_date", "开始日期", "开始时间")
    if start_src:
        renames[start_src] = "start_date"
    end_src = pick_col("end date", "end_date", "结束日期", "结束时间")
    if end_src:
        renames[end_src] = "end_date"
    state_src = pick_col("state", "状态")
    if state_src:
        renames[state_src] = "state"

    out = out.rename(columns=renames)
    for col in ["dag_id", "run_id", "execution_date", "start_date", "end_date", "state"]:
        if col not in out.columns:
            out[col] = None
    return out


def _fill_execution_date_from_run_id(runs: pd.DataFrame) -> pd.DataFrame:
    missing_exec = runs["execution_date"].isna()
    if not missing_exec.any():
        return runs
    s = runs.loc[missing_exec, "run_id"].astype(str)
    extracted = s.str.extract(_RUN_ID_ISO_CHUNK, expand=False)
    parsed = pd.to_datetime(extracted, format="mixed", errors="coerce", utc=True)
    runs = runs.copy()
    runs.loc[missing_exec, "execution_date"] = _sanitize_logical_timestamps(parsed)
    return runs


def _fetch_dag_runs_from_web_list(
    base_url: str,
    headers: Dict[str, str],
    auth,
    verify_setting,
    dag_id: str,
    start_date: datetime,
) -> pd.DataFrame:
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--request",
        "GET",
        f"{base_url}/dagrun/list/?_flt_3_dag_id={quote(dag_id, safe='')}",
        "--max-time",
        "120",
    ]
    for key, value in headers.items():
        command.extend(["--header", f"{key}: {value}"])
    if auth and auth[0]:
        command.extend(["--user", f"{auth[0]}:{auth[1]}"])
    if verify_setting is False:
        command.append("--insecure")
    elif isinstance(verify_setting, str) and verify_setting:
        command.extend(["--cacert", verify_setting])

    html = _run_curl_and_get_text(command)
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        _log(f"web mode dag={dag_id}, no table found in dagrun list page")
        return pd.DataFrame()
    if not tables:
        return pd.DataFrame()
    runs = tables[0].copy()
    runs = _canonical_dagrun_list_columns(runs)
    runs["execution_date"] = _sanitize_logical_timestamps(runs["execution_date"])
    runs = _fill_execution_date_from_run_id(runs)
    missing_exec = runs["execution_date"].isna()
    if missing_exec.any():
        parsed_legacy = pd.to_datetime(
            runs.loc[missing_exec, "run_id"].astype(str).str.extract(
                r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[^+]+\+[0-9:]{2,5})",
                expand=False,
            ),
            errors="coerce",
            utc=True,
        )
        runs.loc[missing_exec, "execution_date"] = _sanitize_logical_timestamps(parsed_legacy)
    still_na = runs["execution_date"].isna()
    if still_na.any():
        fb = pd.to_datetime(runs.loc[still_na, "start_date"], format="mixed", errors="coerce", utc=True)
        runs.loc[still_na, "execution_date"] = _sanitize_logical_timestamps(fb)

    runs["execution_date"] = _sanitize_logical_timestamps(runs["execution_date"])

    n_parse = len(runs)
    valid_exec = int(runs["execution_date"].notna().sum())
    cols_preview = list(runs.columns)[:14]
    max_seen = runs["execution_date"].max() if valid_exec else pd.NaT
    runs = runs[runs["execution_date"] >= start_date]
    n_keep = len(runs)
    if n_parse == 0:
        _log(f"web mode dag={dag_id}, dagrun list HTML produced no parseable rows")
    elif n_keep == 0:
        if valid_exec == 0:
            _log(
                f"web mode dag={dag_id}, parsed {n_parse} dagrun row(s) but logical date unparsed "
                f"(locale/HTML columns?). columns≈{cols_preview}"
            )
        else:
            suspicious = bool(pd.notna(max_seen) and int(max_seen.year) < 1990)
            if suspicious:
                _log(
                    f"web mode dag={dag_id}, parsed {n_parse} dagrun row(s) but logical dates look invalid "
                    f"(max_seen={max_seen}); likely wrong HTML column or locale. columns≈{cols_preview}"
                )
            else:
                _log(
                    f"web mode dag={dag_id}, parsed {n_parse} dagrun row(s), "
                    f"max logical date seen={max_seen}, cutoff={start_date.isoformat()} (UTC); "
                    f"all rows older than cutoff — increase COLLECT_DAYS"
                )

    return runs[["dag_id", "run_id", "execution_date", "start_date", "end_date", "state"]].dropna(
        subset=["run_id", "execution_date"]
    )


def _fetch_task_instances_from_graph_page(
    base_url: str,
    headers: Dict[str, str],
    auth,
    verify_setting,
    dag_id: str,
    execution_date: str,
    run_id: str,
) -> List[dict]:
    graph_url = (
        f"{base_url}/graph?dag_id={quote(dag_id, safe='')}"
        f"&execution_date={quote(execution_date, safe='')}"
    )
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--request",
        "GET",
        graph_url,
        "--max-time",
        "120",
    ]
    for key, value in headers.items():
        command.extend(["--header", f"{key}: {value}"])
    if auth and auth[0]:
        command.extend(["--user", f"{auth[0]}:{auth[1]}"])
    if verify_setting is False:
        command.append("--insecure")
    elif isinstance(verify_setting, str) and verify_setting:
        command.extend(["--cacert", verify_setting])

    html = _run_curl_and_get_text(command)
    anchor = "let taskInstances = "
    start_idx = html.find(anchor)
    if start_idx == -1:
        return []
    json_start = html.find("{", start_idx)
    if json_start == -1:
        return []
    depth = 0
    json_end = -1
    for idx in range(json_start, len(html)):
        ch = html[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                json_end = idx + 1
                break
    if json_end == -1:
        return []

    task_instances = json.loads(html[json_start:json_end])
    rows: List[dict] = []
    for task_id, item in task_instances.items():
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "dag_id": item.get("dag_id") or dag_id,
                "task_id": item.get("task_id") or task_id,
                "run_id": run_id,
                "execution_date": execution_date,
                "start_date": item.get("start_date"),
                "end_date": item.get("end_date"),
                "state": item.get("state"),
                "try_number": item.get("try_number"),
                "duration": item.get("duration"),
            }
        )
    return rows


class TLSv12HttpAdapter(HTTPAdapter):
    """Force TLSv1.2 to avoid some ingress TLSv1.3 handshake EOF issues."""

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def _resolve_base_url() -> str:
    base_url = os.getenv("AIRFLOW_BASE_URL", "").strip().rstrip("/")
    if base_url:
        return base_url
    endpoint = os.getenv(
        "AIRFLOW_TASK_INSTANCES_ENDPOINT",
        "http://localhost:8080/api/v1/dags/~/dagRuns/~/taskInstances/list",
    ).strip()
    parts = urlparse(endpoint)
    return f"{parts.scheme}://{parts.netloc}"


def _airflow_request_json(
    session: requests.Session,
    method: str,
    url: str,
    headers: Dict[str, str],
    auth,
    verify_setting,
    use_curl_fallback: bool,
    payload: Dict[str, object] | None = None,
    query: Dict[str, object] | None = None,
) -> Dict[str, object]:
    try:
        response = session.request(
            method=method,
            url=url,
            json=payload,
            params=query,
            headers=headers,
            auth=auth,
            verify=verify_setting,
            timeout=45,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.SSLError:
        if not use_curl_fallback:
            raise
        _log(f"requests ssl failed, fallback to curl: {method.upper()} {url}")
        return _to_json_with_curl(
            url=url,
            method=method,
            payload=payload,
            query=query,
            headers=headers,
            auth=auth,
            verify_setting=verify_setting,
        )


def _ensure_not_api_error(body: Dict[str, object], endpoint_name: str) -> None:
    status = body.get("status")
    title = str(body.get("title", "")).lower()
    if status in {401, 403} or title in {"unauthorized", "forbidden"}:
        raise PermissionError(
            f"{endpoint_name} unauthorized/forbidden: "
            "current credentials cannot access Airflow REST API."
        )


def _load_dag_ids(
    session: requests.Session,
    base_url: str,
    headers: Dict[str, str],
    auth,
    verify_setting,
    use_curl_fallback: bool,
    page_limit: int,
) -> List[str]:
    allowlist = [item.strip() for item in os.getenv("DAG_ALLOWLIST", "").split(",") if item.strip()]
    if allowlist:
        _log(f"use DAG_ALLOWLIST, dag_count={len(allowlist)}")
        return allowlist

    dag_ids: List[str] = []
    offset = 0
    while True:
        query = {"limit": page_limit, "offset": offset}
        body = _airflow_request_json(
            session=session,
            method="GET",
            url=f"{base_url}/api/v1/dags",
            query=query,
            headers=headers,
            auth=auth,
            verify_setting=verify_setting,
            use_curl_fallback=use_curl_fallback,
        )
        _ensure_not_api_error(body, "GET /api/v1/dags")
        dags = body.get("dags", [])
        dag_ids.extend([d.get("dag_id") for d in dags if d.get("dag_id")])
        _log(f"fetched dag page offset={offset}, rows={len(dags)}")
        if len(dags) < page_limit:
            break
        offset += page_limit
    return dag_ids


def _fetch_task_instances_by_dag(
    session: requests.Session,
    base_url: str,
    dag_id: str,
    headers: Dict[str, str],
    auth,
    verify_setting,
    use_curl_fallback: bool,
    start_date: datetime,
    end_date: datetime,
    page_limit: int,
) -> List[dict]:
    all_rows: List[dict] = []
    dag_id_encoded = quote(dag_id, safe="")
    run_offset = 0
    while True:
        run_query = {
            "limit": page_limit,
            "offset": run_offset,
            "start_date_gte": start_date.isoformat(),
            "start_date_lte": end_date.isoformat(),
            "order_by": "-start_date",
        }
        runs_body = _airflow_request_json(
            session=session,
            method="GET",
            url=f"{base_url}/api/v1/dags/{dag_id_encoded}/dagRuns",
            query=run_query,
            headers=headers,
            auth=auth,
            verify_setting=verify_setting,
            use_curl_fallback=use_curl_fallback,
        )
        _ensure_not_api_error(runs_body, f"GET /api/v1/dags/{dag_id}/dagRuns")
        dag_runs = runs_body.get("dag_runs", [])
        _log(f"dag={dag_id}, dag_runs page offset={run_offset}, rows={len(dag_runs)}")
        for dag_run in dag_runs:
            dag_run_id = dag_run.get("dag_run_id")
            if not dag_run_id:
                continue
            run_id_encoded = quote(dag_run_id, safe="")
            ti_offset = 0
            while True:
                ti_query = {"limit": page_limit, "offset": ti_offset}
                ti_body = _airflow_request_json(
                    session=session,
                    method="GET",
                    url=f"{base_url}/api/v1/dags/{dag_id_encoded}/dagRuns/{run_id_encoded}/taskInstances",
                    query=ti_query,
                    headers=headers,
                    auth=auth,
                    verify_setting=verify_setting,
                    use_curl_fallback=use_curl_fallback,
                )
                _ensure_not_api_error(
                    ti_body,
                    f"GET /api/v1/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances",
                )
                rows = ti_body.get("task_instances", [])
                for row in rows:
                    row["dag_run_id"] = dag_run_id
                    row["dag_id"] = row.get("dag_id") or dag_id
                all_rows.extend(rows)
                if len(rows) < page_limit:
                    break
                ti_offset += page_limit
        if len(dag_runs) < page_limit:
            break
        run_offset += page_limit
    return all_rows


def _fetch_dag_task_edges_for_dag(
    session: requests.Session,
    base_url: str,
    dag_id: str,
    headers: Dict[str, str],
    auth,
    verify_setting,
    use_curl_fallback: bool,
    page_limit: int,
) -> List[dict]:
    rows: List[dict] = []
    dag_id_encoded = quote(dag_id, safe="")
    offset = 0
    while True:
        body = _airflow_request_json(
            session=session,
            method="GET",
            url=f"{base_url}/api/v1/dags/{dag_id_encoded}/tasks",
            query={"limit": page_limit, "offset": offset},
            headers=headers,
            auth=auth,
            verify_setting=verify_setting,
            use_curl_fallback=use_curl_fallback,
        )
        _ensure_not_api_error(body, f"GET /api/v1/dags/{dag_id}/tasks")
        tasks = body.get("tasks", [])
        for task in tasks:
            task_id = task.get("task_id")
            if not task_id:
                continue
            upstream_ids = task.get("upstream_task_ids") or []
            if not upstream_ids:
                rows.append({"dag_id": dag_id, "task_id": task_id, "upstream_task_id": ""})
                continue
            for upstream_task_id in upstream_ids:
                if upstream_task_id:
                    rows.append(
                        {
                            "dag_id": dag_id,
                            "task_id": task_id,
                            "upstream_task_id": upstream_task_id,
                        }
                    )
        if len(tasks) < page_limit:
            break
        offset += page_limit
    return rows


def fetch_dag_task_edges(page_limit: int) -> pd.DataFrame:
    base_url = _resolve_base_url()
    verify_setting = _resolve_verify_setting()
    session = requests.Session()
    session.mount("https://", TLSv12HttpAdapter())
    headers = {"Content-Type": "application/json"}
    headers.update(_build_auth_headers())
    auth = None
    use_curl_fallback = _to_bool(os.getenv("AIRFLOW_USE_CURL_FALLBACK", "true"), default=True)

    dag_ids = _load_dag_ids(
        session=session,
        base_url=base_url,
        headers=headers,
        auth=auth,
        verify_setting=verify_setting,
        use_curl_fallback=use_curl_fallback,
        page_limit=page_limit,
    )
    all_rows: List[dict] = []
    for dag_id in dag_ids:
        try:
            rows = _fetch_dag_task_edges_for_dag(
                session=session,
                base_url=base_url,
                dag_id=dag_id,
                headers=headers,
                auth=auth,
                verify_setting=verify_setting,
                use_curl_fallback=use_curl_fallback,
                page_limit=page_limit,
            )
            all_rows.extend(rows)
            _log(f"dag={dag_id}, task edges={len(rows)}")
        except Exception as exc:
            _log(f"dag={dag_id}, skip task edges due to error: {exc}")
            continue
    return pd.DataFrame(all_rows)


def save_dag_edges(df: pd.DataFrame, db_url: str, edges_table: str, edges_csv_path: str) -> None:
    os.makedirs(os.path.dirname(edges_csv_path), exist_ok=True)
    engine = create_engine(db_url)
    if df.empty:
        _log("no dag edges fetched, skip writing edges table")
        return
    df.to_sql(edges_table, engine, if_exists="replace", index=False)
    df.to_csv(edges_csv_path, index=False, encoding="utf-8")
    _log(f"saved edges table={edges_table}, rows={len(df)}")
    _log(f"saved edges csv={edges_csv_path}")


def fetch_task_instances(days: int, page_limit: int) -> pd.DataFrame:
    base_url = _resolve_base_url()
    verify_setting = _resolve_verify_setting()

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    session = requests.Session()
    session.mount("https://", TLSv12HttpAdapter())
    headers = {"Content-Type": "application/json"}
    headers.update(_build_auth_headers())

    # Runtime-only web session auth (Cookie / CSRF) from Streamlit page.
    auth = None
    use_curl_fallback = _to_bool(os.getenv("AIRFLOW_USE_CURL_FALLBACK", "true"), default=True)
    _log(f"base_url={base_url}")
    _log(f"ssl_verify={verify_setting}")
    _log(f"curl_fallback={use_curl_fallback}")

    source_mode = os.getenv("AIRFLOW_SOURCE_MODE", "web").strip().lower()
    if source_mode == "web":
        dag_ids = _load_dag_ids(
            session=session,
            base_url=base_url,
            headers=headers,
            auth=auth,
            verify_setting=verify_setting,
            use_curl_fallback=use_curl_fallback,
            page_limit=page_limit,
        )
        if not dag_ids:
            raise ValueError("No DAG IDs found for AIRFLOW_SOURCE_MODE=web")
        _log(f"web mode dags={len(dag_ids)}")
        _log(f"web mode collect window: logical date >= {start_date.isoformat()} (UTC), COLLECT_DAYS={days}")
        max_runs = int(os.getenv("WEB_MAX_DAGRUNS_PER_DAG", "30"))
        all_rows: List[dict] = []
        for dag_id in dag_ids:
            try:
                dag_runs = _fetch_dag_runs_from_web_list(
                    base_url=base_url,
                    headers=headers,
                    auth=auth,
                    verify_setting=verify_setting,
                    dag_id=dag_id,
                    start_date=start_date,
                )
            except Exception as exc:
                _log(f"web mode dag={dag_id}, skip due to error: {exc}")
                continue
            if dag_runs.empty:
                _log(f"web mode dag={dag_id}, no dag runs after filters (see messages above)")
                continue
            dag_runs = dag_runs.sort_values("execution_date", ascending=False).head(max_runs)
            _log(f"web mode dag={dag_id}, selected dag runs={len(dag_runs)}")
            for _, run in dag_runs.iterrows():
                execution_date = run["execution_date"].isoformat()
                run_rows = _fetch_task_instances_from_graph_page(
                    base_url=base_url,
                    headers=headers,
                    auth=auth,
                    verify_setting=verify_setting,
                    dag_id=dag_id,
                    execution_date=execution_date,
                    run_id=str(run["run_id"]),
                )
                all_rows.extend(run_rows)
        task_df = pd.DataFrame(all_rows)
        _log(f"web mode task rows={len(task_df)}")
        return task_df

    raise ValueError("Only AIRFLOW_SOURCE_MODE=web is supported in current version.")


def save_raw(df: pd.DataFrame, db_url: str, raw_table: str, raw_csv_path: str) -> None:
    os.makedirs(os.path.dirname(raw_csv_path), exist_ok=True)
    engine = create_engine(db_url)

    if df.empty:
        _log("no rows fetched, skip writing raw table")
        return

    df.to_sql(raw_table, engine, if_exists="replace", index=False)
    df.to_csv(raw_csv_path, index=False, encoding="utf-8")
    _log(f"saved raw table={raw_table}, rows={len(df)}")
    _log(f"saved raw csv={raw_csv_path}")


def main() -> None:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env", override=True)
    days = int(os.getenv("COLLECT_DAYS", "14"))
    page_limit = int(os.getenv("PAGE_LIMIT", "1000"))
    db_url = os.getenv("DB_URL", "sqlite:///airflow_metrics.db")
    raw_table = os.getenv("RAW_TABLE", "raw_task_instances")
    raw_csv_path = os.getenv("RAW_CSV_PATH", "data/raw_task_instances.csv")
    edges_table = os.getenv("EDGES_TABLE", "dag_task_edges")
    edges_csv_path = os.getenv("EDGES_CSV_PATH", "data/dag_task_edges.csv")

    try:
        _log("start extract from airflow api")
        raw_df = fetch_task_instances(days=days, page_limit=page_limit)
        _log(f"extract done, total rows={len(raw_df)}")
        save_raw(raw_df, db_url=db_url, raw_table=raw_table, raw_csv_path=raw_csv_path)
        edges_df = fetch_dag_task_edges(page_limit=page_limit)
        _log(f"task edges extract done, total rows={len(edges_df)}")
        save_dag_edges(edges_df, db_url=db_url, edges_table=edges_table, edges_csv_path=edges_csv_path)
    except requests.exceptions.SSLError as exc:
        _log(
            "ssl handshake failed. Try setting AIRFLOW_CA_BUNDLE to the server CA file, "
            "or temporarily set AIRFLOW_VERIFY_SSL=false for internal-network troubleshooting."
        )
        _log(f"failed: {exc}")
        raise
    except Exception as exc:
        _log(f"failed: {exc}")
        raise


if __name__ == "__main__":
    main()
