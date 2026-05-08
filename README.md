# Airflow Task Duration Local MVP

当前版本仅支持一种方式：在 Streamlit 页面粘贴 `Copy as cURL`，运行时解析认证信息并拉取数据。  
敏感信息不会写入 `.env`。

## 1) 环境准备（首次）

```bash
cd "/Users/chuck.li/Documents/01-项目资料/PG_Projects/A-daily-local-job/airflow增强"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

可选：如果你希望重置默认配置，再执行：

```bash
cp .env.example .env
```

## 2) 启动面板

```bash
streamlit run app.py
```

浏览器打开 `http://localhost:8501`。

## 3) 页面内配置（唯一入口）

在“会话更新（粘贴 Copy as cURL，无需重启）”中填写：

- `cURL` 文本（必填，用于解析 `Cookie` / `X-CSRFToken`）
- `AIRFLOW_BASE_URL`（可留空，通常可从 cURL 自动解析）
- `DAG_ALLOWLIST`（可留空，支持从 cURL 中 `dag_id` / `dag_ids` / `_flt_3_dag_id` 自动解析）

然后点击“更新会话并刷新数据”，会自动执行 ETL。

说明：

- 当 DAG 数较多时，会自动降低 `WEB_MAX_DAGRUNS_PER_DAG` 以避免前端长时间无响应
- ETL 超过 7 分钟会超时返回，建议缩小 `DAG_ALLOWLIST` 范围后重试

## 4) 交付给其他用户

可以把该目录打包给其他用户使用，但建议仅分发下列文件：

- `app.py`
- `collector.py`
- `transform.py`
- `run_pipeline.py`
- `update_cookie.py`
- `requirements.txt`
- `.env.example`
- `README.md`
- `task_mapping.yaml`

不要分发以下内容：

- `.env`
- `airflow_metrics.db`
- `data/*.csv`
- `.venv/`

## 5) 安全说明

- `.env` 仅保留非敏感默认项（数据库、采集天数、SSL 开关等）
- `AIRFLOW_BASE_URL`、`AIRFLOW_COOKIE_HEADER`、`AIRFLOW_X_CSRFTOKEN`、`DAG_ALLOWLIST` 均为运行时内存注入
- 重启 Streamlit 后需要重新粘贴 cURL（安全换便捷）
- 建议每次使用后主动清空 cURL 输入框，并在浏览器退出 Airflow 会话

## 6) 目录说明

- `app.py`: Streamlit 页面，运行时接收 cURL 并触发 ETL
- `collector.py`: Web 模式采集 Airflow 任务实例
- `transform.py`: 构建事实表
- `run_pipeline.py`: 串行执行采集与转换
- `update_cookie.py`: cURL 解析工具函数（不写 `.env`）
