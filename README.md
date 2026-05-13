# Models Cost Management

将 `bills/<project>/*.csv` 导入到 SQLite，并提供一个带项目切换的 Web 页面展示账单数据（含图表与明细列表）。

## TL;DR：2 分钟跑起来（本机调试）

只想先看到页面（不创建管理员、不导入 CSV）：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 关闭鉴权（仅限本机调试）
export COST_MGMT_AUTH_ENABLED=0

python -m app.cli serve --host 127.0.0.1 --port 8002
```

打开：

- 页面：`http://127.0.0.1:8002/`
- 健康检查：`http://127.0.0.1:8002/health`

> 提示：没有导入数据时，项目列表/报表会为空，这是正常的；要看真实数据请继续看“导入 CSV”章节。

## 技术栈

- 后端：Python + FastAPI
- 数据库：SQLite（使用 Python 内置 `sqlite3`，并在建表时做版本化管理）
- 前端：Chart.js（已内置在 `app/static/js/chart.umd.min.js`，由 `/static/...` 提供，无需外网 CDN）
- 测试：pytest（导入逻辑 + API 返回校验）

## 快速启动（带数据）

你本机已有 `bills/<project>/*.csv` 时，按下面顺序即可看到完整功能（导入页 + 报表页 + 图表）。

## 1) 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) 导入 CSV 到数据库

```bash
.venv/bin/python -m app.cli \
  ingest \
  --bills-dir bills \
  --db-path data/cost_mgmt.sqlite3
```

导入逻辑会在数据库里记录 `ingested_files`，同一个 `bills/<project>/<file>.csv` 文件已读取后会跳过；可选 `--reimport-changed` 用于校验和重新导入。

## 3) 启动 Web 页面

系统会默认启用登录鉴权（你需要先创建管理员用户）。

### 3.1) 创建管理员用户

```bash
.venv/bin/python -m app.cli \
  create-admin \
  --bills-dir bills \
  --db-path data/cost_mgmt.sqlite3 \
  --username admin --password "请换成强密码"
```

`create-admin` 的默认值是 `admin/admin12345`，请不要直接使用默认密码。

安全建议（强烈建议在生产环境设置）：
- `COST_MGMT_SESSION_SECRET_KEY`：用于签名登录会话 cookie 的密钥（必须是随机且保密）
- `COST_MGMT_COOKIE_SECURE=1`：当你使用 HTTPS 反向代理时开启（cookie 仅在 HTTPS 下传输）
- `AUTO_INGEST=0`（默认）：服务启动时不会自动扫描并导入 CSV（避免“误读/重复读/写库”的风险）；推荐使用 `ingest` 手动导入

如确需关闭登录鉴权（仅限本机调试），可以设置：
- `COST_MGMT_AUTH_ENABLED=0`

示例（Linux/macOS 终端）：

```bash
export COST_MGMT_SESSION_SECRET_KEY="请换成随机密钥"
export COST_MGMT_COOKIE_SECURE=1
```

```bash
.venv/bin/python -m app.cli \
  serve \
  --bills-dir bills \
  --db-path data/cost_mgmt.sqlite3 \
  --host 127.0.0.1 --port 8000
```

如果 `8000` 端口被占用（例如你已在运行旧服务），可以改用其它端口（例如 `8002`）：

```bash
.venv/bin/python -m app.cli \
  serve \
  --bills-dir bills \
  --db-path data/cost_mgmt.sqlite3 \
  --host 127.0.0.1 --port 8002
```

访问地址（以你实际启动的端口为准）：

- 页面：`http://127.0.0.1:<PORT>/`
- 登录页：`http://127.0.0.1:<PORT>/login`
- 导入页面：`http://127.0.0.1:<PORT>/import`
- Token 分析页面：`http://127.0.0.1:<PORT>/tokens`
- 汇总报表页面：`http://127.0.0.1:<PORT>/reports`
- 健康检查：`http://127.0.0.1:<PORT>/health`
- API 项目列表：`http://127.0.0.1:<PORT>/api/projects`

