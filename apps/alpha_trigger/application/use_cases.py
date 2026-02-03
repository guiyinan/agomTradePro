"""
Alpha Trigger Application Use Cases

Alpha 事件触发的用例编排层。
负责协调触发器创建、证伪检查和候选生成。

仅依赖 Domain 层和事件总线，不直接依赖 ORM 或外部 API。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..domain.entities import (
    AlphaTrigger,
    AlphaCandidate,
    TriggerConfig,
    TriggerStatus,
    TriggerType,
    SignalStrength,
    InvalidationCondition,
)
from ..domain.services import (
    TriggerEvaluator,
    TriggerInvalidator,
    CandidateGenerator,
    InvalidationCheckResult,
    calculate_strength,
)
from apps.events.domain.entities import DomainEvent, EventType, create_event


logger = logging.getLogger(__name__)


# ========== DTOs ==========


@dataclass
class CreateTriggerRequest:
    """
    创建触发器请求

    Attributes:
        trigger_type: 触发器类型
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向 ("LONG", "SHORT", "NEUTRAL")
        trigger_condition: 触发条件
        invalidation_conditions: 证伪条件列表
        confidence: 置信度 (0-1)
        thesis: 投资论点
        expires_in_days: 过期天数（可选）
        related_regime: 相关 Regime（可选）
        related_policy_level: 相关 Policy 档位（可选）
        source_signal_id: 源信号 ID（可选）
    """

    trigger_type: TriggerType
    asset_code: str
    asset_class: str
    direction: str
    trigger_condition: Dict[str, Any]
    invalidation_conditions: List[Dict[str, Any]]
    confidence: float
    thesis: str = ""
    expires_in_days: Optional[int] = None
    related_regime: Optional[str] = None
    related_policy_level: Optional[int] = None
    source_signal_id: Optional[str] = None


@dataclass
class CreateTriggerResponse:
    """
    创建触发器响应

    Attributes:
        success: 是否成功
        trigger: 创建的触发器
        error: 错误信息
    """

    success: bool
    trigger: Optional[AlphaTrigger] = None
    error: Optional[str] = None


@dataclass
class CheckInvalidationRequest:
    """
    检查证伪请求

    Attributes:
        trigger_id: 触发器 ID
        current_indicator_values: 当前指标值
        current_regime: 当前 Regime
        triggered_at: 触发时间（用于时间衰减检查）
    """

    trigger_id: str
    current_indicator_values: Dict[str, float]
    current_regime: Optional[str] = None
    triggered_at: Optional[datetime] = None


@dataclass
class CheckInvalidationResponse:
    """
    检查证伪响应

    Attributes:
        success: 是否成功
        is_invalidated: 是否被证伪
        reason: 原因
        conditions_met: 满足的条件列表
        error: 错误信息
    """

    success: bool
    is_invalidated: bool = False
    reason: str = ""
    conditions_met: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class EvaluateTriggerRequest:
    """
    评估触发器请求

    Attributes:
        trigger_id: 触发器 ID
        current_data: 当前数据
    """

    trigger_id: str
    current_data: Dict[str, Any]


@dataclass
class EvaluateTriggerResponse:
    """
    评估触发器响应

    Attributes:
        success: 是否成功
        should_trigger: 是否应该触发
        reason: 原因
        error: 错误信息
    """

    success: bool
    should_trigger: bool = False
    reason: str = ""
    error: Optional[str] = None


@dataclass
class GenerateCandidateRequest:
    """
    生成候选请求

    Attributes:
        trigger_id: 触发器 ID
        time_window_days: 时间窗口天数
    """

    trigger_id: str
    time_window_days: int = 90


@dataclass
class GenerateCandidateResponse:
    """
    生成候选响应

    Attributes:
        success: 是否成功
        candidate: Alpha 候选
        error: 错误信息
    """

    success: bool
    candidate: Optional[AlphaCandidate] = None
    error: Optional[str] = None


@dataclass
class GetActiveTriggersRequest:
    """
    获取活跃触发器请求

    Attributes:
        asset_code: 资产代码过滤（可选）
        min_strength: 最小信号强度（可选）
        limit: 返回数量限制（可选）
    """

    asset_code: Optional[str] = None
    min_strength: Optional[SignalStrength] = None
    limit: int = 100


@dataclass
class GetActiveTriggersResponse:
    """
    获取活跃触发器响应

    Attributes:
        success: 是否成功
        triggers: 触发器列表
        error: 错误信息
    """

    success: bool
    triggers: List[AlphaTrigger] = field(default_factory=list)
    error: Optional[str] = None


# ========== Use Cases ==========


class CreateAlphaTriggerUseCase:
    """
    创建 Alpha 触发器用例

    创建新的 Alpha 触发器并发布事件。

    Attributes:
        trigger_repository: 触发器仓储
        config: 触发器配置
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = CreateAlphaTriggerUseCase(repository, config, event_bus)
        >>> response = use_case.execute(CreateTriggerRequest(
        ...     trigger_type=TriggerType.MOMENTUM_SIGNAL,
        ...     asset_code="000001.SH",
        ...     asset_class="a_share金融",
        ...     direction="LONG",
        ...     trigger_condition={"momentum_pct": 0.05},
        ...     invalidation_conditions=[...],
        ...     confidence=0.75
        ... ))
    """

    def __init__(self, trigger_repository, config=None, event_bus=None):
        """
        初始化用例

        Args:
            trigger_repository: 触发器仓储
            config: 触发器配置
            event_bus: 事件总线（可选）
        """
        self.trigger_repository = trigger_repository
        self.config = config or TriggerConfig()
        self.event_bus = event_bus

    def execute(self, request: CreateTriggerRequest) -> CreateTriggerResponse:
        """
        创建触发器

        流程：
        1. 验证请求
        2. 计算信号强度
        3. 转换证伪条件
        4. 创建触发器
        5. 保存到仓储
        6. 发布事件

        Args:
            request: 创建请求

        Returns:
            创建响应
        """
        try:
            # 验证请求
            if not self._validate_request(request):
                return CreateTriggerResponse(
                    success=False,
                    error="Invalid trigger request",
                )

            # 计算信号强度
            strength = self.config.get_strength(request.confidence)

            # 转换证伪条件
            invalidation_conditions = [
                InvalidationCondition.from_dict(c)
                for c in request.invalidation_conditions
            ]

            # 计算过期时间
            expires_at = None
            if request.expires_in_days:
                expires_at = datetime.now() + timedelta(days=request.expires_in_days)

            # 创建触发器
            trigger = AlphaTrigger(
                trigger_id=self._generate_trigger_id(),
                trigger_type=request.trigger_type,
                asset_code=request.asset_code,
                asset_class=request.asset_class,
                direction=request.direction,
                trigger_condition=request.trigger_condition,
                invalidation_conditions=invalidation_conditions,
                strength=strength,
                confidence=request.confidence,
                created_at=datetime.now(),
                expires_at=expires_at,
                status=TriggerStatus.ACTIVE,
                source_signal_id=request.source_signal_id,
                related_regime=request.related_regime,
                related_policy_level=request.related_policy_level,
                thesis=request.thesis,
            )

            # 保存
            saved_trigger = self.trigger_repository.save(trigger)

            # 发布事件
            self._publish_event(saved_trigger)

            logger.info(
                f"Alpha trigger created: {saved_trigger.trigger_id} "
                f"for {saved_trigger.asset_code} ({strength.value})"
            )

            return CreateTriggerResponse(
                success=True,
                trigger=saved_trigger,
            )

        except Exception as e:
            logger.error(f"Failed to create alpha trigger: {e}", exc_info=True)
            return CreateTriggerResponse(
                success=False,
                error=str(e),
            )

    def _validate_request(self, request: CreateTriggerRequest) -> bool:
        """验证请求"""
        if not request.asset_code:
            return False
        if request.direction not in ["LONG", "SHORT", "NEUTRAL"]:
            return False
        if not 0 <= request.confidence <= 1:
            return False
        if not request.trigger_condition:
            return False
        return True

    def _generate_trigger_id(self) -> str:
        """生成触发器 ID"""
        import uuid
        return f"trigger_{uuid.uuid4().hex[:12]}"

    def _publish_event(self, trigger: AlphaTrigger):
        """发布事件"""
        if self.event_bus is None:
            return

        event = create_event(
            event_type=EventType.ALPHA_TRIGGER_ACTIVATED,
            payload={
                "trigger_id": trigger.trigger_id,
                "asset_code": trigger.asset_code,
                "asset_class": trigger.asset_class,
                "trigger_type": trigger.trigger_type.value,
                "direction": trigger.direction,
                "strength": trigger.strength.value,
                "confidence": trigger.confidence,
                "thesis": trigger.thesis,
            },
        )

        self.event_bus.publish(event)


class CheckTriggerInvalidationUseCase:
    """
    检查触发器证伪用例

    检查触发器是否满足证伪条件。

    Attributes:
        trigger_repository: 触发器仓储
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = CheckTriggerInvalidationUseCase(repository, event_bus)
        >>> response = use_case.execute(CheckInvalidationRequest(
        ...     trigger_id="trigger_001",
        ...     current_indicator_values={"CN_PMI_MANUFACTURING": 49.5}
        ... ))
    """

    def __init__(self, trigger_repository, event_bus=None):
        """
        初始化用例

        Args:
            trigger_repository: 触发器仓储
            event_bus: 事件总线（可选）
        """
        self.trigger_repository = trigger_repository
        self.event_bus = event_bus

    def execute(self, request: CheckInvalidationRequest) -> CheckInvalidationResponse:
        """
        检查证伪

        流程：
        1. 获取触发器
        2. 构建当前数据上下文
        3. 检查证伪条件
        4. 如果证伪，更新状态并发布事件

        Args:
            request: 检查请求

        Returns:
            检查响应
        """
        try:
            trigger = self.trigger_repository.get_by_id(request.trigger_id)

            if trigger is None:
                return CheckInvalidationResponse(
                    success=False,
                    error=f"Trigger not found: {request.trigger_id}",
                )

            # 构建当前数据上下文
            current_data = {
                **request.current_indicator_values,
            }

            if request.current_regime:
                current_data["current_regime"] = request.current_regime

            if request.triggered_at:
                current_data["triggered_at"] = request.triggered_at

            # 检查证伪
            invalidator = TriggerInvalidator()
            result = invalidator.check_invalidations(trigger, current_data)

            if result.is_invalidated:
                # 标记为证伪
                updated_trigger = self.trigger_repository.update_status(
                    trigger_id=request.trigger_id,
                    status=TriggerStatus.INVALIDATED,
                    invalidated_at=datetime.now(),
                )

                # 发布事件
                self._publish_invalidation_event(updated_trigger, result)

                logger.info(f"Trigger {request.trigger_id} invalidated: {result.reason}")

            return CheckInvalidationResponse(
                success=True,
                is_invalidated=result.is_invalidated,
                reason=result.reason,
                conditions_met=result.conditions_met,
            )

        except Exception as e:
            logger.error(f"Failed to check trigger invalidation: {e}", exc_info=True)
            return CheckInvalidationResponse(
                success=False,
                error=str(e),
            )

    def _publish_invalidation_event(self, trigger: AlphaTrigger, result: InvalidationCheckResult):
        """发布证伪事件"""
        if self.event_bus is None:
            return

        event = create_event(
            event_type=EventType.ALPHA_TRIGGER_INVALIDATED,
            payload={
                "trigger_id": trigger.trigger_id,
                "asset_code": trigger.asset_code,
                "reason": result.reason,
                "conditions_met": result.conditions_met,
            },
        )

        self.event_bus.publish(event)


class EvaluateAlphaTriggerUseCase:
    """
    评估 Alpha 触发器用例

    评估触发器是否应该触发。

    Attributes:
        trigger_repository: 触发器仓储
        config: 触发器配置
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = EvaluateAlphaTriggerUseCase(repository, config, event_bus)
        >>> response = use_case.execute(EvaluateTriggerRequest(
        ...     trigger_id="trigger_001",
        ...     current_data={"momentum": 0.06}
        ... ))
    """

    def __init__(self, trigger_repository, config=None, event_bus=None):
        """
        初始化用例

        Args:
            trigger_repository: 触发器仓储
            config: 触发器配置
            event_bus: 事件总线（可选）
        """
        self.trigger_repository = trigger_repository
        self.config = config or TriggerConfig()
        self.event_bus = event_bus

    def execute(self, request: EvaluateTriggerRequest) -> EvaluateTriggerResponse:
        """
        评估触发器

        Args:
            request: 评估请求

        Returns:
            评估响应
        """
        try:
            trigger = self.trigger_repository.get_by_id(request.trigger_id)

            if trigger is None:
                return EvaluateTriggerResponse(
                    success=False,
                    error=f"Trigger not found: {request.trigger_id}",
                )

            # 评估触发
            evaluator = TriggerEvaluator(self.config)
            should_trigger, reason = evaluator.should_trigger(trigger, request.current_data)

            if should_trigger:
                # 更新触发器状态
                updated_trigger = self.trigger_repository.update_status(
                    trigger_id=request.trigger_id,
                    status=TriggerStatus.TRIGGERED,
                    triggered_at=datetime.now(),
                )

                # 发布事件
                self._publish_triggered_event(updated_trigger, reason, request.current_data)

                logger.info(f"Trigger {request.trigger_id} fired: {reason}")

            return EvaluateTriggerResponse(
                success=True,
                should_trigger=should_trigger,
                reason=reason,
            )

        except Exception as e:
            logger.error(f"Failed to evaluate trigger: {e}", exc_info=True)
            return EvaluateTriggerResponse(
                success=False,
                error=str(e),
            )

    def _publish_triggered_event(self, trigger: AlphaTrigger, reason: str, current_data: Dict[str, Any]):
        """发布触发事件"""
        if self.event_bus is None:
            return

        event = create_event(
            event_type=EventType.ALPHA_TRIGGER_FIRED,
            payload={
                "trigger_id": trigger.trigger_id,
                "asset_code": trigger.asset_code,
                "asset_class": trigger.asset_class,
                "direction": trigger.direction,
                "strength": trigger.strength.value,
                "reason": reason,
                "current_data": current_data,
            },
        )

        self.event_bus.publish(event)


class GenerateCandidateUseCase:
    """
    生成 Alpha 候选用例

    从触发的触发器生成 Alpha 候选。

    Attributes:
        trigger_repository: 触发器仓储
        candidate_repository: 候选仓储
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = GenerateCandidateUseCase(trigger_repo, candidate_repo, event_bus)
        >>> response = use_case.execute(GenerateCandidateRequest(
        ...     trigger_id="trigger_001"
        ... ))
    """

    def __init__(self, trigger_repository, candidate_repository, event_bus=None):
        """
        初始化用例

        Args:
            trigger_repository: 触发器仓储
            candidate_repository: 候选仓储
            event_bus: 事件总线（可选）
        """
        self.trigger_repository = trigger_repository
        self.candidate_repository = candidate_repository
        self.event_bus = event_bus

    def execute(self, request: GenerateCandidateRequest) -> GenerateCandidateResponse:
        """
        生成候选

        Args:
            request: 生成请求

        Returns:
            生成响应
        """
        try:
            trigger = self.trigger_repository.get_by_id(request.trigger_id)

            if trigger is None:
                return GenerateCandidateResponse(
                    success=False,
                    error=f"Trigger not found: {request.trigger_id}",
                )

            if not trigger.is_triggered:
                return GenerateCandidateResponse(
                    success=False,
                    error=f"Trigger not triggered: {request.trigger_id}",
                )

            # 生成候选
            generator = CandidateGenerator()
            candidate = generator.from_trigger(trigger, request.time_window_days)

            # 保存候选
            saved_candidate = self.candidate_repository.save(candidate)

            # 发布事件
            self._publish_event(saved_candidate)

            logger.info(
                f"Candidate generated: {saved_candidate.candidate_id} "
                f"from trigger {request.trigger_id}"
            )

            return GenerateCandidateResponse(
                success=True,
                candidate=saved_candidate,
            )

        except Exception as e:
            logger.error(f"Failed to generate candidate: {e}", exc_info=True)
            return GenerateCandidateResponse(
                success=False,
                error=str(e),
            )

    def _publish_event(self, candidate: AlphaCandidate):
        """发布事件"""
        if self.event_bus is None:
            return

        event = create_event(
            event_type=EventType.SIGNAL_CREATED,
            payload={
                "candidate_id": candidate.candidate_id,
                "trigger_id": candidate.trigger_id,
                "asset_code": candidate.asset_code,
                "asset_class": candidate.asset_class,
                "direction": candidate.direction,
                "strength": candidate.strength.value,
                "confidence": candidate.confidence,
                "thesis": candidate.thesis,
                "status": candidate.status,
            },
        )

        self.event_bus.publish(event)
