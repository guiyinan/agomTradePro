"""Pure Prompt tool definitions and runtime registry rules."""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol

_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SUPPORTED_TREND_PERIODS = ("1m", "3m", "6m", "1y", "2y", "5y")

ToolCallable = Callable[..., Any]


class MacroToolAdapterProtocol(Protocol):
    """Macro operations required by the built-in Prompt tools."""

    def get_indicator_value(
        self,
        indicator_code: str,
        as_of_date: date | None = None,
    ) -> object:
        """Return one point-in-time indicator value."""

    def get_indicator_series(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> object:
        """Return one point-in-time indicator series."""

    def get_macro_summary(
        self,
        as_of_date: date | None = None,
        indicators: list[str] | None = None,
    ) -> object:
        """Return a macro summary for the requested indicators."""

    def calculate_trend(
        self,
        indicator_code: str,
        period: str = "3m",
        as_of_date: date | None = None,
    ) -> object:
        """Calculate a trend from persisted macro observations."""


class RegimeToolAdapterProtocol(Protocol):
    """Regime operations required by the built-in Prompt tools."""

    def get_current_regime(self, as_of_date: date | None = None) -> object:
        """Return the point-in-time Regime state."""

    def get_regime_distribution(self, as_of_date: date | None = None) -> object:
        """Return the point-in-time Regime distribution."""


class ToolInputError(ValueError):
    """Raised when model-supplied tool arguments violate the declared contract."""


@dataclass(frozen=True)
class ToolDefinition:
    """One callable tool and its OpenAI-compatible JSON schema."""

    name: str
    description: str
    parameters: dict[str, Any]
    function: ToolCallable

    def __post_init__(self) -> None:
        """Validate immutable registry metadata at construction time."""

        if not _TOOL_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("tool name must match [A-Za-z0-9_-] and be at most 64 characters")
        if not isinstance(self.description, str):
            raise ValueError("tool description must be a string")
        if not callable(self.function):
            raise ValueError("tool function must be callable")
        schema = _normalize_parameter_schema(self.parameters)
        object.__setattr__(self, "parameters", schema)

    def to_openai_format(self) -> dict[str, Any]:
        """Return an isolated OpenAI Function Calling definition."""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": deepcopy(self.parameters),
            },
        }


class FunctionRegistry:
    """Register and execute the explicitly exposed Prompt tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register or intentionally replace a named tool definition."""

        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Remove a tool if it exists."""

        self._tools.pop(name, None)

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Return one registered tool."""

        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """Return tool definitions in registration order."""

        return list(self._tools.values())

    def execute(self, name: str, parameters: dict[str, Any]) -> Any:
        """Execute one tool and return a stable, redacted failure payload."""

        tool = self.get_tool(name)
        if tool is None:
            raise ValueError(f"Tool not found: {name}")
        if not isinstance(parameters, dict) or any(not isinstance(key, str) for key in parameters):
            return _tool_error(name, "INVALID_TOOL_PARAMETERS", "Invalid tool parameters")
        try:
            return tool.function(**dict(parameters))
        except ToolInputError:
            return _tool_error(name, "INVALID_TOOL_PARAMETERS", "Invalid tool parameters")
        except Exception as exc:
            return {
                **_tool_error(name, "TOOL_EXECUTION_FAILED", "Tool execution failed"),
                "exception_type": type(exc).__name__,
            }

    def to_openai_format(self) -> list[dict[str, Any]]:
        """Return isolated OpenAI schemas for all registered tools."""

        return [tool.to_openai_format() for tool in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """Return tool names in registration order."""

        return list(self._tools)


def create_builtin_tools(
    macro_adapter: MacroToolAdapterProtocol,
    regime_adapter: RegimeToolAdapterProtocol,
) -> FunctionRegistry:
    """Create the governed read-only macro and Regime tool registry."""

    registry = FunctionRegistry()

    def get_macro_indicator(**kwargs: Any) -> object:
        result = macro_adapter.get_indicator_value(
            _required_string(kwargs, "indicator_code"),
            _optional_date(kwargs, "as_of_date"),
        )
        return (
            result
            if result is not None
            else _tool_error(
                "get_macro_indicator",
                "MACRO_INDICATOR_UNAVAILABLE",
                "Macro indicator unavailable",
            )
        )

    def get_macro_series(**kwargs: Any) -> object:
        end_date = _optional_date(kwargs, "as_of_date") or date.today()
        days = _positive_int(kwargs, "days", default=30, maximum=3650)
        return macro_adapter.get_indicator_series(
            _required_string(kwargs, "indicator_code"),
            start_date=end_date - timedelta(days=days),
            end_date=end_date,
        )

    def get_macro_summary(**kwargs: Any) -> object:
        return macro_adapter.get_macro_summary(
            as_of_date=_optional_date(kwargs, "as_of_date"),
            indicators=_optional_string_list(kwargs, "indicators"),
        )

    def get_regime_status(**kwargs: Any) -> object:
        result = regime_adapter.get_current_regime(_optional_date(kwargs, "as_of_date"))
        return (
            result
            if result is not None
            else _tool_error(
                "get_regime_status",
                "REGIME_UNAVAILABLE",
                "Regime unavailable",
            )
        )

    def get_regime_distribution(**kwargs: Any) -> object:
        result = regime_adapter.get_regime_distribution(_optional_date(kwargs, "as_of_date"))
        return (
            result
            if result is not None
            else _tool_error(
                "get_regime_distribution",
                "REGIME_UNAVAILABLE",
                "Regime unavailable",
            )
        )

    def calculate_trend(**kwargs: Any) -> object:
        period = _optional_string(kwargs, "period", default="3m")
        if period not in _SUPPORTED_TREND_PERIODS:
            raise ToolInputError("unsupported trend period")
        return macro_adapter.calculate_trend(
            _required_string(kwargs, "indicator_code"),
            period,
            _optional_date(kwargs, "as_of_date"),
        )

    registry.register(
        ToolDefinition(
            name="get_macro_indicator",
            description="获取指定宏观指标的最新值",
            parameters=_indicator_schema(include_date=True),
            function=get_macro_indicator,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_macro_series",
            description="获取指定宏观指标的时序数据",
            parameters={
                "type": "object",
                "properties": {
                    "indicator_code": deepcopy(PARAMETER_SCHEMAS["indicator_code"]),
                    "days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 3650,
                        "default": 30,
                        "description": "获取最近多少天的数据",
                    },
                    "as_of_date": deepcopy(PARAMETER_SCHEMAS["as_of_date"]),
                },
                "required": ["indicator_code"],
            },
            function=get_macro_series,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_macro_summary",
            description="获取多个宏观指标的摘要信息，包括最新值、变化趋势等",
            parameters={
                "type": "object",
                "properties": {
                    "indicators": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "由指标目录校验的指标代码列表",
                    },
                    "as_of_date": deepcopy(PARAMETER_SCHEMAS["as_of_date"]),
                },
                "required": [],
            },
            function=get_macro_summary,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_regime_status",
            description="获取当前 Regime（增长/通胀象限）判定状态",
            parameters=_date_only_schema(),
            function=get_regime_status,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_regime_distribution",
            description="获取 Regime 的概率分布数据",
            parameters=_date_only_schema(),
            function=get_regime_distribution,
        )
    )
    registry.register(
        ToolDefinition(
            name="calculate_trend",
            description="基于真实宏观时序数据计算指定指标趋势",
            parameters={
                "type": "object",
                "properties": {
                    "indicator_code": deepcopy(PARAMETER_SCHEMAS["indicator_code"]),
                    "period": deepcopy(PARAMETER_SCHEMAS["period"]),
                    "as_of_date": deepcopy(PARAMETER_SCHEMAS["as_of_date"]),
                },
                "required": ["indicator_code"],
            },
            function=calculate_trend,
        )
    )
    return registry


