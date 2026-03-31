# AgomTradePro 决策平面改造

## 实施方案 v1.1

> **文档版本**：v1.1
> **更新日期**：2026-02-03
> **状态**：READY FOR IMPLEMENTATION
> **适用系统**：AgomTradePro V3.4+
> **设计目标**：**Hard Beta Gate / Discrete Alpha / Sparse Decision**

---

## 一、背景与问题定义（PRD）

### 1.1 背景

AgomTradePro 当前已具备：

* 严格的 **Regime + Policy** 宏观过滤
* PIT 数据、防后视偏差、完整回测与风控
* 多维度资产评分与模拟交易验证

系统目标已经达到：

> **"不在错误的宏观环境中下注"**

但在**"如何只关注能赚钱的信息"**这一目标上，仍存在结构性不足。

### 1.2 核心问题

#### P1：Beta 约束是"软"的
* Regime / Policy 主要通过**评分、权重、暂停逻辑**影响结果
* 不满足 Beta 的资产仍会出现在筛选结果和 Dashboard 中
* **结果**：信息负担大，注意力被稀释

#### P2：Alpha 信号被"平均化"
* 多维评分体系天然倾向"折中解"
* 缺少 **离散、结构性、强不对称** 的 Alpha 触发事件
* **结果**：系统很稳健，但很少"必须出手"

#### P3：缺乏决策稀疏度控制
* 系统每天可产生大量"可看项"
* 没有"本周只允许 1–3 个候选"的工程化约束
* **结果**：系统勤奋，但决策效率低

---

## 二、产品目标（PRD）

### 2.1 总体目标

构建一个**决策平面（Decision Plane）**，使系统具备以下能力：

1. **Beta Gate（硬闸门）**：明确哪些资产/策略 **在当前宏观环境下"不可见"**
2. **Alpha Trigger（离散触发）**：只在出现结构性错位时产出 **少量、可证伪、可行动的 Alpha 候选**
3. **Decision Rhythm（稀疏决策）**：工程化限制每周/每月的"可决策数量"

### 2.2 成功判定标准

| 指标 | 目标 |
|------|------|
| 默认资产候选数量 | ↓ ≥ 60% |
| 每周 AlphaCandidate | ≤ 3 |
| 每周 Actionable | ≤ 1 |
| Alpha 事件证伪覆盖率 | 100% |
| "无 Alpha" 周期 | 明确展示为正常状态 |

---

## 三、系统总体架构（TDD）

### 3.1 三层过滤机制

```
原始信号
    ↓
┌─────────────────────────────────────┐
│  Beta Gate (硬闸门)                  │
│  - Regime 匹配检查                   │
│  - Policy 档位否决                   │
│  - 风险画像适配性                    │
│  - 置信度阈值过滤                    │
└─────────────────────────────────────┘
    ↓ (通过)
┌─────────────────────────────────────┐
│  Alpha Trigger (离散触发)            │
│  - 事件驱动检测                      │
│  - 结构化证伪验证                    │
│  - 信号强度评分                      │
└─────────────────────────────────────┘
    ↓ (触发)
┌─────────────────────────────────────┐
│  Decision Rhythm (稀疏决策)          │
│  - 决策配额管理                      │
│  - 冷却期控制                        │
│  - 决策优先级排序                    │
└─────────────────────────────────────┘
    ↓
执行决策
```

### 3.2 模块依赖关系

```
┌──────────────┐
│   events     │  事件总线 (新模块)
│   (shared)   │
└──────┬───────┘
       │ 发布/订阅
       ├─────────────────────────────────┐
       │                                 │
┌──────▼────────┐              ┌────────▼──────┐
│  beta_gate    │              │ alpha_trigger │
│  (新模块)      │              │  (新模块)      │
└──────┬────────┘              └────────┬──────┘
       │                                │
       │                                │
┌──────▼────────┐              ┌────────▼──────┐
│ decision_     │              │ 现有模块:      │
│ rhythm        │◄─────────────│ signal        │
│ (新模块)       │              │ regime        │
└───────────────┘              │ policy        │
                               │ audit         │
                               └───────────────┘
```

### 3.3 新增业务域

```
apps/
├─ beta_gate/          # Beta 闸门（可见性裁剪）
├─ alpha_trigger/      # Alpha 离散触发
├─ decision_rhythm/    # 决策节律与配额
└─ events/             # 领域事件（Domain Events）
```

