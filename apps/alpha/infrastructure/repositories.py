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


class AlphaScoreCacheRepository:
    """ORM-backed access to Alpha score cache rows."""

    def get_latest_qlib_cache(
        self,
        *,
        universe_id: str,
        model_artifact_hash: str,
        scope_hash: str | None = None,
    ) -> Any | None:
        from .models import AlphaScoreCacheModel

        queryset = AlphaScoreCacheModel._default_manager.filter(
            universe_id=universe_id,
            provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        ).exclude(scores=[])
        if scope_hash is not None:
            queryset = queryset.filter(scope_hash=scope_hash)

        latest_cache = queryset.filter(
            model_artifact_hash=model_artifact_hash,
        ).order_by("-intended_trade_date", "-created_at").first()
        if latest_cache is not None:
            return latest_cache
        return queryset.order_by("-intended_trade_date", "-created_at").first()

    def find_broader_qlib_cache_for_scope(
        self,
        *,
        trade_date: date,
        model_artifact_hash: str,
        scope_hash: str | None,
        allowed_codes: set[str],
        limit: int = 30,
    ) -> tuple[Any, list[dict[str, Any]]] | None:
        from .models import AlphaScoreCacheModel

        if not allowed_codes:
            return None

        querysets = [
            AlphaScoreCacheModel._default_manager.filter(
                provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
                intended_trade_date__lte=trade_date,
                model_artifact_hash=model_artifact_hash,
            ).exclude(scores=[]),
            AlphaScoreCacheModel._default_manager.filter(
                provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
                intended_trade_date__lte=trade_date,
            ).exclude(scores=[]),
        ]

        for queryset in querysets:
            broader_caches = queryset.exclude(scope_hash=scope_hash).order_by(
                "-asof_date", "-intended_trade_date", "-created_at"
            )[:limit]
            for broader_cache in broader_caches:
                filtered_scores: list[dict[str, Any]] = []
                for raw_score in broader_cache.scores or []:
                    score_item = dict(raw_score)
                    normalized_code = normalize_stock_code(score_item.get("code"))
                    if normalized_code and normalized_code in allowed_codes:
                        score_item["code"] = normalized_code
                        filtered_scores.append(score_item)
                if filtered_scores:
                    return broader_cache, filtered_scores
        return None
