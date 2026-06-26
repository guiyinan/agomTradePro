# AgomTradePro 投产代码整改方案（2026-06-26）

## 1. 背景

本方案基于当前 `dev/next-development` 分支的投产可用性扫描，重点评估代码层面仍需补齐的闭环。系统主体能力已经具备，近期已完成账户级自动投顾、RSSHub 权威源初始化、实时 quote fallback 与 VPS 部署验证。本轮整改目标不是重做架构，而是补齐生产运行中最容易造成误判、断链或用户点击后无响应的代码缺口。

整改边界：

- 只覆盖需要代码或模板改动的事项。
- 不把普通文档、测试用示例、表单 placeholder 误判为投产缺口。
- 不改变“不接券商、不真实下单”的业务边界。
- 保持现有 DDD 四层架构约束，Application/Interface 层不得新增 ORM 直连。

## 2. 整改目标

1. 决策链路在生产环境下必须有明确的数据可用性守门，尤其是行情快照、宏观、Regime、Pulse、Alpha readiness。
2. 部署后不依赖人工记忆执行修复命令，关键数据刷新和修复应进入初始化脚本或定时任务。
3. Classic UI 中用户可点击的入口不能停留在“待实现”或无实际效果状态。
4. API 文档 schema 输出稳定，避免 enum 命名碰撞影响 SDK/MCP 使用。
5. 将非投产阻塞的技术债纳入排期，避免和 P0 整改混淆。

## 3. P0 必须整改

### P0-1 决策级 quote snapshot 自动刷新

现状：

- `repair_decision_data_reliability` 已能手工修复 quote freshness。
- 默认 `init_scheduler_defaults` 只初始化宏观同步、估值同步、Workspace 快照，没有独立的决策级 quote snapshot 定时刷新。
- 之前 VPS 上 `data_center_quote_snapshot` 长期停留在旧日期，说明生产不能只依赖手工命令。

涉及文件：

- `apps/data_center/management/commands/repair_decision_data_reliability.py`
- `apps/task_monitor/management/commands/init_scheduler_defaults.py`
- `apps/data_center/application/tasks.py` 或新建同层任务文件
- `apps/data_center/application/use_cases.py`

实施方案：

1. 新增 Celery task：`refresh_decision_quote_snapshots_task`。
2. 默认资产范围使用 `DEFAULT_DECISION_ASSET_CODES`，支持从 kwargs 覆盖 `asset_codes`。
3. 内部调用现有 `SyncQuoteUseCase` 或 `RepairDecisionDataReliabilityUseCase`，不得复制行情源选择逻辑。
4. 新增 management command：`setup_decision_quote_refresh`。
5. 将 `setup_decision_quote_refresh` 加入 `init_scheduler_defaults`。
6. 默认定时建议：
   - 交易日 09:45 刷新盘中 quote。
   - 交易日 15:20 刷新收盘后 quote。
   - 每 6 小时执行 freshness check，只告警不伪造数据。
7. 任务输出必须包含：
   - `status`
   - `asset_codes`
   - `synced_count`
   - `failed_codes`
   - `must_not_use_for_decision`
   - `blocked_reasons`

验收标准：

- 冷启动后 `django_celery_beat_periodictask` 中存在并启用决策 quote refresh 任务。
- 行情源失败时任务返回 degraded/blocked，不写入假价格。
- 任务日志能明确看到每个资产代码的刷新状态。

### P0-2 生产 readiness 增加决策数据守门

现状：

- `/api/ready/` 目前检查 DB、Redis、Celery、宏观/Regime 是否非空、Alpha Workspace 一致性。
- `critical_data` 空表返回 `warning`，`is_healthy()` 将 warning 视为健康。
- 生产环境缺少 quote freshness、market thermometer `must_not_use_for_decision` 等决策可用性检查。

涉及文件：

- `core/health_checks.py`
- `core/settings/production.py`
- `tests/unit` 或 `tests/api` 中新增 readiness 覆盖

实施方案：

