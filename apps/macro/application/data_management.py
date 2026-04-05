"""
Data Management Use Cases for Unified Data Controller.

Provides functionality for:
- Manual data fetching
- Scheduled data fetching
- Data deletion
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable

from ..domain.entities import MacroIndicator

logger = logging.getLogger(__name__)


class DataSourceType(Enum):
    """数据源类型"""
    AKSHARE = "akshare"
    TUSHARE = "tushare"


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class FetchDataRequest:
    """数据获取请求"""
    indicators: list[str] | None = None
    start_date: date | None = None
    end_date: date | None = None
    source: str | None = None


@dataclass
class FetchDataResponse:
    """数据获取响应"""
    success: bool
    message: str
    synced_count: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


@dataclass
class DeleteDataRequest:
    """数据删除请求"""
    indicator_code: str | None = None
    source: str | None = None
    start_date: date | None = None
    end_date: date | None = None


@dataclass
class DeleteDataResponse:
    """数据删除响应"""
    success: bool
    message: str
    deleted_count: int = 0


class RunDataSourceConnectionTestUseCase:
    """Application wrapper for datasource connectivity probes."""

    def __init__(
        self,
        probe_runner: Callable[[Any], dict[str, Any]] | None = None,
    ) -> None:
        self._probe_runner = probe_runner or self._default_probe_runner

    def execute(self, config: Any) -> dict[str, Any]:
        """Run the configured probe and return a display-friendly payload."""
        return self._probe_runner(config)

    @staticmethod
    def _default_probe_runner(config: Any) -> dict[str, Any]:
        from apps.macro.infrastructure.datasource_connection_tester import (
            run_datasource_connection_test,
        )

        return run_datasource_connection_test(config)


@dataclass
class DataSourceStatus:
    """数据源状态"""
    name: str
    source_type: str
    priority: int
    is_active: bool
    last_sync: datetime | None = None
    record_count: int = 0


@dataclass
class DataManagementSummary:
    """数据管理概览"""
    total_indicators: int
    total_records: int
    data_sources: list[DataSourceStatus]
    recent_syncs: list[dict[str, Any]]


class FetchDataUseCase:
    """
    数据获取用例
    支持手动触发数据抓取
    """

    def __init__(self, sync_use_case, repository):
        """
        Args:
            sync_use_case: SyncMacroDataUseCase 实例
            repository: 数据仓储
        """
        self.sync_use_case = sync_use_case
        self.repository = repository

    def execute(self, request: FetchDataRequest) -> FetchDataResponse:
        """
        执行数据获取

        Args:
            request: 数据获取请求

        Returns:
            FetchDataResponse: 获取结果
        """
        try:
            # 构建同步请求
            sync_request = self._build_sync_request(request)

            # 执行同步
            sync_response = self.sync_use_case.execute(sync_request)

            if sync_response.success:
                return FetchDataResponse(
                    success=True,
                    message=f"成功同步 {sync_response.synced_count} 条数据",
                    synced_count=sync_response.synced_count
                )
            else:
                return FetchDataResponse(
                    success=False,
                    message="数据同步过程中出现错误",
                    errors=sync_response.errors
                )

        except Exception as e:
            logger.exception("数据获取失败")
            return FetchDataResponse(
                success=False,
                message=f"数据获取失败: {str(e)}",
                errors=[str(e)]
            )

    def _build_sync_request(self, request: FetchDataRequest):
        """构建同步请求"""
        from .use_cases import SyncMacroDataRequest

        start_date = request.start_date or self._get_default_start_date()
        end_date = request.end_date or date.today()

        return SyncMacroDataRequest(
            start_date=start_date,
            end_date=end_date,
            indicators=request.indicators,
            force_refresh=True
        )

    def _get_default_start_date(self) -> date:
        """获取默认起始日期（最近3个月）"""
        from datetime import timedelta
        return date.today() - timedelta(days=90)


class DeleteDataUseCase:
    """
    数据删除用例
    支持按条件删除数据
    """

    def __init__(self, repository):
        """
        Args:
            repository: 数据仓储
        """
        self.repository = repository

    def execute(self, request: DeleteDataRequest) -> DeleteDataResponse:
        """
        执行数据删除

        Args:
            request: 删除请求

        Returns:
            DeleteDataResponse: 删除结果
        """
        try:
            deleted_count = self.repository.delete_by_conditions(
                indicator_code=request.indicator_code,
                source=request.source,
                start_date=request.start_date,
                end_date=request.end_date
            )

            return DeleteDataResponse(
                success=True,
                message=f"成功删除 {deleted_count} 条数据",
                deleted_count=deleted_count
            )

        except Exception as e:
            logger.exception("数据删除失败")
            return DeleteDataResponse(
                success=False,
                message=f"数据删除失败: {str(e)}",
                deleted_count=0
            )


class GetDataManagementSummaryUseCase:
    """
    获取数据管理概览用例
    """

    def __init__(self, repository):
        """
        Args:
            repository: 数据仓储
        """
        self.repository = repository

    def execute(self) -> DataManagementSummary:
        """
        执行获取概览

        Returns:
            DataManagementSummary: 数据管理概览
        """
        # 获取统计信息
        stats = self.repository.get_statistics()

        # 获取数据源状态
        data_sources = self._build_data_source_status(stats)

        # 获取最近同步记录
        recent_syncs = self.repository.get_recent_syncs(limit=10)

        return DataManagementSummary(
            total_indicators=stats['total_indicators'],
            total_records=stats['total_records'],
            data_sources=data_sources,
            recent_syncs=recent_syncs
        )

    def _build_data_source_status(self, stats: dict) -> list[DataSourceStatus]:
        """构建数据源状态列表"""
        sources = []

        for source_info in stats.get('sources', []):
            sources.append(DataSourceStatus(
                name=source_info['name'],
                source_type=source_info.get('type', 'unknown'),
                priority=source_info.get('priority', 0),
                is_active=source_info.get('is_active', True),
                last_sync=source_info.get('last_sync'),
                record_count=source_info.get('record_count', 0)
            ))

        return sources


class ScheduleDataFetchUseCase:
    """
    定时数据获取用例
    配置定时任务规则
    """

    # 支持的指标及其建议抓取频率
    INDICATOR_SCHEDULES = {
        "CN_PMI": {"frequency": "monthly", "day_of_month": 1},
        "CN_NON_MAN_PMI": {"frequency": "monthly", "day_of_month": 1},
        "CN_CPI": {"frequency": "monthly", "day_of_month": 10},
        "CN_CPI_NATIONAL_YOY": {"frequency": "monthly", "day_of_month": 10},
        "CN_CPI_NATIONAL_MOM": {"frequency": "monthly", "day_of_month": 10},
        "CN_CPI_URBAN_YOY": {"frequency": "monthly", "day_of_month": 10},
        "CN_CPI_URBAN_MOM": {"frequency": "monthly", "day_of_month": 10},
        "CN_CPI_RURAL_YOY": {"frequency": "monthly", "day_of_month": 10},
        "CN_CPI_RURAL_MOM": {"frequency": "monthly", "day_of_month": 10},
        "CN_PPI": {"frequency": "monthly", "day_of_month": 10},
        "CN_PPI_YOY": {"frequency": "monthly", "day_of_month": 10},
        "CN_M2": {"frequency": "monthly", "day_of_month": 15},
        "CN_VALUE_ADDED": {"frequency": "monthly", "day_of_month": 15},
        "CN_RETAIL_SALES": {"frequency": "monthly", "day_of_month": 15},
        "CN_GDP": {"frequency": "quarterly", "day_of_month": 20},
        "CN_SHIBOR": {"frequency": "daily"},
        "CN_EXPORTS": {"frequency": "monthly", "day_of_month": 10},
        "CN_IMPORTS": {"frequency": "monthly", "day_of_month": 10},
        "CN_TRADE_BALANCE": {"frequency": "monthly", "day_of_month": 10},
        "CN_UNEMPLOYMENT": {"frequency": "monthly", "day_of_month": 15},
        "CN_FX_RESERVES": {"frequency": "monthly", "day_of_month": 10},
        "CN_LPR": {"frequency": "monthly", "day_of_month": 20},
        "CN_RRR": {"frequency": "daily"},  # 不定期调整，每日检查
        "CN_NEW_HOUSE_PRICE": {"frequency": "monthly", "day_of_month": 15},
        "CN_OIL_PRICE": {"frequency": "daily"},  # 不定期调整，每日检查
        "CN_NEW_CREDIT": {"frequency": "monthly", "day_of_month": 15},
        "CN_RMB_DEPOSIT": {"frequency": "monthly", "day_of_month": 15},
        "CN_RMB_LOAN": {"frequency": "monthly", "day_of_month": 15},
    }

    def __init__(self, repository):
        """
        Args:
            repository: 数据仓储
        """
        self.repository = repository

    def get_scheduled_indicators(self) -> dict[str, dict]:
        """
        获取所有可定时抓取的指标配置

        Returns:
            Dict: 指标调度配置
        """
        return self.INDICATOR_SCHEDULES

    def get_due_indicators(self, as_of_date: date | None = None) -> list[str]:
        """
        获取到期需要抓取的指标

        Args:
            as_of_date: 检查日期，默认为今天

        Returns:
            List[str]: 需要抓取的指标代码列表
        """
        check_date = as_of_date or date.today()
        due_indicators = []

        for indicator, schedule in self.INDICATOR_SCHEDULES.items():
            if self._is_indicator_due(indicator, schedule, check_date):
                due_indicators.append(indicator)

        return due_indicators

    def _is_indicator_due(self, indicator: str, schedule: dict, check_date: date) -> bool:
        """
        判断指标是否到期需要抓取

        Args:
            indicator: 指标代码
            schedule: 调度配置
            check_date: 检查日期

        Returns:
            bool: 是否到期
        """
        frequency = schedule.get("frequency")

        if frequency == "daily":
            return self._is_daily_due(indicator, check_date)
        elif frequency == "monthly":
            day_of_month = schedule.get("day_of_month", 1)
            return self._is_monthly_due(indicator, check_date, day_of_month)

        return False

    def _is_daily_due(self, indicator: str, check_date: date) -> bool:
        """判断日更指标是否到期"""
        # 检查今天是否已有数据
        latest = self.repository.get_latest_observation_date(indicator, check_date)
        return latest != check_date

    def _is_monthly_due(self, indicator: str, check_date: date, target_day: int) -> bool:
        """判断月度指标是否到期"""
        # 检查目标日是否已过或当天
        if check_date.day < target_day:
            return False

        # 检查本月是否已有数据
        from datetime import timedelta
        month_start = check_date.replace(day=1)
        latest = self.repository.get_latest_observation_date(indicator, check_date)

        # 如果没有数据或数据早于本月开始，则需要抓取
        return latest is None or latest < month_start
