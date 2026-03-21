# 估值定价引擎业务文档

> **版本**: V1.0
> **最后更新**: 2026-03-02
> **状态**: 实施完成

---

## 概述

估值定价引擎（Valuation Pricing Engine）是 AgomTradePro 系统的核心组件，用于：

1. **估值计算** - 基于多种方法计算证券的公允价值
2. **价格区间生成** - 自动生成入场价、目标价、止损价区间
3. **仓位建议** - 根据风险预算提供仓位建议
4. **执行审批** - 标准化的交易审批流程

---

## 核心概念

### 1. 估值快照 (ValuationSnapshot)

估值快照捕获决策时刻的估值状态，用于后续追溯和审计。

```
┌─────────────────────────────────────────────────────────┐
│                  ValuationSnapshot                      │
├─────────────────────────────────────────────────────────┤
│ snapshot_id: str          # 快照唯一标识               │
│ security_code: str        # 证券代码                   │
│ valuation_method: str     # 估值方法                   │
│ fair_value: Decimal       # 公允价值                   │
│ entry_price_low: Decimal  # 入场价格下限               │
│ entry_price_high: Decimal # 入场价格上限               │
│ target_price_low: Decimal # 目标价格下限               │
│ target_price_high: Decimal# 目标价格上限               │
│ stop_loss_price: Decimal  # 止损价格                   │
│ calculated_at: datetime   # 计算时间                   │
│ input_parameters: dict    # 输入参数                   │
└─────────────────────────────────────────────────────────┘
```

**估值方法**：
- `DCF` - 现金流折现法
- `PE_BAND` - PE 通道法
- `PB_BAND` - PB 通道法
- `PEG` - PEG 估值法
- `DIVIDEND` - 股息折现法
- `COMPOSITE` - 综合估值法

**计算属性**：
- `upside_potential` - 上行空间（%）
- `downside_risk` - 下行风险（%）
- `risk_reward_ratio` - 风险收益比

### 2. 投资建议 (InvestmentRecommendation)

完整的投资建议，包含方向、价格区间、数量建议和风险预算。

```
┌─────────────────────────────────────────────────────────┐
│             InvestmentRecommendation                    │
├─────────────────────────────────────────────────────────┤
│ recommendation_id: str      # 建议唯一标识              │
│ security_code: str          # 证券代码                  │
│ side: str                   # 方向 (BUY/SELL/HOLD)      │
│ confidence: float           # 置信度 (0-1)              │
│ valuation_method: str       # 估值方法                  │
│ fair_value: Decimal         # 公允价值                  │
│ entry_price_low: Decimal    # 入场价格下限              │
│ entry_price_high: Decimal   # 入场价格上限              │
│ target_price_low: Decimal   # 目标价格下限              │
│ target_price_high: Decimal  # 目标价格上限              │
│ stop_loss_price: Decimal    # 止损价格                  │
│ position_size_pct: float    # 建议仓位比例              │
│ max_capital: Decimal        # 最大资金量                │
│ reason_codes: List[str]     # 原因代码列表              │
│ human_readable_rationale: str # 人类可读的理由          │
│ valuation_snapshot_id: str  # 关联的估值快照 ID         │
│ source_recommendation_ids: List[str] # 来源建议 ID      │
│ status: str                 # 建议状态                  │
└─────────────────────────────────────────────────────────┘
```

**建议方向**：
- `BUY` - 买入
- `SELL` - 卖出
- `HOLD` - 持有

**计算属性**：
- `suggested_quantity` - 建议数量（基于入场价中位和最大资金）
- `is_buy` / `is_sell` - 方向判断

**验证方法**：
- `validate_buy_price(market_price)` - 验证买入价格是否在入场区间内
- `validate_sell_price(market_price, triggered_by_risk)` - 验证卖出价格

### 3. 执行审批请求 (ExecutionApprovalRequest)

标准交易审批单，用于执行前的审批流程。

