from core.integration.strategy_prompt_providers import (
    build_prompt_strategy_providers,
)


class _FakePortfolioProvider:
    pass


class _FakeSignalProvider:
    pass


class _FakeAssetPoolProvider:
    pass


def test_build_prompt_strategy_providers_uses_strategy_module(monkeypatch):
    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.DjangoPortfolioDataProvider",
        _FakePortfolioProvider,
    )
    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.DjangoSignalProvider",
        _FakeSignalProvider,
    )
    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.DjangoAssetPoolProvider",
        _FakeAssetPoolProvider,
    )

    portfolio_provider, signal_provider, asset_pool_provider = (
        build_prompt_strategy_providers()
    )

    assert isinstance(portfolio_provider, _FakePortfolioProvider)
    assert isinstance(signal_provider, _FakeSignalProvider)
    assert isinstance(asset_pool_provider, _FakeAssetPoolProvider)
