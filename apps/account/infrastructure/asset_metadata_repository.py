"""Focused persistence for Account asset metadata and legacy position repricing."""

import logging
from decimal import Decimal
from typing import Any

from django.db.models import Q

from apps.account.domain.transaction_cost_contracts import AssetMetadataRecord
from apps.account.infrastructure.models import AssetMetadataModel, PositionModel

logger = logging.getLogger(__name__)


class AssetMetadataRepository:
    """Persist asset metadata and update legacy Account position valuations."""

    def get_or_create_asset(
        self,
        asset_code: str,
        name: str,
        asset_class: str = "equity",
        region: str = "CN",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return existing asset metadata or create it from validated inputs."""

        asset, created = AssetMetadataModel._default_manager.get_or_create(
            asset_code=asset_code,
            defaults={"name": name, "asset_class": asset_class, "region": region, **kwargs},
        )
        return {
            "id": asset.id,
            "asset_code": asset.asset_code,
            "name": asset.name,
            "asset_class": asset.asset_class,
            "region": asset.region,
            "created": created,
        }

    def search_assets(
        self,
        query: str,
        asset_class: str | None = None,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search at most twenty asset metadata records."""

        queryset = AssetMetadataModel._default_manager.all()
        if query:
            queryset = queryset.filter(Q(asset_code__icontains=query) | Q(name__icontains=query))
        if asset_class:
            queryset = queryset.filter(asset_class=asset_class)
        if region:
            queryset = queryset.filter(region=region)

        return [
            {
                "asset_code": asset.asset_code,
                "name": asset.name,
                "asset_class": asset.asset_class,
                "region": asset.region,
            }
            for asset in queryset[:20]
        ]

    def update_position_prices(self, user_id: int) -> int:
        """Update active positions from canonical prices with exact Decimal math."""

        from apps.account.infrastructure.market_price_service import (
            get_market_price_service,
        )

        positions = PositionModel._default_manager.filter(
            portfolio__user_id=user_id,
            is_closed=False,
        )
        price_service = get_market_price_service()
        updated_count = 0

        for position in positions:
            try:
                price_metadata = price_service.get_price_with_metadata(position.asset_code)
                if price_metadata is None:
                    logger.warning(
                        "Position price unavailable: position_id=%s",
                        position.id,
                    )
                    continue

                new_price = price_metadata["price"]
                shares = Decimal(str(position.shares))
                average_cost = position.avg_cost
                if (
                    not new_price.is_finite()
                    or new_price <= 0
                    or not shares.is_finite()
                    or shares <= 0
                    or not average_cost.is_finite()
                    or average_cost <= 0
                ):
                    logger.warning(
                        "Position valuation inputs invalid: position_id=%s",
                        position.id,
                    )
                    continue

                position.current_price = new_price
                position.market_value = new_price * shares
                position.unrealized_pnl = (new_price - average_cost) * shares
                position.unrealized_pnl_pct = float(
                    (new_price / average_cost - Decimal("1")) * Decimal("100")
                )
                position.save(
                    update_fields=[
                        "current_price",
                        "market_value",
                        "unrealized_pnl",
                        "unrealized_pnl_pct",
                    ]
                )
                updated_count += 1
            except Exception as exc:
                logger.error(
                    "Position price update failed: position_id=%s error_type=%s",
                    position.id,
                    type(exc).__name__,
                )

        return updated_count

    def get_asset_by_code(self, asset_code: str) -> AssetMetadataRecord | None:
        """Return transaction-cost asset metadata when the code exists."""

        try:
            asset = AssetMetadataModel._default_manager.get(asset_code=asset_code)
        except AssetMetadataModel.DoesNotExist:
            return None
        return {
            "asset_code": asset.asset_code,
            "name": asset.name,
            "asset_class": asset.asset_class,
            "region": asset.region,
            "cross_border": asset.cross_border,
            "style": asset.style,
        }


__all__ = ["AssetMetadataRepository"]
