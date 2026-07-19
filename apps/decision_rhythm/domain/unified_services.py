"""
Unified recommendation model parameters and aggregation for Decision Rhythm.

统一推荐模型参数管理（Top-down + Bottom-up 融合）、综合分计算与推荐聚合。

仅使用 Python 标准库。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .entities import DecisionFeatureSnapshot, UnifiedRecommendation

# 默认参数常量（仅用于兜底，不作为主配置）
DEFAULT_MODEL_PARAMS = {
    "alpha_model_weight": 0.40,
    "sentiment_weight": 0.15,
    "flow_weight": 0.15,
    "technical_weight": 0.15,
    "fundamental_weight": 0.15,
    "gate_penalty_cooldown": 0.10,
    "gate_penalty_quota": 0.10,
    "gate_penalty_volatility": 0.10,
    "composite_score_threshold": 0.60,
    "confidence_threshold": 0.70,
    "buy_score_threshold": 0.65,
    "buy_alpha_threshold": 0.60,
    "sell_score_threshold": 0.35,
    "sell_alpha_threshold": 0.30,
    "default_position_pct": 5.0,
    "max_capital_per_trade": 50000.0,
}


@dataclass(frozen=True)
class ModelWeights:
    """
    模型权重配置

    用于综合分计算的权重参数。

    Attributes:
        alpha_model_weight: Alpha 模型权重
        sentiment_weight: 舆情权重
        flow_weight: 资金流向权重
        technical_weight: 技术面权重
        fundamental_weight: 基本面权重
    """

    alpha_model_weight: float = 0.40
    sentiment_weight: float = 0.15
    flow_weight: float = 0.15
    technical_weight: float = 0.15
    fundamental_weight: float = 0.15

    def validate(self) -> tuple[bool, str]:
        """
        验证权重配置

        Returns:
            (是否有效, 错误消息)
        """
        weights = [
            self.alpha_model_weight,
            self.sentiment_weight,
            self.flow_weight,
            self.technical_weight,
            self.fundamental_weight,
        ]

        # 检查非负
        for w in weights:
            if w < 0:
                return False, "权重不能为负数"

        # 检查总和接近 1
        total = sum(weights)
        if abs(total - 1.0) > 0.01:
            return False, f"权重总和应为 1.0，当前为 {total:.2f}"

        return True, ""


@dataclass(frozen=True)
class GatePenalties:
    """
    Gate 惩罚参数

    用于风险惩罚项计算的参数。

    Attributes:
        cooldown_penalty: 冷却期不足惩罚
        quota_penalty: 配额紧张惩罚
        volatility_penalty: 波动超阈值惩罚
    """

    cooldown_penalty: float = 0.10
    quota_penalty: float = 0.10
    volatility_penalty: float = 0.10


class CompositeScoreCalculator:
    """
    综合分计算器

    实现"模型分数主导 + 规则约束兜底"的评分逻辑。

    综合分计算（默认）:
        composite_score = 0.40*alpha_model + 0.15*sentiment + 0.15*flow +
                         0.15*technical + 0.15*fundamental - penalties

    Hard Gate（必须通过）:
        - Beta Gate 不通过 -> 直接过滤
        - Regime/Policy 明确禁止 -> 直接过滤

    风险惩罚项（扣分）:
        - 冷却期不足、配额紧张、波动超阈值
    """

    def __init__(
        self,
        weights: ModelWeights | None = None,
        penalties: GatePenalties | None = None,
    ):
        """
        初始化综合分计算器

        Args:
            weights: 模型权重配置
            penalties: Gate 惩罚参数
        """
        self.weights = weights or ModelWeights()
        self.penalties = penalties or GatePenalties()

    def calculate(
        self,
        alpha_model_score: float,
        sentiment_score: float,
        flow_score: float,
        technical_score: float,
        fundamental_score: float,
        cooldown_violation: bool = False,
        quota_tight: bool = False,
        volatility_high: bool = False,
    ) -> tuple[float, list[str]]:
        """
        计算综合分

        Args:
            alpha_model_score: Alpha 模型分数
            sentiment_score: 舆情分数
            flow_score: 资金流向分数
            technical_score: 技术面分数
            fundamental_score: 基本面分数
            cooldown_violation: 是否违反冷却期
            quota_tight: 配额是否紧张
            volatility_high: 波动是否过高

        Returns:
            (综合分, 惩罚原因列表)
        """
        # 基础分数计算
        base_score = (
            self.weights.alpha_model_weight * alpha_model_score
            + self.weights.sentiment_weight * sentiment_score
            + self.weights.flow_weight * flow_score
            + self.weights.technical_weight * technical_score
            + self.weights.fundamental_weight * fundamental_score
        )

        # 风险惩罚项
        penalty = 0.0
        penalty_reasons = []

        if cooldown_violation:
            penalty += self.penalties.cooldown_penalty
            penalty_reasons.append("COOLDOWN_VIOLATION")

        if quota_tight:
            penalty += self.penalties.quota_penalty
            penalty_reasons.append("QUOTA_TIGHT")

        if volatility_high:
            penalty += self.penalties.volatility_penalty
            penalty_reasons.append("VOLATILITY_HIGH")

        # 最终分数（不低于 0）
        composite_score = max(0.0, base_score - penalty)

        return composite_score, penalty_reasons

    def calculate_from_snapshot(
        self,
        snapshot: DecisionFeatureSnapshot,
        cooldown_violation: bool = False,
        quota_tight: bool = False,
        volatility_high: bool = False,
    ) -> tuple[float, list[str]]:
        """
        从特征快照计算综合分

        Args:
            snapshot: 决策特征快照
            cooldown_violation: 是否违反冷却期
            quota_tight: 配额是否紧张
            volatility_high: 波动是否过高

        Returns:
            (综合分, 惩罚原因列表)
        """
        return self.calculate(
            alpha_model_score=snapshot.alpha_model_score,
            sentiment_score=snapshot.sentiment_score,
            flow_score=snapshot.flow_score,
            technical_score=snapshot.technical_score,
            fundamental_score=snapshot.fundamental_score,
            cooldown_violation=cooldown_violation,
            quota_tight=quota_tight,
            volatility_high=volatility_high,
        )


class RecommendationAggregator:
    """
    推荐聚合器

    实现按 account_id + security_code + side 去重和冲突处理。

    聚合规则:
        1. 同键多来源: 合并 reason/source，保留最高置信/最近快照
        2. 同证券方向冲突: 不落可执行区，入 conflict_queue
    """

    def aggregate(
        self,
        recommendations: list[UnifiedRecommendation],
    ) -> tuple[list[UnifiedRecommendation], list[UnifiedRecommendation], list[ConflictPair]]:
        """
        聚合推荐列表

        Args:
            recommendations: 原始推荐列表

        Returns:
            (去重后的推荐列表, 冲突推荐列表, 冲突对列表)
        """

        # 按聚合键分组
        groups: dict[str, list[UnifiedRecommendation]] = {}
        for rec in recommendations:
            key = rec.get_aggregation_key()
            if key not in groups:
                groups[key] = []
            groups[key].append(rec)

        # 处理每个分组
        deduplicated: list[UnifiedRecommendation] = []
        conflicts: list[UnifiedRecommendation] = []
        conflict_pairs: list[ConflictPair] = []

        for _key, group in groups.items():
            if len(group) == 1:
                deduplicated.append(group[0])
            else:
                # 多个同键推荐，合并
                merged = self._merge_recommendations(group)
                deduplicated.append(merged)

        # 检测 BUY/SELL 冲突
        account_security_groups: dict[str, dict[str, list[UnifiedRecommendation]]] = {}
        for rec in deduplicated:
            as_key = f"{rec.account_id}|{rec.security_code}"
            if as_key not in account_security_groups:
                account_security_groups[as_key] = {}
            if rec.side not in account_security_groups[as_key]:
                account_security_groups[as_key][rec.side] = []
            account_security_groups[as_key][rec.side].append(rec)

        # 处理冲突
        final_recommendations: list[UnifiedRecommendation] = []
        for _as_key, side_groups in account_security_groups.items():
            has_buy = "BUY" in side_groups and side_groups["BUY"]
            has_sell = "SELL" in side_groups and side_groups["SELL"]

            if has_buy and has_sell:
                # BUY/SELL 冲突
                buy_recs = side_groups["BUY"]
                sell_recs = side_groups["SELL"]

                for buy_rec in buy_recs:
                    conflicts.append(buy_rec)
                    for sell_rec in sell_recs:
                        conflict_pairs.append(
                            ConflictPair(
                                buy_recommendation=buy_rec,
                                sell_recommendation=sell_rec,
                            )
                        )

                for sell_rec in sell_recs:
                    if sell_rec not in conflicts:
                        conflicts.append(sell_rec)
            else:
                # 无冲突，加入最终列表
                for recs in side_groups.values():
                    final_recommendations.extend(recs)

        return final_recommendations, conflicts, conflict_pairs

    def _merge_recommendations(
        self,
        recommendations: list[UnifiedRecommendation],
    ) -> UnifiedRecommendation:
        """
        合并多个同键推荐

        策略: 保留最高置信/最近快照

        Args:
            recommendations: 同键推荐列表

        Returns:
            合并后的推荐
        """
        if len(recommendations) == 1:
            return recommendations[0]

        # 按置信度排序，取最高的
        sorted_recs = sorted(
            recommendations,
            key=lambda r: (r.confidence, r.created_at),
            reverse=True,
        )

        best = sorted_recs[0]

        # 合并 reason_codes 和 source
        all_reason_codes: list[str] = []
        all_source_signal_ids: list[str] = []
        all_source_candidate_ids: list[str] = []

        for rec in recommendations:
            all_reason_codes.extend(rec.reason_codes)
            all_source_signal_ids.extend(rec.source_signal_ids)
            all_source_candidate_ids.extend(rec.source_candidate_ids)

        # 去重
        unique_reason_codes = list(set(all_reason_codes))
        unique_source_signal_ids = list(set(all_source_signal_ids))
        unique_source_candidate_ids = list(set(all_source_candidate_ids))

        # 创建合并后的推荐（使用 best 的其他属性）
        from .entities import UnifiedRecommendation

        return UnifiedRecommendation(
            recommendation_id=best.recommendation_id,
            account_id=best.account_id,
            security_code=best.security_code,
            side=best.side,
            regime=best.regime,
            regime_confidence=best.regime_confidence,
            policy_level=best.policy_level,
            beta_gate_passed=best.beta_gate_passed,
            sentiment_score=best.sentiment_score,
            flow_score=best.flow_score,
            technical_score=best.technical_score,
            fundamental_score=best.fundamental_score,
            alpha_model_score=best.alpha_model_score,
            composite_score=best.composite_score,
            confidence=best.confidence,
            reason_codes=unique_reason_codes,
            human_rationale=best.human_rationale,
            fair_value=best.fair_value,
            entry_price_low=best.entry_price_low,
            entry_price_high=best.entry_price_high,
            target_price_low=best.target_price_low,
            target_price_high=best.target_price_high,
            stop_loss_price=best.stop_loss_price,
            position_pct=best.position_pct,
            suggested_quantity=best.suggested_quantity,
            max_capital=best.max_capital,
            source_signal_ids=unique_source_signal_ids,
            source_candidate_ids=unique_source_candidate_ids,
            feature_snapshot_id=best.feature_snapshot_id,
            status=best.status,
            created_at=best.created_at,
            updated_at=datetime.now(UTC),
        )


@dataclass
class ConflictPair:
    """
    冲突对

    表示同证券 BUY/SELL 冲突。

    Attributes:
        buy_recommendation: BUY 方向的推荐
        sell_recommendation: SELL 方向的推荐
    """

    buy_recommendation: UnifiedRecommendation
    sell_recommendation: UnifiedRecommendation


__all__ = [
    "DEFAULT_MODEL_PARAMS",
    "CompositeScoreCalculator",
    "ConflictPair",
    "GatePenalties",
    "ModelWeights",
    "RecommendationAggregator",
]
