"""Application helpers used by prompt interface entrypoints."""

from __future__ import annotations

import logging
from typing import Any

from apps.ai_provider.application.client_provider import get_ai_client_factory
from core.integration.strategy_prompt_providers import (
    build_prompt_strategy_providers,
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
from .use_cases import (
    ExecuteChainUseCase,
    ExecutePromptUseCase,
    GenerateReportUseCase,
    GenerateSignalUseCase,
)
from ..infrastructure.adapters.macro_adapter import MacroDataAdapter
from ..infrastructure.adapters.regime_adapter import RegimeDataAdapter
from ..infrastructure.repositories import (
    DjangoChainRepository,
    DjangoExecutionLogRepository,
    DjangoPromptRepository,
)

logger = logging.getLogger(__name__)


def get_prompt_template_queryset() -> Any:
    """Return the active prompt template queryset for interface consumers."""

    return DjangoPromptRepository().get_active_template_queryset()


def get_chain_config_queryset() -> Any:
    """Return the active chain config queryset for interface consumers."""

    return DjangoChainRepository().get_active_chain_queryset()


def get_execution_log_queryset(
    *,
    template_id: str | None = None,
    chain_id: str | None = None,
    execution_id: str | None = None,
    status_filter: str | None = None,
) -> Any:
    """Return the filtered execution log queryset for interface consumers."""

    return DjangoExecutionLogRepository().get_filtered_queryset(
        template_id=template_id,
        chain_id=chain_id,
        execution_id=execution_id,
        status_filter=status_filter,
    )


def build_execute_prompt_use_case() -> ExecutePromptUseCase:
    """Build the default prompt execution use case graph."""

    return ExecutePromptUseCase(
        prompt_repository=DjangoPromptRepository(),
        execution_log_repository=DjangoExecutionLogRepository(),
        ai_client_factory=get_ai_client_factory(),
        macro_adapter=MacroDataAdapter(),
        regime_adapter=RegimeDataAdapter(),
    )


def create_prompt_template(template: Any) -> Any:
    """Persist a prompt template entity through the default repository."""

    return DjangoPromptRepository().create_template(template)


def update_prompt_template(template_id: int, template: Any) -> Any | None:
    """Update a prompt template entity through the default repository."""

    return DjangoPromptRepository().update_template(template_id, template)


def create_chain_config(chain_config: Any) -> Any:
    """Persist a chain config entity through the default repository."""

    return DjangoChainRepository().create_chain(chain_config)


def update_chain_config(chain_id: int, chain_config: Any) -> Any | None:
    """Update a chain config entity through the default repository."""

    return DjangoChainRepository().update_chain(chain_id, chain_config)


def build_execute_chain_use_case() -> ExecuteChainUseCase:
    """Build the default chain execution use case graph."""

    return ExecuteChainUseCase(
        chain_repository=DjangoChainRepository(),
        prompt_use_case=build_execute_prompt_use_case(),
    )


def build_generate_report_use_case() -> GenerateReportUseCase:
    """Build the default report generation use case."""

    return GenerateReportUseCase(chain_use_case=build_execute_chain_use_case())


def build_generate_signal_use_case() -> GenerateSignalUseCase:
    """Build the default signal generation use case."""

    return GenerateSignalUseCase(chain_use_case=build_execute_chain_use_case())


def build_agent_runtime() -> AgentRuntime:
    """Build the default Agent Runtime with interface-safe dependencies."""

    macro_adapter = MacroDataAdapter()
    regime_adapter = RegimeDataAdapter()

    portfolio_provider = None
    signal_provider = None
    asset_pool_provider = None
    try:
        (
            portfolio_provider,
            signal_provider,
            asset_pool_provider,
        ) = build_prompt_strategy_providers()
    except ImportError:
        logger.warning(
            "Strategy providers not available, portfolio/signal/asset_pool context disabled"
        )

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
    if portfolio_provider:
        context_builder.register_provider(PortfolioContextProvider(portfolio_provider))
    if signal_provider:
        context_builder.register_provider(SignalContextProvider(signal_provider))
    if asset_pool_provider:
        context_builder.register_provider(AssetPoolContextProvider(asset_pool_provider))

    execution_logger = AgentExecutionLogger(
        execution_log_repository=DjangoExecutionLogRepository()
    )

    return AgentRuntime(
        ai_client_factory=get_ai_client_factory(),
        tool_registry=tool_registry,
        context_builder=context_builder,
        execution_logger=execution_logger,
    )
