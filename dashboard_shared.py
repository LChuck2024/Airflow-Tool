"""供 Streamlit 与 FastAPI 共用的数据加载与 cURL 解析逻辑。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
from pandas.errors import DatabaseError
from sqlalchemy import create_engine


def _log(message: str) -> None:
    print(f"[dashboard_shared] {message}")


def load_fact_data(db_url: str, fact_table: str) -> pd.DataFrame:
    engine = create_engine(db_url)
    try:
        return pd.read_sql(f"SELECT * FROM {fact_table}", engine)
    except DatabaseError:
        _log(f"fact table={fact_table} not found yet")
        return pd.DataFrame()


def load_dag_edges(db_url: str, edges_table: str, edges_csv_path: str) -> pd.DataFrame:
    engine = create_engine(db_url)
    try:
        df = pd.read_sql(f"SELECT * FROM {edges_table}", engine)
        if not df.empty:
            return df
    except DatabaseError:
        _log(f"edges table={edges_table} not found yet")

    csv_path = Path(edges_csv_path)
    if csv_path.is_file():
        try:
            return pd.read_csv(csv_path)
        except Exception as exc:
            _log(f"read edges csv failed: {exc}")
    return pd.DataFrame(columns=["dag_id", "task_id", "upstream_task_id"])


def default_edges_table() -> str:
    return os.getenv("EDGES_TABLE", "dag_task_edges")


def default_edges_csv_path() -> str:
    return os.getenv("EDGES_CSV_PATH", "data/dag_task_edges.csv")


def extract_base_url_from_curl(curl_text: str) -> str:
    text = (curl_text or "").strip()
    if not text:
        return ""
    first_line = text.splitlines()[0]
    quote_char = "'" if "'" in first_line else '"'
    if "curl " not in first_line or quote_char not in first_line:
        return ""
    parts = first_line.split(quote_char)
    if len(parts) < 2:
        return ""
    raw_url = parts[1].strip()
    parsed = urlparse(raw_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def extract_dag_allowlist_from_curl(curl_text: str) -> str:
    dag_ids: set[str] = set()
    text = (curl_text or "").strip()
    if not text:
        return ""

    first_line = text.splitlines()[0]
    quote_char = "'" if "'" in first_line else '"'
    if "curl " in first_line and quote_char in first_line:
        parts = first_line.split(quote_char)
        if len(parts) >= 2:
            raw_url = parts[1].strip()
            parsed = urlparse(raw_url)
            query = parse_qs(parsed.query)
            for key in ("dag_id", "_flt_3_dag_id"):
                for value in query.get(key, []):
                    item = unquote(value).strip()
                    if item:
                        dag_ids.add(item)

    patterns = [
        r"(?:--data-urlencode|--data)\s+'(?:_flt_3_dag_id|dag_id)=([^']+)'",
        r"(?:--data-urlencode|--data)\s+\"(?:_flt_3_dag_id|dag_id)=([^\"]+)\"",
        r"(?:\?|&)(?:_flt_3_dag_id|dag_id)=([^&'\"\\s]+)",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            item = unquote(str(match)).strip()
            if item:
                dag_ids.add(item)

    data_raw_patterns = [
        r"--data-raw\s+'([^']*)'",
        r"--data-raw\s+\"([^\"]*)\"",
    ]
    for raw_pattern in data_raw_patterns:
        for raw_body in re.findall(raw_pattern, text, flags=re.IGNORECASE | re.DOTALL):
            query = parse_qs(raw_body, keep_blank_values=False)
            for key in ("dag_ids", "dag_id", "_flt_3_dag_id"):
                for value in query.get(key, []):
                    item = unquote(value).strip()
                    if item:
                        dag_ids.add(item)

    return ",".join(sorted(dag_ids))


def project_root() -> Path:
    return Path(__file__).resolve().parent


def default_db_url() -> str:
    return os.getenv("DB_URL", "sqlite:///airflow_metrics.db")


def default_fact_table() -> str:
    return os.getenv("FACT_TABLE", "fact_airflow_task_run")
