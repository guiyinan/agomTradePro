"""Level-based Regime V2 calculation use case."""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError

from core.exceptions import BusinessLogicError, DataFetchError, InsufficientDataError

from ..domain.services_v2 import RegimeCalculationResult, ThresholdConfig
from .repository_provider import MacroRepositoryAdapterProtocol

logger = logging.getLogger(__name__)

RECOVERABLE_REGIME_USE_CASE_EXCEPTIONS = (
    ArithmeticError,
    AttributeError,
    BusinessLogicError,
    ConnectionError,
    DataFetchError,
    DatabaseError,
    ImportError,
    ImproperlyConfigured,
    InsufficientDataError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


# ==================== V2 Use Case (Level-based) ====================


@dataclass
class CalculateRegimeV2Request:
    """计算 Regime V2 的请求 DTO"""

    as_of_date: date
    use_pit: bool = False
    growth_indicator: str = "PMI"
    inflation_indicator: str = "CPI"
    data_source: str | None = None
    skip_cache: bool = False
    published_only: bool = False


@dataclass
class CalculateRegimeV2Response:
    """计算 Regime V2 的响应 DTO"""

    success: bool
    result: Optional["RegimeCalculationResult"]
    warnings: list[str]
    error: str | None = None
    raw_data: dict[str, Any] | None = None


class CalculateRegimeV2UseCase:
    """
    计算 Regime V2 的用例（基于绝对水平）

    职责：
    1. 使用 V2 服务（水平判定法）计算 Regime
    2. 从数据库读取阈值配置
    3. 返回包含趋势预测的结果
    """

    MIN_DATA_POINTS = 3  # V2 只需要最近的数据

    def __init__(self, repository: MacroRepositoryAdapterProtocol) -> None:
        self.repository = repository

    def _load_threshold_config(self) -> "ThresholdConfig":
        """从数据库加载阈值配置"""
        from ..domain.services_v2 import ThresholdConfig

        try:
            from .repository_provider import get_regime_repository

            values = get_regime_repository().get_active_threshold_config_values()
            if values:

                return ThresholdConfig(
                    pmi_expansion=values["pmi_expansion"],
                    pmi_contraction=values["pmi_contraction"],
                    cpi_high=values["cpi_high"],
                    cpi_low=values["cpi_low"],
                    cpi_deflation=values["cpi_deflation"],
                    momentum_weight=values["momentum_weight"],
                )
        except RECOVERABLE_REGIME_USE_CASE_EXCEPTIONS as e:
            logger.warning(f"Failed to load threshold config from database: {e}, using defaults")

        # 返回默认配置
        return ThresholdConfig()

    def execute(self, request: CalculateRegimeV2Request) -> CalculateRegimeV2Response:
        """执行 Regime V2 计算"""
        warnings_list: list[str] = []

        try:
            from ..domain.services_v2 import RegimeCalculatorV2

            # 转换指标代码
            self.repository.GROWTH_INDICATORS.get(
                request.growth_indicator, request.growth_indicator
            )
            self.repository.INFLATION_INDICATORS.get(
                request.inflation_indicator, request.inflation_indicator
            )

            # 获取数据序列（只需要最近的数据）
            growth_series = self.repository.get_growth_series(
                indicator_code=request.growth_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source,
                published_only=request.published_only,
            )

            inflation_series = self.repository.get_inflation_series(
                indicator_code=request.inflation_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source,
                published_only=request.published_only,
            )

            if not growth_series or not inflation_series:
                return CalculateRegimeV2Response(
                    success=False, result=None, warnings=[], error="数据不足：需要 PMI 和 CPI 数据"
                )

            # 加载阈值配置
            config = self._load_threshold_config()

            # 使用 V2 计算器
            calculator = RegimeCalculatorV2(config=config)
            result = calculator.calculate(
                pmi_series=growth_series, cpi_series=inflation_series, as_of_date=request.as_of_date
            )

            # 获取完整数据用于展示
            growth_full = self.repository.get_growth_series_full(
                indicator_code=request.growth_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source,
                published_only=request.published_only,
            )
            inflation_full = self.repository.get_inflation_series_full(
                indicator_code=request.inflation_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source,
                published_only=request.published_only,
            )

            raw_data = {
                "growth": [
                    {"date": ind.reporting_period.isoformat(), "value": ind.value, "code": ind.code}
                    for ind in growth_full
                ],
                "inflation": [
                    {"date": ind.reporting_period.isoformat(), "value": ind.value, "code": ind.code}
                    for ind in inflation_full
                ],
            }

            return CalculateRegimeV2Response(
                success=True,
                result=result,
                warnings=result.warnings + warnings_list,
                error=None,
                raw_data=raw_data,
            )

        except RECOVERABLE_REGIME_USE_CASE_EXCEPTIONS as e:
            logger.exception(f"Unexpected error during regime V2 calculation: {e}")
            return CalculateRegimeV2Response(
                success=False, result=None, warnings=warnings_list, error=f"计算失败: {str(e)}"
            )