```
┌─────────────────────────────────────────────────────────┐
│            ExecutionApprovalRequest                     │
├─────────────────────────────────────────────────────────┤
│ request_id: str             # 请求唯一标识              │
│ recommendation_id: str      # 关联的投资建议 ID         │
│ account_id: str             # 账户 ID                   │
│ security_code: str          # 证券代码                  │
│ side: str                   # 方向                      │
│ approval_status: ApprovalStatus # 审批状态              │
│ suggested_quantity: int     # 建议数量                  │
│ market_price_at_review: Decimal # 审批时的市场价格      │
│ price_range_low: Decimal    # 价格区间下限              │
│ price_range_high: Decimal   # 价格区间上限              │
│ stop_loss_price: Decimal    # 止损价格                  │
│ risk_check_results: dict    # 风控检查结果              │
│ reviewer_comments: str      # 审批评论                  │
│ regime_source: str          # Regime 来源标识           │
│ created_at: datetime        # 创建时间                  │
│ reviewed_at: datetime       # 审批时间                  │
│ executed_at: datetime       # 执行时间                  │
└─────────────────────────────────────────────────────────┘
```

**审批状态流转**：

```
DRAFT ──→ PENDING ──→ APPROVED ──→ EXECUTED
              │            │
              │            └──→ FAILED
              │
              └──→ REJECTED (终态)

FAILED ──→ PENDING (允许重试)
```

**状态说明**：
- `DRAFT` - 草稿：初始状态
- `PENDING` - 待审批：已提交审批
- `APPROVED` - 已批准：审批通过
- `REJECTED` - 已拒绝：审批拒绝（终态）
- `EXECUTED` - 已执行：执行完成（终态）
- `FAILED` - 执行失败：执行出错

---

## 业务规则

### 1. 价格区间计算规则

```
入场价格区间:
  entry_price_low = fair_value × (1 - tolerance)   # 默认 5% 容差
  entry_price_high = fair_value × (1 + tolerance)

目标价格区间:
  target_price_low = fair_value × (1 + upside × 0.8)
  target_price_high = fair_value × (1 + upside × 1.2)  # 默认 20% 上行

止损价格:
  stop_loss_price = entry_price_low × (1 - stop_loss_pct)  # 默认 10%
```

### 2. 买入审批条件

```python
def can_approve_buy(market_price, entry_price_high):
    return market_price <= entry_price_high
```

**拒绝条件**：
- 市场价格 > 入场价格上限
- 风控检查未通过

### 3. 卖出审批条件

```python
def can_approve_sell(market_price, target_price_low, triggered_by_risk):
    if triggered_by_risk:
        return True  # 风控触发允许任何价格卖出
    return market_price >= target_price_low
```

**拒绝条件**：
- 非风控触发且市场价格 < 目标价格下限
- 风控检查未通过

### 4. 唯一性约束

```
同账户 + 同证券 + 同方向 = 只允许一个 PENDING 请求
```

聚合键格式：`{account_id}:{security_code}:{side}`

### 5. 建议聚合规则

当多个建议具有相同的 `(security_code, side)` 时：

1. **置信度** - 加权平均（按 position_size_pct 加权）
2. **价格区间** - 取并集（扩大范围）
3. **仓位比例** - 累加（有上限 20%）
4. **原因代码** - 取并集
5. **来源 ID** - 收集所有

---

## API 端点

### 估值相关

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/valuation/recalculate/` | POST | 重新计算估值 |
| `/api/valuation/snapshot/{id}/` | GET | 获取估值快照 |

### 决策工作台

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/decision/workspace/aggregated/` | GET | 获取聚合建议 |
| `/api/decision/execute/preview/` | POST | 预览执行详情 |
| `/api/decision/execute/approve/` | POST | 批准执行 |
| `/api/decision/execute/reject/` | POST | 拒绝执行 |
| `/api/decision/execute/{request_id}/` | GET | 获取执行状态 |

### 请求/响应示例

#### 获取聚合工作台

```http
GET /api/decision/workspace/aggregated/?account_id=account_1
```

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
      "confidence": 0.72
    }
  }
}
```

#### 预览执行

```http
POST /api/decision/execute/preview/
Content-Type: application/json

