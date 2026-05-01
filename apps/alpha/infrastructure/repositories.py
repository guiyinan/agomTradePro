"""Alpha infrastructure repositories."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from apps.alpha.domain.entities import normalize_stock_code
from apps.data_center.infrastructure.models import AssetMasterModel, PriceBarModel
from apps.equity.infrastructure.models import StockInfoModel, ValuationModel
from core.integration.account_ledger import (
    get_account_portfolio_model,
    get_account_position_model,
)
from core.integration.runtime_settings import get_runtime_alpha_pool_mode

logger = logging.getLogger(__name__)


class AlphaPoolDataRepository:
    """ORM-backed data access for portfolio-driven Alpha pool resolution."""

    def list_active_portfolio_refs(self, *, limit: int | None = 50) -> list[dict[str, Any]]:
        """Return active portfolio identifiers for scheduled scoped Alpha inference."""
        portfolio_model = get_account_portfolio_model()
        queryset = (
            portfolio_model._default_manager.filter(is_active=True)
            .exclude(user_id=None)
            .order_by("-updated_at", "-created_at")
            .values("id", "user_id", "name")
        )
        rows = queryset[:limit] if limit and limit > 0 else queryset
        return [
            {
                "portfolio_id": row["id"],
                "user_id": row["user_id"],
                "name": row.get("name") or "",
            }
            for row in rows
        ]

    def resolve_portfolio(self, *, user_id: int, portfolio_id: int | None) -> Any | None:
        portfolio_model = get_account_portfolio_model()
        queryset = portfolio_model._default_manager.filter(user_id=user_id)
        if portfolio_id is not None:
            return queryset.filter(id=portfolio_id).first()
        portfolio = queryset.filter(is_active=True).order_by("-updated_at", "-created_at").first()
        if portfolio:
            return portfolio
        return queryset.order_by("-updated_at", "-created_at").first()

    def resolve_market(self, *, portfolio_id: int | None, default_market: str) -> str:
        if portfolio_id is None:
            return default_market

        position_model = get_account_position_model()
        position_codes = list(
            position_model._default_manager.filter(
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
            return get_runtime_alpha_pool_mode(default_mode) or default_mode
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

    def get_active_model(self) -> Any | None:
        """Return the active qlib model row, if any."""

        from .models import QlibModelRegistryModel

        return QlibModelRegistryModel._default_manager.filter(is_active=True).first()

    def count_activations_on(self, target_date: date) -> int:
        """Return how many models were activated on one day."""

        from .models import QlibModelRegistryModel

        return QlibModelRegistryModel._default_manager.filter(
            activated_at__date=target_date
        ).count()

    def list_recent_metric_rows(self, days: int) -> list[dict[str, Any]]:
        """Return recent metric rows keyed by created date."""

        from .models import QlibModelRegistryModel

        if days <= 0:
            return []

        cutoff_date = date.today() - timedelta(days=max(days - 1, 0))
        rows = (
            QlibModelRegistryModel._default_manager.filter(
                created_at__date__gte=cutoff_date,
            )
            .order_by("created_at")
            .values("created_at", "ic", "icir", "rank_ic")
        )
        return list(rows)

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

    def create_model_entry(
        self,
        *,
        model_name: str,
        artifact_hash: str,
        model_type: str,
        universe: str,
        train_config: dict[str, Any],
        feature_set_id: str,
        label_id: str,
        data_version: str,
        ic: float | None,
        icir: float | None,
        rank_ic: float | None,
        model_path: str,
        is_active: bool = False,
    ) -> Any:
        """Create one qlib model registry row."""

        from .models import QlibModelRegistryModel

        return QlibModelRegistryModel._default_manager.create(
            model_name=model_name,
            artifact_hash=artifact_hash,
            model_type=model_type,
            universe=universe,
            train_config=train_config,
            feature_set_id=feature_set_id,
            label_id=label_id,
            data_version=data_version,
            ic=ic,
            icir=icir,
            rank_ic=rank_ic,
            model_path=model_path,
            is_active=is_active,
        )

    def activate_model(self, *, artifact_hash: str, activated_by: str) -> Any:
        """Activate one model entry."""

        model = self.get_by_artifact_hash(artifact_hash)
        model.activate(activated_by=activated_by)
        return model


class AlphaScoreCacheRepository:
    """ORM-backed access to Alpha score cache rows."""

    def list_recent_provider_caches(self, *, provider: str, since) -> list[Any]:
        """Return recent cache rows for one provider."""

        from .models import AlphaScoreCacheModel

        return list(
            AlphaScoreCacheModel._default_manager.filter(
                provider_source=provider,
                created_at__gte=since,
            )
        )

    def get_latest_cache_for_universe(self, *, universe_id: str, since) -> Any | None:
        """Return the latest cache row for one universe since a cutoff."""

        from .models import AlphaScoreCacheModel

        return (
            AlphaScoreCacheModel._default_manager.filter(
                universe_id=universe_id,
                created_at__gte=since,
            )
            .order_by("-created_at")
            .first()
        )

    def list_caches_for_model(
        self,
        *,
        model_artifact_hash: str,
        provider_source: str,
    ) -> list[Any]:
        """Return ordered cache rows for one model/provider pair."""

        from .models import AlphaScoreCacheModel

        return list(
            AlphaScoreCacheModel._default_manager.filter(
                model_artifact_hash=model_artifact_hash,
                provider_source=provider_source,
            ).order_by("intended_trade_date")
        )

    def list_today_cache_rows(self, target_date: date) -> list[dict[str, Any]]:
        """Return lightweight cache rows created on one day."""

        from .models import AlphaScoreCacheModel

        return list(
            AlphaScoreCacheModel._default_manager.filter(
                created_at__date=target_date
            ).values("provider_source", "status")
        )

    def list_recent_qlib_caches(self, *, limit: int = 20) -> list[Any]:
        """Return recent qlib cache rows for operational inspection."""

        from .models import AlphaScoreCacheModel

        return list(
            AlphaScoreCacheModel._default_manager.filter(
                provider_source=AlphaScoreCacheModel.PROVIDER_QLIB
            )
            .order_by("-created_at")[:limit]
        )

    def cleanup_before(self, cutoff_date: date) -> int:
        """Delete cache rows older than the cutoff trade date."""

        from .models import AlphaScoreCacheModel

        return AlphaScoreCacheModel._default_manager.filter(
            intended_trade_date__lt=cutoff_date
        ).delete()[0]

    def upsert_qlib_cache(
        self,
        *,
        universe_id: str,
        trade_date: date | None = None,
        intended_trade_date: date | None = None,
        asof_date: date | None = None,
        active_model: Any | None = None,
        model_id: str | None = None,
        model_artifact_hash: str | None = None,
        scores_data: list[dict[str, Any]] | None = None,
        scores: list[dict[str, Any]] | None = None,
        status: str = "available",
        metrics_snapshot: dict[str, Any] | None = None,
        pool_scope: Any | None = None,
        user: Any | None = None,
    ) -> tuple[Any, bool]:
        """Create or update one qlib cache row."""

        from .models import AlphaScoreCacheModel

        resolved_trade_date = trade_date or intended_trade_date
        if resolved_trade_date is None:
            raise ValueError("trade_date or intended_trade_date is required")
        if asof_date is None:
            raise ValueError("asof_date is required")

        resolved_model_id = model_id or getattr(active_model, "model_name", "")
        resolved_artifact_hash = model_artifact_hash or getattr(
            active_model, "artifact_hash", ""
        )
        resolved_scores = scores_data if scores_data is not None else scores
        if resolved_scores is None:
            resolved_scores = []

        return AlphaScoreCacheModel._default_manager.update_or_create(
            user=user,
            universe_id=universe_id,
            intended_trade_date=resolved_trade_date,
            provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
            model_artifact_hash=resolved_artifact_hash,
            defaults={
                "asof_date": asof_date,
                "model_id": resolved_model_id,
                "model_artifact_hash": resolved_artifact_hash,
                "feature_set_id": getattr(active_model, "feature_set_id", None),
                "label_id": getattr(active_model, "label_id", None),
                "data_version": getattr(active_model, "data_version", None),
                "scores": resolved_scores,
                "status": status,
                "metrics_snapshot": metrics_snapshot,
                "user": user,
                "scope_hash": getattr(pool_scope, "scope_hash", None),
                "scope_label": getattr(pool_scope, "display_label", None),
                "scope_metadata": pool_scope.to_dict() if pool_scope else None,
            },
        )

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


class AlphaAlertRepository:
    """ORM-backed access to alpha alert rows."""

    def get_open_alert(self, *, alert_type: str) -> Any | None:
        from .models import AlphaAlertModel

        return AlphaAlertModel._default_manager.filter(
            alert_type=alert_type,
            is_resolved=False,
        ).first()

    def list_recent_alerts(self, *, limit: int = 20) -> list[Any]:
        """Return recent alpha alerts for operational pages."""
        from .models import AlphaAlertModel

        return list(AlphaAlertModel._default_manager.order_by("-created_at")[:limit])

    def create_alert(
        self,
        *,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        from .models import AlphaAlertModel

        return AlphaAlertModel._default_manager.create(
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            metadata=metadata,
        )

    def update_alert(
        self,
        *,
        alert_id: int,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        from .models import AlphaAlertModel

        return AlphaAlertModel._default_manager.filter(id=alert_id).update(
            message=message,
            metadata=metadata,
        ) > 0
