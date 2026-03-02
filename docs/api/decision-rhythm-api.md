# Decision Rhythm API 文档

> **版本**: V1.0
> **最后更新**: 2026-03-02
> **基础路径**: `/api/decision-rhythm/`

---

## 概述

Decision Rhythm API 提供估值定价引擎和执行审批的完整接口。

---

## 认证

所有 API 请求需要认证：

```http
Authorization: Bearer <token>
X-CSRFToken: <csrf_token>
```

---

## API 端点总览

### 估值相关

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/valuation/recalculate/` | POST | 重新计算估值 |
| `/api/valuation/snapshot/{id}/` | GET | 获取估值快照 |

### 决策工作台

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/decision/workspace/aggregated/` | GET | 获取聚合建议 |
| `/api/decision/execute/preview/` | POST | 预览执行详情 |
| `/api/decision/execute/approve/` | POST | 批准执行 |
| `/api/decision/execute/reject/` | POST | 拒绝执行 |
| `/api/decision/execute/{request_id}/` | GET | 获取执行状态 |

---

## 估值 API

### 重新计算估值

重新计算指定证券的估值。

**请求**:
```http
POST /api/valuation/recalculate/
Content-Type: application/json

{
  "security_code": "000001.SH",
  "valuation_method": "COMPOSITE",
  "force_refresh": false
}
```

**参数**:
| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| security_code | string | 是 | 证券代码 |
| valuation_method | string | 否 | 估值方法（默认 COMPOSITE） |
| force_refresh | boolean | 否 | 是否强制刷新（忽略缓存） |

**响应**:
```json
{
  "success": true,
  "data": {
    "snapshot_id": "vs_abc123",
    "security_code": "000001.SH",
    "valuation_method": "COMPOSITE",
    "fair_value": 12.50,
    "entry_range": [10.50, 11.00],
    "target_range": [13.00, 14.50],
    "stop_loss": 9.50,
    "calculated_at": "2026-03-02T10:00:00Z",
    "upside_potential": 27.27,
    "downside_risk": 9.09,
    "risk_reward_ratio": 3.0
  }
}
```

**错误响应**:
```json
{
  "success": false,
  "error": "Unable to get current price for 000001.SH"
}
```

---

### 获取估值快照

获取指定估值快照的详细信息。

**请求**:
```http
GET /api/valuation/snapshot/vs_abc123/
```

**响应**:
```json
{
  "success": true,
  "data": {
    "snapshot_id": "vs_abc123",
    "security_code": "000001.SH",
    "valuation_method": "COMPOSITE",
    "fair_value": "12.50",
    "entry_price_low": "10.50",
    "entry_price_high": "11.00",
    "target_price_low": "13.00",
    "target_price_high": "14.50",
    "stop_loss_price": "9.50",
    "calculated_at": "2026-03-02T10:00:00Z",
    "input_parameters": {
      "pe_percentile": 0.15,
      "pb_percentile": 0.20,
      "overall_score": 75
    },
    "version": 1,
    "is_legacy": false,
    "upside_potential": "27.27",
    "downside_risk": "9.09",
    "risk_reward_ratio": "3.00"
  }
}
```

---

## 决策工作台 API

### 获取聚合建议

获取按账户+证券+方向聚合后的投资建议。

**请求**:
```http
GET /api/decision/workspace/aggregated/?account_id=account_1&include_executed=false
```

**参数**:
| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| account_id | string | 否 | 账户 ID（不传则获取全部） |
| include_executed | boolean | 否 | 是否包含已执行的建议（默认 false） |

**响应**:
```json
{
  "success": true,
  "data": {
    "aggregated_recommendations": [
      {
        "aggregation_key": "account_1:000001.SH:BUY",
        "security_code": "000001.SH",
        "security_name": "平安银行",
        "side": "BUY",
        "confidence": 0.85,
        "valuation_snapshot_id": "vs_abc123",
        "price_range": {
          "entry_low": 10.50,
          "entry_high": 11.00,
          "target_low": 13.00,
          "target_high": 14.50,
          "stop_loss": 9.50
        },
        "position_suggestion": {
          "suggested_pct": 5.0,
          "suggested_quantity": 500,
          "max_capital": 50000
        },
        "risk_checks": {
          "beta_gate": {"passed": true, "reason": ""},
          "quota": {"passed": true, "remaining": 5},
          "cooldown": {"passed": true, "hours_remaining": 0}
        },
        "source_recommendation_ids": ["rec_1", "rec_2"],
        "reason_codes": ["PMI_RECOVERY", "VALUATION_LOW"],
        "human_readable_rationale": "PMI连续回升，估值处于历史低位...",
        "regime_source": "V2_CALCULATION"
      }
    ],
    "regime_context": {
      "current_regime": "Recovery",
      "confidence": 0.72,
      "source": "V2_CALCULATION"
    }
  }
}
```

---

### 预览执行详情

在审批前预览执行详情，包括风控检查结果。

**请求**:
```http
POST /api/decision/execute/preview/
Content-Type: application/json

{
  "recommendation_id": "rec_001",
  "account_id": "account_1",
  "market_price": 10.80
}
```

**参数**:
| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| recommendation_id | string | 是 | 投资建议 ID |
| account_id | string | 是 | 账户 ID |
| market_price | number | 否 | 当前市场价格（可选） |

