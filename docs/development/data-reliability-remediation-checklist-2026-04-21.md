# 数据可靠性修复清单（2026-04-21）

> 适用范围：本地 `start.bat` 选项 2 启动链路、Dashboard、API、SDK、MCP
> 背景：2026-04-21 本地 UAT / E2E / MCP live 验证确认“流程可跑通”，但当前数据链仍不足以支撑真实投资决策。
> 补充更新：2026-04-21 已完成 P0 第一批落地，见“已落地状态”。

## 已落地状态

### REL-001 已落地

- `GetActionRecommendationUseCase` 的 stale Pulse 决策阻断链路已处于生效状态
- `Regime action API` 已返回：
  - `must_not_use_for_decision`
  - `blocked_reason`
  - `blocked_code`
  - `pulse_is_reliable`
  - `stale_indicator_codes`
- 本轮补充了 SDK / MCP 侧文档说明与透传测试，避免 Agent 把 blocked contract 误读为正常建议
- `Pulse current API` 作为诊断读取端点，现也返回只读可靠性 contract：
  - `must_not_use_for_decision`
  - `blocked_reason`
  - `is_stale`
  - `stale_indicator_codes`
- 2026-04-21 live SDK / MCP 复测确认：当前 Pulse 快照 `data_source="stale"`、`is_reliable=false`，且 `CN_PMI`、`000300.SH` 被标记为 stale，仅可诊断，不可决策

### REL-002 已落地（第一阶段）

- `/api/data-center/prices/quotes/` 已新增 freshness 元数据：
  - `age_minutes`
  - `is_stale`
  - `freshness_status`
  - `must_not_use_for_decision`
  - `blocked_reason`
  - `contract`
- 该端点已支持：
  - `strict_freshness`
  - `max_age_hours`
- `strict_freshness=true` 且最新行情超过 freshness 阈值时，接口现返回 `409`
- SDK / MCP 已支持透传 `strict_freshness` 与 `max_age_hours`

### REL-003 已落地（最终状态）

- `/api/data-center/macro/series/` 已彻底移除 legacy fallback
- 运行时只读取 Data Center 宏观事实表
- 当标准事实缺失或规则缺失时，接口直接返回 blocked / degraded contract，不再拼接 legacy 宏观序列
- 宏观返回已补充 freshness / decision contract：
  - `data_source`
  - `freshness_status`
  - `decision_grade`
  - `latest_reporting_period`
  - `latest_published_at`
  - `latest_quality`
  - `contract`

### REL-004 已落地（第一阶段）

- Provider connection test 与部分 sync 用例已回写 telemetry 到 `ProviderConfig.extra_config`
- 当前已覆盖：
  - `RunProviderConnectionTestUseCase`
  - `SyncMacroUseCase`
  - `SyncPriceUseCase`
  - `SyncQuoteUseCase`
- `/api/data-center/providers/status/` 现在会优先用 live registry 状态，并在 live snapshot 缺少 `last_success_at` / `avg_latency_ms` 时，用持久化 telemetry 回补

### REL-005 / REL-006 已落地（第二阶段）

- Dashboard Alpha 的 scoped cache 追踪已补齐：
  - `verified_scope_hash`
  - `verified_asof_date`
  - `trade_date_adjusted`
- 2026-04-21 live smoke 已覆盖 API / SDK / MCP 三入口：
  - `portfolio_id=366`
  - `pool_mode=price_covered`
  - `scope_hash=4104d1d15fbd0ab9`
  - `scope_verification_status="verified"`
  - `derived_from_broader_cache=false`
  - `freshness_status="trade_date_adjusted"`
  - `result_age_days=1`
  - `verified_asof_date="2026-04-20"`
  - `recommendation_ready=false`
  - `must_not_use_for_decision=true`
- 当前结论：账户池 scoped Alpha 数据链已打通，但 2026-04-21 请求被调整到 2026-04-20，系统正确阻断为“研究结果，不可用于决策”

### REL-007 已落地（第三阶段）