1. 增加 `check_decision_data_readiness()`：
   - 检查关键 quote snapshot 是否存在。
   - 检查最新 quote 是否超过最大允许时效。
   - 检查最新 quote 是否 `must_not_use_for_decision=True`。
   - 检查 market thermometer 最新快照是否可用于决策。
2. 增加配置项：
   - `DECISION_READINESS_ASSET_CODES`
   - `DECISION_QUOTE_MAX_AGE_HOURS`
   - `PRODUCTION_STRICT_READINESS`
3. `run_readiness_checks()` 纳入 `decision_data`。
4. `is_healthy()` 在 `PRODUCTION_STRICT_READINESS=True` 时不接受关键项 warning。
5. 本地 development 可保留 warning 通过，避免开发体验被外部数据源阻断。

验收标准：

- 生产配置下，关键 quote 缺失或 stale 时 `/api/ready/` 返回非健康。
- development/test 配置下，外部行情缺失不会无谓阻塞普通开发测试。
- readiness payload 明确说明 blocked code、最新时间、原因。

### P0-3 冷启动/部署脚本纳入决策数据修复

现状：

- `bootstrap_cold_start` 已纳入 scheduler defaults、RSSHub 权威源、决策模型参数、仓位规则。
- 但没有 quote / decision reliability repair 入口。
- 部署后需要人工记得执行 `repair_decision_data_reliability`。

涉及文件：

- `apps/account/management/commands/bootstrap_cold_start.py`
- `docs/development/system_initialization.md`
- `scripts/deploy-vps.ps1` 或 VPS 部署脚本的 postdeploy 阶段

实施方案：

1. `bootstrap_cold_start` 增加参数：
   - `--with-decision-repair`
   - `--decision-asset-codes`
   - `--decision-quote-max-age-hours`
   - `--skip-pulse`
   - `--skip-alpha`
2. 参数启用时调用 `repair_decision_data_reliability`。
3. VPS 部署脚本 postdeploy 阶段在可配置开关下运行一轮非 strict repair。
4. 若 strict repair 失败，部署不应静默成功；非 strict 则输出 degraded 报告。

验收标准：

- 新环境执行一条 bootstrap 命令即可完成基础配置、RSS 源、定时任务和决策数据修复。
- repair 失败时输出结构化原因，不吞异常。
- 部署日志保留 repair 报告摘要。

### P0-4 Classic UI 未完成交互闭环

现状：

- Prompt 管理页存在用户可点击但只弹出“待实现”的功能：
  - `saveChain`
  - `viewLog`
- Share 收益曲线 period 切换调用空函数，只 `console.log`。

涉及文件：

- `core/templates/prompt/manage.html`
- `core/templates/share/partials/performance_chart.html`
- `apps/prompt/interface/*`
- `apps/account/application/query_services.py`
- `apps/account/infrastructure/repositories.py`

实施方案：

1. Prompt 链保存：
   - 接入已有链配置 API；若缺 API，则在 prompt app 补 Application service + Interface endpoint。
   - 表单 JSON 字段保存前做前端和后端校验。
   - 保存成功刷新链配置列表。
2. Prompt 日志详情：
   - 接入日志详情 API。
   - 使用 modal 展示输入、输出、错误、耗时、模板名、时间。
3. Share 收益曲线：
   - period 切换使用真实 portfolio snapshot 数据。
   - 后端已有 `get_portfolio_snapshot_performance_data` 时优先复用。
   - 无数据时显示空状态，不渲染假曲线。

验收标准：

- 页面不再出现“待实现” alert。
- period 切换会更新图表或显示明确空状态。
- API 错误时前端显示可读错误，不只写 console。

## 4. P1 应整改

### P1-1 策略规则编辑器移除硬编码宏观指标

现状：

- `core/templates/strategy/components/rule_editor.html` 中宏观指标列表仍为示例数据。
- 这会和 Data Center 指标目录、单位规则发生漂移。

实施方案：

