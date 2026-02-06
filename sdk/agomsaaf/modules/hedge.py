"""
AgomSAAF SDK - Hedge Module

对冲组合模块 SDK 封装。
"""

from datetime import date
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..client import AgomSAAFClient


class HedgeModule:
    """对冲组合模块"""

    def __init__(self, client: "AgomSAAFClient") -> None:
        """初始化模块"""
        self._client = client

    def get_all_pairs(self) -> list[dict[str, Any]]:
        """
        获取所有对冲对

        Returns:
            对冲对列表
        """
        result = self._client.get("hedge/api/pairs/")
        return result.get("results", result) if isinstance(result, dict) else result

    def get_pair_info(self, pair_name: str) -> Optional[dict[str, Any]]:
        """
        获取对冲对详情

        Args:
            pair_name: 对冲对名称

        Returns:
            对冲对详情
        """
        pairs = self.get_all_pairs()
        for pair in pairs:
            if pair.get("name") == pair_name:
                return pair
        return None

    # ========================================================================
    # Correlation Analysis
    # ========================================================================

    def calculate_correlation(
        self,
        asset1: str,
        asset2: str,
        window_days: int = 60
    ) -> dict[str, Any]:
        """
        计算两个资产的相关性

        Args:
            asset1: 资产1代码
            asset2: 资产2代码
            window_days: 计算窗口

        Returns:
            相关性指标
        """
        return self._client.post(
            "hedge/api/actions/calculate-correlation/",
            json={
                "asset1": asset1,
                "asset2": asset2,
                "window_days": window_days,
            }
        )

    def get_correlation_matrix(
        self,
        asset_codes: list[str],
        window_days: int = 60
    ) -> dict[str, Any]:
        """
        获取相关性矩阵

        Args:
            asset_codes: 资产代码列表
            window_days: 计算窗口

        Returns:
            相关性矩阵
        """
        return self._client.post(
            "hedge/api/actions/get-correlation-matrix/",
            json={
                "asset_codes": asset_codes,
                "window_days": window_days,
            }
        )

    # ========================================================================
    # Hedge Ratio
    # ========================================================================

    def calculate_hedge_ratio(self, pair_name: str) -> dict[str, Any]:
        """
        计算对冲比例

        Args:
            pair_name: 对冲对名称

        Returns:
            对冲比例及详情
        """
        return self._client.post(
            "hedge/api/actions/check-hedge-ratio/",
            json={"pair_name": pair_name}
        )

    # ========================================================================
    # Hedge Effectiveness
    # ========================================================================

    def check_effectiveness(self, pair_name: str) -> dict[str, Any]:
        """
        检查对冲有效性

        Args:
            pair_name: 对冲对名称

        Returns:
            有效性评估结果
        """
        # Get pair info to find ID
        pair_info = self.get_pair_info(pair_name)
        if not pair_info:
            return {"error": f"Hedge pair not found: {pair_name}"}

        pair_id = pair_info.get("id")
        return self._client.post(
            f"hedge/api/pairs/{pair_id}/check_effectiveness/",
            json={}
        )

    def get_all_effectiveness(self) -> dict[str, Any]:
        """
        获取所有对冲对的有效性

        Returns:
            所有效率评估结果
        """
        return self._client.get("hedge/api/pairs/all_effectiveness/")

    # ========================================================================
    # Portfolio State
    # ========================================================================

    def get_portfolio_state(self, pair_name: str) -> Optional[dict[str, Any]]:
        """
        获取组合状态

        Args:
            pair_name: 对冲对名称

        Returns:
            组合状态
        """
        holdings = self._client.get("hedge/api/holdings/latest/")
        results = holdings.get("results", holdings) if isinstance(holdings, dict) else holdings

        for holding in results:
            if holding.get("pair_name") == pair_name:
                return holding

        return None

    def update_all_portfolios(self) -> dict[str, Any]:
        """
        更新所有对冲组合

        Returns:
            更新结果
        """
        return self._client.post("hedge/api/holdings/update_all/")

    # ========================================================================
    # Alerts
    # ========================================================================

    def get_alerts(self, days: int = 7) -> list[dict[str, Any]]:
        """
        获取对冲告警

        Args:
            days: 查询天数

        Returns:
            告警列表
        """
        result = self._client.get(f"hedge/api/alerts/active/?days={days}")
        return result.get("results", result) if isinstance(result, dict) else result

    def monitor_alerts(self) -> dict[str, Any]:
        """
        运行对冲监控并生成告警

        Returns:
            生成的告警
        """
        return self._client.post("hedge/api/alerts/monitor/")

    def resolve_alert(self, alert_id: int) -> dict[str, Any]:
        """
        解决告警

        Args:
            alert_id: 告警ID

        Returns:
            操作结果
        """
        return self._client.post(f"hedge/api/alerts/{alert_id}/resolve/")
