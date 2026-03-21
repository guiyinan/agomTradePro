# 决策工作流使用指南

> **版本**: 1.0
> **更新日期**: 2026-03-01
> **适用版本**: AgomTradePro V3.4+

---

## 概述

决策工作流是 AgomTradePro 系统的核心执行链路，将 Alpha 候选转化为可执行的投资决策，并支持落地到模拟盘或账户持仓记录。

### 核心功能

1. **预检查**: 在提交决策前检查各项准入条件
2. **决策提交**: 将候选转化为决策请求
3. **执行落地**: 将决策执行到模拟盘或账户记录
4. **状态追踪**: 实时追踪决策执行状态

---

## 主流程

```
首页 -> 选择候选 -> 预检查 -> 提交决策 -> 执行落地 -> 状态回写
```

### 步骤详解

1. **选择候选**: 从首页选择状态为 `ACTIONABLE` 的 Alpha 候选
2. **预检查**: 系统自动检查四项条件
3. **提交决策**: 通过检查后提交决策请求
4. **执行落地**: 选择执行目标（模拟盘/账户记录）
5. **状态回写**: 系统自动更新候选和决策状态

---

## 预检查 API

### 接口说明

`POST /api/decision-workflow/precheck/`

### 检查项

| 检查项 | 说明 | 失败处理 |
|--------|------|----------|
| Beta Gate | 资产是否通过宏观环境准入 | 等待环境变化或选择其他资产 |
| 配额 | 决策次数是否充足 | 等待配额重置或申请提额 |
| 冷却期 | 是否在交易冷却期外 | 等待冷却期结束 |
| 候选状态 | 候选是否仍为 ACTIONABLE | 选择其他候选 |

### 请求示例

```bash
curl -X POST /api/decision-workflow/precheck/ \
  -H "Authorization: Token your_token" \
  -H "Content-Type: application/json" \
  -d '{"candidate_id": "cand_xxx"}'
```

### 响应示例

```json
{
  "success": true,
  "result": {
    "candidate_id": "cand_xxx",
    "beta_gate_passed": true,
    "quota_ok": true,
    "cooldown_ok": true,
    "candidate_valid": true,
    "warnings": [],
    "errors": []
  }
}
```

### 错误处理

- `errors` 非空时表示存在阻断性问题，不可继续提交
- `warnings` 非空时表示存在警告，可继续但需谨慎

---

## 决策提交 API

### 接口说明

`POST /api/decision-rhythm/submit/`

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| asset_code | string | 是 | 资产代码 |
| asset_class | string | 是 | 资产类别 |
| direction | string | 是 | 交易方向（BUY/SELL） |
| priority | string | 否 | 优先级（LOW/MEDIUM/HIGH） |
| candidate_id | string | 否 | 关联的 Alpha 候选 ID |
| execution_target | string | 否 | 执行目标（NONE/SIMULATED/ACCOUNT） |
| reason | string | 否 | 决策原因 |
| expected_confidence | float | 否 | 预期置信度 |

### 请求示例

```bash
curl -X POST /api/decision-rhythm/submit/ \
  -H "Authorization: Token your_token" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_code": "000001.SH",
    "asset_class": "a_share",
    "direction": "BUY",
    "priority": "HIGH",
    "candidate_id": "cand_xxx",
    "execution_target": "SIMULATED",
    "reason": "来源候选 cand_xxx"
  }'
```

---

## 决策执行 API

### 接口说明

`POST /api/decision-rhythm/requests/{request_id}/execute/`

### 权限要求

仅以下角色可执行：
- admin
- owner
- investment_manager

> **注意**: analyst 角色仅可预检查和提交，不可执行落地

### 执行目标

#### 1. 模拟盘执行 (SIMULATED)

将决策执行到模拟盘账户，生成模拟交易记录。

```json
{
  "target": "SIMULATED",
  "sim_account_id": 1,
  "asset_code": "000001.SH",
  "action": "buy",
  "quantity": 1000,
  "price": 12.35,
  "reason": "按决策请求执行"
}
```

