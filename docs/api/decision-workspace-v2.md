# Decision Workspace V2 API（M1 草稿）

- 版本: v0.2
- 日期: 2026-03-22
- 状态: Draft（用于外包 M1 里程碑验收）

## 1. 概述

本文件定义决策工作台统一推荐相关 API（Top-down + Bottom-up 融合）：

1. 推荐列表查询
2. 推荐刷新触发
3. 推荐用户动作写入
4. 冲突列表查询
5. 模型参数查询与更新

### 1.1 前端账户绑定约定

- 工作台顶部“选择账户”与推荐/审批/冲突筛选使用模拟账户接口 `/api/simulated-trading/accounts/`
- 该接口前端应读取 `accounts` 数组，单项字段使用 `account_id`、`account_name`
- 审批弹窗中的“账户落地”使用真实投资组合接口 `/account/api/portfolios/`
- 该接口为 DRF 分页列表，前端应读取 `results` 数组，并将 `id` 作为 `portfolio_id`

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

## 6. 模型参数

### 5.1 查询参数

- 方法: `GET`
- 路径: `/api/decision/workspace/params/`
- Query:
  - `env`（可选，默认 `dev`）

### 5.2 更新参数

- 方法: `POST`
- 路径: `/api/decision/workspace/params/update/`
- Body:
  - `param_key`（必填）
  - `param_value`（必填）
  - `param_type`（可选，默认 `float`）
  - `env`（可选，默认 `dev`）
  - `updated_reason`（建议必填）

## 7. 首页推荐到工作台的闭环

- 首页 Alpha 推荐和个股筛选页可以通过 `security_code + action + source` 深链进入 `/decision/workspace/`
- 工作台收到深链后会：
  1. 调用 `/api/decision/workspace/recommendations/refresh/` 按证券同步统一推荐
  2. 调用 `/api/decision/workspace/recommendations/` 拉回对应推荐
  3. 可选调用 `/api/decision/workspace/recommendations/action/` 写入用户动作
- 这使得链路统一为：`系统推荐 -> 推荐解释 -> 用户动作 -> 执行审批`

## 8. 默认参数初始化

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
