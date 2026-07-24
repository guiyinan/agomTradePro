"""Simulated Trading owner of the legacy Account portfolio bridge."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.account.infrastructure.models import (
    AssetCategoryModel,
    AssetMetadataModel,
    CapitalFlowModel,
    CurrencyModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from apps.simulated_trading.infrastructure.models import (
        LedgerMigrationMapModel,
    )
    from apps.simulated_trading.infrastructure.models import (
        PositionModel as UnifiedPositionModel,
    )


class PortfolioApiRepository:
    """Persistence helpers for the account portfolio/position API boundary."""

    def get_portfolio_with_owner(self, portfolio_id: int) -> PortfolioModel | None:
        """Return one portfolio with owner/base currency loaded when available."""

        return (
            PortfolioModel._default_manager.select_related("user", "base_currency")
            .filter(id=portfolio_id)
            .first()
        )

    def get_active_observer_grant(
        self,
        *,
        owner_user_id: int,
        observer_user_id: int,
    ) -> PortfolioObserverGrantModel | None:
        """Return one active observer grant when available."""

        return (
            PortfolioObserverGrantModel._default_manager.filter(
                owner_user_id_id=owner_user_id,
                observer_user_id_id=observer_user_id,
                status="active",
            )
            .order_by("-created_at")
            .first()
        )

    def get_inactive_observer_grant(
        self,
        *,
        owner_user_id: int,
        observer_user_id: int,
    ) -> PortfolioObserverGrantModel | None:
        """Return one non-active observer grant when available."""

        return (
            PortfolioObserverGrantModel._default_manager.filter(
                owner_user_id_id=owner_user_id,
                observer_user_id_id=observer_user_id,
            )
            .exclude(status="active")
            .order_by("-created_at")
            .first()
        )

    def ensure_real_account(self, portfolio: PortfolioModel) -> int:
        """Return the unified real account id mapped to one portfolio."""

        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            SimulatedAccountModel,
        )

        with transaction.atomic():
            locked_portfolio = PortfolioModel._default_manager.select_for_update().get(
                pk=portfolio.pk
            )
            mapping = (
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(
                    source_app="account",
                    source_table="portfolio",
                    source_id=locked_portfolio.id,
                )
                .first()
            )
            if mapping is not None and SimulatedAccountModel._default_manager.filter(
                pk=mapping.target_id
            ).exists():
                return int(mapping.target_id)

            real_account = SimulatedAccountModel._default_manager.create(
                user=locked_portfolio.user,
                account_name=locked_portfolio.name,
                account_type="real",
                initial_capital=0,
                current_cash=0,
                current_market_value=0,
                total_value=0,
                is_active=locked_portfolio.is_active,
                auto_trading_enabled=False,
            )
            LedgerMigrationMapModel._default_manager.update_or_create(
                source_app="account",
                source_table="portfolio",
                source_id=locked_portfolio.id,
                defaults={
                    "target_table": "simulated_account",
                    "target_id": real_account.pk,
                },
            )
        return int(real_account.pk)

    def get_portfolio_for_account(self, account_id: int) -> PortfolioModel | None:
        """Return the portfolio mapped to one unified real account."""

        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        mapping = (
            LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="portfolio",
                target_table="simulated_account",
                target_id=account_id,
            )
            .order_by("-id")
            .first()
        )
        if mapping is None:
            return None
        return self.get_portfolio_with_owner(mapping.source_id)

    def list_open_legacy_positions(
        self,
        portfolio: PortfolioModel,
    ) -> QuerySet[PositionModel]:
        """Return open legacy positions for one portfolio."""

        queryset: QuerySet[PositionModel] = (
            portfolio.positions.filter(is_closed=False)
            .select_related("category", "currency", "portfolio", "portfolio__user")
            .order_by("id")
        )
        return queryset

    def get_legacy_position_by_id(self, position_id: int) -> PositionModel | None:
        """Return one legacy position projection with related fields loaded."""

        return (
            PositionModel._default_manager.filter(pk=position_id)
            .select_related("portfolio", "portfolio__user", "category", "currency")
            .first()
        )

    def get_legacy_projection_for_unified_position(
        self,
        unified_position_id: int,
    ) -> PositionModel | None:
        """Return the legacy projection mapped to one unified position."""

        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        mapping = (
            LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="position",
                target_table="simulated_position",
                target_id=unified_position_id,
            )
            .order_by("-id")
            .first()
        )
        if mapping is None:
            return None
        return self.get_legacy_position_by_id(mapping.source_id)

    def get_position_mapping_for_source(
        self,
        source_id: int,
    ) -> LedgerMigrationMapModel | None:
        """Return one legacy-to-unified position mapping for a source id."""

        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        return (
            LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="position",
                source_id=source_id,
            )
            .order_by("-id")
            .first()
        )

    def create_position_mapping(self, *, source_id: int, target_id: int) -> None:
        """Persist one legacy-to-unified position mapping."""

        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        LedgerMigrationMapModel._default_manager.create(
            source_app="account",
            source_table="position",
            source_id=source_id,
            target_table="simulated_position",
            target_id=target_id,
        )

    def upsert_position_mapping(self, *, source_id: int, target_id: int) -> None:
        """Create or update one legacy-to-unified position mapping."""

        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        LedgerMigrationMapModel._default_manager.update_or_create(
            source_app="account",
            source_table="position",
            source_id=source_id,
            defaults={
                "target_table": "simulated_position",
                "target_id": target_id,
            },
        )

    def delete_position_mapping_for_source(self, source_id: int) -> None:
        """Delete stale legacy-to-unified position mappings by source id."""

        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="position",
            source_id=source_id,
        ).delete()

    def delete_position_mapping_for_target(self, target_id: int) -> None:
        """Delete legacy-to-unified position mappings by target id."""

        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="position",
            target_table="simulated_position",
            target_id=target_id,
        ).delete()

    def get_unified_position(self, position_id: int) -> UnifiedPositionModel | None:
        """Return one unified position with account loaded when available."""

        from apps.simulated_trading.infrastructure.models import (
            PositionModel as UnifiedPositionModel,
        )

        return (
            UnifiedPositionModel._default_manager.select_related("account")
            .filter(pk=position_id)
            .first()
        )

    def get_unified_position_for_account_asset(
        self,
        *,
        account_id: int,
        asset_code: str,
    ) -> UnifiedPositionModel | None:
        """Return one unified position by account and asset code when available."""

        from apps.simulated_trading.infrastructure.models import (
            PositionModel as UnifiedPositionModel,
        )

        return (
            UnifiedPositionModel._default_manager.select_related("account")
            .filter(account_id=account_id, asset_code=asset_code)
            .first()
        )

    def list_unified_positions(
        self,
        *,
        account_ids: list[int],
        asset_code: str | None = None,
    ) -> QuerySet[UnifiedPositionModel]:
        """Return unified positions for the provided account ids."""

        from apps.simulated_trading.infrastructure.models import (
            PositionModel as UnifiedPositionModel,
        )

        queryset = (
            UnifiedPositionModel._default_manager.filter(account_id__in=account_ids)
            .select_related("account")
            .order_by("-market_value", "asset_code")
        )
        if asset_code:
            queryset = queryset.filter(asset_code=asset_code)
        typed_queryset: QuerySet[UnifiedPositionModel] = queryset
        return typed_queryset

    def delete_unified_position(self, position_id: int) -> None:
        """Delete one unified position by id."""

        from apps.simulated_trading.infrastructure.models import (
            PositionModel as UnifiedPositionModel,
        )

        UnifiedPositionModel._default_manager.filter(pk=position_id).delete()

    def delete_legacy_projection(self, legacy_projection: PositionModel) -> None:
        """Delete one legacy position projection."""

        legacy_projection.delete()

    def upsert_legacy_projection_from_unified(
        self,
        *,
        unified_position: UnifiedPositionModel,
        portfolio: PortfolioModel,
        asset_class: str,
        region: str,
        cross_border: str,
        category: AssetCategoryModel | None = None,
        currency: CurrencyModel | None = None,
        source: str = "manual",
        source_id: int | None = None,
        close_projection: bool = False,
    ) -> PositionModel | None:
        """Mirror one unified position into the legacy projection table."""

        legacy_projection = self.get_legacy_projection_for_unified_position(unified_position.id)
        if legacy_projection is None:
            legacy_projection = (
                PositionModel._default_manager.filter(
                    portfolio=portfolio,
                    asset_code=unified_position.asset_code,
                    is_closed=False,
                )
                .select_related("portfolio", "portfolio__user", "category", "currency")
                .first()
            )

        if legacy_projection is None:
            legacy_projection = PositionModel._default_manager.create(
                portfolio=portfolio,
                asset_code=unified_position.asset_code,
                category=category,
                currency=currency,
                asset_class=asset_class,
                region=region,
                cross_border=cross_border,
                shares=float(unified_position.quantity),
                avg_cost=unified_position.avg_cost,
                current_price=unified_position.current_price,
                market_value=unified_position.market_value,
                unrealized_pnl=unified_position.unrealized_pnl,
                unrealized_pnl_pct=unified_position.unrealized_pnl_pct,
                source=source,
                source_id=source_id,
                is_closed=False,
            )
        else:
            legacy_projection.category = category
            legacy_projection.currency = currency
            legacy_projection.asset_class = asset_class
            legacy_projection.region = region
            legacy_projection.cross_border = cross_border
            legacy_projection.shares = float(unified_position.quantity)
            legacy_projection.avg_cost = unified_position.avg_cost
            legacy_projection.current_price = unified_position.current_price
            legacy_projection.market_value = unified_position.market_value
            legacy_projection.unrealized_pnl = unified_position.unrealized_pnl
            legacy_projection.unrealized_pnl_pct = unified_position.unrealized_pnl_pct
            legacy_projection.source = source
            legacy_projection.source_id = source_id
            if not close_projection:
                legacy_projection.is_closed = False
                legacy_projection.closed_at = None
            legacy_projection.save()

        self.upsert_position_mapping(
            source_id=legacy_projection.id,
            target_id=unified_position.id,
        )
        return (
            PositionModel._default_manager.filter(pk=legacy_projection.pk)
            .select_related("portfolio", "portfolio__user", "category", "currency")
            .first()
        )

    def mark_legacy_projection_closed_for_unified(
        self,
        *,
        target_id: int,
        closed_at: datetime | None = None,
    ) -> PositionModel | None:
        """Mark the legacy account.position projection closed for a unified position."""

        legacy_projection = self.get_legacy_projection_for_unified_position(target_id)
        if legacy_projection is None:
            return None
        legacy_projection.shares = 0
        legacy_projection.market_value = Decimal("0")
        legacy_projection.unrealized_pnl = Decimal("0")
        legacy_projection.unrealized_pnl_pct = 0.0
        legacy_projection.is_closed = True
        legacy_projection.closed_at = closed_at or timezone.now()
        legacy_projection.save(
            update_fields=[
                "shares",
                "market_value",
                "unrealized_pnl",
                "unrealized_pnl_pct",
                "is_closed",
                "closed_at",
                "updated_at",
            ]
        )
        return legacy_projection

    def build_position_payload(
        self,
        unified_position: UnifiedPositionModel,
        portfolio: PortfolioModel | None = None,
    ) -> dict[str, Any]:
        """Build the position response payload for one unified position."""

        legacy_projection = self.get_legacy_projection_for_unified_position(unified_position.id)
        if portfolio is None and legacy_projection is not None:
            portfolio = legacy_projection.portfolio
        if portfolio is None:
            portfolio = self.get_portfolio_for_account(unified_position.account_id)

        asset_metadata = AssetMetadataModel._default_manager.filter(
            asset_code=unified_position.asset_code
        ).first()

        category = legacy_projection.category if legacy_projection else None
        currency = (
            legacy_projection.currency
            if legacy_projection
            else getattr(portfolio, "base_currency", None)
        )
        asset_class = (
            legacy_projection.asset_class
            if legacy_projection
            else getattr(asset_metadata, "asset_class", unified_position.asset_type)
        )
        region = (
            legacy_projection.region
            if legacy_projection
            else getattr(asset_metadata, "region", "CN")
        )
        cross_border = (
            legacy_projection.cross_border
            if legacy_projection
            else getattr(asset_metadata, "cross_border", "domestic")
        )

        return {
            "id": unified_position.id,
            "portfolio": portfolio.id if portfolio else None,
            "portfolio_name": portfolio.name if portfolio else "",
            "asset_code": unified_position.asset_code,
            "asset_name": getattr(asset_metadata, "name", None)
            or unified_position.asset_name
            or unified_position.asset_code,
            "category": category.id if category else None,
            "category_code": category.code if category else None,
            "category_name": category.name if category else None,
            "category_path": category.get_full_path() if category else None,
            "currency": currency.id if currency else None,
            "currency_code": currency.code if currency else None,
            "currency_name": currency.name if currency else None,
            "currency_symbol": currency.symbol if currency else None,
            "asset_class": asset_class,
            "region": region,
            "cross_border": cross_border,
            "shares": float(unified_position.quantity),
            "avg_cost": unified_position.avg_cost,
            "current_price": unified_position.current_price,
            "market_value": unified_position.market_value,
            "unrealized_pnl": unified_position.unrealized_pnl,
            "unrealized_pnl_pct": unified_position.unrealized_pnl_pct,
            "source": legacy_projection.source if legacy_projection else "manual",
            "source_id": (
                legacy_projection.source_id if legacy_projection else unified_position.signal_id
            ),
            "is_closed": False,
            "opened_at": legacy_projection.opened_at if legacy_projection else None,
            "closed_at": legacy_projection.closed_at if legacy_projection else None,
            "created_at": getattr(unified_position, "created_at", None),
            "updated_at": getattr(unified_position, "updated_at", None),
        }

    def build_closed_position_payload(
        self,
        *,
        unified_position: UnifiedPositionModel,
        portfolio: PortfolioModel,
        legacy_projection: PositionModel | None,
    ) -> dict[str, Any]:
        """Build the closed-position response payload after a full close."""

        return {
            "id": unified_position.id,
            "portfolio": portfolio.id,
            "portfolio_name": portfolio.name,
            "asset_code": unified_position.asset_code,
            "asset_name": unified_position.asset_name,
            "category": legacy_projection.category_id if legacy_projection else None,
            "category_code": (
                legacy_projection.category.code
                if legacy_projection and legacy_projection.category
                else None
            ),
            "category_name": (
                legacy_projection.category.name
                if legacy_projection and legacy_projection.category
                else None
            ),
            "category_path": (
                legacy_projection.category.get_full_path()
                if legacy_projection and legacy_projection.category
                else None
            ),
            "currency": legacy_projection.currency_id if legacy_projection else None,
            "currency_code": (
                legacy_projection.currency.code
                if legacy_projection and legacy_projection.currency
                else None
            ),
            "currency_name": (
                legacy_projection.currency.name
                if legacy_projection and legacy_projection.currency
                else None
            ),
            "currency_symbol": (
                legacy_projection.currency.symbol
                if legacy_projection and legacy_projection.currency
                else None
            ),
            "asset_class": legacy_projection.asset_class if legacy_projection else "equity",
            "region": legacy_projection.region if legacy_projection else "CN",
            "cross_border": legacy_projection.cross_border if legacy_projection else "domestic",
            "shares": 0.0,
            "avg_cost": (
                legacy_projection.avg_cost if legacy_projection else unified_position.avg_cost
            ),
            "current_price": (
                legacy_projection.current_price
                if legacy_projection
                else unified_position.current_price
            ),
            "market_value": Decimal("0.00"),
            "unrealized_pnl": Decimal("0.00"),
            "unrealized_pnl_pct": 0.0,
            "source": legacy_projection.source if legacy_projection else "manual",
            "source_id": (
                legacy_projection.source_id if legacy_projection else unified_position.signal_id
            ),
            "is_closed": True,
            "opened_at": legacy_projection.opened_at if legacy_projection else None,
            "closed_at": legacy_projection.closed_at if legacy_projection else timezone.now(),
            "created_at": getattr(legacy_projection, "created_at", None),
            "updated_at": getattr(legacy_projection, "updated_at", None),
        }

    def build_portfolio_statistics(self, portfolio: PortfolioModel) -> dict[str, Any]:
        """Build summary statistics for one portfolio."""

        positions = list(
            PositionModel._default_manager.filter(portfolio=portfolio, is_closed=False)
        )
        position_count = len(positions)
        total_value = sum((position.market_value or Decimal("0")) for position in positions)
        total_cost = sum(
            Decimal(str(position.shares)) * (position.avg_cost or Decimal("0"))
            for position in positions
        )
        total_pnl = total_value - total_cost
        total_pnl_pct = float((total_pnl / total_cost * 100) if total_cost > 0 else 0)

        asset_class_breakdown: dict[str, float] = {}
        region_breakdown: dict[str, float] = {}
        for position in positions:
            asset_key = position.get_asset_class_display()
            region_key = position.get_region_display()
            market_value = float(position.market_value or 0)
            asset_class_breakdown[asset_key] = (
                asset_class_breakdown.get(asset_key, 0.0) + market_value
            )
            region_breakdown[region_key] = region_breakdown.get(region_key, 0.0) + market_value

        capital_flows = CapitalFlowModel._default_manager.filter(portfolio=portfolio)
        total_inflow = capital_flows.filter(flow_type="deposit").aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0")
        total_outflow = capital_flows.filter(flow_type="withdraw").aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0")

        return {
            "total_value": total_value,
            "total_cost": total_cost,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "position_count": position_count,
            "asset_class_breakdown": asset_class_breakdown,
            "region_breakdown": region_breakdown,
            "total_capital_inflow": total_inflow,
            "total_capital_outflow": total_outflow,
            "net_capital_flow": total_inflow - total_outflow,
        }
