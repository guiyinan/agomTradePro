"""
Pulse 数据提供者 — 从 macro 模块已入库的数据中读取指标。

指标定义和信号阈值从 PulseIndicatorConfig 模型加载，
若数据库中无配置则使用 Domain 层默认值。
"""

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apps.data_center.application.public import (
    get_latest_quote_payloads,
    get_macro_fact_series,
    get_macro_indicator_catalog,
    get_price_bar_series,
    is_direct_macro_input_allowed,
)
from apps.pulse.domain.entities import PulseConfig, PulseIndicatorReading
from shared.date_utils import business_day_age
from shared.infrastructure.decision_safe_series_registry import get_sentiment_series_loader
from shared.numeric import safe_float

logger = logging.getLogger(__name__)
CN_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


# ==================== Domain 层默认指标配置 ====================


@dataclass
class PulseIndicatorDef:
    """单个 Pulse 指标的完整定义"""

    code: str
    name: str
    dimension: str  # growth / inflation / liquidity / sentiment
    frequency: str  # daily / monthly
    weight: float = 1.0  # 维度内权重

    # 信号阈值配置
    signal_type: str = "zscore"  # zscore / level / pct_change
    bullish_threshold: float = 1.0
    bearish_threshold: float = -1.0
    neutral_band: float = 0.5  # |z| < neutral_band → neutral
    signal_multiplier: float = 0.4  # z_score → signal_score 的乘数


@dataclass(frozen=True)
class PulseSeriesPoint:
    """One normalized source observation used by the Pulse calculator."""

    observed_at: date
    value: float
    published_at: date | None
    source_kind: str


@dataclass(frozen=True)
class PulseMacroFactCandidate:
    """Detached macro fact used by canonical source-selection rules."""

    indicator_code: str
    reporting_period: date
    value: float
    source: str
    revision_number: int
    published_at: date | None
    fetched_at: datetime
    extra: Mapping[str, object]


