# API / MCP / SDK 对齐说明（2026-03-14）

## 目的

本文档定义 AgomTradePro 当前对外接入的唯一事实来源，解决以下问题：

- 后端实际 API 路由与 SDK 调用不一致
- MCP 工具仍引用历史路径
- 本地开发与生产环境地址混用
- 本机存在多个 `8000` 进程时，网页、SDK、MCP 命中不同实例

## 一致性规则

1. SDK 与 MCP 只面向 canonical API 路径。
2. canonical API 路径优先使用 `/api/{module}/...`。
3. 预发布阶段已移除 `/{module}/api/...`、`/api/{module}/api/...` 等历史兼容入口。
4. 本地 MCP 与生产 MCP 必须拆成两个 server 名，不允许通过改同一个 server 的 `BASE_URL` 切环境。
5. 本地调试时，`127.0.0.1:8000` 只能保留一套 Django 进程。

## 当前 canonical 路径

| 模块 | canonical API | 说明 |
|------|---------------|------|
| regime | `/api/regime/` | SDK/MCP 使用 V2 current/history/distribution |
| pulse | `/api/pulse/current/` | Pulse canonical 读入口；历史与计算分别使用 `/api/pulse/history/`、`/api/pulse/calculate/` |
| policy | `/api/policy/` | SDK/MCP 不再走 `/policy/...` |
| macro | `/api/macro/` | 历史 module-first 前缀已废弃 |
| account | `/api/account/` | 旧 module-first 前缀已移除 |
| filter | `/api/filter/` | 旧 module-first 前缀已移除 |
| backtest | `/api/backtest/` | 页面旧别名如 `/backtest/list/` 已移除 |
| ai_provider | `/api/ai/` | 页面旧别名已移除 |
| prompt | `/api/prompt/` | 仅保留 canonical |
| strategy | `/api/strategy/` | 仅保留 canonical |
| simulated_trading | `/api/simulated-trading/` | 下划线旧路径已移除 |
| realtime | `/api/realtime/` | root 不再重定向到子路径 |
| system | `/api/system/` | task monitor root 已补齐 |
| events | `/api/events/` | 页面式旧路径 `/events/*` 已移除 |
| dashboard | `/api/dashboard/` | 历史 module-first 前缀仅保留兼容 |
| fund | `/api/fund/` | 读取 `rank/info/nav/holding/style` |
| sector | `/api/sector/` | 当前对外可用入口为 `rotation/` |
| rotation | `/api/rotation/` | recommendation/assets/configs/signals/templates/account-configs |
| hedge | `/api/hedge/` | pairs/alerts/snapshots/actions |
| factor | `/api/factor/` | `all-factors/all-configs/top-stocks/create-portfolio/explain-stock` |
| backtest | `/api/backtest/` | `api/backtests/` 与 `api/run/` 为当前挂载结果 |
| equity | `/api/equity/` | valuation repair config 已对齐 |
| market_data | `/api/market-data/` | MCP 外部市场数据链已打通 |
| audit | `/api/audit/` | 历史页面式前缀已移除 |
| decision_workflow | `/api/decision/...` | `workspace/recommendations/`, `funnel/context/` 已对齐 |

其中 redesign 相关新增 canonical 端点为：

- `/api/regime/navigator/`
- `/api/regime/action/`
- `/api/regime/navigator/history/`
- `/api/pulse/current/`
- `/api/pulse/history/`
- `/api/pulse/calculate/`
- `/api/decision/funnel/context/`

## 统一账户口径（2026-04-01）

- canonical 用户账户接口为 `/api/account/accounts/`
- `/api/simulated-trading/accounts/` 保留为模块原生入口，与 `/api/account/accounts/` 对齐到同一套统一账户实现
- `account_type` 是统一账户属性，当前支持 `real` / `simulated`
- `/api/account/portfolios/*` 保留为旧账本兼容层，不再作为新能力的首选接入面
- SDK/MCP 对外应优先暴露 `account_id`，仅在旧账本导入、观察员授权、历史流水导入场景下继续出现 `portfolio_id`

## 已修复的典型错配

