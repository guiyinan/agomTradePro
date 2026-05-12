"""
Alpha Trigger Domain Services

Alpha 事件触发的核心业务逻辑实现。
提供触发器评估、证伪检查和候选生成的算法。

仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .entities import (
    AlphaCandidate,
    AlphaTrigger,
    CandidateStatus,
    InvalidationCondition,
    SignalStrength,
    TriggerConfig,
    TriggerStatus,
    TriggerType,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InvalidationCheckResult:
    """
    证伪检查结果

    Attributes:
        is_invalidated: 是否被证伪
        reason: 证伪原因
        conditions_met: 满足的条件列表
        details: 详细信息
    """

    is_invalidated: bool
    reason: str
    conditions_met: list[str]
    details: dict[str, Any] = field(default_factory=dict)


class TriggerEvaluator:
    """
    触发器评估器

    评估 Alpha 触发器是否应该触发。

    Attributes:
        config: 触发器配置

    Example:
        >>> evaluator = TriggerEvaluator()
        >>> should_trigger, reason = evaluator.should_trigger(trigger, current_data)
    """

    def __init__(self, config: TriggerConfig | None = None):
        """
        初始化评估器

        Args:
            config: 触发器配置
        """
        self.config = config or TriggerConfig()

    def should_trigger(
        self,
        trigger: AlphaTrigger,
        current_data: dict[str, Any],
    ) -> tuple[bool, str]:
        """
        判断触发器是否应该触发

        Args:
            trigger: Alpha 触发器
            current_data: 当前数据（包含指标值等）

        Returns:
            (是否触发, 原因)
        """
        if not trigger.is_active:
            return False, f"触发器状态不是激活: {trigger.status.value}"

        if trigger.is_expired:
            return False, "触发器已过期"

        trigger_type = trigger.trigger_type

        if trigger_type == TriggerType.THRESHOLD_CROSS:
            return self._check_threshold_cross(trigger, current_data)
        elif trigger_type == TriggerType.MOMENTUM_SIGNAL:
            return self._check_momentum_signal(trigger, current_data)
        elif trigger_type == TriggerType.REGIME_TRANSITION:
            return self._check_regime_transition(trigger, current_data)
        elif trigger_type == TriggerType.POLICY_CHANGE:
            return self._check_policy_change(trigger, current_data)
        elif trigger_type == TriggerType.MANUAL_OVERRIDE:
            return True, "手动覆盖触发"
        else:
            return False, f"未知的触发器类型: {trigger_type.value}"

    def _check_threshold_cross(
        self,
        trigger: AlphaTrigger,
        current_data: dict[str, Any],
    ) -> tuple[bool, str]:
        """检查阈值穿越"""
        indicator = trigger.trigger_condition.get("indicator_code")
        threshold = trigger.trigger_condition.get("threshold")
        direction = trigger.trigger_condition.get("direction", "above")

        if indicator is None or threshold is None:
            return False, "缺少必要参数: indicator_code 或 threshold"

        current_value = current_data.get(indicator)
        if current_value is None:
            return False, f"指标 {indicator} 没有当前值"

        if direction == "above":
            if current_value > threshold:
                return True, f"{indicator} ({current_value:.2f}) 突破阈值 {threshold}"
        else:
            if current_value < threshold:
                return True, f"{indicator} ({current_value:.2f}) 跌破阈值 {threshold}"

        return False, f"{indicator} ({current_value:.2f}) 未满足穿越条件"

    def _check_momentum_signal(
        self,
        trigger: AlphaTrigger,
        current_data: dict[str, Any],
    ) -> tuple[bool, str]:
        """检查动量信号"""
        momentum_pct = trigger.trigger_condition.get("momentum_pct")
        if momentum_pct is None:
            return False, "缺少动量参数"

        actual_momentum = current_data.get("momentum")
        if actual_momentum is None:
            actual_momentum = current_data.get("momentum_pct")
        if actual_momentum is None:
            return False, "no momentum data"

        if trigger.direction == "LONG":
            if actual_momentum >= momentum_pct:
                return True, f"momentum met: {actual_momentum:.2%} >= {momentum_pct:.2%}"
        else:
            if actual_momentum <= -momentum_pct:
                return True, f"momentum met: {actual_momentum:.2%} <= -{momentum_pct:.2%}"

        return False, f"momentum not met: {actual_momentum:.2%}"

    def _check_regime_transition(
        self,
        trigger: AlphaTrigger,
        current_data: dict[str, Any],
    ) -> tuple[bool, str]:
        """检查 Regime 转换"""
        target_regime = trigger.trigger_condition.get("target_regime")
        if target_regime is None:
            return False, "缺少目标 Regime"

        current_regime = current_data.get("current_regime")
        if current_regime is None:
            return False, "没有当前 Regime 数据"

        if current_regime == target_regime:
            return True, f"Regime 转换为 {target_regime}"

        return False, f"当前 Regime ({current_regime}) 不是目标 Regime ({target_regime})"

    def _check_policy_change(
        self,
        trigger: AlphaTrigger,
        current_data: dict[str, Any],
    ) -> tuple[bool, str]:
        """检查政策变化"""
        target_level = trigger.trigger_condition.get("target_policy_level")
        if target_level is None:
            return False, "缺少目标 Policy 档位"

        current_level = current_data.get("policy_level")
        if current_level is None:
            return False, "没有当前 Policy 档位数据"

        if current_level == target_level:
            return True, f"Policy 档位变为 P{target_level}"

        return False, f"当前 Policy 档位 (P{current_level}) 不是目标档位 (P{target_level})"


class TriggerInvalidator:
    """
    触发器证伪检查器

    检查 Alpha 触发器是否满足证伪条件。

    Example:
        >>> invalidator = TriggerInvalidator()
        >>> result = invalidator.check_invalidations(trigger, current_data)
        >>> if result.is_invalidated:
        ...     print(f"触发器证伪: {result.reason}")
    """

    def check_invalidations(
        self,
        trigger: AlphaTrigger,
        current_data: dict[str, Any],
    ) -> InvalidationCheckResult:
        """
        检查触发器是否应该证伪

        满足任一证伪条件即判定为证伪。

        Args:
            trigger: Alpha 触发器
            current_data: 当前数据

        Returns:
            证伪检查结果
        """
        conditions_met: list[str] = []
        reasons: list[str] = []
        details = {}

        for condition in trigger.invalidation_conditions:
            met, reason, condition_details = self._check_condition(condition, current_data)
            if met:
                cond_key = str(condition.condition_type)
                conditions_met.append(cond_key)
                reasons.append(reason)
                details[cond_key] = condition_details

        if conditions_met:
            return InvalidationCheckResult(
                is_invalidated=True,
                reason=f"满足证伪条件: {', '.join(reasons)}",
                conditions_met=conditions_met,
                details=details,
            )

        return InvalidationCheckResult(
            is_invalidated=False,
            reason="无证伪条件满足",
            conditions_met=[],
        )

    def _check_condition(
        self,
        condition: InvalidationCondition,
        current_data: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        检查单个证伪条件

        Returns:
            (是否满足, 原因, 详细信息)
        """
        if condition.condition_type == "threshold_cross":
            return self._check_threshold_condition(condition, current_data)
        elif condition.condition_type == "time_decay":
            return self._check_time_decay(condition, current_data)
        elif condition.condition_type == "regime_mismatch":
            return self._check_regime_mismatch(condition, current_data)
        else:
            return False, f"未知的条件类型: {condition.condition_type}", {}

    def _check_threshold_condition(
        self,
        condition: InvalidationCondition,
        current_data: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any]]:
        """检查阈值穿越条件"""
        indicator = condition.indicator_code
        if indicator is None:
            return False, "缺少指标代码", {}

        current_value = current_data.get(indicator)
        if current_value is None:
            return False, f"指标 {indicator} 没有当前值", {}

        threshold = condition.threshold_value
        if threshold is None:
            return False, "缺少阈值", {}

        direction = condition.cross_direction or "below"

        met = False
        if direction == "below":
            met = current_value < threshold
        else:
            met = current_value > threshold

        if met:
            details = {
                "indicator": indicator,
                "current_value": current_value,
                "threshold": threshold,
                "direction": direction,
            }
            return True, f"{indicator} ({current_value:.2f}) {direction} {threshold}", details

        return False, f"{indicator} ({current_value:.2f}) 未满足条件", {}

    def _check_time_decay(
        self,
        condition: InvalidationCondition,
        current_data: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any]]:
        """检查时间衰减条件"""
        max_days = condition.max_holding_days
        max_hours = condition.time_window_hours or condition.time_limit_hours
        if max_days is None and max_hours is None:
            return False, "未设置时间衰减阈值", {}

        triggered_at = current_data.get("triggered_at")
        if triggered_at is None:
            return False, "没有触发时间", {}

        if isinstance(triggered_at, str):
            triggered_at = datetime.fromisoformat(triggered_at)
        elif isinstance(triggered_at, datetime):
            pass
        else:
            return False, "无效的触发时间格式", {}

        now = datetime.now(triggered_at.tzinfo) if triggered_at.tzinfo else datetime.now(UTC)
        elapsed = now - triggered_at
        hours_elapsed = elapsed.total_seconds() / 3600
        days_elapsed = elapsed.days

        if max_hours is not None:
            if hours_elapsed > max_hours:
                return True, f"time decay: {hours_elapsed:.1f}h > {max_hours}h", {
                    "max_hours": max_hours,
                    "hours_elapsed": round(hours_elapsed, 2),
                }
            return False, f"time decay not met: {hours_elapsed:.1f}h <= {max_hours}h", {}

        if days_elapsed > (max_days or 0):
            details = {
                "max_holding_days": max_days,
                "days_elapsed": days_elapsed,
                "exceeded_by": days_elapsed - (max_days or 0),
            }
            return True, f"持仓 {days_elapsed} 天超过最大 {max_days} 天", details

        return False, f"持仓 {days_elapsed} 天未超过最大 {max_days} 天", {}

    def _check_regime_mismatch(
        self,
        condition: InvalidationCondition,
        current_data: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any]]:
        """检查 Regime 不匹配条件"""
        required_regime = condition.required_regime
        if required_regime is None:
            return False, "未设置要求的 Regime", {}

        current_regime = current_data.get("current_regime")
        if current_regime is None:
            return False, "没有当前 Regime", {}

        if current_regime != required_regime:
            details = {
                "required_regime": required_regime,
                "current_regime": current_regime,
            }
            return True, f"当前 Regime ({current_regime}) 与要求 ({required_regime}) 不匹配", details

        return False, f"当前 Regime ({current_regime}) 满足要求", {}