---

## 四、Domain 层设计

### 4.1 `apps/beta_gate/domain/entities.py`

```python
"""Beta Gate Domain Entities - 硬闸门过滤的实体定义"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional, List, Dict, Any


class GateStatus(Enum):
    """闸门状态"""
    PASSED = "passed"
    BLOCKED_REGIME = "blocked_regime"
    BLOCKED_POLICY = "blocked_policy"
    BLOCKED_RISK = "blocked_risk"
    BLOCKED_CONFIDENCE = "blocked_confidence"
    BLOCKED_PORTFOLIO = "blocked_portfolio"


class RiskProfile(Enum):
    """风险画像"""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


@dataclass(frozen=True)
class RegimeConstraint:
    """Regime 约束配置"""
    allowed_regimes: List[str]     # 允许的 Regime 列表
    min_confidence: float          # 最低置信度
    require_high_confidence: bool  # 是否要求高置信度(>0.5)

    def is_regime_allowed(self, regime: str, confidence: float) -> tuple[bool, str]:
        """检查 Regime 是否允许"""
        if regime not in self.allowed_regimes:
            return False, f"Regime {regime} 不在允许列表中"
        if confidence < self.min_confidence:
            return False, f"置信度 {confidence:.2f} 低于阈值 {self.min_confidence}"
        if self.require_high_confidence and confidence <= 0.5:
            return False, f"要求高置信度，当前仅 {confidence:.2f}"
        return True, ""


@dataclass(frozen=True)
class PolicyConstraint:
    """Policy 约束配置"""
    max_allowed_level: int         # 最高允许档位 (0-3)
    veto_on_p3: bool = True        # P3 档位自动否决

    def is_policy_allowed(self, policy_level: int) -> tuple[bool, str]:
        """检查 Policy 是否允许"""
        if self.veto_on_p3 and policy_level >= 3:
            return False, f"P3 档位自动否决"
        if policy_level > self.max_allowed_level:
            return False, f"Policy 档位 {policy_level} 超过最大允许 {self.max_allowed_level}"
        return True, ""


@dataclass(frozen=True)
class PortfolioConstraint:
    """组合约束配置"""
    max_total_position_pct: float = 95.0
    max_single_position_pct: float = 20.0
    max_correlated_exposure: float = 60.0
    require_diversification: bool = True


@dataclass(frozen=True)
class GateDecision:
    """闸门决策结果"""
    status: GateStatus
    asset_code: str
    asset_class: str
    current_regime: str
    policy_level: int
    regime_confidence: float
    evaluated_at: datetime
    regime_check: tuple[bool, str] = (True, "")
    policy_check: tuple[bool, str] = (True, "")
    risk_check: tuple[bool, str] = (True, "")
    portfolio_check: tuple[bool, str] = (True, "")
    suggested_alternatives: List[str] = field(default_factory=list)
    waiting_period_days: Optional[int] = None

    @property
    def is_passed(self) -> bool:
        return self.status == GateStatus.PASSED

    @property
    def blocking_reason(self) -> str:
        """获取拦截原因"""
        checks = [
            ("Regime", self.regime_check),
            ("Policy", self.policy_check),
            ("Risk", self.risk_check),
            ("Portfolio", self.portfolio_check),
        ]
        for name, (passed, reason) in checks:
            if not passed:
                return f"[{name}] {reason}"
        return "未知原因"


@dataclass(frozen=True)
class GateConfig:
    """闸门全局配置"""
    regime_constraint: RegimeConstraint
    policy_constraint: PolicyConstraint
    portfolio_constraint: PortfolioConstraint
    risk_profile: RiskProfile
    config_id: str
    version: int = 1
    is_active: bool = True
    effective_date: date = field(default_factory=date.today)
```

### 4.2 `apps/alpha_trigger/domain/entities.py`

