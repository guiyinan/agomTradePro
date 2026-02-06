# AgomSAAF 开发快速参考

> **文档版本**: V1.1
> **更新日期**: 2026-02-06
> **目标读者**: 开发人员

---

## 项目信息

| 项目 | AgomSAAF (Agom Strategic Asset Allocation Framework) |
|------|------------------------------------------------------|
| 版本 | V3.4 |
| 完成度 | 98% |
| 业务模块 | 27个 |
| 测试覆盖 | 263+个测试，100%通过 |
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

### Regime API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/regime/current/` | GET | 获取当前 Regime |
| `/api/regime/history/` | GET | 获取 Regime 历史 |
| `/api/regime/chart-data/` | GET | 获取图表数据 |
| `/api/regime/calculate/` | POST | 触发 Regime 计算 |

### Signal API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/signals/` | GET | 列出所有信号 |
| `/api/signals/` | POST | 创建新信号 |
| `/api/signals/{id}/` | GET | 获取信号详情 |
| `/api/signals/{id}/validate/` | POST | 验证信号 |
| `/api/signals/{id}/invalidate/` | POST | 证伪信号 |

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
| `/api/realtime/prices/` | POST | 手动触发轮询 |
| `/api/realtime/prices/{code}/` | GET | 查询单个资产价格 |
| `/api/realtime/health/` | GET | 健康检查 |

### Alpha API (AI 选股)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/alpha/scores/` | GET | 获取股票评分 |
| `/api/alpha/providers/status/` | GET | Provider 状态 |
| `/api/alpha/models/` | GET | 模型列表 |
| `/api/alpha/models/activate/` | POST | 激活模型 |
| `/api/alpha/models/rollback/` | POST | 回滚模型 |
| `/api/alpha/metrics/` | GET | 监控指标 |
| `/api/alpha/alerts/` | GET | 告警列表 |

### Factor API (因子管理)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/factors/` | GET | 因子列表 |
| `/api/factors/{id}/` | GET | 因子详情 |
| `/api/factors/calculate/` | POST | 计算因子 |
| `/api/factors/analysis/` | GET | 因子分析 |

### Rotation API (板块轮动)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/rotation/signals/` | GET | 轮动信号 |
| `/api/rotation/sectors/` | GET | 板块排名 |
| `/api/rotation/matrix/` | GET | Regime-板块映射 |

### Hedge API (对冲策略)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/hedge/positions/` | GET | 对冲持仓 |
| `/api/hedge/calculate/` | POST | 计算对冲 |
| `/api/hedge/instruments/` | GET | 对冲工具 |

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
| `policy` | 政策事件管理 | ✅ 完整 |
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
| `dashboard` | 仪表盘 | ⚠️ 不完整 |
| `backtest` | 回测引擎 | ✅ 完整 |
| `events` | 事件系统 | ⚠️ 不完整 |

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
