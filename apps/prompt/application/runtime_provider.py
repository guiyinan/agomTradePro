"""Application-level composition helpers for prompt runtime consumers."""

from __future__ import annotations

from typing import Any

from apps.prompt.infrastructure.adapters.function_registry import create_builtin_tools
from apps.prompt.infrastructure.adapters.macro_adapter import MacroDataAdapter
from apps.prompt.infrastructure.adapters.regime_adapter import RegimeDataAdapter
from apps.prompt.infrastructure.providers import (
    DjangoChainRepository,
    DjangoExecutionLogRepository,
    DjangoPromptRepository,
)

from .agent_runtime import AgentRuntime
from .context_builders import (
    AssetPoolContextProvider,
    ContextBundleBuilder,
    MacroContextProvider,
    PortfolioContextProvider,
    RegimeContextProvider,
    SignalContextProvider,
)
from .tool_execution import create_agent_tool_registry
from .trace_logging import AgentExecutionLogger


def get_prompt_repository() -> DjangoPromptRepository:
    """Return the default prompt repository."""

    return DjangoPromptRepository()


def get_chain_repository() -> DjangoChainRepository:
    """Return the default chain repository."""

    return DjangoChainRepository()


def get_execution_log_repository() -> DjangoExecutionLogRepository:
    """Return the default execution log repository."""

    return DjangoExecutionLogRepository()


def build_terminal_agent_runtime(ai_client_factory: Any) -> AgentRuntime:
    """Build the default AgentRuntime for terminal prompt commands."""

    macro_adapter = MacroDataAdapter()
    regime_adapter = RegimeDataAdapter()

    tool_registry = create_agent_tool_registry(
        macro_adapter=macro_adapter,
        regime_adapter=regime_adapter,
    )

    context_builder = ContextBundleBuilder()
    context_builder.register_provider(MacroContextProvider(macro_adapter))
    context_builder.register_provider(RegimeContextProvider(regime_adapter))

    execution_logger = AgentExecutionLogger(execution_log_repository=get_execution_log_repository())

    return AgentRuntime(
        ai_client_factory=ai_client_factory,
        tool_registry=tool_registry,
        context_builder=context_builder,
        execution_logger=execution_logger,
    )


def build_strategy_agent_runtime(
    *,
    ai_client_factory: Any,
    portfolio_provider: Any,
    signal_provider: Any,
    asset_pool_provider: Any,
) -> AgentRuntime:
    """Build the AgentRuntime used by AI-driven strategy execution."""

    macro_adapter = MacroDataAdapter()
    regime_adapter = RegimeDataAdapter()

    tool_registry = create_agent_tool_registry(
        macro_adapter=macro_adapter,
        regime_adapter=regime_adapter,
        portfolio_provider=portfolio_provider,
        signal_provider=signal_provider,
        asset_pool_provider=asset_pool_provider,
    )

    context_builder = ContextBundleBuilder()
    context_builder.register_provider(MacroContextProvider(macro_adapter))
    context_builder.register_provider(RegimeContextProvider(regime_adapter))
    context_builder.register_provider(PortfolioContextProvider(portfolio_provider))
    context_builder.register_provider(SignalContextProvider(signal_provider))
    context_builder.register_provider(AssetPoolContextProvider(asset_pool_provider))

    return AgentRuntime(
        ai_client_factory=ai_client_factory,
        tool_registry=tool_registry,
        context_builder=context_builder,
    )


def execute_builtin_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Execute a built-in prompt tool through prompt-owned adapters."""

    registry = create_builtin_tools(MacroDataAdapter(), RegimeDataAdapter())
    return registry.execute(tool_name, params)