- macro SDK: 历史 module-first 前缀已清理，只保留 `/api/macro/*`
- account SDK: 历史 module-first 前缀已清理，只保留 `/api/account/*`
- filter SDK: 历史 module-first 前缀已清理，只保留 `/api/filter/*`
- backtest SDK: 历史页面/API 别名已清理，只保留 `/api/backtest/*`
- ai provider SDK: 历史 module-first 前缀已清理，只保留 `/api/ai/*`
- prompt SDK: 历史 module-first 前缀已清理，只保留 `/api/prompt/*`
- strategy SDK: 历史 module-first 前缀已清理，只保留 `/api/strategy/*`
- simulated trading SDK: 历史下划线与 module-first 前缀已清理，只保留 `/api/simulated-trading/*`
- events SDK: 历史页面式别名已清理，只保留 `/api/events/*`
- dashboard SDK: 历史页面式别名已清理，只保留 `/api/dashboard/*`
- policy SDK: `/policy/...` -> `/api/policy/...`
- fund SDK: 历史 `funds/*` -> 当前 `rank/info/nav/holding/style`
- sector SDK: 历史 `sectors/*` -> 当前 `rotation/`
- rotation SDK: 历史 module-first 前缀 -> `/api/rotation/*`
- hedge SDK: 历史 module-first 前缀 -> `/api/hedge/*`
- factor SDK: 历史 module-first 前缀 -> `/api/factor/*`
- regime SDK: distribution 不再通过 `history(limit=10000)` 侧算，改为 `/api/regime/distribution/`
- pulse SDK/MCP: 统一走 `/api/pulse/current/`、`/api/pulse/history/`、`/api/pulse/calculate/`，不再从 dashboard JSON 或页面模板提取数据
- decision funnel SDK/MCP: `get_funnel_context()` 对齐 `/api/decision/funnel/context/`，同时支持 `trade_id` 和 `backtest_id`
- decision funnel Step 3 freshness: `/api/decision/funnel/context/` 的 `step3_sectors` 统一返回 `rotation_data_source`、`rotation_is_stale`、`rotation_warning_message`、`rotation_signal_date`，MCP/SDK 文档必须同步说明
- decision funnel MCP convenience summary: `decision_workflow_get_funnel_context` 在保留原始 API payload 的同时，额外返回顶层 `step3_status / step3_data_source / step3_signal_date / step3_warning_message`
- backtest SDK: `results/*` -> 当前 `/api/backtest/backtests/*`
- equity SDK: 历史 `stocks/*` -> 当前 `pool/`、`screen/`、`valuation/{stock_code}/`
- sector SDK: 历史 `sectors/*` / `hot-sectors/` / `compare/` -> 当前 `rotation/` + 本地兼容聚合
- fund SDK: 历史 `funds/*/performance/` -> 当前 `performance/calculate/`
- audit API: 混合 `urls.py` 拆分为 `api_urls.py`，以 canonical `/api/audit/*` 为唯一文档化入口

## 根因总结

本轮排查确认，反复出现的 404/400 主要来自四类系统性问题：

1. SDK 中残留了早期资源型路由设计，如 `stocks/*`、`funds/*`、`sectors/*`，而后端现已演化为 action 型 API（如 `screen/`、`rank/`、`rotation/`、`pool/`）。
2. 个别模块把页面路由和 API 路由混挂在同一入口，导致 `/api/...` 命中重定向或错误 View。
3. DRF action 的路径正则曾使用 `[^/.]+`，会把 `000001.SZ` 这类带点代码挡掉，形成“接口存在但调用 404”的假象。
4. 缺少覆盖 SDK/MCP 路由的自动护栏测试，导致后端改完后，SDK/MCP 仍可长期保留陈旧地址。
5. `audit` 这类页面/API 混合模块如果继续直接挂到 `core` 的 `/api/{module}/`，会出现双前缀畸形路径。

## 新增护栏

- 新增静态回归测试：
  `sdk/tests/test_sdk/test_route_alignment_guardrails.py`
- 该测试会阻止常见历史路由模式重新进入 SDK 模块。

## Regime V2 口径

Rotation、Sector 等依赖当前 regime 的模块，统一使用：

- Python: `apps.regime.application.current_regime.resolve_current_regime`
- HTTP: `/api/regime/current/`

禁止再引用不存在或过时的：

- `apps.regime.application.services.RegimeService`
- `/api/regime/...` 作为 SDK/MCP 默认入口

## MCP 环境拆分

仓库内 `.mcp.json` 只保留本地开发实例：

