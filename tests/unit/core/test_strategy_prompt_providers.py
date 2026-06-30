from core.integration.strategy_prompt_providers import (
    build_prompt_strategy_providers,
)


def test_build_prompt_strategy_providers_uses_strategy_application_provider(monkeypatch):
    expected = (object(), object(), object())
    monkeypatch.setattr(
        "apps.strategy.application.repository_provider.build_prompt_strategy_providers",
        lambda: expected,
    )

    assert build_prompt_strategy_providers() == expected