def create_custom_function(
    name: str,
    description: str,
    parameters: dict[str, Any],
    func: ToolCallable,
) -> ToolDefinition:
    """Create one validated custom tool definition."""

    return ToolDefinition(
        name=name,
        description=description,
        parameters=parameters,
        function=func,
    )


def _normalize_parameter_schema(parameters: object) -> dict[str, Any]:
    if not isinstance(parameters, dict) or any(not isinstance(key, str) for key in parameters):
        raise ValueError("tool parameters must be a string-keyed JSON schema")
    if not parameters:
        return {"type": "object", "properties": {}, "required": []}
    schema = deepcopy(parameters)
    if schema.get("type") != "object":
        raise ValueError("tool parameter schema type must be object")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or any(not isinstance(key, str) for key in properties):
        raise ValueError("tool schema properties must be string-keyed")
    if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
        raise ValueError("tool schema required must be a string list")
    if any(key not in properties for key in required):
        raise ValueError("required tool parameters must exist in properties")
    schema["properties"] = properties
    schema["required"] = required
    return schema


def _required_string(parameters: dict[str, Any], key: str) -> str:
    value = parameters.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ToolInputError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(parameters: dict[str, Any], key: str, *, default: str) -> str:
    value: object = parameters.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_date(parameters: dict[str, Any], key: str) -> date | None:
    value = parameters.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ToolInputError(f"{key} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolInputError(f"{key} must be an ISO date string") from exc


def _positive_int(
    parameters: dict[str, Any],
    key: str,
    *,
    default: int,
    maximum: int,
) -> int:
    value: object = parameters.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ToolInputError(f"{key} must be between 1 and {maximum}")
    return value


def _optional_string_list(parameters: dict[str, Any], key: str) -> list[str] | None:
    value = parameters.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 100:
        raise ToolInputError(f"{key} must be a bounded string list")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 128:
            raise ToolInputError(f"{key} must be a bounded string list")
        normalized.append(item.strip())
    return normalized


def _tool_error(tool_name: str, error_code: str, message: str) -> dict[str, str]:
    return {"error": message, "error_code": error_code, "tool": tool_name}


def _indicator_schema(*, include_date: bool) -> dict[str, Any]:
    properties = {"indicator_code": deepcopy(PARAMETER_SCHEMAS["indicator_code"])}
    if include_date:
        properties["as_of_date"] = deepcopy(PARAMETER_SCHEMAS["as_of_date"])
    return {"type": "object", "properties": properties, "required": ["indicator_code"]}


def _date_only_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"as_of_date": deepcopy(PARAMETER_SCHEMAS["as_of_date"])},
        "required": [],
    }


PARAMETER_SCHEMAS: dict[str, dict[str, Any]] = {
    "indicator_code": {
        "type": "string",
        "description": "由数据中心指标目录校验的宏观指标代码",
    },
    "as_of_date": {
        "type": "string",
        "format": "date",
        "description": "查询截止日期（可选），格式：YYYY-MM-DD",
    },
    "period": {
        "type": "string",
        "description": "统计周期",
        "enum": list(_SUPPORTED_TREND_PERIODS),
        "default": "3m",
    },
}


__all__ = [
    "FunctionRegistry",
    "MacroToolAdapterProtocol",
    "PARAMETER_SCHEMAS",
    "RegimeToolAdapterProtocol",
    "ToolCallable",
    "ToolDefinition",
    "ToolInputError",
    "create_builtin_tools",
    "create_custom_function",
]
