"""Market thermometer config and user-override management use cases."""

from __future__ import annotations

from typing import Any

from apps.data_center.domain.entities import (
    MarketThermometerConfig,
    MarketThermometerThresholds,
    MarketThermometerUserOverride,
)
from apps.data_center.domain.protocols import (
    MarketThermometerConfigRepositoryProtocol,
    MarketThermometerUserOverrideRepositoryProtocol,
)


class ManageMarketThermometerConfigUseCase:
    """CRUD facade for system-level market thermometer config."""

    def __init__(self, repo: MarketThermometerConfigRepositoryProtocol) -> None:
        self._repo = repo

    def get(self) -> MarketThermometerConfig:
        """Return the active singleton config."""

        return self._repo.load()

    def update(
        self,
        *,
        short_window: int | None = None,
        medium_window: int | None = None,
        long_window: int | None = None,
        monthly_long_window: int | None = None,
        daily_stale_days: int | None = None,
        monthly_stale_days: int | None = None,
        min_valid_components: int | None = None,
        component_weights: dict[str, float] | None = None,
        thresholds: dict[str, float] | None = None,
    ) -> MarketThermometerConfig:
        """Update the singleton config with partial fields."""

        current = self._repo.load()
        next_thresholds = current.thresholds.to_dict()
        if thresholds:
            next_thresholds.update(thresholds)
        updated = MarketThermometerConfig(
            short_window=short_window or current.short_window,
            medium_window=medium_window or current.medium_window,
            long_window=long_window or current.long_window,
            monthly_long_window=monthly_long_window or current.monthly_long_window,
            daily_stale_days=daily_stale_days or current.daily_stale_days,
            monthly_stale_days=monthly_stale_days or current.monthly_stale_days,
            min_valid_components=min_valid_components or current.min_valid_components,
            component_weights=component_weights or dict(current.component_weights),
            thresholds=MarketThermometerThresholds(**next_thresholds),
        )
        return self._repo.save(updated)


class ManageMarketThermometerUserOverrideUseCase:
    """Manage per-user threshold overrides."""

    def __init__(self, repo: MarketThermometerUserOverrideRepositoryProtocol) -> None:
        self._repo = repo

    def get(self, user_id: int) -> MarketThermometerUserOverride | None:
        """Return the override for one user, if present."""

        return self._repo.get_by_user_id(user_id)

    def upsert(
        self,
        *,
        user_id: int,
        warm_threshold: float | None = None,
        hot_threshold: float | None = None,
        overheat_threshold: float | None = None,
        extreme_threshold: float | None = None,
    ) -> MarketThermometerUserOverride:
        """Create or update one user's threshold override."""

        existing = self._repo.get_by_user_id(user_id)
        base = (
            existing.thresholds.to_dict() if existing else MarketThermometerThresholds().to_dict()
        )
        payload = {
            "warm_threshold": (
                warm_threshold if warm_threshold is not None else base["warm_threshold"]
            ),
            "hot_threshold": hot_threshold if hot_threshold is not None else base["hot_threshold"],
            "overheat_threshold": (
                overheat_threshold if overheat_threshold is not None else base["overheat_threshold"]
            ),
            "extreme_threshold": (
                extreme_threshold if extreme_threshold is not None else base["extreme_threshold"]
            ),
        }
        return self._repo.save(
            MarketThermometerUserOverride(
                user_id=user_id,
                thresholds=MarketThermometerThresholds(**payload),
            )
        )

    def delete(self, user_id: int) -> None:
        """Delete one user's override."""

        self._repo.delete(user_id)


def build_market_thermometer_override_payload(
    *,
    config: MarketThermometerConfig,
    override: MarketThermometerUserOverride | None,
) -> dict[str, Any]:
    """Return combined system + override payload for API consumers."""

    effective = override.thresholds if override is not None else config.thresholds
    return {
        "override": override.thresholds.to_dict() if override is not None else None,
        "effective": effective.to_dict(),
        "source": "user_override" if override is not None else "system",
    }
