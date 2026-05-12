"""
Beta Gate Application Use Cases

硬闸门过滤的用例编排层。
负责协调 Domain 层服务和事件发布。

仅依赖 Domain 层和事件总线，不直接依赖 ORM 或外部 API。
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from apps.events.domain.entities import EventType, create_event

from ..domain.entities import (
    GateConfig,
    GateDecision,
    RiskProfile,
    VisibilityUniverse,
)
from ..domain.services import (
    BetaGateEvaluator,
)

logger = logging.getLogger(__name__)


# ========== DTOs ==========


@dataclass
class EvaluateGateRequest:
    """
    评估闸门请求

    Attributes:
        asset_code: 资产代码
        asset_class: 资产类别
        current_regime: 当前 Regime
        regime_confidence: Regime 置信度
        policy_level: Policy 档位
        current_portfolio_value: 当前组合价值
        new_position_value: 新建仓位价值
        risk_profile: 风险画像
        request_id: 请求 ID（可选）
    """

    asset_code: str
    asset_class: str
    current_regime: str
    regime_confidence: float
    policy_level: int
    current_portfolio_value: float = 0.0
    new_position_value: float = 0.0
    risk_profile: RiskProfile = RiskProfile.BALANCED
    request_id: str | None = None


@dataclass
class EvaluateGateResponse:
    """
    评估闸门响应

    Attributes:
        success: 是否成功
        decision: 闸门决策结果
        warnings: 警告列表
        error: 错误信息
    """

    success: bool
    decision: GateDecision | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class GetGateConfigRequest:
    """
    获取闸门配置请求

    Attributes:
        risk_profile: 风险画像
    """

    risk_profile: RiskProfile = RiskProfile.BALANCED


@dataclass
class GetGateConfigResponse:
    """
    获取闸门配置响应

    Attributes:
        success: 是否成功
        config: 闸门配置
        error: 错误信息
    """

    success: bool
    config: GateConfig | None = None
    error: str | None = None


@dataclass
class BuildUniverseRequest:
    """
    构建可见性宇宙请求

    Attributes:
        current_regime: 当前 Regime
        regime_confidence: Regime 置信度
        policy_level: Policy 档位
        risk_profile: 风险画像
        regime_snapshot_id: Regime 快照 ID
        policy_snapshot_id: Policy 快照 ID
        candidate_assets: 候选资产列表 [(asset_code, asset_class), ...]
    """

    current_regime: str
    regime_confidence: float
    policy_level: int
    risk_profile: RiskProfile = RiskProfile.BALANCED
    regime_snapshot_id: str = ""
    policy_snapshot_id: str = ""
    candidate_assets: list[tuple[str, str]] | None = None


@dataclass
class BuildUniverseResponse:
    """
    构建可见性宇宙响应

    Attributes:
        success: 是否成功
        universe: 可见性宇宙
        error: 错误信息
    """

    success: bool
    universe: VisibilityUniverse | None = None
    error: str | None = None


@dataclass
class EvaluateBatchRequest:
    """
    批量评估请求

    Attributes:
        assets: 资产列表 [(asset_code, asset_class), ...]
        current_regime: 当前 Regime
        regime_confidence: Regime 置信度
        policy_level: Policy 档位
        current_portfolio_value: 当前组合价值
        risk_profile: 风险画像
    """

    assets: list[tuple[str, str]]
    current_regime: str
    regime_confidence: float
    policy_level: int
    current_portfolio_value: float = 0.0
    risk_profile: RiskProfile = RiskProfile.BALANCED


@dataclass
class EvaluateBatchResponse:
    """
    批量评估响应

    Attributes:
        success: 是否成功
        decisions: 决策结果列表
        summary: 摘要统计
        error: 错误信息
    """

    success: bool
    decisions: list[GateDecision] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ========== Use Cases ==========


class EvaluateBetaGateUseCase:
    """
    评估 Beta Gate 用例

    评估单个资产是否通过 Beta Gate。

    Attributes:
        config_selector: 配置选择器
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = EvaluateBetaGateUseCase(config_selector, event_bus)
        >>> response = use_case.execute(EvaluateGateRequest(
        ...     asset_code="000001.SH",
        ...     asset_class="a_share金融",
        ...     current_regime="Recovery",
        ...     regime_confidence=0.7,
        ...     policy_level=0
        ... ))
    """

    def __init__(self, config_selector, event_bus=None):
        """
        初始化用例

        Args:
            config_selector: 配置选择器
            event_bus: 事件总线（可选）
        """
        self.config_selector = config_selector
        self.event_bus = event_bus

    def execute(self, request: EvaluateGateRequest) -> EvaluateGateResponse:
        """
        执行闸门评估

        流程：
        1. 获取配置
        2. 创建评估器
        3. 执行评估
        4. 发布事件
        5. 返回结果

        Args:
            request: 评估请求

        Returns:
            评估响应
        """
        warnings = []

        try:
            # 获取配置
            config = self.config_selector.get_config(request.risk_profile)

            if not config.is_valid:
                warnings.append(f"配置无效或已过期: {config.config_id}")
                # 继续使用，但记录警告

            # 创建评估器
            evaluator = BetaGateEvaluator(config)

            # 执行评估
            decision = evaluator.evaluate(
                asset_code=request.asset_code,
                asset_class=request.asset_class,
                current_regime=request.current_regime,
                regime_confidence=request.regime_confidence,
                policy_level=request.policy_level,
                current_portfolio_value=request.current_portfolio_value,
                new_position_value=request.new_position_value,
            )

            # 发布事件
            self._publish_event(decision, request)

            # 记录日志
            self._log_decision(decision)

            return EvaluateGateResponse(
                success=True,
                decision=decision,
                warnings=warnings,
            )

        except Exception as e:
            logger.error(f"Beta Gate evaluation failed: {e}", exc_info=True)
            return EvaluateGateResponse(
                success=False,
                warnings=warnings,
                error=str(e),
            )

    def _publish_event(self, decision: GateDecision, request: EvaluateGateRequest):
        """发布事件"""
        if self.event_bus is None:
            return

        event_type = EventType.BETA_GATE_PASSED if decision.is_passed else EventType.BETA_GATE_BLOCKED

        event = create_event(
            event_type=event_type,
            payload={
                "asset_code": decision.asset_code,
                "asset_class": decision.asset_class,
                "status": decision.status.value,
                "regime": decision.current_regime,
                "policy_level": decision.policy_level,
                "regime_confidence": decision.regime_confidence,
                "blocking_reason": decision.blocking_reason if not decision.is_passed else None,
                "risk_profile": request.risk_profile.value,
            },
        )

        self.event_bus.publish(event)

    def _log_decision(self, decision: GateDecision):
        """记录决策"""
        if decision.is_passed:
            logger.info(f"Beta Gate PASSED: {decision.asset_code} in {decision.current_regime}")
        else:
            logger.warning(f"Beta Gate BLOCKED: {decision.asset_code} - {decision.blocking_reason}")


class EvaluateBatchUseCase:
    """
    批量评估 Beta Gate 用例

    批量评估多个资产是否通过 Beta Gate。

    Attributes:
        config_selector: 配置选择器
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = EvaluateBatchUseCase(config_selector, event_bus)
        >>> response = use_case.execute(EvaluateBatchRequest(
        ...     assets=[("000001.SH", "a_share金融"), ("000002.SZ", "a_share金融")],
        ...     current_regime="Recovery",
        ...     regime_confidence=0.7,
        ...     policy_level=0
        ... ))
    """

    def __init__(self, config_selector, event_bus=None):
        """
        初始化用例

        Args:
            config_selector: 配置选择器
            event_bus: 事件总线（可选）
        """
        self.config_selector = config_selector
        self.event_bus = event_bus

    def execute(self, request: EvaluateBatchRequest) -> EvaluateBatchResponse:
        """
        执行批量评估

        Args:
            request: 批量评估请求

        Returns:
            批量评估响应
        """
        try:
            # 获取配置
            config = self.config_selector.get_config(request.risk_profile)

            # 创建评估器
            evaluator = BetaGateEvaluator(config)

            # 批量评估
            decisions = evaluator.evaluate_batch(
                assets=request.assets,
                current_regime=request.current_regime,
                regime_confidence=request.regime_confidence,
                policy_level=request.policy_level,
                current_portfolio_value=request.current_portfolio_value,
            )

            # 统计摘要
            summary = self._calculate_summary(decisions)

            # 发布汇总事件
            self._publish_summary_event(decisions, summary, request)

            return EvaluateBatchResponse(
                success=True,
                decisions=decisions,
                summary=summary,
            )

        except Exception as e:
            logger.error(f"Batch Beta Gate evaluation failed: {e}", exc_info=True)
            return EvaluateBatchResponse(
                success=False,
                error=str(e),
            )

    def _calculate_summary(self, decisions: list[GateDecision]) -> dict[str, Any]:
        """计算摘要统计"""
        total = len(decisions)
        passed = sum(1 for d in decisions if d.is_passed)
        blocked = total - passed

        # 按拦截原因分组
        blocked_by_reason = {}
        for decision in decisions:
            if decision.is_blocked:
                reason = decision.blocking_reason
                blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1

        return {
            "total": total,
            "passed": passed,
            "blocked": blocked,
            "pass_rate": passed / total if total > 0 else 0,
            "blocked_by_reason": blocked_by_reason,
        }

    def _publish_summary_event(
        self,
        decisions: list[GateDecision],
        summary: dict[str, Any],
        request: EvaluateBatchRequest,
    ):
        """发布汇总事件"""
        if self.event_bus is None:
            return

        event = create_event(
            event_type=EventType.BETA_GATE_EVALUATED,
            payload={
                "total_assets": len(request.assets),
                "passed": summary["passed"],
                "blocked": summary["blocked"],
                "pass_rate": summary["pass_rate"],
                "regime": request.current_regime,
                "policy_level": request.policy_level,
                "risk_profile": request.risk_profile.value,
            },
        )

        self.event_bus.publish(event)


class GetGateConfigUseCase:
    """
    获取闸门配置用例

    获取指定风险画像的闸门配置。

    Attributes:
        config_selector: 配置选择器

    Example:
        >>> use_case = GetGateConfigUseCase(config_selector)
        >>> response = use_case.execute(GetGateConfigRequest(RiskProfile.BALANCED))
    """

    def __init__(self, config_selector):
        """
        初始化用例

        Args:
            config_selector: 配置选择器
        """
        self.config_selector = config_selector

    def execute(self, request: GetGateConfigRequest) -> GetGateConfigResponse:
        """
        获取闸门配置

        Args:
            request: 获取配置请求

        Returns:
            配置响应
        """
        try:
            config = self.config_selector.get_config(request.risk_profile)

            return GetGateConfigResponse(
                success=True,
                config=config,
            )

        except Exception as e:
            logger.error(f"Failed to get gate config: {e}", exc_info=True)
            return GetGateConfigResponse(
                success=False,
                error=str(e),
            )


class BuildVisibilityUniverseUseCase:
    """
    构建可见性宇宙用例

    根据当前环境构建可见性宇宙。

    Attributes:
        universe_builder: 宇宙构建器
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = BuildVisibilityUniverseUseCase(builder, event_bus)
        >>> response = use_case.execute(BuildUniverseRequest(
        ...     current_regime="Recovery",
        ...     regime_confidence=0.7,
        ...     policy_level=0
        ... ))
    """

    def __init__(self, universe_builder, event_bus=None):
        """
        初始化用例

        Args:
            universe_builder: 宇宙构建器
            event_bus: 事件总线（可选）
        """
        self.universe_builder = universe_builder
        self.event_bus = event_bus

    def execute(self, request: BuildUniverseRequest) -> BuildUniverseResponse:
        """
        构建可见性宇宙

        Args:
            request: 构建请求

        Returns:
            构建响应
        """
        try:
            universe = self.universe_builder.build(
                current_regime=request.current_regime,
                regime_confidence=request.regime_confidence,
                policy_level=request.policy_level,
                risk_profile=request.risk_profile,
                regime_snapshot_id=request.regime_snapshot_id,
                policy_snapshot_id=request.policy_snapshot_id,
                candidate_assets=request.candidate_assets,
            )

            # 发布事件
            self._publish_event(universe, request)

            # 记录日志
            self._log_universe(universe)

            return BuildUniverseResponse(
                success=True,
                universe=universe,
            )

        except Exception as e:
            logger.error(f"Failed to build visibility universe: {e}", exc_info=True)
            return BuildUniverseResponse(
                success=False,
                error=str(e),
            )

    def _publish_event(self, universe: VisibilityUniverse, request: BuildUniverseRequest):
        """发布事件"""
        if self.event_bus is None:
            return

        event = create_event(
            event_type=EventType.BETA_GATE_EVALUATED,
            payload={
                "regime": request.current_regime,
                "policy_level": request.policy_level,
                "risk_profile": request.risk_profile.value,
                "visible_asset_categories": universe.visible_asset_categories,
                "visible_strategies": universe.visible_strategies,
                "hard_exclusions_count": len(universe.hard_exclusions),
                "watch_list_count": len(universe.watch_list),
            },
        )

        self.event_bus.publish(event)

    def _log_universe(self, universe: VisibilityUniverse):
        """记录宇宙"""
        logger.info(
            f"Visibility Universe built: "
            f"{len(universe.visible_asset_categories)} categories, "
            f"{len(universe.visible_strategies)} strategies, "
            f"{len(universe.hard_exclusions)} excluded, "
            f"{len(universe.watch_list)} watch"
        )
