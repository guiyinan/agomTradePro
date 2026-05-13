"""AgomTradePro MCP Tools - Config Center tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_config_center_tools(server: FastMCP) -> None:
    @server.tool()
    def list_config_capabilities() -> list[dict[str, Any]]:
        """列出系统当前支持统一发现的配置能力清单。"""
        client = AgomTradeProClient()
        return client.config_center.list_capabilities()

    @server.tool()
    def get_config_center_snapshot() -> dict[str, Any]:
        """获取当前配置中心聚合摘要。"""
        client = AgomTradeProClient()
        return client.config_center.get_snapshot()

    @server.tool()
    def get_qlib_runtime_config() -> dict[str, Any]:
        """读取 Qlib Runtime 配置摘要。"""
        client = AgomTradeProClient()
        return client.config_center.get_qlib_runtime()

    @server.tool()
    def update_qlib_runtime_config(
        enabled: bool | None = None,
        provider_uri: str | None = None,
        region: str | None = None,
        model_root: str | None = None,
        default_universe: str | None = None,
        default_feature_set_id: str | None = None,
        default_label_id: str | None = None,
        train_queue_name: str | None = None,
        infer_queue_name: str | None = None,
        allow_auto_activate: bool | None = None,
        alpha_fixed_provider: str | None = None,
        alpha_pool_mode: str | None = None,
    ) -> dict[str, Any]:
        """更新 Qlib Runtime 配置。需要读写 Token，且调用账号必须是 superuser。"""
        client = AgomTradeProClient()
        payload = {
            key: value
            for key, value in {
                "enabled": enabled,
                "provider_uri": provider_uri,
                "region": region,
                "model_root": model_root,
                "default_universe": default_universe,
                "default_feature_set_id": default_feature_set_id,
                "default_label_id": default_label_id,
                "train_queue_name": train_queue_name,
                "infer_queue_name": infer_queue_name,
                "allow_auto_activate": allow_auto_activate,
                "alpha_fixed_provider": alpha_fixed_provider,
                "alpha_pool_mode": alpha_pool_mode,
            }.items()
            if value is not None
        }
        return client.config_center.update_qlib_runtime(payload)

    @server.tool()
    def list_qlib_training_profiles() -> list[dict[str, Any]]:
        """列出 Qlib 训练模板。"""
        client = AgomTradeProClient()
        return client.config_center.list_qlib_training_profiles()

    @server.tool()
    def save_qlib_training_profile(
        profile_key: str,
        name: str,
        model_name: str,
        model_type: str,
        universe: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        feature_set_id: str = "",
        label_id: str = "",
        learning_rate: float | None = None,
        epochs: int | None = None,
        model_params: dict[str, Any] | None = None,
        extra_train_config: dict[str, Any] | None = None,
        activate_after_train: bool = False,
        is_active: bool = True,
        notes: str = "",
        profile_id: int | None = None,
    ) -> dict[str, Any]:
        """创建或更新 Qlib 训练模板。需要读写 Token，且调用账号必须是 superuser。"""
        client = AgomTradeProClient()
        payload = {
            "profile_key": profile_key,
            "name": name,
            "model_name": model_name,
            "model_type": model_type,
            "universe": universe,
            "start_date": start_date,
            "end_date": end_date,
            "feature_set_id": feature_set_id,
            "label_id": label_id,
            "learning_rate": learning_rate,
            "epochs": epochs,
            "model_params": model_params or {},
            "extra_train_config": extra_train_config or {},
            "activate_after_train": activate_after_train,
            "is_active": is_active,
            "notes": notes,
        }
        if profile_id is not None:
            payload["id"] = profile_id
        return client.config_center.save_qlib_training_profile(payload)

    @server.tool()
    def list_qlib_training_runs(limit: int = 20) -> list[dict[str, Any]]:
        """列出最近的 Qlib 训练任务。"""
        client = AgomTradeProClient()
        return client.config_center.list_qlib_training_runs(limit=limit)

    @server.tool()
    def get_qlib_training_run_detail(run_id: str) -> dict[str, Any]:
        """读取单个 Qlib 训练任务详情。"""
        client = AgomTradeProClient()
        return client.config_center.get_qlib_training_run_detail(run_id)

    @server.tool()
    def trigger_qlib_training(
        model_name: str = "",
        model_type: str = "",
        profile_key: str = "",
        universe: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        feature_set_id: str = "",
        label_id: str = "",
        learning_rate: float | None = None,
        epochs: int | None = None,
        model_params: dict[str, Any] | None = None,
        extra_train_config: dict[str, Any] | None = None,
        activate: bool | None = None,
    ) -> dict[str, Any]:
        """触发一条新的 Qlib 异步训练任务。需要读写 Token，且调用账号必须是 superuser。"""
        client = AgomTradeProClient()
        payload = {
            key: value
            for key, value in {
                "model_name": model_name,
                "model_type": model_type,
                "profile_key": profile_key,
                "universe": universe,
                "start_date": start_date,
                "end_date": end_date,
                "feature_set_id": feature_set_id,
                "label_id": label_id,
                "learning_rate": learning_rate,
                "epochs": epochs,
                "model_params": model_params or {},
                "extra_train_config": extra_train_config or {},
                "activate": activate,
            }.items()
            if value not in (None, "")
        }
        return client.config_center.trigger_qlib_training(payload)

    @server.tool()
    def list_data_center_providers() -> list[dict[str, Any]]:
        """列出数据中台中的 Provider 配置。"""
        client = AgomTradeProClient()
        return client.data_center.list_providers()

    @server.tool()
    def create_data_center_provider(
        name: str,
        source_type: str,
        priority: int = 0,
        is_active: bool = True,
        api_key: str = "",
        http_url: str = "",
        api_endpoint: str = "",
        api_secret: str = "",
        extra_config: dict[str, Any] | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """创建数据中台 Provider 配置。"""
        client = AgomTradeProClient()
        return client.data_center.create_provider(
            {
                "name": name,
                "source_type": source_type,
                "priority": priority,
                "is_active": is_active,
                "api_key": api_key,
                "http_url": http_url,
                "api_endpoint": api_endpoint,
                "api_secret": api_secret,
                "extra_config": extra_config or {},
                "description": description,
            }
        )

    @server.tool()
    def update_data_center_provider(
        provider_id: int,
        name: str | None = None,
        source_type: str | None = None,
        priority: int | None = None,
        is_active: bool | None = None,
        api_key: str | None = None,
        http_url: str | None = None,
        api_endpoint: str | None = None,
        api_secret: str | None = None,
        extra_config: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """更新数据中台 Provider 配置。"""
        client = AgomTradeProClient()
        payload = {
            key: value
            for key, value in {
                "name": name,
                "source_type": source_type,
                "priority": priority,
                "is_active": is_active,
                "api_key": api_key,
                "http_url": http_url,
                "api_endpoint": api_endpoint,
                "api_secret": api_secret,
                "extra_config": extra_config,
                "description": description,
            }.items()
            if value is not None
        }
        return client.data_center.update_provider(provider_id, payload, partial=True)

    @server.tool()
    def test_data_center_provider_connection(provider_id: int) -> dict[str, Any]:
        """执行数据中台 Provider 连通性测试。"""
        client = AgomTradeProClient()
        return client.data_center.test_provider_connection(provider_id)