# Domain 层默认指标列表（用于 DB 无配置时 fallback）
DEFAULT_PULSE_INDICATORS: list[PulseIndicatorDef] = [
    PulseIndicatorDef(
        code="CN_PMI",
        name="制造业PMI",
        dimension="growth",
        frequency="monthly",
        signal_type="level",
        bullish_threshold=50.0,
        bearish_threshold=49.0,
    ),
    PulseIndicatorDef(
        code="CN_NEW_CREDIT",
        name="新增信贷",
        dimension="growth",
        frequency="monthly",
        signal_type="level",
        bullish_threshold=3.0e12,
        bearish_threshold=1.0e12,
    ),
    PulseIndicatorDef(
        code="CN_CPI_NATIONAL_YOY",
        name="全国CPI同比",
        dimension="inflation",
        frequency="monthly",
        signal_type="level",
        bullish_threshold=2.0,
        bearish_threshold=0.0,
    ),
    PulseIndicatorDef(
        code="CN_SHIBOR",
        name="SHIBOR",
        dimension="liquidity",
        frequency="daily",
        signal_type="zscore",
        bullish_threshold=-1.0,  # 宽松 → bullish
        bearish_threshold=1.0,  # 紧缩 → bearish
        signal_multiplier=-0.4,  # 负号：z 高=利率高=bearish
    ),
    PulseIndicatorDef(
        code="CN_LPR",
        name="LPR",
        dimension="liquidity",
        frequency="monthly",
        signal_type="zscore",
        bullish_threshold=-0.3,
        bearish_threshold=0.3,
        signal_multiplier=-0.25,
    ),
    PulseIndicatorDef(
        code="CN_M2_YOY",
        name="M2增速",
        dimension="liquidity",
        frequency="monthly",
        signal_type="level",
        bullish_threshold=8.0,
        bearish_threshold=6.0,
    ),
    PulseIndicatorDef(
        code="000300.SH",
        name="沪深300",
        dimension="sentiment",
        frequency="daily",
        signal_type="pct_change",
        bullish_threshold=3.0,
        bearish_threshold=-3.0,
        signal_multiplier=0.1,
    ),
    PulseIndicatorDef(
        code="CN_A_TOTAL_TURNOVER",
        name="A股全市场成交额",
        dimension="sentiment",
        frequency="daily",
        signal_type="pct_change",
        bullish_threshold=20.0,
        bearish_threshold=-20.0,
        signal_multiplier=0.025,
    ),
    PulseIndicatorDef(
        code="CN_A_MARGIN_BALANCE",
        name="A股融资余额",
        dimension="sentiment",
        frequency="daily",
        signal_type="pct_change",
        bullish_threshold=3.0,
        bearish_threshold=-3.0,
        signal_multiplier=0.1,
    ),
    PulseIndicatorDef(
        code="CN_A_MARKET_NEWS_SENTIMENT",
        name="A股市场新闻情绪均值",
        dimension="sentiment",
        frequency="daily",
        signal_type="level",
        bullish_threshold=0.2,
        bearish_threshold=-0.2,
        signal_multiplier=1.0,
    ),
    PulseIndicatorDef(
        code="CN_A_ETF_NET_FLOW",
        name="A股ETF资金净流入",
        dimension="sentiment",
        frequency="daily",
        signal_type="zscore",
        bullish_threshold=1.0,
        bearish_threshold=-1.0,
        signal_multiplier=0.4,
    ),
    PulseIndicatorDef(
        code="SENTIMENT_DAILY_INDEX",
        name="文本情绪指数",
        dimension="sentiment",
        frequency="daily",
        signal_type="level",
        bullish_threshold=0.3,
        bearish_threshold=-0.3,
        neutral_band=0.1,
        signal_multiplier=1.0,
    ),
    PulseIndicatorDef(
        code="CN_A_ADVANCE_COUNT",
        name="A股上涨家数",
        dimension="sentiment",
        frequency="daily",
        signal_type="zscore",
        bullish_threshold=1.0,
        bearish_threshold=-1.0,
        signal_multiplier=0.4,
    ),
    PulseIndicatorDef(
        code="CN_A_DECLINE_COUNT",
        name="A股下跌家数",
        dimension="sentiment",
        frequency="daily",
        signal_type="zscore",
        bullish_threshold=1.0,
        bearish_threshold=-1.0,
        signal_multiplier=-0.4,
    ),
    PulseIndicatorDef(
        code="CN_A_LIMIT_UP_COUNT",
        name="A股涨停家数",
        dimension="sentiment",
        frequency="daily",
        signal_type="zscore",
        bullish_threshold=1.0,
        bearish_threshold=-1.0,
        signal_multiplier=0.4,
    ),
    PulseIndicatorDef(
        code="CN_A_LIMIT_DOWN_COUNT",
        name="A股跌停家数",
        dimension="sentiment",
        frequency="daily",
        signal_type="zscore",
        bullish_threshold=1.0,
        bearish_threshold=-1.0,
        signal_multiplier=-0.4,
    ),
]