- `agomtradepro_local -> http://127.0.0.1:8000`

客户端全局配置建议保留两套：

- `agomtradepro_local -> http://127.0.0.1:8000`
- `agomtradepro_prod -> https://your-production-domain.com`

必须同时配置：

- `AGOMTRADEPRO_BASE_URL`
- `AGOMTRADEPRO_API_TOKEN`

`AGOMTRADEPRO_API_BASE_URL` 仅作为环境变量兼容读取，不代表系统继续支持旧 HTTP 路径。

## 本地运行约束

如果本机同时有多套 `manage.py runserver 8000`，会出现：

- 网页看到的是 A 进程
- MCP/SDK 请求命中的是 B 进程
- 日志来自 C 进程

本地回归前必须先确认：

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*runserver*8000*' } | Select-Object ProcessId, CommandLine
```

预期是只剩 1 条。

## 回归基线

2026-03-14 本地已验证以下链路：

- `get_current_regime`
- `get_policy_status`
- `list_macro_indicators`
- `sync_macro_indicator`
- `list_hedge_pairs`
- `list_rotation_assets`
- `list_backtests`
- `get_regime_distribution`
- `get_valuation_repair_config`
- `get_rotation_recommendation`

说明：

- `get_rotation_recommendation` 当前可返回结果，但若本地未配置 Tushare，会退化为 mock 价格数据。
- `list_sectors`、`list_funds` 若返回空列表，优先看本地数据是否为空，而不是先怀疑路由。

## 2026-03-15 MCP 实跑端口与问题清单

端口口径：

- 正式本地回环地址：`http://127.0.0.1:8000`
- 临时隔离排查实例：`http://127.0.0.1:8017`

说明：

- `8017` 仅用于确认“代码是否正确、MCP 是否可调用”，不是长期配置端口。
- 文档、SDK、MCP 默认地址仍应统一指向 `127.0.0.1:8000`。
- 若 `8000` 卡死，可临时起隔离端口做比对，但修复完成后必须回到 `8000` 复验。

2026-03-15 真实 MCP 长尾扫面中，曾确认的失败项：

- `list_config_capabilities`: SDK 对 list 响应误用 `.get(...)`
- `query_events`: SDK 用 `POST`，后端实际为 `GET`
- `get_decision_rhythm_summary`: SDK 允许 `POST`，后端实际为 `GET`；同时后端把 `DecisionScheduler` 误传给 `RhythmManager`
- `alpha_trigger_performance`: SDK 用 `POST`，后端实际为 `GET`
- `asset_pool_summary`: SDK 用 `POST`，后端实际为 `GET`
- `get_sentiment_index` / `get_sentiment_recent`: SDK 用 `POST`，后端实际为 `GET`
- `list_alpha_triggers`: 后端 repository 误依赖失效的 queryset manager 扩展，导致 `500`

还有一批不是路由错配，而是“数据不存在/业务前置条件不满足”：

- `get_ai_provider`
- `decision_workflow_precheck`
- `get_audit_summary`
- `get_task_monitor_status`
- `get_task_monitor_statistics`
- `get_account_rotation_config`
- `get_alpha_stock_scores`

这些项的修复策略应是：

1. 先保证 MCP 不抛底层异常，统一返回结构化失败结果。
2. 再按是否需要种子数据、配置数据或业务参数补齐环境。

## 2026-03-15 写工具回归

回归端口：

- 本地 Django: `http://127.0.0.1:8000`
- MCP base URL: `AGOMTRADEPRO_BASE_URL=http://127.0.0.1:8000`

本轮补齐的问题：

- `audit.run-validation` 之前会把 `ThresholdValidationReport` dataclass 直接塞进 `Response`，导致 `500`；现已改为显式序列化。
- `alpha.upload_scores` 之前总是发送 `model_artifact_hash=""`，而后端把该字段视为“可选但非空”，导致 SDK/MCP 专有的 `400`；现已改为“空值不发送”。
- `publish_event`、`query_events`、`submit_decision_request`、`submit_batch_decision_request` 这类写工具，若业务参数不满足要求，MCP 现在统一返回结构化失败结果，不再抛 `ToolError`。

2026-03-15 实测通过的写工具链路：

