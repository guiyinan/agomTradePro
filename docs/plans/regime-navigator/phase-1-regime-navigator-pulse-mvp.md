# Phase 1: Regime Navigator + Pulse MVP + Dashboard 改造

> **状态**: ✅ **已完成 (2026-03-24)**
> **父文档**: [regime-navigator-pulse-redesign-260323.md](regime-navigator-pulse-redesign-260323.md)
> **预估周期**: 5-6 周
> **目标**: 最小完整垂直切片 — regime 导航仪 + pulse 脉搏 → 联合行动建议 → 在 dashboard 上可见

---

## 1A. Regime Navigator 域增强（Week 1-2）

### 1A.1 新增 Domain 实体

**文件**: `apps/regime/domain/entities.py`（追加到文件末尾）

```python
from apps.regime.domain.services_v2 import RegimeType, RegimeCalculationResult


@dataclass(frozen=True)
class RegimeMovement:
    """Regime 移动方向判定

    描述当前 regime 是稳定还是正在向另一个象限转移。
    """
    direction: str  # 'stable', 'transitioning'
    transition_target: str | None  # 目标象限名称，如 "Overheat"
    transition_probability: float  # 0-1, 转折概率
    leading_indicators: list[str]  # 触发转折预警的指标说明列表
    momentum_summary: str  # "PMI 上升 + CPI 持平" 等描述


@dataclass(frozen=True)
class AssetWeightRange:
    """资产类别权重区间"""
    category: str  # 'equity', 'bond', 'commodity', 'cash'
    lower: float   # 下限百分比 (0-1)
    upper: float   # 上限百分比 (0-1)
    label: str     # 中文标签，如 "权益类"


@dataclass(frozen=True)
class RegimeAssetGuidance:
    """Regime 资产配置指引

    基于当前 regime 给出的大方向资产配置建议。
    提供的是区间而非精确值——精确值由 Pulse 微调产生。
    """
    weight_ranges: list[AssetWeightRange]
    risk_budget_pct: float  # 总仓位上限 (0-1)
    recommended_sectors: list[str]  # ["消费", "科技"] 等
    benefiting_styles: list[str]  # ["成长", "价值"] 等
    reasoning: str  # 配置逻辑说明


@dataclass(frozen=True)
class WatchIndicator:
    """关注指标"""
    code: str            # 指标代码
    name: str            # 人类可读名称
    current_value: float
    threshold: str       # "PMI 跌破 50" 等描述
    significance: str    # 'high', 'medium', 'low'


@dataclass(frozen=True)
class RegimeNavigatorOutput:
    """Regime 导航仪完整输出

    组合 RegimeCalculationResult + Movement + AssetGuidance + WatchIndicators。
    这是 Regime 模块对外输出的最完整形态。
    """
    # 基础 regime 判定（复用现有）
    regime_result: RegimeCalculationResult

    # 扩展：移动方向
    movement: RegimeMovement

    # 扩展：资产配置指引
    asset_guidance: RegimeAssetGuidance

    # 扩展：关注指标列表
    watch_indicators: list[WatchIndicator]

    # 元数据
    generated_at: date
    data_freshness: str  # 'fresh', 'stale', 'degraded'

    @property
    def regime_name(self) -> str:
        return self.regime_result.regime.value

    @property
    def confidence(self) -> float:
        return self.regime_result.confidence

    @property
    def is_transitioning(self) -> bool:
        return self.movement.direction == 'transitioning'
```

### 1A.2 新增 Domain 服务

**文件**: `apps/regime/domain/services_v2.py`（追加到文件末尾）