class DjangoPulseDataProvider:
    """
    从 Django ORM (macro 模块) 读取高频数据并转换为 PulseIndicatorReading。

    指标定义优先从数据库 PulseIndicatorConfig 加载，
    若无配置则使用 DEFAULT_PULSE_INDICATORS。
    """

    def __init__(self, config: PulseConfig | None = None) -> None:
        self.config = config or PulseConfig.defaults()
        self._indicator_defs: list[PulseIndicatorDef] | None = None
        self._indicator_extra_cache: dict[str, dict[str, object]] = {}

    def _load_indicator_defs(self) -> list[PulseIndicatorDef]:
        """从 DB 加载指标定义，fallback 到 Domain 默认值"""
        if self._indicator_defs is not None:
            return self._indicator_defs

        try:
            from apps.pulse.infrastructure.models import (
                PulseIndicatorConfigModel,
                PulseIndicatorWeight,
                PulseWeightConfig,
            )

            db_configs = list(PulseIndicatorConfigModel.objects.filter(is_active=True))

            # Override weights from active PulseWeightConfig
            active_weight_cfg = PulseWeightConfig.objects.filter(is_active=True).first()
            weight_overrides: dict[str, PulseIndicatorWeight] = {}
            if active_weight_cfg:
                weight_overrides = {w.indicator_code: w for w in active_weight_cfg.weights.all()}

            if db_configs:
                self._indicator_defs = []
                for c in db_configs:
                    w_model = weight_overrides.get(c.indicator_code)
                    if w_model and not w_model.is_enabled:
                        continue  # If explicitly disabled, skip
                    weight = safe_float(w_model.weight if w_model else c.weight)
                    bullish_threshold = safe_float(c.bullish_threshold)
                    bearish_threshold = safe_float(c.bearish_threshold)
                    neutral_band = safe_float(c.neutral_band)
                    signal_multiplier = safe_float(c.signal_multiplier)
                    if (
                        weight is None
                        or weight <= 0
                        or bullish_threshold is None
                        or bearish_threshold is None
                        or neutral_band is None
                        or neutral_band < 0
                        or signal_multiplier is None
                    ):
                        logger.warning(
                            "Skipping invalid Pulse indicator config: code=%s",
                            c.indicator_code,
                        )
                        continue
                    self._indicator_defs.append(
                        PulseIndicatorDef(
                            code=c.indicator_code,
                            name=c.indicator_name,
                            dimension=c.dimension,
                            frequency=c.frequency,
                            weight=weight,
                            signal_type=c.signal_type,
                            bullish_threshold=bullish_threshold,
                            bearish_threshold=bearish_threshold,
                            neutral_band=neutral_band,
                            signal_multiplier=signal_multiplier,
                        )
                    )
                logger.info(f"Loaded {len(self._indicator_defs)} pulse indicators from DB")
                return self._indicator_defs

            # 如果没有 PulseIndicatorConfigModel，可以尝试用 weight_overrides 覆盖 DEFAULT_PULSE_INDICATORS
            self._indicator_defs = []
            for default_ind in DEFAULT_PULSE_INDICATORS:
                w_model = weight_overrides.get(default_ind.code)
                if w_model and not w_model.is_enabled:
                    continue
                weight = safe_float(w_model.weight if w_model else default_ind.weight)
                if weight is None or weight <= 0:
                    logger.warning(
                        "Skipping invalid Pulse weight override: code=%s",
                        default_ind.code,
                    )
                    continue
                self._indicator_defs.append(replace(default_ind, weight=weight))

            return self._indicator_defs

        except Exception as exc:
            logger.warning(
                "Failed to load Pulse indicator configs: error_type=%s",
                exc.__class__.__name__,
            )

        self._indicator_defs = DEFAULT_PULSE_INDICATORS
        return self._indicator_defs

    def get_all_readings(self, as_of_date: date) -> list[PulseIndicatorReading]:
        """获取所有 Pulse 指标的最新读数"""
        indicator_defs = self._load_indicator_defs()
        readings: list[PulseIndicatorReading] = []
        for ind_def in indicator_defs:
            reading = self._get_indicator_reading(ind_def, as_of_date)
            if reading:
                readings.append(reading)
            else:
                logger.warning("Pulse indicator %s not available", ind_def.code)
        return readings

    def _get_indicator_reading(
        self,
        ind_def: PulseIndicatorDef,
        as_of_date: date,
    ) -> PulseIndicatorReading | None:
        """获取单个指标的读数"""
        try:
            series = self._load_data_center_series(ind_def.code, as_of_date)
            if not series:
                return None

            latest_point = series[-1]
            observed_date = latest_point.observed_at
            current_value = latest_point.value
            published_at = latest_point.published_at
            freshness_anchor = published_at or observed_date
            # 判断是否过期
            stale_days = (
                self.config.daily_stale_days
                if ind_def.frequency == "daily"
                else self.config.monthly_stale_days
            )
            data_age = (
                business_day_age(freshness_anchor, as_of_date)
                if ind_def.frequency == "daily"
                else max((as_of_date - freshness_anchor).days, 0)
            )
            is_stale = data_age > stale_days
            if (
                self._is_asset_code(ind_def.code)
                and as_of_date.weekday() < 5
                and observed_date < as_of_date
            ):
                # A weekday market-sentiment reading must not masquerade as the
                # current session merely because it is inside the generic
                # seven-day tolerance used by other daily indicators.
                is_stale = True

            history = [point.value for point in series]

            z_score = self._calculate_z_score(history, current_value)
            direction = self._determine_direction(history)
            signal, signal_score = self._calculate_signal(ind_def, current_value, z_score, history)

            return PulseIndicatorReading(
                code=ind_def.code,
                name=ind_def.name,
                dimension=ind_def.dimension,
                value=current_value,
                z_score=round(z_score, 3),
                direction=direction,
                signal=signal,
                signal_score=round(signal_score, 3),
                weight=ind_def.weight,
                data_age_days=data_age,
                is_stale=is_stale,
                observed_at=observed_date,
                source_kind=latest_point.source_kind,
            )

        except Exception as exc:
            logger.warning(
                "Error reading Pulse indicator %s: error_type=%s",
                ind_def.code,
                exc.__class__.__name__,
            )
            return None

    def _load_data_center_series(
        self,
        code: str,
        as_of_date: date,
    ) -> list[PulseSeriesPoint]:
        """Read Pulse inputs from Data Center facts before legacy macro tables."""
        lookback = as_of_date - timedelta(days=365)
        if code == "SENTIMENT_DAILY_INDEX":
            return self._load_sentiment_module_series(as_of_date)
        if self._is_asset_code(code):
            series: list[PulseSeriesPoint] = []
            rows = get_price_bar_series(code, start=lookback, end=as_of_date, limit=500)
            for row in rows:
                bar_date = date.fromisoformat(str(row["timestamp"]))
                numeric_close = safe_float(row.get("close"))
                if numeric_close is None:
                    continue
                series.append(
                    PulseSeriesPoint(
                        observed_at=bar_date,
                        value=numeric_close,
                        published_at=None,
                        source_kind="price_bar_close",
                    )
                )
            latest_quotes = get_latest_quote_payloads([code])
            if latest_quotes:
                latest_quote = latest_quotes[0]
                snapshot_value = latest_quote.get("snapshot_at")
                quote_datetime = datetime.fromisoformat(str(snapshot_value)) if snapshot_value else None
                quote_date = (
                    quote_datetime.astimezone(CN_MARKET_TIMEZONE).date()
                    if quote_datetime is not None and quote_datetime.tzinfo is not None
                    else None
                )
                latest_bar_date = series[-1].observed_at if series else None
                if quote_date is not None and quote_date <= as_of_date and (
                    latest_bar_date is None or quote_date > latest_bar_date
                ):
                    quote_value = safe_float(latest_quote.get("current_price"))
                    if quote_value is not None:
                        series.append(
                            PulseSeriesPoint(
                                observed_at=quote_date,
                                value=quote_value,
                                published_at=quote_date,
                                source_kind="quote_current_price",
                            )
                        )
            return series

        if not self._is_pulse_direct_input_allowed(code):
            logger.warning(
                "Blocked Pulse direct input for %s because catalog policy requires derivation first",
                code,
            )
            return []

        facts = get_macro_fact_series(
            code,
            start=lookback,
            end=as_of_date,
            limit=500,
            use_pit=True,
        )
        macro_series: list[PulseSeriesPoint] = []
        for fact in facts:
            numeric_value = safe_float(fact.get("value"))
            if numeric_value is None:
                continue
            observed_at = date.fromisoformat(str(fact["reporting_period"]))
            published_value = fact.get("published_at")
            published_at = date.fromisoformat(str(published_value)) if published_value else None
            macro_series.append(
                PulseSeriesPoint(
                    observed_at=observed_at,
                    value=numeric_value,
                    published_at=published_at,
                    source_kind="macro_fact",
                )
            )
        macro_series.sort(key=lambda point: point.observed_at)
        return macro_series

    @staticmethod
    def _load_sentiment_module_series(as_of_date: date) -> list[PulseSeriesPoint]:
        """Load the sentiment module index without laundering blocked observations."""

        loader = get_sentiment_series_loader()
        if loader is None:
            logger.warning("Blocked Pulse text sentiment input: sentiment loader unavailable")
            return []
        result = loader(
            as_of_date=as_of_date,
            lookback_days=365,
        )
        if result.must_not_use_for_decision:
            logger.warning(
                "Blocked Pulse text sentiment input: reason=%s observed_at=%s",
                result.blocked_reason,
                result.observed_at,
            )
            return []
        return [
            PulseSeriesPoint(
                observed_at=point.observed_at,
                value=point.value,
                published_at=point.observed_at,
                source_kind="sentiment_index",
            )
            for point in result.points
        ]

    def _get_indicator_extra(self, code: str) -> dict[str, object]:
        if code not in self._indicator_extra_cache:
            catalog = get_macro_indicator_catalog(code)
            self._indicator_extra_cache[code] = dict(catalog.get("extra") or {})
        return self._indicator_extra_cache[code]

    def _is_pulse_direct_input_allowed(self, code: str) -> bool:
        return is_direct_macro_input_allowed(
            self._get_indicator_extra(code),
            consumer="pulse",
        )

    @staticmethod
    def _is_asset_code(code: str) -> bool:
        return code.endswith((".SH", ".SZ", ".BJ"))

    def _calculate_z_score(self, series: list[float], value: float) -> float:
        """计算 z-score"""
        if len(series) < 3:
            return 0.0
        mean_val = sum(series) / len(series)
        variance = sum((x - mean_val) ** 2 for x in series) / len(series)
        std_val = math.sqrt(variance) if variance > 0 else 0
        if std_val == 0:
            return 0.0
        return (value - mean_val) / std_val

    def _determine_direction(self, series: list[float]) -> str:
        """基于最近数据判定方向"""
        if len(series) < 4:
            return "stable"
        recent = series[-4:]
        trend = recent[-1] - recent[0]
        if abs(trend) < 0.01 * (abs(recent[0]) + 1):
            return "stable"
        return "improving" if trend > 0 else "deteriorating"

    def _calculate_signal(
        self,
        ind_def: PulseIndicatorDef,
        value: float,
        z_score: float,
        history: list[float],
    ) -> tuple[str, float]:
        """
        按指标配置计算信号

        信号计算统一通过 signal_type 分发：
        - 'level': 基于绝对水平判定
        - 'pct_change': 基于近期涨跌幅判定
        - 'zscore': 基于 z-score 判定（通用）
        """
        if ind_def.signal_type == "level":
            return self._signal_by_level(ind_def, value)
        elif ind_def.signal_type == "pct_change":
            return self._signal_by_pct_change(ind_def, value, history)
        else:
            return self._signal_by_zscore(ind_def, z_score)

    def _signal_by_level(self, ind_def: PulseIndicatorDef, value: float) -> tuple[str, float]:
        """基于绝对水平的信号"""
        # 特殊处理：VIX 类逆向指标
        if ind_def.code == "VIX_INDEX":
            if value < ind_def.bullish_threshold:
                return "bullish", 0.7
            elif value > ind_def.bearish_threshold:
                return "bearish", -0.8
            mid = (ind_def.bullish_threshold + ind_def.bearish_threshold) / 2
            range_half = (ind_def.bearish_threshold - ind_def.bullish_threshold) / 2
            return "neutral", -(value - mid) / max(range_half, 1)

        # 正向指标：高于 bullish 阈值 → bullish
        if value >= ind_def.bullish_threshold:
            return "bullish", 1.0
        elif value <= ind_def.bearish_threshold:
            return "bearish", -1.0
        # 线性插值
        range_size = ind_def.bullish_threshold - ind_def.bearish_threshold
        if range_size > 0:
            return "neutral", (value - ind_def.bearish_threshold) / range_size * 2 - 1
        return "neutral", 0.0

    def _signal_by_pct_change(
        self, ind_def: PulseIndicatorDef, value: float, history: list[float]
    ) -> tuple[str, float]:
        """基于涨跌幅的信号"""
        if len(history) < 20:
            return "neutral", 0.0

        past = history[-20]
        if past == 0:
            return "neutral", 0.0

        change_pct = ((value - past) / abs(past)) * 100

        if change_pct > ind_def.bullish_threshold:
            return "bullish", 0.8
        elif change_pct < ind_def.bearish_threshold:
            return "bearish", -0.8
        return "neutral", change_pct * ind_def.signal_multiplier

    def _signal_by_zscore(self, ind_def: PulseIndicatorDef, z_score: float) -> tuple[str, float]:
        """基于 z-score 的信号（通用）"""
        # 对于 SHIBOR 等逆向指标，multiplier 为负数
        effective_z = z_score * (1 if ind_def.signal_multiplier >= 0 else -1)

        if effective_z > abs(ind_def.bullish_threshold):
            signal = "bullish"
        elif effective_z < -abs(ind_def.bearish_threshold):
            signal = "bearish"
        else:
            signal = "neutral"

        score = z_score * ind_def.signal_multiplier
        return signal, max(-1.0, min(1.0, score))
