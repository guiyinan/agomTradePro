"""Read a locked owner-scoped simulated account resource snapshot."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    ActiveRebalanceReservation,
    RebalanceResourceSnapshot,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservationBook,
    OrderReservationError,
)
from apps.simulated_trading.infrastructure.account_mapper import SimulatedAccountMapper
from apps.simulated_trading.infrastructure.order_reservation_codec import decode_order_reservation
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    lock_active_order_reservations,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.position_mapper import PositionMapper
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
)

from .execution_settlement_uow_repository import DjangoSimulatedTradeExecutionRepository


class DjangoRebalanceResourceSnapshotRepository:
    """Serialize preview resource reads with existing simulated-ledger writers."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Bind the exact database used by the account, reservations, and positions."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be a nonempty database alias")
        self._using = using
        self._execution = DjangoSimulatedTradeExecutionRepository(using=using)

    def read_account_snapshot(
        self,
        *,
        account_id: int,
        user_id: int,
    ) -> RebalanceResourceSnapshot | None:
        """Read account, active holds, and all positions using writer lock order."""

        if type(account_id) is not int or account_id <= 0:
            return None
        if type(user_id) is not int or user_id <= 0:
            return None
        try:
            with transaction.atomic(using=self._using):
                account_model = self._execution._locked_account(
                    account_id=account_id,
                    user_id=user_id,
                    require_active=True,
                )
                active_models = lock_active_order_reservations(
                    account_id=account_id,
                    using=self._using,
                )
                position_models = list(
                    PositionModel._default_manager.using(self._using)
                    .select_for_update()
                    .filter(account_id=account_id)
                    .order_by("pk")
                )
                return self._build_snapshot(
                    account_model=account_model,
                    active_models=active_models,
                    position_models=position_models,
                    owner_user_id=user_id,
                    read_at=timezone.now(),
                )
        except (
            ArithmeticError,
            AttributeError,
            OrderReservationError,
            SimulatedTradeAccountScopeUnavailable,
            SimulatedTradeExecutionBlocked,
            TypeError,
            ValueError,
        ):
            return None

    def _build_snapshot(
        self,
        *,
        account_model: SimulatedAccountModel,
        active_models: list[SimulatedOrderReservationModel],
        position_models: list[PositionModel],
        owner_user_id: int,
        read_at: datetime,
    ) -> RebalanceResourceSnapshot | None:
        """Decode every active hold and validate its cash/share envelope."""

        account_id = account_model.pk
        if account_model.user_id != owner_user_id or type(account_id) is not int:
            return None
        account = SimulatedAccountMapper.to_entity(account_model)
        positions = tuple(PositionMapper.to_entity(row) for row in position_models)
        position_by_code = {row.asset_code: row for row in position_models}
        decoded_rows = []
        snapshot_rows: list[ActiveRebalanceReservation] = []
        grouped_codes: dict[str, set[str]] = {}
        for row in active_models:
            if (
                type(row.pk) is not int
                or row.account_id != account_id
                or row.owner_user_id != owner_user_id
                or row.status != SimulatedOrderReservationModel.STATUS_ACTIVE
            ):
                return None
            reservation = decode_order_reservation(row)
            if reservation.identity.account_id != account_id:
                return None
            if row.side != reservation.side.value:
                return None
            decoded_rows.append(reservation)
            grouped_codes.setdefault(reservation.identity.security_id, set()).add(row.asset_code)
            snapshot_rows.append(
                ActiveRebalanceReservation(
                    reservation_id=row.pk,
                    asset_code=row.asset_code,
                    security_id=reservation.identity.security_id,
                    side=reservation.side.value,
                    remaining_cash=reservation.remaining_cash,
                    remaining_shares=reservation.remaining_shares,
                    remaining_buy_notional=reservation.remaining_buy_notional,
                )
            )

        book_cash = (
            Decimal(str(account_model.current_cash)) if account_model.cash_known is True else None
        )
        all_reservations = tuple(decoded_rows)
        for security_id, asset_codes in grouped_codes.items():
            if len(asset_codes) != 1:
                return None
            asset_code = next(iter(asset_codes))
            position_model = position_by_code.get(asset_code)
            if position_model is None and any(
                reservation.identity.security_id == security_id and reservation.side.value == "sell"
                for reservation in decoded_rows
            ):
                return None
            sellable_shares = (
                Decimal(str(position_model.available_quantity))
                if position_model is not None and position_model.available_quantity_known is True
                else None
            )
            OrderReservationBook(
                account_id=account_id,
                security_id=security_id,
                book_cash=book_cash,
                withdrawable_cash=None,
                sellable_shares=sellable_shares,
                reservations=all_reservations,
            )

        return RebalanceResourceSnapshot(
            owner_user_id=owner_user_id,
            read_at=read_at,
            account=account,
            positions=positions,
            active_reservations=tuple(snapshot_rows),
        )


__all__: tuple[str, ...] = ("DjangoRebalanceResourceSnapshotRepository",)
