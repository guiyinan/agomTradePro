"""
Use Cases for Macro Data Collection.

Application layer orchestrating the workflow of syncing macro data from various sources.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Dict

from ..domain.entities import MacroIndicator


@dataclass
class SyncMacroDataRequest:
    """同步宏观数据的请求 DTO"""
    start_date: date
    end_date: Optional[date] = None
    indicators: Optional[List[str]] = None
    force_refresh: bool = False


@dataclass
class SyncMacroDataResponse:
    """同步宏观数据的响应 DTO"""
    success: bool
    synced_count: int
    skipped_count: int
    errors: List[str]


@dataclass
class MacroDataPoint:
    """宏观数据点"""
    code: str
    value: float
    observed_at: date
    published_at: Optional[date]
    source: str


class SyncMacroDataUseCase:
    """
    同步宏观数据的用例

    职责：
    1. 调用适配器获取数据
    2. 去重处理
    3. 批量保存到数据库
    """

    def __init__(self, repository, adapters: Optional[Dict[str, object]] = None):
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

                # 2. 去重处理
                new_points = self._deduplicate_data(indicator_code, data_points)

                # 3. 批量保存
                indicators_to_save = [
                    MacroIndicator(
                        code=dp.code,
                        value=dp.value,
                        observed_at=dp.observed_at,
                        published_at=dp.published_at,
                        source=dp.source
                    )
                    for dp in new_points
                ]

                if indicators_to_save:
                    self.repository.save_indicators_batch(indicators_to_save)
                    synced_count += len(indicators_to_save)

                skipped_count = len(data_points) - len(new_points)

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
    ) -> List[MacroDataPoint]:
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

    def _get_adapter_for_indicator(self, indicator_code: str) -> Optional[object]:
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

    def _deduplicate_data(
        self,
        code: str,
        data_points: List[MacroDataPoint]
    ) -> List[MacroDataPoint]:
        """
        去重处理

        Args:
            code: 指标代码
            data_points: 数据点列表

        Returns:
            List[MacroDataPoint]: 去重后的数据点列表
        """
        new_points = []

        for dp in data_points:
            # 检查数据库中是否已存在
            existing = self.repository.get_by_code_and_date(
                code=code,
                observed_at=dp.observed_at
            )

            if existing is None:
                new_points.append(dp)

        return new_points

    def _get_default_indicators(self) -> List[str]:
        """
        获取默认支持的指标列表

        Returns:
            List[str]: 指标代码列表
        """
        return [
            "CN_PMI",      # PMI
            "CN_CPI",      # CPI
            "CN_PPI",      # PPI
            "SHIBOR",      # SHIBOR 利率
        ]


@dataclass
class GetLatestMacroDataRequest:
    """获取最新宏观数据的请求 DTO"""
    indicator_codes: List[str]
    as_of_date: Optional[date] = None


@dataclass
class GetLatestMacroDataResponse:
    """获取最新宏观数据的响应 DTO"""
    data: Dict[str, Optional[MacroIndicator]]
    missing: List[str]


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
