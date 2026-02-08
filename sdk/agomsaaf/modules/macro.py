from typing import TYPE_CHECKING
"""
AgomSAAF SDK - Macro 宏观数据模块

提供宏观指标数据相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from .base import BaseModule
from ..types import MacroDataPoint, MacroIndicator


class MacroModule(BaseModule):
    """
    宏观数据模块

    提供宏观指标查询、数据同步等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Macro 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        # Backend macro endpoints are served under /macro/api/*
        super().__init__(client, "/macro/api")

    def list_indicators(
        self,
        data_source: Optional[str] = None,
        frequency: Optional[str] = None,
        limit: int = 100,
    ) -> list[MacroIndicator]:
        """
        获取宏观指标列表

        Args:
            data_source: 数据源过滤（可选）
            frequency: 频率过滤（可选）
            limit: 返回数量限制

        Returns:
            宏观指标列表

        Example:
            >>> client = AgomSAAFClient()
            >>> indicators = client.macro.list_indicators(frequency="monthly")
            >>> for indicator in indicators:
            ...     print(f"{indicator.code}: {indicator.name}")
        """
        params: dict[str, Any] = {"limit": limit}

        if data_source is not None:
            params["data_source"] = data_source
        if frequency is not None:
            params["frequency"] = frequency

        response = self._get("indicators/", params=params)
        results = response.get("results", response)
        return [self._parse_indicator(item) for item in results]

    def get_indicator(self, indicator_code: str) -> MacroIndicator:
        """
        获取单个宏观指标详情

        Args:
            indicator_code: 指标代码

        Returns:
            宏观指标详情

        Raises:
            NotFoundError: 当指标不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> indicator = client.macro.get_indicator("PMI")
            >>> print(f"名称: {indicator.name}")
            >>> print(f"单位: {indicator.unit}")
        """
        response = self._get(f"indicators/{indicator_code}/")
        return self._parse_indicator(response)

    def get_indicator_data(
        self,
        indicator_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 100,
    ) -> list[MacroDataPoint]:
        """
        获取宏观指标数据

        Args:
            indicator_code: 指标代码
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）
            limit: 返回数量限制

        Returns:
            宏观数据点列表

        Example:
            >>> from datetime import date
            >>> client = AgomSAAFClient()
            >>> data = client.macro.get_indicator_data(
            ...     indicator_code="PMI",
            ...     start_date=date(2023, 1, 1),
            ...     end_date=date(2024, 12, 31)
            ... )
            >>> for point in data:
            ...     print(f"{point.date}: {point.value} {point.unit}")
        """
        params: dict[str, Any] = {"limit": limit}

        if start_date is not None:
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            params["end_date"] = end_date.isoformat()

        response = self._get(f"indicators/{indicator_code}/data/", params=params)
        results = response.get("results", response)
        return [self._parse_data_point(item, indicator_code) for item in results]

    def get_latest_data(self, indicator_code: str) -> Optional[MacroDataPoint]:
        """
        获取宏观指标最新数据

        Args:
            indicator_code: 指标代码

        Returns:
            最新的宏观数据点，如果没有数据则返回 None

        Example:
            >>> client = AgomSAAFClient()
            >>> latest = client.macro.get_latest_data("PMI")
            >>> if latest:
            ...     print(f"最新 PMI: {latest.value}")
            ... else:
            ...     print("暂无数据")
        """
        data = self.get_indicator_data(indicator_code, limit=1)
        return data[0] if data else None

    def sync_indicator(
        self,
        indicator_code: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        同步宏观指标数据

        从数据源拉取最新数据并存储。

        Args:
            indicator_code: 指标代码
            force: 是否强制同步（忽略缓存）

        Returns:
            同步结果，包含新增/更新的数据点数量

        Raises:
            ValidationError: 当指标代码无效时
            ServerError: 当同步失败时

        Example:
            >>> client = AgomSAAFClient()
            >>> result = client.macro.sync_indicator("PMI", force=True)
            >>> print(f"新增数据点: {result['created']}")
            >>> print(f"更新数据点: {result['updated']}")
        """
        data = {"force": force}
        return self._post(f"indicators/{indicator_code}/sync/", json=data)

    def _parse_indicator(self, data: dict[str, Any]) -> MacroIndicator:
        """
        解析宏观指标数据

        Args:
            data: API 返回的 JSON 数据

        Returns:
            MacroIndicator 对象
        """
        return MacroIndicator(
            code=data["code"],
            name=data["name"],
            unit=data["unit"],
            frequency=data["frequency"],
            data_source=data["data_source"],
        )

    def _parse_data_point(self, data: dict[str, Any], indicator_code: str) -> MacroDataPoint:
        """
        解析宏观数据点

        Args:
            data: API 返回的 JSON 数据
            indicator_code: 指标代码

        Returns:
            MacroDataPoint 对象
        """
        # 处理日期
        obs_date = data.get("date")
        if isinstance(obs_date, str):
            from datetime import datetime

            obs_date = datetime.fromisoformat(obs_date).date()
        elif obs_date is None:
            obs_date = date.today()

        return MacroDataPoint(
            indicator_code=indicator_code,
            date=obs_date,
            value=data["value"],
            unit=data.get("unit", ""),
        )
