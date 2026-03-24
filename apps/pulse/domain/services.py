"""Pulse 计算服务 — 纯 Python 域逻辑。"""

from apps.pulse.domain.entities import (
    DimensionScore,
    PulseConfig,
    PulseIndicatorReading,
    PulseSnapshot,
)


def calculate_dimension_score(
    readings: list[PulseIndicatorReading],
    dimension: str,
) -> DimensionScore:
    """
    计算单个维度的汇总分数

    等权聚合维度内所有有效指标的 signal_score。
    """
    valid = [r for r in readings if r.dimension == dimension and not r.is_stale]
    if not valid:
        return DimensionScore(
            dimension=dimension,
            score=0.0,
            signal="neutral",
            indicator_count=0,
            description=f"{_dim_label(dimension)}数据不足",
        )

    total_weight = sum(r.weight for r in valid)
    if total_weight == 0:
        avg_score = 0.0
    else:
        avg_score = sum(r.signal_score * r.weight for r in valid) / total_weight

    signal = "bullish" if avg_score > 0.2 else ("bearish" if avg_score < -0.2 else "neutral")
    strength = "偏强" if avg_score > 0.2 else ("偏弱" if avg_score < -0.2 else "中性")

    return DimensionScore(
        dimension=dimension,
        score=round(avg_score, 3),
        signal=signal,
        indicator_count=len(valid),
        description=f"{_dim_label(dimension)}{strength}",
    )


def calculate_pulse(
    readings: list[PulseIndicatorReading],
    regime_context: str,
    observed_at,
    config: PulseConfig | None = None,
) -> PulseSnapshot:
    """
    计算完整的 Pulse 脉搏快照

    流程：
    1. 按维度聚合各指标分数
    2. 计算综合分数
    3. 判定 regime 内强弱
    4. 检测转折预警
    """
    if config is None:
        config = PulseConfig.defaults()

    dimensions = ["growth", "inflation", "liquidity", "sentiment"]
    dim_scores = [calculate_dimension_score(readings, d) for d in dimensions]

    # 综合分数（维度加权平均）
    composite = sum(
        ds.score * config.dimension_weights.get(ds.dimension, 0.25)
        for ds in dim_scores
    )
    composite = round(composite, 3)

    # Regime 内强弱
    regime_strength = assess_regime_strength(composite)

    # 转折预警
    warning, direction, reasons = detect_transition_warning(
        dim_scores, regime_context, config
    )

    stale_count = sum(1 for r in readings if r.is_stale)
    data_source = "calculated" if stale_count == 0 else "stale"

    return PulseSnapshot(
        observed_at=observed_at,
        regime_context=regime_context,
        dimension_scores=dim_scores,
        composite_score=composite,
        regime_strength=regime_strength,
        transition_warning=warning,
        transition_direction=direction,
        transition_reasons=reasons,
        indicator_readings=readings,
        data_source=data_source,
        stale_indicator_count=stale_count,
    )


def assess_regime_strength(composite_score: float) -> str:
    """根据综合分数判定 regime 内强弱"""
    if composite_score > 0.3:
        return "strong"
    elif composite_score > -0.3:
        return "moderate"
    else:
        return "weak"


def detect_transition_warning(
    dim_scores: list[DimensionScore],
    regime_context: str,
    config: PulseConfig,
) -> tuple[bool, str | None, list[str]]:
    """
    检测 regime 转折预警

    当多个维度信号与当前 regime 矛盾时触发预警。
    """
    dim_dict = {ds.dimension: ds.score for ds in dim_scores}
    growth = dim_dict.get("growth", 0)
    inflation = dim_dict.get("inflation", 0)
    liquidity = dim_dict.get("liquidity", 0)
    reasons: list[str] = []
    threshold = config.transition_warning_threshold

    if regime_context == "Recovery":
        if growth < threshold and liquidity < threshold:
            reasons.append("增长和流动性同步走弱")
            return True, "Deflation", reasons
        if inflation > abs(threshold):
            reasons.append("通胀维度走强，可能转向过热")
            return True, "Overheat", reasons

    elif regime_context == "Overheat":
        if growth < threshold:
            reasons.append("增长脉搏转弱")
            return True, "Stagflation", reasons
        if inflation < threshold:
            reasons.append("通胀维度回落")
            return True, "Recovery", reasons

    elif regime_context == "Stagflation":
        if inflation < threshold:
            reasons.append("通胀压力缓解")
            if growth < threshold:
                return True, "Deflation", reasons + ["增长仍弱"]
            return True, "Recovery", reasons + ["增长未恶化"]

    elif regime_context == "Deflation":
        if growth > abs(threshold) and liquidity > abs(threshold):
            reasons.append("增长和流动性同步改善")
            return True, "Recovery", reasons

    return False, None, []


def _dim_label(dimension: str) -> str:
    labels = {
        "growth": "增长脉搏",
        "inflation": "通胀脉搏",
        "liquidity": "流动性脉搏",
        "sentiment": "情绪脉搏",
    }
    return labels.get(dimension, dimension)