```python
# ==================== Navigator Services ====================

# Regime → 资产类别权重映射表
REGIME_ASSET_RANGES: dict[str, dict[str, tuple[float, float]]] = {
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

REGIME_RISK_BUDGET: dict[str, float] = {
    "Recovery": 0.85,
    "Overheat": 0.70,
    "Stagflation": 0.50,
    "Deflation": 0.60,
}

REGIME_SECTORS: dict[str, list[str]] = {
    "Recovery": ["消费", "科技", "金融"],
    "Overheat": ["能源", "材料", "公用事业"],
    "Stagflation": ["公用事业", "医药", "必选消费"],
    "Deflation": ["债券ETF", "货币基金", "高股息"],
}

REGIME_STYLES: dict[str, list[str]] = {
    "Recovery": ["成长", "中小盘"],
    "Overheat": ["价值", "周期"],
    "Stagflation": ["防御", "红利"],
    "Deflation": ["债券", "红利", "低波"],
}


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
    pmi_trend = None
    cpi_trend = None
    reasons = []

    for ti in trend_indicators:
        if ti.indicator_code == "PMI":
            pmi_trend = ti
        elif ti.indicator_code == "CPI":
            cpi_trend = ti

    if not pmi_trend or not cpi_trend:
        return "stable", None, 0.0, ["趋势数据不足"]

    # 基于当前 regime + 趋势方向判定转折可能性
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
) -> dict:
    """
    将 regime 映射为资产配置指引

    Returns:
        dict with 'weight_ranges', 'risk_budget', 'sectors', 'styles', 'reasoning'
    """
    regime_name = regime.value
    ranges = REGIME_ASSET_RANGES.get(regime_name, REGIME_ASSET_RANGES["Deflation"])
    risk_budget = REGIME_RISK_BUDGET.get(regime_name, 0.5)
    sectors = REGIME_SECTORS.get(regime_name, [])
    styles = REGIME_STYLES.get(regime_name, [])

    # 低置信度时收紧风险预算
    if confidence < 0.3:
        risk_budget *= 0.8

    category_labels = {
        "equity": "权益类",
        "bond": "债券类",
        "commodity": "商品类",
        "cash": "现金类",
    }

    return {
        "weight_ranges": [
            {
                "category": cat,
                "lower": lo,
                "upper": hi,
                "label": category_labels.get(cat, cat),
            }
            for cat, (lo, hi) in ranges.items()
        ],
        "risk_budget": risk_budget,
        "sectors": sectors,
        "styles": styles,
        "reasoning": _build_regime_reasoning(regime_name, confidence),
    }


def determine_watch_indicators(
    regime: RegimeType,
    direction: str,
    transition_target: str | None,
) -> list[dict]:
    """
    确定当前应关注的指标

    基于 regime 和移动方向，返回用户应该重点关注的下一次可能触发转折的指标。
    """
    indicators = []

    # 始终关注 PMI
    indicators.append({
        "code": "PMI",
        "name": "制造业PMI",
        "threshold": "跌破50 → 收缩；站上50 → 扩张",
        "significance": "high",
    })

    # 始终关注 CPI
    indicators.append({
        "code": "CPI",
        "name": "居民消费价格指数",
        "threshold": "> 2% → 高通胀；< 0 → 通缩",
        "significance": "high",
    })

    # 根据转折方向增加具体指标
    if transition_target == "Stagflation" or regime == RegimeType.OVERHEAT:
        indicators.append({
            "code": "CN_NHCI",
            "name": "南华商品指数",
            "threshold": "持续上涨 → 通胀压力加大",
            "significance": "medium",
        })

    if transition_target in ("Deflation", "Recovery") or direction == "transitioning":
        indicators.append({
            "code": "CN_TERM_SPREAD_10Y2Y",
            "name": "国债利差(10Y-2Y)",
            "threshold": "倒挂 → 衰退预警；走扩 → 增长预期改善",
            "significance": "high",
        })

    if transition_target == "Recovery" or regime == RegimeType.DEFLATION:
        indicators.append({
            "code": "CN_NEW_CREDIT",
            "name": "新增信贷",
            "threshold": "同比增速回升 → 经济见底信号",
            "significance": "medium",
        })

    return indicators


def _build_regime_reasoning(regime_name: str, confidence: float) -> str:
    """生成 regime 配置逻辑说明"""
    reasons = {
        "Recovery": "经济复苏期，增长改善+通胀受控，权益类资产受益最大。建议超配权益、标配债券、低配商品。",
        "Overheat": "经济过热期，增长强劲但通胀上升，商品类资产受益。建议超配商品、标配权益、低配债券。",
        "Stagflation": "滞胀期，增长放缓+通胀高企，防御为主。建议超配现金和债券、低配权益。",
        "Deflation": "通缩期，增长和通胀双弱，债券类资产受益。建议超配债券、标配现金、低配权益和商品。",
    }
    base = reasons.get(regime_name, "环境不确定，建议均衡配置。")
    if confidence < 0.3:
        base += " 当前置信度较低，建议降低整体仓位。"
    return base
```

