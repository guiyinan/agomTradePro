# Decision Workspace V2 API（M1 草稿）

- 版本: v0.2
- 日期: 2026-03-22
- 状态: Draft（用于外包 M1 里程碑验收）

## 1. 概述

本文件定义决策工作台主链路 API。当前主链路已从“推荐解释 -> 直接审批”收敛为：

`系统级分析 -> 推荐筛选 -> 账户级交易计划 -> 审批执行 -> 审计入口`

其中：

- `UnifiedRecommendation` 只代表推荐层对象，不再视为最终执行单
- 工作台真正的执行产物是 `PortfolioTransitionPlan`
- `审计复盘` 已移出主流程，执行完成后进入 `/audit/`

当前 API 范围包括：

1. 推荐列表查询
2. 推荐刷新触发
3. 推荐用户动作写入
4. 冲突列表查询
5. 交易计划生成与更新
6. 审批执行预览
7. 模型参数查询与更新
8. 账户级自动投顾建议单

### 1.1 前端账户绑定约定

- 工作台页面头部必须提供全局账户 selector，作为当前决策口径的唯一入口
- 工作台左侧栏应显示当前账户现状，包括账户状态、资产概览和持仓摘要
- Step 1-3 需要显式展示当前账户上下文，但必须标注为“系统级分析”，不得误导为按单账户重算
- Step 1-6 的 HTMX 请求应透传 `account_id`，保证页面刷新与 URL 中的账户口径一致
- 工作台顶部“选择账户”与推荐/审批/冲突筛选使用统一账户接口 `/api/account/accounts/`
- 工作台应显式请求 `active_only=false`，确保账户 selector 与 `/simulated-trading/my-accounts/` 展示口径一致
- 工作台中的“刷新推荐”动作也应携带当前 `account_id`，避免刷新任务与当前页面账户口径脱节
- 该接口前端应读取 `accounts` 数组，单项字段使用 `account_id`、`account_name`
- 该接口后端只允许返回当前登录用户拥有的账户，不得返回其他用户的活跃账户
- 历史模板 `core/templates/decision/workspace_legacy.html` 已废弃并移除，工作台只允许维护 `core/templates/decision/workspace.html`
- 左侧栏账户现状使用 `/api/account/accounts/{id}/` 和 `/api/account/accounts/{id}/positions/`
- Step 4 的详情弹窗只展示推荐参数与风控预览，不得承载任何执行目标、账户落地或审批评论表单
- Step 1 应优先复用最近一次已落库的 `Regime` / `Pulse` 快照；仅在本地无快照时才回退到实时计算
- Step 2 应优先复用最近一次已落库的 `ActionRecommendationLog`，避免页面打开时阻塞在宏观与 Pulse 重算链路
- Step 3 读取轮动建议时，若当日 `rotation_signal` 已落库，应优先复用已持久化结果；仅在无可用 signal 时才触发实时重算，避免页面请求阻塞在外部行情链路
- 决策工作台页面读路径允许复用“最近一次已落库”轮动信号作为 UI 上下文，即使该信号不是当日数据；前端必须通过 stale/source 元数据明确提示用户
- Step 3 partial 和 JSON context 都应返回轮动结果状态元数据：`rotation_data_source`、`rotation_is_stale`、`rotation_warning_message`、`rotation_signal_date`，前端必须显式提示用户当前是否为回退结果
- Step 1-3 的系统级上下文改为夜间预计算口径，默认由 `apps.decision_rhythm.application.tasks.refresh_decision_workspace_snapshots` 在每日 22:45（Asia/Shanghai）统一刷新
- 工作台前端必须显式展示每类系统级数据的 `数据日期`、`有效至`、`来源`、`状态`，避免用户把历史快照误判为实时结果
- 当前有效期约定：夜间快照在 `observed_at` 次日 `23:59`（Asia/Shanghai）前视为有效；超时后标记为 `已过期`
- 当前状态标签约定：
  - `有效`：命中夜间快照且未超过有效期
  - `已过期`：命中夜间快照，但已超过预期有效期
  - `实时回退`：未命中可用夜间快照，页面临时实时计算
  - `缺失`：无快照且无可展示回退结果