class CandidateGenerator:
    """
    Alpha 候选生成器

    从触发的触发器生成 Alpha 候选。

    Attributes:
        config: 触发器配置

    Example:
        >>> generator = CandidateGenerator()
        >>> candidate = generator.from_trigger(trigger)
    """

    def __init__(self, config: TriggerConfig | None = None):
        """
        初始化生成器

        Args:
            config: 触发器配置
        """
        self.config = config or TriggerConfig()

    def from_trigger(
        self,
        trigger: AlphaTrigger,
        time_window_days: int = 90,
    ) -> AlphaCandidate:
        """
        从触发器生成候选

        Args:
            trigger: Alpha 触发器
            time_window_days: 时间窗口（天数）

        Returns:
            Alpha 候选
        """
        from datetime import date
        from uuid import uuid4

        # 计算时间窗口
        start_date = date.today()
        end_date = start_date + timedelta(days=time_window_days)

        # 确定预期不对称性
        asymmetry = self._calculate_asymmetry(trigger)

        # 生成证伪描述
        invalidation_desc = self._describe_invalidations(trigger.invalidation_conditions)

        status = CandidateStatus.ACTIONABLE if trigger.strength == SignalStrength.VERY_STRONG else CandidateStatus.CANDIDATE

        return AlphaCandidate(
            candidate_id=str(uuid4()),
            trigger_id=trigger.trigger_id,
            asset_code=trigger.asset_code,
            asset_class=trigger.asset_class,
            direction=trigger.direction,
            strength=trigger.strength,
            confidence=trigger.confidence,
            thesis=trigger.thesis,
            invalidation=invalidation_desc,
            time_window_start=start_date,
            time_window_end=end_date,
            time_horizon=time_window_days,
            expected_asymmetry=asymmetry,
            status=status,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            audit_trail=[f"从触发器 {trigger.trigger_id} 生成"],
        )

    def _calculate_asymmetry(self, trigger: AlphaTrigger) -> str:
        """计算预期不对称性"""
        # 基于置信度和信号强度
        if trigger.confidence >= 0.8 and trigger.strength in [SignalStrength.STRONG, SignalStrength.VERY_STRONG]:
            return "HIGH"
        elif trigger.confidence >= 0.5:
            return "MED"
        else:
            return "LOW"

    def _describe_invalidations(self, conditions: list[InvalidationCondition]) -> str:
        """描述证伪条件"""
        if not conditions:
            return "无证伪条件"

        descriptions = []
        for condition in conditions:
            if condition.condition_type == "threshold_cross":
                direction = "跌破" if condition.cross_direction == "below" else "突破"
                desc = f"{condition.indicator_code} {direction} {condition.threshold_value}"
                descriptions.append(desc)
            elif condition.condition_type == "time_decay":
                desc = f"持仓超过 {condition.max_holding_days} 天"
                descriptions.append(desc)
            elif condition.condition_type == "regime_mismatch":
                desc = f"Regime 不再是 {condition.required_regime}"
                descriptions.append(desc)

        return "; ".join(descriptions)


