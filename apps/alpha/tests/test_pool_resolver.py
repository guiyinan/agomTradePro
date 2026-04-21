from datetime import date
from types import SimpleNamespace

from apps.alpha.application.pool_resolver import (
    ALPHA_POOL_MODE_MARKET,
    ALPHA_POOL_MODE_PRICE_COVERED,
    ALPHA_POOL_MODE_STRICT_VALUATION,
    PortfolioAlphaPoolResolver,
)


def _make_codes(count: int) -> list[str]:
    return [f"{index:06d}.SZ" for index in range(1, count + 1)]


def test_portfolio_alpha_pool_resolver_falls_back_to_wider_account_pool():
    class FakeRepository:
        def resolve_portfolio(self, *, user_id: int, portfolio_id: int | None):
            return SimpleNamespace(id=135, name="默认组合")

        def resolve_market(self, *, portfolio_id: int | None, default_market: str) -> str:
            return "CN"

        def resolve_pool_mode(self, *, default_mode: str) -> str:
            return ALPHA_POOL_MODE_STRICT_VALUATION

        def resolve_instrument_codes(self, *, market: str, trade_date: date, pool_mode: str) -> list[str]:
            if pool_mode == ALPHA_POOL_MODE_STRICT_VALUATION:
                return _make_codes(1)
            if pool_mode == ALPHA_POOL_MODE_PRICE_COVERED:
                return _make_codes(18)
            if pool_mode == ALPHA_POOL_MODE_MARKET:
                return _make_codes(120)
            return []

    resolver = PortfolioAlphaPoolResolver(repository=FakeRepository())

    resolved = resolver.resolve(user_id=7, trade_date=date(2026, 4, 20))

    assert resolved.requested_pool_mode == ALPHA_POOL_MODE_STRICT_VALUATION
    assert resolved.requested_pool_size == 1
    assert resolved.scope.pool_mode == ALPHA_POOL_MODE_PRICE_COVERED
    assert resolved.scope.pool_size == 18
    assert resolved.scope_fallback is True
    assert "仅覆盖 1 只股票" in resolved.fallback_reason


def test_portfolio_alpha_pool_resolver_keeps_requested_pool_when_it_is_large_enough():
    class FakeRepository:
        def resolve_portfolio(self, *, user_id: int, portfolio_id: int | None):
            return SimpleNamespace(id=135, name="默认组合")

        def resolve_market(self, *, portfolio_id: int | None, default_market: str) -> str:
            return "CN"

        def resolve_pool_mode(self, *, default_mode: str) -> str:
            return ALPHA_POOL_MODE_PRICE_COVERED

        def resolve_instrument_codes(self, *, market: str, trade_date: date, pool_mode: str) -> list[str]:
            if pool_mode == ALPHA_POOL_MODE_PRICE_COVERED:
                return _make_codes(16)
            if pool_mode == ALPHA_POOL_MODE_MARKET:
                return _make_codes(90)
            return []

    resolver = PortfolioAlphaPoolResolver(repository=FakeRepository())

    resolved = resolver.resolve(user_id=7, trade_date=date(2026, 4, 20))

    assert resolved.requested_pool_mode == ALPHA_POOL_MODE_PRICE_COVERED
    assert resolved.scope.pool_mode == ALPHA_POOL_MODE_PRICE_COVERED
    assert resolved.scope.pool_size == 16
    assert resolved.scope_fallback is False
    assert resolved.fallback_reason == ""
