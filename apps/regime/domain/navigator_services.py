"""
Regime Navigator Services — 纯 Domain 层逻辑，不依赖 Django。

所有映射表均以 dataclass 配置对象提供默认值，
Application 层可从数据库加载配置并传入覆盖默认值。

提供：
- assess_regime_movement: 评估 regime 移动方向
- map_regime_to_asset_guidance: 将 regime 映射为资产配置指引
- determine_watch_indicators: 确定关注指标
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TypedDict

from apps.regime.domain.services_v2 import RegimeType, TrendIndicator


class AssetWeightRangePayload(TypedDict):
    """One normalized allocation range published by the navigator."""

    category: str
    lower: float
    upper: float
    label: str


class RegimeAssetGuidancePayload(TypedDict):
    """Asset guidance payload consumed by the navigator use case."""

    weight_ranges: list[AssetWeightRangePayload]
    risk_budget: float
    sectors: list[str]
    styles: list[str]
    reasoning: str


class WatchIndicatorPayload(TypedDict):
    """One normalized indicator watch rule."""

    code: str
    name: str
    threshold: str
    significance: str


_REGIME_NAMES = frozenset(regime.value for regime in RegimeType)
_ASSET_CATEGORIES = frozenset({"equity", "bond", "commodity", "cash"})
_WATCH_FIELDS = ("code", "name", "threshold", "significance")


def _unit_float(value: object, *, field_name: str) -> float:
    """Return a finite unit-interval value and reject bool coercion."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a finite number between 0 and 1")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be a finite number between 0 and 1")
    return normalized


def _regime_name(value: object, *, field_name: str) -> str:
    """Validate one configured Regime identifier."""

    if not isinstance(value, str) or value not in _REGIME_NAMES:
        raise ValueError(f"{field_name} must identify a supported Regime")
    return value


def _text_list(values: object, *, field_name: str) -> tuple[str, ...]:
    """Detach a bounded list of non-empty display labels."""

    if isinstance(values, str) or not isinstance(values, Sequence) or len(values) > 100:
        raise ValueError(f"{field_name} must contain at most 100 labels")
    normalized: list[str] = []
    for value in values:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 100
            or any(character in value for character in "\r\n\x00")
        ):
            raise ValueError(f"{field_name} contains an invalid label")
        normalized.append(value.strip())
    return tuple(normalized)


def _watch_rule(rule: object, *, field_name: str) -> Mapping[str, str]:
    """Validate and detach one watch-indicator rule."""

    if not isinstance(rule, Mapping) or set(rule) != set(_WATCH_FIELDS):
        raise ValueError(f"{field_name} must contain the canonical watch fields")
    normalized: dict[str, str] = {}
    for key in _WATCH_FIELDS:
        value = rule[key]
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 500
            or any(character in value for character in "\r\n\x00")
        ):
            raise ValueError(f"{field_name}.{key} is invalid")
        normalized[key] = value.strip()
    if normalized["significance"] not in {"high", "medium", "low"}:
        raise ValueError(f"{field_name}.significance is invalid")
    return MappingProxyType(normalized)


def _watch_payload(rule: Mapping[str, str]) -> WatchIndicatorPayload:
    """Return a detached typed payload for one validated watch rule."""

    return {
        "code": rule["code"],
        "name": rule["name"],
        "threshold": rule["threshold"],
        "significance": rule["significance"],
    }


# ==================== 配置 Dataclass（Domain 层默认值） ====================