class TriggerFilter:
    """
    触发器过滤器

    根据各种条件过滤触发器。

    Example:
        >>> filter = TriggerFilter()
        >>> active_triggers = filter.filter_by_status(triggers, TriggerStatus.ACTIVE)
    """

    def filter_by_status(
        self,
        triggers: list[AlphaTrigger],
        status: TriggerStatus,
    ) -> list[AlphaTrigger]:
        """按状态过滤"""
        return [t for t in triggers if t.status == status]

    def filter_by_asset(
        self,
        triggers: list[AlphaTrigger],
        asset_code: str,
    ) -> list[AlphaTrigger]:
        """按资产过滤"""
        return [t for t in triggers if t.asset_code == asset_code]

    def filter_by_strength(
        self,
        triggers: list[AlphaTrigger],
        min_strength: SignalStrength,
    ) -> list[AlphaTrigger]:
        """按信号强度过滤"""
        strength_order = {
            SignalStrength.WEAK: 1,
            SignalStrength.MODERATE: 2,
            SignalStrength.STRONG: 3,
            SignalStrength.VERY_STRONG: 4,
        }
        min_level = strength_order.get(min_strength, 1)
        return [
            t for t in triggers
            if strength_order.get(t.strength, 0) >= min_level
        ]

    def filter_active(self, triggers: list[AlphaTrigger]) -> list[AlphaTrigger]:
        """过滤激活的触发器"""
        return [t for t in triggers if t.is_active and not t.is_expired]

    def sort_by_confidence(
        self,
        triggers: list[AlphaTrigger],
        descending: bool = True,
    ) -> list[AlphaTrigger]:
        """按置信度排序"""
        return sorted(
            triggers,
            key=lambda t: t.confidence,
            reverse=descending,
        )

    def get_top_n(
        self,
        triggers: list[AlphaTrigger],
        n: int,
        by: str = "confidence",
    ) -> list[AlphaTrigger]:
        """
        获取 Top N 触发器

        Args:
            triggers: 触发器列表
            n: 返回数量
            by: 排序依据 ("confidence", "created_at")

        Returns:
            Top N 触发器
        """
        if by == "confidence":
            sorted_triggers = self.sort_by_confidence(triggers, descending=True)
        elif by == "created_at":
            sorted_triggers = sorted(triggers, key=lambda t: t.created_at, reverse=True)
        else:
            sorted_triggers = triggers

        return sorted_triggers[:n]


