# Models Cost Management

把 `bills/<project>/*.csv` 导入 SQLite，用 Web 查看 Cost / Tokens / Estimate / Reports。

默认地址：**http://127.0.0.1:8000/**  
技术栈：FastAPI + SQLite + Chart.js（静态资源本地提供）+ pytest。

---

## 一、怎么跑起来

按你的系统选一节，从头复制执行即可。有 `bills/` 数据时会导入并建管理员；只想先看空页面可跳过 `ingest` / `create-admin`，并打开 `COST_MGMT_AUTH_ENABLED=0`。

### macOS / Linux

```bash
cd /path/to/ai-cost-manager

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 有账单数据时执行（可跳过）
python -m app.cli ingest --bills-dir bills --db-path data/cost_mgmt.sqlite3
python -m app.cli create-admin \
  --bills-dir bills \
  --db-path data/cost_mgmt.sqlite3 \
  --username admin --password "请换成强密码"

# 本机调试可关登录：export COST_MGMT_AUTH_ENABLED=0
# 生产建议：export COST_MGMT_SESSION_SECRET_KEY="随机密钥"

python -m app.cli serve \
  --bills-dir bills \
  --db-path data/cost_mgmt.sqlite3 \
  --host 127.0.0.1 --port 8000
```

### Windows（PowerShell）

```powershell
cd C:\path\to\ai-cost-manager

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 若提示无法加载 Activate.ps1：
# Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 有账单数据时执行（可跳过）
python -m app.cli ingest --bills-dir bills --db-path data/cost_mgmt.sqlite3
python -m app.cli create-admin `
  --bills-dir bills `
  --db-path data/cost_mgmt.sqlite3 `
  --username admin --password "请换成强密码"

# 本机调试可关登录：$env:COST_MGMT_AUTH_ENABLED = "0"
# 生产建议：$env:COST_MGMT_SESSION_SECRET_KEY = "随机密钥"

python -m app.cli serve `
  --bills-dir bills `
  --db-path data/cost_mgmt.sqlite3 `
  --host 127.0.0.1 --port 8000
```

### Windows（CMD）

```bat
cd C:\path\to\ai-cost-manager

python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt

REM 有账单数据时执行（可跳过）
python -m app.cli ingest --bills-dir bills --db-path data/cost_mgmt.sqlite3
python -m app.cli create-admin --bills-dir bills --db-path data/cost_mgmt.sqlite3 --username admin --password "请换成强密码"

REM 本机调试可关登录：set COST_MGMT_AUTH_ENABLED=0
REM 生产建议：set COST_MGMT_SESSION_SECRET_KEY=随机密钥

python -m app.cli serve --bills-dir bills --db-path data/cost_mgmt.sqlite3 --host 127.0.0.1 --port 8000
```

### 启动后打开

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
`create-admin` 不设密码时默认 `admin/admin12345`，勿用于生产。  
已导入文件记在 `ingested_files`，重复 `ingest` 会跳过；按校验和重导加 `--reimport-changed`。

### 常用环境变量

| 变量 | 何时用 |
|------|--------|
| `COST_MGMT_AUTH_ENABLED=0` | 本机调试，关掉登录 |
| `COST_MGMT_SESSION_SECRET_KEY` | 生产必设，会话签名密钥 |
| `COST_MGMT_COOKIE_SECURE=1` | 走 HTTPS 反代时打开 |
| `AUTO_INGEST=0` | 默认；启动不自动扫 CSV，用 `ingest` 手动导入 |

---

## 二、测试与检查

先激活虚拟环境，再执行：

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