1. 增加只读 API：列出可用于策略规则的宏观指标。
2. API 来源必须是 Data Center `IndicatorCatalog` 或已有 Application query service。
3. 前端加载失败时保留空状态和重试按钮，不退回硬编码默认值。

验收标准：

- 规则编辑器显示数据库中的指标代码、名称、单位。
- 新增指标后无需改模板即可出现在规则编辑器。

### P1-2 RSSHub 旧路由示例清理

现状：

- UI placeholder、model help_text 和 docstring 仍残留旧的证监会 RSSHub 路由示例。
- 当前权威源已切到可用 RSSHub government route。

实施方案：

1. 将示例统一改为 `/gov/csrc/news/c100028/common_xq_list.shtml`。
2. migration 历史文件不改；只改当前 model help_text、模板、文档。
3. 补一条轻量测试或静态扫描，避免旧示例再次出现于非 migration 文件。

验收标准：

- 管理页和表单不再提示旧路由。
- 旧证监会 RSSHub 路由示例只允许出现在历史 migration 或归档文档中。

### P1-3 OpenAPI enum 命名稳定

现状：

- `python manage.py check --deploy` 在生产配置下仍有 drf-spectacular enum warning。
- 运行不受影响，但 SDK/MCP schema 生成可能不稳定。

实施方案：

1. 在 `SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]` 中补齐冲突 enum：
   - `CommandTypeEnum`
   - category 相关 enum
   - risk_level 相关 enum
   - type 相关 enum
2. 跑 schema 生成或 `check --deploy` 验证 warning 消除。

验收标准：

- 生产配置下 `python manage.py check --deploy` 不再出现 drf-spectacular enum warning。
- API schema diff 稳定，不出现自动编号 enum 名称。

## 5. P2 已实施增强

### P2-1 回测市值加权

现状：市值加权分支退化为等权。

方案：为 Backtest Domain 注入市值数据访问接口，Domain 层只接收已标准化市值，不直接读 ORM 或外部 API。

实现状态：已完成。`StockSelectionBacktestEngine` 支持 `market_cap_weight` / `market_cap_weighted`，通过 `get_market_cap_func` 注入标准化市值；市值缺失、非法或总市值为 0 时降级为等权，避免生成虚假权重。

### P2-2 EventBus 真异步

现状：`publish_async()` 直接调用同步 `publish()`。

方案：Application/Infrastructure 层通过 Celery 或线程池实现异步派发，Domain 层保持纯事件定义和同步接口。

实现状态：已完成。`InMemoryEventBus.publish_async()` 改为线程池派发，新增 `async_max_workers` 配置与 `wait_for_async()` 测试钩子；`stop()` 会等待并关闭 executor，`start()` 可重新创建 executor。

### P2-3 Sentiment 新闻侧接入

现状：情绪指数只分析政策事件，新闻侧为空。

方案：复用 RSS 政策/新闻摄入结果，给 Sentiment 增加新闻项读取接口与权重配置。

实现状态：已完成。Sentiment 日任务通过 application provider 读取 Data Center 市场新闻，优先复用新闻已存情绪分数；缺失分数时按标题和摘要调用现有 `SentimentAnalyzer`，并写入真实 `news_count`。

### P2-4 Alpha 监控长期归档

现状：旧监控缓存会清理，但长期归档未实现。

方案：增加归档表或文件归档策略，并为清理任务补充归档前置步骤。

实现状态：已完成。新增 `AlphaMonitoringArchiveModel` 与迁移，`cleanup_old_metrics` 删除旧 Alpha score cache 前先写入归档摘要，保留 provider/status 分布、模型信息、score 数量、metrics 快照和时间戳。

## 6. 测试计划

### Unit tests

- quote refresh task 在成功、部分失败、全部失败时返回正确结构。
- readiness 在 quote stale、quote missing、`must_not_use_for_decision=True` 时正确降级。
- `bootstrap_cold_start --with-decision-repair` 调用 repair command，参数透传正确。
- Prompt chain 保存参数校验。
- Share performance period 过滤逻辑。

