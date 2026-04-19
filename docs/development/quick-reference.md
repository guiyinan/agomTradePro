# AgomTradePro 开发快速参考

> **文档版本**: V1.9
> **更新日期**: 2026-04-10
> **目标读者**: 开发人员

---

## 项目信息

| 项目 | AgomTradePro (Agom Strategic Asset Allocation Framework) |
|------|------------------------------------------------------|
| 版本 | 0.7.0 |
| 状态 | 生产就绪 |
| 完成度 | 99% |
| 业务模块 | 34个 |
| 测试规模 | 1,700+ 项 |
| Python版本 | 3.11+ |
| Django版本 | 5.x |

---

## 核心命令

### Django 命令

```bash
# 一键安装本地最小运行环境（推荐给首次 clone 用户）
install.bat

# 安装完整开发环境（pytest / Playwright / mypy 等）
install.bat --dev

# 启动开发服务器
agomtradepro/Scripts/python manage.py runserver

# 启动开发菜单
start.bat

# 杀掉所有 Django runserver 进程
powershell -ExecutionPolicy Bypass -File scripts/kill-django.ps1

# 只杀掉指定端口的 Django runserver 进程
powershell -ExecutionPolicy Bypass -File scripts/kill-django.ps1 -Port 8000

# 数据库迁移
agomtradepro/Scripts/python manage.py makemigrations
agomtradepro/Scripts/python manage.py migrate

# 生成本地 .env 并自动补齐安全密钥
agomtradepro/Scripts/python manage.py bootstrap_local_env

# 创建超级用户
agomtradepro/Scripts/python manage.py createsuperuser

# 同步宏观数据
agomtradepro/Scripts/python manage.py sync_macro_data

# 初始化配置数据
agomtradepro/Scripts/python manage.py init_asset_codes
agomtradepro/Scripts/python manage.py init_indicators
agomtradepro/Scripts/python manage.py init_thresholds
agomtradepro/Scripts/python manage.py init_weight_config
agomtradepro/Scripts/python manage.py init_prompt_templates
agomtradepro/Scripts/python manage.py init_fee_configs

# Alpha 模块（Qlib 集成）
agomtradepro/Scripts/python manage.py init_qlib_data --check
agomtradepro/Scripts/python manage.py train_qlib_model --name mlp_csi300 --type LGBModel --activate
agomtradepro/Scripts/python manage.py activate_model --model-name mlp_csi300 --version <hash>
agomtradepro/Scripts/python manage.py rollback_model --model-name mlp_csi300
agomtradepro/Scripts/python manage.py list_models
```

- `start.bat` 选项 `2`（SQLite + Redis + Celery）会在独立的 Django 日志窗口中启动服务，菜单窗口会立即返回。
- `start.bat` 选项 `2`（SQLite + Redis + Celery）会在独立的 Django 日志窗口中启动服务，原菜单窗口会自动退出，避免重复启动。
- Windows 下如通过环境变量覆盖 `DJANGO_LOG_LEVEL`，启动链路会自动清理首尾空格，避免日志配置导致启动失败。
- `install.bat` 默认只安装本地最小运行依赖（`requirements-prod.txt`），不会再强制拉起 Playwright / pytest 等开发工具；如需完整开发栈，显式使用 `install.bat --dev`。
- `scripts/dev.bat` 现在会先执行 `manage.py bootstrap_local_env`，自动创建 `.env` 并补齐 `SECRET_KEY` / `AGOMTRADEPRO_ENCRYPTION_KEY`，避免首次启动出现密钥缺失 warning。
- 开发环境默认强制使用本地内存缓存；即使 `.env` 里保留了 `REDIS_URL`，也不会把登录和页面 API 绑死到 Redis。只有显式设置 `USE_REDIS_CACHE=true` 才会启用开发态 Redis 缓存。
- 本地未启动 Redis 时，登录锁定缓存和 DRF 节流会自动降级为“记录 warning 但不阻断页面/API”，因此 `/ai/`、`/ai/me/`、`/ai/quotas/` 等入口不再因 Redis 缺失直接报 500。
- 从 2026-04-03 起，开发环境 `runserver` 会额外落盘到项目本地 `logs/` 目录，文件名格式为 `django-dev-YYYYMMDD-HHMMSS.log`，每次启动生成一个新文件。
- 开发日志默认按单文件 `20MB` 轮转，保留 `5` 个备份；可用环境变量 `DJANGO_DEV_LOG_MAX_MB` 和 `DJANGO_DEV_LOG_BACKUP_COUNT` 覆盖。