### 1.2 Nightly Snapshot Contract

夜间快照任务需要串行刷新以下系统级上下文，供工作台 Step 1-3 直接读取：

1. 宏观输入同步
2. `Regime` 快照计算与持久化
3. `Pulse` 快照计算与持久化
4. `ActionRecommendationLog` 刷新与持久化
5. `RotationSignal` 刷新与持久化

默认 beat 配置命令：

```bash
python manage.py setup_workspace_snapshot_refresh
```

默认创建的周期任务：

- 名称: `decision-workspace-nightly-snapshot-refresh`
- 任务: `apps.decision_rhythm.application.tasks.refresh_decision_workspace_snapshots`
- 时区: `Asia/Shanghai`
- 默认时间: `22:45`

## 2. 账户级自动投顾建议单

`GET /api/decision/advisor/sheet/?account_id=<id>`

用途: 按一个账户生成当天自动投顾建议单。该接口只返回建议订单/订单意图，不接券商、不真实下单、不修改持仓。

约束:

- `account_id` 必填。
- 后端必须校验账户归属，禁止跨用户读取。
- 建议单必须先读取账户现有持仓，再生成订单意图。
- UI 可以展示账户类型、账户名称、账户状态、持仓和订单建议，但不要求用户理解底层持仓来自模拟盘表还是手工组合表。

响应字段:

```json
{
  "success": true,
  "data": {
    "account": {
      "account_id": "1",
      "account_name": "Growth Account",
      "account_type": "simulated",
      "account_type_label": "模拟盘账户",
      "account_status": "active",
      "total_asset": 100000.0,
      "available_cash": 20000.0,
      "holding_count": 3,
      "baseline": "existing_positions"
    },
    "today_conclusion": "ACT",
    "risk_policy": {
      "version": "riskcfg_xxx",
      "risk_profile": "moderate",
      "parameters": {}
    },
    "data_health": {
      "status": "ok",
      "must_not_use_for_decision": false,
      "blocked_reasons": []
    },
    "exposure_summary": {
      "limits": {
        "sector": 0.25,
        "strategy": 0.3
      },
      "by_sector": [],
      "by_industry": [],
      "by_strategy": [],
      "alerts": [],
      "missing_exposure_assets": []
    },
    "holdings": [],
    "allocation": [],
    "order_summary": {
      "total": 2,
      "actionable": 2,
      "blocked": 0,
      "buy": 1,
      "add": 0,
      "reduce": 1,
      "exit": 0,
      "hold": 0,
      "watch": 0
    },
    "order_intents": [],
    "decision_cards": [],
    "execution_plan": {
      "status": "READY_FOR_CONFIRMATION",
      "execution_mode": "real_confirm_only",
      "broker_execution_enabled": false,
      "requires_human_confirmation": true,
      "confirmation_status": "PENDING",
      "orders_count": 2,
      "orders": []
    },
    "recommendation_conflicts": [],
    "blockers": [],
    "next_actions": []
  }
}
```

`order_intents` 单项固定字段:

- `order_intent_id`
- `account_id`
- `asset_code`
- `asset_name`
- `side`: `BUY / ADD / REDUCE / EXIT / HOLD / WATCH`
- `current_quantity`
- `target_quantity`
- `delta_quantity`
- `estimated_price`
- `estimated_amount`
- `current_weight`
- `target_weight`
- `priority`
- `price_band`
- `reason`
- `risk_notes`
- `invalidation_rule`
- `execution_hint`
- `source_recommendation_id`
- `blocking_status`
- `risk_gate_status`
- `risk_gate`
- `data_asof`
- `tracking`
- `confirmation`
- `decision_card`
- `source_recommendation_ids`
- `conflict_resolution`