- 新增决策数据可靠性修复流水线：
  - 管理命令：`python manage.py repair_decision_data_reliability --target-date 2026-04-21 --portfolio-id 366 --strict`
  - API：`POST /api/data-center/decision-reliability/repair/`
  - SDK：`client.data_center.repair_decision_data_reliability(...)`
  - MCP：`data_center_repair_decision_data_reliability`
- 修复流水线按顺序执行：
  - 幂等引导 `AKShare Public` provider
  - 用 Data Center sync 补 `CN_PMI` 等关键宏观事实
  - 用 Data Center sync 持久化刷新 `510300.SH` / `000300.SH` quote 与 price bar
  - 重算 Pulse 并复验 `is_reliable` 与 stale indicators
  - 尝试刷新 Qlib 数据并对 `portfolio_id=366` 的 scoped Alpha 重新推理
- Pulse 数据提供者已优先读取 Data Center 标准事实表与价格表，旧 macro 表仅作为 fallback 诊断来源
- 该流水线不会把 legacy/stale/adjusted 结果伪装为 actionable；若上游未发布当日数据，最终报告保持 `must_not_use_for_decision=true`

## 目标

把本轮确认的 4 个问题拆成可执行修复项，并明确先后顺序：

1. `macro freshness`
2. `quote freshness`
3. `pulse stale guard`
4. `dashboard alpha readiness`

本清单的优先级原则不是“哪里最容易改”，而是“哪里最容易误导用户做出错误决策”。

## 当前阻塞事实

截至 2026-04-21，本地 live 验证已确认以下事实：

- `sdk_current_regime` 返回 `observed_at=2026-04-21`，但 `growth_value=null`、`inflation_value=null`，`confidence=0.3741750180670613`
- `sdk_pulse_current` 返回 `data_source="stale"`、`is_reliable=false`，且 `CN_PMI`、`000300.SH` 已进入 stale 状态
- 上一轮 live SDK 检查中，`510300.SH` 的“最新行情”时间戳仍停留在 `2026-04-06T08:06:25+00:00`
- 历史问题曾出现 `CN_PMI` 回退到 legacy 老数据；当前运行时已禁止该行为
- 上一轮 live SDK 检查中，Data Center provider 连接测试成功，但 `last_success_at`、`avg_latency_ms` 仍为空
- 最新 live API / SDK / MCP 检查中，Dashboard Alpha 对 `portfolio_id=366` 返回：
  - `recommendation_ready=false`
  - `must_not_treat_as_recommendation=true`
  - `readiness_status="blocked_trade_date_adjusted"`
  - `scope_verification_status="verified"`
  - `verified_scope_hash="4104d1d15fbd0ab9"`
  - `verified_asof_date="2026-04-20"`
  - `actionable_candidate_count=0`

结论很明确：当前系统“可演示、可联调、可验收”，但还不是“可直接据此下注”的数据状态。

## 优先级总览

| 优先级 | 主题 | 为什么先做 | 主要落点 |
|------|------|------|------|
| P0 | Pulse stale guard | 当前最危险的问题是“不可靠脉搏仍可能继续生成行动建议” | `apps/pulse/`, `apps/regime/`, `apps/dashboard/`, `sdk/` |
| P0 | Quote freshness | “最新行情”如果已陈旧，用户会直接误判价格和仓位 | `apps/data_center/`, `apps/dashboard/`, `sdk/` |
| P1 | Macro freshness | Regime / Pulse 上游宏观数据仍可能静默使用 legacy 或缺失值 | `apps/data_center/`, `apps/macro/`, `apps/regime/`, `apps/pulse/` |
| P1 | Dashboard Alpha readiness | 契约已经有了，但首页仍需更强的“不可误读”表达和 freshness 口径 | `apps/dashboard/`, `apps/alpha/`, `sdk/`, `sdk/agomtradepro_mcp/` |

## P0-1 Pulse stale guard

### 当前缺口