导入功能已拆到独立页面：`/import`，用于把本地 `bills/<project>/*.csv` 中尚未入库的文件导入数据库。

### 登录失败 / DevTools 里很多红色请求？

- 密码错误时会回到 **`/login?error=invalid`**，页面会显示与登录页一致的错误提示（不再是纯文本 `Unauthorized`）。
- 若在 Chrome **Network** 里看到 `utils.js`、`extensionState.js` 等 **`net::ERR_FILE_NOT_FOUND`**，且地址是 **`chrome-extension://...`**，来源是**浏览器扩展**，不是本项目；本应用登录页不依赖外链脚本（图表库已放在 `app/static/js/`）。

## 4) 测试

```bash
.venv/bin/python -m pytest
```

## 4.1) 浏览器级 E2E（Playwright）

该套件会启动一个临时的 FastAPI/uvicorn 服务，并用真实浏览器执行前端 JavaScript（含图表渲染）。

安装依赖 + 浏览器：

```bash
.venv/bin/pip install -r requirements-e2e.txt
.venv/bin/python -m playwright install chromium
```

运行 e2e：

```bash
.venv/bin/python -m pytest -m e2e
```

## 5) 代码质量（Lint）

本项目使用 `ruff` 做基础静态检查（在 CI 中强制执行）。

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
```

## 数据表结构说明

建表文件在 `app/db.py` 中定义，核心表：

- `projects`：项目名称（来自 `bills/<project>`）
- `ingested_files`：记录每个 CSV 文件是否已读取（含 sha256 校验和）
- `transactions`：每条账单行（按 CSV 行导入，包含完整 CSV 列（含 Resource* 字段）与 `raw_json`；本项目不做 Forecast 统计与展示）

## 如何验证统计口径是否正确

推荐用“同一口径双算”来验证：**从 CSV 直接汇总** vs **从 SQLite 查询汇总**，两边结果应该一致。

### 1) 验证总成本（Actual CostUSD）

- 口径：在筛选条件（project、currency、date range）内，`SUM(CostUSD)`
- 注意：同一天可能多行，这里按行累加是正确的（等价于“当天总额=当天多行求和”）

### 2) 验证天数（Days With Data）

- 口径：在筛选条件内，`CostUSD` 有值的 **不同 UsageDate 个数**
- 这能避免“同一天多行导致天数被重复计数”的问题

### 3) 验证方法（SQLite）

你可以用任意 SQLite 客户端执行（示例：按项目与币种统计）：

```sql
-- Total Actual CostUSD
SELECT COALESCE(SUM(cost_usd), 0) AS total_cost_usd
FROM transactions
WHERE project_name = 'YOUR_PROJECT' AND currency = 'USD';

-- Days With Data (distinct usage_date with non-null cost_usd)
SELECT COUNT(DISTINCT CASE WHEN cost_usd IS NOT NULL THEN usage_date END) AS days_with_data
FROM transactions
WHERE project_name = 'YOUR_PROJECT' AND currency = 'USD';
```

## Vibe Coding + Harness Engineering

本项目已引入严格模式的 Vibe Coding 规范，目标是“快速迭代 + 工程可持续”。

- 全局 Agent 约束：`AGENTS.md`
- Cursor Rules：
  - `.cursor/rules/vibe-harness-core.mdc`
  - `.cursor/rules/vibe-harness-python-web.mdc`
  - `.cursor/rules/commit-quality-gate.mdc`
  - `.cursor/rules/db-migration-policy.mdc`
  - `.cursor/rules/release-readiness.mdc`
  - `.cursor/rules/incident-response.mdc`
- 项目 Skill：
  - `.cursor/skills/vibe-harness-engineering/SKILL.md`
- Playbook：
  - `docs/harness-playbook.md`
  - `docs/templates/pr-description.md`
  - `docs/templates/incident-postmortem.md`

推荐协作节奏：
1. 小步快跑实现功能
2. 立即验证（`pytest` + 必要的手工检查）
3. 明确记录改动原因与验证结果