`recommendation_conflicts` 记录同一标的多模块方向冲突的归并结果:

- `asset_code`
- `accepted_recommendation_id`
- `accepted_side`
- `rejected_recommendations`
- `conflict_reason`

`risk_gate` 由两部分组成:

- `execution_guard`: Decision Rhythm 执行前检查，包括 `price_validation`、`beta_gate`、`quota`、`cooldown`、`signal_invalidation`
- `risk_center`: 集中风控中心检查，包括个人风险配置版本、投前风控结果和预测指标
- `exposure_guard`: 组合暴露检查，包括行业、细分行业和策略 bucket 的 projected weight

若 `execution_guard` 失败，`blocking_status` 为 `BLOCKED_EXECUTION_GUARD`。
若新增买入/加仓导致行业、细分行业或策略暴露超过风险配置上限，`blocking_status` 为 `BLOCKED_EXPOSURE_LIMIT`。减仓和清仓不会被暴露超限阻断。

`exposure_summary` 记录当前组合和拟执行订单后的预测暴露:

- `limits`: 命中的 `max_sector_position_pct`、`max_industry_position_pct`、`max_strategy_position_pct`
- `by_sector`
- `by_industry`
- `by_strategy`
- `alerts`: projected weight 超过上限的机器可读告警
- `missing_exposure_assets`: 缺少行业或细分行业元数据的资产

`tracking` 记录来源推荐的复盘入口:

- `review_status`: `PENDING_REVIEW / ADOPTED_PENDING_EXECUTION / EXECUTED / NO_SOURCE_RECOMMENDATION`
- `source_recommendation_ids`
- `recommendations`: 来源推荐的 `user_action`、备注、动作时间和执行链接
- `execution_links`: 已匹配的手工成交或模拟成交链接
- `execution_count`
- `is_executed`
- `performance`: 来源推荐按锚点价计算的 `7d / 20d / 60d` 表现窗口，包含 `error_attribution` 初版归因

`performance.error_attribution.deep_attribution` 记录深层归因证据:

- `regime`: 推荐时 Regime、置信度、成熟表现窗口对应日期的事后 Regime 标签，以及上下文缺失/偏弱/判断错误分类
- `policy`: 推荐时 Policy 档位、成熟表现窗口对应日期的事后 Policy 标签，以及上下文缺失/误判分类
- `manual_override`: 结合 `user_action` 和成熟表现窗口判断未采纳建议后的结果
- `secondary_categories`: `REGIME_CONTEXT_MISSING / REGIME_CONTEXT_WEAK / REGIME_JUDGMENT_ERROR / POLICY_CONTEXT_MISSING / POLICY_MISJUDGMENT / MANUAL_OVERRIDE_ERROR / MANUAL_OVERRIDE_PROTECTED_CAPITAL`

`confirmation` 记录半自动执行前的二次确认要求:

- `required`
- `status`: `PENDING / NOT_REQUIRED / NOT_APPLICABLE`
- `reasons`: 机器可读确认原因，例如 `large_order_amount`、`real_account_manual_confirm`、`data_health_warning`
- `confirmable`
- `approval_entry`: 后续进入 approval/request 流程所需的来源信息

`execution_plan` 是只读交易计划，不会触发券商真实下单:

- `execution_mode`: `real_confirm_only / semi_auto_plan / no_executable_orders`
- `broker_execution_enabled`: 固定为 false
- `requires_human_confirmation`
- `confirmation_status`
- `real_account_guard`
- `orders`: 可执行订单及其确认状态、执行前检查、价格区间和失效时间

`decision_cards` 单项用于 Dashboard、Terminal 和 API 统一展示建议卡片，包含:

- `action`
- `confidence`
- `current_weight`
- `target_weight`
- `delta_weight`
- `estimated_amount`
- `primary_reasons`
- `counter_reasons`
- `invalidation_logic`
- `valid_until`
- `data_asof`
- `risk_notes`
- `risk_gate_status`
- `blocking_status`
- `tracking`
- `confirmation`
- `expected_loss_if_wrong`

