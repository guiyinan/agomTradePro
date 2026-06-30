"""Infrastructure read models for account diagnostics."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Sum

from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetCategoryModel,
    AssetMetadataModel,
    CurrencyModel,
    PortfolioModel,
    PositionModel,
)


class AccountDiagnosticRepository:
    """Read account summary counts for operational diagnostics."""

    def get_user_count(self) -> int:
        """Return the number of auth users."""

        return int(get_user_model()._default_manager.count())

    def get_first_user_payload(self) -> dict[str, Any] | None:
        """Return the first auth user in dashboard diagnostic shape."""

        user = get_user_model()._default_manager.first()
        if user is None:
            return None
        return {
            "id": user.id,
            "username": user.username,
        }

    def get_account_summary(self) -> dict[str, Any]:
        """Return account summary metrics for the data-connection command."""

        open_positions = PositionModel.objects.filter(is_closed=False)
        return {
            "currency_count": CurrencyModel.objects.count(),
            "active_currency_count": CurrencyModel.objects.filter(is_active=True).count(),
            "asset_category_count": AssetCategoryModel.objects.count(),
            "profile_count": AccountProfileModel.objects.count(),
            "pending_profile_count": AccountProfileModel.objects.filter(
                approval_status="pending"
            ).count(),
            "approved_profile_count": AccountProfileModel.objects.filter(
                approval_status="approved"
            ).count(),
            "portfolio_count": PortfolioModel.objects.count(),
            "active_portfolio_count": PortfolioModel.objects.filter(is_active=True).count(),
            "position_count": PositionModel.objects.count(),
            "open_position_count": open_positions.count(),
            "open_position_market_value": open_positions.aggregate(
                total=Sum("market_value")
            )["total"]
            or Decimal("0"),
            "open_position_unrealized_pnl": open_positions.aggregate(
                total=Sum("unrealized_pnl")
            )["total"]
            or Decimal("0"),
        }

    def count_orphan_positions(self) -> int:
        """Return the number of positions without a portfolio."""

        return int(PositionModel.objects.filter(portfolio__isnull=True).count())

    def count_missing_asset_metadata(self, asset_codes: list[str]) -> int:
        """Return how many asset codes do not have metadata rows."""

        missing = 0
        for asset_code in {code for code in asset_codes if code}:
            if not AssetMetadataModel.objects.filter(asset_code=asset_code).exists():
                missing += 1
        return missing