### 1A.3 新增 Action Mapper

**文件**: `apps/regime/domain/action_mapper.py`（新建）

```python
"""
Regime Action Mapper - 将 Regime 导航仪 + Pulse 脉搏转化为可执行的行动建议。

纯 Domain 层逻辑，不依赖 Django 或外部库。
"""

from dataclasses import dataclass, field
from datetime import date


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
) -> RegimeActionRecommendation:
    """
    将 Regime 权重区间 + Pulse 综合分数 → 具体资产配置

    核心逻辑：
    - Pulse score > 0.3 → 取权重区间上限（进攻）
    - Pulse score < -0.3 → 取权重区间下限（防御）
    - 否则 → 线性插值

    Args:
        regime_name: Regime 名称
        weight_ranges: [{"category": "equity", "lower": 0.5, "upper": 0.7}, ...]
        risk_budget: 总仓位上限
        sectors: 推荐板块
        styles: 推荐风格
        reasoning: regime 层面的配置逻辑说明
        pulse_composite_score: Pulse 综合分数 (-1 to +1)
        pulse_regime_strength: Pulse 判定的 regime 内强弱
        confidence: 综合置信度
        as_of_date: 生成日期
    """
    # 将 pulse score 从 [-1, 1] 映射到 [0, 1] 作为插值系数
    # score=1 → ratio=1 (取上限)，score=-1 → ratio=0 (取下限)
    interpolation_ratio = (pulse_composite_score + 1.0) / 2.0
    interpolation_ratio = max(0.0, min(1.0, interpolation_ratio))

    asset_weights = {}
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
        adjusted_risk_budget *= 0.85
    elif pulse_regime_strength == "strong":
        adjusted_risk_budget = min(adjusted_risk_budget * 1.05, 0.95)

    # 单一持仓上限
    position_limit = 0.10 if risk_budget >= 0.7 else 0.08

    # 对冲建议
    hedge_rec = None
    if regime_name == "Stagflation":
        hedge_rec = "建议持有商品多头对冲通胀风险"
    elif regime_name == "Deflation" and pulse_regime_strength == "weak":
        hedge_rec = "可考虑增加国债久期对冲下行风险"

    # 可解释性
    regime_str = f"{regime_name}期"
    eq_range = next((wr for wr in weight_ranges if wr["category"] == "equity"), None)
    regime_contrib = f"{regime_str}，权益区间 {eq_range['lower']*100:.0f}-{eq_range['upper']*100:.0f}%" if eq_range else regime_str
    pulse_contrib = f"脉搏{pulse_regime_strength}(score={pulse_composite_score:.2f})，插值系数{interpolation_ratio:.2f}"

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
```

### 1A.4 新增 Application 层用例

**文件**: `apps/regime/application/use_cases.py`（追加两个用例）

```python
class BuildRegimeNavigatorUseCase:
    """
    构建 Regime 导航仪完整输出

    编排流程:
    1. 调用 CalculateRegimeV2UseCase 获取基础 regime 判定
    2. 调用 assess_regime_movement() 判定移动方向
    3. 调用 map_regime_to_asset_guidance() 生成资产指引
    4. 调用 determine_watch_indicators() 确定关注指标
    5. 组合为 RegimeNavigatorOutput
    """

    def __init__(self, macro_repo):
        self.macro_repo = macro_repo

    def execute(self, as_of_date: date) -> RegimeNavigatorOutput | None:
        # ... 详见实现


class GetActionRecommendationUseCase:
    """
    获取联合行动建议

    编排流程:
    1. 调用 BuildRegimeNavigatorUseCase 获取导航仪输出
    2. 调用 GetLatestPulseUseCase（从 pulse 模块）获取最新脉搏
    3. 调用 map_regime_pulse_to_action() 计算具体配置
    4. 返回 RegimeActionRecommendation
    """

    def __init__(self, macro_repo, pulse_provider=None):
        self.macro_repo = macro_repo
        self.pulse_provider = pulse_provider

    def execute(self, as_of_date: date) -> RegimeActionRecommendation | None:
        # ... 详见实现
```

### 1A.5 新增 API 端点

**文件**: `apps/regime/interface/api_views.py`（追加）