## 2.1 Dashboard 自动投顾主控台

- 方法: `GET`
- 路径: `/api/dashboard/auto-advisor-console/?account_id=<id>`
- 用途: 首页聚合今日自动投顾状态，不触发下单。

响应 `data` 主要字段:

- `today_tradeability`: 今日结论、是否可交易、是否需要复核、阻断订单数
- `macro_regime`: 当前宏观象限、置信度和分布
- `portfolio_risk`: 最大持仓权重、超配持仓、暴露告警、阻断和 warning 数量
- `today_advice`: 订单摘要、前 5 条决策卡片、前 5 条订单意图
- `must_handle_alerts`: 必须处理的阻断、确认、暴露和数据告警
- `data_freshness`: 数据健康状态、阻断原因、quote 数量
- `execution`: 执行模式、确认状态、是否需要人工确认、是否允许自动下单
- `next_actions`: 建议下一步动作

该接口复用 advisor sheet，只返回主控台摘要；真实账户仍固定 `broker_execution_enabled=false`。

Dashboard 首页已嵌入“今日自动投顾主控台”面板，默认读取第一个投资账户，并支持账户切换后刷新该接口。

## 2.2 Dashboard 自动投顾自然语言查询

- 方法: `GET`
- 路径: `/api/dashboard/auto-advisor-query/?account_id=<id>&q=<question>`
- 用途: 针对个人自动投顾建议单做确定性问答，不触发下单，不依赖 LLM。

Query:

- `account_id`（必填）
- `q` / `question` / `query`（必填，三者任选其一）

首版支持的 intent:

- `largest_risk`: “我现在最大风险是什么”
- `reduce_reason`: “今天为什么建议减仓”
- `invalidated_positions`: “哪些持仓已经证伪”
- `market_shock_loss`: “如果明天跌 3%, 组合损失多少”
- `unexecuted_recommendations`: “哪些建议我上次没执行, 结果如何”
- `overview`: 未命中特定 intent 时返回建议单概览

响应 `data` 主要字段:

- `query`: 原始问题、识别出的 intent、支持的 intent 列表
- `answer`: 面向人的简短回答
- `highlights`: 结构化重点项，例如风险项、减仓标的、证伪信号、冲击损失估算或未执行建议表现
- `evidence`: 用于审计和前端展开的原始摘要证据

该接口复用 advisor sheet 的 `risk_summary`、`decision_cards`、`order_intents`、`tracking`、`data_health` 和账户市值字段。下跌冲击损失为线性估算，不包含 beta、对冲、流动性和隔夜跳空影响。

## 2.3 Dashboard 自动投顾个人周报

- 方法: `GET`
- 路径: `/api/dashboard/auto-advisor-weekly-report/?account_id=<id>&as_of=YYYY-MM-DD`
- 用途: 输出个人自动投顾周报首版，不触发下单，不落库。
- 方法: `POST`
- 路径: `/api/dashboard/auto-advisor-weekly-report/`
- Body: `{"account_id": "<id>", "as_of": "YYYY-MM-DD"}`
- 用途: 生成并持久化个人自动投顾周报，同时写入投资日记、Dashboard 通知和审计日志。

Query:

- `account_id`（必填）
- `as_of`（可选，默认当天，用于计算周一到周日的报告区间）

响应 `data` 主要字段:

