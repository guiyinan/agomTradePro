"""Alpha pool resolution services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.alpha.domain.entities import AlphaPoolScope
from apps.alpha.application.repository_provider import AlphaPoolDataRepository

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
    requested_pool_mode: str
    requested_pool_size: int
    scope_fallback: bool = False
    fallback_reason: str = ""


class PortfolioAlphaPoolResolver:
    """Resolve the homepage Alpha pool from the current portfolio context."""

    DEFAULT_MARKET = "CN"
    DEFAULT_POOL_MODE = ALPHA_POOL_MODE_STRICT_VALUATION
    MIN_ALPHA_POOL_SIZE = 10

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
        requested_pool_mode = self._resolve_pool_mode(pool_mode)
        requested_scope = self._build_scope(
            portfolio=portfolio,
            market=market,
            trade_date=trade_date,
            pool_mode=requested_pool_mode,
            instrument_codes=self._resolve_instrument_codes(
                market=market,
                trade_date=trade_date,
                pool_mode=requested_pool_mode,
            ),
        )
        selected_scope, fallback_reason = self._select_effective_scope(
            requested_scope=requested_scope,
            portfolio=portfolio,
            market=market,
            trade_date=trade_date,
        )
        return ResolvedAlphaPool(
            portfolio_id=portfolio.id if portfolio else None,
            portfolio_name=portfolio.name if portfolio else "默认组合",
            scope=selected_scope,
            requested_pool_mode=requested_pool_mode,
            requested_pool_size=requested_scope.pool_size,
            scope_fallback=selected_scope.pool_mode != requested_pool_mode,
            fallback_reason=fallback_reason,
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

    def _build_scope(
        self,
        *,
        portfolio,
        market: str,
        trade_date: date,
        pool_mode: str,
        instrument_codes: list[str],
    ) -> AlphaPoolScope:
        portfolio_name = portfolio.name if portfolio else "默认组合"
        display_label = f"{portfolio_name} · {self._get_pool_mode_label(pool_mode)}"
        return AlphaPoolScope(
            pool_type="portfolio_market",
            market=market,
            pool_mode=pool_mode,
            instrument_codes=tuple(instrument_codes),
            selection_reason=self._get_selection_reason(pool_mode),
            trade_date=trade_date,
            display_label=display_label,
            portfolio_id=portfolio.id if portfolio else None,
            portfolio_name=portfolio_name,
        )

    def _select_effective_scope(
        self,
        *,
        requested_scope: AlphaPoolScope,
        portfolio,
        market: str,
        trade_date: date,
    ) -> tuple[AlphaPoolScope, str]:
        if (
            requested_scope.pool_mode == ALPHA_POOL_MODE_MARKET
            or requested_scope.pool_size >= self.MIN_ALPHA_POOL_SIZE
        ):
            return requested_scope, ""

        fallback_scopes: list[AlphaPoolScope] = [requested_scope]
        for fallback_mode in self._iter_fallback_modes(requested_scope.pool_mode):
            candidate_scope = self._build_scope(
                portfolio=portfolio,
                market=market,
                trade_date=trade_date,
                pool_mode=fallback_mode,
                instrument_codes=self._resolve_instrument_codes(
                    market=market,
                    trade_date=trade_date,
                    pool_mode=fallback_mode,
                ),
            )
            fallback_scopes.append(candidate_scope)
            if candidate_scope.pool_size >= self.MIN_ALPHA_POOL_SIZE:
                return candidate_scope, self._build_fallback_reason(
                    requested_scope=requested_scope,
                    selected_scope=candidate_scope,
                )

        non_empty_scopes = [scope for scope in fallback_scopes if scope.pool_size > 0]
        if non_empty_scopes:
            selected_scope = max(non_empty_scopes, key=lambda scope: scope.pool_size)
            if selected_scope.pool_mode != requested_scope.pool_mode:
                return selected_scope, self._build_fallback_reason(
                    requested_scope=requested_scope,
                    selected_scope=selected_scope,
                )

        return requested_scope, ""

    @staticmethod
    def _iter_fallback_modes(requested_pool_mode: str) -> list[str]:
        if requested_pool_mode == ALPHA_POOL_MODE_STRICT_VALUATION:
            return [ALPHA_POOL_MODE_PRICE_COVERED, ALPHA_POOL_MODE_MARKET]
        if requested_pool_mode == ALPHA_POOL_MODE_PRICE_COVERED:
            return [ALPHA_POOL_MODE_MARKET]
        return []

    def _build_fallback_reason(
        self,
        *,
        requested_scope: AlphaPoolScope,
        selected_scope: AlphaPoolScope,
    ) -> str:
        return (
            f"当前 {self._get_pool_mode_label(requested_scope.pool_mode)} 仅覆盖 "
            f"{requested_scope.pool_size} 只股票，已自动切换到 "
            f"{self._get_pool_mode_label(selected_scope.pool_mode)} "
            f"({selected_scope.pool_size} 只) 以完成账户池 Alpha 排序。"
        )

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