```python
# GET /api/regime/navigator/
class RegimeNavigatorView(APIView):
    """Regime 导航仪完整输出"""

    def get(self, request):
        # 返回: regime + movement + asset_guidance + watch_indicators


# GET /api/regime/action/
class RegimeActionView(APIView):
    """Regime + Pulse 联合行动建议"""

    def get(self, request):
        # 返回: asset_weights + risk_budget + sectors + reasoning
```

**文件**: `apps/regime/interface/api_urls.py`（追加路由）

```python
path('navigator/', RegimeNavigatorView.as_view(), name='regime-navigator'),
path('action/', RegimeActionView.as_view(), name='regime-action'),
```

### 1A.6 测试要求

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/unit/test_regime_movement.py` | `assess_regime_movement()` 所有 regime×trend 组合 |
| `tests/unit/test_regime_asset_mapping.py` | `map_regime_to_asset_guidance()` 4个象限映射正确 |
| `tests/unit/test_regime_action_mapper.py` | `map_regime_pulse_to_action()` 插值逻辑、归一化、边界值 |
| `tests/unit/test_regime_watch_indicators.py` | `determine_watch_indicators()` 不同转折方向返回正确指标 |
| `tests/api/test_regime_navigator_api.py` | `/api/regime/navigator/` 契约测试 |
| `tests/api/test_regime_action_api.py` | `/api/regime/action/` 契约测试 |

---

## 1B. Pulse 模块创建（Week 2-3）

### 1B.1 模块结构

```
apps/pulse/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── entities.py       # PulseIndicatorReading, PulseSnapshot, PulseConfig
│   ├── services.py       # calculate_pulse(), assess_regime_strength(), detect_transition_warning()
│   └── protocols.py      # PulseDataProviderProtocol
├── application/
│   ├── __init__.py
│   ├── use_cases.py      # CalculatePulseUseCase, GetLatestPulseUseCase
│   └── tasks.py          # calculate_weekly_pulse Celery task
├── infrastructure/
│   ├── __init__.py
│   ├── models.py         # PulseLog ORM
│   ├── repositories.py   # PulseRepository
│   └── data_provider.py  # DjangoPulseDataProvider (wraps MacroDataProviderProtocol)
├── interface/
│   ├── __init__.py
│   ├── api_views.py      # DRF API views
│   ├── api_urls.py       # /api/pulse/*
│   └── admin.py          # Admin 注册
└── apps.py               # Django AppConfig
```

### 1B.2 Domain 层实体

**文件**: `apps/pulse/domain/entities.py`

```python
"""Pulse Module Domain Entities — 纯 Python，不依赖外部库。"""

from dataclasses import dataclass, field
from datetime import date


class PulseDimension:
    """脉搏维度常量"""
    GROWTH = "growth"
    INFLATION = "inflation"
    LIQUIDITY = "liquidity"
    SENTIMENT = "sentiment"


@dataclass(frozen=True)
class PulseIndicatorReading:
    """单个脉搏指标的读数"""
    code: str                    # 指标代码，如 'CN_TERM_SPREAD_10Y2Y'
    name: str                    # 人类可读名称，如 '国债利差(10Y-2Y)'
    dimension: str               # 所属维度：growth/inflation/liquidity/sentiment
    value: float                 # 当前值
    z_score: float               # 相对历史的 z-score
    direction: str               # 'improving', 'deteriorating', 'stable'
    signal: str                  # 'bullish', 'bearish', 'neutral'
    signal_score: float          # -1 to +1
    weight: float                # 维度内权重（Phase 1 等权 = 1.0）
    data_age_days: int           # 数据距今天数
    is_stale: bool               # 数据是否过期


@dataclass(frozen=True)
class DimensionScore:
    """单个维度的汇总分数"""
    dimension: str               # growth/inflation/liquidity/sentiment
    score: float                 # -1 to +1
    signal: str                  # 'bullish', 'bearish', 'neutral'
    indicator_count: int         # 该维度有效指标数
    description: str             # "增长脉搏偏弱" 等