- `week`: 周报起止日期和 as-of 日期
- `portfolio_change`: 组合周变化；优先返回 `HISTORICAL`，历史不足时返回 `CURRENT_SNAPSHOT_ONLY`
- `largest_risk_exposure`: 最大风险暴露摘要和结构化风险项
- `system_vs_actual`: 系统建议数量、动作分布、复盘状态分布和执行确认状态
- `unexecuted_recommendations`: 未执行或待复核建议及其表现窗口
- `invalidated_recommendations`: 来源信号已证伪或证伪检查失败的建议
- `investment_diary`: 从 advisor sheet 派生的投资日记首版，包含周复盘 entry、反思标签、经验教训、人工备注提示和原始证据
- `next_week_watchlist`: 下周重点观察清单，包含数据健康、阻断订单和需复核决策卡片
- `evidence`: advisor sheet 摘要证据

周报和投资日记复用 advisor sheet。Celery 周报任务和 `POST /api/dashboard/auto-advisor-weekly-report/` 会把 weekly report payload、`investment_diary`、dashboard 通知和 audit operation log 写入数据库；直接调用 GET 只读 API 时仍只生成实时 payload。组合变化优先读取模拟账户日净值历史，历史不足时降级为当前快照。`investment_diary.status=DERIVED_FROM_ADVISOR_SHEET` 表示日记内容由 advisor sheet 派生。

持久化读取:

- 周报历史: `/api/dashboard/auto-advisor-weekly-report-history/?account_id=<id>&limit=20`
- 通知输出: `/api/dashboard/auto-advisor-notifications/?account_id=<id>&limit=20`
- 存储表: `dashboard_auto_advisor_weekly_report`、`dashboard_auto_advisor_notification`
- 审计: 每次 Celery 或 POST 持久化会写入 `audit_operation_log`

自动生成:

- Celery 任务: `dashboard.generate_auto_advisor_weekly_reports`
- 默认 beat 名称: `dashboard-auto-advisor-weekly-report`
- 默认初始化: `python manage.py setup_auto_advisor_weekly_report`
- 统一初始化: `python manage.py init_scheduler_defaults`
- 默认频率: 每周五 17:30，生成全部活跃账户周报
- 可选范围: `--user-id <id> --account-ids <id1,id2>`

Terminal CLI:

- `advisor_today account_id=<id>`: 查看今日自动投顾建议单
- `advisor_query account_id=<id> question=<问题>`: 对账户执行自动投顾自然语言查询

MCP / SDK 原生入口:

- SDK `client.decision_rhythm.advisor_sheet(account_id)`
- SDK `client.dashboard.auto_advisor_console(account_id)`
- SDK `client.dashboard.auto_advisor_query(account_id, question)`
- SDK `client.dashboard.auto_advisor_weekly_report(account_id, as_of=None)`
- SDK `client.dashboard.create_auto_advisor_weekly_report(account_id, as_of=None)`
- SDK `client.dashboard.auto_advisor_weekly_report_history(account_id=None, limit=20)`
- SDK `client.dashboard.auto_advisor_notifications(account_id=None, limit=20)`
- MCP `get_auto_advisor_decision_sheet(account_id)`
- MCP `get_auto_advisor_console(account_id)`
- MCP `ask_auto_advisor(account_id, question)`
- MCP `get_auto_advisor_weekly_report(account_id, as_of=None)`
- MCP `create_auto_advisor_weekly_report(account_id, as_of=None)`
- MCP `list_auto_advisor_weekly_report_history(account_id=None, limit=20)`
- MCP `list_auto_advisor_notifications(account_id=None, limit=20)`

`create_auto_advisor_weekly_report` 会写入报表、投资日记、通知和审计日志；所有 MCP 自动投顾工具都不提供真实交易执行能力。

## 3. 统一推荐列表

- 方法: `GET`
- 路径: `/api/decision/workspace/recommendations/`
- Query:
  - `account_id`（必填）
  - `status`（可选）
  - `user_action`（可选，支持 `PENDING` / `WATCHING` / `ADOPTED` / `IGNORED`）
  - `security_code`（可选）
  - `recommendation_id`（可选）
  - `include_ignored`（可选，默认 false）
  - `page`（可选，默认 1）
  - `page_size`（可选，默认 20，范围 1..200）

成功响应示例：

