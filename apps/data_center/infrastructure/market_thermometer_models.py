"""ORM persistence models for the market thermometer feature."""

from typing import Any

from django.conf import settings
from django.db import models

from apps.data_center.domain.entities import (
    MarketThermometerComponentScore,
    MarketThermometerConfig,
    MarketThermometerSnapshot,
    MarketThermometerThresholds,
    MarketThermometerUserOverride,
)

from .fact_json_values import (
    _json_bool,
    _optional_json_float,
    _optional_json_nonnegative_int,
    _required_json_float,
)

# ---------------------------------------------------------------------------
# Market thermometer persistence
# ---------------------------------------------------------------------------


class MarketThermometerConfigModel(models.Model):
    """Singleton configuration for market thermometer scoring."""

    _SINGLETON_PK = 1

    short_window = models.PositiveIntegerField(default=5)
    medium_window = models.PositiveIntegerField(default=20)
    long_window = models.PositiveIntegerField(default=252)
    monthly_long_window = models.PositiveIntegerField(default=24)
    daily_stale_days = models.PositiveIntegerField(default=3)
    monthly_stale_days = models.PositiveIntegerField(default=45)
    min_valid_components = models.PositiveIntegerField(default=4)
    component_weights = models.JSONField(
        default=dict,
        blank=True,
        help_text="Component weights keyed by component_key",
    )
    warm_threshold = models.FloatField(default=35.0)
    hot_threshold = models.FloatField(default=60.0)
    overheat_threshold = models.FloatField(default=75.0)
    extreme_threshold = models.FloatField(default=85.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_market_thermometer_config"
        verbose_name = "Market Thermometer Config"
        verbose_name_plural = "Market Thermometer Config"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist the singleton config at primary key 1."""

        self.pk = self._SINGLETON_PK
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "MarketThermometerConfigModel":
        """Return the singleton config, creating it with defaults if absent."""

        obj, _ = cls.objects.get_or_create(
            pk=cls._SINGLETON_PK,
            defaults={
                "component_weights": {
                    "turnover": 0.25,
                    "margin_balance": 0.20,
                    "new_investor_accounts": 0.15,
                    "etf_net_flow": 0.15,
                    "market_news_count": 0.15,
                    "market_news_sentiment": 0.10,
                }
            },
        )
        return obj

    def to_domain(self) -> MarketThermometerConfig:
        """Convert to domain MarketThermometerConfig value object."""

        return MarketThermometerConfig(
            short_window=self.short_window,
            medium_window=self.medium_window,
            long_window=self.long_window,
            monthly_long_window=self.monthly_long_window,
            daily_stale_days=self.daily_stale_days,
            monthly_stale_days=self.monthly_stale_days,
            min_valid_components=self.min_valid_components,
            component_weights=dict(self.component_weights or {}),
            thresholds=MarketThermometerThresholds(
                warm_threshold=float(self.warm_threshold),
                hot_threshold=float(self.hot_threshold),
                overheat_threshold=float(self.overheat_threshold),
                extreme_threshold=float(self.extreme_threshold),
            ),
        )


class MarketThermometerUserOverrideModel(models.Model):
    """Per-user threshold override for market thermometer interpretation."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="market_thermometer_override",
    )
    warm_threshold = models.FloatField(default=35.0)
    hot_threshold = models.FloatField(default=60.0)
    overheat_threshold = models.FloatField(default=75.0)
    extreme_threshold = models.FloatField(default=85.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_market_thermometer_user_override"
        verbose_name = "Market Thermometer User Override"
        verbose_name_plural = "Market Thermometer User Overrides"

    def to_domain(self) -> MarketThermometerUserOverride:
        """Convert to domain MarketThermometerUserOverride value object."""

        return MarketThermometerUserOverride(
            user_id=int(self.user_id),
            thresholds=MarketThermometerThresholds(
                warm_threshold=float(self.warm_threshold),
                hot_threshold=float(self.hot_threshold),
                overheat_threshold=float(self.overheat_threshold),
                extreme_threshold=float(self.extreme_threshold),
            ),
        )


class MarketThermometerSnapshotModel(models.Model):
    """One persisted market thermometer snapshot per observed date."""

    observed_at = models.DateField(unique=True, db_index=True)
    score = models.FloatField()
    band = models.CharField(max_length=20, db_index=True)
    change_5d = models.FloatField(null=True, blank=True)
    change_20d = models.FloatField(null=True, blank=True)
    components = models.JSONField(default=list, blank=True)
    trigger_reasons = models.JSONField(default=list, blank=True)
    stale_components = models.JSONField(default=list, blank=True)
    missing_components = models.JSONField(default=list, blank=True)
    valid_component_count = models.PositiveIntegerField(default=0)
    data_source = models.CharField(max_length=20, default="calculated")
    must_not_use_for_decision = models.BooleanField(default=False)
    blocked_reason = models.TextField(blank=True, default="")
    calculated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_market_thermometer_snapshot"
        ordering = ["-observed_at"]
        verbose_name = "Market Thermometer Snapshot"
        verbose_name_plural = "Market Thermometer Snapshots"
        indexes = [
            models.Index(fields=["band", "observed_at"]),
        ]

    def to_domain(self) -> MarketThermometerSnapshot:
        """Convert to domain MarketThermometerSnapshot value object."""

        components: list[MarketThermometerComponentScore] = []
        for item in self.components or []:
            if isinstance(item, dict):
                components.append(
                    MarketThermometerComponentScore(
                        component_key=str(item.get("component_key", "")),
                        label=str(item.get("label", "")),
                        indicator_code=str(item.get("indicator_code", "")),
                        score=_required_json_float(item.get("score", 0.0), "component.score"),
                        weight=_required_json_float(item.get("weight", 0.0), "component.weight"),
                        current_value=_optional_json_float(
                            item.get("current_value"), "component.current_value"
                        ),
                        unit=str(item.get("unit", "")),
                        growth_score=_optional_json_float(
                            item.get("growth_score"), "component.growth_score"
                        ),
                        percentile_score=_optional_json_float(
                            item.get("percentile_score"), "component.percentile_score"
                        ),
                        sentiment_score=_optional_json_float(
                            item.get("sentiment_score"), "component.sentiment_score"
                        ),
                        positive_ratio_score=_optional_json_float(
                            item.get("positive_ratio_score"),
                            "component.positive_ratio_score",
                        ),
                        is_stale=_json_bool(item.get("is_stale", False), "component.is_stale"),
                        is_missing=_json_bool(
                            item.get("is_missing", False), "component.is_missing"
                        ),
                        age_days=_optional_json_nonnegative_int(
                            item.get("age_days"), "component.age_days"
                        ),
                        reason=str(item.get("reason", "")),
                    )
                )

        return MarketThermometerSnapshot(
            observed_at=self.observed_at,
            score=float(self.score),
            band=self.band,
            change_5d=float(self.change_5d) if self.change_5d is not None else None,
            change_20d=float(self.change_20d) if self.change_20d is not None else None,
            components=components,
            trigger_reasons=[str(item) for item in (self.trigger_reasons or [])],
            stale_components=[str(item) for item in (self.stale_components or [])],
            missing_components=[str(item) for item in (self.missing_components or [])],
            valid_component_count=int(self.valid_component_count),
            data_source=self.data_source,
            must_not_use_for_decision=bool(self.must_not_use_for_decision),
            blocked_reason=self.blocked_reason,
            calculated_at=self.calculated_at,
        )
