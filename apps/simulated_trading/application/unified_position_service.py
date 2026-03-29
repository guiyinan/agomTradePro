"""
Unified Position Service.

Application-layer service that provides account_type-agnostic position
management backed by the simulated_trading ledger tables.

Both the account API (/api/account/positions/*) and the simulated-trading
API (/api/simulated-trading/accounts/*/positions/) should delegate to this
service so that all position mutations go through a single, consistent path
that:
  - Always recalculates market_value / unrealized_pnl / unrealized_pnl_pct
  - Always writes a SimulatedTradeModel record on close
  - Applies consistent business rules regardless of account_type
  - Preserves Decimal precision for non-integer share quantities
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

_QUANTITY_PLACES = Decimal("0.000001")
_COST_PLACES = Decimal("0.0001")
_VALUE_PLACES = Decimal("0.01")


def _to_decimal(value, places: Decimal) -> Decimal:
    """Convert a numeric value to Decimal with the given precision."""
    return Decimal(str(value)).quantize(places, rounding=ROUND_HALF_UP)


class UnifiedPositionService:
    """
    Unified position lifecycle service backed by simulated_trading tables.

    Instantiate with the three infrastructure repositories:
        service = UnifiedPositionService(
            account_repo=DjangoSimulatedAccountRepository(),
            position_repo=DjangoPositionRepository(),
            trade_repo=DjangoTradeRepository(),
        )
    """

    def __init__(self, account_repo, position_repo, trade_repo):
        self._account_repo = account_repo
        self._position_repo = position_repo
        self._trade_repo = trade_repo

    # ── reads ──────────────────────────────────────────────────────────────

    def list_positions(self, account_id: int) -> list:
        """Return all active positions for *account_id*."""
        return self._position_repo.get_by_account(account_id)

    def get_position_by_id(self, position_id: int):
        """Return a single position entity by its primary key."""
        return self._position_repo.get_position_by_id(position_id)

    def get_position(self, account_id: int, asset_code: str):
        """Return the position for a specific asset inside an account."""
        return self._position_repo.get_position(account_id, asset_code)

    # ── writes ─────────────────────────────────────────────────────────────

    def create_position(
        self,
        account_id: int,
        asset_code: str,
        shares: float | Decimal,
        price: float | Decimal,
        *,
        current_price: float | Decimal | None = None,
        asset_name: str = "",
        asset_type: str = "equity",
        source: str = "manual",
        source_id: int | None = None,
        entry_reason: str = "",
    ):
        """
        Open a new position (or merge into an existing one) in the unified ledger.

        Preserves non-integer share quantities from the source system.
        Returns the created/updated PositionModel ORM instance.
        """
        from shared.domain.position_calculations import recalculate_derived_fields
        from apps.simulated_trading.infrastructure.models import (
            PositionModel,
            SimulatedTradeModel,
        )

        qty = _to_decimal(shares, _QUANTITY_PLACES)
        avg_cost_d = _to_decimal(price, _COST_PLACES)
        cur_price_d = _to_decimal(current_price if current_price is not None else price, _COST_PLACES)

        mv, pnl, pnl_pct = recalculate_derived_fields(
            float(qty), float(avg_cost_d), float(cur_price_d)
        )

        with db_transaction.atomic():
            existing = PositionModel._default_manager.filter(
                account_id=account_id,
                asset_code=asset_code,
            ).first()

            if existing:
                # Merge: blend avg_cost, add quantities
                combined_qty = existing.quantity + qty
                blended_cost = (
                    (existing.avg_cost * existing.quantity + avg_cost_d * qty) / combined_qty
                ).quantize(_COST_PLACES, rounding=ROUND_HALF_UP)
                mv2, pnl2, pnl_pct2 = recalculate_derived_fields(
                    float(combined_qty), float(blended_cost), float(cur_price_d)
                )
                PositionModel._default_manager.filter(pk=existing.pk).update(
                    quantity=combined_qty,
                    available_quantity=combined_qty,
                    avg_cost=blended_cost,
                    total_cost=(blended_cost * combined_qty).quantize(_VALUE_PLACES),
                    current_price=cur_price_d,
                    market_value=_to_decimal(mv2, _VALUE_PLACES),
                    unrealized_pnl=_to_decimal(pnl2, _VALUE_PLACES),
                    unrealized_pnl_pct=pnl_pct2,
                    last_update_date=date.today(),
                )
                model = PositionModel._default_manager.get(pk=existing.pk)
            else:
                model = PositionModel._default_manager.create(
                    account_id=account_id,
                    asset_code=asset_code,
                    asset_name=asset_name or asset_code,
                    asset_type=asset_type,
                    quantity=qty,
                    available_quantity=qty,
                    avg_cost=avg_cost_d,
                    total_cost=(avg_cost_d * qty).quantize(_VALUE_PLACES),
                    current_price=cur_price_d,
                    market_value=_to_decimal(mv, _VALUE_PLACES),
                    unrealized_pnl=_to_decimal(pnl, _VALUE_PLACES),
                    unrealized_pnl_pct=pnl_pct,
                    first_buy_date=date.today(),
                    signal_id=source_id if source == "signal" else None,
                    entry_reason=entry_reason or f"created via {source}",
                )

            # Write BUY trade record
            SimulatedTradeModel._default_manager.create(
                account_id=account_id,
                asset_code=asset_code,
                asset_name=asset_name or asset_code,
                asset_type=asset_type,
                action="buy",
                quantity=qty,
                price=avg_cost_d,
                amount=(avg_cost_d * qty).quantize(_VALUE_PLACES),
                commission=Decimal("0"),
                slippage=Decimal("0"),
                total_cost=Decimal("0"),
                realized_pnl=None,
                realized_pnl_pct=None,
                reason=entry_reason or f"开仓 ({source})",
                order_date=date.today(),
                execution_date=date.today(),
                execution_time=timezone.now(),
                status="executed",
            )

        return model

    def update_position(
        self,
        account_id: int,
        asset_code: str,
        *,
        shares: float | Decimal | None = None,
        avg_cost: float | Decimal | None = None,
        current_price: float | Decimal | None = None,
    ):
        """
        Calibrate (手工校准) a real-account position.

        Any supplied field is applied; derived fields are then recalculated
        atomically so the response always reflects consistent data.

        Returns the updated Position domain entity.
        """
        from shared.domain.position_calculations import recalculate_derived_fields
        from apps.simulated_trading.infrastructure.models import PositionModel

        model = PositionModel._default_manager.get(
            account_id=account_id,
            asset_code=asset_code,
        )

        if shares is not None:
            model.quantity = _to_decimal(shares, _QUANTITY_PLACES)
            model.available_quantity = model.quantity
        if avg_cost is not None:
            model.avg_cost = _to_decimal(avg_cost, _COST_PLACES)
            model.total_cost = (model.avg_cost * model.quantity).quantize(_VALUE_PLACES)
        if current_price is not None:
            model.current_price = _to_decimal(current_price, _COST_PLACES)

        mv, pnl, pnl_pct = recalculate_derived_fields(
            float(model.quantity),
            float(model.avg_cost),
            float(model.current_price),
        )
        model.market_value = _to_decimal(mv, _VALUE_PLACES)
        model.unrealized_pnl = _to_decimal(pnl, _VALUE_PLACES)
        model.unrealized_pnl_pct = pnl_pct
        model.last_update_date = date.today()
        model.save()

        from apps.simulated_trading.infrastructure.repositories import PositionMapper
        return PositionMapper.to_entity(model)

    def close_position(
        self,
        account_id: int,
        asset_code: str,
        *,
        close_shares: float | Decimal | None = None,
        close_price: float | Decimal | None = None,
        reason: str = "平仓",
    ):
        """
        Close (全部或部分平仓) a position and record a sell trade.

        Preserves Decimal precision for partial-close remainder.
        Returns the updated Position domain entity, or None on full close.
        """
        from shared.domain.position_calculations import recalculate_derived_fields
        from apps.simulated_trading.infrastructure.models import (
            PositionModel,
            SimulatedTradeModel,
        )

        model = PositionModel._default_manager.get(
            account_id=account_id,
            asset_code=asset_code,
        )

        qty_to_close = (
            _to_decimal(close_shares, _QUANTITY_PLACES)
            if close_shares is not None
            else model.quantity
        )
        price_d = (
            _to_decimal(close_price, _COST_PLACES)
            if close_price is not None
            else model.current_price
        )
        amount = (qty_to_close * price_d).quantize(_VALUE_PLACES)
        realized_pnl = amount - (model.avg_cost * qty_to_close).quantize(_VALUE_PLACES)
        realized_pnl_pct = (
            float((price_d - model.avg_cost) / model.avg_cost * 100)
            if model.avg_cost > 0
            else 0.0
        )

        # Write SELL trade record
        SimulatedTradeModel._default_manager.create(
            account_id=account_id,
            asset_code=model.asset_code,
            asset_name=model.asset_name,
            asset_type=model.asset_type,
            action="sell",
            quantity=qty_to_close,
            price=price_d,
            amount=amount,
            commission=Decimal("0"),
            slippage=Decimal("0"),
            total_cost=Decimal("0"),
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            reason=reason,
            signal_id=model.signal_id,
            order_date=date.today(),
            execution_date=date.today(),
            execution_time=timezone.now(),
            status="executed",
        )

        # Update or delete position
        remaining = model.quantity - qty_to_close
        if remaining <= 0:
            model.delete()
            return None

        model.quantity = remaining.quantize(_QUANTITY_PLACES)
        model.available_quantity = model.quantity
        model.total_cost = (model.avg_cost * model.quantity).quantize(_VALUE_PLACES)
        mv, pnl, pnl_pct = recalculate_derived_fields(
            float(model.quantity), float(model.avg_cost), float(price_d)
        )
        model.market_value = _to_decimal(mv, _VALUE_PLACES)
        model.unrealized_pnl = _to_decimal(pnl, _VALUE_PLACES)
        model.unrealized_pnl_pct = pnl_pct
        model.last_update_date = date.today()
        model.save()

        from apps.simulated_trading.infrastructure.repositories import PositionMapper
        return PositionMapper.to_entity(model)

    # ── factory method ────────────────────────────────────────────────────

    @classmethod
    def default(cls) -> "UnifiedPositionService":
        """Return a service instance wired to the default Django repositories."""
        from apps.simulated_trading.infrastructure.repositories import (
            DjangoPositionRepository,
            DjangoSimulatedAccountRepository,
            DjangoTradeRepository,
        )
        return cls(
            account_repo=DjangoSimulatedAccountRepository(),
            position_repo=DjangoPositionRepository(),
            trade_repo=DjangoTradeRepository(),
        )