@dataclass(frozen=True)
class PulseSnapshot:
    """Pulse 脉搏快照 — Pulse 模块的核心输出"""
    observed_at: date
    regime_context: str          # 当前 regime 名称

    # 4 维度分数
    dimension_scores: list[DimensionScore]

    # 综合评估
    composite_score: float       # -1 to +1
    regime_strength: str         # 'strong', 'moderate', 'weak'

    # 转折预警
    transition_warning: bool
    transition_direction: str | None  # 预警的转折方向
    transition_reasons: list[str]

    # 明细
    indicator_readings: list[PulseIndicatorReading]

    # 元数据
    data_source: str = "calculated"  # calculated, stale, degraded
    stale_indicator_count: int = 0

    @property
    def is_reliable(self) -> bool:
        """数据是否可靠（非过期非降级）"""
        return self.data_source == "calculated" and self.stale_indicator_count == 0

    @property
    def dimension_dict(self) -> dict[str, float]:
        """维度分数字典"""
        return {ds.dimension: ds.score for ds in self.dimension_scores}


@dataclass(frozen=True)
class PulseConfig:
    """Pulse 配置"""
    # Z-score 阈值
    bullish_z_threshold: float = 1.0
    bearish_z_threshold: float = -1.0

    # 方向判定阈值
    direction_change_threshold: float = 0.1

    # 数据过期天数
    daily_stale_days: int = 7
    monthly_stale_days: int = 45

    # 维度权重（Phase 1 等权）
    dimension_weights: dict[str, float] = field(default_factory=lambda: {
        "growth": 0.25,
        "inflation": 0.25,
        "liquidity": 0.25,
        "sentiment": 0.25,
    })

    # 转折预警阈值
    transition_warning_threshold: float = -0.3

    @classmethod
    def defaults(cls) -> "PulseConfig":
        return cls()
```

### 1B.3 Domain 层服务

**文件**: `apps/pulse/domain/services.py`

```python
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
    reasons = []
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
```

### 1B.4 Infrastructure 层

**文件**: `apps/pulse/infrastructure/models.py`

```python
from django.db import models


class PulseLog(models.Model):
    """Pulse 脉搏快照日志"""

    observed_at = models.DateField(db_index=True)
    regime_context = models.CharField("当时的 Regime", max_length=20)

    # 4 维度分数
    growth_score = models.FloatField("增长脉搏", default=0.0)
    inflation_score = models.FloatField("通胀脉搏", default=0.0)
    liquidity_score = models.FloatField("流动性脉搏", default=0.0)
    sentiment_score = models.FloatField("情绪脉搏", default=0.0)

    # 综合
    composite_score = models.FloatField("综合分数")
    regime_strength = models.CharField("Regime 内强弱", max_length=20)

    # 转折预警
    transition_warning = models.BooleanField("转折预警", default=False)
    transition_direction = models.CharField("预警方向", max_length=20, blank=True, null=True)

    # 明细 (JSON)
    indicator_readings = models.JSONField("指标明细", default=dict)
    transition_reasons = models.JSONField("预警原因", default=list)

    # 元数据
    data_source = models.CharField(max_length=20, default="calculated")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pulse_log"
        ordering = ["-observed_at"]
        get_latest_by = "observed_at"

    def __str__(self):
        return f"{self.observed_at}: {self.regime_strength} ({self.composite_score:.2f})"
```

### 1B.5 Application 层

**文件**: `apps/pulse/application/use_cases.py`

```python
class CalculatePulseUseCase:
    """
    计算当前 Pulse 脉搏

    编排流程：
    1. 通过 PulseDataProviderProtocol 获取各指标最新数据
    2. 获取当前 regime 上下文
    3. 对每个指标计算 signal_score
    4. 调用 domain services 计算 PulseSnapshot
    5. 持久化到 PulseLog
    """

class GetLatestPulseUseCase:
    """获取最新的 Pulse 脉搏快照（从数据库读取）"""
```

**文件**: `apps/pulse/application/tasks.py`

```python
@shared_task(name="pulse.calculate_weekly")
def calculate_weekly_pulse():
    """每周五收盘后计算 Pulse 脉搏，Celery Beat 调度。"""
```

### 1B.6 Interface 层

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/pulse/current/` | GET | 获取最新 Pulse 快照 |
| `/api/pulse/history/` | GET | 获取历史 Pulse（支持 ?months=N） |
| `/api/pulse/calculate/` | POST | 手动触发 Pulse 计算（staff only） |

### 1B.7 指标信号计算规则（Phase 1）

Pulse 的 `data_provider.py` 从 macro 数据库读取指标，然后按以下规则转化为 signal_score：

