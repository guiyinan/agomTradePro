"""Pulse 模块 Protocol 接口定义。"""

from datetime import date
from typing import Protocol


class PulseDataProviderProtocol(Protocol):
    """Pulse 数据提供者协议

    定义 Pulse 模块从 macro 模块获取高频数据的接口。
    """

    def get_latest_value(
        self,
        indicator_code: str,
        before_date: date | None = None,
    ) -> tuple[float, date, int] | None:
        """
        获取指标最新值

        Returns:
            (value, observed_date, data_age_days) 或 None
        """
        ...

    def get_series(
        self,
        indicator_code: str,
        end_date: date,
        lookback_days: int = 365,
    ) -> list[float]:
        """
        获取指标历史序列值

        Returns:
            值列表（按时间排序）
        """
        ...
