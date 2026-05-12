"""
AgomTradePro SDK - Rotation Module

资产轮动模块 SDK 封装。
"""

from datetime import date
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..client import AgomTradeProClient


class RotationModule:
    """资产轮动模块"""

    def __init__(self, client: "AgomTradeProClient") -> None:
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
            "/api/rotation/recommendation/",
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
            "/api/rotation/compare/",
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
            "/api/rotation/correlation/",
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
        result = self._client.get("/api/rotation/configs/")
        return result.get("results", result) if isinstance(result, dict) else result

    def get_config(self, config_id: int) -> dict[str, Any]:
        """
        获取单个配置详情

        Args:
            config_id: 配置ID

        Returns:
            配置详情
        """
        return self._client.get(f"/api/rotation/configs/{config_id}/")

    def generate_signal(
        self,
        config_name: str,
        signal_date: date | None = None
    ) -> dict[str, Any] | None:
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
            "/api/rotation/generate-signal/",
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
        return self._client.get("/api/rotation/signals/latest/")

    def get_all_assets(self) -> list[dict[str, Any]]:
        """
        获取所有可轮动资产

        Returns:
            资产列表
        """
        return self._client.get("/api/rotation/assets/with_prices/")

    def list_assets(self) -> list[dict[str, Any]]:
        """
        获取轮动资产主数据列表

        Returns:
            资产主数据列表
        """
        result = self._client.get("/api/rotation/assets/")
        return result.get("results", result) if isinstance(result, dict) else result

    def get_asset(self, asset_code: str) -> dict[str, Any]:
        """
        获取单个轮动资产主数据

        Args:
            asset_code: 资产代码

        Returns:
            资产详情
        """
        return self._client.get(f"/api/rotation/assets/{asset_code}/")

    def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        创建轮动资产

        Args:
            payload: 资产字段载荷

        Returns:
            创建后的资产详情
        """
        return self._client.post("/api/rotation/assets/", json=payload)

    def update_asset(self, asset_code: str, payload: dict[str, Any], partial: bool = False) -> dict[str, Any]:
        """
        更新轮动资产

        Args:
            asset_code: 资产代码
            payload: 更新内容
            partial: 是否使用 PATCH

        Returns:
            更新后的资产详情
        """
        if partial:
            return self._client.patch(f"/api/rotation/assets/{asset_code}/", json=payload)
        return self._client.put(f"/api/rotation/assets/{asset_code}/", json=payload)

    def delete_asset(self, asset_code: str) -> dict[str, Any]:
        """
        删除轮动资产（默认软删除）

        Args:
            asset_code: 资产代码

        Returns:
            删除响应
        """
        return self._client.delete(f"/api/rotation/assets/{asset_code}/")

    def import_default_assets(self) -> dict[str, Any]:
        """
        导入或恢复默认轮动资产池

        Returns:
            导入结果
        """
        return self._client.post("/api/rotation/assets/import-defaults/", json={})

    def export_assets(self, export_format: str = "json") -> Any:
        """
        导出当前轮动资产池

        Args:
            export_format: json 或 csv

        Returns:
            导出结果
        """
        return self._client.get("/api/rotation/assets/export/", params={"format": export_format})

    def get_asset_info(self, asset_code: str) -> dict[str, Any] | None:
        """
        获取资产详情

        Args:
            asset_code: 资产代码

        Returns:
            资产详情
        """
        return self._client.get(f"/api/rotation/assets/{asset_code}/detail/")

    def clear_cache(self) -> dict[str, Any]:
        """清除价格缓存"""
        return self._client.post("/api/rotation/clear-cache/")

    def list_regimes(self) -> list[dict[str, Any]]:
        """
        获取宏观象限列表

        Returns:
            象限列表，元素形如 {"key": "Overheat", "label": "Overheat"}
        """
        return self._client.get("/api/rotation/regimes/")

    def list_templates(self) -> list[dict[str, Any]]:
        """
        获取轮动模板列表

        Returns:
            模板列表
        """
        result = self._client.get("/api/rotation/templates/")
        return result.get("results", result) if isinstance(result, dict) else result

    def list_account_configs(self) -> list[dict[str, Any]]:
        """
        获取当前用户的账户轮动配置列表

        Returns:
            账户配置列表
        """
        result = self._client.get("/api/rotation/account-configs/")
        return result.get("results", result) if isinstance(result, dict) else result

    def get_account_config(self, config_id: int) -> dict[str, Any]:
        """
        按配置 ID 获取账户轮动配置

        Args:
            config_id: 配置 ID

        Returns:
            单条账户配置详情
        """
        return self._client.get(f"/api/rotation/account-configs/{config_id}/")

    def get_account_config_by_account(self, account_id: int) -> dict[str, Any]:
        """
        按账户 ID 获取轮动配置

        Args:
            account_id: 账户 ID

        Returns:
            单条账户配置详情
        """
        return self._client.get(f"/api/rotation/account-configs/by-account/{account_id}/")

    def create_account_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        新建账户轮动配置

        Args:
            payload: 配置载荷，需包含 account/risk_tolerance/is_enabled/regime_allocations

        Returns:
            新建后的配置详情
        """
        return self._client.post("/api/rotation/account-configs/", json=payload)

    def update_account_config(
        self,
        config_id: int,
        payload: dict[str, Any],
        partial: bool = False,
    ) -> dict[str, Any]:
        """
        更新账户轮动配置

        Args:
            config_id: 配置 ID
            payload: 更新内容
            partial: 是否使用 PATCH 部分更新，默认 False 使用 PUT

        Returns:
            更新后的配置详情
        """
        if partial:
            return self._client.patch(f"/api/rotation/account-configs/{config_id}/", json=payload)
        return self._client.put(f"/api/rotation/account-configs/{config_id}/", json=payload)

    def delete_account_config(self, config_id: int) -> dict[str, Any]:
        """
        删除账户轮动配置

        Args:
            config_id: 配置 ID

        Returns:
            删除响应
        """
        return self._client.delete(f"/api/rotation/account-configs/{config_id}/")

    def apply_template_to_account_config(self, config_id: int, template_key: str) -> dict[str, Any]:
        """
        将预设模板应用到指定账户轮动配置

        Args:
            config_id: 配置 ID
            template_key: 模板 key，如 conservative/moderate/aggressive

        Returns:
            应用后的配置详情
        """
        return self._client.post(
            f"/api/rotation/account-configs/{config_id}/apply-template/",
            json={"template_key": template_key},
        )
