"""Strategy provider bridges for prompt runtime context."""


def build_prompt_strategy_providers():
    """Return strategy-owned providers used by prompt agent runtime."""
    from apps.strategy.application.repository_provider import (
        build_prompt_strategy_providers as _build_prompt_strategy_providers,
    )

    return _build_prompt_strategy_providers()
