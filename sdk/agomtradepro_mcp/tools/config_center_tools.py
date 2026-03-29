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
    def list_macro_datasources() -> list[dict[str, Any]]:
        """列出统一财经数据源中台中的宏观数据源配置。"""
        client = AgomTradeProClient()
        return client.macro.list_datasources()

    @server.tool()
    def create_macro_datasource(
        name: str,
        source_type: str,
        priority: int = 0,
        is_active: bool = True,
        api_key: str = "",
        http_url: str = "",
        api_endpoint: str = "",
        api_secret: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        """创建宏观数据源配置，支持为 Tushare 设置自定义 HTTP URL。"""
        client = AgomTradeProClient()
        return client.macro.create_datasource(
            {
                "name": name,
                "source_type": source_type,
                "priority": priority,
                "is_active": is_active,
                "api_key": api_key,
                "http_url": http_url,
                "api_endpoint": api_endpoint,
                "api_secret": api_secret,
                "description": description,
            }
        )

    @server.tool()
    def update_macro_datasource(
        source_id: int,
        name: str | None = None,
        source_type: str | None = None,
        priority: int | None = None,
        is_active: bool | None = None,
        api_key: str | None = None,
        http_url: str | None = None,
        api_endpoint: str | None = None,
        api_secret: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """更新宏观数据源配置，Tushare 第三方代理地址请传 http_url。"""
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
                "description": description,
            }.items()
            if value is not None
        }
        return client.macro.update_datasource(source_id, payload, partial=True)
