from typing import TYPE_CHECKING
"""
AgomTradePro SDK - Macro 宏观数据模块

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

    INDICATOR_ALIASES = {
        "PMI": "CN_PMI",
        "CPI": "CN_CPI",
        "PPI": "CN_PPI",
        "M2": "CN_M2",
    }

    def __init__(self, client: Any) -> None:
        """
        初始化 Macro 模块

        Args:
            client: AgomTradePro 客户端实例
        """
        # Backend macro endpoints are served under /api/macro/*.
        # The previous /macro/api/* path is no longer mounted in the current app.
        super().__init__(client, "/api/macro")

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
            >>> client = AgomTradeProClient()
            >>> indicators = client.macro.list_indicators(frequency="monthly")
            >>> for indicator in indicators:
            ...     print(f"{indicator.code}: {indicator.name}")
        """
        params: dict[str, Any] = {"limit": limit}

        if data_source is not None:
            params["data_source"] = data_source
        if frequency is not None:
            params["frequency"] = frequency

        response = self._get("supported-indicators/", params=params)
        if isinstance(response, dict):
            results = response.get("indicators", response.get("results", response))
        else:
            results = response
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
            >>> client = AgomTradeProClient()
            >>> indicator = client.macro.get_indicator("PMI")
            >>> print(f"名称: {indicator.name}")
            >>> print(f"单位: {indicator.unit}")
        """
        normalized_code = self._normalize_indicator_code(indicator_code)
        indicators = self.list_indicators(limit=1000)
        for indicator in indicators:
            if indicator.code == normalized_code:
                return indicator
        raise ValueError(f"Macro indicator not found: {indicator_code}")

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
            >>> client = AgomTradeProClient()
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

        normalized_code = self._normalize_indicator_code(indicator_code)
        response = self._get("indicator-data/", params={"code": normalized_code, **params})
        if isinstance(response, dict):
            results = response.get("data", response.get("results", response))
        else:
            results = response
        return [self._parse_data_point(item, normalized_code) for item in results]

    def get_latest_data(self, indicator_code: str) -> Optional[MacroDataPoint]:
        """
        获取宏观指标最新数据

        Args:
            indicator_code: 指标代码

        Returns:
            最新的宏观数据点，如果没有数据则返回 None

        Example:
            >>> client = AgomTradeProClient()
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
            >>> client = AgomTradeProClient()
            >>> result = client.macro.sync_indicator("PMI", force=True)
            >>> print(f"新增数据点: {result['created']}")
            >>> print(f"更新数据点: {result['updated']}")
        """
        normalized_code = self._normalize_indicator_code(indicator_code)
        data = {
            "indicators": [normalized_code],
            "source": "akshare",
            "force_refresh": force,
        }
        return self._post("fetch/", json=data)

    def list_datasources(self) -> list[dict[str, Any]]:
        """列出财经数据源中台中的宏观数据源配置。"""
        response = self._get("datasources/")
        if isinstance(response, dict):
            return response.get("results", response.get("data", []))
        return response

    def create_datasource(self, payload: dict[str, Any]) -> dict[str, Any]:
        """创建宏观数据源配置。"""
        return self._post("datasources/", json=payload)

    def update_datasource(
        self,
        source_id: int,
        payload: dict[str, Any],
        *,
        partial: bool = True,
    ) -> dict[str, Any]:
        """更新宏观数据源配置。"""
        if partial:
            return self._patch(f"datasources/{source_id}/", json=payload)
        return self._put(f"datasources/{source_id}/", json=payload)

    def _normalize_indicator_code(self, indicator_code: str) -> str:
        """Map legacy short names used by MCP/SDK docs to backend codes."""
        return self.INDICATOR_ALIASES.get(indicator_code, indicator_code)

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
            unit=data.get("unit", ""),
            frequency=data.get("frequency", ""),
            data_source=data.get("data_source", ""),
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