- `validate_all_indicators`
- `run_audit_validation`
- `clear_sentiment_cache`
- `reset_decision_quota`
- `create_ai_provider`
- `create_account_rotation_config`（在使用真实存在的 account_id 时）
- `upload_alpha_scores`

关于业务失败口径：

- 如果 payload 缺必填字段，MCP 应返回 `{success: false, error: "...", payload: ...}`，而不是工具执行异常。
- 如果本地数据已存在（例如同一账户已创建过 rotation config），允许返回结构化 `400`，这属于环境状态，不再视为 MCP/SDK 断链。

## 2026-03-15 第二批写工具结果

本轮继续验证并修复了：

- `create_strategy`
- `create_signal`
- `invalidate_signal`
- `create_prompt_template`

对应修复：

- `strategy`：后端序列化器不再把 `created_by` 暴露成外部必填字段，创建时由 `perform_create()` 统一注入当前用户。
- `signal`：SDK 创建请求改为对齐 DRF `POST /api/signal/` 的真实输入结构；后端 `SignalViewSet` 新增 `approve/reject/invalidate` action，并在创建后返回标准输出 serializer。
- `prompt`：`PromptTemplateViewSet.create()` 改为显式返回稳定 JSON，不再把 domain entity 直接交给 DRF 的 `ModelSerializer` 渲染，避免 `datetime.date` / timezone 渲染异常。

当前已知的剩余限制：

- `reset_simulated_account` 在当前后端没有对应的 canonical API endpoint。
- 因此 MCP 现在会返回结构化失败：
  `{success: false, account_id: ..., error: "[404] Resource not found."}`
- 这表示“功能尚未由后端实现”，不再视为 SDK/MCP 路由断链。

## 2026-03-15 第三批写工具结果

本轮继续对剩余长尾写工具做真实回环地址复验，端口仍统一为：

- Django: `http://127.0.0.1:8000`
- MCP/SDK base URL: `AGOMTRADEPRO_BASE_URL=http://127.0.0.1:8000`

已从“系统故障”修复为可用或结构化结果的项：

- `create_beta_gate_config`
  - 后端补齐了 `POST /api/beta-gate/configs/`
  - 同时新增了 `apps/beta_gate/interface/api_urls.py`，把 `/api/beta-gate/` 收口为 API-only canonical root
- `create_policy_event`
  - SDK/MCP 改为兼容后端现行的 `level/title/evidence_url`
  - 后端校验失败改为 `400`，不再误报 `500`
- `run_backtest`
  - `/api/backtest/run/` 改成 DRF API 入口，token 调用不再被 CSRF 拦截
  - 修掉了 SDK 仍发送旧字段 `strategy_name` 的问题，当前按 `name` 传输
  - 修掉了 `run_async` 透传到 `RunBacktestRequest` 导致的 `500`

已从 `500` 降级为明确业务错误的项：

- `create_filter`
  - 当前若本地宏观指标不存在，会返回 `400`
  - 这表示“数据缺失”，不是 SDK/MCP/路由断链
- `create_factor_portfolio`
  - 修掉了缺失 repository import 导致的 `500`
  - 当前若组合配置本身的因子权重和不为 `1.0`，会返回 `400`
- `generate_rotation_signal`
  - 当前若配置名不存在，会返回 `404`
  - 不再把“配置不存在”伪装成 `500`

2026-03-15 当前实测状态：

- `create_beta_gate_config`: 成功
- `create_policy_event`: 成功
- `run_backtest`: 成功
- `create_filter`: 已通过冷启动配置修复
- `create_factor_portfolio`: 已通过冷启动配置修复
- `generate_rotation_signal`: 已通过冷启动配置修复

## 2026-03-15 MCP 冷启动配置

为保证以下写工具在本地空库或半空库环境下可直接验证：

- `create_filter`
- `create_factor_portfolio`
- `generate_rotation_signal`

新增了管理命令：

- `python manage.py bootstrap_mcp_cold_start`

该命令是幂等的，当前会补齐：

- `MCP_TEST_IND`
  - 基于已有 `CN_PMI` 复制生成的测试宏观指标
  - 供 `create_filter` 直接使用
- `动量轮动配置`
  - 从现有 `动量轮动策略` 复制出的 MCP 兼容别名
  - 供 `generate_rotation_signal` 直接使用
- `MCP冷启动动量组合`
  - 只依赖可回退计算的动量/波动/量能因子
  - 供 `create_factor_portfolio` 在无 Tushare 凭证时仍可返回结果
