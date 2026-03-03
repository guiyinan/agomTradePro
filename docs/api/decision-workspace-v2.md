# Decision Workspace V2 API（M1 草稿）

- 版本: v0.1-draft
- 日期: 2026-03-02
- 状态: Draft（用于外包 M1 里程碑验收）

## 1. 概述

本文件定义决策工作台统一推荐相关 API（Top-down + Bottom-up 融合）：

1. 推荐列表查询
2. 推荐刷新触发
3. 冲突列表查询
4. 模型参数查询与更新

## 2. 统一推荐列表

- 方法: `GET`
- 路径: `/api/decision/workspace/recommendations/`
- Query:
  - `account_id`（必填）
  - `status`（可选）
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
        "status": "NEW"
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

## 4. 冲突列表

- 方法: `GET`
- 路径: `/api/decision/workspace/conflicts/`
- Query:
  - `account_id`（必填）

## 5. 模型参数

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

## 6. 默认参数初始化

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

