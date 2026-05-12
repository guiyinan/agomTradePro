"""
Function Registry for AI Tool Calling.

This module manages the registry of functions that AI can call
during tool calling mode (OpenAI Function Calling format).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class ToolDefinition:
    """工具定义（用于Function Calling）

    Attributes:
        name: 工具名称
        description: 工具描述
        parameters: 参数定义（JSON Schema格式）
        function: 实际执行的函数
    """
    name: str
    description: str
    parameters: dict[str, Any]
    function: Callable

    def to_openai_format(self) -> dict[str, Any]:
        """转换为OpenAI Function Calling格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


class FunctionRegistry:
    """
    函数注册表

    管理AI可调用的所有函数。
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        """
        注册工具

        Args:
            tool: 工具定义
        """
        self._tools[tool.name] = tool

    def unregister(self, name: str):
        """
        注销工具

        Args:
            name: 工具名称
        """
        if name in self._tools:
            del self._tools[name]

    def get_tool(self, name: str) -> ToolDefinition | None:
        """
        获取工具

        Args:
            name: 工具名称

        Returns:
            工具定义，不存在返回None
        """
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """
        列出所有工具

        Returns:
            工具定义列表
        """
        return list(self._tools.values())

    def execute(self, name: str, parameters: dict[str, Any]) -> Any:
        """
        执行工具

        Args:
            name: 工具名称
            parameters: 参数

        Returns:
            执行结果

        Raises:
            ValueError: 工具不存在
        """
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")

        try:
            return tool.function(**parameters)
        except Exception as e:
            return {
                "error": str(e),
                "tool": name,
                "parameters": parameters
            }

    def to_openai_format(self) -> list[dict[str, Any]]:
        """
        转换为OpenAI Function Calling格式

        Returns:
            OpenAI格式的工具列表
        """
        return [tool.to_openai_format() for tool in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """
        获取所有工具名称

        Returns:
            工具名称列表
        """
        return list(self._tools.keys())


def create_builtin_tools(
    macro_adapter,
    regime_adapter
) -> FunctionRegistry:
    """
    创建内置工具注册表

    Args:
        macro_adapter: 宏观数据适配器
        regime_adapter: Regime数据适配器

    Returns:
        函数注册表
    """
    registry = FunctionRegistry()

    # 工具1：获取宏观指标最新值
    registry.register(ToolDefinition(
        name="get_macro_indicator",
        description="获取指定宏观指标的最新值",
        parameters={
            "type": "object",
            "properties": {
                "indicator_code": {
                    "type": "string",
                    "enum": ["CN_PMI", "CN_CPI", "CN_PPI", "CN_M2",
                            "CN_VALUE_ADDED", "CN_RETAIL_SALES"],
                    "description": "指标代码"
                },
                "as_of_date": {
                    "type": "string",
                    "format": "date",
                    "description": "查询截止日期（可选），格式：YYYY-MM-DD"
                }
            },
            "required": ["indicator_code"]
        },
        function=lambda **kwargs: macro_adapter.get_indicator_value(
            kwargs.get("indicator_code"),
            date.fromisoformat(kwargs["as_of_date"]) if kwargs.get("as_of_date") else None
        )
    ))

    # 工具2：获取宏观指标时序数据
    registry.register(ToolDefinition(
        name="get_macro_series",
        description="获取指定宏观指标的时序数据",
        parameters={
            "type": "object",
            "properties": {
                "indicator_code": {
                    "type": "string",
                    "description": "指标代码"
                },
                "days": {
                    "type": "integer",
                    "default": 30,
                    "description": "获取最近多少天的数据"
                },
                "as_of_date": {
                    "type": "string",
                    "format": "date",
                    "description": "查询截止日期（可选）"
                }
            },
            "required": ["indicator_code"]
        },
        function=lambda **kwargs: macro_adapter.get_indicator_series(
            kwargs.get("indicator_code"),
            **macro_adapter._calculate_series_range(kwargs)
        )
    ))

    # 工具3：获取宏观指标摘要
    registry.register(ToolDefinition(
        name="get_macro_summary",
        description="获取多个宏观指标的摘要信息，包括最新值、变化趋势等",
        parameters={
            "type": "object",
            "properties": {
                "indicators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指标代码列表，默认使用主要指标"
                },
                "as_of_date": {
                    "type": "string",
                    "format": "date",
                    "description": "查询截止日期（可选）"
                }
            },
            "required": []
        },
        function=lambda **kwargs: macro_adapter.get_macro_summary(
            as_of_date=date.fromisoformat(kwargs["as_of_date"]) if kwargs.get("as_of_date") else None,
            indicators=kwargs.get("indicators")
        )
    ))

    # 工具4：获取当前Regime状态
    registry.register(ToolDefinition(
        name="get_regime_status",
        description="获取当前Regime（增长/通胀象限）判定状态",
        parameters={
            "type": "object",
            "properties": {
                "as_of_date": {
                    "type": "string",
                    "format": "date",
                    "description": "查询截止日期（可选）"
                }
            },
            "required": []
        },
        function=lambda **kwargs: regime_adapter.get_current_regime(
            date.fromisoformat(kwargs["as_of_date"]) if kwargs.get("as_of_date") else None
        )
    ))

    # 工具5：获取Regime概率分布
    registry.register(ToolDefinition(
        name="get_regime_distribution",
        description="获取Regime的概率分布数据",
        parameters={
            "type": "object",
            "properties": {
                "as_of_date": {
                    "type": "string",
                    "format": "date",
                    "description": "查询截止日期（可选）"
                }
            },
            "required": []
        },
        function=lambda **kwargs: regime_adapter.get_regime_distribution(
            date.fromisoformat(kwargs["as_of_date"]) if kwargs.get("as_of_date") else None
        )
    ))

    # 工具6：计算指标趋势
    registry.register(ToolDefinition(
        name="calculate_trend",
        description="计算指定宏观指标在一段时间内的趋势",
        parameters={
            "type": "object",
            "properties": {
                "indicator_code": {
                    "type": "string",
                    "description": "指标代码"
                },
                "period": {
                    "type": "string",
                    "enum": ["1m", "3m", "6m", "1y", "2y"],
                    "default": "3m",
                    "description": "统计周期"
                },
                "as_of_date": {
                    "type": "string",
                    "format": "date",
                    "description": "查询截止日期（可选）"
                }
            },
            "required": ["indicator_code"]
        },
        function=lambda **kwargs: {
            "indicator": kwargs.get("indicator_code"),
            "period": kwargs.get("period", "3m"),
            "trend": "up"  # 简化实现，实际应调用趋势计算器
        }
    ))

    return registry


def create_custom_function(
    name: str,
    description: str,
    parameters: dict[str, Any],
    func: Callable
) -> ToolDefinition:
    """
    创建自定义工具

    Args:
        name: 工具名称
        description: 工具描述
        parameters: 参数定义（JSON Schema）
        func: 执行函数

    Returns:
        工具定义
    """
    return ToolDefinition(
        name=name,
        description=description,
        parameters=parameters,
        function=func
    )


# 预定义的工具参数Schema模板
PARAMETER_SCHEMAS = {
    "indicator_code": {
        "type": "string",
        "description": "宏观指标代码",
        "enum": ["CN_PMI", "CN_CPI", "CN_PPI", "CN_M2",
                "CN_VALUE_ADDED", "CN_RETAIL_SALES"]
    },
    "as_of_date": {
        "type": "string",
        "format": "date",
        "description": "查询截止日期（可选），格式：YYYY-MM-DD"
    },
    "period": {
        "type": "string",
        "description": "统计周期",
        "enum": ["1m", "3m", "6m", "1y", "2y"]
    }
}
