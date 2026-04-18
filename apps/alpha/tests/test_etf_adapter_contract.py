from datetime import date
from types import SimpleNamespace

from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider


def test_etf_provider_accepts_pool_scope_kwargs():
    provider = ETFFallbackProvider()
    pool_scope = SimpleNamespace(universe_id="portfolio-cn")

    assert provider.supports("unsupported", pool_scope=pool_scope) is False

    result = provider.get_stock_scores(
        "unsupported",
        date(2026, 4, 18),
        top_n=5,
        pool_scope=pool_scope,
        user=SimpleNamespace(id=7),
    )

    assert result.success is False
    assert result.status == "unavailable"
