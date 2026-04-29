"""
Pulse 数据提供者 — 从 macro 模块已入库的数据中读取指标。

指标定义和信号阈值从 PulseIndicatorConfig 模型加载，
若数据库中无配置则使用 Domain 层默认值。
"""

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta

from apps.pulse.domain.entities import PulseConfig, PulseIndicatorReading

logger = logging.getLogger(__name__)


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
        bullish_threshold=8.0e15,
        bearish_threshold=3.0e15,
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
        code="CN_M2",
        name="M2增速",
        dimension="liquidity",
        frequency="monthly",
        signal_type="zscore",
        bullish_threshold=0.5,
        bearish_threshold=-0.5,
        signal_multiplier=0.3,
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
]


class DjangoPulseDataProvider:
    """
    从 Django ORM (macro 模块) 读取高频数据并转换为 PulseIndicatorReading。

    指标定义优先从数据库 PulseIndicatorConfig 加载，
    若无配置则使用 DEFAULT_PULSE_INDICATORS。
    """

    def __init__(self, config: PulseConfig | None = None):
        self.config = config or PulseConfig.defaults()
        self._indicator_defs: list[PulseIndicatorDef] | None = None

    def _load_indicator_defs(self) -> list[PulseIndicatorDef]:
        """从 DB 加载指标定义，fallback 到 Domain 默认值"""
        if self._indicator_defs is not None:
            return self._indicator_defs

        try:
            from apps.pulse.infrastructure.models import (
                PulseIndicatorConfigModel,
                PulseWeightConfig,
            )

            db_configs = list(PulseIndicatorConfigModel.objects.filter(is_active=True))

            # Override weights from active PulseWeightConfig
            active_weight_cfg = PulseWeightConfig.objects.filter(is_active=True).first()
            weight_overrides = {}
            if active_weight_cfg:
                weight_overrides = {w.indicator_code: w for w in active_weight_cfg.weights.all()}

            if db_configs:
                self._indicator_defs = []
                for c in db_configs:
                    w_model = weight_overrides.get(c.indicator_code)
                    if w_model and not w_model.is_enabled:
                        continue  # If explicitly disabled, skip
                    weight = w_model.weight if w_model else c.weight
                    self._indicator_defs.append(
                        PulseIndicatorDef(
                            code=c.indicator_code,
                            name=c.indicator_name,
                            dimension=c.dimension,
                            frequency=c.frequency,
                            weight=weight,
                            signal_type=c.signal_type,
                            bullish_threshold=c.bullish_threshold,
                            bearish_threshold=c.bearish_threshold,
                            neutral_band=c.neutral_band,
                            signal_multiplier=c.signal_multiplier,
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
                weight = w_model.weight if w_model else default_ind.weight

                # Copy and update weight
                ind_kwargs = {
                    k: getattr(default_ind, k) for k in default_ind.__annotations__.keys()
                }
                ind_kwargs["weight"] = weight
                self._indicator_defs.append(PulseIndicatorDef(**ind_kwargs))

            return self._indicator_defs

        except Exception as e:
            logger.warning(f"Failed to load pulse indicator configs from DB: {e}")

        self._indicator_defs = DEFAULT_PULSE_INDICATORS
        return self._indicator_defs

    def get_all_readings(self, as_of_date: date) -> list[PulseIndicatorReading]:
        """获取所有 Pulse 指标的最新读数"""
        indicator_defs = self._load_indicator_defs()
        readings = []
        for ind_def in indicator_defs:
            reading = self._get_indicator_reading(ind_def, as_of_date)
            if reading:
                readings.append(reading)
            else:
                logger.warning(f"Pulse indicator {ind_def.code} not available")
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

            observed_date, current_value, published_at = series[-1]
            freshness_anchor = published_at or observed_date
            data_age = (as_of_date - freshness_anchor).days

            # 判断是否过期
            stale_days = (
                self.config.daily_stale_days
                if ind_def.frequency == "daily"
                else self.config.monthly_stale_days
            )
            is_stale = data_age > stale_days

            history = [value for _observed_at, value, _published_at in series]

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
            )

        except Exception as e:
            logger.warning(f"Error reading pulse indicator {ind_def.code}: {e}")
            return None

    def _load_data_center_series(
        self,
        code: str,
        as_of_date: date,
    ) -> list[tuple[date, float, date | None]]:
        """Read Pulse inputs from Data Center facts before legacy macro tables."""
        lookback = as_of_date - timedelta(days=365)
        if self._is_asset_code(code):
            from apps.data_center.infrastructure.models import PriceBarModel

            rows = (
                PriceBarModel.objects.filter(
                    asset_code=code,
                    bar_date__gte=lookback,
                    bar_date__lte=as_of_date,
                )
                .order_by("bar_date")
                .values_list("bar_date", "close")
            )
            return [(bar_date, float(close), None) for bar_date, close in rows]

        from apps.data_center.infrastructure.models import MacroFactModel

        rows = (
            MacroFactModel.objects.filter(
                indicator_code=code,
                reporting_period__gte=lookback,
                reporting_period__lte=as_of_date,
            )
            .order_by("reporting_period", "revision_number")
            .values_list("reporting_period", "value", "published_at")
        )
        return [
            (reporting_period, float(value), published_at)
            for reporting_period, value, published_at in rows
        ]

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
        if value > ind_def.bullish_threshold:
            return "bullish", 1.0
        elif value < ind_def.bearish_threshold:
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