| 指标 | signal_score 计算 | 数据来源 |
|------|------------------|---------|
| `CN_TERM_SPREAD_10Y2Y` | spread > 100BP → +1; < 0 → -1; 线性插值 | macro.high_frequency_fetchers |
| `CN_NEW_CREDIT` | 同比变化率 > 10% → +0.8; < 0% → -0.8 | macro.financial_fetchers |
| `CN_NHCI` | 4周涨幅 > 5% → +0.8; 跌幅 > 5% → -0.8 | macro.high_frequency_fetchers |
| `CN_SHIBOR` | z_score < -1 → +0.8 (宽松); > 1 → -0.8 (紧缩) | macro.financial_fetchers |
| `CN_CREDIT_SPREAD` | 收窄趋势 → +0.6; 走扩趋势 → -0.6 | macro.high_frequency_fetchers |
| `CN_M2` | 增速加快 → +0.6; 减速 → -0.6 | macro.base_fetchers |
| `VIX_INDEX` | < 20 → +0.7; > 30 → -0.8 | macro.high_frequency_fetchers |
| `USD_INDEX` | 走弱趋势 → +0.5; 走强趋势 → -0.5 | macro.high_frequency_fetchers |

### 1B.8 测试要求

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/unit/test_pulse_entities.py` | 实体创建、冻结性、属性计算 |
| `tests/unit/test_pulse_services.py` | calculate_pulse() 全路径、边界值、空数据降级 |
| `tests/unit/test_pulse_dimension.py` | 4维度分别计算、等权聚合、过期指标排除 |
| `tests/unit/test_pulse_transition.py` | 转折预警逻辑，4个regime×多种维度组合 |
| `tests/api/test_pulse_api.py` | /api/pulse/current/ 和 /api/pulse/history/ 契约测试 |

---

## 1C. Dashboard 改造 — 日常模式（Week 4-5）

### 1C.1 页面结构重构

当前 dashboard（`core/templates/dashboard/index.html`）三栏布局保留，但内容重组：

```
┌─────────────────────────────────────────────────────────────┐
│  [Regime 状态栏] 复苏期 ▸ 置信度 46% │ Pulse: 偏弱 │ 风险预算 72% │
├──────────┬──────────────────────────────┬───────────────────┤
│ 侧栏     │ 主内容区                      │ 右栏              │
│ (导航)   │                               │ (辅助信息)        │
│          │ ┌────────────────────────┐    │                   │
│ 宏观环境  │ │ 今日关注               │    │ Pulse 四维仪表盘  │
│ 投资决策  │ │ • 2 条信号待审批       │    │ ┌──────┐┌──────┐ │
│ 资产分析  │ │ • Pulse 流动性转弱预警 │    │ │增长  ││通胀  │ │
│ 执行账户  │ │ • 持仓 XX 触及止损     │    │ │ 0.3  ││-0.1  │ │
│ 系统设置  │ └────────────────────────┘    │ └──────┘└──────┘ │
│          │                               │ ┌──────┐┌──────┐ │
│ ──────── │ ┌────────────────────────┐    │ │流动性││情绪  │ │
│ [发起新  │ │ 行动建议               │    │ │-0.4  ││ 0.2  │ │
│  决策]   │ │ 权益55% 债券30% 现金15%│    │ └──────┘└──────┘ │
│          │ │ "复苏偏弱，降低进攻性" │    │                   │
│          │ └────────────────────────┘    │ 关注指标          │
│          │                               │ • PMI (高)        │
│          │ ┌────────────────────────┐    │ • 利差 (高)       │
│          │ │ 持仓概览 / 信号列表    │    │ • NHCI (中)       │
│          │ └────────────────────────┘    │                   │
└──────────┴──────────────────────────────┴───────────────────┘
```

### 1C.2 新增模板组件

| 组件文件 | 用途 | HTMX 数据源 |
|---------|------|-------------|
| `core/templates/components/regime_status_bar.html` | 顶部 Regime 状态条 | `GET /api/dashboard/regime-status/` |
| `core/templates/components/pulse_card.html` | Pulse 四维仪表盘 | `GET /api/dashboard/pulse-card/` |
| `core/templates/components/attention_items.html` | 今日关注卡片 | `GET /api/dashboard/attention-items/` |
| `core/templates/components/action_recommendation.html` | 行动建议卡片 | `GET /api/dashboard/action-recommendation/` |

### 1C.3 Regime 状态栏设计

```html
<!-- regime_status_bar.html -->
<!-- 始终固定在页面顶部，regime 感知背景色 -->
<div class="regime-status-bar regime-bg-{{ regime_name|lower }}"
     hx-get="/api/dashboard/regime-status/"
     hx-trigger="every 300s"
     hx-swap="innerHTML">
    <span class="regime-badge">{{ regime_name_cn }}</span>
    <span class="regime-direction">
        {% if is_transitioning %}▸ 转向 {{ transition_target }}{% else %}● 稳定{% endif %}
    </span>
    <span class="regime-confidence">置信度 {{ confidence_pct }}%</span>
    <span class="divider">│</span>
    <span class="pulse-badge pulse-{{ regime_strength }}">脉搏: {{ regime_strength_cn }}</span>
    <span class="divider">│</span>
    <span class="risk-budget">风险预算 {{ risk_budget_pct }}%</span>
