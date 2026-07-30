"""Unified decision recommendation generation and query use cases."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.utils import timezone

if TYPE_CHECKING:
    from ..domain.entities import (
        DecisionFeatureSnapshot,
        UnifiedRecommendation,
    )

from .decision_model_param_use_cases import GetModelParamsUseCase

logger = logging.getLogger(__name__)

RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    DatabaseError,
    ImportError,
    ImproperlyConfigured,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


class FeatureDataProviderProtocol(Protocol):
    """特征数据提供者协议"""

    def get_regime(self) -> dict[str, Any] | None:
        """获取当前 Regime 状态"""
        ...

    def get_policy_level(self) -> str | None:
        """获取当前政策档位"""
        ...

    def check_beta_gate(self, security_code: str) -> bool:
        """检查 Beta Gate 是否通过"""
        ...

    def get_sentiment_score(self, security_code: str) -> float:
        """获取舆情分数"""
        ...

    def get_flow_score(self, security_code: str) -> float:
        """获取资金流向分数"""
        ...

    def get_technical_score(self, security_code: str) -> float:
        """获取技术面分数"""
        ...

    def get_fundamental_score(self, security_code: str) -> float:
        """获取基本面分数"""
        ...

    def get_alpha_model_score(self, security_code: str) -> float:
        """获取 Alpha 模型分数"""
        ...


class FeatureFreshnessContract(TypedDict):
    """Decision-safety metadata for one feature observation."""

    observed_at: str | None
    freshness_status: str
    must_not_use_for_decision: bool
    blocked_reason: str


@runtime_checkable
class FeatureFreshnessProviderProtocol(Protocol):
    """Optional extension that preserves feature observation quality."""

    def get_feature_freshness_contracts(
        self,
        security_code: str,
    ) -> dict[str, FeatureFreshnessContract]: ...


class ValuationProviderProtocol(Protocol):
    """估值数据提供者协议"""

    def get_valuation(
        self,
        security_code: str,
    ) -> dict[str, Any] | None:
        """获取估值数据"""
        ...


class SignalProviderProtocol(Protocol):
    """信号数据提供者协议"""

    def get_active_signals(
        self,
        security_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取活跃信号"""
        ...