### Streamlit 命令

```bash
# 启动 Streamlit 仪表盘（新交互层）
streamlit run streamlit_app/app.py
```

### Dashboard 切换

```bash
# 在 .env 中启用 Streamlit 仪表盘入口
STREAMLIT_DASHBOARD_ENABLED=True
STREAMLIT_DASHBOARD_URL=http://127.0.0.1:8501
```

- `/dashboard/`：新入口（启用开关后跳转 Streamlit）
- `/dashboard/__internal/legacy/`：Django 旧版内部调试入口（仅开发环境）

### 后台入口模型

- `/settings/`：设置中心，统一承接配置类入口
- `/admin-console/`：管理控制台，统一承接管理员日常操作与运维入口
- `/admin/`：Django Admin，仅保留给底层模型和未产品化功能
- 顶部导航分组：`研究`（宏观环境 / 策略研究 / 智能模块）、`执行`（决策工作台 / 账户与执行）、`平台`（设置 / 数据源 / AI 与自动化 / 运行校验）、`帮助`（文档 / API）、`运维`（管理员与值守）

### Celery 命令

```bash
# 启动 Celery Worker（默认队列）
celery -A core worker -l info

# 启动 Celery Beat（定时任务）
celery -A core beat -l info

# Qlib 专用 Worker（Alpha 模块）
celery -A core worker -l info -Q qlib_train --max-tasks-per-child=1
celery -A core worker -l info -Q qlib_infer --max-tasks-per-child=10
```

- 从 2026-04-07 起，Celery 独立日志会落盘到项目本地 `logs/` 目录：
  - Worker: `logs/celery-worker.log`
  - Beat: `logs/celery-beat.log`
- Celery 日志默认按单文件 `20MB` 轮转，保留 `5` 个备份；可用环境变量 `CELERY_LOG_MAX_MB` 和 `CELERY_LOG_BACKUP_COUNT` 覆盖。
- 开发环境的 Celery Beat 现在固定使用 `django_celery_beat.schedulers.DatabaseScheduler`，本地启动链会在 Beat 启动前执行 `manage.py setup_macro_daily_sync --hour 8 --minute 5`，统一对齐 `daily-sync-and-calculate`、`check-data-freshness`、`high-frequency-generate-signal`、`high-frequency-recalculate-regime` 这 4 条关键数据链任务。

### 测试命令

```bash
# 运行全部测试
pytest tests/ -v

# 运行本地全量回归入口（默认包含 preflight + backend + browser + RC 子集）
python scripts/run_full_regression.py

# 只跑测试基础设施和浏览器矩阵
python scripts/run_full_regression.py --stages preflight,browser

# 运行特定模块测试
pytest tests/unit/domain/ -v
pytest tests/integration/ -v

# 运行综合 UAT 回归（显式管理 Django live server，拒绝整组 skip 假绿）
python tests/uat/run_uat.py

# 单独跑 Playwright smoke / UAT（helper 会起服务、传 --base-url、校验最小执行数）
python scripts/run_live_server_pytest.py --suite-name smoke --port 8010 --base-url http://127.0.0.1:8010 --junitxml reports/quality/local-smoke.xml --min-tests 10 -- tests/playwright/tests/smoke -q --browser chromium
python scripts/run_live_server_pytest.py --suite-name uat --port 8011 --base-url http://127.0.0.1:8011 --junitxml reports/quality/local-uat.xml --min-tests 20 -- tests/playwright/tests/uat -q --browser chromium

# 生成覆盖率报告
pytest tests/ -v --cov=apps --cov-report=html

# 运行特定测试文件
pytest tests/unit/test_regime_services.py -v
```

- `scripts/run_live_server_pytest.py` 会在执行前检查 `/account/login/` 可达，CI/本地严格模式下服务不可达直接失败，不再把整组 Playwright 用例 skip 成假绿。
- `scripts/run_full_regression.py` 默认使用 `core.settings.development_sqlite` 和独立端口 `8010`，避免误打正在开发的 `8000` 服务。

