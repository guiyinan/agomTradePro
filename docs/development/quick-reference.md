# AgomSAAF 开发快速参考

> **文档版本**: V1.3
> **更新日期**: 2026-02-27
> **目标读者**: 开发人员

---

## 项目信息

| 项目 | AgomSAAF (Agom Strategic Asset Allocation Framework) |
|------|------------------------------------------------------|
| 版本 | V3.4 |
| 状态 | 生产就绪 |
| 完成度 | 98% |
| 业务模块 | 27个 |
| 测试规模 | 1,604 项（2026-02-27 collect-only） |
| Python版本 | 3.11+ |
| Django版本 | 5.x |

---

## 核心命令

### Django 命令

```bash
# 启动开发服务器
agomsaaf/Scripts/python manage.py runserver

# 数据库迁移
agomsaaf/Scripts/python manage.py makemigrations
agomsaaf/Scripts/python manage.py migrate

# 创建超级用户
agomsaaf/Scripts/python manage.py createsuperuser

# 同步宏观数据
agomsaaf/Scripts/python manage.py sync_macro_data

# 初始化配置数据
agomsaaf/Scripts/python manage.py init_asset_codes
agomsaaf/Scripts/python manage.py init_indicators
agomsaaf/Scripts/python manage.py init_thresholds
agomsaaf/Scripts/python manage.py init_weight_config
agomsaaf/Scripts/python manage.py init_prompt_templates
agomsaaf/Scripts/python manage.py init_fee_configs

# Alpha 模块（Qlib 集成）
agomsaaf/Scripts/python manage.py init_qlib_data --check
agomsaaf/Scripts/python manage.py train_qlib_model --name mlp_csi300 --type LGBModel --activate
agomsaaf/Scripts/python manage.py activate_model --model-name mlp_csi300 --version <hash>
agomsaaf/Scripts/python manage.py rollback_model --model-name mlp_csi300
agomsaaf/Scripts/python manage.py list_models
```

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

### 测试命令

```bash
# 运行全部测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/unit/domain/ -v
pytest tests/integration/ -v

# 生成覆盖率报告
pytest tests/ -v --cov=apps --cov-report=html

# 运行特定测试文件
pytest tests/unit/test_regime_services.py -v
```

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

---

## 核心 API 端点

> **注意**: 接口以运行时 OpenAPI 文档为准（`/api/schema/`、`/api/docs/`）。
>
> **路由格式说明**:
> - 统一格式: `/api/{module}/{endpoint}/` (所有 API 端点)
> - 页面路由: `/{module}/dashboard/` 等需要登录
> - 旧格式 (`/api/{module}/api/` 和 `/{module}/api/`) 仍保持向后兼容

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
| `/api/asset-analysis/screen/{asset_type}/` | GET | 资产筛选 |
| `/api/asset-analysis/pool-summary/` | GET | 资产池摘要 |
| `/api/asset-analysis/score/{asset_code}/` | GET | 资产评分 |

### Simulated Trading API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/simulated-trading/accounts/` | POST | 创建模拟账户 |
| `/api/simulated-trading/accounts/{id}/` | GET | 获取账户详情 |
| `/api/simulated-trading/accounts/{id}/positions/` | GET | 获取持仓列表 |
| `/api/simulated-trading/accounts/{id}/trades/` | GET | 获取交易记录 |
| `/api/simulated-trading/accounts/{id}/performance/` | GET | 获取账户绩效 |
| `/api/simulated-trading/manual-trade/` | POST | 手动交易 |

### Realtime Price API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/realtime/prices/` | GET | 查询价格 |
| `/api/realtime/poll/` | POST | 手动触发轮询 |
| `/api/realtime/prices/{code}/` | GET | 查询单个资产价格 |
| `/api/realtime/health/` | GET | 健康检查 |

### Alpha API (AI 选股)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/alpha/scores/` | GET | 获取股票评分 |
| `/api/alpha/providers/status/` | GET | Provider 状态 |

### Factor API (因子管理)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/factor/api/definitions/` | GET | 因子定义列表 (需认证) |
| `/factor/api/configs/` | GET | 因子配置列表 (需认证) |

### Rotation API (板块轮动)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/rotation/api/` | GET | API 操作列表 |
| `/rotation/api/recommendation/` | GET | 轮动建议 |
| `/rotation/api/signals/` | GET | 轮动信号 |
| `/rotation/api/compare/` | POST | 资产比较 |

### Hedge API (对冲策略)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/hedge/api/pairs/` | GET | 对冲配对列表 (需认证) |
| `/hedge/api/alerts/` | GET | 对冲告警 (需认证) |

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
| `/ops/` | Operations Center（替代高频 Admin 入口） |
| `/policy/events/new/` | 新增政策事件 |
| `/policy/rss/manage/new/` | 新增 RSS 源 |
| `/policy/rss/keywords/new/` | 新增关键词规则 |
| `/macro/datasources/new/` | 新增数据源配置 |

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
agomsaaf/Scripts/activate  # Windows
source agomsaaf/bin/activate  # Linux/Mac

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
| `SYSTEM_OVERVIEW.md` | 系统全景概览 |
| `project_structure.md` | 项目结构详解 |
| `module-dependency-graph.md` | 模块依赖关系图 |
| `AgomSAAF_V3.4.md` | 业务需求文档 |
| `CLAUDE.md` | 项目开发规则 |
