"""
Regime Action Mapper - 将 Regime 导航仪 + Pulse 脉搏转化为可执行的行动建议。

纯 Domain 层逻辑，不依赖 Django 或外部库。
所有阈值/参数通过 ActionMapperConfig 注入。
"""

from dataclasses import dataclass, field
from datetime import date


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
    position_limit_high_risk: float = 0.10   # risk_budget >= 0.7 时
    position_limit_low_risk: float = 0.08    # risk_budget < 0.7 时
    position_limit_threshold: float = 0.70

    # 对冲建议触发条件
    hedge_enabled: bool = True

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
    risk_budget_pct: float       # 总仓位上限
    position_limit_pct: float    # 单一持仓上限

    # 板块建议
    recommended_sectors: list[str]
    benefiting_styles: list[str]

    # 对冲建议（可选）
    hedge_recommendation: str | None

    # 可解释性
    reasoning: str
    regime_contribution: str   # "复苏期，权益区间 50-70%"
    pulse_contribution: str    # "脉搏偏弱(score=-0.15)，取区间下半部分"

    # 元数据
    generated_at: date
    confidence: float  # 综合置信度


def map_regime_pulse_to_action(
    regime_name: str,
    weight_ranges: list[dict],
    risk_budget: float,
    sectors: list[str],
    styles: list[str],
    reasoning: str,
    pulse_composite_score: float,  # -1 to +1
    pulse_regime_strength: str,    # 'strong', 'moderate', 'weak'
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
    )
