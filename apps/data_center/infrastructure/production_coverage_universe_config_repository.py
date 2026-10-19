"""Persistence owner for the configured production coverage universe."""

from __future__ import annotations

from apps.data_center.domain.entities import ProductionCoverageUniverseConfig
from apps.data_center.infrastructure.models import ProductionCoverageUniverseConfigModel
from core.exceptions import MissingConfigError


class ProductionCoverageUniverseConfigRepository:
    """Persists and retrieves production coverage universe config."""

    def load(self) -> ProductionCoverageUniverseConfig:
        """Load the singleton without creating or mutating database state."""

        try:
            model = ProductionCoverageUniverseConfigModel.objects.get(pk=1)
        except ProductionCoverageUniverseConfigModel.DoesNotExist as exc:
            raise MissingConfigError(
                "Production coverage universe config is not initialized"
            ) from exc
        return model.to_domain()

    def save(
        self,
        config: ProductionCoverageUniverseConfig,
    ) -> ProductionCoverageUniverseConfig:
        """Create or replace the singleton at this explicit write boundary."""

        model, _ = ProductionCoverageUniverseConfigModel.objects.update_or_create(
            pk=1,
            defaults={
                "universe_id": config.universe_id,
                "asset_type": config.asset_type,
                "exchanges": list(config.exchanges),
                "include_inactive": config.include_inactive,
                "min_active_asset_count": config.min_active_asset_count,
                "min_star_market_count": config.min_star_market_count,
                "min_chinext_count": config.min_chinext_count,
                "min_bse_count": config.min_bse_count,
                "description": config.description,
            },
        )
        return model.to_domain()


__all__ = ["ProductionCoverageUniverseConfigRepository"]
