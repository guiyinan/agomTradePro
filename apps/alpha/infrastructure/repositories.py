"""Alpha infrastructure repositories."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from apps.account.infrastructure.models import PortfolioModel, PositionModel
from apps.alpha.domain.entities import normalize_stock_code
from apps.equity.infrastructure.models import StockInfoModel, ValuationModel

logger = logging.getLogger(__name__)


class AlphaPoolDataRepository:
    """ORM-backed data access for portfolio-driven Alpha pool resolution."""

    def resolve_portfolio(self, *, user_id: int, portfolio_id: int | None) -> Any | None:
        queryset = PortfolioModel._default_manager.filter(user_id=user_id)
        if portfolio_id is not None:
            return queryset.filter(id=portfolio_id).first()
        portfolio = queryset.filter(is_active=True).order_by("-updated_at", "-created_at").first()
        if portfolio:
            return portfolio
        return queryset.order_by("-updated_at", "-created_at").first()

    def resolve_market(self, *, portfolio_id: int | None, default_market: str) -> str:
        if portfolio_id is None:
            return default_market

        position_codes = list(
            PositionModel._default_manager.filter(
                portfolio_id=portfolio_id, is_closed=False
            ).values_list("asset_code", flat=True)[:20]
        )
        for raw_code in position_codes:
            code = normalize_stock_code(raw_code)
            if code.endswith((".SH", ".SZ", ".BJ")):
                return default_market
        return default_market

    def resolve_instrument_codes(self, *, market: str, trade_date: date) -> list[str]:
        latest_valuation_date = (
            ValuationModel._default_manager.filter(trade_date__lte=trade_date, is_valid=True)
            .order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .first()
        )
        if latest_valuation_date is None:
            logger.warning("AlphaPoolDataRepository: no valuation data found before %s", trade_date)
            return []

        valuation_codes = set(
            normalize_stock_code(code)
            for code in ValuationModel._default_manager.filter(
                trade_date=latest_valuation_date,
                is_valid=True,
            ).values_list("stock_code", flat=True)
        )
        info_rows = StockInfoModel._default_manager.filter(is_active=True).only(
            "stock_code", "market"
        )
        if market == "CN":
            info_rows = info_rows.filter(market__in=["SH", "SZ", "BJ"])

        resolved_codes = [
            normalized
            for normalized in (
                normalize_stock_code(stock.stock_code) for stock in info_rows.iterator()
            )
            if normalized and normalized in valuation_codes
        ]
        return sorted(dict.fromkeys(resolved_codes))
