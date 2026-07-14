"""Realtime alert and subscription persistence models."""

from django.conf import settings
from django.db import models

from apps.realtime.domain.entities import AlertCondition, AlertStatus


class PriceAlertModel(models.Model):
    """Durable owner-scoped price alert."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="realtime_price_alerts",
    )
    asset_code = models.CharField(max_length=32, db_index=True)
    condition = models.CharField(
        max_length=16,
        choices=[(value.value, value.value) for value in AlertCondition],
    )
    threshold = models.DecimalField(max_digits=20, decimal_places=6)
    status = models.CharField(
        max_length=16,
        choices=[(value.value, value.value) for value in AlertStatus],
        default=AlertStatus.ACTIVE.value,
        db_index=True,
    )
    message = models.CharField(max_length=500, blank=True, default="")
    triggered_price = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        blank=True,
        null=True,
    )
    triggered_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "realtime_price_alert"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["owner", "status", "asset_code"],
                name="rt_alert_owner_status_asset",
            ),
        ]


class PriceSubscriptionModel(models.Model):
    """Durable owner-to-asset realtime subscription."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="realtime_price_subscriptions",
    )
    asset_code = models.CharField(max_length=32, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "realtime_price_subscription"
        ordering = ["asset_code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "asset_code"],
                name="realtime_subscription_owner_asset_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["owner", "is_active"],
                name="rt_sub_owner_active_idx",
            ),
        ]


__all__ = ["PriceAlertModel", "PriceSubscriptionModel"]