```powershell
# 自动化调试日志 API 端到端回归（含鉴权/增量/导出）
pwsh -File scripts/e2e_debug_log_api.ps1
```

### 代码质量检查

```bash
# 格式化代码
black .
isort .

# Lint 检查
ruff check .

# 类型检查
mypy apps/ --strict
```

### API 改动同步检查

如果本次提交修改了 API 路径、参数、响应字段、状态码或 fallback 语义，合入前额外执行：

```bash
# 重新生成 OpenAPI 产物
python manage.py spectacular --file schema.yml
python manage.py spectacular --file docs/testing/api/openapi.yaml
python manage.py spectacular --format openapi-json --file docs/testing/api/openapi.json

# 验证文档 / MCP / SDK 对齐
pytest -q tests/unit/test_docs_route_alignment.py
pytest sdk/tests/test_mcp/test_tool_execution.py -q

# 如果改了 SDK 契约或 canonical 路径，再执行
pytest sdk/tests/test_sdk/test_extended_module_endpoints.py -q
```

- 必须同步：API 实现、SDK、MCP、OpenAPI、用户提示文案。
- 详细规则见 `docs/development/engineering-guardrails.md` 的“API 改动同步门禁”。

---

## 核心 API 端点

> **注意**: 接口以运行时 OpenAPI 文档为准（`/api/schema/`、`/api/docs/`）。
>
> **路由格式说明**:
> - 统一格式: `/api/{module}/{endpoint}/` (所有 API 端点)
> - 页面路由: `/{module}/dashboard/` 等需要登录
> - 旧格式 (`/api/{module}/api/` 和 `/{module}/api/`) 仍保持向后兼容
>
> **Schema 生成说明**:
> - `python manage.py spectacular --file schema.yml` 只输出规范化 `/api/*` 端点
> - 枚举组件名已做稳定映射，避免生成带哈希后缀的临时 enum 名

### Regime API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/regime/` | GET | 获取 Regime 列表 (需认证) |
| `/api/regime/{id}/` | GET | 获取指定 Regime 详情 (需认证) |
| `/api/regime/health/` | GET | 健康检查 (需认证) |
| `/api/regime/current/` | GET | 获取当前 Regime (需认证) |
| `/api/regime/calculate/` | POST | 计算 Regime (需认证) |
| `/api/regime/history/` | GET | 获取历史记录 (需认证) |
| `/api/regime/distribution/` | GET | 获取分布统计 (需认证) |
| `/regime/dashboard/` | GET | Regime 仪表盘页面 |

### Policy Workbench API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/policy/workbench/summary/` | GET | 工作台概览 (需认证) |
| `/api/policy/workbench/items/` | GET | 事件列表 (需认证) |
| `/api/policy/workbench/items/{id}/approve/` | POST | 审核通过 (需认证) |
| `/api/policy/workbench/items/{id}/reject/` | POST | 审核拒绝 (需认证) |
| `/api/policy/workbench/items/{id}/rollback/` | POST | 回滚生效 (需认证) |
| `/api/policy/workbench/items/{id}/override/` | POST | 临时豁免 (需认证) |
| `/api/policy/sentiment-gate/state/` | GET | 热点情绪闸门状态 (需认证) |
| `/api/policy/ingestion-config/` | GET/PUT | 摄入配置 (需认证) |
| `/api/policy/sentiment-gate-config/` | GET/PUT | 闸门配置 (需认证) |
| `/policy/workbench/` | GET | 工作台页面 |

### Signal API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/signal/` | GET/POST | 列出/创建信号 (需认证) |
| `/api/signal/{id}/` | GET | 获取信号详情 (需认证) |
| `/api/signal/health/` | GET | 健康检查 (需认证) |
| `/signal/manage/` | GET | 信号管理页面 |

### Account API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/account/profile/` | GET | 获取账户配置 (需认证) |
| `/api/account/health/` | GET | 账户模块健康检查 (需认证) |
| `/api/account/volatility/` | GET | 获取当前活跃组合波动率视图数据 (需认证) |
| `/api/account/sizing-context/` | GET | 获取宏观仓位系数上下文与建议乘数，支持 `portfolio_id` 查询参数 (需认证) |