{
  "recommendation_id": "rec_001",
  "account_id": "account_1",
  "market_price": 10.80
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "preview": {
      "recommendation_id": "rec_001",
      "security_code": "000001.SH",
      "side": "BUY",
      "confidence": 0.85,
      "suggested_quantity": 500,
      "market_price": 10.80,
      "price_range": {
        "entry_low": 10.50,
        "entry_high": 11.00,
        "target_low": 13.00,
        "target_high": 14.50,
        "stop_loss": 9.50
      },
      "regime_source": "V2_CALCULATION"
    },
    "risk_checks": {
      "beta_gate": {"passed": true, "reason": ""},
      "quota": {"passed": true, "remaining": 5},
      "cooldown": {"passed": true, "hours_remaining": 0}
    }
  }
}
```

#### 批准执行

```http
POST /api/decision/execute/approve/
Content-Type: application/json

{
  "approval_request_id": "apr_001",
  "reviewer_comments": "审批通过，市场环境符合预期",
  "market_price": 10.80
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "request_id": "apr_001",
    "approval_status": "APPROVED",
    "reviewed_at": "2026-03-02T10:30:00Z"
  }
}
```

---

## 风控检查

### 检查项

| 检查项 | 说明 | 通过条件 |
|--------|------|----------|
| `price_validation` | 价格验证 | BUY: market_price ≤ entry_high; SELL: 总是通过（风控触发时） |
| `quota` | 配额检查 | 配额未耗尽 |
| `cooldown` | 冷却期检查 | 不在冷却期内 |

### 风控结果格式

```json
{
  "risk_checks": {
    "price_validation": {
      "passed": true,
      "reason": ""
    },
    "quota": {
      "passed": true,
      "remaining": 5,
      "reason": ""
    },
    "cooldown": {
      "passed": false,
      "hours_remaining": 2.5,
      "reason": "冷却期内，剩余 2.5 小时"
    }
  }
}
```

---

## Regime 追踪

所有执行审批请求都记录 Regime 来源，用于事后审计和分析。

**Regime 来源标识**：
- `V2_CALCULATION` - V2 版本计算结果
- `MANUAL_OVERRIDE` - 手动覆盖
- `UNKNOWN` - 未知来源

**查询接口**：
```http
GET /api/decision/execute/?regime_source=V2_CALCULATION
```

---

## 数据迁移

### 历史数据回填

对于历史建议，需要创建 legacy 估值快照：

```python
from apps.decision_rhythm.domain.services import ValuationSnapshotService

service = ValuationSnapshotService()

# 为历史建议创建快照
snapshot = service.create_legacy_snapshot(
    security_code="000001.SH",
    estimated_fair_value=Decimal("11.00"),
    current_price=Decimal("10.50"),
)
# snapshot.is_legacy = True
```

### 迁移脚本

```bash
python manage.py backfill_valuations
```

---

## 测试覆盖

### 单元测试

| 测试文件 | 覆盖内容 |
|----------|----------|
| `tests/unit/decision_rhythm/test_valuation_services.py` | 估值快照、审批服务、状态机 |
| `tests/unit/test_decision_rhythm_services.py` | 配额/冷却/节奏管理既有回归 |

### 运行测试

```bash
pytest tests/unit/decision_rhythm/ -v --cov=apps/decision_rhythm
```

---

## 常见问题

### Q1: 为什么买入时价格超出区间会阻止审批？

A: 这是风险控制措施。如果在高于预期的价格买入，会降低潜在收益并增加风险。建议等待价格回落到合理区间。

### Q2: 卖出时为什么允许风控触发？

A: 风控触发的卖出通常是止损或紧急情况，此时不应受目标价格限制，优先保护资本。

### Q3: 建议聚合后如何追溯原始建议？

A: 每个聚合建议都保留 `source_recommendation_ids`，可以追溯所有原始建议。

### Q4: 如何处理历史数据的估值快照？

A: 使用 `create_legacy_snapshot()` 方法创建历史快照，标记 `is_legacy=True`。

---

## 更新历史

| 日期 | 版本 | 更新内容 |
|------|------|----------|
| 2026-03-02 | V1.0 | 初始版本，完成实施 |
