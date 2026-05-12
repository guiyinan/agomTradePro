"""Application-level composition helpers for prompt runtime consumers."""

from __future__ import annotations

from typing import Any

from .agent_runtime import AgentRuntime
from .context_builders import (
    AssetPoolContextProvider,
    ContextBundleBuilder,
    MacroContextProvider,
    PortfolioContextProvider,
    RegimeContextProvider,
    SignalContextProvider,
)
from .repository_provider import (
    build_macro_adapter,
    build_regime_adapter,
    create_builtin_tools,
    get_execution_log_repository,
)
from .repository_provider import (
    get_chain_repository as get_default_chain_repository,
)
from .repository_provider import (
    get_prompt_repository as get_default_prompt_repository,
)
from .tool_execution import create_agent_tool_registry
from .trace_logging import AgentExecutionLogger


def build_terminal_agent_runtime(ai_client_factory: Any) -> AgentRuntime:
    """Build the default AgentRuntime for terminal prompt commands."""

    macro_adapter = build_macro_adapter()
    regime_adapter = build_regime_adapter()

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

    macro_adapter = build_macro_adapter()
    regime_adapter = build_regime_adapter()

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

    registry = create_builtin_tools(build_macro_adapter(), build_regime_adapter())
    return registry.execute(tool_name, params)


def get_prompt_repository() -> Any:
    """Backward-compatible prompt repository accessor for existing consumers."""

    return get_default_prompt_repository()


def get_chain_repository() -> Any:
    """Backward-compatible chain repository accessor for existing consumers."""

    return get_default_chain_repository()