@dataclass(frozen=True)
class RegimeAssetConfig:
    """Regime → 资产配置的映射配置

    所有值为默认值，可由 DB 覆盖。
    """

    # {regime_name: {category: (lower, upper)}}
    asset_ranges: Mapping[str, Mapping[str, tuple[float, float]]] = field(
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

    risk_budget: Mapping[str, float] = field(
        default_factory=lambda: {
            "Recovery": 0.85,
            "Overheat": 0.70,
            "Stagflation": 0.50,
            "Deflation": 0.60,
        }
    )

    # {regime_name: [sector_names]}
    sectors: Mapping[str, Sequence[str]] = field(
        default_factory=lambda: {
            "Recovery": ["消费", "科技", "金融"],
            "Overheat": ["能源", "材料", "公用事业"],
            "Stagflation": ["公用事业", "医药", "必选消费"],
            "Deflation": ["债券ETF", "货币基金", "高股息"],
        }
    )

    styles: Mapping[str, Sequence[str]] = field(
        default_factory=lambda: {
            "Recovery": ["成长", "中小盘"],
            "Overheat": ["价值", "周期"],
            "Stagflation": ["防御", "红利"],
            "Deflation": ["债券", "红利", "低波"],
        }
    )

    # 低置信度风险预算折扣因子
    low_confidence_threshold: float = 0.3
    low_confidence_discount: float = 0.8

    category_labels: Mapping[str, str] = field(
        default_factory=lambda: {
            "equity": "权益类",
            "bond": "债券类",
            "commodity": "商品类",
            "cash": "现金类",
        }
    )

    def __post_init__(self) -> None:
        """Validate and detach allocation policy loaded from persistence."""

        if not isinstance(self.asset_ranges, Mapping):
            raise ValueError("asset_ranges must be a mapping")
        normalized_ranges: dict[str, Mapping[str, tuple[float, float]]] = {}
        for raw_regime, categories in self.asset_ranges.items():
            regime_name = _regime_name(raw_regime, field_name="asset_ranges key")
            if not isinstance(categories, Mapping) or not categories:
                raise ValueError(f"asset_ranges[{regime_name}] must not be empty")
            normalized_categories: dict[str, tuple[float, float]] = {}
            for category, bounds in categories.items():
                if not isinstance(category, str) or category not in _ASSET_CATEGORIES:
                    raise ValueError("asset range category is unsupported")
                if not isinstance(bounds, Sequence) or len(bounds) != 2:
                    raise ValueError(f"asset_ranges[{regime_name}][{category}] is invalid")
                lower = _unit_float(bounds[0], field_name=f"{regime_name}.{category}.lower")
                upper = _unit_float(bounds[1], field_name=f"{regime_name}.{category}.upper")
                if lower > upper:
                    raise ValueError(f"{regime_name}.{category} lower exceeds upper")
                normalized_categories[category] = (lower, upper)
            lower_total = math.fsum(bounds[0] for bounds in normalized_categories.values())
            upper_total = math.fsum(bounds[1] for bounds in normalized_categories.values())
            if lower_total > 1.0 + 1e-9 or upper_total < 1.0 - 1e-9:
                raise ValueError(f"asset_ranges[{regime_name}] cannot form a full allocation")
            normalized_ranges[regime_name] = MappingProxyType(normalized_categories)

        if not isinstance(self.risk_budget, Mapping):
            raise ValueError("risk_budget must be a mapping")
        normalized_budgets = {
            _regime_name(name, field_name="risk_budget key"): _unit_float(
                value, field_name=f"risk_budget[{name}]"
            )
            for name, value in self.risk_budget.items()
        }

        normalized_text_maps: dict[str, Mapping[str, tuple[str, ...]]] = {}
        for field_name, values in (("sectors", self.sectors), ("styles", self.styles)):
            if not isinstance(values, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            normalized_text_maps[field_name] = MappingProxyType(
                {
                    _regime_name(name, field_name=f"{field_name} key"): _text_list(
                        labels, field_name=f"{field_name}[{name}]"
                    )
                    for name, labels in values.items()
                }
            )

        if not isinstance(self.category_labels, Mapping):
            raise ValueError("category_labels must be a mapping")
        normalized_labels: dict[str, str] = {}
        for category, label in self.category_labels.items():
            if category not in _ASSET_CATEGORIES:
                raise ValueError("category label key is unsupported")
            normalized_labels[category] = _text_list(
                [label], field_name=f"category_labels[{category}]"
            )[0]

        object.__setattr__(self, "asset_ranges", MappingProxyType(normalized_ranges))
        object.__setattr__(self, "risk_budget", MappingProxyType(normalized_budgets))
        object.__setattr__(self, "sectors", normalized_text_maps["sectors"])
        object.__setattr__(self, "styles", normalized_text_maps["styles"])
        object.__setattr__(self, "category_labels", MappingProxyType(normalized_labels))
        object.__setattr__(
            self,
            "low_confidence_threshold",
            _unit_float(self.low_confidence_threshold, field_name="low_confidence_threshold"),
        )
        object.__setattr__(
            self,
            "low_confidence_discount",
            _unit_float(self.low_confidence_discount, field_name="low_confidence_discount"),
        )

    @classmethod
    def defaults(cls) -> "RegimeAssetConfig":
        return cls()


@dataclass(frozen=True)
class WatchIndicatorConfig:
    """关注指标配置

    定义各场景下需要关注的指标及其阈值描述。
    """

    # 基础指标（总是显示）
    base_indicators: Sequence[Mapping[str, str]] = field(
        default_factory=lambda: [
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
        ]
    )

    # 通胀预警指标
    inflation_indicator: Mapping[str, str] = field(
        default_factory=lambda: {
            "code": "CN_NHCI",
            "name": "南华商品指数",
            "threshold": "持续上涨 → 通胀压力加大",
            "significance": "medium",
        }
    )

    # 利差指标
    term_spread_indicator: Mapping[str, str] = field(
        default_factory=lambda: {
            "code": "CN_TERM_SPREAD_10Y2Y",
            "name": "国债利差(10Y-2Y)",
            "threshold": "倒挂 → 衰退预警；走扩 → 增长预期改善",
            "significance": "high",
        }
    )

    # 信贷指标
    credit_indicator: Mapping[str, str] = field(
        default_factory=lambda: {
            "code": "CN_NEW_CREDIT",
            "name": "新增信贷",
            "threshold": "同比增速回升 → 经济见底信号",
            "significance": "medium",
        }
    )

    def __post_init__(self) -> None:
        """Validate and detach every published watch rule."""

        if isinstance(self.base_indicators, str) or not isinstance(self.base_indicators, Sequence):
            raise ValueError("base_indicators must be a sequence")
        object.__setattr__(
            self,
            "base_indicators",
            tuple(
                _watch_rule(rule, field_name=f"base_indicators[{index}]")
                for index, rule in enumerate(self.base_indicators)
            ),
        )
        for field_name in (
            "inflation_indicator",
            "term_spread_indicator",
            "credit_indicator",
        ):
            object.__setattr__(
                self,
                field_name,
                _watch_rule(getattr(self, field_name), field_name=field_name),
            )

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
    if not isinstance(regime, RegimeType):
        raise ValueError("regime must be a RegimeType")
    if not isinstance(trend_indicators, list) or any(
        not isinstance(indicator, TrendIndicator) for indicator in trend_indicators
    ):
        raise ValueError("trend_indicators must contain TrendIndicator values")
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
) -> RegimeAssetGuidancePayload:
    """
    将 regime 映射为资产配置指引

    Args:
        regime: 当前 regime
        confidence: 置信度
        config: 资产配置映射配置（None 则使用默认值）

    Returns:
        dict with 'weight_ranges', 'risk_budget', 'sectors', 'styles', 'reasoning'
    """
    if not isinstance(regime, RegimeType):
        raise ValueError("regime must be a RegimeType")
    confidence = _unit_float(confidence, field_name="confidence")
    if config is not None and not isinstance(config, RegimeAssetConfig):
        raise ValueError("config must be a RegimeAssetConfig")
    config = config or RegimeAssetConfig.defaults()
    defaults = RegimeAssetConfig.defaults()

    regime_name = regime.value
    ranges = config.asset_ranges.get(regime_name, defaults.asset_ranges[regime_name])
    risk_budget = config.risk_budget.get(regime_name, defaults.risk_budget[regime_name])
    sectors = config.sectors.get(regime_name, defaults.sectors[regime_name])
    styles = config.styles.get(regime_name, defaults.styles[regime_name])

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
        "sectors": list(sectors),
        "styles": list(styles),
        "reasoning": _build_regime_reasoning(regime_name, confidence, config),
    }


