# API / MCP / SDK 对齐说明（2026-03-14）

## 目的

本文档定义 AgomSAAF 当前对外接入的唯一事实来源，解决以下问题：

- 后端实际 API 路由与 SDK 调用不一致
- MCP 工具仍引用历史路径
- 本地开发与生产环境地址混用
- 本机存在多个 `8000` 进程时，网页、SDK、MCP 命中不同实例

## 一致性规则

1. SDK 与 MCP 只面向 canonical API 路径。
2. canonical API 路径优先使用 `/api/{module}/...`。
3. 若系统保留 `/{module}/api/...` 兼容入口，视为页面/历史兼容，不作为 SDK/MCP 契约。
4. 本地 MCP 与生产 MCP 必须拆成两个 server 名，不允许通过改同一个 server 的 `BASE_URL` 切环境。
5. 本地调试时，`127.0.0.1:8000` 只能保留一套 Django 进程。

## 当前 canonical 路径

| 模块 | canonical API | 说明 |
|------|---------------|------|
| regime | `/api/regime/` | SDK/MCP 使用 V2 current/history/distribution |
| policy | `/api/policy/` | SDK/MCP 不再走 `/policy/...` |
| macro | `/api/macro/` | 旧 `/macro/api/` 已废弃 |
| account | `/api/account/` | 旧 `/account/api/` 仅保留兼容 |
| filter | `/api/filter/` | 旧 `/filter/api/` 仅保留兼容 |
| backtest | `/api/backtest/` | 旧 `/backtest/api/` 仅保留兼容 |
| ai_provider | `/api/ai/` | 旧 `/ai/api/` 仅保留兼容 |
| prompt | `/api/prompt/` | 旧 `/prompt/api/` 仅保留兼容 |
| strategy | `/api/strategy/` | 旧 `/strategy/api/` 仅保留兼容 |
| simulated_trading | `/api/simulated-trading/` | 旧 `/simulated-trading/api/` 仅保留兼容 |
| realtime | `/api/realtime/` | root 不再重定向到子路径 |
| system | `/api/system/` | task monitor root 已补齐 |
| events | `/api/events/` | 旧 `/events/api/` 仅保留兼容 |
| dashboard | `/api/dashboard/` | 旧 `/dashboard/api/` 仅保留兼容 |
| fund | `/api/fund/` | 读取 `rank/info/nav/holding/style` |
| sector | `/api/sector/` | 当前对外可用入口为 `rotation/` |
| rotation | `/api/rotation/` | recommendation/assets/configs/signals/templates/account-configs |
| hedge | `/api/hedge/` | pairs/alerts/holdings/actions |
| factor | `/api/factor/` | `all-factors/all-configs/top-stocks/create-portfolio/explain-stock` |
| backtest | `/api/backtest/` | `api/backtests/` 与 `api/run/` 为当前挂载结果 |
| equity | `/api/equity/` | valuation repair config 已对齐 |
| market_data | `/api/market-data/` | MCP 外部市场数据链已打通 |
| audit | `/api/audit/` | `/audit/api/` 仅保留页面/历史兼容 |

## 已修复的典型错配

- macro SDK: `/macro/api/*` -> `/api/macro/*`
- account SDK: `/account/api/*` -> `/api/account/*`
- filter SDK: `/filter/api/*` -> `/api/filter/*`
- backtest SDK: `/backtest/api/*` -> `/api/backtest/*`
- ai provider SDK: `/ai/api/*` -> `/api/ai/*`
- prompt SDK: `/prompt/api/*` -> `/api/prompt/*`
- strategy SDK: `/strategy/api/*` -> `/api/strategy/*`
- simulated trading SDK: `/simulated-trading/api/*` -> `/api/simulated-trading/*`
- events SDK: `/events/api/*` -> `/api/events/*`
- dashboard SDK: `/dashboard/api/*` -> `/api/dashboard/*`
- policy SDK: `/policy/...` -> `/api/policy/...`
- fund SDK: 历史 `funds/*` -> 当前 `rank/info/nav/holding/style`
- sector SDK: 历史 `sectors/*` -> 当前 `rotation/`
- rotation SDK: `rotation/api/*` -> `/api/rotation/*`
- hedge SDK: `hedge/api/*` -> `/api/hedge/*`
- factor SDK: `factor/api/*` -> `/api/factor/*`
- regime SDK: distribution 不再通过 `history(limit=10000)` 侧算，改为 `/api/regime/distribution/`
- backtest SDK: `results/*` -> 当前 `/api/backtest/backtests/*`
- equity SDK: 历史 `stocks/*` -> 当前 `pool/`、`screen/`、`valuation/{stock_code}/`
- sector SDK: 历史 `sectors/*` / `hot-sectors/` / `compare/` -> 当前 `rotation/` + 本地兼容聚合
- fund SDK: 历史 `funds/*/performance/` -> 当前 `performance/calculate/`
- audit API: 混合 `urls.py` 拆分为 `api_urls.py`，canonical `/api/audit/*` 与 legacy `/audit/api/*` 指向同一套视图

## 根因总结

本轮排查确认，反复出现的 404/400 主要来自四类系统性问题：

1. SDK 中残留了早期资源型路由设计，如 `stocks/*`、`funds/*`、`sectors/*`，而后端现已演化为 action 型 API（如 `screen/`、`rank/`、`rotation/`、`pool/`）。
2. 个别模块把页面路由和 API 路由混挂在同一入口，导致 `/api/...` 命中重定向或错误 View。
3. DRF action 的路径正则曾使用 `[^/.]+`，会把 `000001.SZ` 这类带点代码挡掉，形成“接口存在但调用 404”的假象。
4. 缺少覆盖 SDK/MCP 路由的自动护栏测试，导致后端改完后，SDK/MCP 仍可长期保留陈旧地址。
5. `audit` 这类页面/API 混合模块如果继续直接挂到 `core` 的 `/api/{module}/`，会出现 `/api/audit/api/*` 这种双前缀畸形路径。

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

- `agomsaaf_local -> http://127.0.0.1:8000`

客户端全局配置建议保留两套：

- `agomsaaf_local -> http://127.0.0.1:8000`
- `agomsaaf_prod -> http://141.11.211.21:8000`

必须同时配置：

- `AGOMSAAF_BASE_URL`
- `AGOMSAAF_API_TOKEN`

兼容历史调用时，也可额外提供：

- `AGOMSAAF_API_BASE_URL`

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
- MCP base URL: `AGOMSAAF_BASE_URL=http://127.0.0.1:8000`

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
