"""AgomTradePro SDK - Dashboard 模块。"""

from typing import Any

from .base import BaseModule


class DashboardModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/dashboard")

    def position_detail(self, asset_code: str) -> dict[str, Any]:
        return self._get(f"position/{asset_code}/")

    def positions(self) -> dict[str, Any]:
        return self._get("positions/")

    def allocation(self) -> dict[str, Any]:
        return self._get("allocation/")

    def performance(self) -> dict[str, Any]:
        return self._get("performance/")

    def summary_v1(self) -> dict[str, Any]:
        return self._get("v1/summary/")

    def regime_quadrant_v1(self) -> dict[str, Any]:
        return self._get("v1/regime-quadrant/")

    def equity_curve_v1(self) -> dict[str, Any]:
        return self._get("v1/equity-curve/")

    def signal_status_v1(self) -> dict[str, Any]:
        return self._get("v1/signal-status/")

    def alpha_stocks(self) -> dict[str, Any]:
        return self._get("alpha/stocks/")

    def alpha_provider_status(self) -> dict[str, Any]:
        return self._get("alpha/provider-status/")

    def alpha_coverage(self) -> dict[str, Any]:
        return self._get("alpha/coverage/")

    def alpha_ic_trends(self) -> dict[str, Any]:
        return self._get("alpha/ic-trends/")
