"""
AgomSAAF SDK - Rotation Module

资产轮动模块 SDK 封装。
"""

from datetime import date
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..client import AgomSAAFClient


class RotationModule:
    """资产轮动模块"""

    def __init__(self, client: "AgomSAAFClient") -> None:
        """初始化模块"""
        self._client = client

    def get_recommendation(
        self,
        strategy: str = "momentum"
    ) -> dict[str, Any]:
        """
        获取轮动推荐

        Args:
            strategy: 策略类型 (momentum, regime_based, risk_parity)

        Returns:
            推荐配置字典
        """
        return self._client.get(
            "rotation/api/recommendation/",
            params={"strategy": strategy}
        )

    def compare_assets(
        self,
        asset_codes: list[str],
        lookback_days: int = 60
    ) -> dict[str, Any]:
        """
        比较多个资产

        Args:
            asset_codes: 资产代码列表
            lookback_days: 回溯天数

        Returns:
            比较结果字典
        """
        return self._client.post(
            "rotation/api/compare/",
            json={
                "asset_codes": asset_codes,
                "lookback_days": lookback_days,
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
            相关性矩阵字典
        """
        return self._client.post(
            "rotation/api/correlation/",
            json={
                "asset_codes": asset_codes,
                "window_days": window_days,
            }
        )

    def get_all_configs(self) -> list[dict[str, Any]]:
        """
        获取所有轮动配置

        Returns:
            配置列表
        """
        result = self._client.get("rotation/api/configs/")
        return result.get("results", result) if isinstance(result, dict) else result

    def get_config(self, config_id: int) -> dict[str, Any]:
        """
        获取单个配置详情

        Args:
            config_id: 配置ID

        Returns:
            配置详情
        """
        return self._client.get(f"rotation/api/configs/{config_id}/")

    def generate_signal(
        self,
        config_name: str,
        signal_date: Optional[date] = None
    ) -> Optional[dict[str, Any]]:
        """
        生成轮动信号

        Args:
            config_name: 配置名称
            signal_date: 信号日期

        Returns:
            信号详情
        """
        date_str = signal_date.isoformat() if signal_date else None
        return self._client.post(
            "rotation/api/generate-signal/",
            json={
                "config_name": config_name,
                "signal_date": date_str,
            }
        )

    def get_latest_signals(self) -> list[dict[str, Any]]:
        """
        获取最新信号

        Returns:
            信号列表
        """
        return self._client.get("rotation/api/signals/latest/")

    def get_all_assets(self) -> list[dict[str, Any]]:
        """
        获取所有可轮动资产

        Returns:
            资产列表
        """
        return self._client.get("rotation/api/assets/with_prices/")

    def get_asset_info(self, asset_code: str) -> Optional[dict[str, Any]]:
        """
        获取资产详情

        Args:
            asset_code: 资产代码

        Returns:
            资产详情
        """
        return self._client.get(f"rotation/api/assets/{asset_code}/detail/")

    def clear_cache(self) -> dict[str, Any]:
        """清除价格缓存"""
        return self._client.post("rotation/api/clear-cache/")
