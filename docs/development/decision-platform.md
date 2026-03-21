# 决策平台开发文档

> **版本**: 1.0
> **更新日期**: 2026-02-05
> **模块**: Beta Gate, Alpha Trigger, Decision Rhythm

---

## 一、架构概述

决策平台采用严格的**四层架构**，确保代码的可维护性和可测试性。

### 1.1 架构分层

```
┌─────────────────────────────────────────────────────────┐
│                    Interface 层                         │
│  (views.py, serializers.py, urls.py, templates/)       │
│  处理 HTTP 请求/响应，输入验证，输出格式化               │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Application 层                          │
│  (use_cases.py, tasks.py, dtos.py)                     │
│  编排业务流程，依赖注入 Domain 层                        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    Domain 层                             │
│  (entities.py, rules.py, services.py)                   │
│  纯业务逻辑，Python 标准库，无外部依赖                    │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                Infrastructure 层                          │
│  (models.py, repositories.py, adapters/)                 │
│  ORM、外部 API、数据持久化                                │
└─────────────────────────────────────────────────────────┘
```

### 1.2 模块依赖关系

```
decision_rhythm ─────┐
                      ├──→ shared (domain interfaces)
beta_gate ────────────┤
                      │
alpha_trigger ────────┘
                      │
                      ▼
                regime, policy
```

---

## 二、Beta Gate 模块

### 2.1 功能描述

Beta Gate 是基于宏观环境的资产可见性过滤系统，确保投资者不在错误的宏观环境中下注。

### 2.2 Domain 层

#### 实体 (entities.py)

```python
@dataclass(frozen=True)
class GateConfig:
    """闸门配置"""
    config_id: str
    version: int
    is_active: bool
    is_valid: bool
    risk_profile: RiskProfile
    regime_constraint: RegimeConstraint
    policy_constraint: PolicyConstraint
    portfolio_constraint: PortfolioConstraint
    effective_date: Optional[date] = None
    expires_at: Optional[date] = None
```

#### 服务 (services.py)

```python
class GateEvaluator:
    """闸门评估器 - 判断资产是否可见"""

    def evaluate(self, config: GateConfig, asset: Asset,
                 regime: RegimeState, policy: PolicyLevel) -> GateDecision:
        """评估资产是否通过闸门"""
```

### 2.3 Application 层

#### 用例 (use_cases.py)

```python
class EvaluateGateUseCase:
    """评估闸门用例"""

    def execute(self, request: EvaluateGateRequest) -> EvaluateGateResponse:
        """执行闸门评估"""
```

### 2.4 Infrastructure 层

#### 仓储 (repositories.py)

```python
class DjangoGateConfigRepository:
    """Django ORM 实现的配置仓储"""

    def get_all_active(self) -> List[GateConfig]:
        """获取所有活跃配置"""
```

---

## 三、Alpha Trigger 模块

### 3.1 功能描述

Alpha Trigger 提供离散、可证伪、可行动的 Alpha 信号触发机制。

### 3.2 Domain 层

#### 实体 (entities.py)

```python
@dataclass(frozen=True)
class AlphaTrigger:
    """Alpha 触发器"""
    trigger_id: str
    trigger_type: TriggerType
    asset_code: str
    asset_class: str
    direction: Direction
    trigger_condition: Dict[str, Any]
    invalidation_conditions: List[InvalidationCondition]
    strength: SignalStrength
    confidence: float
    status: TriggerStatus
    # ... 其他字段
```

### 3.3 证伪条件系统

#### 条件类型

```python
class InvalidationType(Enum):
    """证伪条件类型"""
    INDICATOR = "indicator"          # 指标穿越
    TIME_DECAY = "time_decay"        # 时间衰减
    REGIME_MISMATCH = "regime"       # Regime 不匹配
    POLICY_CHANGE = "policy"         # 政策变化
    STOP_LOSS = "stop_loss"          # 止损
    TARGET_REACHED = "target"        # 目标达成
```

### 3.4 Application 层

#### 用例 (use_cases.py)

```python
class CreateAlphaTriggerUseCase:
    """创建触发器用例"""

    def execute(self, request: CreateTriggerRequest) -> CreateTriggerResponse:
        """创建新的 Alpha 触发器"""

class CheckTriggerInvalidationUseCase:
    """检查证伪用例"""

    def execute(self, request: CheckInvalidationRequest) -> CheckInvalidationResponse:
        """检查触发器是否被证伪"""
```

---

## 四、Decision Rhythm 模块

### 4.1 功能描述

Decision Rhythm 通过决策频率约束和配额管理，防止过度交易。

### 4.2 Domain 层

#### 实体 (entities.py)

```python
@dataclass(frozen=True)
class DecisionQuota:
    """决策配额"""
    quota_id: str
    period: QuotaPeriod
    max_decisions: int
    used_decisions: int
    max_executions: int
    used_executions: int
    period_start: datetime
    is_active: bool
```

### 4.3 配额周期

```python
class QuotaPeriod(Enum):
    """配额周期"""
    DAILY = "DAILY"       # 每日
    WEEKLY = "WEEKLY"     # 每周
    MONTHLY = "MONTHLY"   # 每月
```

### 4.4 冷却期管理

```python
@dataclass(frozen=True)
class CooldownPeriod:
    """冷却期"""
    cooldown_id: str
    asset_code: str
    direction: Optional[Direction]
    cooldown_hours: int
    start_time: datetime
    status: CooldownStatus
```

