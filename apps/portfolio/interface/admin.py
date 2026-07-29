"""Admin management for versioned portfolio planning policies."""

from django.contrib import admin
from django.http import HttpRequest

from apps.portfolio.models import PortfolioPlanningPolicyModel
from shared.infrastructure.django_admin import TypedModelAdmin


@admin.register(PortfolioPlanningPolicyModel)
class PortfolioPlanningPolicyAdmin(TypedModelAdmin[PortfolioPlanningPolicyModel]):
    """Expose policy versions while preserving immutable thresholds."""

    list_display = ("version", "status", "buy_lot_size", "created_at")
    list_filter = ("status",)
    search_fields = ("version",)
    readonly_fields = ("created_at",)

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: PortfolioPlanningPolicyModel | None = None,
    ) -> tuple[str, ...]:
        """Keep all versioned policy thresholds immutable after creation."""
        if obj is None:
            return self.readonly_fields
        return self.readonly_fields + (
            "policy_id",
            "version",
            "buy_lot_size",
            "fee_rate",
            "slippage_rate",
            "min_rebalance_value",
            "max_asset_weight",
            "max_volume_participation",
        )
