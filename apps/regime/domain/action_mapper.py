"""
Regime Action Mapper - 将 Regime 导航仪 + Pulse 脉搏转化为可执行的行动建议。

纯 Domain 层逻辑，不依赖 Django 或外部库。
所有阈值/参数通过 ActionMapperConfig 注入。
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TypedDict


class WeightRange(TypedDict):
    """Validated asset allocation interval consumed by the action mapper."""

    category: str
    lower: float
    upper: float


def cached_action_is_stale(
    observed_at: date,
    *,
    as_of_date: date,
    max_business_days: int = 1,
) -> bool:
    """Return whether a persisted daily action is too old for current decisions."""

    if max_business_days < 0:
        raise ValueError("max_business_days must be non-negative")
    if observed_at > as_of_date:
        return True
    current = observed_at + timedelta(days=1)
    age = 0
    while current <= as_of_date:
        if current.weekday() < 5:
            age += 1
        current += timedelta(days=1)
    return age > max_business_days


@dataclass(frozen=True)
class ActionMapperConfig:
    """Action Mapper 配置

    所有阈值均可通过 DB 覆盖，Domain 层提供默认值。
    """

    # Pulse regime strength 对风险预算的调整系数
    weak_risk_factor: float = 0.85
    strong_risk_factor: float = 1.05
    max_risk_budget: float = 0.95

    # 单一持仓上限
    position_limit_high_risk: float = 0.10  # risk_budget >= 0.7 时
    position_limit_low_risk: float = 0.08  # risk_budget < 0.7 时
    position_limit_threshold: float = 0.70

    # 对冲建议触发条件
    hedge_enabled: bool = True

    def __post_init__(self) -> None:
        """Reject non-finite or incoherent action limits."""

        bounded = {
            "weak_risk_factor": self.weak_risk_factor,
            "max_risk_budget": self.max_risk_budget,
            "position_limit_high_risk": self.position_limit_high_risk,
            "position_limit_low_risk": self.position_limit_low_risk,
            "position_limit_threshold": self.position_limit_threshold,
        }
        for name, value in bounded.items():
            if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        if (
            isinstance(self.strong_risk_factor, bool)
            or not math.isfinite(self.strong_risk_factor)
            or self.strong_risk_factor <= 0
        ):
            raise ValueError("strong_risk_factor must be finite and positive")

    @classmethod
    def defaults(cls) -> "ActionMapperConfig":
        return cls()


@dataclass(frozen=True)
class RegimeActionRecommendation:
    """Regime 行动建议

    Regime (权重区间) + Pulse (微调) → 具体配置。
    """

    # 具体资产配置（百分比，0-1）
    asset_weights: dict[str, float]  # {"equity": 0.55, "bond": 0.30, ...}

    # 风险预算
    risk_budget_pct: float  # 总仓位上限
    position_limit_pct: float  # 单一持仓上限

    # 板块建议
    recommended_sectors: list[str]
    benefiting_styles: list[str]

    # 对冲建议（可选）
    hedge_recommendation: str | None

    # 可解释性
    reasoning: str
    regime_contribution: str  # "复苏期，权益区间 50-70%"
    pulse_contribution: str  # "脉搏偏弱(score=-0.15)，取区间下半部分"

    # 元数据
    generated_at: date
    confidence: float  # 综合置信度
    must_not_use_for_decision: bool = False
    blocked_reason: str = ""
    blocked_code: str = ""
    pulse_observed_at: date | None = None
    pulse_is_reliable: bool = True
    stale_indicator_codes: list[str] = field(default_factory=list)
    context_observed_at: date | None = None
    context_source: str = "live_action_fallback"


def map_regime_pulse_to_action(
    regime_name: str,
    weight_ranges: list[WeightRange],
    risk_budget: float,
    sectors: list[str],
    styles: list[str],
    reasoning: str,
    pulse_composite_score: float,  # -1 to +1
    pulse_regime_strength: str,  # 'strong', 'moderate', 'weak'
    confidence: float,
    as_of_date: date,
    config: ActionMapperConfig | None = None,
) -> RegimeActionRecommendation:
    """
    将 Regime 权重区间 + Pulse 综合分数 → 具体资产配置

    核心逻辑：
    - Pulse score > 0 → 权重区间偏上限（进攻）
    - Pulse score < 0 → 权重区间偏下限（防御）
    - 线性插值：ratio = (score + 1) / 2

    Args:
        config: 可选配置，None 则使用默认值
    """
    if config is None:
        config = ActionMapperConfig.defaults()
    if not weight_ranges:
        raise ValueError("weight_ranges must not be empty")
    if isinstance(pulse_composite_score, bool) or not math.isfinite(pulse_composite_score):
        raise ValueError("pulse_composite_score must be finite")
    if pulse_regime_strength not in {"strong", "moderate", "weak"}:
        raise ValueError("pulse_regime_strength is unsupported")
    for name, value in (("risk_budget", risk_budget), ("confidence", confidence)):
        if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be finite and between 0 and 1")

    seen_categories: set[str] = set()
    for weight_range in weight_ranges:
        category = weight_range["category"]
        lower = weight_range["lower"]
        upper = weight_range["upper"]
        if not isinstance(category, str) or not category.strip() or category in seen_categories:
            raise ValueError("weight range categories must be non-empty and unique")
        if (
            any(
                isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1
                for value in (lower, upper)
            )
            or lower > upper
        ):
            raise ValueError("weight ranges must be finite, ordered, and between 0 and 1")
        seen_categories.add(category)

    # 将 pulse score 从 [-1, 1] 映射到 [0, 1] 作为插值系数
    interpolation_ratio = (pulse_composite_score + 1.0) / 2.0
    interpolation_ratio = max(0.0, min(1.0, interpolation_ratio))

    asset_weights: dict[str, float] = {}
    for wr in weight_ranges:
        lower = wr["lower"]
        upper = wr["upper"]
        weight = lower + (upper - lower) * interpolation_ratio
        asset_weights[wr["category"]] = round(weight, 3)

    # 归一化确保总和 = 1.0
    total = sum(asset_weights.values())
    if total > 0:
        asset_weights = {k: round(v / total, 3) for k, v in asset_weights.items()}

    # Pulse 弱时进一步压缩风险预算
    adjusted_risk_budget = risk_budget
    if pulse_regime_strength == "weak":
        adjusted_risk_budget *= config.weak_risk_factor
    elif pulse_regime_strength == "strong":
        adjusted_risk_budget = min(
            adjusted_risk_budget * config.strong_risk_factor,
            config.max_risk_budget,
        )

    # 单一持仓上限
    position_limit = (
        config.position_limit_high_risk
        if risk_budget >= config.position_limit_threshold
        else config.position_limit_low_risk
    )

    # 对冲建议
    hedge_rec: str | None = None
    if config.hedge_enabled:
        if regime_name == "Stagflation":
            hedge_rec = "建议持有商品多头对冲通胀风险"
        elif regime_name == "Deflation" and pulse_regime_strength == "weak":
            hedge_rec = "可考虑增加国债久期对冲下行风险"

    # 可解释性
    regime_str = f"{regime_name}期"
    eq_range = next((wr for wr in weight_ranges if wr["category"] == "equity"), None)
    regime_contrib = (
        f"{regime_str}，权益区间 {eq_range['lower']*100:.0f}-{eq_range['upper']*100:.0f}%"
        if eq_range
        else regime_str
    )
    pulse_contrib = (
        f"脉搏{pulse_regime_strength}(score={pulse_composite_score:.2f})，"
        f"插值系数{interpolation_ratio:.2f}"
    )

    return RegimeActionRecommendation(
        asset_weights=asset_weights,
        risk_budget_pct=round(adjusted_risk_budget, 3),
        position_limit_pct=position_limit,
        recommended_sectors=sectors,
        benefiting_styles=styles,
        hedge_recommendation=hedge_rec,
        reasoning=reasoning,
        regime_contribution=regime_contrib,
        pulse_contribution=pulse_contrib,
        generated_at=as_of_date,
        confidence=confidence,
        must_not_use_for_decision=False,
        blocked_reason="",
        blocked_code="",
        pulse_observed_at=as_of_date,
        pulse_is_reliable=True,
        stale_indicator_codes=[],
        context_observed_at=as_of_date,
        context_source="live_action_fallback",
    )