- `apps/pulse/application/use_cases.py` 中 `GetLatestPulseUseCase.execute()` 默认 `require_reliable=False`
- `apps/dashboard/interface/views.py` 当前会在首页调用 `GetLatestPulseUseCase().execute(as_of_date=target_date, refresh_if_stale=True)`，但没有要求 `require_reliable=True`
- `apps/pulse/domain/entities.py` 已定义 `PulseSnapshot.is_reliable`
- `apps/pulse/domain/services.py` 已把 stale 快照标记为 `data_source="stale"`
- 但上一轮 live 验证中，系统仍能给出 action recommendation，这意味着“只标记不阻断”

### 可执行项

1. 在所有“决策输出”调用链上强制 `require_reliable=True`
   - 覆盖 Dashboard 行动建议区块
   - 覆盖 Regime action recommendation use case / API
   - 覆盖 SDK / MCP 的 recommendation 类工具
2. 区分“研究态读取”和“决策态读取”
   - `get_pulse_current` 允许返回 stale 快照用于诊断
   - 但行动建议接口不得基于 `is_reliable=false` 的 Pulse 继续生成资产权重
3. 给 recommendation 响应补充统一阻断契约
   - `must_not_use_for_decision`
   - `blocked_reason`
   - `stale_indicator_codes`
   - `pulse_observed_at`
4. Dashboard 在 Pulse 不可靠时，不展示可执行权重
   - 展示“数据不可靠，已阻断行动建议”
   - 不允许把 stale Pulse 插值结果继续包装成“建议配置”
5. SDK / MCP 文档同步补充“stale 只可读，不可用来下结论”的规则

### 建议落地文件

- `apps/pulse/application/use_cases.py`
- `apps/regime/application/navigator_use_cases.py`
- `apps/dashboard/interface/views.py`
- `sdk/agomtradepro/modules/regime.py`
- `sdk/agomtradepro_mcp/tools/*`

### 验收标准

- 当 `pulse.is_reliable=false` 时，行动建议接口返回阻断状态，而不是正常资产权重
- Dashboard 不再展示可执行仓位建议，只展示阻断原因
- SDK / MCP 调用结果带有明确的 `must_not_use_for_decision=true`
- 新增 API / SDK / MCP 契约测试覆盖 stale Pulse 场景

## P0-2 Quote freshness

### 当前缺口

- `apps/data_center/application/use_cases.py` 中 `QueryLatestQuoteUseCase` 只是“取最新一条”
- `apps/data_center/domain/rules.py` 虽然已有 `is_stale(...)`，但最新行情 use case 并未使用
- 上一轮 live 检查中，`510300.SH` 的 latest quote 已落后当前日期约两周，但系统仍把它当“最新行情”返回

### 可执行项

1. 为 Quote 定义明确 freshness policy
   - 至少区分 ETF / 股票 / 指数
   - 至少区分交易时段与非交易时段
   - 给出默认 `max_age_minutes` / `max_age_hours`
2. 扩展 latest quote 响应契约
   - `snapshot_at`
   - `age_minutes`
   - `is_stale`
   - `freshness_status`
   - `must_not_use_for_decision`
3. 在 Dashboard / 决策页面上禁止把 stale quote 渲染成“当前价格”
   - 可显示最后更新时间
   - 必须显示 stale 提示
4. 为“决策态读取”增加严格模式
   - stale quote 直接阻断
   - 或返回 degraded contract，而不是静默放行
5. 把 quote 抓取成功事件写入 provider / sync telemetry
   - 让 provider status 不只是“配了”，而是“最近真的取到过”
6. 补充定时任务 / 心跳检查
   - 开市时段的最新行情必须持续更新
   - 非交易时段允许放宽，但不能丢 freshness 标记

### 建议落地文件

- `apps/data_center/application/use_cases.py`
- `apps/data_center/domain/rules.py`
- `apps/data_center/interface/api_views.py`
- `apps/dashboard/interface/views.py`
- `sdk/agomtradepro/modules/data_center.py`

### 验收标准

- 默认 latest quote API 返回 freshness 元数据
- stale quote 不能再被 Dashboard 当作“当前价”
- 决策相关调用链对 stale quote 有明确阻断或 degraded 行为
- 新增 API / SDK 契约测试验证 stale quote 场景

## P1-1 Macro freshness

