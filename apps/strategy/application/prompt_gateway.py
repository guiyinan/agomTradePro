"""Strategy-owned adapter for Prompt context providers."""

from apps.prompt.application.strategy_gateway import register_prompt_strategy_gateway
from apps.strategy.domain.protocols import (
    AssetPoolProviderProtocol,
    PortfolioDataProviderProtocol,
    SignalProviderProtocol,
)

from .repository_provider import build_prompt_strategy_providers


class StrategyPromptGateway:
    def build_context_providers(
        self,
    ) -> tuple[
        PortfolioDataProviderProtocol,
        SignalProviderProtocol,
        AssetPoolProviderProtocol,
    ]:
        return build_prompt_strategy_providers()


def register_strategy_prompt_gateway() -> None:
    register_prompt_strategy_gateway(StrategyPromptGateway())


__all__ = ["StrategyPromptGateway", "register_strategy_prompt_gateway"]
