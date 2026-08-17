# Models Cost Management

把 `bills/<project>/*.csv` 导入 SQLite，用 Web 查看 Cost / Tokens / Estimate / Reports。

默认地址：**http://127.0.0.1:8000/**  
技术栈：FastAPI + SQLite + Chart.js（静态资源本地提供）+ pytest。

---

## 一、怎么跑起来

按顺序做即可。命令默认在已激活的虚拟环境里执行。

### 1. 环境差异（先看这张表）

| 步骤 | macOS / Linux | Windows PowerShell |
|------|---------------|-------------------|
| 建环境 | `python3 -m venv .venv` | `python -m venv .venv` |
| 激活 | `source .venv/bin/activate` | `.\.venv\Scripts\Activate.ps1` |
| 设环境变量 | `export KEY=value` | `$env:KEY = "value"` |

Windows CMD：激活用 `.venv\Scripts\activate.bat`，环境变量用 `set KEY=value`。  
若 PowerShell 拒绝执行脚本：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

### 2. 安装

```bash
pip install -r requirements.txt
```

### 3. （推荐）导入账单 + 建管理员

有 `bills/` 数据时：

```bash
python -m app.cli ingest --bills-dir bills --db-path data/cost_mgmt.sqlite3
python -m app.cli create-admin --bills-dir bills --db-path data/cost_mgmt.sqlite3 \
  --username admin --password "请换成强密码"
```

- 已导入文件会记在 `ingested_files`，重复跑会跳过；要按校验和重导加 `--reimport-changed`。
- 不设密码时默认 `admin/admin12345`，勿用于生产。
- 只想先看空页面：跳过本步，并设 `COST_MGMT_AUTH_ENABLED=0` 关闭登录。

### 4. 启动

```bash
python -m app.cli serve \
  --bills-dir bills \
  --db-path data/cost_mgmt.sqlite3 \
  --host 127.0.0.1 --port 8000
```

| 页面 | URL |
|------|-----|
| Cost | http://127.0.0.1:8000/ |
| Login | http://127.0.0.1:8000/login |
| Import | http://127.0.0.1:8000/import |
| Tokens | http://127.0.0.1:8000/tokens |
| Estimate | http://127.0.0.1:8000/estimate |
| Reports | http://127.0.0.1:8000/reports |
| Health | http://127.0.0.1:8000/health |

未导入数据时列表为空是正常的。

### 5. 常用环境变量

| 变量 | 何时用 |
|------|--------|
| `COST_MGMT_AUTH_ENABLED=0` | 本机调试，关掉登录 |
| `COST_MGMT_SESSION_SECRET_KEY` | 生产必设，会话签名密钥 |
| `COST_MGMT_COOKIE_SECURE=1` | 走 HTTPS 反代时打开 |
| `AUTO_INGEST=0` | 默认；启动不自动扫 CSV，用 `ingest` 手动导入 |

---

## 二、测试与检查

```bash
python -m pytest --ignore=tests/e2e

pip install -r requirements-dev.txt && python -m ruff check .

# 可选 E2E
pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m pytest -m e2e
```

---

## 三、数据口径（可选）

表定义在 `app/db.py`：`projects`、`ingested_files`、`transactions`。

用 SQLite 自核时，与页面同一口径：

```sql
SELECT COALESCE(SUM(cost_usd), 0) AS total_cost_usd
FROM transactions
WHERE project_name = 'YOUR_PROJECT' AND currency = 'USD';

SELECT COUNT(DISTINCT CASE WHEN cost_usd IS NOT NULL THEN usage_date END) AS days_with_data
FROM transactions
WHERE project_name = 'YOUR_PROJECT' AND currency = 'USD';
```

- 总成本：范围内行求和（同日多行累加）。
- 天数：有 `cost_usd` 的不同 `usage_date` 个数。

---

## 四、排障

- 登录失败：回到 `/login?error=invalid`，看页面提示。
- DevTools 里 `chrome-extension://...` 的 `ERR_FILE_NOT_FOUND`：浏览器扩展问题，与本项目无关。

---

## 五、工程约定

`AGENTS.md`、`.cursor/rules/`、`docs/harness-playbook.md`：小步改 → `pytest` 验证 → 写清原因与结果。
