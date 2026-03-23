"""
Use Cases for Macro Data Collection.

Application layer orchestrating the workflow of syncing macro data from various sources.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from ..domain.entities import MacroIndicator
from .indicator_service import IndicatorUnitService


@dataclass
class SyncMacroDataRequest:
    """同步宏观数据的请求 DTO"""
    start_date: date
    end_date: date | None = None
    indicators: list[str] | None = None
    force_refresh: bool = False


@dataclass
class SyncMacroDataResponse:
    """同步宏观数据的响应 DTO"""
    success: bool
    synced_count: int
    skipped_count: int
    errors: list[str]


@dataclass
class MacroDataPoint:
    """宏观数据点"""
    code: str
    value: float
    observed_at: date
    published_at: date | None
    source: str
    unit: str = ""
    original_unit: str = ""  # 原始单位（数据源返回的单位）


class SyncMacroDataUseCase:
    """
    同步宏观数据的用例

    职责：
    1. 调用适配器获取数据
    2. 去重处理
    3. 批量保存到数据库
    """

    def __init__(self, repository, adapters: dict[str, object] | None = None):
        """
        Args:
            repository: MacroRepository 实例
            adapters: 数据源适配器字典 {source: adapter}
        """
        self.repository = repository
        self.adapters = adapters or {}

    def execute(self, request: SyncMacroDataRequest) -> SyncMacroDataResponse:
        """
        执行数据同步

        Args:
            request: 同步请求

        Returns:
            SyncMacroDataResponse: 同步结果
        """
        if request.end_date is None:
            end_date = date.today()
        else:
            end_date = request.end_date

        errors = []
        synced_count = 0
        skipped_count = 0

        # 如果没有指定指标，同步所有支持的指标
        indicators = request.indicators or self._get_default_indicators()

        for indicator_code in indicators:
            try:
                # 1. 调用适配器获取数据
                data_points = self._fetch_indicator_data(
                    indicator_code,
                    request.start_date,
                    end_date
                )

                if not data_points:
                    errors.append(f"无数据返回: {indicator_code}")
                    continue

                # 2. 映射 MacroDataPoint 到 Domain 实体（用于保存/去重）
                candidate_indicators = []
                for dp in data_points:
                    # 确定原始单位（优先使用适配器提供的，否则从配置获取）
                    original_unit_to_use = dp.original_unit if dp.original_unit else (
                        dp.unit if dp.unit else IndicatorUnitService.get_unit_for_indicator(dp.code)
                    )

                    # 获取标准化后的单位和值（货币类自动转换为元）
                    normalized_value, normalized_unit = IndicatorUnitService.get_normalized_unit_and_value(
                        dp.code, dp.value
                    )

                    # 存储单位：如果是货币类且成功转换，使用"元"；否则使用原始单位
                    if normalized_unit == "元":
                        unit_to_save = "元"
                        value_to_save = normalized_value
                    else:
                        unit_to_save = original_unit_to_use
                        value_to_save = dp.value

                    candidate_indicators.append(
                        MacroIndicator(
                            code=dp.code,
                            value=value_to_save,
                            reporting_period=dp.observed_at,  # MacroDataPoint.observed_at -> MacroIndicator.reporting_period
                            published_at=dp.published_at,
                            source=dp.source,
                            unit=unit_to_save,  # 存储单位（货币类为"元"）
                            original_unit=original_unit_to_use,  # 原始单位（用于展示）
                            period_type='M'  # 默认月度，可以根据指标代码优化
                        )
                    )

                # 3. 去重处理（仅跳过“完全相同”的记录；有变化则更新）
                indicators_to_save, skipped_for_indicator = self._filter_new_or_changed_indicators(
                    candidate_indicators,
                    force_refresh=request.force_refresh
                )

                if indicators_to_save:
                    self.repository.save_indicators_batch(indicators_to_save)
                    synced_count += len(indicators_to_save)

                skipped_count += skipped_for_indicator

            except Exception as e:
                errors.append(f"{indicator_code}: {str(e)}")

        return SyncMacroDataResponse(
            success=len(errors) == 0,
            synced_count=synced_count,
            skipped_count=skipped_count,
            errors=errors
        )

    def _fetch_indicator_data(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """
        获取指标数据

        Args:
            indicator_code: 指标代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 数据点列表
        """
        # 根据指标代码选择适配器
        adapter = self._get_adapter_for_indicator(indicator_code)
        if adapter is None:
            raise ValueError(f"不支持的指标: {indicator_code}")

        # 调用适配器获取数据
        # 这里需要适配器实现 fetch 方法
        if hasattr(adapter, 'fetch'):
            return adapter.fetch(indicator_code, start_date, end_date)

        return []

    def _get_adapter_for_indicator(self, indicator_code: str) -> object | None:
        """
        根据指标代码获取适配器

        Args:
            indicator_code: 指标代码

        Returns:
            Optional[object]: 适配器实例
        """
        # 简单的映射逻辑
        for source, adapter in self.adapters.items():
            if hasattr(adapter, 'supports') and adapter.supports(indicator_code):
                return adapter

        return None

    def _filter_new_or_changed_indicators(
        self,
        indicators: list[MacroIndicator],
        force_refresh: bool = False
    ) -> tuple[list[MacroIndicator], int]:
        """
        过滤需要保存的指标：
        - 不存在 -> 保存
        - 存在但内容有变化 -> 保存（走更新）
        - 存在且内容完全一致 -> 跳过
        """
        indicators_to_save: list[MacroIndicator] = []
        skipped = 0

        for indicator in indicators:
            if force_refresh:
                indicators_to_save.append(indicator)
                continue

            existing = self.repository.get_by_code_and_date(
                code=indicator.code,
                observed_at=indicator.reporting_period
            )

            if existing is None:
                indicators_to_save.append(indicator)
                continue

            if self._is_indicator_changed(existing, indicator):
                indicators_to_save.append(indicator)
            else:
                skipped += 1

        return indicators_to_save, skipped

    @staticmethod
    def _is_indicator_changed(existing: MacroIndicator, incoming: MacroIndicator) -> bool:
        """判断新指标是否相对现有记录发生变化。"""
        return (
            float(existing.value) != float(incoming.value)
            or existing.published_at != incoming.published_at
            or existing.source != incoming.source
            or existing.unit != incoming.unit
            or existing.original_unit != incoming.original_unit
            or existing.period_type != incoming.period_type
        )

    def _get_default_indicators(self) -> list[str]:
        """
        获取默认支持的指标列表

        Returns:
            List[str]: 指标代码列表
        """
        return [
            # 基础指标
            "CN_PMI",               # PMI (制造业采购经理指数)
            "CN_NON_MAN_PMI",       # 非制造业PMI
            "CN_CPI",               # CPI (居民消费价格指数)
            "CN_CPI_NATIONAL_YOY",  # 全国CPI同比
            "CN_CPI_NATIONAL_MOM",  # 全国CPI环比
            "CN_PPI",               # PPI (工业生产者出厂价格指数)
            "CN_PPI_YOY",           # PPI同比
            "CN_M2",                # M2 (货币供应量)
            "CN_VALUE_ADDED",       # 工业增加值
            "CN_RETAIL_SALES",      # 社会消费品零售总额
            "CN_GDP",               # GDP (国内生产总值)

            # 贸易数据
            "CN_EXPORTS",           # 出口同比增长
            "CN_IMPORTS",           # 进口同比增长
            "CN_TRADE_BALANCE",     # 贸易差额

            # 房产数据
            "CN_NEW_HOUSE_PRICE",   # 新房价格指数

            # 金融数据
            "CN_SHIBOR",            # SHIBOR 利率
            "CN_LPR",               # LPR (贷款市场报价利率)
            "CN_RRR",               # 存款准备金率

            # 信贷数据
            "CN_NEW_CREDIT",        # 新增信贷
            "CN_RMB_DEPOSIT",        # 人民币存款
            "CN_RMB_LOAN",          # 人民币贷款

            # 其他数据
            "CN_UNEMPLOYMENT",      # 城镇调查失业率
            "CN_FX_RESERVES",       # 外汇储备
        ]


@dataclass
class GetLatestMacroDataRequest:
    """获取最新宏观数据的请求 DTO"""
    indicator_codes: list[str]
    as_of_date: date | None = None


@dataclass
class GetLatestMacroDataResponse:
    """获取最新宏观数据的响应 DTO"""
    data: dict[str, MacroIndicator | None]
    missing: list[str]


class GetLatestMacroDataUseCase:
    """
    获取最新宏观数据的用例
    """

    def __init__(self, repository):
        """
        Args:
            repository: MacroRepository 实例
        """
        self.repository = repository

    def execute(
        self,
        request: GetLatestMacroDataRequest
    ) -> GetLatestMacroDataResponse:
        """
        执行获取最新数据

        Args:
            request: 请求

        Returns:
            GetLatestMacroDataResponse: 最新数据
        """
        data = {}
        missing = []

        for code in request.indicator_codes:
            try:
                # 获取该指标的最新可用日期
                latest_date = self.repository.get_latest_observation_date(
                    code=code,
                    as_of_date=request.as_of_date
                )

                if latest_date:
                    indicator = self.repository.get_by_code_and_date(
                        code=code,
                        observed_at=latest_date
                    )
                    data[code] = indicator
                else:
                    data[code] = None
                    missing.append(code)

            except Exception:
                data[code] = None
                missing.append(code)

        return GetLatestMacroDataResponse(
            data=data,
            missing=missing
        )