### Sentiment API (舆情分析)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/sentiment/analyze/` | POST | 分析文本情感 (需认证) |
| `/api/sentiment/batch-analyze/` | POST | 批量分析 (需认证) |
| `/api/sentiment/index/` | GET | 获取情绪指数 (需认证) |
| `/api/sentiment/health/` | GET | 健康检查 (需认证) |
| `/sentiment/dashboard/` | GET | 舆情仪表盘页面 |

### Asset Analysis API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/asset-analysis/screen/{asset_type}/` | POST | 资产池筛选 |
| `/api/asset-analysis/pool-summary/` | GET | 资产池摘要 |
| `/api/asset-analysis/current-weight/` | GET | 当前生效权重 |
| `/api/asset-analysis/score/{asset_code}/` | GET | 资产评分 |

### Simulated Trading API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/account/accounts/` | GET/POST | 获取当前登录用户的统一账户列表 / 创建账户 |
| `/api/account/accounts/{id}/` | GET | 获取当前登录用户名下账户详情 |
| `/api/account/accounts/{id}/positions/` | GET | 获取当前登录用户名下账户持仓列表 |
| `/api/account/accounts/{id}/trades/` | GET | 获取当前登录用户名下账户交易记录 |
| `/api/account/accounts/{id}/performance/` | GET | 获取当前登录用户名下账户绩效 |
| `/api/simulated-trading/manual-trade/` | POST | 手动交易 |

### Setup Wizard API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/setup/api/password-strength/` | GET | 安装向导密码强度检查（页面当前使用路径） |
| `/api/setup/password-strength/` | GET | 安装向导密码强度检查兼容入口 |

### Realtime Price API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/realtime/prices/` | GET | 查询价格 |
| `/api/realtime/poll/` | POST | 手动触发轮询 |
| `/api/realtime/prices/{code}/` | GET | 查询单个资产价格 |
| `/api/realtime/health/` | GET | 健康检查 |

### Equity Technical API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/equity/technical/{code}/` | GET | 返回个股日/周/月 K 线、MA5/20/60、MACD 以及最近金叉死叉信号 |
| `/api/equity/intraday/{code}/` | GET | 返回个股最新交易日的 1 分钟分时价格、均价与成交量 |

- Equity 技术图表接口中的分时 `timestamp` 统一返回带时区的 ISO 8601 时间；备用分时源仅在通过价格一致性校验后才会启用。

### Alpha API (AI 选股)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/alpha/scores/` | GET | 获取股票评分 |
| `/api/alpha/providers/status/` | GET | Provider 状态 |

### Data Center API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/data-center/providers/` | GET/POST | 列出或创建统一 Provider 配置 |
| `/api/data-center/providers/{id}/` | GET/PATCH/DELETE | 获取、更新或删除 Provider |
| `/api/data-center/providers/{id}/test/` | POST | 执行 Provider 连通性探针 |
| `/api/data-center/providers/status/` | GET | 获取 Provider 运行状态 |
| `/api/data-center/assets/resolve/` | GET | 解析资产代码到 canonical code |
| `/api/data-center/macro/series/` | GET | 查询宏观时序 |
| `/api/data-center/prices/history/` | GET | 查询历史价格 |
| `/api/data-center/prices/quotes/` | GET | 查询最新行情快照 |
| `/api/data-center/funds/nav/` | GET | 查询基金净值时序 |
| `/api/data-center/financials/` | GET | 查询财务事实表 |
| `/api/data-center/valuations/` | GET | 查询估值事实表 |
| `/api/data-center/sectors/constituents/` | GET | 查询板块成分 |
| `/api/data-center/news/` | GET | 查询新闻事实表 |
| `/api/data-center/capital-flows/` | GET | 查询资金流事实表 |
| `/api/data-center/sync/macro/` | POST | 同步宏观事实到中台 |
| `/api/data-center/sync/prices/` | POST | 同步历史价格到中台 |
| `/api/data-center/sync/quotes/` | POST | 同步最新行情快照到中台 |
| `/api/data-center/sync/funds/nav/` | POST | 同步基金净值到中台 |
| `/api/data-center/sync/financials/` | POST | 同步财务事实到中台 |
| `/api/data-center/sync/valuations/` | POST | 同步估值事实到中台 |
| `/api/data-center/sync/sectors/constituents/` | POST | 同步板块成分到中台 |
| `/api/data-center/sync/news/` | POST | 同步新闻到中台 |
| `/api/data-center/sync/capital-flows/` | POST | 同步资金流到中台 |