```python
"""Alpha Trigger Domain Entities - 事件驱动的 Alpha 信号触发机制"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any


class TriggerType(Enum):
    """触发器类型"""
    THRESHOLD_CROSS = "threshold_cross"
    MOMENTUM_SIGNAL = "momentum_signal"
    REGIME_TRANSITION = "regime_transition"
    POLICY_CHANGE = "policy_change"
    MANUAL_OVERRIDE = "manual_override"


class TriggerStatus(Enum):
    """触发器状态"""
    ACTIVE = "active"
    TRIGGERED = "triggered"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class SignalStrength(Enum):
    """信号强度"""
    WEAK = "weak"               # 0-0.3
    MODERATE = "moderate"       # 0.3-0.6
    STRONG = "strong"           # 0.6-0.8
    VERY_STRONG = "very_strong" # 0.8-1.0


@dataclass(frozen=True)
class InvalidationCondition:
    """证伪条件（结构化）"""
    condition_type: str         # "threshold_cross", "time_decay", "regime_mismatch"
    indicator_code: Optional[str] = None
    threshold_value: Optional[float] = None
    cross_direction: Optional[str] = None     # "above", "below"
    max_holding_days: Optional[int] = None
    required_regime: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "condition_type": self.condition_type,
            "indicator_code": self.indicator_code,
            "threshold_value": self.threshold_value,
            "cross_direction": self.cross_direction,
            "max_holding_days": self.max_holding_days,
            "required_regime": self.required_regime,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InvalidationCondition":
        return cls(**data)


@dataclass(frozen=True)
class AlphaTrigger:
    """Alpha 触发器实体"""
    trigger_id: str
    trigger_type: TriggerType
    asset_code: str
    asset_class: str
    direction: str              # LONG, SHORT
    trigger_condition: Dict[str, Any]
    invalidation_conditions: List[InvalidationCondition]
    strength: SignalStrength
    confidence: float           # 0-1
    created_at: datetime
    expires_at: Optional[datetime] = None
    status: TriggerStatus = TriggerStatus.ACTIVE
    triggered_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    source_signal_id: Optional[str] = None
    related_regime: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.status == TriggerStatus.ACTIVE

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


@dataclass(frozen=True)
class TriggerEvent:
    """触发事件"""
    event_id: str
    trigger_id: str
    event_type: str            # "triggered", "invalidated", "expired"
    occurred_at: datetime
    trigger_value: Optional[float] = None
    indicator_value: Optional[float] = None
    reason: str = ""
    current_regime: Optional[str] = None
    policy_level: Optional[int] = None
```

### 4.3 `apps/decision_rhythm/domain/entities.py`

```python
"""Decision Rhythm Domain Entities - 决策频率约束和配额管理"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any


class DecisionPriority(Enum):
    """决策优先级"""
    CRITICAL = "critical"       # 紧急（如强制平仓）
    HIGH = "high"              # 高（如强信号触发）
    MEDIUM = "medium"          # 中（如正常调仓）
    LOW = "low"                # 低（如优化建议）
    INFO = "info"              # 信息（不执行）


class QuotaPeriod(Enum):
    """配额周期"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass(frozen=True)
class DecisionQuota:
    """决策配额"""
    period: QuotaPeriod
    max_decisions: int         # 最大决策次数
    max_execution_count: int   # 最大执行次数
    used_decisions: int = 0
    used_executions: int = 0
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None

    @property
    def remaining_decisions(self) -> int:
        return max(0, self.max_decisions - self.used_decisions)

    @property
    def remaining_executions(self) -> int:
        return max(0, self.max_execution_count - self.used_executions)

    @property
    def is_quota_exceeded(self) -> bool:
        return self.remaining_decisions <= 0 or self.remaining_executions <= 0

    @property
    def utilization_rate(self) -> float:
        if self.max_decisions == 0:
            return 1.0
        return self.used_decisions / self.max_decisions


@dataclass(frozen=True)
class CooldownPeriod:
    """冷却期配置"""
    asset_code: str
    last_decision_at: Optional[datetime] = None
    last_execution_at: Optional[datetime] = None
    min_decision_interval_hours: int = 24
    min_execution_interval_hours: int = 48
    same_asset_cooldown_hours: int = 72

    @property
    def is_decision_ready(self) -> bool:
        if self.last_decision_at is None:
            return True
        elapsed = (datetime.now() - self.last_decision_at).total_seconds() / 3600
        return elapsed >= self.min_decision_interval_hours

    @property
    def is_execution_ready(self) -> bool:
        if self.last_execution_at is None:
            return True
        elapsed = (datetime.now() - self.last_execution_at).total_seconds() / 3600
        return elapsed >= self.min_execution_interval_hours


@dataclass(frozen=True)
class DecisionRequest:
    """决策请求"""
    request_id: str
    asset_code: str
    asset_class: str
    direction: str              # BUY, SELL
    priority: DecisionPriority
    trigger_id: Optional[str] = None
    reason: str = ""
    expected_confidence: float = 0.0
    quantity: Optional[int] = None
    notional: Optional[float] = None
    requested_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class DecisionResponse:
    """决策响应"""
    request_id: str
    approved: bool
    approval_reason: str
    scheduled_at: Optional[datetime] = None
    estimated_execution_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    wait_until: Optional[datetime] = None
    alternative_suggestions: List[str] = field(default_factory=list)
```

