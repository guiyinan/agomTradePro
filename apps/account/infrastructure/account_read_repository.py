"""Read-only account repository used by governed SDK and MCP queries."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.account.infrastructure.models import (
    AssetMetadataModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
)


class AccountReadRepository:
    """Provide account projections without synchronizing or mutating ledgers."""

    def list_open_legacy_position_payloads(
        self,
        portfolio: PortfolioModel,
    ) -> list[dict[str, Any]]:
        """Return open position payloads for one already-authorized portfolio."""

        positions = list(
            portfolio.positions.filter(is_closed=False)
            .select_related("category", "currency", "portfolio", "portfolio__user")
            .order_by("id")
        )
        asset_codes = [position.asset_code for position in positions]
        metadata_by_code = {
            item.asset_code: item
            for item in AssetMetadataModel._default_manager.filter(asset_code__in=asset_codes)
        }
        return [
            {
                "id": position.id,
                "portfolio": portfolio.id,
                "portfolio_name": portfolio.name,
                "asset_code": position.asset_code,
                "asset_name": (
                    metadata_by_code[position.asset_code].name
                    if position.asset_code in metadata_by_code
                    else position.asset_code
                ),
                "asset_class": position.asset_class,
                "shares": position.shares,
                "avg_cost": position.avg_cost,
                "current_price": position.current_price,
                "market_value": position.market_value,
                "unrealized_pnl": position.unrealized_pnl,
                "unrealized_pnl_pct": position.unrealized_pnl_pct,
                "source": position.source,
                "source_id": position.source_id,
                "opened_at": position.opened_at,
                "updated_at": position.updated_at,
            }
            for position in positions
        ]

    def list_position_payloads(
        self,
        *,
        user_id: int,
        portfolio_id: int | None = None,
        asset_code: str | None = None,
        include_closed: bool = False,
    ) -> list[dict[str, Any]]:
        """Return accessible legacy position projections using read-only queries."""

        now = timezone.now()
        observable_owner_ids = (
            PortfolioObserverGrantModel._default_manager.filter(
                observer_user_id=user_id,
                status="active",
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .values_list("owner_user_id", flat=True)
        )
        positions = PositionModel._default_manager.filter(
            Q(portfolio__user_id=user_id) | Q(portfolio__user_id__in=observable_owner_ids)
        ).select_related(
            "portfolio",
            "category",
            "currency",
        )
        if portfolio_id is not None:
            positions = positions.filter(portfolio_id=portfolio_id)
        if asset_code:
            positions = positions.filter(asset_code=asset_code)
        if not include_closed:
            positions = positions.filter(is_closed=False)

        return [self._position_payload(position) for position in positions.order_by("id")]

    @staticmethod
    def _position_payload(position: PositionModel) -> dict[str, Any]:
        """Serialize one legacy position without invoking ledger synchronization."""

        category = position.category
        currency = position.currency
        return {
            "id": position.id,
            "portfolio": position.portfolio_id,
            "portfolio_name": position.portfolio.name,
            "asset_code": position.asset_code,
            "asset_name": position.asset_code,
            "category": position.category_id,
            "category_code": category.code if category else None,
            "category_name": category.name if category else None,
            "category_path": category.path if category else None,
            "currency": position.currency_id,
            "currency_code": currency.code if currency else None,
            "currency_name": currency.name if currency else None,
            "currency_symbol": currency.symbol if currency else None,
            "asset_class": position.asset_class,
            "region": position.region,
            "cross_border": position.cross_border,
            "shares": position.shares,
            "avg_cost": position.avg_cost,
            "current_price": position.current_price,
            "market_value": position.market_value,
            "unrealized_pnl": position.unrealized_pnl,
            "unrealized_pnl_pct": position.unrealized_pnl_pct,
            "source": position.source,
            "source_id": position.source_id,
            "is_closed": position.is_closed,
            "opened_at": position.opened_at,
            "closed_at": position.closed_at,
            "created_at": position.created_at,
            "updated_at": position.updated_at,
        }