# ========== 便捷函数 ==========


def evaluate_trigger(
    trigger: AlphaTrigger,
    current_data: dict[str, Any],
    config: TriggerConfig | None = None,
) -> tuple[bool, str]:
    """
    评估触发器是否应该触发的便捷函数

    Args:
        trigger: Alpha 触发器
        current_data: 当前数据
        config: 触发器配置

    Returns:
        (是否触发, 原因)
    """
    evaluator = TriggerEvaluator(config)
    return evaluator.should_trigger(trigger, current_data)


def check_invalidations(
    trigger: AlphaTrigger,
    current_data: dict[str, Any],
) -> InvalidationCheckResult:
    """
    检查触发器证伪的便捷函数

    Args:
        trigger: Alpha 触发器
        current_data: 当前数据

    Returns:
        证伪检查结果
    """
    invalidator = TriggerInvalidator()
    return invalidator.check_invalidations(trigger, current_data)


def generate_candidate(
    trigger: AlphaTrigger,
    time_window_days: int = 90,
) -> AlphaCandidate:
    """
    从触发器生成候选的便捷函数

    Args:
        trigger: Alpha 触发器
        time_window_days: 时间窗口天数

    Returns:
        Alpha 候选
    """
    generator = CandidateGenerator()
    return generator.from_trigger(trigger, time_window_days)