### 4.4 `apps/events/domain/entities.py`

```python
"""Events Domain Entities - 事件总线的核心实体定义"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod


class EventType(Enum):
    """事件类型"""
    # Regime 事件
    REGIME_CHANGED = "regime_changed"
    REGIME_CONFIDENCE_LOW = "regime_confidence_low"

    # Policy 事件
    POLICY_LEVEL_CHANGED = "policy_level_changed"
    POLICY_EVENT_CREATED = "policy_event_created"

    # Signal 事件
    SIGNAL_CREATED = "signal_created"
    SIGNAL_TRIGGERED = "signal_triggered"
    SIGNAL_INVALIDATED = "signal_invalidated"

    # Trigger 事件
    ALPHA_TRIGGER_ACTIVATED = "alpha_trigger_activated"
    ALPHA_TRIGGER_INVALIDATED = "alpha_trigger_invalidated"

    # Gate 事件
    BETA_GATE_BLOCKED = "beta_gate_blocked"
    BETA_GATE_PASSED = "beta_gate_passed"

    # Rhythm 事件
    DECISION_REQUESTED = "decision_requested"
    DECISION_APPROVED = "decision_approved"
    DECISION_REJECTED = "decision_rejected"

    # Portfolio 事件
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_STOPPED = "position_stopped"


@dataclass(frozen=True)
class DomainEvent:
    """领域事件基类"""
    event_id: str
    event_type: EventType
    occurred_at: datetime
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_payload_value(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


class EventHandler(ABC):
    """事件处理器接口"""

    @abstractmethod
    def can_handle(self, event_type: EventType) -> bool:
        pass

    @abstractmethod
    def handle(self, event: DomainEvent) -> None:
        pass


@dataclass(frozen=True)
class EventSubscription:
    """事件订阅"""
    subscription_id: str
    event_type: EventType
    handler: EventHandler
    is_active: bool = True
    filter_criteria: Optional[Dict[str, Any]] = None

    def should_process(self, event: DomainEvent) -> bool:
        if not self.is_active:
            return False
        if event.event_type != self.event_type:
            return False
        if self.filter_criteria:
            for key, value in self.filter_criteria.items():
                if event.payload.get(key) != value:
                    return False
        return True
```

---

## 五、Application 层设计

### 5.1 Beta Gate 用例

```python
"""apps/beta_gate/application/use_cases.py"""

@dataclass
class EvaluateGateRequest:
    asset_code: str
    asset_class: str
    current_regime: str
    regime_confidence: float
    policy_level: int
    current_portfolio_value: float = 0.0
    new_position_value: float = 0.0
    risk_profile: RiskProfile = RiskProfile.BALANCED


@dataclass
class EvaluateGateResponse:
    success: bool
    decision: Optional[GateDecision]
    warnings: List[str]
    error: Optional[str] = None


class EvaluateBetaGateUseCase:
    """评估 Beta Gate 用例"""
    def execute(self, request: EvaluateGateRequest) -> EvaluateGateResponse:
        """执行闸门评估，发布事件"""
        # 1. 执行评估
        # 2. 发布事件
        # 3. 返回结果
```

### 5.2 Alpha Trigger 用例

```python
"""apps/alpha_trigger/application/use_cases.py"""

@dataclass
class CreateTriggerRequest:
    trigger_type: TriggerType
    asset_code: str
    asset_class: str
    direction: str
    trigger_condition: Dict[str, Any]
    invalidation_conditions: List[Dict[str, Any]]
    confidence: float
    expires_in_days: Optional[int] = None


@dataclass
class CreateTriggerResponse:
    success: bool
    trigger: Optional[AlphaTrigger]
    error: Optional[str] = None


class CreateAlphaTriggerUseCase:
    """创建 Alpha 触发器用例"""
    def execute(self, request: CreateTriggerRequest) -> CreateTriggerResponse:
        """创建触发器，保存到仓储，发布事件"""


class CheckTriggerInvalidationUseCase:
    """检查触发器证伪用例"""
    def execute(self, request: CheckInvalidationRequest) -> CheckInvalidationResponse:
        """检查证伪条件，标记过期，发布事件"""
```