### 当前缺口

- 默认运行时已不再回退到旧 legacy 宏观仓储
- 现阶段剩余重点是继续完善指标级 freshness policy、同步 telemetry 与下游决策提示
- provider status 接口在 provider 未被 registry 真实调用时，会返回 `last_success_at=None`、`avg_latency_ms=None`
- live 验证里，Regime 的 `observed_at` 是今天，但关键底层值仍是 `null`

### 可执行项

1. 维持“事实不足即 blocked”的默认策略
   - 不允许“老数据 + 今天 observed_at”这种伪当前态
2. 建立指标级 freshness policy
   - 每个宏观指标配置 `expected_frequency`
   - 配置 `max_reporting_lag_days`
   - 配置 `decision_critical=true/false`
3. 扩展 macro API / SDK / MCP 响应
   - `quality`
   - `published_at`
   - `age_days`
   - `is_stale`
   - `freshness_status`
   - `decision_grade`
4. Regime / Pulse 上游改成消费 freshness-aware 宏观数据
   - 缺关键指标时，返回“不可判定”或“低可信”
   - 不再只给一个当前 observed date 掩盖底层空值
5. 把 provider 成功拉取的时间、延迟、失败次数落到持久化状态
   - 让 Data Center status 真正反映“最新成功取数时间”
6. 为宏观同步增加门禁测试
   - 决策默认路径不得回退到任何 legacy 数据
   - stale / missing 必须可见

### 建议落地文件

- `apps/data_center/application/use_cases.py`
- `apps/data_center/interface/api_views.py`
- `apps/data_center/infrastructure/repositories.py`
- `apps/macro/application/use_cases.py`
- `apps/regime/application/current_regime.py`
- `apps/pulse/infrastructure/data_provider.py`

### 验收标准

- `CN_PMI` 默认 API 读取不再静默返回 legacy 旧数据
- 当关键宏观数据缺失时，Regime / Pulse 返回 degraded 状态而不是伪正常态
- provider status 在一次成功同步后出现非空 `last_success_at`
- 新增 integration / acceptance 测试验证 freshness 口径

## P1-2 Dashboard Alpha readiness

### 当前状态

- `REL-005` 已落地（第一阶段）
  - `alpha_homepage` 现在会输出 `readiness_status`、`scope_verification_status`、`freshness_status`、`result_age_days`、`verified_scope_hash`、`verified_asof_date`
  - 当结果来自 broader cache / scope fallback / stale / degraded / trade-date-adjusted 时，会明确给出 `must_not_use_for_decision=true` 与 `blocked_reason`
  - 单票候选在 not-ready 场景下不再落成 `actionable`
- `REL-006` 已落地（第一阶段）
  - `/api/dashboard/alpha/stocks/?format=json` 现在会返回 `contract`
  - SDK / MCP 契约同步扩展了 readiness / freshness / verification 字段
- 第二阶段补充：
  - scoped-but-stale 结果也会保留 `verified_scope_hash` 与 `verified_asof_date`，便于审计
  - `trade_date_adjusted` 已进入 API / SDK / MCP contract
  - live smoke 已确认 pending / top-ranked 结果不会被提升为 actionable recommendation

### 当前缺口

- `apps/dashboard/application/alpha_homepage.py` 已有 `_mark_no_verified_recommendation(...)`
- `sdk/agomtradepro/modules/dashboard.py` 已给出：
  - `recommendation_ready`
  - `must_not_treat_as_recommendation`
  - `async_refresh_queued`
- `sdk/agomtradepro_mcp/tools/dashboard_tools.py` 也已写明：`recommendation_ready=false` 时不得解释为推荐
- 但首页和周边区块仍需更明确地区分：
  - `Top 10 研究结果`
  - `Workflow 可行动候选`
  - `Pending 请求`

### 可执行项

1. 首页在 `recommendation_ready=false` 时，必须明确显示“暂无可信 Alpha 推荐”
   - 不允许拿 `pending_requests`
   - 不允许拿历史 workflow 候选
   - 不允许拿异步排队状态顶替推荐结果