</div>
```

### 1C.4 CSS 新增

**文件**: `core/static/css/home.css`（追加）

```css
/* Regime 感知背景色 */
.regime-bg-recovery { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); }
.regime-bg-overheat { background: linear-gradient(135deg, #fff7ed 0%, #fed7aa 100%); }
.regime-bg-stagflation { background: linear-gradient(135deg, #fef2f2 0%, #fecaca 100%); }
.regime-bg-deflation { background: linear-gradient(135deg, #eff6ff 0%, #bfdbfe 100%); }

/* Pulse 强弱指示 */
.pulse-strong { color: var(--color-success); }
.pulse-moderate { color: var(--color-warning); }
.pulse-weak { color: var(--color-danger); }
```

### 1C.5 导航栏重组

**文件**: `core/templates/base.html`

将当前平铺的菜单按 §4.4 的分类表重组。主要改动：
- 顶部保留：系统首页、决策工作台
- 下拉菜单：宏观环境、投资决策、资产分析、执行与账户
- 右侧：系统设置(gear icon)
- 新增：侧栏底部"发起新决策"按钮

---

## 1D. 测试与集成验证（Week 5-6）

### 1D.1 Domain 层单元测试

```bash
pytest tests/unit/test_regime_movement.py -v
pytest tests/unit/test_regime_asset_mapping.py -v
pytest tests/unit/test_regime_action_mapper.py -v
pytest tests/unit/test_pulse_services.py -v
pytest tests/unit/test_pulse_transition.py -v
```

### 1D.2 API 契约测试

```bash
pytest tests/api/test_regime_navigator_api.py -v
pytest tests/api/test_regime_action_api.py -v
pytest tests/api/test_pulse_api.py -v
```

### 1D.3 端到端集成测试

```bash
# 完整链路: macro 数据 → pulse 计算 → regime 导航 → action 建议
pytest tests/integration/test_regime_pulse_chain.py -v
```

### 1D.4 手动验证

```bash
python manage.py runserver
# 访问 http://localhost:8000/dashboard/
# 确认：Regime 状态栏、Pulse 卡片、今日关注、行动建议 正常显示
```

---

## 交付物清单

| 交付物 | 类型 | 状态 |
|--------|------|------|
| `apps/regime/domain/entities.py` 新增实体 | 代码修改 | 待实施 |
| `apps/regime/domain/services_v2.py` 新增导航服务 | 代码修改 | 待实施 |
| `apps/regime/domain/action_mapper.py` | 新建文件 | 待实施 |
| `apps/regime/application/use_cases.py` 新增用例 | 代码修改 | 待实施 |
| `apps/regime/interface/api_views.py` 新增端点 | 代码修改 | 待实施 |
| `apps/pulse/` 完整四层架构 | 新建模块 | 待实施 |
| `core/templates/components/regime_status_bar.html` | 新建文件 | 待实施 |
| `core/templates/components/pulse_card.html` | 新建文件 | 待实施 |
| `core/templates/components/attention_items.html` | 新建文件 | 待实施 |
| `core/templates/components/action_recommendation.html` | 新建文件 | 待实施 |
| `core/templates/dashboard/index.html` 重构 | 代码修改 | 待实施 |
| `core/templates/base.html` 导航重组 | 代码修改 | 待实施 |
| 单元测试 (≥90% domain 覆盖) | 测试 | 待实施 |
| API 契约测试 | 测试 | 待实施 |
| 数据库迁移 (PulseLog) | 迁移 | 待实施 |
