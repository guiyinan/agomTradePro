"""Alpha pool resolution services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.alpha.domain.entities import AlphaPoolScope
from apps.alpha.infrastructure.repositories import AlphaPoolDataRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedAlphaPool:
    """Resolved portfolio + pool scope bundle."""

    portfolio_id: int | None
    portfolio_name: str
    scope: AlphaPoolScope


class PortfolioAlphaPoolResolver:
    """Resolve the homepage Alpha pool from the current portfolio context."""

    DEFAULT_MARKET = "CN"
    DEFAULT_LABEL = "CN A-share 可交易池"

    def __init__(self, *, repository: AlphaPoolDataRepository | None = None) -> None:
        self.repository = repository or AlphaPoolDataRepository()

    def resolve(
        self,
        *,
        user_id: int,
        trade_date: date,
        portfolio_id: int | None = None,
    ) -> ResolvedAlphaPool:
        """Resolve the active portfolio and its stock universe."""
        portfolio = self._resolve_portfolio(user_id=user_id, portfolio_id=portfolio_id)
        market = self._resolve_market(portfolio_id=portfolio.id if portfolio else None)
        instrument_codes = self._resolve_instrument_codes(market=market, trade_date=trade_date)
        portfolio_name = portfolio.name if portfolio else "默认组合"
        display_label = f"{portfolio_name} · {self.DEFAULT_LABEL}"
        scope = AlphaPoolScope(
            pool_type="portfolio_market",
            market=market,
            instrument_codes=tuple(instrument_codes),
            selection_reason="当前激活组合所属市场内、具备最新估值/行情覆盖的股票集合",
            trade_date=trade_date,
            display_label=display_label,
            portfolio_id=portfolio.id if portfolio else None,
            portfolio_name=portfolio_name,
        )
        return ResolvedAlphaPool(
            portfolio_id=portfolio.id if portfolio else None,
            portfolio_name=portfolio_name,
            scope=scope,
        )

    def _resolve_portfolio(self, *, user_id: int, portfolio_id: int | None) -> Any | None:
        return self.repository.resolve_portfolio(user_id=user_id, portfolio_id=portfolio_id)

    def _resolve_market(self, *, portfolio_id: int | None) -> str:
        return self.repository.resolve_market(
            portfolio_id=portfolio_id,
            default_market=self.DEFAULT_MARKET,
        )

    def _resolve_instrument_codes(self, *, market: str, trade_date: date) -> list[str]:
        codes = self.repository.resolve_instrument_codes(market=market, trade_date=trade_date)
        if not codes:
            logger.warning("PortfolioAlphaPoolResolver: no instruments resolved for %s", trade_date)
        return codes