2. 扩展 Alpha candidate contract 的 freshness 字段
   - `last_verified_trade_date`
   - `last_verified_generated_at`
   - `verified_scope_hash`
   - `result_age_minutes`
   - `degraded_reason`
3. 页面文案与 SDK / MCP 契约完全对齐
   - 页面怎么写，SDK / MCP 就怎么说
   - 不允许 UI 口径和 Agent 口径冲突
4. 异步刷新状态要可追踪但不可误读
   - `queued` / `recently_queued` / `failed`
   - 这些状态只能表示“后台在做”，不能表示“推荐已可用”
5. 对 `portfolio_id=366` 这类当前 not-ready 的真实账户路径补回归测试
   - 页面测试
   - API 契约测试
   - SDK / MCP smoke

### 建议落地文件

- `apps/dashboard/application/alpha_homepage.py`
- `apps/dashboard/application/queries.py`
- `apps/dashboard/interface/views.py`
- `sdk/agomtradepro/modules/dashboard.py`
- `sdk/agomtradepro_mcp/tools/dashboard_tools.py`
- `apps/dashboard/tests/*`

### 验收标准

- 当账户池没有 verified Alpha 结果时，页面和 SDK / MCP 都明确返回“not ready”
- 待执行队列和异步排队状态不能再被误解为“推荐资产”
- Alpha 返回结果带有可审计的 freshness / verification 元数据

## 横切执行项

以下工作不属于单一模块，但必须一起做，否则四个修复点会继续各说各话。

### 1. 统一 reliability contract

建议在 Macro / Quote / Pulse / Dashboard recommendation 这四类输出上统一字段：

- `observed_at` 或 `snapshot_at`
- `is_reliable`
- `is_stale`
- `freshness_status`
- `must_not_use_for_decision`
- `blocked_reason`
- `data_source`

### 2. 新增 live acceptance 门禁

至少补 4 条真实链路断言：

1. stale Pulse 不得继续产出 action recommendation
2. stale quote 不得被当作当前价格
3. macro 默认路径不得静默落回 legacy
4. `recommendation_ready=false` 的 Dashboard Alpha 不得被 Agent 解释为推荐

### 3. Data freshness summary 收口

建议把 freshness summary 作为一个可复用聚合层，供：

- Dashboard
- Agent Runtime
- SDK
- MCP

统一消费，避免各层再次各自写一套 stale 判断。

## 建议执行顺序

### 第一批：先堵住误导性输出

1. `pulse stale guard`
2. `quote freshness`

### 第二批：修上游真实数据状态

1. `macro freshness`
2. provider telemetry 持久化

### 第三批：修首页口径和对外契约

1. `dashboard alpha readiness`
2. SDK / MCP / 文档同步

## 建议拆分为的任务单

| 任务单 | 优先级 | 说明 |
|------|------|------|
| REL-001 | P0 | Action recommendation 在 Pulse stale 时强制阻断 |
| REL-002 | P0 | Quote latest API 增加 freshness 契约与 strict mode |
| REL-003 | P1 | Macro series 默认路径移除静默 legacy fallback |
| REL-004 | P1 | Provider status 持久化 `last_success_at` / `avg_latency_ms` |
| REL-005 | P1 | Dashboard Alpha 增加 verification / freshness 元数据（已落地第一阶段） |
| REL-006 | P1 | Dashboard 页面文案与 SDK / MCP 契约收口（已落地第一阶段） |
| REL-007 | P1 | Regime / Pulse 消费 freshness-aware macro inputs |
| REL-008 | P2 | live acceptance 与回归门禁补齐 |

## 完成定义

本轮修复完成后，至少应达到以下标准：

- 用户能明确区分“有数据”和“数据可决策”是两回事
- 任一 stale / degraded 输入都不能再被包装成正常推荐
- Dashboard、API、SDK、MCP 对同一条数据的可靠性表述一致
- provider status 能回答“最近一次成功取数是什么时候”
- 本地 live 验证重新执行后，不再出现“今天 observed_at + 底层关键值为空 / 陈旧”的伪当前态
