"""
AgomTradePro SDK - Regime 判定模块

提供宏观象限（Regime）相关的 API 操作。
"""

from datetime import date
from typing import Any

from ..exceptions import ValidationError
from ..types import RegimeState, RegimeType
from .base import BaseModule


class RegimeModule(BaseModule):
    """
    Regime 判定模块

    提供宏观象限判定、历史查询等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Regime 模块

        Args:
            client: AgomTradePro 客户端实例
        """
        super().__init__(client, "/api/regime")

    def get_current(self) -> RegimeState:
        """
        获取当前宏观象限

        Returns:
            当前宏观象限状态

        Raises:
            NotFoundError: 当没有可用的 Regime 数据时
            ServerError: 当服务器处理失败时

        Example:
            >>> client = AgomTradeProClient()
            >>> regime = client.regime.get_current()
            >>> print(f"当前象限: {regime.dominant_regime}")
            >>> print(f"增长水平: {regime.growth_level}")
            >>> print(f"通胀水平: {regime.inflation_level}")
        """
        response = self._get("current/")
        return self._parse_regime_state(response)

    def calculate(
        self,
        as_of_date: date | None = None,
        growth_indicator: str = "PMI",
        inflation_indicator: str = "CPI",
        use_pit: bool = True,
        data_source: str = "akshare",
    ) -> RegimeState:
        """
        计算指定日期的 Regime 判定

        Args:
            as_of_date: 计算日期（None 表示使用最新数据）
            growth_indicator: 增长指标代码（默认 PMI）
            inflation_indicator: 通胀指标代码（默认 CPI）
            use_pit: 是否使用 Point-in-Time 数据（默认 True）
            data_source: 已持久化宏观数据的来源（默认 akshare）

        Returns:
            计算得到的宏观象限状态

        Raises:
            ValidationError: 当参数无效时
            ServerError: 当计算失败时

        Example:
            >>> from datetime import date
            >>> client = AgomTradeProClient()
            >>> regime = client.regime.calculate(
            ...     as_of_date=date(2024, 1, 1),
            ...     growth_indicator="PMI",
            ...     inflation_indicator="CPI"
            ... )
            >>> print(f"象限: {regime.dominant_regime}")
        """
        response = self.calculate_snapshot(
            as_of_date=as_of_date,
            growth_indicator=growth_indicator,
            inflation_indicator=inflation_indicator,
            use_pit=use_pit,
            data_source=data_source,
        )
        snapshot = response.get("snapshot")
        if not response.get("success") or not isinstance(snapshot, dict):
            raise ValidationError(
                response.get("error") or "Regime calculation returned no snapshot.",
                response=response,
            )

        raw_data = response.get("raw_data")
        growth_rows = raw_data.get("growth", []) if isinstance(raw_data, dict) else []
        inflation_rows = raw_data.get("inflation", []) if isinstance(raw_data, dict) else []
        normalized = {
            **snapshot,
            "growth_level": self._series_direction(growth_rows),
            "inflation_level": self._series_direction(inflation_rows),
            "growth_indicator": growth_indicator,
            "inflation_indicator": inflation_indicator,
            "growth_value": self._latest_series_value(growth_rows),
            "inflation_value": self._latest_series_value(inflation_rows),
        }
        return self._parse_regime_state(normalized)

    def calculate_snapshot(
        self,
        as_of_date: date | None = None,
        growth_indicator: str = "PMI",
        inflation_indicator: str = "CPI",
        use_pit: bool = True,
        data_source: str = "akshare",
    ) -> dict[str, Any]:
        """Return the canonical pure-calculation response envelope."""

        payload: dict[str, Any] = {
            "use_pit": use_pit,
            "growth_indicator": growth_indicator,
            "inflation_indicator": inflation_indicator,
            "data_source": data_source,
        }
        if as_of_date is not None:
            payload["as_of_date"] = as_of_date.isoformat()
        return self._post("calculate/", json=payload)

    def history(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
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
            >>> client = AgomTradeProClient()
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
            items = response.get("data", response.get("results", []))
        elif isinstance(response, list):
            items = response
        else:
            items = []
        return [self._parse_regime_state(item) for item in items]

    def get_regime_distribution(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[RegimeType, int]:
        """
        获取指定时间段内的 Regime 分布统计

        Args:
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            各象限出现天数的字典

        Example:
            >>> client = AgomTradeProClient()
            >>> distribution = client.regime.get_regime_distribution(
            ...     start_date=date(2023, 1, 1),
            ...     end_date=date(2024, 12, 31)
            ... )
            >>> for regime_type, days in distribution.items():
            ...     print(f"{regime_type}: {days} 天")
        """
        params: dict[str, Any] = {}
        if start_date is not None:
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            params["end_date"] = end_date.isoformat()
        response = self._get("distribution/", params=params)
        stats: list[dict[str, Any]]
        if isinstance(response, dict) and "distribution" in response:
            stats = response.get("distribution", [])
        elif isinstance(response, dict) and "results" in response:
            counts: dict[str, int] = {}
            for item in response.get("results", []):
                regime = item.get("dominant_regime")
                if regime:
                    counts[regime] = counts.get(regime, 0) + 1
            stats = [
                {"dominant_regime": regime, "count": count} for regime, count in counts.items()
            ]
        else:
            stats = []

        distribution: dict[RegimeType, int] = {
            "Recovery": 0,
            "Overheat": 0,
            "Stagflation": 0,
            "Deflation": 0,
        }
        for stat in stats:
            regime = stat.get("dominant_regime")
            if regime == "Repression":
                regime = "Deflation"
            if regime in distribution:
                distribution[regime] += stat.get("count", 0)
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
        elif observed_at is not None and not isinstance(observed_at, date):
            raise ValidationError("observed_at must be an ISO date or null")

        contract = data.get("contract") if isinstance(data.get("contract"), dict) else {}

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
            diagnostic_regime=data.get("diagnostic_regime"),
            is_stale=bool(data.get("is_stale", contract.get("is_stale", False))),
            must_not_use_for_decision=bool(
                data.get(
                    "must_not_use_for_decision",
                    contract.get("must_not_use_for_decision", False),
                )
            ),
            blocked_reason=str(
                data.get("blocked_reason", contract.get("blocked_reason", "")) or ""
            ),
        )

    @staticmethod
    def _latest_series_value(rows: Any) -> float | None:
        """Return the latest numeric value from a canonical raw-data series."""

        if not isinstance(rows, list) or not rows:
            return None
        value = rows[-1].get("value") if isinstance(rows[-1], dict) else None
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _series_direction(cls, rows: Any) -> str:
        """Derive the stable SDK direction label from the latest two values."""

        if not isinstance(rows, list) or len(rows) < 2:
            return "neutral"
        previous = cls._latest_series_value(rows[:-1])
        current = cls._latest_series_value(rows)
        if previous is None or current is None:
            return "neutral"
        if current > previous:
            return "up"
        if current < previous:
            return "down"
        return "neutral"
