"""Composition helpers for prompt application consumers."""

from __future__ import annotations

from apps.prompt.infrastructure.adapters.function_registry import (
    FunctionRegistry,
    ToolDefinition,
    create_builtin_tools,
)
from apps.prompt.infrastructure.adapters.macro_adapter import FunctionExecutor, MacroDataAdapter
from apps.prompt.infrastructure.adapters.regime_adapter import RegimeDataAdapter
from apps.prompt.infrastructure.providers import (
    DjangoChainRepository,
    DjangoExecutionLogRepository,
    DjangoPromptRepository,
)


def get_prompt_repository() -> DjangoPromptRepository:
    """Return the default prompt repository."""

    return DjangoPromptRepository()


def get_chain_repository() -> DjangoChainRepository:
    """Return the default chain repository."""

    return DjangoChainRepository()


def get_execution_log_repository() -> DjangoExecutionLogRepository:
    """Return the default execution log repository."""

    return DjangoExecutionLogRepository()


def build_macro_adapter() -> MacroDataAdapter:
    """Build the default macro adapter for prompt application use."""

    return MacroDataAdapter()


def build_regime_adapter() -> RegimeDataAdapter:
    """Build the default regime adapter for prompt application use."""

    return RegimeDataAdapter()


def build_function_executor(macro_adapter: MacroDataAdapter) -> FunctionExecutor:
    """Build the default function executor."""

    return FunctionExecutor(macro_adapter)


__all__ = [
    "DjangoChainRepository",
    "DjangoExecutionLogRepository",
    "DjangoPromptRepository",
    "FunctionExecutor",
    "FunctionRegistry",
    "MacroDataAdapter",
    "RegimeDataAdapter",
    "ToolDefinition",
    "build_function_executor",
    "build_macro_adapter",
    "build_regime_adapter",
    "create_builtin_tools",
    "get_chain_repository",
    "get_execution_log_repository",
    "get_prompt_repository",
]
