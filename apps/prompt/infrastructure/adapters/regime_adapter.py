"""
Regime Data Adapter for Prompt Placeholder Resolution.

This adapter fetches regime data and resolves placeholders
related to regime analysis.
"""

from datetime import date
from typing import Any, Dict, Optional

from apps.regime.application.current_regime import resolve_current_regime


class RegimeDataAdapter:
    """
    Regime数据适配器

    负责获取Regime判定数据，用于Prompt占位符解析。

    支持的占位符：
    - {{REGIME}} -> 当前Regime状态
    - {{REGIME_DISTRIBUTION}} -> Regime概率分布
    """

    # Regime显示名称映射
    REGIME_NAMES = {
        "Recovery": "复苏",
        "Overheat": "过热",
        "Stagflation": "滞胀",
        "Deflation": "通缩",
        "Unknown": "未知",
    }

    def __init__(self, regime_repository=None):
        """
        初始化Regime适配器

        Args:
            regime_repository: Regime仓储（可选，运行时注入）
        """
        self.regime_repository = regime_repository

    def set_regime_repository(self, repository):
        """设置Regime仓储"""
        self.regime_repository = repository

    def get_current_regime(
        self,
        as_of_date: date | None = None
    ) -> dict[str, Any] | None:
        """
        获取当前Regime状态

        Args:
            as_of_date: 截止日期

        Returns:
            Regime状态数据：
            {
                "dominant_regime": "MD",
                "dominant_regime_name": "中增长低通胀",
                "confidence": 0.65,
                "growth_z": 0.8,
                "inflation_z": -0.3,
                "distribution": {
                    "GG": 0.1, "GD": 0.15, ..., "MD": 0.65, ...
                }
            }
        """
        try:
            current = resolve_current_regime(as_of_date=as_of_date or date.today())
            return {
                "as_of_date": current.observed_at.isoformat(),
                "dominant_regime": current.dominant_regime,
                "dominant_regime_name": self.REGIME_NAMES.get(
                    current.dominant_regime,
                    current.dominant_regime
                ),
                "confidence": current.confidence,
                "growth_z": 0.0,
                "inflation_z": 0.0,
                "distribution": {},
            }
        except Exception:
            return self._get_mock_regime()

    def get_regime_distribution(
        self,
        as_of_date: date | None = None
    ) -> dict[str, float] | None:
        """
        获取Regime概率分布

        Args:
            as_of_date: 截止日期

        Returns:
            概率分布字典
        """
        regime_data = self.get_current_regime(as_of_date)
        if not regime_data:
            return None

        return regime_data.get("distribution")

    def resolve_placeholder(
        self,
        placeholder_name: str,
        as_of_date: date | None = None
    ) -> Any | None:
        """
        解析占位符

        支持的占位符：
        - REGIME -> 当前Regime状态
        - REGIME_DISTRIBUTION -> 概率分布
        - DOMINANT_REGIME -> 主导Regime代码
        - DOMINANT_REGIME_NAME -> 主导Regime名称

        Args:
            placeholder_name: 占位符名称
            as_of_date: 截止日期

        Returns:
            占位符值
        """
        regime_data = self.get_current_regime(as_of_date)
        if not regime_data:
            return None

        if placeholder_name == "REGIME":
            return regime_data
        elif placeholder_name == "REGIME_DISTRIBUTION":
            return regime_data.get("distribution")
        elif placeholder_name == "DOMINANT_REGIME":
            return regime_data.get("dominant_regime")
        elif placeholder_name == "DOMINANT_REGIME_NAME":
            return regime_data.get("dominant_regime_name")
        elif placeholder_name == "GROWTH_Z":
            return regime_data.get("growth_z")
        elif placeholder_name == "INFLATION_Z":
            return regime_data.get("inflation_z")
        elif placeholder_name == "REGIME_CONFIDENCE":
            return regime_data.get("confidence")

        return None

    def _get_mock_regime(self) -> dict[str, Any]:
        """
        获取模拟Regime数据（用于测试）

        Returns:
            模拟的Regime状态
        """
        return {
            "as_of_date": date.today().isoformat(),
            "dominant_regime": "Recovery",
            "dominant_regime_name": "复苏",
            "confidence": 0.65,
            "growth_z": 0.0,
            "inflation_z": 0.0,
            "distribution": {}
        }