- 最小股票池
  - 向 `equity_stock_info` 写入 10 只示例股票
  - 避免 `factor` 模块因股票池为空而始终返回空结果
- 因子配置修复
  - 自动把历史配置里的负权重规范化为正权重且总和为 `1.0`

实现口径：

- 冷启动默认服务端口仍以 `127.0.0.1:8000` 为准
- 隔离回归时可临时起 `8001/8002/8003`，但仅用于验证最新代码，不是长期配置

2026-03-15 使用隔离实例 `127.0.0.1:8003` 的实测结果：

- `create_filter({'indicator_code': 'MCP_TEST_IND', ...})`: 成功
- `generate_rotation_signal('动量轮动配置')`: 成功
- `create_factor_portfolio('MCP冷启动动量组合')`: 成功
- `create_factor_portfolio('动量精选组合')`: 成功

补充说明：

- `factor` 模块为支持冷启动，已改成”缺单个因子值时跳过该因子，不整组合失败”
- 同时修掉了服务层对已移除字段 `style/size/valuation_score` 的历史访问

---

## 账户账本统一（2026-03-27）

### 背景

原系统存在两套持仓账本：`apps/account`（真实仓，基于 `PortfolioModel / PositionModel / TransactionModel`）和 `apps/simulated_trading`（基于 `SimulatedAccountModel / PositionModel / SimulatedTradeModel`）。本次统一目标：

- 以 `simulated_trading` 数据表为唯一账本，`account_type=real|simulated` 作为唯一区分维度
- 两套外部入口（`/api/account/*` 和 `/api/simulated-trading/*`）底层都改用统一账本服务
- 禁止双写和规则漂移

### 统一后的语义规则

| 规则 | 说明 |
|------|------|
| 真实/模拟是账户属性 | 不是两套持仓系统，仅靠 `account_type` 区分 |
| SDK/MCP 只走 canonical 路径 | `/api/account/*` 或 `/api/simulated-trading/*`，禁用 `account/api/*` |
| 旧 `account/api/*` 仅兼容 | 不作为对外契约，不写入 SDK/MCP 主调用链 |
| 平仓必须写交易账本 | 禁止接口层仅改 `is_closed`，必须通过 close use case |
| 派生字段必须在服务层重算 | 任何持仓更新后，`market_value / unrealized_pnl / unrealized_pnl_pct` 需联动 |

### 已修复 Bug（Phase 1-2，2026-03-27）

1. **真实仓更新派生字段不重算**：`/api/account/positions/{id}/` 已改为统一走 `UnifiedPositionService.update_position()`，派生字段在统一账本服务层重算。
2. **平仓不写交易记录**：`/api/account/positions/{id}/close/` 已改为统一走 `UnifiedPositionService.close_position()`，平仓交易先写入统一账本，再同步 account 投影。
3. **真实仓仍暴露第二条 canonical 读路径**：预上线阶段已取消 `/api/account/unified-positions/`，`/api/account/positions/` 直接成为 canonical 实仓持仓读写入口。

### 已建立接口（Phase 2，2026-03-27）

- **`shared/domain/position_calculations.py`**：纯 Python `recalculate_derived_fields(shares, avg_cost, current_price)`，被 account 与 simulated_trading 共用。
- **`shared/domain/investment_protocols.py`**：`InvestmentAccountRepositoryProtocol` / `PositionLedgerRepositoryProtocol` / `TradeLedgerRepositoryProtocol` 统一协议定义。
- **`apps/simulated_trading/application/unified_position_service.py`**：`UnifiedPositionService` 封装统一账本的增删改查，account_type 无关，自动重算派生字段并记录交易。
- **`/api/account/positions/`**：预上线硬切后的 canonical 实仓持仓入口，读写都直接围绕统一账本执行。

### MCP 路径修正（Phase 2，2026-03-27）

所有 MCP 文件（`account_tools.py`、`server.py`、`rbac.py`）及 MCP 测试文件已将 `account/api/` 全部替换为 `api/account/`，与 SDK 模块路径完全一致。

### 下一步

- 继续压缩 `apps/account` 投影用途，仅保留 account 专属展示字段与过渡期统计支撑
- 将 `transactions` 等剩余 real-account 读写入口进一步收口到同一统一账本服务
