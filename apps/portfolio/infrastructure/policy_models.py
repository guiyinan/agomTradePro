"""Versioned database policy for portfolio-to-order planning."""

from django.core.exceptions import ValidationError
from django.db import models


class PortfolioPlanningPolicyModel(models.Model):
    """Immutable planning thresholds selected through an explicit active version."""

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("retired", "Retired"),
    ]

    policy_id = models.CharField(max_length=64, primary_key=True)
    version = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="draft", db_index=True)
    buy_lot_size = models.PositiveIntegerField()
    fee_rate = models.DecimalField(max_digits=12, decimal_places=8)
    slippage_rate = models.DecimalField(max_digits=12, decimal_places=8)
    min_rebalance_value = models.DecimalField(max_digits=24, decimal_places=4)
    max_asset_weight = models.DecimalField(max_digits=10, decimal_places=8)
    max_volume_participation = models.DecimalField(max_digits=10, decimal_places=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "portfolio_planning_policy"
        constraints = [
            models.UniqueConstraint(
                fields=["status"],
                condition=models.Q(status="active"),
                name="portfolio_one_active_planning_policy",
            ),
            models.CheckConstraint(
                condition=models.Q(buy_lot_size__gt=0),
                name="portfolio_policy_positive_lot",
            ),
            models.CheckConstraint(
                condition=models.Q(fee_rate__gte=0, fee_rate__lt=1),
                name="portfolio_policy_fee_range",
            ),
            models.CheckConstraint(
                condition=models.Q(slippage_rate__gte=0, slippage_rate__lt=1),
                name="portfolio_policy_slippage_range",
            ),
            models.CheckConstraint(
                condition=models.Q(min_rebalance_value__gte=0),
                name="portfolio_policy_min_rebalance_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(max_asset_weight__gt=0, max_asset_weight__lte=1),
                name="portfolio_policy_asset_weight_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    max_volume_participation__gte=0,
                    max_volume_participation__lte=1,
                ),
                name="portfolio_policy_participation_range",
            ),
        ]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        """Reject threshold mutation; create a new version instead."""

        if self.pk:
            original = type(self)._default_manager.filter(pk=self.pk).first()
            immutable = (
                "version",
                "buy_lot_size",
                "fee_rate",
                "slippage_rate",
                "min_rebalance_value",
                "max_asset_weight",
                "max_volume_participation",
            )
            if original and any(
                getattr(original, field) != getattr(self, field) for field in immutable
            ):
                raise ValidationError(
                    "Planning policy thresholds are immutable; create a new version."
                )
        return super().save(*args, **kwargs)
