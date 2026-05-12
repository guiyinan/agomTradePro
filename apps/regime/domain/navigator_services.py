"""
Regime Navigator Services — 纯 Domain 层逻辑，不依赖 Django。

所有映射表均以 dataclass 配置对象提供默认值，
Application 层可从数据库加载配置并传入覆盖默认值。

提供：
- assess_regime_movement: 评估 regime 移动方向
- map_regime_to_asset_guidance: 将 regime 映射为资产配置指引
- determine_watch_indicators: 确定关注指标
"""

from dataclasses import dataclass, field

from apps.regime.domain.services_v2 import RegimeType, TrendIndicator

# ==================== 配置 Dataclass（Domain 层默认值） ====================


@dataclass(frozen=True)
class RegimeAssetConfig:
    """Regime → 资产配置的映射配置

    所有值为默认值，可由 DB 覆盖。
    """
    # {regime_name: {category: (lower, upper)}}
    asset_ranges: dict[str, dict[str, tuple[float, float]]] = field(
        default_factory=lambda: {
            "Recovery": {
                "equity": (0.50, 0.70),
                "bond": (0.15, 0.30),
                "commodity": (0.05, 0.15),
                "cash": (0.05, 0.15),
            },
            "Overheat": {
                "equity": (0.20, 0.40),
                "bond": (0.10, 0.25),
                "commodity": (0.25, 0.40),
                "cash": (0.10, 0.20),
            },
            "Stagflation": {
                "equity": (0.05, 0.20),
                "bond": (0.20, 0.35),
                "commodity": (0.15, 0.30),
                "cash": (0.25, 0.40),
            },
            "Deflation": {
                "equity": (0.10, 0.25),
                "bond": (0.40, 0.60),
                "commodity": (0.00, 0.10),
                "cash": (0.15, 0.30),
            },
        }
    )

    risk_budget: dict[str, float] = field(default_factory=lambda: {
        "Recovery": 0.85,
        "Overheat": 0.70,
        "Stagflation": 0.50,
        "Deflation": 0.60,
    })

    # {regime_name: [sector_names]}
    sectors: dict[str, list[str]] = field(default_factory=lambda: {
        "Recovery": ["消费", "科技", "金融"],
        "Overheat": ["能源", "材料", "公用事业"],
        "Stagflation": ["公用事业", "医药", "必选消费"],
        "Deflation": ["债券ETF", "货币基金", "高股息"],
    })

    styles: dict[str, list[str]] = field(default_factory=lambda: {
        "Recovery": ["成长", "中小盘"],
        "Overheat": ["价值", "周期"],
        "Stagflation": ["防御", "红利"],
        "Deflation": ["债券", "红利", "低波"],
    })

    # 低置信度风险预算折扣因子
    low_confidence_threshold: float = 0.3
    low_confidence_discount: float = 0.8

    category_labels: dict[str, str] = field(default_factory=lambda: {
        "equity": "权益类",
        "bond": "债券类",
        "commodity": "商品类",
        "cash": "现金类",
    })

    @classmethod
    def defaults(cls) -> "RegimeAssetConfig":
        return cls()


@dataclass(frozen=True)
class WatchIndicatorConfig:
    """关注指标配置

    定义各场景下需要关注的指标及其阈值描述。
    """
    # 基础指标（总是显示）
    base_indicators: list[dict[str, str]] = field(default_factory=lambda: [
        {
            "code": "PMI",
            "name": "制造业PMI",
            "threshold": "跌破50 → 收缩；站上50 → 扩张",
            "significance": "high",
        },
        {
            "code": "CPI",
            "name": "居民消费价格指数",
            "threshold": "> 2% → 高通胀；< 0 → 通缩",
            "significance": "high",
        },
    ])

    # 通胀预警指标
    inflation_indicator: dict[str, str] = field(default_factory=lambda: {
        "code": "CN_NHCI",
        "name": "南华商品指数",
        "threshold": "持续上涨 → 通胀压力加大",
        "significance": "medium",
    })

    # 利差指标
    term_spread_indicator: dict[str, str] = field(default_factory=lambda: {
        "code": "CN_TERM_SPREAD_10Y2Y",
        "name": "国债利差(10Y-2Y)",
        "threshold": "倒挂 → 衰退预警；走扩 → 增长预期改善",
        "significance": "high",
    })

    # 信贷指标
    credit_indicator: dict[str, str] = field(default_factory=lambda: {
        "code": "CN_NEW_CREDIT",
        "name": "新增信贷",
        "threshold": "同比增速回升 → 经济见底信号",
        "significance": "medium",
    })

    @classmethod
    def defaults(cls) -> "WatchIndicatorConfig":
        return cls()


# ==================== 服务函数 ====================