### 5.3 Decision Rhythm 用例

```python
"""apps/decision_rhythm/application/use_cases.py"""

@dataclass
class SubmitDecisionRequestRequest:
    asset_code: str
    asset_class: str
    direction: str
    priority: DecisionPriority
    trigger_id: Optional[str] = None
    reason: str = ""
    quantity: Optional[int] = None
    notional: Optional[float] = None


class SubmitDecisionRequestUseCase:
    """提交决策请求用例"""
    def execute(self, request: SubmitDecisionRequestRequest) -> SubmitDecisionRequestResponse:
        """检查配额、冷却期、优先级，批准/拒绝决策"""
```

### 5.4 事件总线用例

```python
"""apps/events/application/use_cases.py"""

class InMemoryEventBus:
    """内存事件总线实现"""
    def subscribe(self, subscription: EventSubscription) -> None:
        """订阅事件"""

    def unsubscribe(self, subscription_id: str) -> None:
        """取消订阅"""

    def publish(self, event: DomainEvent) -> None:
        """发布事件，同步处理"""
```

---

## 六、Infrastructure 层设计

### 6.1 ORM Models

```python
"""apps/beta_gate/infrastructure/models.py"""

class GateConfigModel(models.Model):
    """闸门配置 ORM 模型"""
    config_id = models.CharField(max_length=100, unique=True)
    risk_profile = models.CharField(max_length=20)

    # Regime 约束
    allowed_regimes = models.JSONField(default=list)
    min_confidence = models.FloatField(default=0.3)
    require_high_confidence = models.BooleanField(default=False)

    # Policy 约束
    max_allowed_level = models.IntegerField(default=2)
    veto_on_p3 = models.BooleanField(default=True)

    # 组合约束
    max_total_position_pct = models.FloatField(default=95.0)
    max_single_position_pct = models.FloatField(default=20.0)

    # 元数据
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    effective_date = models.DateField()

    class Meta:
        db_table = 'beta_gate_config'


class GateDecisionLogModel(models.Model):
    """闸门决策日志"""
    asset_code = models.CharField(max_length=50)
    asset_class = models.CharField(max_length=50)
    status = models.CharField(max_length=50)
    current_regime = models.CharField(max_length=50)
    policy_level = models.IntegerField()
    regime_confidence = models.FloatField()
    evaluated_at = models.DateTimeField()
    blocking_reason = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'beta_gate_log'
        indexes = [
            models.Index(fields=['asset_code']),
            models.Index(fields=['evaluated_at']),
            models.Index(fields=['status']),
        ]
```

### 6.2 Repositories

```python
"""apps/beta_gate/infrastructure/repositories.py"""

class DjangoGateConfigRepository:
    """闸门配置仓储"""
    def get_active_config(self, risk_profile: RiskProfile) -> Optional[GateConfig]:
        """获取激活的配置，降级到默认配置"""
```

---

## 七、API 接口设计

### 7.1 Beta Gate API

```http
GET /api/beta-gate/universe/latest
```

返回：
* 当前可见资产类别
* 被硬性排除的资产及原因
* 有效期（TTL）

```http
POST /api/beta-gate/evaluate
```

评估单个资产是否通过闸门

### 7.2 Alpha Trigger API

```http
POST /api/alpha-triggers/create/
GET  /api/alpha-triggers/candidates/?status=
```

### 7.3 Decision Rhythm API

```http
POST /api/decision-rhythm/submit
GET  /api/decision-rhythm/summary/latest
GET  /api/decision-rhythm/quota/weekly
```

---

## 八、集成点设计

### 8.1 事件总线初始化

```python
"""shared/infrastructure/event_bus_initializer.py"""

class EventBusInitializer:
    """事件总线初始化器"""
    @staticmethod
    def setup_subscriptions(event_bus):
        """设置所有订阅"""
        # Beta Gate 订阅 Regime 变化事件
        # Alpha Trigger 订阅 Signal 创建事件
        # Decision Rhythm 订阅所有决策相关事件
```

### 8.2 与现有 Signal 模块集成

