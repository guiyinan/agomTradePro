"""Strategy provider bridges for prompt runtime context."""


def build_prompt_strategy_providers():
    """Return strategy-owned providers used by prompt agent runtime."""
    from apps.strategy.infrastructure.providers import (
        DjangoAssetPoolProvider,
        DjangoPortfolioDataProvider,
        DjangoSignalProvider,
    )

    return (
        DjangoPortfolioDataProvider(),
        DjangoSignalProvider(),
        DjangoAssetPoolProvider(),
    )
