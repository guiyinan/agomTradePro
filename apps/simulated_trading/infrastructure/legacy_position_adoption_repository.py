"""Atomic persistence for adopting one legacy holding without a trade row."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    PositionModel,
    SimulatedAccountModel,
)
from apps.simulated_trading.infrastructure.repository_helpers import _require_saved_id


class DjangoLegacyPositionAdoptionRepository:
    """Persist a source-mapped balance after exact ownership checks."""

    def adopt_legacy_position_projection(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        portfolio_id: int,
        source_position_id: int,
        asset_code: str,
        asset_name: str,
        asset_type: str,
        quantity: Decimal,
        avg_cost: Decimal,
        current_price: Decimal | None,
        first_buy_date: date,
    ) -> int | None:
        """Create one unknown-availability position and its exact source map.

        A valid existing map is an idempotent read. Ambiguous, dangling,
        cross-account, or same-asset-unmapped rows return ``None`` without
        changing positions, maps, or trade history.
        """
        with transaction.atomic():
            account = (
                SimulatedAccountModel._default_manager.select_for_update()
                .filter(pk=account_id)
                .first()
            )
            if (
                account is None
                or account.account_type != "real"
                or account.user_id != owner_user_id
            ):
                return None

            portfolio_maps = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(source_table="portfolio", source_id=portfolio_id)
                .order_by("pk")
            )
            if (
                len(portfolio_maps) != 1
                or portfolio_maps[0].source_app != "account"
                or portfolio_maps[0].target_table != "simulated_account"
                or portfolio_maps[0].target_id != account_id
            ):
                return None
            account_targets = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(target_table="simulated_account", target_id=account_id)
                .order_by("pk")
            )
            if (
                len(account_targets) != 1
                or account_targets[0].source_app != "account"
                or account_targets[0].source_table != "portfolio"
                or account_targets[0].source_id != portfolio_id
            ):
                return None

            source_maps = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(source_table="position", source_id=source_position_id)
                .order_by("pk")
            )
            if source_maps:
                if (
                    len(source_maps) != 1
                    or source_maps[0].source_app != "account"
                    or source_maps[0].target_table != "simulated_position"
                ):
                    return None
                mapped_position = (
                    PositionModel._default_manager.select_for_update()
                    .filter(pk=source_maps[0].target_id)
                    .first()
                )
                if (
                    mapped_position is None
                    or mapped_position.account_id != account_id
                    or mapped_position.asset_code != asset_code
                ):
                    return None
                reverse_maps = list(
                    LedgerMigrationMapModel._default_manager.select_for_update()
                    .filter(target_table="simulated_position", target_id=mapped_position.pk)
                    .order_by("pk")
                )
                if len(reverse_maps) != 1 or reverse_maps[0].pk != source_maps[0].pk:
                    return None
                return _require_saved_id(mapped_position.pk, "position")

            same_asset = (
                PositionModel._default_manager.select_for_update()
                .filter(account_id=account_id, asset_code=asset_code)
                .first()
            )
            if same_asset is not None:
                return None

            total_cost = (avg_cost * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            stored_price = current_price if current_price is not None else Decimal("0")
            market_value = (stored_price * quantity).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            unrealized_pnl = (
                market_value - total_cost if current_price is not None else Decimal("0")
            )
            unrealized_pnl_pct = (
                float((unrealized_pnl / total_cost) * Decimal("100")) if total_cost > 0 else 0.0
            )
            position, created = PositionModel._default_manager.select_for_update().get_or_create(
                account_id=account_id,
                asset_code=asset_code,
                defaults={
                    "asset_name": asset_name,
                    "asset_type": asset_type,
                    "quantity": quantity,
                    "available_quantity": Decimal("0.000000"),
                    "available_quantity_known": False,
                    "avg_cost": avg_cost,
                    "total_cost": total_cost,
                    "current_price": stored_price,
                    "market_value": market_value,
                    "valuation_known": current_price is not None,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "first_buy_date": first_buy_date,
                    "first_buy_date_known": False,
                },
            )
            if not created:
                return None
            position_id = _require_saved_id(position.pk, "position")
            LedgerMigrationMapModel._default_manager.create(
                source_app="account",
                source_table="position",
                source_id=source_position_id,
                target_table="simulated_position",
                target_id=position_id,
            )
            return position_id
