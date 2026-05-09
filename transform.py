import os
from pathlib import Path
from typing import List

import pandas as pd
import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine


def _log(message: str) -> None:
    print(f"[transform] {message}")


def _safe_datetime(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df


def _load_mapping(mapping_file: str) -> pd.DataFrame:
    if not os.path.exists(mapping_file):
        return pd.DataFrame(columns=["dag_id", "task_id", "owner", "domain", "criticality"])

    with open(mapping_file, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    rows = cfg.get("mappings", [])
    if not rows:
        return pd.DataFrame(columns=["dag_id", "task_id", "owner", "domain", "criticality"])

    mapping_df = pd.DataFrame(rows)
    for col in ["dag_id", "task_id", "owner", "domain", "criticality"]:
        if col not in mapping_df.columns:
            mapping_df[col] = None
    return mapping_df[["dag_id", "task_id", "owner", "domain", "criticality"]]


def build_fact(raw_df: pd.DataFrame, mapping_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return raw_df

    raw_df = _safe_datetime(raw_df, ["start_date", "end_date", "execution_date"])

    # Transform: derive duration with stable numeric type.
    raw_df["duration_sec"] = (raw_df["end_date"] - raw_df["start_date"]).dt.total_seconds()
    raw_df["duration_sec"] = raw_df["duration_sec"].fillna(0).clip(lower=0)

    for col in ["dag_id", "task_id", "run_id", "state", "try_number"]:
        if col not in raw_df.columns:
            raw_df[col] = None

    raw_df["try_number"] = pd.to_numeric(raw_df["try_number"], errors="coerce").fillna(0).astype(int)

    # Deduplicate by business key and keep latest retry.
    raw_df = raw_df.sort_values(["dag_id", "task_id", "run_id", "try_number"])
    fact_df = raw_df.drop_duplicates(subset=["dag_id", "task_id", "run_id"], keep="last").copy()

    fact_df = fact_df.merge(mapping_df, on=["dag_id", "task_id"], how="left")
    fact_df["run_date"] = (
        pd.to_datetime(fact_df["execution_date"], errors="coerce", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.strftime("%Y-%m-%d")
    )

    selected_cols = [
        "dag_id",
        "task_id",
        "run_id",
        "state",
        "execution_date",
        "start_date",
        "end_date",
        "duration_sec",
        "try_number",
        "owner",
        "domain",
        "criticality",
        "run_date",
    ]
    return fact_df[selected_cols]


def main() -> None:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env", override=True)
    db_url = os.getenv("DB_URL", "sqlite:///airflow_metrics.db")
    raw_table = os.getenv("RAW_TABLE", "raw_task_instances")
    fact_table = os.getenv("FACT_TABLE", "fact_airflow_task_run")
    fact_csv_path = os.getenv("FACT_CSV_PATH", "data/fact_airflow_task_run.csv")
    mapping_file = os.getenv("TASK_MAPPING_FILE", "task_mapping.yaml")

    try:
        engine = create_engine(db_url)
        try:
            raw_df = pd.read_sql(f"SELECT * FROM {raw_table}", engine)
        except Exception as exc:
            err = str(exc).lower()
            if "no such table" in err or "does not exist" in err:
                _log(f"raw table={raw_table} not found yet, treat as empty")
                raw_df = pd.DataFrame()
            else:
                raise
        _log(f"read raw rows={len(raw_df)} from table={raw_table}")

        mapping_df = _load_mapping(mapping_file)
        _log(f"loaded mapping rows={len(mapping_df)}")

        fact_df = build_fact(raw_df, mapping_df)
        if fact_df.empty:
            _log("fact dataframe is empty, skip writing")
            return

        os.makedirs(os.path.dirname(fact_csv_path), exist_ok=True)
        fact_df.to_sql(fact_table, engine, if_exists="replace", index=False)
        fact_df.to_csv(fact_csv_path, index=False, encoding="utf-8")
        _log(f"saved fact rows={len(fact_df)} to table={fact_table}")
        _log(f"saved fact csv={fact_csv_path}")
    except Exception as exc:
        _log(f"failed: {exc}")
        raise


if __name__ == "__main__":
    main()
