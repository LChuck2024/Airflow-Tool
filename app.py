import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from pandas.errors import DatabaseError
from sqlalchemy import create_engine
from update_cookie import parse_curl_auth


def _log(message: str) -> None:
    print(f"[app] {message}")


def load_fact_data(db_url: str, fact_table: str) -> pd.DataFrame:
    engine = create_engine(db_url)
    try:
        return pd.read_sql(f"SELECT * FROM {fact_table}", engine)
    except DatabaseError:
        _log(f"fact table={fact_table} not found yet")
        return pd.DataFrame()


def _extract_base_url_from_curl(curl_text: str) -> str:
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


def _extract_dag_allowlist_from_curl(curl_text: str) -> str:
    dag_ids: set[str] = set()
    text = (curl_text or "").strip()
    if not text:
        return ""

    # 1) Parse from request URL query string.
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

    # 2) Parse from --data-urlencode / --data params.
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

    # 3) Parse from --data-raw with repeated dag_ids params.
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


def main() -> None:
    load_dotenv()
    db_url = os.getenv("DB_URL", "sqlite:///airflow_metrics.db")
    fact_table = os.getenv("FACT_TABLE", "fact_airflow_task_run")
    project_dir = Path(__file__).resolve().parent

    st.set_page_config(page_title="Airflow Task Duration MVP", layout="wide")
    st.markdown(
        """
        <style>
        .stApp { background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%); }
        .block-container { padding-top: 1.4rem; padding-bottom: 2rem; }
        .dashboard-title {
            padding: 0.9rem 1rem; border-radius: 14px;
            background: linear-gradient(90deg, #1d4ed8 0%, #4338ca 100%);
            color: white; font-weight: 700; font-size: 1.9rem; margin-bottom: 0.6rem;
            box-shadow: 0 8px 24px rgba(37, 99, 235, 0.25);
        }
        .section-note { color: #334155; margin-top: -0.2rem; margin-bottom: 0.8rem; font-size: 0.95rem; }
        .section-chip {
            display: inline-block; padding: 0.2rem 0.55rem; border-radius: 999px;
            background: #dbeafe; color: #1e40af; font-size: 0.78rem; font-weight: 700;
            margin-bottom: 0.35rem;
        }
        .panel-title { font-size: 1.1rem; font-weight: 700; color: #1e3a8a; margin: 0.15rem 0 0.45rem 0; }
        div[data-testid="stMetric"] {
            background: #ffffff; border: 1px solid #dbeafe; border-radius: 12px;
            padding: 0.55rem 0.75rem; box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
        }
        div[data-testid="stExpander"] {
            background: #ffffff; border: 1px solid #dbeafe; border-radius: 12px;
            box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05);
        }
        .stButton > button {
            border-radius: 10px; border: 1px solid #93c5fd;
            background: linear-gradient(90deg, #eff6ff, #dbeafe);
            color: #1e3a8a; font-weight: 600;
        }
        div[data-testid="stTabs"] [role="tablist"] {
            gap: 0.45rem;
            background: rgba(219, 234, 254, 0.55);
            border: 1px solid #bfdbfe;
            border-radius: 12px;
            padding: 0.25rem;
            margin-bottom: 0.8rem;
        }
        div[data-testid="stTabs"] [role="tab"] {
            height: 2.4rem;
            border-radius: 10px;
            padding: 0 0.95rem;
            color: #1e3a8a;
            font-weight: 700;
            border: 1px solid transparent;
            background: rgba(255, 255, 255, 0.6);
            transition: all 0.2s ease;
        }
        div[data-testid="stTabs"] [role="tab"]:hover {
            border-color: #93c5fd;
            background: #eff6ff;
        }
        div[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
            color: #ffffff;
            border-color: #1d4ed8;
            background: linear-gradient(90deg, #2563eb 0%, #4338ca 100%);
            box-shadow: 0 4px 14px rgba(37, 99, 235, 0.32);
        }
        h3 { color: #1e3a8a; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="dashboard-title">Airflow 任务耗时对比面板</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-note">聚焦异常波动任务，优先定位最值得优化的 Task。</div>',
        unsafe_allow_html=True,
    )
    st.session_state.setdefault("runtime_base_url", "")
    st.session_state.setdefault("runtime_cookie_header", "")
    st.session_state.setdefault("runtime_csrf_token", "")
    st.session_state.setdefault("runtime_dag_allowlist", "")
    with st.expander("会话更新（粘贴 Copy as cURL，无需重启）", expanded=True):
        # st.caption("自动从 cURL 解析 AIRFLOW_BASE_URL，无需手工输入。")
        curl_text = st.text_area(
            "粘贴 cURL 文本",
            height=140,
            placeholder="在浏览器 Network 中右键请求 -> Copy as cURL，粘贴到这里",
        )
        dag_allowlist_value = st.text_input(
            "DAG_ALLOWLIST（逗号分隔）",
            value=st.session_state["runtime_dag_allowlist"],
            help="例如: D_PARTNER_DAILY_NEW,D_PARTNER_WEEKLY,GTM_MDM_DAILY",
        )
        if st.button("更新会话并刷新数据"):
            try:
                runtime_base_url = st.session_state["runtime_base_url"]
                runtime_cookie = st.session_state["runtime_cookie_header"]
                runtime_csrf = st.session_state["runtime_csrf_token"]
                base_url_source = "历史会话"
                dag_allowlist_source = "手动输入"

                if curl_text.strip():
                    auth = parse_curl_auth(curl_text)
                    if not auth.get("cookie"):
                        st.warning("cURL 中未解析到 Cookie，请重新复制 Airflow 请求的 cURL。")
                        return
                    runtime_cookie = auth["cookie"]
                    runtime_csrf = auth.get("csrf", "")
                    parsed_base_url = _extract_base_url_from_curl(curl_text)
                    if parsed_base_url:
                        runtime_base_url = parsed_base_url
                        base_url_source = "cURL 自动解析"
                    parsed_dag_allowlist = _extract_dag_allowlist_from_curl(curl_text)
                    if parsed_dag_allowlist and not dag_allowlist_value.strip():
                        dag_allowlist_value = parsed_dag_allowlist
                        dag_allowlist_source = "cURL 自动解析"
                else:
                    st.warning("请粘贴 Airflow 请求 cURL，系统会自动解析 BASE_URL 与 Cookie。")
                    return

                if not runtime_base_url:
                    st.warning("未从 cURL 解析到 AIRFLOW_BASE_URL，请确认粘贴的是 Airflow 页面请求 cURL。")
                    return
                if not runtime_cookie:
                    st.warning("请先粘贴含 Cookie 的 cURL。")
                    return
                if not dag_allowlist_value.strip():
                    st.warning("请先输入 DAG_ALLOWLIST，避免 web 模式下无法取数。")
                    return

                st.session_state["runtime_base_url"] = runtime_base_url
                st.session_state["runtime_cookie_header"] = runtime_cookie
                st.session_state["runtime_csrf_token"] = runtime_csrf
                st.session_state["runtime_dag_allowlist"] = dag_allowlist_value.strip()

                run_env = os.environ.copy()
                run_env["AIRFLOW_BASE_URL"] = runtime_base_url
                run_env["AIRFLOW_COOKIE_HEADER"] = runtime_cookie
                run_env["AIRFLOW_X_CSRFTOKEN"] = runtime_csrf
                run_env["DAG_ALLOWLIST"] = dag_allowlist_value.strip()
                dag_count = len([x for x in dag_allowlist_value.split(",") if x.strip()])
                # Avoid UI appearing frozen when too many DAGs are selected.
                if dag_count > 20:
                    run_env["WEB_MAX_DAGRUNS_PER_DAG"] = "5"
                else:
                    run_env["WEB_MAX_DAGRUNS_PER_DAG"] = "15"
                st.info(
                    f"本次配置来源：BASE_URL={base_url_source}，DAG_ALLOWLIST={dag_allowlist_source}；"
                    f"DAG 数={dag_count}，WEB_MAX_DAGRUNS_PER_DAG={run_env['WEB_MAX_DAGRUNS_PER_DAG']}"
                )

                with st.spinner("正在抓取并转换数据，DAG 较多时会耗时几分钟..."):
                    run_result = subprocess.run(
                        [sys.executable, "run_pipeline.py"],
                        cwd=str(project_dir),
                        text=True,
                        capture_output=True,
                        env=run_env,
                        timeout=420,
                    )
                output_text = (run_result.stdout or "") + ("\n" + run_result.stderr if run_result.stderr else "")
                st.code(output_text.strip() or "No output")
                if run_result.returncode != 0:
                    st.error("ETL 执行失败，请检查输出日志。")
                else:
                    st.success("会话更新成功（仅内存态），数据已刷新。")
                    st.rerun()
            except subprocess.TimeoutExpired as exc:
                partial = (exc.stdout or "") + ("\n" + exc.stderr if exc.stderr else "")
                st.code(partial.strip() or "No output before timeout")
                st.error("ETL 执行超时（>7分钟）。建议减少 DAG_ALLOWLIST 范围后重试。")
            except Exception as exc:
                st.error(f"更新失败: {exc}")

    try:
        df = load_fact_data(db_url=db_url, fact_table=fact_table)
    except Exception as exc:
        st.error("读取事实表失败，请先运行 collector.py 和 transform.py")
        st.code(str(exc))
        _log(f"load fact failed: {exc}")
        return

    if df.empty:
        st.warning("暂无数据，请先执行 ETL 流程。")
        return

    for col in ["execution_date", "start_date", "end_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    df["duration_min"] = pd.to_numeric(df["duration_sec"], errors="coerce").fillna(0) / 60.0
    df["run_day"] = df["execution_date"].dt.date.astype("string")

    st.sidebar.markdown("### 筛选与导航")
    st.sidebar.caption("先筛选范围，再看分标签洞察。")
    dag_options = sorted(df["dag_id"].dropna().unique().tolist())
    state_options = sorted(df["state"].dropna().unique().tolist())
    domain_options = sorted(df["domain"].dropna().unique().tolist())
    all_days = pd.to_datetime(df["execution_date"], errors="coerce").dropna()
    min_day = all_days.min().date()
    max_day = all_days.max().date()
    default_start = max(min_day, max_day - pd.Timedelta(days=6))
    selected_days = st.sidebar.date_input(
        "时间范围",
        value=(default_start, max_day),
        min_value=min_day,
        max_value=max_day,
    )
    dag_multi = st.sidebar.multiselect("DAG（可多选）", dag_options, default=dag_options[: min(len(dag_options), 6)])
    state_multi = st.sidebar.multiselect("状态（可多选）", state_options, default=state_options)
    domain_multi = st.sidebar.multiselect("业务域（可多选）", domain_options, default=domain_options)
    task_keyword = st.sidebar.text_input("Task 关键词", placeholder="例如: extract / load / sync")
    top_n = st.sidebar.slider("Top N 任务", min_value=5, max_value=50, value=20, step=5)
    if st.sidebar.button("重置筛选"):
        st.rerun()

    # Streamlit range date_input may return 1 date while user is still picking the end date.
    if isinstance(selected_days, (tuple, list)):
        if len(selected_days) >= 2:
            start_day = selected_days[0]
            end_day = selected_days[1]
        elif len(selected_days) == 1:
            start_day = selected_days[0]
            end_day = selected_days[0]
            st.sidebar.info("已选择开始日期，请继续选择结束日期。")
        else:
            start_day = min_day
            end_day = max_day
    else:
        start_day = selected_days
        end_day = selected_days

    if start_day > end_day:
        start_day, end_day = end_day, start_day

    filtered = df.copy()
    filtered = filtered[
        filtered["execution_date"].dt.date.between(start_day, end_day)
    ]
    if dag_multi:
        filtered = filtered[filtered["dag_id"].isin(dag_multi)]
    if state_multi:
        filtered = filtered[filtered["state"].isin(state_multi)]
    if domain_multi:
        filtered = filtered[filtered["domain"].isin(domain_multi)]
    if task_keyword.strip():
        filtered = filtered[
            filtered["task_id"].astype("string").str.contains(task_keyword.strip(), case=False, na=False)
        ]

    if filtered.empty:
        st.warning("筛选后无数据，请调整过滤条件。")
        return

    # Unified date display format across tables.
    filtered_display = filtered.copy()
    for col in ["execution_date", "start_date", "end_date"]:
        if col in filtered_display.columns:
            filtered_display[col] = pd.to_datetime(filtered_display[col], errors="coerce").dt.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
    if "run_day" in filtered_display.columns:
        filtered_display["run_day"] = pd.to_datetime(filtered_display["run_day"], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )

    st.markdown(
        f'<div class="section-note">当前筛选结果：{start_day} ~ {end_day}，任务实例 {len(filtered):,} 条。</div>',
        unsafe_allow_html=True,
    )
    st.caption("导航说明：📊 看整体趋势，🧪 看单任务波动，🚨 看异常清单，📋 看明细导出。")

    tab_overview, tab_task, tab_anomaly, tab_detail = st.tabs(
        ["📊 总览大盘", "🧪 单任务对比", "🚨 异常候选", "📋 明细与导出"]
    )

    with tab_overview:
        st.markdown('<div class="section-chip">OVERVIEW</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">核心指标与优化优先级</div>', unsafe_allow_html=True)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("任务实例数", f"{len(filtered):,}")
        k2.metric("覆盖 DAG 数", f"{filtered['dag_id'].nunique():,}")
        k3.metric("平均耗时(分钟)", f"{filtered['duration_min'].mean():.2f}")
        k4.metric("P95耗时(分钟)", f"{filtered['duration_min'].quantile(0.95):.2f}")

        st.subheader("波动最大 Task 排行（优化优先级）")
        vol_col1, vol_col2 = st.columns(2)
        vol_lookback_days = vol_col1.slider("波动统计天数", min_value=3, max_value=30, value=14, step=1)
        vol_min_samples = vol_col2.slider("最少有效天数", min_value=2, max_value=10, value=3, step=1)

        latest_day = filtered["execution_date"].dt.date.max()
        if pd.notna(latest_day):
            vol_start_day = latest_day - pd.Timedelta(days=vol_lookback_days - 1)
            recent_df = filtered[filtered["execution_date"].dt.date >= vol_start_day].copy()
        else:
            recent_df = filtered.copy()

        task_daily_vol = (
            recent_df.groupby(["dag_id", "task_id", "run_day"], as_index=False)["duration_min"]
            .mean()
            .rename(columns={"duration_min": "daily_mean_min"})
        )
        if task_daily_vol.empty:
            st.info("近几天暂无可用于波动分析的数据。")
        else:
            volatility = (
                task_daily_vol.groupby(["dag_id", "task_id"], as_index=False)["daily_mean_min"]
                .agg(["count", "mean", "std", "min", "max"])
                .reset_index()
                .rename(
                    columns={
                        "count": "valid_days",
                        "mean": "avg_min",
                        "std": "std_min",
                        "min": "min_min",
                        "max": "max_min",
                    }
                )
            )
            volatility["std_min"] = volatility["std_min"].fillna(0)
            volatility["range_min"] = volatility["max_min"] - volatility["min_min"]
            volatility["cv"] = volatility.apply(
                lambda r: float(r["std_min"] / r["avg_min"]) if r["avg_min"] > 0 else 0.0,
                axis=1,
            )
            volatility["risk_level"] = pd.cut(
                volatility["cv"],
                bins=[-0.001, 0.3, 0.6, float("inf")],
                labels=["低风险", "中风险", "高风险"],
            ).astype("string")
            volatility["risk_badge"] = volatility["risk_level"].map(
                {"高风险": "🔴 高风险", "中风险": "🟡 中风险", "低风险": "🟢 低风险"}
            )
            volatility = volatility[volatility["valid_days"] >= vol_min_samples]
            volatility = volatility.sort_values(["cv", "std_min", "range_min"], ascending=False).head(top_n)
            if volatility.empty:
                st.info("满足最少有效天数条件的 Task 不足，请降低阈值。")
            else:
                volatility["dag_task"] = volatility["dag_id"] + " / " + volatility["task_id"]
                risk_count = volatility["risk_level"].value_counts()
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("高风险 Task", int(risk_count.get("高风险", 0)))
                rc2.metric("中风险 Task", int(risk_count.get("中风险", 0)))
                rc3.metric("低风险 Task", int(risk_count.get("低风险", 0)))
                st.dataframe(
                    volatility[
                        [
                            "risk_badge",
                            "dag_id",
                            "task_id",
                            "valid_days",
                            "avg_min",
                            "std_min",
                            "cv",
                            "range_min",
                            "min_min",
                            "max_min",
                        ]
                    ]
                    .rename(
                        columns={
                            "risk_badge": "风险等级",
                            "dag_id": "DAG",
                            "task_id": "Task",
                            "valid_days": "有效天数",
                            "avg_min": "日均耗时(分钟)",
                            "std_min": "波动标准差(分钟)",
                            "cv": "波动系数(稳定性指标)",
                            "range_min": "最大-最小差值(分钟)",
                            "min_min": "最低日均(分钟)",
                            "max_min": "最高日均(分钟)",
                        }
                    )
                    .sort_values("波动系数(稳定性指标)", ascending=False),
                    use_container_width=True,
                    height=320,
                )
                st.caption(
                    "说明：波动系数 = 波动标准差 / 日均耗时。数值越大，说明该 Task 的耗时越不稳定，越值得优先排查。"
                )
                vol_fig = px.bar(
                    volatility.sort_values("cv", ascending=True),
                    x="cv",
                    y="dag_task",
                    color="risk_level",
                    color_discrete_map={"高风险": "#dc2626", "中风险": "#f59e0b", "低风险": "#16a34a"},
                    orientation="h",
                    title=f"近{vol_lookback_days}天波动最大 Top {len(volatility)} Task（按CV）",
                    hover_data=["std_min", "range_min", "avg_min", "valid_days"],
                )
                vol_fig.update_layout(
                    xaxis_title="波动系数 CV (std/mean)",
                    yaxis_title="DAG / Task",
                    template="plotly_white",
                    paper_bgcolor="rgba(255,255,255,0.98)",
                    plot_bgcolor="rgba(255,255,255,0.98)",
                )
                st.plotly_chart(vol_fig, use_container_width=True)

        bar_data = (
            filtered.groupby(["dag_id", "task_id"], as_index=False)["duration_min"]
            .mean()
            .sort_values("duration_min", ascending=False)
            .head(top_n)
        )
        bar_data["dag_task"] = bar_data["dag_id"] + " / " + bar_data["task_id"]
        bar_data["耗时风险"] = pd.cut(
            bar_data["duration_min"],
            bins=[-0.001, bar_data["duration_min"].quantile(0.5), bar_data["duration_min"].quantile(0.8), float("inf")],
            labels=["低耗时", "中耗时", "高耗时"],
            include_lowest=True,
        ).astype("string")
        fig_bar = px.bar(
            bar_data,
            x="dag_task",
            y="duration_min",
            color="耗时风险",
            color_discrete_map={"高耗时": "#dc2626", "中耗时": "#f59e0b", "低耗时": "#16a34a"},
            title=f"平均耗时 Top {top_n} 任务(分钟)",
        )
        fig_bar.update_layout(
            xaxis_title="DAG / Task",
            yaxis_title="平均耗时(分钟)",
            template="plotly_white",
            paper_bgcolor="rgba(255,255,255,0.98)",
            plot_bgcolor="rgba(255,255,255,0.98)",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        line_data = (
            filtered.groupby("run_day", as_index=False)["duration_min"]
            .mean()
            .sort_values("run_day")
        )
        fig_line = px.line(
            line_data,
            x="run_day",
            y="duration_min",
            markers=True,
            title="每日平均耗时趋势(分钟)",
        )
        fig_line.update_traces(line=dict(color="#2563eb", width=3), marker=dict(size=7))
        fig_line.update_layout(
            xaxis_title="运行日期",
            yaxis_title="平均耗时(分钟)",
            template="plotly_white",
            paper_bgcolor="rgba(255,255,255,0.98)",
            plot_bgcolor="rgba(255,255,255,0.98)",
        )
        fig_line.update_xaxes(tickformat="%Y-%m-%d")
        st.plotly_chart(fig_line, use_container_width=True)

    with tab_task:
        st.subheader("指定 Task 当天 vs 前几天对比")
        task_options = sorted(
            (
                filtered[["dag_id", "task_id"]]
                .dropna()
                .drop_duplicates()
                .assign(dag_task=lambda x: x["dag_id"] + " / " + x["task_id"])["dag_task"]
                .tolist()
            )
        )
        if not task_options:
            st.info("当前筛选条件下没有可对比 Task。")
        else:
            selected_task = st.selectbox("选择要对比的 Task", task_options)
            lookback_days = st.slider("对比前几天", min_value=3, max_value=30, value=7, step=1)
            metric_mode = st.radio("对比口径", options=["mean", "p95", "max"], horizontal=True)
            alert_ratio = st.slider("变慢告警阈值倍率", min_value=1.05, max_value=2.0, value=1.30, step=0.05)
            selected_dag_id, selected_task_id = selected_task.split(" / ", 1)
            task_df = filtered[
                (filtered["dag_id"] == selected_dag_id) & (filtered["task_id"] == selected_task_id)
            ].copy()

            if metric_mode == "p95":
                task_daily = (
                    task_df.groupby("run_day", as_index=False)["duration_min"]
                    .quantile(0.95)
                    .sort_values("run_day")
                    .tail(lookback_days + 1)
                )
                metric_label = "P95"
            elif metric_mode == "max":
                task_daily = (
                    task_df.groupby("run_day", as_index=False)["duration_min"]
                    .max()
                    .sort_values("run_day")
                    .tail(lookback_days + 1)
                )
                metric_label = "最大值"
            else:
                task_daily = (
                    task_df.groupby("run_day", as_index=False)["duration_min"]
                    .mean()
                    .sort_values("run_day")
                    .tail(lookback_days + 1)
                )
                metric_label = "均值"

            if not task_daily.empty:
                today_row = task_daily.iloc[-1]
                baseline_df = task_daily.iloc[:-1]
                baseline_avg = baseline_df["duration_min"].mean() if not baseline_df.empty else 0.0
                delta_min = float(today_row["duration_min"] - baseline_avg)
                delta_pct = float((delta_min / baseline_avg) * 100) if baseline_avg > 0 else 0.0
                slow_ratio = float(today_row["duration_min"] / baseline_avg) if baseline_avg > 0 else 0.0

                c1, c2, c3 = st.columns(3)
                c1.metric(f"当天{metric_label}(分钟)", f"{today_row['duration_min']:.2f}")
                c2.metric(f"前{lookback_days}天基线(分钟)", f"{baseline_avg:.2f}")
                c3.metric("较基线变化", f"{delta_min:+.2f} 分钟 ({delta_pct:+.1f}%)")

                if baseline_avg > 0:
                    if slow_ratio >= alert_ratio:
                        status_badge = "🔴 高风险"
                        st.error(
                            f"状态: 红色告警 | 今日{metric_label}为基线的 {slow_ratio:.2f}x，超过阈值 {alert_ratio:.2f}x"
                        )
                    elif slow_ratio >= alert_ratio * 0.85:
                        status_badge = "🟡 中风险"
                        st.warning(
                            f"状态: 黄色预警 | 今日{metric_label}为基线的 {slow_ratio:.2f}x，接近阈值 {alert_ratio:.2f}x"
                        )
                    else:
                        status_badge = "🟢 低风险"
                        st.success(f"状态: 绿色正常 | 今日{metric_label}为基线的 {slow_ratio:.2f}x")
                    st.caption(f"风险判定：{status_badge}（基于今日/基线倍率）")

                compare_fig = px.bar(
                    task_daily,
                    x="run_day",
                    y="duration_min",
                    title=f"{selected_task_id} 每日{metric_label}耗时对比(分钟)",
                )
                trend_daily = (
                    task_df.groupby("run_day", as_index=False)["duration_min"]
                    .agg(["mean", "max"])
                    .reset_index()
                    .rename(columns={"mean": "mean_min", "max": "max_min"})
                )
                p95_daily = (
                    task_df.groupby("run_day", as_index=False)["duration_min"]
                    .quantile(0.95)
                    .rename(columns={"duration_min": "p95_min"})
                )
                trend_daily = trend_daily.merge(p95_daily, on="run_day", how="left")
                compare_fig.add_trace(
                    go.Scatter(
                        x=trend_daily["run_day"],
                        y=trend_daily["mean_min"],
                        mode="lines+markers",
                        name="均值",
                        line=dict(color="#1f77b4"),
                        yaxis="y2",
                    )
                )
                compare_fig.add_trace(
                    go.Scatter(
                        x=trend_daily["run_day"],
                        y=trend_daily["p95_min"],
                        mode="lines+markers",
                        name="P95",
                        line=dict(color="#ff7f0e"),
                        yaxis="y2",
                    )
                )
                compare_fig.add_trace(
                    go.Scatter(
                        x=trend_daily["run_day"],
                        y=trend_daily["max_min"],
                        mode="lines+markers",
                        name="最大值",
                        line=dict(color="#d62728"),
                        yaxis="y2",
                    )
                )
                if baseline_avg > 0:
                    compare_fig.add_hline(
                        y=baseline_avg,
                        line_dash="dash",
                        line_color="red",
                        annotation_text=f"前{lookback_days}天基线 {baseline_avg:.2f}",
                    )
                compare_fig.update_layout(
                    xaxis_title="运行日期",
                    yaxis_title=f"{metric_label}(柱状)",
                    yaxis2=dict(
                        title="均值/P95/最大值(折线)",
                        overlaying="y",
                        side="right",
                        showgrid=False,
                    ),
                    legend=dict(orientation="h"),
                    template="plotly_white",
                    paper_bgcolor="rgba(255,255,255,0.98)",
                    plot_bgcolor="rgba(255,255,255,0.98)",
                )
                compare_fig.update_xaxes(tickformat="%Y-%m-%d")
                st.plotly_chart(compare_fig, use_container_width=True)
                st.dataframe(
                    task_daily.assign(run_day=lambda x: pd.to_datetime(x["run_day"], errors="coerce").dt.strftime("%Y-%m-%d"))
                    .rename(columns={"run_day": "日期", "duration_min": f"{metric_label}耗时(分钟)"})
                    .sort_values("日期", ascending=False),
                    use_container_width=True,
                    height=240,
                )

    with tab_anomaly:
        st.subheader("异常任务候选 (超过整体P95)")
        threshold = filtered["duration_min"].quantile(0.95)
        abnormal = filtered_display[filtered["duration_min"] > threshold].sort_values("duration_min", ascending=False)
        abnormal["异常等级"] = abnormal["duration_min"].apply(
            lambda x: "🔴 高异常" if x >= threshold * 1.5 else "🟡 中异常"
        )
        a1, a2 = st.columns(2)
        a1.metric("异常阈值 P95(分钟)", f"{threshold:.2f}")
        a2.metric("异常样本数", f"{len(abnormal):,}")
        st.dataframe(
            abnormal[
                [
                    "异常等级",
                    "dag_id",
                    "task_id",
                    "state",
                    "execution_date",
                    "duration_min",
                    "owner",
                    "domain",
                    "criticality",
                ]
            ],
            column_config={
                "异常等级": "异常等级",
                "dag_id": "DAG",
                "task_id": "Task",
                "state": "状态",
                "execution_date": "执行时间",
                "duration_min": "耗时(分钟)",
                "owner": "负责人",
                "domain": "业务域",
                "criticality": "关键级别",
            },
            use_container_width=True,
            height=320,
        )

    with tab_detail:
        st.subheader("明细数据")
        detail_df = filtered_display.sort_values("execution_date", ascending=False)
        st.download_button(
            label="下载筛选结果 CSV",
            data=detail_df.to_csv(index=False).encode("utf-8"),
            file_name="airflow_filtered_detail.csv",
            mime="text/csv",
        )
        st.dataframe(
            detail_df,
            column_config={
                "dag_id": "DAG",
                "task_id": "Task",
                "state": "状态",
                "execution_date": "执行时间",
                "start_date": "开始时间",
                "end_date": "结束时间",
                "duration_min": "耗时(分钟)",
                "owner": "负责人",
                "domain": "业务域",
                "criticality": "关键级别",
            },
            use_container_width=True,
            height=440,
        )


if __name__ == "__main__":
    main()