### 路由兼容与快捷入口

- 页面根路径快捷入口：`/account/ -> /account/login/`、`/equity/ -> /equity/screen/`、`/fund/ -> /fund/dashboard/`、`/prompt/ -> /prompt/manage/`
- `GET /api/filter/` 返回可发现的 API 根信息；真正执行滤波仍使用 `POST /api/filter/`
- `/api/macro/indicator-data/` 同时接受 `code` 与 `indicator_code` 查询参数
- `/api/pulse/current/` 在无历史快照或最新快照已过期/不可靠时，会尝试按需重算当前 Pulse
- Setup Wizard 密码强度检查同时支持 `/setup/api/password-strength/` 与 `/api/setup/password-strength/`

### 数据源中台提示

- Tushare 第三方代理地址统一配置在 `ProviderConfigModel.http_url`
- 运行时会自动下发到 `pro._DataApi__http_url`
- 不需要在 `equity / backtest / data_center / fund / sector / factor / hedge` 分别配置
- QMT 行情源统一配置在 `ProviderConfigModel.source_type=qmt`
- `extra_config` 可承载 `client_path`、`data_dir`、`dividend_type` 等本地 XtQuant 参数
- `data_center` registry 会按优先级注册可用 Provider；旧 market-data API 前缀已下线

### Factor API (因子管理)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/factor/definitions/` | GET | 因子定义列表 (需认证) |
| `/api/factor/configs/` | GET | 因子配置列表 (需认证) |

### Rotation API (板块轮动)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/rotation/` | GET | API 操作列表 |
| `/api/rotation/assets/` | GET | 资产类别 |
| `/api/rotation/signals/` | GET | 轮动信号 |
| `/api/rotation/account-configs/` | GET | 账户级轮动配置 |

### Hedge API (对冲策略)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/hedge/pairs/` | GET | 对冲配对列表 (需认证) |
| `/api/hedge/alerts/` | GET | 对冲告警 (需认证) |

### Dashboard v1 API (Streamlit)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/` | GET | Dashboard API 根路径（端点清单） |
| `/api/dashboard/v1/summary/` | GET | 仪表盘摘要 |
| `/api/dashboard/v1/regime-quadrant/` | GET | Regime 象限数据 |
| `/api/dashboard/v1/equity-curve/` | GET | 资金曲线数据 |
| `/api/dashboard/v1/signal-status/` | GET | 信号状态数据 |
| `/api/dashboard/v1/*` | GET | dashboard canonical 路径 |

### Operations UI

| 页面 | 说明 |
|------|------|
| `/settings/` | Settings Center（替代高频 Admin 入口） |
| `/admin-console/` | 管理控制台（用户 / Token / 日志 / 文档 / Django Admin 统一入口） |
| `/settings/mcp-tools/` | MCP 工具治理页（设置域下的系统级能力开关与同步入口） |
| `/ai/` | AI Provider 配置页（管理员系统级 Provider、预算与日志治理入口） |
| `/ai/me/` | 我的 AI Provider 页（用户个人 Provider 优先级与兜底额度查看入口） |
| `/ai/quotas/` | 用户系统兜底额度页（管理员批量/单用户额度管理入口） |
| `/prompt/manage/` | Prompt 模板管理页（设置域下的模板 / 链 / 执行测试入口） |
| `/admin/server-logs/` | 服务端日志值守页（管理控制台运维入口） |
| `/admin/docs/manage/` | 文档管理页（管理控制台内容运维入口） |
| `/admin/docs/edit/` | 文档编辑页（管理控制台内容编辑入口） |
| `/policy/rss/sources/` | RSS 源运维页（政策摄入链路配置入口） |
| `/share/manage/` | 账户分享运营页（账户与执行链路中的分享管理入口） |
| `/share/manage/disclaimer/` | 分享页风险提示配置（公开分享链路的系统文案入口） |
| `/policy/events/new/` | 新增政策事件 |
| `/policy/rss/sources/new/` | 新增 RSS 源 |
| `/policy/rss/keywords/new/` | 新增关键词规则 |
| `/data-center/providers/` | 数据中台 Provider 配置页 |
| `/data-center/monitor/` | 数据中台运行状态页 |

