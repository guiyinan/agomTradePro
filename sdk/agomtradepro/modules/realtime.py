from typing import TYPE_CHECKING
"""
AgomTradePro SDK - Realtime 实时价格监控模块

提供实时价格监控相关的 API 操作。
"""

from typing import Any, Optional

from .base import BaseModule


class RealtimeModule(BaseModule):
    """
    实时价格监控模块

    提供实时价格查询、价格预警、价格历史等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Realtime 模块

        Args:
            client: AgomTradePro 客户端实例
        """
        super().__init__(client, "/api/realtime")

    def get_price(
        self,
        asset_code: str,
    ) -> dict[str, Any]:
        """
        获取实时价格

        Args:
            asset_code: 资产代码

        Returns:
            实时价格信息，包括当前价、涨跌额、涨跌幅等

        Raises:
            NotFoundError: 当资产不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> price = client.realtime.get_price("000001.SH")
            >>> print(f"当前价: {price['current_price']}")
            >>> print(f"涨跌幅: {price['change_percent']:.2%}")
        """
        response = self._get(f"prices/{asset_code}/")
        return self._normalize_price_payload(response)

    def get_multiple_prices(
        self,
        asset_codes: list[str],
    ) -> dict[str, dict[str, Any]]:
        """
        批量获取实时价格

        Args:
            asset_codes: 资产代码列表

        Returns:
            资产代码到价格信息的字典

        Example:
            >>> client = AgomTradeProClient()
            >>> prices = client.realtime.get_multiple_prices([
            ...     "000001.SH", "000002.SZ"
            ... ])
            >>> for code, price in prices.items():
            ...     print(f"{code}: {price['current_price']}")
        """
        if not asset_codes:
            return {}

        response = self._get("prices/", params={"assets": ",".join(asset_codes)})
        prices = response.get("prices", response)
        normalized = [self._normalize_price_payload(item) for item in prices]
        return {item["asset_code"]: item for item in normalized if item.get("asset_code")}

    def get_batch_prices(
        self,
        asset_codes: list[str],
    ) -> list[dict[str, Any]]:
        """
        批量获取实时价格列表。

        兼容旧示例命名，内部复用 `get_multiple_prices()`。
        """
        return list(self.get_multiple_prices(asset_codes).values())

    def get_price_history(
        self,
        asset_code: str,
        period: str = "1d",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取价格历史

        Args:
            asset_code: 资产代码
            period: 时间周期（1m/5m/15m/30m/60m/1d/1w/1M）
            limit: 返回数量限制

        Returns:
            价格历史列表

        Example:
            >>> client = AgomTradeProClient()
            >>> history = client.realtime.get_price_history(
            ...     asset_code="000001.SH",
            ...     period="1d",
            ...     limit=30
            ... )
            >>> for bar in history:
            ...     print(f"{bar['timestamp']}: {bar['close']}")
        """
        params: dict[str, Any] = {"period": period, "limit": limit}
        response = self._get(f"prices/{asset_code}/history/", params=params)
        results = response.get("results", response)
        return results

    def list_alerts(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取价格预警列表

        Args:
            status: 预警状态过滤（active/triggered/inactive）
            limit: 返回数量限制

        Returns:
            预警列表

        Example:
            >>> client = AgomTradeProClient()
            >>> alerts = client.realtime.list_alerts(status="active")
            >>> for alert in alerts:
            ...     print(f"{alert['asset_code']}: {alert['condition']}")
        """
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status

        response = self._get("alerts/", params=params)
        results = response.get("results", response)
        return results

    def create_alert(
        self,
        asset_code: str,
        condition: str,
        threshold: float,
        message: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        创建价格预警

        Args:
            asset_code: 资产代码
            condition: 触发条件（above/below/cross_up/cross_down）
            threshold: 阈值
            message: 预警消息（可选）

        Returns:
            创建的预警信息

        Raises:
            ValidationError: 当参数验证失败时

        Example:
            >>> client = AgomTradeProClient()
            >>> alert = client.realtime.create_alert(
            ...     asset_code="000001.SH",
            ...     condition="above",
            ...     threshold=10.0,
            ...     message="价格突破10元"
            ... )
            >>> print(f"预警已创建: {alert['id']}")
        """
        data: dict[str, Any] = {
            "asset_code": asset_code,
            "condition": condition,
            "threshold": threshold,
        }

        if message is not None:
            data["message"] = message

        return self._post("alerts/", json=data)

    def get_alert(self, alert_id: int) -> dict[str, Any]:
        """
        获取预警详情

        Args:
            alert_id: 预警 ID

        Returns:
            预警详情

        Raises:
            NotFoundError: 当预警不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> alert = client.realtime.get_alert(1)
            >>> print(f"资产: {alert['asset_code']}")
            >>> print(f"状态: {alert['status']}")
        """
        return self._get(f"alerts/{alert_id}/")

    def delete_alert(self, alert_id: int) -> None:
        """
        删除预警

        Args:
            alert_id: 预警 ID

        Raises:
            NotFoundError: 当预警不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> client.realtime.delete_alert(1)
            >>> print("预警已删除")
        """
        self._delete(f"alerts/{alert_id}/")

    def get_market_summary(self) -> dict[str, Any]:
        """
        获取市场概况

        Returns:
            市场概况，包括主要指数、涨跌统计、成交额等

        Example:
            >>> client = AgomTradeProClient()
            >>> summary = client.realtime.get_market_summary()
            >>> print(f"上证指数: {summary['sh_index']}")
            >>> print(f"上涨家数: {summary['up_count']}")
        """
        return self._get("market-summary/")

    def get_market_overview(self) -> dict[str, Any]:
        """
        获取市场概况兼容别名。

        返回值在 `get_market_summary()` 基础上补充统一字段，便于旧示例继续运行。
        """
        summary = self.get_market_summary()
        indices = []
        for code_key, name in (
            ("sh_index", "Shanghai Index"),
            ("sz_index", "Shenzhen Index"),
            ("cyb_index", "ChiNext Index"),
        ):
            value = summary.get(code_key)
            if value is None:
                continue
            indices.append(
                {
                    "name": name,
                    "value": value,
                    "change": summary.get(f"{code_key}_change"),
                    "change_percent": summary.get(f"{code_key}_change_pct"),
                }
            )

        return {
            **summary,
            "market_status": "open" if summary.get("success") else "unavailable",
            "last_update": summary.get("timestamp"),
            "indices": indices,
            "market_summary": {
                "advancing": summary.get("up_count", 0),
                "declining": summary.get("down_count", 0),
                "unchanged": summary.get("flat_count", 0),
                "limit_up": summary.get("limit_up_count", 0),
                "limit_down": summary.get("limit_down_count", 0),
            },
            "turnover": summary.get("total_value"),
        }

    def get_sector_performance(self) -> list[dict[str, Any]]:
        """
        获取板块实时表现

        Returns:
            板块表现列表

        Example:
            >>> client = AgomTradeProClient()
            >>> sectors = client.realtime.get_sector_performance()
            >>> for sector in sectors:
            ...     print(f"{sector['name']}: {sector['change_percent']:.2%}")
        """
        response = self._get("sector-performance/")
        results = response.get("results", response)
        return results

    def get_top_movers(
        self,
        direction: str = "up",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        获取涨幅榜/跌幅榜

        Args:
            direction: 方向（up/down）
            limit: 返回数量限制

        Returns:
            涨跌幅榜列表

        Example:
            >>> client = AgomTradeProClient()
            >>> top_gainers = client.realtime.get_top_movers(direction="up")
            >>> for stock in top_gainers:
            ...     print(f"{stock['code']}: {stock['change_percent']:.2%}")
        """
        prices = self._get_live_snapshot_prices()
        reverse = direction != "down"
        sorted_prices = sorted(
            prices,
            key=lambda item: self._numeric(item.get("price_change_percent")),
            reverse=reverse,
        )
        return sorted_prices[:limit]

    def get_top_gainers(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取涨幅榜兼容方法。"""
        return self.get_top_movers(direction="up", limit=limit)

    def get_top_losers(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取跌幅榜兼容方法。"""
        return self.get_top_movers(direction="down", limit=limit)

    def get_most_active(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取成交量最活跃资产。"""
        prices = self._get_live_snapshot_prices()
        sorted_prices = sorted(
            prices,
            key=lambda item: self._numeric(item.get("volume")),
            reverse=True,
        )
        return sorted_prices[:limit]

    def subscribe_price(
        self,
        asset_code: str,
    ) -> dict[str, Any]:
        """
        订阅实时价格推送

        Args:
            asset_code: 资产代码

        Returns:
            订阅信息

        Note:
            实时推送需要使用 WebSocket 连接
        """
        data = {"asset_code": asset_code}
        return self._post("subscriptions/", json=data)

    def unsubscribe_price(
        self,
        asset_code: str,
    ) -> None:
        """
        取消订阅实时价格推送

        Args:
            asset_code: 资产代码
        """
        data = {"asset_code": asset_code}
        self._post("subscriptions/unsubscribe/", json=data)

    def get_subscriptions(self) -> list[dict[str, Any]]:
        """
        获取当前订阅列表

        Returns:
            订阅列表

        Example:
            >>> client = AgomTradeProClient()
            >>> subs = client.realtime.get_subscriptions()
            >>> for sub in subs:
            ...     print(f"{sub['asset_code']}: {sub['status']}")
        """
        response = self._get("subscriptions/")
        results = response.get("results", response)
        return results

    def _get_live_snapshot_prices(self) -> list[dict[str, Any]]:
        snapshot = self._post("prices/")
        prices = snapshot.get("prices", snapshot)
        return [self._normalize_price_payload(item) for item in prices]

    def _normalize_price_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        price = payload.get("current_price", payload.get("price"))
        change = payload.get("price_change", payload.get("change"))
        change_pct = payload.get(
            "price_change_percent",
            payload.get("change_percent", payload.get("change_pct")),
        )
        timestamp = payload.get("updated_at", payload.get("timestamp"))

        normalized = dict(payload)
        normalized.setdefault("current_price", price)
        normalized.setdefault("price_change", change)
        normalized.setdefault("price_change_percent", change_pct)
        normalized.setdefault("updated_at", timestamp)

        # 保留后端字段别名，方便旧代码和新代码同时工作。
        normalized.setdefault("price", price)
        normalized.setdefault("change", change)
        normalized.setdefault("change_pct", change_pct)
        normalized.setdefault("timestamp", timestamp)
        return normalized

    def _numeric(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
