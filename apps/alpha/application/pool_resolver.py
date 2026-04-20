"""Alpha pool resolution services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.alpha.domain.entities import AlphaPoolScope
from apps.alpha.infrastructure.repositories import AlphaPoolDataRepository

logger = logging.getLogger(__name__)

ALPHA_POOL_MODE_STRICT_VALUATION = "strict_valuation"
ALPHA_POOL_MODE_MARKET = "market"
ALPHA_POOL_MODE_PRICE_COVERED = "price_covered"

ALPHA_POOL_MODE_CHOICES = (
    (ALPHA_POOL_MODE_STRICT_VALUATION, "严格估值覆盖池"),
    (ALPHA_POOL_MODE_MARKET, "市场可交易池"),
    (ALPHA_POOL_MODE_PRICE_COVERED, "价格覆盖池"),
)


@dataclass(frozen=True)
class ResolvedAlphaPool:
    """Resolved portfolio + pool scope bundle."""

    portfolio_id: int | None
    portfolio_name: str
    scope: AlphaPoolScope


class PortfolioAlphaPoolResolver:
    """Resolve the homepage Alpha pool from the current portfolio context."""

    DEFAULT_MARKET = "CN"
    DEFAULT_POOL_MODE = ALPHA_POOL_MODE_STRICT_VALUATION

    def __init__(self, *, repository: AlphaPoolDataRepository | None = None) -> None:
        self.repository = repository or AlphaPoolDataRepository()

    def resolve(
        self,
        *,
        user_id: int,
        trade_date: date,
        portfolio_id: int | None = None,
        pool_mode: str | None = None,
    ) -> ResolvedAlphaPool:
        """Resolve the active portfolio and its stock universe."""
        portfolio = self._resolve_portfolio(user_id=user_id, portfolio_id=portfolio_id)
        market = self._resolve_market(portfolio_id=portfolio.id if portfolio else None)
        resolved_pool_mode = self._resolve_pool_mode(pool_mode)
        instrument_codes = self._resolve_instrument_codes(
            market=market,
            trade_date=trade_date,
            pool_mode=resolved_pool_mode,
        )
        portfolio_name = portfolio.name if portfolio else "默认组合"
        display_label = f"{portfolio_name} · {self._get_pool_mode_label(resolved_pool_mode)}"
        scope = AlphaPoolScope(
            pool_type="portfolio_market",
            market=market,
            pool_mode=resolved_pool_mode,
            instrument_codes=tuple(instrument_codes),
            selection_reason=self._get_selection_reason(resolved_pool_mode),
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

    def _resolve_pool_mode(self, pool_mode: str | None) -> str:
        if pool_mode:
            return normalize_alpha_pool_mode(pool_mode)
        return self.repository.resolve_pool_mode(default_mode=self.DEFAULT_POOL_MODE)

    def _resolve_instrument_codes(self, *, market: str, trade_date: date, pool_mode: str) -> list[str]:
        codes = self.repository.resolve_instrument_codes(
            market=market,
            trade_date=trade_date,
            pool_mode=pool_mode,
        )
        if not codes:
            logger.warning("PortfolioAlphaPoolResolver: no instruments resolved for %s", trade_date)
        return codes

    @staticmethod
    def _get_pool_mode_label(pool_mode: str) -> str:
        return dict(ALPHA_POOL_MODE_CHOICES).get(pool_mode, "Alpha 股票池")

    @staticmethod
    def _get_selection_reason(pool_mode: str) -> str:
        if pool_mode == ALPHA_POOL_MODE_MARKET:
            return "当前激活组合所属市场内、资产主数据已登记的股票集合"
        if pool_mode == ALPHA_POOL_MODE_PRICE_COVERED:
            return "当前激活组合所属市场内、本地价格库已有覆盖的股票集合"
        return "当前激活组合所属市场内、具备最新有效估值覆盖的股票集合"


def normalize_alpha_pool_mode(raw_value: str | None) -> str:
    """Normalize Alpha pool mode to a supported value."""
    normalized = str(raw_value or "").strip()
    supported = {value for value, _label in ALPHA_POOL_MODE_CHOICES}
    if normalized in supported:
        return normalized
    return ALPHA_POOL_MODE_STRICT_VALUATION


def get_alpha_pool_mode_choices() -> list[dict[str, str]]:
    """Return Alpha pool mode choices for interface rendering."""
    return [{"value": value, "label": label} for value, label in ALPHA_POOL_MODE_CHOICES]
