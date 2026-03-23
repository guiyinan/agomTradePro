"""
Tool Execution Service.

为 AgentRuntime 提供工具注册、白名单管理和执行记录。
在现有 FunctionRegistry 基础上增加权限域、成本级别和标准化错误处理。
"""

import logging
from typing import Any, Dict, List, Optional

from ..infrastructure.adapters.function_registry import (
    FunctionRegistry,
    ToolDefinition,
    create_builtin_tools,
)

logger = logging.getLogger(__name__)


# 工具权限域
TOOL_PERMISSION_READONLY = "readonly"
TOOL_PERMISSION_WRITE = "write"

# 工具成本级别
TOOL_COST_LOW = "low"       # 本地计算或缓存读取
TOOL_COST_MEDIUM = "medium"  # 数据库查询
TOOL_COST_HIGH = "high"     # 外部 API 调用


class ToolMetadata:
    """工具元数据，扩展 ToolDefinition 的元信息。"""

    def __init__(
        self,
        permission: str = TOOL_PERMISSION_READONLY,
        cost_level: str = TOOL_COST_LOW,
        max_calls_per_session: int = 10,
    ):
        self.permission = permission
        self.cost_level = cost_level
        self.max_calls_per_session = max_calls_per_session


class EnhancedToolRegistry:
    """
    增强型工具注册表。

    在 FunctionRegistry 基础上增加：
    - 工具元数据（权限、成本级别）
    - 白名单过滤
    - 每会话调用次数限制
    """

    def __init__(self, base_registry: FunctionRegistry | None = None):
        self._registry = base_registry or FunctionRegistry()
        self._metadata: dict[str, ToolMetadata] = {}

    @property
    def registry(self) -> FunctionRegistry:
        """底层注册表。"""
        return self._registry

    def register(
        self,
        tool: ToolDefinition,
        metadata: ToolMetadata | None = None,
    ) -> None:
        """注册工具及其元数据。"""
        self._registry.register(tool)
        self._metadata[tool.name] = metadata or ToolMetadata()

    def get_readonly_tools(self) -> list[str]:
        """返回所有只读工具名称。"""
        return [
            name for name, meta in self._metadata.items()
            if meta.permission == TOOL_PERMISSION_READONLY
        ]

    def get_tools_schema(
        self, whitelist: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """获取 OpenAI 格式的工具 schema（按白名单过滤）。"""
        all_tools = self._registry.to_openai_format()
        if whitelist is None:
            return all_tools
        whiteset = set(whitelist)
        return [
            t for t in all_tools
            if t.get("function", {}).get("name") in whiteset
        ]

    def get_tool_names(self) -> list[str]:
        return self._registry.get_tool_names()


def create_agent_tool_registry(
    macro_adapter: Any = None,
    regime_adapter: Any = None,
    portfolio_provider: Any = None,
    signal_provider: Any = None,
    asset_pool_provider: Any = None,
) -> FunctionRegistry:
    """
    创建 Agent Runtime 使用的工具注册表。

    在内置工具基础上增加投资组合和信号相关工具。

    Args:
        macro_adapter: 宏观数据适配器
        regime_adapter: Regime 数据适配器
        portfolio_provider: 投资组合数据提供者
        signal_provider: 信号数据提供者
        asset_pool_provider: 资产池数据提供者

    Returns:
        配置完成的 FunctionRegistry
    """
    # 先创建基础内置工具
    if macro_adapter and regime_adapter:
        registry = create_builtin_tools(macro_adapter, regime_adapter)
    else:
        registry = FunctionRegistry()

    # 添加投资组合工具
    if portfolio_provider:
        registry.register(ToolDefinition(
            name="get_portfolio_snapshot",
            description="获取投资组合快照，包括总资产、持仓数量、现金等概要信息",
            parameters={
                "type": "object",
                "properties": {
                    "portfolio_id": {
                        "type": "integer",
                        "description": "投资组合ID"
                    }
                },
                "required": ["portfolio_id"]
            },
            function=lambda **kwargs: _safe_call(
                portfolio_provider, "get_portfolio_snapshot",
                kwargs.get("portfolio_id")
            ),
        ))

        registry.register(ToolDefinition(
            name="get_portfolio_positions",
            description="获取投资组合的所有持仓明细",
            parameters={
                "type": "object",
                "properties": {
                    "portfolio_id": {
                        "type": "integer",
                        "description": "投资组合ID"
                    }
                },
                "required": ["portfolio_id"]
            },
            function=lambda **kwargs: _safe_call(
                portfolio_provider, "get_positions",
                kwargs.get("portfolio_id")
            ),
        ))

        registry.register(ToolDefinition(
            name="get_portfolio_cash",
            description="获取投资组合的可用现金",
            parameters={
                "type": "object",
                "properties": {
                    "portfolio_id": {
                        "type": "integer",
                        "description": "投资组合ID"
                    }
                },
                "required": ["portfolio_id"]
            },
            function=lambda **kwargs: _safe_call(
                portfolio_provider, "get_cash",
                kwargs.get("portfolio_id")
            ),
        ))

    # 添加信号工具
    if signal_provider:
        registry.register(ToolDefinition(
            name="get_valid_signals",
            description="获取当前所有有效的投资信号",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            function=lambda **kwargs: _safe_call(
                signal_provider, "get_valid_signals"
            ),
        ))

    # 添加资产池工具
    if asset_pool_provider:
        registry.register(ToolDefinition(
            name="get_asset_pool",
            description="获取当前可投资的资产池列表",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            function=lambda **kwargs: _safe_call(
                asset_pool_provider, "get_investable_assets"
            ),
        ))

    return registry


def _safe_call(provider: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """安全调用 provider 方法，统一错误处理。"""
    fn = getattr(provider, method_name, None)
    if fn is None:
        return {"error": f"Provider does not support method: {method_name}"}
    try:
        result = fn(*args, **kwargs)
        # 确保结果可 JSON 序列化
        if hasattr(result, "__dict__"):
            return result.__dict__
        return result
    except Exception as exc:
        logger.warning("Tool call %s failed: %s", method_name, exc)
        return {"error": str(exc)}