def assess_regime_movement(
    regime: RegimeType,
    trend_indicators: list[TrendIndicator],
) -> tuple[str, str | None, float, list[str]]:
    """
    评估 regime 移动方向

    基于 PMI 和 CPI 的趋势指标，判断当前 regime 是否稳定。

    Returns:
        (direction, transition_target, probability, reasons)
    """
    pmi_trend: TrendIndicator | None = None
    cpi_trend: TrendIndicator | None = None
    reasons: list[str] = []

    for ti in trend_indicators:
        if ti.indicator_code == "PMI":
            pmi_trend = ti
        elif ti.indicator_code == "CPI":
            cpi_trend = ti

    if not pmi_trend or not cpi_trend:
        return "stable", None, 0.0, ["趋势数据不足"]

    if regime == RegimeType.RECOVERY:
        if pmi_trend.direction == "down":
            reasons.append(f"PMI 动量下降 (z={pmi_trend.momentum_z:.2f})，增长可能减弱")
            if cpi_trend.direction == "up":
                return "transitioning", "Stagflation", 0.4, reasons + ["CPI 上行，滞胀风险"]
            return "transitioning", "Deflation", 0.3, reasons
        if cpi_trend.direction == "up" and cpi_trend.strength == "strong":
            reasons.append("CPI 强势上行，通胀压力加大")
            return "transitioning", "Overheat", 0.35, reasons

    elif regime == RegimeType.OVERHEAT:
        if pmi_trend.direction == "down":
            reasons.append("PMI 动量下降，增长放缓")
            return "transitioning", "Stagflation", 0.35, reasons
        if cpi_trend.direction == "down" and cpi_trend.strength in ("moderate", "strong"):
            reasons.append("CPI 回落明显")
            return "transitioning", "Recovery", 0.3, reasons

    elif regime == RegimeType.STAGFLATION:
        if cpi_trend.direction == "down":
            reasons.append("CPI 回落")
            if pmi_trend.direction == "down":
                return "transitioning", "Deflation", 0.35, reasons + ["PMI 仍弱"]
            return "transitioning", "Recovery", 0.3, reasons + ["增长未恶化"]
        if pmi_trend.direction == "up" and pmi_trend.strength in ("moderate", "strong"):
            reasons.append("PMI 回升明显")
            return "transitioning", "Overheat", 0.3, reasons

    elif regime == RegimeType.DEFLATION:
        if pmi_trend.direction == "up":
            reasons.append("PMI 回升")
            if cpi_trend.direction == "up":
                return "transitioning", "Overheat", 0.3, reasons + ["通胀同步上行"]
            return "transitioning", "Recovery", 0.4, reasons + ["通胀受控"]
        if cpi_trend.direction == "up" and cpi_trend.strength in ("moderate", "strong"):
            reasons.append("CPI 上行但增长仍弱")
            return "transitioning", "Stagflation", 0.25, reasons

    return "stable", None, 0.0, ["PMI/CPI 趋势与当前 regime 一致"]


def map_regime_to_asset_guidance(
    regime: RegimeType,
    confidence: float,
    config: RegimeAssetConfig | None = None,
) -> dict:
    """
    将 regime 映射为资产配置指引

    Args:
        regime: 当前 regime
        confidence: 置信度
        config: 资产配置映射配置（None 则使用默认值）

    Returns:
        dict with 'weight_ranges', 'risk_budget', 'sectors', 'styles', 'reasoning'
    """
    if config is None:
        config = RegimeAssetConfig.defaults()

    regime_name = regime.value
    ranges = config.asset_ranges.get(regime_name, config.asset_ranges.get("Deflation", {}))
    risk_budget = config.risk_budget.get(regime_name, 0.5)
    sectors = config.sectors.get(regime_name, [])
    styles = config.styles.get(regime_name, [])

    if confidence < config.low_confidence_threshold:
        risk_budget *= config.low_confidence_discount

    return {
        "weight_ranges": [
            {
                "category": cat,
                "lower": lo,
                "upper": hi,
                "label": config.category_labels.get(cat, cat),
            }
            for cat, (lo, hi) in ranges.items()
        ],
        "risk_budget": risk_budget,
        "sectors": sectors,
        "styles": styles,
        "reasoning": _build_regime_reasoning(regime_name, confidence, config),
    }


def determine_watch_indicators(
    regime: RegimeType,
    direction: str,
    transition_target: str | None,
    config: WatchIndicatorConfig | None = None,
) -> list[dict]:
    """
    确定当前应关注的指标

    Args:
        regime: 当前 regime
        direction: 移动方向
        transition_target: 转折目标
        config: 关注指标配置（None 则使用默认值）
    """
    if config is None:
        config = WatchIndicatorConfig.defaults()

    indicators: list[dict] = list(config.base_indicators)

    if transition_target == "Stagflation" or regime == RegimeType.OVERHEAT:
        indicators.append(dict(config.inflation_indicator))

    if transition_target in ("Deflation", "Recovery") or direction == "transitioning":
        indicators.append(dict(config.term_spread_indicator))

    if transition_target == "Recovery" or regime == RegimeType.DEFLATION:
        indicators.append(dict(config.credit_indicator))

    return indicators


def _build_regime_reasoning(
    regime_name: str,
    confidence: float,
    config: RegimeAssetConfig,
) -> str:
    """生成 regime 配置逻辑说明"""
    reasons = {
        "Recovery": "经济复苏期，增长改善+通胀受控，权益类资产受益最大。建议超配权益、标配债券、低配商品。",
        "Overheat": "经济过热期，增长强劲但通胀上升，商品类资产受益。建议超配商品、标配权益、低配债券。",
        "Stagflation": "滞胀期，增长放缓+通胀高企，防御为主。建议超配现金和债券、低配权益。",
        "Deflation": "通缩期，增长和通胀双弱，债券类资产受益。建议超配债券、标配现金、低配权益和商品。",
    }
    base = reasons.get(regime_name, "环境不确定，建议均衡配置。")
    if confidence < config.low_confidence_threshold:
        base += " 当前置信度较低，建议降低整体仓位。"
    return base