def determine_watch_indicators(
    regime: RegimeType,
    direction: str,
    transition_target: str | None,
    config: WatchIndicatorConfig | None = None,
) -> list[WatchIndicatorPayload]:
    """
    确定当前应关注的指标

    Args:
        regime: 当前 regime
        direction: 移动方向
        transition_target: 转折目标
        config: 关注指标配置（None 则使用默认值）
    """
    if not isinstance(regime, RegimeType):
        raise ValueError("regime must be a RegimeType")
    if direction not in {"stable", "transitioning"}:
        raise ValueError("direction must be stable or transitioning")
    if transition_target is not None and transition_target not in _REGIME_NAMES:
        raise ValueError("transition_target must identify a supported Regime")
    if config is not None and not isinstance(config, WatchIndicatorConfig):
        raise ValueError("config must be a WatchIndicatorConfig")
    config = config or WatchIndicatorConfig.defaults()

    indicators = [_watch_payload(rule) for rule in config.base_indicators]

    if transition_target == "Stagflation" or regime == RegimeType.OVERHEAT:
        indicators.append(_watch_payload(config.inflation_indicator))

    if transition_target in ("Deflation", "Recovery") or direction == "transitioning":
        indicators.append(_watch_payload(config.term_spread_indicator))

    if transition_target == "Recovery" or regime == RegimeType.DEFLATION:
        indicators.append(_watch_payload(config.credit_indicator))

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