class CandidateProviderProtocol(Protocol):
    """候选数据提供者协议"""

    def get_active_candidates(
        self,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取活跃候选"""
        ...


class PositionSnapshotProviderProtocol(Protocol):
    """持仓快照提供者协议。"""

    def get_position_snapshots(self, account_id: str) -> list[dict[str, Any]]:
        """获取账户当前持仓快照。"""
        ...


class UnifiedRecommendationRepositoryProtocol(Protocol):
    """统一推荐仓储协议"""

    def save(self, recommendation: "UnifiedRecommendation") -> "UnifiedRecommendation":
        """保存推荐"""
        ...

    def save_feature_snapshot(
        self, snapshot: "DecisionFeatureSnapshot"
    ) -> "DecisionFeatureSnapshot":
        """保存特征快照"""
        ...

    def get_by_account(
        self,
        account_id: str,
        status: str | None = None,
    ) -> list["UnifiedRecommendation"]:
        """按账户获取推荐"""
        ...

    def get_conflicts(self, account_id: str) -> list["UnifiedRecommendation"]:
        """获取冲突推荐"""
        ...

    def mark_as_conflict(self, recommendation_id: str) -> None:
        """标记为冲突"""
        ...


@dataclass
class GenerateRecommendationsRequest:
    """生成推荐请求"""

    account_id: str
    security_codes: list[str] | None = None
    force_refresh: bool = False


@dataclass
class GenerateRecommendationsResponse:
    """生成推荐响应"""

    success: bool
    recommendations: list["UnifiedRecommendation"] = field(default_factory=list)
    conflicts: list["UnifiedRecommendation"] = field(default_factory=list)
    error: str = ""


class GenerateUnifiedRecommendationsUseCase:
    """
    生成统一推荐用例

    协调 Top-down 和 Bottom-up 数据汇聚，生成统一推荐。

    流程:
        1. 数据汇聚: 拉取 Regime、Policy、Beta Gate、舆情、价格交易、财务、Alpha 分数
        2. 推荐生成: 生成统一推荐对象 UnifiedRecommendation
        3. 后端聚合: 按 account_id + security_code + side 去重
        4. 冲突处理: 同账户同证券同时 BUY/SELL 进入冲突队列
    """

    def __init__(
        self,
        feature_provider: FeatureDataProviderProtocol,
        valuation_provider: ValuationProviderProtocol,
        signal_provider: SignalProviderProtocol,
        candidate_provider: CandidateProviderProtocol,
        recommendation_repo: UnifiedRecommendationRepositoryProtocol,
        param_use_case: GetModelParamsUseCase,
        position_snapshot_provider: PositionSnapshotProviderProtocol | None = None,
    ):
        """
        初始化用例

        Args:
            feature_provider: 特征数据提供者
            valuation_provider: 估值数据提供者
            signal_provider: 信号数据提供者
            candidate_provider: 候选数据提供者
            recommendation_repo: 推荐仓储
            param_use_case: 参数获取用例
            position_snapshot_provider: 持仓快照提供者（可选）
        """
        self.feature_provider = feature_provider
        self.valuation_provider = valuation_provider
        self.signal_provider = signal_provider
        self.candidate_provider = candidate_provider
        self.recommendation_repo = recommendation_repo
        self.param_use_case = param_use_case
        self.position_snapshot_provider = position_snapshot_provider

    def execute(
        self,
        request: GenerateRecommendationsRequest,
    ) -> GenerateRecommendationsResponse:
        """
        执行推荐生成

        Args:
            request: 生成请求

        Returns:
            生成响应
        """

        from uuid import uuid4

        from ..domain.entities import (
            DecisionFeatureSnapshot,
            RecommendationStatus,
            UnifiedRecommendation,
        )
        from ..domain.services import (
            CompositeScoreCalculator,
            RecommendationAggregator,
        )

        def _to_float(value: Any, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        try:
            # 获取模型参数
            params: dict[str, Any] = {}
            if hasattr(self.param_use_case, "execute"):
                raw_params = self.param_use_case.execute()
                if isinstance(raw_params, dict):
                    params = raw_params
            weights = self.param_use_case.get_model_weights()
            penalties = self.param_use_case.get_gate_penalties()
            calculator = CompositeScoreCalculator(weights, penalties)
            aggregator = RecommendationAggregator()
            buy_score_threshold = _to_float(params.get("buy_score_threshold", 0.65), 0.65)
            buy_alpha_threshold = _to_float(params.get("buy_alpha_threshold", 0.60), 0.60)
            sell_score_threshold = _to_float(params.get("sell_score_threshold", 0.35), 0.35)
            sell_alpha_threshold = _to_float(params.get("sell_alpha_threshold", 0.30), 0.30)
            default_position_pct = _to_float(params.get("default_position_pct", 5.0), 5.0)
            max_capital_per_trade_raw = _to_float(
                params.get("max_capital_per_trade", 50000.0), 50000.0
            )
            max_capital_per_trade = Decimal(str(max_capital_per_trade_raw))

            # 1. 数据汇聚
            regime_data = self.feature_provider.get_regime()
            policy_level = self.feature_provider.get_policy_level()

            # 获取证券列表
            security_codes = request.security_codes
            if not security_codes:
                candidates = self.candidate_provider.get_active_candidates(request.account_id)
                candidate_codes = {
                    str(code).strip()
                    for code in (c.get("security_code") for c in candidates)
                    if str(code or "").strip()
                }
                held_codes: set[str] = set()
                if self.position_snapshot_provider is not None:
                    position_snapshots = self.position_snapshot_provider.get_position_snapshots(
                        request.account_id
                    )
                    held_codes = {
                        str(code).strip()
                        for code in (p.get("asset_code") for p in position_snapshots)
                        if str(code or "").strip()
                    }
                security_codes = list(candidate_codes | held_codes)

            # 2. 生成推荐
            raw_recommendations: list[UnifiedRecommendation] = []

            for security_code in security_codes:
                # 检查 Beta Gate
                beta_gate_passed = self.feature_provider.check_beta_gate(security_code)

                # 收集特征，并在取值后读取提供者保留的源观测质量。
                sentiment_score = self.feature_provider.get_sentiment_score(security_code)
                flow_score = self.feature_provider.get_flow_score(security_code)
                feature_freshness = self._get_feature_freshness_contracts(security_code)
                regime_freshness = self._get_regime_freshness_contract(regime_data)
                if regime_freshness is not None:
                    feature_freshness["regime"] = regime_freshness
                snapshot = DecisionFeatureSnapshot(
                    snapshot_id=f"fsn_{uuid4().hex[:12]}",
                    security_code=security_code,
                    snapshot_time=timezone.now(),
                    regime=regime_data.get("regime", "") if regime_data else "",
                    regime_confidence=regime_data.get("confidence", 0.0) if regime_data else 0.0,
                    policy_level=policy_level or "",
                    beta_gate_passed=beta_gate_passed,
                    sentiment_score=sentiment_score,
                    flow_score=flow_score,
                    technical_score=self.feature_provider.get_technical_score(security_code),
                    fundamental_score=self.feature_provider.get_fundamental_score(security_code),
                    alpha_model_score=self.feature_provider.get_alpha_model_score(security_code),
                    extra_features={"feature_freshness": feature_freshness},
                )

                # 保存特征快照
                self.recommendation_repo.save_feature_snapshot(snapshot)

                # 计算综合分
                composite_score, penalty_reasons = calculator.calculate_from_snapshot(snapshot)

                # 获取估值数据
                valuation = self.valuation_provider.get_valuation(security_code)
                valuation_reason_codes = []
                if valuation and valuation.get("valuation_source") == "current_price_fallback":
                    valuation_reason_codes.append("valuation_current_price_fallback")

                # 确定方向（基于综合分）
                side = self._determine_side(
                    composite_score,
                    snapshot.alpha_model_score,
                    buy_score_threshold=buy_score_threshold,
                    buy_alpha_threshold=buy_alpha_threshold,
                    sell_score_threshold=sell_score_threshold,
                    sell_alpha_threshold=sell_alpha_threshold,
                )
                feature_blocked_reasons = self._get_blocked_feature_reasons(feature_freshness)
                if not beta_gate_passed or feature_blocked_reasons:
                    side = "HOLD"

                # 获取来源信号
                signals = self.signal_provider.get_active_signals(security_code)
                signal_ids = [
                    str(signal_id)
                    for signal in signals
                    if (signal_id := signal.get("signal_id")) is not None and str(signal_id).strip()
                ]

                # 获取来源候选
                candidates = self.candidate_provider.get_active_candidates(request.account_id)
                candidate_ids = [
                    str(candidate_id)
                    for candidate in candidates
                    if candidate.get("security_code") == security_code
                    and (candidate_id := candidate.get("candidate_id")) is not None
                    and str(candidate_id).strip()
                ]

                # 生成推荐
                recommendation = UnifiedRecommendation(
                    recommendation_id=f"urec_{uuid4().hex[:12]}",
                    account_id=request.account_id,
                    security_code=security_code,
                    side=side,
                    regime=snapshot.regime,
                    regime_confidence=snapshot.regime_confidence,
                    policy_level=snapshot.policy_level,
                    beta_gate_passed=snapshot.beta_gate_passed,
                    sentiment_score=snapshot.sentiment_score,
                    flow_score=snapshot.flow_score,
                    technical_score=snapshot.technical_score,
                    fundamental_score=snapshot.fundamental_score,
                    alpha_model_score=snapshot.alpha_model_score,
                    composite_score=composite_score,
                    confidence=(
                        0.0
                        if feature_blocked_reasons
                        else min(snapshot.regime_confidence + snapshot.alpha_model_score, 1.0) / 2
                    ),
                    reason_codes=penalty_reasons
                    + valuation_reason_codes
                    + [
                        f"FEATURE_BLOCKED_{reason.upper().replace('-', '_')}"
                        for reason in feature_blocked_reasons
                    ]
                    + self._generate_reason_codes(snapshot, composite_score),
                    human_rationale=self._generate_rationale(snapshot, composite_score, side),
                    fair_value=(
                        Decimal(str(valuation.get("fair_value", 0))) if valuation else Decimal("0")
                    ),
                    entry_price_low=(
                        Decimal(str(valuation.get("entry_price_low", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    entry_price_high=(
                        Decimal(str(valuation.get("entry_price_high", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    target_price_low=(
                        Decimal(str(valuation.get("target_price_low", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    target_price_high=(
                        Decimal(str(valuation.get("target_price_high", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    stop_loss_price=(
                        Decimal(str(valuation.get("stop_loss_price", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    position_pct=default_position_pct,
                    suggested_quantity=0,  # 需要根据账户资金计算
                    max_capital=max_capital_per_trade,
                    source_signal_ids=signal_ids,
                    source_candidate_ids=candidate_ids,
                    feature_snapshot_id=snapshot.snapshot_id,
                    status=RecommendationStatus.NEW,
                )

                raw_recommendations.append(recommendation)

            # 3. 后端聚合（去重）
            # 4. 冲突处理
            deduplicated, conflicts, conflict_pairs = aggregator.aggregate(raw_recommendations)

            # 保存推荐和冲突
            saved_recommendations: list[UnifiedRecommendation] = []
            for rec in deduplicated:
                saved = self.recommendation_repo.save(rec)
                saved_recommendations.append(saved)

            saved_conflicts: list[UnifiedRecommendation] = []
            for conflict in conflicts:
                self.recommendation_repo.mark_as_conflict(conflict.recommendation_id)
                saved_conflicts.append(conflict)

            logger.info(
                f"Generated {len(saved_recommendations)} recommendations, "
                f"{len(saved_conflicts)} conflicts for account {request.account_id}"
            )

            return GenerateRecommendationsResponse(
                success=True,
                recommendations=saved_recommendations,
                conflicts=saved_conflicts,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to generate recommendations: {e}", exc_info=True)
            return GenerateRecommendationsResponse(
                success=False,
                error=str(e),
            )

    def _determine_side(
        self,
        composite_score: float,
        alpha_score: float,
        buy_score_threshold: float,
        buy_alpha_threshold: float,
        sell_score_threshold: float,
        sell_alpha_threshold: float,
    ) -> str:
        """
        确定推荐方向

        Args:
            composite_score: 综合分
            alpha_score: Alpha 分数

        Returns:
            方向 (BUY/SELL/HOLD)
        """
        if composite_score >= buy_score_threshold and alpha_score >= buy_alpha_threshold:
            return "BUY"
        elif composite_score <= sell_score_threshold or alpha_score <= sell_alpha_threshold:
            return "SELL"
        else:
            return "HOLD"

    def _get_feature_freshness_contracts(
        self,
        security_code: str,
    ) -> dict[str, FeatureFreshnessContract]:
        """Read the optional freshness extension without changing score providers."""

        if not isinstance(self.feature_provider, FeatureFreshnessProviderProtocol):
            return {}
        return dict(self.feature_provider.get_feature_freshness_contracts(security_code))

    @staticmethod
    def _get_regime_freshness_contract(
        regime_data: dict[str, Any] | None,
    ) -> FeatureFreshnessContract | None:
        """Preserve explicit Regime decision-safety metadata when published."""

        if regime_data is None or "must_not_use_for_decision" not in regime_data:
            return None
        observed_at = regime_data.get("observed_at")
        return FeatureFreshnessContract(
            observed_at=str(observed_at) if observed_at is not None else None,
            freshness_status=str(regime_data.get("freshness_status") or "unknown"),
            must_not_use_for_decision=bool(regime_data["must_not_use_for_decision"]),
            blocked_reason=str(regime_data.get("blocked_reason") or ""),
        )

    @staticmethod
    def _get_blocked_feature_reasons(
        contracts: dict[str, FeatureFreshnessContract],
    ) -> list[str]:
        """Return stable reasons for observations unsafe for recommendations."""

        return sorted(
            {
                contract["blocked_reason"] or f"{feature_name}_unavailable"
                for feature_name, contract in contracts.items()
                if contract["must_not_use_for_decision"]
            }
        )

    def _generate_reason_codes(
        self,
        snapshot: "DecisionFeatureSnapshot",
        composite_score: float,
    ) -> list[str]:
        """
        生成原因代码

        Args:
            snapshot: 特征快照
            composite_score: 综合分

        Returns:
            原因代码列表
        """
        codes = []

        if snapshot.alpha_model_score >= 0.7:
            codes.append("ALPHA_HIGH")
        elif snapshot.alpha_model_score <= 0.3:
            codes.append("ALPHA_LOW")

        if snapshot.regime_confidence >= 0.8:
            codes.append("REGIME_CONFIDENT")

        if snapshot.beta_gate_passed:
            codes.append("BETA_GATE_PASS")
        else:
            codes.append("BETA_GATE_BLOCKED")

        if composite_score >= 0.7:
            codes.append("COMPOSITE_HIGH")

        return codes

    def _generate_rationale(
        self,
        snapshot: "DecisionFeatureSnapshot",
        composite_score: float,
        side: str,
    ) -> str:
        """
        生成人类可读理由

        Args:
            snapshot: 特征快照
            composite_score: 综合分
            side: 方向

        Returns:
            人类可读理由
        """
        parts = []

        if side == "BUY":
            parts.append("推荐买入")
        elif side == "SELL":
            parts.append("推荐卖出")
        else:
            parts.append("建议持有")

        parts.append(f"综合分 {composite_score:.2f}")

        if snapshot.alpha_model_score >= 0.7:
            parts.append(f"Alpha 分数较高({snapshot.alpha_model_score:.2f})")

        if snapshot.regime:
            parts.append(f"当前 Regime: {snapshot.regime}")

        if snapshot.policy_level:
            parts.append(f"政策档位: {snapshot.policy_level}")

        if not snapshot.beta_gate_passed:
            parts.append("Beta Gate 未通过，当前仅展示观察，不进入执行")

        freshness = snapshot.extra_features.get("feature_freshness")
        if isinstance(freshness, dict):
            blocked_reasons = sorted(
                {
                    str(contract.get("blocked_reason") or f"{name}_unavailable")
                    for name, contract in freshness.items()
                    if isinstance(contract, dict)
                    and bool(contract.get("must_not_use_for_decision"))
                }
            )
            if blocked_reasons:
                parts.append(f"特征数据不可用于决策({', '.join(blocked_reasons)})")

        return "。".join(parts) + "。"


@dataclass
class GetRecommendationsRequest:
    """获取推荐请求"""

    account_id: str
    status: str | None = None
    page: int = 1
    page_size: int = 20


@dataclass
class GetRecommendationsResponse:
    """获取推荐响应"""

    success: bool
    recommendations: list["UnifiedRecommendation"] = field(default_factory=list)
    total_count: int = 0
    error: str = ""


class GetUnifiedRecommendationsUseCase:
    """
    获取统一推荐用例

    从仓储获取已生成的推荐列表。
    """

    def __init__(
        self,
        recommendation_repo: UnifiedRecommendationRepositoryProtocol,
    ):
        """
        初始化用例

        Args:
            recommendation_repo: 推荐仓储
        """
        self.recommendation_repo = recommendation_repo

    def execute(
        self,
        request: GetRecommendationsRequest,
    ) -> GetRecommendationsResponse:
        """
        执行获取推荐

        Args:
            request: 获取请求

        Returns:
            获取响应
        """
        try:
            recommendations = self.recommendation_repo.get_by_account(
                account_id=request.account_id,
                status=request.status,
            )

            return GetRecommendationsResponse(
                success=True,
                recommendations=recommendations,
                total_count=len(recommendations),
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to get recommendations: {e}", exc_info=True)
            return GetRecommendationsResponse(
                success=False,
                error=str(e),
            )


@dataclass
class GetConflictsRequest:
    """获取冲突请求"""

    account_id: str


@dataclass
class GetConflictsResponse:
    """获取冲突响应"""

    success: bool
    conflicts: list["UnifiedRecommendation"] = field(default_factory=list)
    total_count: int = 0
    error: str = ""


class GetConflictsUseCase:
    """
    获取冲突用例

    从仓储获取冲突推荐列表。
    """

    def __init__(
        self,
        recommendation_repo: UnifiedRecommendationRepositoryProtocol,
    ):
        """
        初始化用例

        Args:
            recommendation_repo: 推荐仓储
        """
        self.recommendation_repo = recommendation_repo

    def execute(
        self,
        request: GetConflictsRequest,
    ) -> GetConflictsResponse:
        """
        执行获取冲突

        Args:
            request: 获取请求

        Returns:
            获取响应
        """
        try:
            conflicts = self.recommendation_repo.get_conflicts(request.account_id)

            return GetConflictsResponse(
                success=True,
                conflicts=conflicts,
                total_count=len(conflicts),
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to get conflicts: {e}", exc_info=True)
            return GetConflictsResponse(
                success=False,
                error=str(e),
            )


__all__ = [
    "FeatureDataProviderProtocol",
    "FeatureFreshnessContract",
    "FeatureFreshnessProviderProtocol",
    "ValuationProviderProtocol",
    "SignalProviderProtocol",
    "CandidateProviderProtocol",
    "PositionSnapshotProviderProtocol",
    "UnifiedRecommendationRepositoryProtocol",
    "GenerateRecommendationsRequest",
    "GenerateRecommendationsResponse",
    "GenerateUnifiedRecommendationsUseCase",
    "GetRecommendationsRequest",
    "GetRecommendationsResponse",
    "GetUnifiedRecommendationsUseCase",
    "GetConflictsRequest",
    "GetConflictsResponse",
    "GetConflictsUseCase",
]
