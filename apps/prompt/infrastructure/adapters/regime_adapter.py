"""
Regime Data Adapter for Prompt Placeholder Resolution.

This adapter fetches regime data and resolves placeholders
related to regime analysis.
"""

from typing import Dict, Any, Optional
from datetime import date


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
        "GG": "高增长高通胀",
        "GD": "高增长低通胀",
        "GR": "高增长通缩",
        "MG": "中增长高通胀",
        "MD": "中增长低通胀",
        "MR": "中增长通缩",
        "LG": "低增长高通胀",
        "LD": "低增长低通胀",
        "LR": "低增长通缩",
        "SG": "滞胀",
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
        as_of_date: Optional[date] = None
    ) -> Optional[Dict[str, Any]]:
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
        if not self.regime_repository:
            return self._get_mock_regime()

        # 获取最新快照
        snapshot = self.regime_repository.get_latest_snapshot(as_of_date)
        if not snapshot:
            return None

        return {
            "as_of_date": snapshot.as_of_date.isoformat(),
            "dominant_regime": snapshot.dominant_regime,
            "dominant_regime_name": self.REGIME_NAMES.get(
                snapshot.dominant_regime,
                snapshot.dominant_regime
            ),
            "confidence": snapshot.confidence,
            "growth_z": snapshot.growth_momentum_z,
            "inflation_z": snapshot.inflation_momentum_z,
            "distribution": snapshot.distribution,
        }

    def get_regime_distribution(
        self,
        as_of_date: Optional[date] = None
    ) -> Optional[Dict[str, float]]:
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
        as_of_date: Optional[date] = None
    ) -> Optional[Any]:
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

    def _get_mock_regime(self) -> Dict[str, Any]:
        """
        获取模拟Regime数据（用于测试）

        Returns:
            模拟的Regime状态
        """
        return {
            "as_of_date": date.today().isoformat(),
            "dominant_regime": "MD",
            "dominant_regime_name": "中增长低通胀",
            "confidence": 0.65,
            "growth_z": 0.8,
            "inflation_z": -0.3,
            "distribution": {
                "GG": 0.05, "GD": 0.15, "GR": 0.02,
                "MG": 0.08, "MD": 0.45, "MR": 0.03,
                "LG": 0.03, "LD": 0.18, "LR": 0.01,
            }
        }
