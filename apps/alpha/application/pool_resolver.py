"""Alpha pool resolution services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from apps.account.infrastructure.models import PortfolioModel, PositionModel
from apps.alpha.domain.entities import AlphaPoolScope, normalize_stock_code
from apps.equity.infrastructure.models import StockInfoModel, ValuationModel

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

    def _resolve_portfolio(self, *, user_id: int, portfolio_id: int | None) -> PortfolioModel | None:
        queryset = PortfolioModel._default_manager.filter(user_id=user_id)
        if portfolio_id is not None:
            return queryset.filter(id=portfolio_id).first()
        portfolio = queryset.filter(is_active=True).order_by("-updated_at", "-created_at").first()
        if portfolio:
            return portfolio
        return queryset.order_by("-updated_at", "-created_at").first()

    def _resolve_market(self, *, portfolio_id: int | None) -> str:
        if portfolio_id is None:
            return self.DEFAULT_MARKET

        position_codes = list(
            PositionModel._default_manager.filter(portfolio_id=portfolio_id, is_closed=False)
            .values_list("asset_code", flat=True)[:20]
        )
        for raw_code in position_codes:
            code = normalize_stock_code(raw_code)
            if code.endswith(".SH"):
                return self.DEFAULT_MARKET
            if code.endswith(".SZ"):
                return self.DEFAULT_MARKET
            if code.endswith(".BJ"):
                return self.DEFAULT_MARKET
        return self.DEFAULT_MARKET

    def _resolve_instrument_codes(self, *, market: str, trade_date: date) -> list[str]:
        latest_valuation_date = (
            ValuationModel._default_manager.filter(trade_date__lte=trade_date, is_valid=True)
            .order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .first()
        )
        if latest_valuation_date is None:
            logger.warning("PortfolioAlphaPoolResolver: no valuation data found before %s", trade_date)
            return []

        valuation_codes = set(
            normalize_stock_code(code)
            for code in ValuationModel._default_manager.filter(
                trade_date=latest_valuation_date,
                is_valid=True,
            ).values_list("stock_code", flat=True)
        )
        info_rows = StockInfoModel._default_manager.filter(is_active=True).only("stock_code", "market")
        if market == "CN":
            info_rows = info_rows.filter(market__in=["SH", "SZ", "BJ"])

        resolved_codes = [
            normalized
            for normalized in (
                normalize_stock_code(stock.stock_code)
                for stock in info_rows.iterator()
            )
            if normalized and normalized in valuation_codes
        ]
        return sorted(dict.fromkeys(resolved_codes))