```json
{
  "success": true,
  "data": {
    "recommendations": [
      {
        "recommendation_id": "urec_xxx",
        "account_id": "account_001",
        "security_code": "000001.SZ",
        "side": "BUY",
        "composite_score": 0.82,
        "confidence": 0.74,
        "status": "NEW",
        "user_action": "WATCHING",
        "user_action_note": "source=dashboard-alpha",
        "user_action_at": "2026-03-22T10:30:00+08:00"
      }
    ],
    "total_count": 1,
    "page": 1,
    "page_size": 20,
    "total_pages": 1
  }
}
```

失败响应示例：

```json
{
  "success": false,
  "error": "account_id is required"
}
```

## 3. 刷新推荐

- 方法: `POST`
- 路径: `/api/decision/workspace/recommendations/refresh/`
- Body:
  - `account_id`（可选）
  - `security_codes`（可选）
  - `force`（可选，默认 false）
  - `async_mode`（可选，默认 true）

响应示例：

```json
{
  "success": true,
  "data": {
    "task_id": "refresh_xxx",
    "status": "ACCEPTED",
    "message": "刷新请求已接收，正在处理中",
    "recommendations_count": 0,
    "conflicts_count": 0
  }
}
```

## 4. 推荐用户动作

- 方法: `POST`
- 路径: `/api/decision/workspace/recommendations/action/`
- Body:
  - `recommendation_id`（必填）
  - `action`（必填，支持 `watch` / `adopt` / `ignore` / `pending`）
  - `account_id`（可选）
  - `note`（可选）

响应示例：

```json
{
  "success": true,
  "data": {
    "message": "已更新为观察中",
    "recommendation": {
      "recommendation_id": "urec_xxx",
      "security_code": "000001.SZ",
      "status": "NEW",
      "user_action": "WATCHING"
    }
  }
}
```

## 5. 冲突列表

- 方法: `GET`
- 路径: `/api/decision/workspace/conflicts/`
- Query:
  - `account_id`（必填）

## 6. 交易计划

### 6.1 领域约定

`PortfolioTransitionPlan` 是账户级调仓计划，至少包含：

- `plan_id`
- `account_id`
- `source_recommendation_ids`
- `current_positions`
- `target_positions`
- `orders`
- `risk_contract`
- `summary`
- `status`

订单 `orders[*]` 至少包含：

- `security_code`
- `action`（v1 支持 `BUY` / `REDUCE` / `EXIT` / `HOLD`）
- `current_qty`
- `target_qty`
- `delta_qty`
- `target_weight`
- `price_band_low`
- `price_band_high`
- `stop_loss_price`
- `invalidation_rule`
- `review_by`
- `source_recommendation_id`

证伪逻辑补充能力：

- 系统模板：`POST /api/decision/workspace/invalidation/template/`
  - 自动结合当前 `Pulse` 和 `Regime` 上下文生成结构化 JSON 草稿
- AI 草稿：`POST /api/decision/workspace/invalidation/ai-draft/`
  - 在系统模板基础上结合用户补充提示生成更细化的 JSON 规则
- 前端仍保留 JSON 自定义编辑，允许人工直接修改 `invalidation_rule`

### 6.2 生成交易计划

- 方法: `POST`
- 路径: `/api/decision/workspace/plans/generate/`
- Body:
  - `account_id`（必填）
  - `recommendation_ids`（可选；为空时默认取当前账户全部 `ADOPTED` 推荐）

约束：

- Step 4 的勾选只是“计划候选集”，真正生成计划时仍只接受 `ADOPTED` 推荐
- 若 `recommendation_ids` 全部不是 `ADOPTED`，接口返回 400，并提示“当前账户没有可生成交易计划的已采纳推荐”
- 纯 `HOLD` / 无可执行订单的计划必须停留在 `DRAFT`，不得进入审批执行

响应示例：