---

## Celery 定时任务

| 任务名称 | 调度时间 | 说明 |
|---------|---------|------|
| `daily-sync-and-calculate` | 每天 8:00 | 同步宏观数据并计算 Regime |
| `daily-signal-invalidation` | 每天 2:00 | 检查信号证伪条件 |
| `hourly-stop-loss-check` | 每小时 | 检查止损触发 |
| `daily-volatility-check` | 每天 1:00 | 检查波动率并调整 |
| `daily-sentiment-index` | 每天 23:00 | 计算情感指数 |
| `simulated-trading-daily` | 工作日 15:30 | 模拟盘自动交易 |
| `simulated-trading-update-prices` | 工作日 16:00 | 更新持仓价格 |
| `simulated-trading-calculate-performance` | 周日 2:00 | 计算绩效 |
| `simulated-trading-cleanup` | 周日 3:00 | 清理不活跃账户 |
| `simulated-trading-summary` | 工作日 17:00 | 发送绩效摘要 |
| `realtime-update-after-close` | 工作日 16:30 | 收盘后批量更新价格 |

### Policy Workbench 定时任务

| 任务名称 | 调度时间 | 说明 |
|---------|---------|------|
| `fetch_rss_sources` | 每 6 小时 | RSS 源抓取 |
| `auto_assign_pending_audits` | 每 15 分钟 | 自动分配审核 |
| `monitor_sla_exceeded` | 每 10 分钟 | SLA 超时监控 |
| `refresh_gate_constraints` | 每 5 分钟 | 刷新闸门约束 |
| `trigger_signal_reevaluation` | 按需 | 政策档位变化时信号重评 |

### Alpha 模块定时任务

| 任务名称 | 调度时间 | 说明 |
|---------|---------|------|
| `evaluate_alerts` | 每分钟 | 评估告警规则 |
| `update_provider_metrics` | 每 5 分钟 | 更新 Provider 指标 |
| `calculate_ic_drift` | 每周 | 计算 IC 漂移 |
| `check_queue_lag` | 每分钟 | 检查队列积压 |
| `generate_daily_report` | 每天 | 生成每日报告 |
| `cleanup_old_metrics` | 每周 | 清理旧数据 |

---

## 模块速查表

### 核心引擎模块 (5个)

| 模块 | 职责 | 状态 |
|------|------|------|
| `macro` | 宏观数据采集 | ✅ 完整 |
| `regime` | Regime 判定 | ✅ 完整 |
| `policy` | 政策事件管理 + 工作台 | ✅ 完整 |
| `signal` | 投资信号管理 | ✅ 完整 |
| `filter` | HP/Kalman 滤波 | ✅ 完整 |

### 资产分析模块 (5个)

| 模块 | 职责 | 状态 |
|------|------|------|
| `asset_analysis` | 通用资产分析框架 | ✅ 完整 |
| `equity` | 个股分析 | ✅ 完整 |
| `fund` | 基金分析 | ✅ 完整 |
| `sector` | 板块分析 | ✅ 完整 |
| `sentiment` | 舆情情感分析 | ✅ 完整 |

### AI 智能模块 (7个)

| 模块 | 职责 | 状态 |
|------|------|------|
| `alpha` | Alpha 选股信号（Qlib 集成） | ✅ 完整 |
| `alpha_trigger` | Alpha 离散触发 | ✅ 完整 |
| `beta_gate` | Beta 闸门 | ✅ 完整 |
| `decision_rhythm` | 决策频率约束 | ✅ 完整 |
| `factor` | 因子管理 | ✅ 完整 |
| `rotation` | 板块轮动 | ✅ 完整 |
| `hedge` | 对冲策略 | ✅ 完整 |

### 风控与账户模块 (5个)

| 模块 | 职责 | 状态 |
|------|------|------|
| `account` | 账户与持仓管理 | ✅ 完整 |
| `audit` | 事后审计 | ✅ 完整 |
| `simulated_trading` | 模拟盘自动交易 | ✅ 完整 |
| `realtime` | 实时价格监控 | ✅ 完整 |
| `strategy` | 策略系统 | ✅ 完整 |

### 工具模块 (5个)

