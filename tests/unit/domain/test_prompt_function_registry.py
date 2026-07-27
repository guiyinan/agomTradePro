"""Behavior tests for the Prompt Domain function registry."""

from datetime import date
from typing import Any

import pytest

from apps.prompt.domain import (
    PARAMETER_SCHEMAS,
    FunctionRegistry,
    ToolDefinition,
    create_builtin_tools,
    create_custom_function,
)
from apps.prompt.infrastructure.adapters.function_registry import (
    FunctionRegistry as CompatibilityFunctionRegistry,
)


class MacroAdapterFake:
    """Deterministic fake for built-in macro tools."""

    def get_indicator_value(self, code: str, as_of: date | None) -> dict[str, Any]:
        """Return the normalized call arguments."""
        return {"code": code, "as_of": as_of}

    def get_indicator_series(
        self,
        code: str,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Return the normalized series call."""
        return {"code": code, "start": start_date, "end": end_date}

    def get_macro_summary(
        self,
        *,
        as_of_date: date | None,
        indicators: list[str] | None,
    ) -> dict[str, Any]:
        """Return the normalized summary call."""
        return {"as_of": as_of_date, "indicators": indicators}

    def calculate_trend(
        self,
        indicator_code: str,
        period: str = "3m",
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        """Return a deterministic persisted-series trend result."""

        return {"indicator": indicator_code, "period": period, "as_of": as_of_date}


class RegimeAdapterFake:
    """Deterministic fake for built-in Regime tools."""

    def get_current_regime(self, as_of: date | None) -> dict[str, Any]:
        """Return a current Regime payload."""
        return {"regime": "Recovery", "as_of": as_of}

    def get_regime_distribution(self, as_of: date | None) -> dict[str, Any]:
        """Return a deterministic probability distribution."""
        return {"Recovery": 0.7, "as_of": as_of}


def _tool(name: str = "sum") -> ToolDefinition:
    """Create a small deterministic tool."""
    return ToolDefinition(
        name=name,
        description="add two values",
        parameters={
            "type": "object",
            "properties": {"left": {"type": "integer"}, "right": {"type": "integer"}},
        },
        function=lambda left, right: left + right,
    )


def test_registry_lifecycle_and_openai_projection() -> None:
    """Registration, replacement, lookup, removal, and projection stay aligned."""
    registry = FunctionRegistry()
    first = _tool()
    replacement = _tool()

    registry.register(first)
    registry.register(replacement)

    assert registry.get_tool("sum") is replacement
    assert registry.list_tools() == [replacement]
    assert registry.get_tool_names() == ["sum"]
    assert registry.to_openai_format() == [replacement.to_openai_format()]
    assert replacement.to_openai_format()["function"]["parameters"] == replacement.parameters

    registry.unregister("missing")
    registry.unregister("sum")
    assert registry.list_tools() == []


def test_domain_registry_is_the_compatibility_export_and_schemas_are_isolated() -> None:
    """Application and legacy imports share one class without mutable schema leakage."""

    assert CompatibilityFunctionRegistry is FunctionRegistry
    tool = _tool()
    projected = tool.to_openai_format()
    projected["function"]["parameters"]["properties"].clear()
    assert tool.parameters["properties"]


def test_registry_execution_maps_tool_errors_without_raising() -> None:
    """Tool failures become explicit error payloads while unknown tools remain caller errors."""
    registry = FunctionRegistry()
    registry.register(_tool())
    registry.register(
        ToolDefinition(
            name="explode",
            description="raise",
            parameters={},
            function=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError(f"boom:{kwargs.get('token')}")
            ),
        )
    )

    assert registry.execute("sum", {"left": 2, "right": 3}) == 5
    assert registry.execute("explode", {"token": "must-not-leak"}) == {
        "error": "Tool execution failed",
        "error_code": "TOOL_EXECUTION_FAILED",
        "tool": "explode",
        "exception_type": "RuntimeError",
    }
    with pytest.raises(ValueError, match="Tool not found: missing"):
        registry.execute("missing", {})


def test_builtin_tools_forward_dates_ranges_and_defaults() -> None:
    """Built-in tools normalize dates and forward deterministic adapter arguments."""
    registry = create_builtin_tools(MacroAdapterFake(), RegimeAdapterFake())

    assert registry.get_tool_names() == [
        "get_macro_indicator",
        "get_macro_series",
        "get_macro_summary",
        "get_regime_status",
        "get_regime_distribution",
        "calculate_trend",
    ]
    assert registry.execute(
        "get_macro_indicator",
        {"indicator_code": "CN_PMI", "as_of_date": "2024-01-31"},
    ) == {"code": "CN_PMI", "as_of": date(2024, 1, 31)}
    assert registry.execute("get_macro_indicator", {"indicator_code": "CN_CPI"}) == {
        "code": "CN_CPI",
        "as_of": None,
    }
    assert registry.execute(
        "get_macro_series",
        {"indicator_code": "CN_PMI", "days": 9, "as_of_date": "2024-01-10"},
    ) == {
        "code": "CN_PMI",
        "start": date(2024, 1, 1),
        "end": date(2024, 1, 10),
    }
    assert registry.execute(
        "get_macro_summary",
        {"indicators": ["CN_PMI"], "as_of_date": "2024-01-31"},
    ) == {"as_of": date(2024, 1, 31), "indicators": ["CN_PMI"]}
    assert registry.execute("get_regime_status", {}) == {"regime": "Recovery", "as_of": None}
    assert registry.execute(
        "get_regime_distribution",
        {"as_of_date": "2024-01-31"},
    ) == {"Recovery": 0.7, "as_of": date(2024, 1, 31)}
    assert registry.execute("calculate_trend", {"indicator_code": "CN_PMI"}) == {
        "indicator": "CN_PMI",
        "period": "3m",
        "as_of": None,
    }
    assert registry.execute(
        "get_macro_series",
        {"indicator_code": "CN_PMI", "days": 0, "token": "must-not-leak"},
    ) == {
        "error": "Invalid tool parameters",
        "error_code": "INVALID_TOOL_PARAMETERS",
        "tool": "get_macro_series",
    }
    assert registry.execute(
        "get_regime_status",
        {"as_of_date": "not-a-date"},
    ) == {
        "error": "Invalid tool parameters",
        "error_code": "INVALID_TOOL_PARAMETERS",
        "tool": "get_regime_status",
    }


def test_custom_function_and_parameter_schemas_are_reusable() -> None:
    """Custom tools preserve the callable and canonical parameter schemas."""
    custom = create_custom_function(
        "echo",
        "echo value",
        {"type": "object"},
        lambda value: value,
    )

    assert custom.function(value="ok") == "ok"
    assert "enum" not in PARAMETER_SCHEMAS["indicator_code"]
    assert PARAMETER_SCHEMAS["as_of_date"]["format"] == "date"
    assert "3m" in PARAMETER_SCHEMAS["period"]["enum"]
