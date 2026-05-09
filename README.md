# Airflow 任务耗时看板（本地）

从 Airflow 网页拉任务实例，算耗时并看图表。**电脑要能打开 Airflow**（内网或连上 VPN）。登录方式：在浏览器里对 Airflow 请求 **Copy as cURL**，粘贴到看板里的「数据源会话」即可（Cookie 不会写入 `.env`）。

**需要：** Python 3.10+、Node 18+。

---

## 第一次用

在**项目根目录**执行：

```bash
python3 -m venv .venv-backend
source .venv-backend/bin/activate   # Windows：.venv-backend\Scripts\activate
pip install -r requirements.txt -r backend/requirements.txt
deactivate

npm install
cp .env.example .env    # 可选
```

## 平时怎么用

```bash
npm run dev
```

浏览器打开 <http://localhost:5173> → 展开「数据源会话」→ 粘贴 cURL → 运行管线。前端会通过 Vite 访问本机 API（`127.0.0.1:8000`）。

只起一半：`npm run dev:web`（仅页面）或 `npm run dev:api`（仅接口）。

## 其他

- **旧版 Streamlit**：`source .venv-backend/bin/activate && streamlit run app.py`（端口 8501）。
- **打包前端**：`npm run build`，结果在 `frontend/dist/`。部署静态站时若要跨域调 API，设环境变量 **`VITE_API_BASE_URL`** 为 API 根地址。
- **别发给别人的东西**：含 Cookie 的 cURL、`.env` 里的秘密、数据库文件 `airflow_metrics.db`、`data/*.csv`、虚拟环境文件夹。