---

## 五、API 端点清单

### 5.1 Beta Gate API

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/beta-gate/configs/` | 获取所有配置 |
| GET | `/api/beta-gate/configs/{id}/` | 获取指定配置 |
| POST | `/api/beta-gate/test/` | 测试资产 |
| GET | `/api/beta-gate/version/compare/` | 版本对比 |
| POST | `/api/beta-gate/config/rollback/` | 回滚配置 |

### 5.2 Alpha Trigger API

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/alpha-triggers/triggers/` | 获取触发器列表 |
| POST | `/api/alpha-triggers/create/` | 创建触发器 |
| GET | `/api/alpha-triggers/triggers/{id}/` | 获取触发器详情 |
| POST | `/api/alpha-triggers/check-invalidation/` | 检查证伪 |
| GET | `/api/alpha-triggers/performance/` | 性能统计 |

### 5.3 Decision Rhythm API

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/decision-rhythm/quotas/` | 获取配额列表 |
| GET | `/api/decision-rhythm/cooldowns/` | 获取冷却期列表 |
| GET | `/api/decision-rhythm/requests/` | 获取决策请求列表 |
| GET | `/api/decision-rhythm/requests/{id}/` | 获取决策请求详情 |
| POST | `/api/decision-rhythm/submit/` | 提交决策请求 |
| POST | `/api/decision-rhythm/submit-batch/` | 批量提交决策请求 |
| POST | `/api/decision-rhythm/requests/{id}/execute/` | 执行决策请求 |
| POST | `/api/decision-rhythm/requests/{id}/cancel/` | 取消决策请求 |
| POST | `/api/decision-rhythm/reset-quota/` | 重置配额 |
| GET/POST | `/api/decision-rhythm/summary/` | 获取决策摘要 |
| GET/POST | `/api/decision-rhythm/trend-data/` | 趋势数据 |

### 5.4 Decision Workflow API（V3.4+ 新增）

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/decision-workflow/precheck/` | 决策预检查 |
| POST | `/api/decision-workflow/check-beta-gate/` | 检查 Beta Gate |
| POST | `/api/decision-workflow/check-quota/` | 检查配额状态 |
| POST | `/api/decision-workflow/check-cooldown/` | 检查冷却期 |

---

## 六、数据模型

### 6.1 Beta Gate 数据表

```sql
-- GateConfig 表
CREATE TABLE beta_gate_config (
    config_id VARCHAR(64) PRIMARY KEY,
    version INT NOT NULL,
    risk_profile VARCHAR(32) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    regime_constraints JSON,
    policy_constraints JSON,
    portfolio_constraints JSON,
    effective_date DATE,
    expires_at DATE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### 6.2 Alpha Trigger 数据表

```sql
-- AlphaTrigger 表
CREATE TABLE alpha_trigger (
    trigger_id VARCHAR(64) PRIMARY KEY,
    trigger_type VARCHAR(32) NOT NULL,
    asset_code VARCHAR(32) NOT NULL,
    asset_class VARCHAR(32) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    trigger_condition JSON,
    invalidation_conditions JSON,
    strength VARCHAR(16),
    confidence FLOAT,
    status VARCHAR(16),
    created_at TIMESTAMP,
    expires_at TIMESTAMP,
    related_regime VARCHAR(32),
    related_policy_level INT
);
```

### 6.3 Decision Rhythm 数据表

```sql
-- DecisionQuota 表
CREATE TABLE decision_quota (
    quota_id VARCHAR(64) PRIMARY KEY,
    period VARCHAR(16) NOT NULL,
    max_decisions INT NOT NULL,
    used_decisions INT DEFAULT 0,
    max_execution_count INT NOT NULL,
    period_start TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);
```

---

## 七、开发规范

### 7.1 Domain 层约束

```python
# ✅ 允许
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum
from abc import ABC, abstractmethod

# ❌ 禁止
import django  # 任何 django.* 模块
import pandas  # 任何 pandas 模块
import requests  # 任何外部 API
```

### 7.2 依赖注入

```python
# Application 层必须通过依赖注入使用 Domain 层
class EvaluateGateUseCase:
    def __init__(self, config_selector: ConfigSelectorProtocol):
        self.config_selector = config_selector
```

### 7.3 测试要求

- Domain 层覆盖率 ≥ 90%
- Application 层覆盖率 ≥ 80%
- 集成测试覆盖关键工作流

---

## 八、常见问题

### Q1: 如何添加新的证伪条件类型？

1. 在 `InvalidationType` 枚举中添加新类型
2. 在 `InvalidationCondition` 实体中添加对应字段
3. 在 `TriggerInvalidator` 服务中实现检查逻辑
4. 更新序列化器和表单

### Q2: 如何扩展配额周期？

1. 在 `QuotaPeriod` 枚举中添加新周期
2. 更新 `DecisionQuota` 实体
3. 修改 `QuotaManager` 中的周期处理逻辑
4. 更新 Admin 界面和 API

### Q3: 如何集成新的数据源？

1. 在 Infrastructure 层创建新的 Adapter
2. 实现 Protocol 接口
3. 在 Use Case 中通过依赖注入使用
4. 编写集成测试验证

---

## 九、参考文档

- [AgomTradePro V3.4 总体架构](../business/AgomTradePro_V3.4.md)
- [四层架构规范](../../CLAUDE.md)
- [API 文档](/api/docs/)
- [测试指南](../../tests/README.md)
