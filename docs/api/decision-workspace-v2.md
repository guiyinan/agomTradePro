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

## 2. 统一推荐列表

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