```json
{
  "success": true,
  "data": {
    "plan_id": "plan_xxx",
    "account_id": "394",
    "status": "DRAFT",
    "can_enter_approval": false,
    "blocking_issues": ["000001.SH: 缺少完整证伪条件"],
    "orders": [
      {
        "security_code": "000001.SH",
        "security_name": "平安银行",
        "action": "BUY",
        "current_qty": 0,
        "target_qty": 500,
        "delta_qty": 500,
        "stop_loss_price": "9.5000",
        "invalidation_rule": {
          "logic": "AND",
          "conditions": [],
          "requires_user_confirmation": true
        }
      }
    ]
  }
}
```

说明：

- 推荐列表、交易计划、冲突列表中的证券对象会返回 `security_name`，前端应优先展示“简称 + 代码”。
- `current_positions`、`target_positions`、`orders` 等计划快照中的金额/价格字段会以 JSON 安全格式返回；涉及 `Decimal` 的值会序列化为字符串，避免持仓快照落库时报 500。

### 6.3 查询交易计划

- 方法: `GET`
- 路径: `/api/decision/workspace/plans/<plan_id>/`

### 6.4 更新交易计划

- 方法: `POST`
- 路径: `/api/decision/workspace/plans/<plan_id>/update/`
- Body:
  - `orders[*].stop_loss_price`
  - `orders[*].invalidation_rule`
  - `orders[*].review_by`
  - `risk_contract`

## 7. 审批执行预览

- 方法: `POST`
- 路径: `/api/decision/execute/preview/`
- 主入参: `plan_id`
- 兼容入参: `recommendation_id`
- 可选入参: `create_request`

兼容策略：

- 新主链路必须优先传 `plan_id`
- 旧客户端仍可继续传 `recommendation_id`
- `create_request=false` 或省略时，接口只返回风控预览，不落库审批请求
- 只有显式传入 `create_request=true` 时，才创建审批请求并返回 `request_id`
- Step 4 只能调用预览模式；Step 5 才是唯一允许提交审批请求的入口

`plan_id` 响应示例：

```json
{
  "success": true,
  "data": {
    "request_id": "apr_xxx",
    "plan_id": "plan_xxx",
    "recommendation_type": "plan",
    "preview": {
      "orders_count": 2,
      "active_orders_count": 2
    }
  }
}
```

## 8. 模型参数

### 8.1 查询参数

- 方法: `GET`
- 路径: `/api/decision/workspace/params/`
- Query:
  - `env`（可选，默认 `dev`）

### 8.2 更新参数

- 方法: `POST`
- 路径: `/api/decision/workspace/params/update/`
- Body:
  - `param_key`（必填）
  - `param_value`（必填）
  - `param_type`（可选，默认 `float`）
  - `env`（可选，默认 `dev`）
  - `updated_reason`（建议必填）

## 9. 首页推荐到工作台的闭环

- 首页 Alpha 推荐和个股筛选页可以通过 `security_code + action + source` 深链进入 `/decision/workspace/`
- 工作台收到深链后会：
  1. 调用 `/api/decision/workspace/recommendations/refresh/` 按证券同步统一推荐
  2. 调用 `/api/decision/workspace/recommendations/` 拉回对应推荐
  3. 可选调用 `/api/decision/workspace/recommendations/action/` 写入用户动作
- 这使得链路统一为：`系统推荐 -> 用户动作 -> 交易计划 -> 审批执行 -> 审计入口`

## 10. 默认参数初始化

- 命令: `python manage.py init_decision_model_params --env dev`
- 可选:
  - `--force` 强制覆盖已有参数

初始化参数包括：

- `alpha_model_weight`
- `sentiment_weight`
- `flow_weight`
- `technical_weight`
- `fundamental_weight`
- `gate_penalty_cooldown`
- `gate_penalty_quota`
- `gate_penalty_volatility`
- `composite_score_threshold`
- `confidence_threshold`
- `default_position_pct`
- `max_position_pct`
- `max_capital_per_trade`
