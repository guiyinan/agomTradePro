"""
AgomTradePro SDK - Pulse 脉搏模块

提供 Pulse（宏观脉搏）相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from .base import BaseModule


class PulseModule(BaseModule):
    """
    Pulse 脉搏模块

    提供 Pulse 计算、查询、历史等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Pulse 模块

        Args:
            client: AgomTradePro 客户端实例
        """
        super().__init__(client, "/api/pulse")

    def get_current(self) -> dict[str, Any]:
        """
        获取最新 Pulse 快照

        Returns:
            包含 4 维度脉搏分数、综合评分、Regime 强度等信息的字典

        Raises:
            NotFoundError: 当没有可用的 Pulse 数据时
            ServerError: 当服务器处理失败时

        Example:
            >>> client = AgomTradeProClient()
            >>> pulse = client.pulse.get_current()
            >>> print(f"综合分数: {pulse['composite_score']}")
            >>> print(f"Regime 强度: {pulse['regime_strength']}")
        """
        return self._get("current/")

    def get_history(
        self,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """
        获取 Pulse 历史记录

        Args:
            limit: 返回记录数量限制（默认 30）

        Returns:
            Pulse 快照列表

        Example:
            >>> client = AgomTradeProClient()
            >>> history = client.pulse.get_history(limit=10)
            >>> for snapshot in history:
            ...     print(f"{snapshot['observed_at']}: {snapshot['composite_score']}")
        """
        params: dict[str, Any] = {"limit": limit}
        response = self._get("history/", params=params)
        if isinstance(response, dict):
            return response.get("data", response.get("results", []))
        elif isinstance(response, list):
            return response
        return []

    def calculate(self) -> dict[str, Any]:
        """
        手动触发 Pulse 计算

        仅限 staff 用户调用。

        Returns:
            新计算的 Pulse 快照

        Raises:
            PermissionError: 非 staff 用户调用时
            ServerError: 当计算失败时

        Example:
            >>> client = AgomTradeProClient()
            >>> result = client.pulse.calculate()
            >>> print(f"新计算: {result['composite_score']}")
        """
        return self._post("calculate/")

    def get_navigator(self) -> dict[str, Any]:
        """
        获取 Regime 导航仪完整输出

        包含象限判定、移动方向、资产配置指引、关注指标。

        Returns:
            包含以下字段的字典:
            - regime_name: 象限名称
            - confidence: 置信度
            - movement: 移动方向信息
            - asset_guidance: 资产配置指引
            - watch_indicators: 关注指标列表
            - distribution: 四象限概率分布

        Example:
            >>> client = AgomTradeProClient()
            >>> nav = client.pulse.get_navigator()
            >>> print(f"象限: {nav['regime_name']}")
            >>> print(f"方向: {nav['movement']['direction']}")
        """
        return self._get_from("/api/regime/navigator/")

    def get_action_recommendation(self) -> dict[str, Any]:
        """
        获取 Regime + Pulse 联合行动建议

        返回具体的资产配置百分比、风险预算、推荐板块/风格、对冲建议。

        Returns:
            包含以下字段的字典:
            - asset_weights: 资产配置百分比
            - risk_budget_pct: 风险预算%
            - sectors: 推荐板块
            - styles: 受益风格
            - hedge_recommendation: 对冲建议
            - regime_contribution: Regime 贡献说明
            - pulse_contribution: Pulse 贡献说明

        Example:
            >>> client = AgomTradeProClient()
            >>> action = client.pulse.get_action_recommendation()
            >>> print(f"权益: {action['asset_weights']['equity']:.0%}")
            >>> print(f"风险预算: {action['risk_budget_pct']:.0%}")
        """
        return self._get_from("/api/regime/action/")

    def _get_from(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """从非模块基础路径获取数据"""
        url = f"{self._client.base_url.rstrip('/')}{path}"
        response = self._client._session.get(url, params=params)
        response.raise_for_status()
        return response.json()
