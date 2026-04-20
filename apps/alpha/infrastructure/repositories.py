"""Alpha infrastructure repositories."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from apps.account.infrastructure.models import PortfolioModel, PositionModel
from apps.alpha.domain.entities import normalize_stock_code
from apps.data_center.infrastructure.models import AssetMasterModel, PriceBarModel
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

    def resolve_pool_mode(self, *, default_mode: str) -> str:
        try:
            from apps.account.infrastructure.models import SystemSettingsModel

            return SystemSettingsModel.get_runtime_alpha_pool_mode() or default_mode
        except Exception as exc:
            logger.warning("AlphaPoolDataRepository: failed to resolve pool mode: %s", exc)
            return default_mode

    def resolve_instrument_codes(self, *, market: str, trade_date: date, pool_mode: str) -> list[str]:
        base_codes = self._resolve_market_codes(market=market)
        if not base_codes:
            return []

        if pool_mode == "market":
            return sorted(base_codes)
        if pool_mode == "price_covered":
            price_codes = self._resolve_price_covered_codes(trade_date=trade_date)
            return sorted(base_codes & price_codes)

        valuation_codes = self._resolve_latest_valuation_codes(trade_date=trade_date)
        return sorted(base_codes & valuation_codes)

    def _resolve_market_codes(self, *, market: str) -> set[str]:
        asset_rows = AssetMasterModel._default_manager.filter(
            is_active=True,
            asset_type="stock",
        )
        if market == "CN":
            asset_rows = asset_rows.filter(exchange__in=["SSE", "SZSE", "BSE"])

        asset_codes = {
            normalize_stock_code(code)
            for code in asset_rows.values_list("code", flat=True)
        }
        if asset_codes:
            return {code for code in asset_codes if code}

        info_rows = StockInfoModel._default_manager.filter(is_active=True).only(
            "stock_code", "market"
        )
        if market == "CN":
            info_rows = info_rows.filter(market__in=["SH", "SZ", "BJ"])
        return {
            normalized
            for normalized in (
                normalize_stock_code(stock.stock_code) for stock in info_rows.iterator()
            )
            if normalized
        }

    def _resolve_latest_valuation_codes(self, *, trade_date: date) -> set[str]:
        latest_valuation_date = (
            ValuationModel._default_manager.filter(trade_date__lte=trade_date, is_valid=True)
            .order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .first()
        )
        if latest_valuation_date is None:
            logger.warning("AlphaPoolDataRepository: no valuation data found before %s", trade_date)
            return set()

        return {
            normalize_stock_code(code)
            for code in ValuationModel._default_manager.filter(
                trade_date=latest_valuation_date,
                is_valid=True,
            ).values_list("stock_code", flat=True)
            if normalize_stock_code(code)
        }

    def _resolve_price_covered_codes(self, *, trade_date: date) -> set[str]:
        return {
            normalize_stock_code(code)
            for code in PriceBarModel._default_manager.filter(
                bar_date__lte=trade_date,
            ).values_list("asset_code", flat=True)
            if normalize_stock_code(code)
        }


class QlibModelRegistryRepository:
    """ORM-backed access to Qlib model registry rows."""

    def get_by_artifact_hash(self, artifact_hash: str) -> Any:
        from .models import QlibModelRegistryModel

        return QlibModelRegistryModel._default_manager.get(artifact_hash=artifact_hash)

    def update_metrics(
        self,
        *,
        artifact_hash: str,
        ic: float | None,
        icir: float | None,
        rank_ic: float | None,
    ) -> Any:
        model = self.get_by_artifact_hash(artifact_hash)

        if ic is not None:
            model.ic = ic
        if icir is not None:
            model.icir = icir
        if rank_ic is not None:
            model.rank_ic = rank_ic

        model.save(update_fields=["ic", "icir", "rank_ic"])
        return model