**响应**:
```json
{
  "success": true,
  "data": {
    "request_id": "apr_001",
    "recommendation_id": "rec_001",
    "valuation_snapshot_id": "vs_abc123",
    "preview": {
      "recommendation_id": "rec_001",
      "account_id": "account_1",
      "security_code": "000001.SH",
      "side": "BUY",
      "confidence": 0.85,
      "fair_value": "12.50",
      "suggested_quantity": 500,
      "market_price": 10.80,
      "price_range": {
        "entry_low": "10.50",
        "entry_high": "11.00",
        "target_low": "13.00",
        "target_high": "14.50",
        "stop_loss": "9.50"
      },
      "position_suggestion": {
        "suggested_pct": 5.0,
        "suggested_quantity": 500,
        "max_capital": "50000"
      },
      "regime_source": "V2_CALCULATION"
    },
    "risk_checks": {
      "price_validation": {
        "passed": true,
        "reason": ""
      },
      "beta_gate": {
        "passed": true,
        "reason": ""
      },
      "quota": {
        "passed": true,
        "remaining": 5,
        "reason": ""
      },
      "cooldown": {
        "passed": true,
        "hours_remaining": 0,
        "reason": ""
      }
    }
  }
}
```

**错误响应**:
```json
{
  "success": false,
  "error": "Recommendation not found: rec_001"
}
```

---

### 批准执行

批准执行审批请求。

**请求**:
```http
POST /api/decision/execute/approve/
Content-Type: application/json

{
  "approval_request_id": "apr_001",
  "reviewer_comments": "审批通过，市场环境符合预期",
  "market_price": 10.80
}
```

**参数**:
| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| approval_request_id | string | 是 | 执行审批请求 ID |
| reviewer_comments | string | 否 | 审批评论 |
| market_price | number | 否 | 审批时的市场价格 |

**响应**:
```json
{
  "success": true,
  "data": {
    "request_id": "apr_001",
    "recommendation_id": "rec_001",
    "account_id": "account_1",
    "security_code": "000001.SH",
    "side": "BUY",
    "approval_status": "APPROVED",
    "reviewer_comments": "审批通过，市场环境符合预期",
    "reviewed_at": "2026-03-02T10:30:00Z"
  }
}
```

**错误响应**:
```json
{
  "success": false,
  "error": "Cannot approve: market price 12.00 exceeds entry price high 11.00"
}
```

---

### 拒绝执行

拒绝执行审批请求。

**请求**:
```http
POST /api/decision/execute/reject/
Content-Type: application/json

{
  "approval_request_id": "apr_001",
  "reviewer_comments": "市场波动过大，风险不可控"
}
```

**参数**:
| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| approval_request_id | string | 是 | 执行审批请求 ID |
| reviewer_comments | string | 是 | 拒绝原因 |

**响应**:
```json
{
  "success": true,
  "data": {
    "request_id": "apr_001",
    "recommendation_id": "rec_001",
    "account_id": "account_1",
    "security_code": "000001.SH",
    "side": "BUY",
    "approval_status": "REJECTED",
    "reviewer_comments": "市场波动过大，风险不可控",
    "reviewed_at": "2026-03-02T10:30:00Z"
  }
}
```

---

### 获取执行状态

获取指定执行审批请求的状态。

**请求**:
```http
GET /api/decision/execute/apr_001/
```

**响应**:
```json
{
  "success": true,
  "data": {
    "request_id": "apr_001",
    "recommendation_id": "rec_001",
    "account_id": "account_1",
    "security_code": "000001.SH",
    "security_name": "平安银行",
    "side": "BUY",
    "approval_status": "APPROVED",
    "suggested_quantity": 500,
    "market_price_at_review": 10.80,
    "price_range": {
      "low": 10.50,
      "high": 11.00,
      "stop_loss": 9.50
    },
    "risk_check_results": {
      "beta_gate": {"passed": true},
      "quota": {"passed": true, "remaining": 5},
      "cooldown": {"passed": true}
    },
    "reviewer_comments": "审批通过",
    "regime_source": "V2_CALCULATION",
    "created_at": "2026-03-02T09:00:00Z",
    "reviewed_at": "2026-03-02T10:30:00Z",
    "executed_at": null
  }
}
```

---

## 错误码

| 错误码 | HTTP 状态码 | 描述 |
|--------|------------|------|
| `VALUATION_001` | 400 | 无法获取当前价格 |
| `VALUATION_002` | 404 | 估值快照不存在 |
| `RECOMMENDATION_001` | 404 | 投资建议不存在 |
| `APPROVAL_001` | 400 | 无法批准：价格超出区间 |
| `APPROVAL_002` | 400 | 无法批准：风控检查未通过 |
| `APPROVAL_003` | 400 | 无法批准：状态不正确 |
| `APPROVAL_004` | 404 | 审批请求不存在 |
| `APPROVAL_005` | 409 | 已存在待审批请求 |
| `APPROVAL_006` | 400 | 无法拒绝：状态不正确 |

---

## 速率限制

| 端点 | 限制 |
|------|------|
| `/api/valuation/recalculate/` | 10 次/分钟 |
| 其他端点 | 100 次/分钟 |

---

## 更新历史

| 日期 | 版本 | 更新内容 |
|------|------|----------|
| 2026-03-02 | V1.0 | 初始版本 |