### API tests

- `/api/ready/` 在 strict/non-strict 下行为稳定。
- Prompt chain save/detail endpoint 返回契约稳定。
- Share performance endpoint 支持 `period=1m/3m/6m/1y/all`。
- 策略宏观指标 API 从 Data Center 返回单位和指标名。

### UI tests

- Prompt 管理页保存链配置后刷新列表。
- Prompt 日志详情 modal 能显示详情。
- Share 页切换 period 后图表数据变化或显示空状态。
- 策略规则编辑器加载真实指标。

### Regression

- `python manage.py check --deploy` with production settings。
- 架构 guard：Application/Interface 层不新增 ORM 直连。
- `ruff check`。
- 数据链相关单测：
  - `tests/unit/data_center`
  - `tests/unit/test_repair_decision_data_reliability_command.py`
  - `tests/unit/test_auto_advisor_decision_sheet.py`

## 7. 实施顺序

1. P0-1 + P0-2：先补自动刷新和 readiness 守门，这是投产风险最高的部分。
2. P0-3：把修复链路纳入 bootstrap/deploy，降低运维遗漏概率。
3. P0-4：补用户会点到的 Classic UI 未完成交互。
4. P1-1 + P1-2：清理硬编码指标和 RSS 旧路由提示。
5. P1-3：收敛 OpenAPI schema warning。
6. P2 项已补齐，作为本轮投产整改的增强项一并验证。

## 8. 完成定义

本轮整改完成后应满足：

- 生产部署后不需要人工补跑 quote repair 才能得到新鲜行情。
- `/api/ready/` 能暴露决策数据是否可用，而不是只说明服务进程可用。
- 用户在 Prompt、Share、Strategy 的关键页面不会遇到未实现按钮或静态示例数据。
- OpenAPI schema 不再出现 enum 命名碰撞 warning。
- 所有新增代码通过架构护栏、单测和生产配置检查。

## 9. 执行状态（2026-06-26）

本轮已完成 P0、P1 与 P2 整改项。

已落地内容：

- 决策级 quote snapshot 自动刷新：新增 Celery task、scheduler 初始化命令，并纳入 `init_scheduler_defaults`。
- 生产 readiness 决策守门：新增 quote freshness 与市场温度计可决策性检查，生产 strict 模式下 warning 会阻断健康状态。
- 冷启动/部署脚本：`bootstrap_cold_start` 和 VPS 部署脚本增加 decision repair 参数与 postdeploy 接入。
- Classic UI 闭环：Prompt 链保存/日志详情接入 API；Share 收益曲线 period 切换接入真实接口并支持空状态。
- Strategy 规则编辑器：宏观指标列表改为从 Data Center 指标目录 API 加载。
- RSSHub 路由：当前模板和 model help_text 统一为权威 government route，旧 route 仅保留在历史 migration。
- OpenAPI schema：补齐 enum name overrides，`check --deploy` 不再出现 drf-spectacular enum warning。
- Backtest 市值加权：回测引擎支持注入标准化市值并生成市值权重，缺失数据时显式降级等权。
- EventBus 真异步：`publish_async()` 改为线程池异步派发，补充 executor 生命周期与测试等待接口。
- Sentiment 新闻侧接入：每日情绪指数纳入 Data Center 市场新闻，复用新闻情绪分数或调用现有文本分析。
- Alpha 长期归档：旧监控缓存清理前写入归档摘要表，避免只删不留审计上下文。

验证结果：

- `python manage.py check --deploy`：通过，0 issues。
- `python manage.py makemigrations --check --dry-run`：通过，No changes detected。
- `python scripts/check_architecture_delta.py`：通过，0 boundary violations。
- `ruff check`（本轮涉及 Python 文件）：通过。
- 目标测试：`82 passed`，覆盖 decision repair、health checks、scheduler、data_center use cases、share views、advisor sheet。
- P2 回归测试：`110 passed`，覆盖 backtest 权重、events 异步派发、sentiment 日任务、Alpha 归档清理。
