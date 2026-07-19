"""Market thermometer config, user override, and snapshot persistence."""

from __future__ import annotations

from datetime import date, timedelta

from apps.data_center.domain.entities import (
    MarketThermometerConfig,
    MarketThermometerSnapshot,
    MarketThermometerUserOverride,
)
from apps.data_center.infrastructure.models import (
    MarketThermometerConfigModel,
    MarketThermometerSnapshotModel,
    MarketThermometerUserOverrideModel,
)


class MarketThermometerConfigRepository:
    """Persists and retrieves singleton market thermometer config."""

    def load(self) -> MarketThermometerConfig:
        return MarketThermometerConfigModel.load().to_domain()

    def save(self, config: MarketThermometerConfig) -> MarketThermometerConfig:
        model = MarketThermometerConfigModel.load()
        model.short_window = config.short_window
        model.medium_window = config.medium_window
        model.long_window = config.long_window
        model.monthly_long_window = config.monthly_long_window
        model.daily_stale_days = config.daily_stale_days
        model.monthly_stale_days = config.monthly_stale_days
        model.min_valid_components = config.min_valid_components
        model.component_weights = dict(config.component_weights)
        model.warm_threshold = config.thresholds.warm_threshold
        model.hot_threshold = config.thresholds.hot_threshold
        model.overheat_threshold = config.thresholds.overheat_threshold
        model.extreme_threshold = config.thresholds.extreme_threshold
        model.save()
        return model.to_domain()


class MarketThermometerUserOverrideRepository:
    """Persists per-user market thermometer threshold overrides."""

    def get_by_user_id(self, user_id: int) -> MarketThermometerUserOverride | None:
        try:
            return MarketThermometerUserOverrideModel.objects.get(user_id=user_id).to_domain()
        except MarketThermometerUserOverrideModel.DoesNotExist:
            return None

    def save(
        self,
        override: MarketThermometerUserOverride,
    ) -> MarketThermometerUserOverride:
        model, _ = MarketThermometerUserOverrideModel.objects.update_or_create(
            user_id=override.user_id,
            defaults={
                "warm_threshold": override.thresholds.warm_threshold,
                "hot_threshold": override.thresholds.hot_threshold,
                "overheat_threshold": override.thresholds.overheat_threshold,
                "extreme_threshold": override.thresholds.extreme_threshold,
            },
        )
        return model.to_domain()

    def delete(self, user_id: int) -> None:
        MarketThermometerUserOverrideModel.objects.filter(user_id=user_id).delete()


class MarketThermometerSnapshotRepository:
    """Persists and retrieves market thermometer snapshots."""

    def get_latest(self) -> MarketThermometerSnapshot | None:
        model = MarketThermometerSnapshotModel.objects.order_by("-observed_at").first()
        return model.to_domain() if model is not None else None

    def get_by_date(self, observed_at: date) -> MarketThermometerSnapshot | None:
        try:
            return MarketThermometerSnapshotModel.objects.get(observed_at=observed_at).to_domain()
        except MarketThermometerSnapshotModel.DoesNotExist:
            return None

    def list_history(self, days: int = 90) -> list[MarketThermometerSnapshot]:
        cutoff = date.today() if days <= 0 else date.today() - timedelta(days=days)
        rows = MarketThermometerSnapshotModel.objects.filter(observed_at__gte=cutoff)
        return [row.to_domain() for row in rows.order_by("-observed_at")]

    def save(self, snapshot: MarketThermometerSnapshot) -> MarketThermometerSnapshot:
        model, _ = MarketThermometerSnapshotModel.objects.update_or_create(
            observed_at=snapshot.observed_at,
            defaults={
                "score": snapshot.score,
                "band": snapshot.band,
                "change_5d": snapshot.change_5d,
                "change_20d": snapshot.change_20d,
                "components": [component.to_dict() for component in snapshot.components],
                "trigger_reasons": list(snapshot.trigger_reasons),
                "stale_components": list(snapshot.stale_components),
                "missing_components": list(snapshot.missing_components),
                "valid_component_count": snapshot.valid_component_count,
                "data_source": snapshot.data_source,
                "must_not_use_for_decision": snapshot.must_not_use_for_decision,
                "blocked_reason": snapshot.blocked_reason,
                "calculated_at": snapshot.calculated_at,
            },
        )
        return model.to_domain()
