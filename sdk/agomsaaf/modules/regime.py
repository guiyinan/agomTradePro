from typing import TYPE_CHECKING
"""
AgomSAAF SDK - Regime 判定模块

提供宏观象限（Regime）相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from .base import BaseModule
from ..types import RegimeCalculationParams, RegimeState, RegimeType


class RegimeModule(BaseModule):
    """
    Regime 判定模块

    提供宏观象限判定、历史查询等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Regime 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        super().__init__(client, "/regime/api")

    def get_current(self) -> RegimeState:
        """
        获取当前宏观象限

        Returns:
            当前宏观象限状态

        Raises:
            NotFoundError: 当没有可用的 Regime 数据时
            ServerError: 当服务器处理失败时

        Example:
            >>> client = AgomSAAFClient()
            >>> regime = client.regime.get_current()
            >>> print(f"当前象限: {regime.dominant_regime}")
            >>> print(f"增长水平: {regime.growth_level}")
            >>> print(f"通胀水平: {regime.inflation_level}")
        """
        response = self._get("current/")
        return self._parse_regime_state(response)

    def calculate(
        self,
        as_of_date: Optional[date] = None,
        growth_indicator: str = "PMI",
        inflation_indicator: str = "CPI",
        use_kalman: bool = True,
    ) -> RegimeState:
        """
        计算指定日期的 Regime 判定

        Args:
            as_of_date: 计算日期（None 表示使用最新数据）
            growth_indicator: 增长指标代码（默认 PMI）
            inflation_indicator: 通胀指标代码（默认 CPI）
            use_kalman: 是否使用 Kalman 滤波（默认 True）

        Returns:
            计算得到的宏观象限状态

        Raises:
            ValidationError: 当参数无效时
            ServerError: 当计算失败时

        Example:
            >>> from datetime import date
            >>> client = AgomSAAFClient()
            >>> regime = client.regime.calculate(
            ...     as_of_date=date(2024, 1, 1),
            ...     growth_indicator="PMI",
            ...     inflation_indicator="CPI"
            ... )
            >>> print(f"象限: {regime.dominant_regime}")
        """
        params: dict[str, Any] = {
            "growth_indicator": growth_indicator,
            "inflation_indicator": inflation_indicator,
            "use_kalman": use_kalman,
        }

        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        response = self._post("calculate/", json=params)
        return self._parse_regime_state(response)

    def history(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 100,
    ) -> list[RegimeState]:
        """
        获取 Regime 历史记录

        Args:
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）
            limit: 返回记录数量限制

        Returns:
            Regime 状态列表

        Raises:
            ValidationError: 当日期参数无效时

        Example:
            >>> from datetime import date
            >>> client = AgomSAAFClient()
            >>> history = client.regime.history(
            ...     start_date=date(2023, 1, 1),
            ...     end_date=date(2024, 12, 31),
            ...     limit=365
            ... )
            >>> for state in history:
            ...     print(f"{state.observed_at}: {state.dominant_regime}")
        """
        params: dict[str, Any] = {"limit": limit}

        if start_date is not None:
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            params["end_date"] = end_date.isoformat()

        response = self._get("history/", params=params)
        if isinstance(response, dict):
            items = response.get("results", [])
        elif isinstance(response, list):
            items = response
        else:
            items = []
        return [self._parse_regime_state(item) for item in items]

    def get_regime_distribution(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[RegimeType, int]:
        """
        获取指定时间段内的 Regime 分布统计

        Args:
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            各象限出现天数的字典

        Example:
            >>> client = AgomSAAFClient()
            >>> distribution = client.regime.get_regime_distribution(
            ...     start_date=date(2023, 1, 1),
            ...     end_date=date(2024, 12, 31)
            ... )
            >>> for regime_type, days in distribution.items():
            ...     print(f"{regime_type}: {days} 天")
        """
        history = self.history(start_date=start_date, end_date=end_date, limit=10000)

        distribution: dict[RegimeType, int] = {
            "Recovery": 0,
            "Overheat": 0,
            "Stagflation": 0,
            "Repression": 0,
        }

        for state in history:
            distribution[state.dominant_regime] += 1

        return distribution

    def _parse_regime_state(self, data: dict[str, Any]) -> RegimeState:
        """
        解析 Regime 状态数据

        Args:
            data: API 返回的 JSON 数据

        Returns:
            RegimeState 对象
        """
        # 处理日期
        observed_at = data.get("observed_at")
        if isinstance(observed_at, str):
            from datetime import datetime

            observed_at = datetime.fromisoformat(observed_at).date()
        elif observed_at is None:
            observed_at = date.today()

        return RegimeState(
            dominant_regime=data["dominant_regime"],
            observed_at=observed_at,
            growth_level=data.get("growth_level", "neutral"),
            inflation_level=data.get("inflation_level", "neutral"),
            growth_indicator=data.get("growth_indicator", "PMI"),
            inflation_indicator=data.get("inflation_indicator", "CPI"),
            growth_value=data.get("growth_value"),
            inflation_value=data.get("inflation_value"),
            confidence=data.get("confidence"),
        )