| 模块 | 职责 | 状态 |
|------|------|------|
| `ai_provider` | AI 服务商管理 | ✅ 完整 |
| `prompt` | AI Prompt 模板 | ✅ 完整 |
| `dashboard` | 仪表盘 | ✅ Streamlit 集成 |
| `backtest` | 回测引擎 | ✅ 完整 |
| `events` | 事件系统 | ✅ 完整 |

---

## 配置说明

### 环境变量 (.env)

```bash
# 数据库
DATABASE_URL=sqlite:///db.sqlite3

# Redis
REDIS_URL=redis://localhost:6379/0

# 数据源 API 密钥
TUSHARE_TOKEN=your_token_here
FRED_API_KEY=

# Django
SECRET_KEY=
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# 告警
SLACK_WEBHOOK_URL=
ALERT_EMAIL=
```

### 虚拟环境

```bash
# 激活虚拟环境
agomtradepro/Scripts/activate  # Windows
source agomtradepro/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
```

---

## 四层架构约束

### Domain 层 (`apps/*/domain/`)
```
✅ 允许：Python 标准库、dataclasses、typing、enum、abc
❌ 禁止：django.*、pandas、numpy、requests、任何外部库
```

### Application 层 (`apps/*/application/`)
```
✅ 允许：Domain 层、Protocol 接口
❌ 禁止：直接导入 ORM Model、直接调用外部 API
```

### Infrastructure 层 (`apps/*/infrastructure/`)
```
✅ 允许：Django ORM、Pandas、外部 API 客户端
```

### Interface 层 (`apps/*/interface/`)
```
✅ 允许：输入验证、输出格式化
❌ 禁止：业务逻辑
```

---

## 数据模型速查

### 核心模型

| 模型 | 表名 | 说明 |
|------|------|------|
| `MacroIndicatorModel` | `macro_macroindicator` | 宏观数据 |
| `RegimeHistoryModel` | `regime_regimehistory` | Regime 历史 |
| `PolicyEventModel` | `policy_policyevent` | 政策事件 |
| `InvestmentSignalModel` | `signal_investmentsignal` | 投资信号 |
| `BacktestResultModel` | `backtest_backtestresult` | 回测结果 |
| `SimulatedAccountModel` | `simulated_trading_simulatedaccount` | 模拟账户 |
| `RealtimePriceModel` | `realtime_realtimeprice` | 实时价格 |

### shared 模型

| 模型 | 表名 | 说明 |
|------|------|------|
| `RiskParameterConfigModel` | `shared_riskparameterconfig` | 风险参数配置 |
| `RegimeEligibilityConfigModel` | `shared_regimeeligibilityconfig` | 准入矩阵配置 |
| `InvestmentRuleModel` | `shared_investmentrule` | 投资规则 |

---

## 常见问题

### Q: 如何添加新的宏观数据指标？

1. 在 `apps/macro/domain/entities.py` 添加指标定义
2. 在 `apps/macro/infrastructure/adapters/fetchers/` 添加 fetcher
3. 在 `apps/macro/infrastructure/adapters/akshare_adapter.py` 注册 fetcher
4. 运行 `python manage.py init_indicators` 初始化配置

### Q: 如何修改 Regime 计算参数？

编辑 `apps/regime/domain/entities.py` 中的 `KalmanFilterParams` 或 `RegimeConfig`

### Q: 如何添加新的 Celery 定时任务？

1. 在 `apps/{module}/application/tasks.py` 定义任务
2. 在 `core/settings/base.py` 的 `CELERY_BEAT_SCHEDULE` 注册任务
3. 重启 Celery Beat

### Q: 如何查看当前系统状态？

- 访问 `/admin/` Django Admin 后台
- 访问 `/api/regime/current/` 获取当前 Regime
- 访问 `/api/realtime/health/` 检查实时数据服务状态

---

## 相关文档

| 文档 | 说明 |
|------|------|
| `governance/SYSTEM_BASELINE.md` | 系统基线（单一叙事来源） |
| `SYSTEM_SPECIFICATION.md` | 系统完整说明书 |
| `project_structure.md` | 项目结构详解 |
| `module-dependency-graph.md` | 模块依赖关系图 |
| `AgomTradePro_V3.4.md` | 业务需求文档 |
| `CLAUDE.md` | 项目开发规则 |