#### 2. 账户记录 (ACCOUNT)

将决策记录到账户持仓，用于追踪实盘持仓。

```json
{
  "target": "ACCOUNT",
  "portfolio_id": 9,
  "asset_code": "000001.SH",
  "shares": 1000,
  "avg_cost": 12.35,
  "current_price": 12.35,
  "reason": "按决策请求落地持仓"
}
```

### 响应示例

```json
{
  "success": true,
  "result": {
    "request_id": "req_xxx",
    "execution_status": "EXECUTED",
    "executed_at": "2026-03-01T10:00:00+08:00",
    "execution_ref": {
      "trade_id": "trd_xxx",
      "account_id": 1
    },
    "candidate_status": "EXECUTED"
  }
}
```

---

## 状态机

### DecisionRequest 状态

```
PENDING -> EXECUTED (执行成功)
        -> FAILED    (执行失败)
        -> CANCELLED (手动取消)
```

### AlphaCandidate 状态

```
CANDIDATE -> ACTIONABLE -> EXECUTED (仅通过执行 API)
                        -> CANCELLED
          -> INVALIDATED
          -> EXPIRED
```

### 硬约束

1. 候选不能通过"状态按钮"直接标记为 `EXECUTED`
2. 必须通过执行 API 完成落地
3. 执行成功后系统自动回写候选状态

---

## SDK 使用示例

### Python SDK

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient()

# 1. 预检查
precheck_result = client.decision_workflow.precheck("cand_xxx")
if not precheck_result["result"]["beta_gate_passed"]:
    print("Beta Gate 未通过")
    exit(1)

# 2. 提交决策
submit_result = client.decision_rhythm.submit({
    "asset_code": "000001.SH",
    "asset_class": "a_share",
    "direction": "BUY",
    "candidate_id": "cand_xxx",
    "execution_target": "SIMULATED"
})
request_id = submit_result["request_id"]

# 3. 执行决策
execute_result = client.decision_rhythm.execute_request(
    request_id,
    {
        "target": "SIMULATED",
        "sim_account_id": 1,
        "asset_code": "000001.SH",
        "action": "buy",
        "quantity": 1000,
        "reason": "按决策请求执行"
    }
)
print(f"执行状态: {execute_result['result']['execution_status']}")
```

---

## MCP 工具

### decision_workflow_precheck

执行决策预检查。

```json
{
  "name": "decision_workflow_precheck",
  "arguments": {
    "candidate_id": "cand_xxx"
  }
}
```

### decision_execute_request

执行决策请求（需要执行权限）。

```json
{
  "name": "decision_execute_request",
  "arguments": {
    "request_id": "req_xxx",
    "payload": {
      "target": "SIMULATED",
      "sim_account_id": 1,
      "asset_code": "000001.SH",
      "action": "buy",
      "quantity": 1000
    }
  }
}
```

---

## 常见问题

### Q1: 预检查失败怎么办？

根据 `errors` 字段判断失败原因：
- **Beta Gate 未通过**: 等待宏观环境变化或选择其他资产
- **配额不足**: 等待配额重置（周期结束自动重置）
- **冷却期中**: 等待冷却期结束
- **候选无效**: 候选已被执行或取消，选择其他候选

### Q2: analyst 角色可以执行决策吗？

不可以。analyst 仅可预检查和提交决策，执行落地需要 admin、owner 或 investment_manager 权限。

### Q3: 执行失败后可以重试吗？

可以。执行失败后 `execution_status` 为 `FAILED`，可以通过工作台的"失败重试"功能重新执行。

### Q4: 如何取消待执行的决策？

调用取消 API：`POST /api/decision-rhythm/requests/{request_id}/cancel/`

---

## 相关文档

- [决策平台开发文档](../../development/decision-platform.md)
- [API 参考文档](../testing/api/API_REFERENCE.md)
- [SDK 文档](../../sdk/README.md)
