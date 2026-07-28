"""
Use Cases for Macro Data Collection.

Application layer orchestrating the workflow of syncing macro data from various sources.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from apps.data_center.application.dtos import SyncMacroBatchRequest
from apps.data_center.application.sync_use_cases import SyncMacroBatchUseCase

from ..domain.entities import MacroIndicator, PeriodType
from .repository_provider import MacroRepositoryProtocol

logger = logging.getLogger(__name__)

_MACRO_INDICATOR_SYNC_FAILED = "macro_indicator_sync_failed"
_MACRO_OPERATION_EXCEPTIONS = (
    ArithmeticError,
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


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


class MacroDataAdapterProtocol(Protocol):
    """Adapter surface required by legacy Macro sync orchestration."""

    def supports(self, indicator_code: str) -> bool:
        """Return whether the adapter owns the requested indicator."""
        ...

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Fetch validated Macro data points for one indicator."""
        ...


class SyncMacroDataUseCase:
    """
    同步宏观数据的用例

    职责：
    1. 调用适配器获取数据
    2. 去重处理
    3. 批量保存到数据库
    """

    def __init__(
        self,
        repository: MacroRepositoryProtocol,
        adapters: Mapping[str, MacroDataAdapterProtocol] | None = None,
    ) -> None:
        """
        Args:
            repository: MacroRepository 实例
            adapters: 数据源适配器字典 {source: adapter}
        """
        self.repository = repository
        self.adapters = dict(adapters or {})

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

        errors: list[str] = []
        synced_count = 0
        skipped_count = 0

        # 如果没有指定指标，同步所有支持的指标
        indicators = request.indicators or self._get_default_indicators()

        for indicator_code in indicators:
            try:
                # 1. 调用适配器获取数据
                data_points = self._fetch_indicator_data(
                    indicator_code, request.start_date, end_date
                )

                if not data_points:
                    errors.append(f"无数据返回: {indicator_code}")
                    continue

                # 2. 映射 MacroDataPoint 到 Domain 实体（用于保存/去重）
                candidate_indicators = []
                for dp in data_points:
                    original_unit_to_use = dp.original_unit if dp.original_unit else dp.unit

                    candidate_indicators.append(
                        MacroIndicator(
                            code=dp.code,
                            value=dp.value,
                            reporting_period=dp.observed_at,  # MacroDataPoint.observed_at -> MacroIndicator.reporting_period
                            published_at=dp.published_at,
                            source=dp.source,
                            unit=original_unit_to_use,
                            original_unit=original_unit_to_use,  # 原始单位（用于展示）
                            period_type=PeriodType.MONTH,
                        )
                    )

                # 3. 去重处理（仅跳过“完全相同”的记录；有变化则更新）
                indicators_to_save, skipped_for_indicator = self._filter_new_or_changed_indicators(
                    candidate_indicators, force_refresh=request.force_refresh
                )

                if indicators_to_save:
                    self.repository.save_indicators_batch(indicators_to_save)
                    synced_count += len(indicators_to_save)

                skipped_count += skipped_for_indicator

            except _MACRO_OPERATION_EXCEPTIONS as exc:
                logger.warning(
                    "Macro indicator sync failed; indicator=%s; exception_type=%s",
                    indicator_code,
                    type(exc).__name__,
                )
                errors.append(f"{indicator_code}: {_MACRO_INDICATOR_SYNC_FAILED}")

        return SyncMacroDataResponse(
            success=len(errors) == 0,
            synced_count=synced_count,
            skipped_count=skipped_count,
            errors=errors,
        )

    def _fetch_indicator_data(
        self, indicator_code: str, start_date: date, end_date: date
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

        data_points = adapter.fetch(indicator_code, start_date, end_date)
        if not isinstance(data_points, list) or not all(
            isinstance(point, MacroDataPoint) for point in data_points
        ):
            raise TypeError("macro_adapter_payload_invalid")
        return data_points

    def _get_adapter_for_indicator(
        self,
        indicator_code: str,
    ) -> MacroDataAdapterProtocol | None:
        """
        根据指标代码获取适配器

        Args:
            indicator_code: 指标代码

        Returns:
            Optional[object]: 适配器实例
        """
        # 简单的映射逻辑
        for _source, adapter in self.adapters.items():
            if adapter.supports(indicator_code):
                return adapter

        return None

    def _filter_new_or_changed_indicators(
        self, indicators: list[MacroIndicator], force_refresh: bool = False
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
                code=indicator.code, observed_at=indicator.reporting_period
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

    @staticmethod
    def _get_default_indicators() -> list[str]:
        """
        获取默认支持的指标列表

        Returns:
            List[str]: 指标代码列表
        """
        return [
            # 基础指标
            "CN_PMI",  # PMI (制造业采购经理指数)
            "CN_NON_MAN_PMI",  # 非制造业PMI
            "CN_CPI",  # CPI (居民消费价格指数)
            "CN_CPI_NATIONAL_YOY",  # 全国CPI同比
            "CN_CPI_NATIONAL_MOM",  # 全国CPI环比
            "CN_PPI",  # PPI (工业生产者出厂价格指数)
            "CN_PPI_YOY",  # PPI同比
            "CN_M2",  # M2 (货币供应量)
            "CN_M2_YOY",  # M2同比
            "CN_VALUE_ADDED",  # 工业增加值
            "CN_RETAIL_SALES",  # 社会消费品零售总额
            "CN_RETAIL_SALES_YOY",  # 社会消费品零售总额同比
            "CN_FIXED_INVESTMENT",  # 固定资产投资累计值
            "CN_FAI_YOY",  # 固定资产投资累计同比
            "CN_GDP",  # GDP (国内生产总值)
            "CN_GDP_YOY",  # GDP同比
            # 贸易数据
            "CN_EXPORTS",  # 当月出口额
            "CN_EXPORT_YOY",  # 当月出口额同比增长
            "CN_IMPORTS",  # 当月进口额
            "CN_IMPORT_YOY",  # 当月进口额同比增长
            "CN_TRADE_BALANCE",  # 贸易差额
            # 房产数据
            "CN_NEW_HOUSE_PRICE",  # 新房价格指数
            # 金融数据
            "CN_SHIBOR",  # SHIBOR 利率
            "CN_LPR",  # LPR (贷款市场报价利率)
            "CN_RRR",  # 存款准备金率
            # 信贷数据
            "CN_NEW_CREDIT",  # 新增信贷
            "CN_RMB_DEPOSIT",  # 人民币存款
            "CN_RMB_LOAN",  # 人民币贷款
            "CN_SOCIAL_FINANCING",  # 社会融资规模增量
            "CN_SOCIAL_FINANCING_YOY",  # 社会融资规模增量同比
            # 其他数据
            "CN_UNEMPLOYMENT",  # 城镇调查失业率
            "CN_FX_RESERVES",  # 外汇储备
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

    def __init__(self, repository: MacroRepositoryProtocol) -> None:
        """
        Args:
            repository: MacroRepository 实例
        """
        self.repository = repository

    def execute(self, request: GetLatestMacroDataRequest) -> GetLatestMacroDataResponse:
        """
        执行获取最新数据

        Args:
            request: 请求

        Returns:
            GetLatestMacroDataResponse: 最新数据
        """
        data: dict[str, MacroIndicator | None] = {}
        missing: list[str] = []

        for code in request.indicator_codes:
            try:
                # 获取该指标的最新可用日期
                latest_date = self.repository.get_latest_observation_date(
                    code=code, as_of_date=request.as_of_date
                )

                if latest_date:
                    indicator = self.repository.get_by_code_and_date(
                        code=code, observed_at=latest_date
                    )
                    data[code] = indicator
                else:
                    data[code] = None
                    missing.append(code)

            except _MACRO_OPERATION_EXCEPTIONS as exc:
                logger.warning(
                    "Latest Macro data lookup failed; indicator=%s; exception_type=%s",
                    code,
                    type(exc).__name__,
                )
                data[code] = None
                missing.append(code)

        return GetLatestMacroDataResponse(data=data, missing=missing)


class CanonicalMacroSyncUseCase:
    """Macro-facing facade over the canonical Data Center sync pipeline."""

    def __init__(
        self,
        batch_use_case: SyncMacroBatchUseCase,
        source: str | None = None,
    ) -> None:
        self._batch_use_case = batch_use_case
        self._source = source

    def execute(self, request: SyncMacroDataRequest) -> SyncMacroDataResponse:
        result = self._batch_use_case.execute(
            SyncMacroBatchRequest(
                indicator_codes=request.indicators
                or SyncMacroDataUseCase._get_default_indicators(),
                start=request.start_date,
                end=request.end_date or date.today(),
                source=self._source,
            )
        )
        return SyncMacroDataResponse(
            success=not result.errors,
            synced_count=result.stored_count,
            skipped_count=0,
            errors=list(result.errors),
        )


def build_sync_macro_data_use_case(
    source: str | None = None,
) -> CanonicalMacroSyncUseCase:
    """Build the Macro facade over Data Center's canonical provider registry."""
    from apps.data_center.application.interface_services import (
        make_sync_macro_batch_use_case,
    )

    return CanonicalMacroSyncUseCase(
        batch_use_case=make_sync_macro_batch_use_case(),
        source=source,
    )