```python
"""apps/signal/application/handlers.py"""

class SignalEventHandler(EventHandler):
    """Signal 事件处理器"""
    def handle(self, event: DomainEvent) -> None:
        """处理 Signal 创建事件，自动创建 Alpha Trigger"""
```

---

## 九、Dashboard 要求

### 9.1 必须新增的三个区块

#### 1️⃣ Beta Gate 状态
* 当前 Regime / Policy
* 可见资产类别
* 锁仓 / 观察提示

#### 2️⃣ Alpha 面板
```
WATCH | CANDIDATE | ACTIONABLE
```

#### 3️⃣ 决策配额
* 本期配额
* 已占用
* 剩余额度
* "无 Alpha = 正常状态"提示

---

## 十、实施里程碑

### Phase 1: 基础框架（2-3周）

**目标**：Domain 层实体和事件总线

- [x] `apps/events` 模块 - Domain 层
- [x] `apps/beta_gate` Domain 层 - 实体和服务
- [x] `apps/alpha_trigger` Domain 层 - 实体和服务
- [x] `apps/decision_rhythm` Domain 层 - 实体和服务

**交付物**：
- 完整的 Domain 层实体定义
- 内存事件总线实现
- 单元测试覆盖率 > 90%

### Phase 2: Application 层编排（2-3周）

- [ ] `apps/beta_gate` Application 层 - 用例
- [ ] `apps/alpha_trigger` Application 层 - 用例
- [ ] `apps/decision_rhythm` Application 层 - 用例
- [ ] 事件处理器实现

**交付物**：
- 完整的 Use Case 实现
- 事件处理器集成
- 集成测试

### Phase 3: Infrastructure 层实现（2周）

- [ ] ORM Models 定义
- [ ] Repositories 实现
- [ ] 数据库迁移脚本
- [ ] 配置初始化管理命令

**交付物**：
- 完整的 Infrastructure 层
- 数据库 schema
- 管理命令

### Phase 4: API 接口和 UI（2周）

- [ ] DRF ViewSets
- [ ] API 端点
- [ ] Dashboard 集成
- [ ] 决策历史视图

**交付物**：
- RESTful API
- Dashboard 组件
- API 文档

### Phase 5: 测试和优化（1-2周）

- [ ] 端到端测试
- [ ] 性能优化
- [ ] 文档完善
- [ ] 监控告警

---

## 十一、关键文件清单

### 核心实体定义（Domain 层）
- `apps/beta_gate/domain/entities.py` - 硬闸门核心实体
- `apps/alpha_trigger/domain/entities.py` - Alpha 触发器实体
- `apps/decision_rhythm/domain/entities.py` - 决策配额实体
- `apps/events/domain/entities.py` - 事件总线核心实体

### 业务逻辑（Domain 层）
- `apps/beta_gate/domain/services.py` - Beta Gate 评估算法
- `apps/alpha_trigger/domain/services.py` - 触发器评估算法
- `apps/decision_rhythm/domain/services.py` - 配额管理算法

### 用例编排（Application 层）
- `apps/beta_gate/application/use_cases.py` - 硬闸门用例
- `apps/alpha_trigger/application/use_cases.py` - Alpha 触发用例
- `apps/decision_rhythm/application/use_cases.py` - 决策配额用例

### 现有集成点
- `apps/regime/domain/entities.py` - Regime 实体（已存在）
- `apps/policy/domain/entities.py` - Policy 实体（已存在）
- `apps/signal/domain/entities.py` - Signal 实体（已存在）

---

## 十二、非功能性要求

| 类别 | 要求 |
|------|------|
| 可解释性 | 所有 Gate / Trigger / 降级都有 reason codes |
| 可审计性 | 所有状态变化留痕 |
| 可测试性 | Domain 规则测试 ≥ 80% |
| 性能 | 每日全流程 < 5 min |
| 解耦 | 使用 Domain Events |

---

## 十三、明确非目标

* 不接券商 API
* 不做 ML 自动学习
* 不追求高频

---

## 十四、验收清单（DoD）

* [ ] Beta 不满足的资产 **不可见**
* [ ] AlphaCandidate ≤ 3 / week
* [ ] Actionable ≤ 1 / week
* [ ] 100% Alpha 有证伪条件
* [ ] 全量测试通过，旧模块不回归

---

## 十五、对工程团队的一句话

> **这次改造的目标不是"更聪明"，而是"更少、更硬、更敢于什么都不做"。**
