"""Resolve locked owner order IDs to retained Apply or Cancel targets."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict, cast

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchDecision,
)
from apps.simulated_trading.application.owner_order_operations import (
    OwnerOrderCancelTarget,
    OwnerOrderFillTarget,
)
from apps.simulated_trading.domain.local_order_matching import LocalMatchOutcome
from apps.simulated_trading.domain.order_reservation import OrderReservation
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import _decode_row
from apps.simulated_trading.infrastructure.order_reservation_codec import decode_order_reservation
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)


class _ActorState(TypedDict):
    """Only the authenticated user's current activation column."""

    is_active: object


class DjangoOwnerOrderOperationTargetReader:
    """Lock current owner scope and decode the original retained order facts."""

    def __init__(
        self,
        *,
        using: str = DEFAULT_DB_ALIAS,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Bind target reads to one database alias and one aware execution clock."""

        if type(using) is not str or not using or using.strip() != using:
            raise SimulatedTradeExecutionInputError("订单操作目标数据库别名无效")
        self._using = using
        self._clock = clock

    def resolve_fill_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
    ) -> OwnerOrderFillTarget:
        """Return the exact retained MATCHED event locator inside owner locks."""

        _validate_ids(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            decision_id=decision_id,
        )
        with transaction.atomic(using=self._using):
            self._lock_owner(account_id=account_id, user_id=user_id)
            reservation_row, reservation = self._lock_reservation(
                account_id=account_id,
                user_id=user_id,
                order_id=order_id,
            )
            current_time = self._current_time()
            decision = self._read_decision(
                account_id=account_id,
                user_id=user_id,
                order_id=order_id,
                decision_id=decision_id,
                reservation_row=reservation_row,
                reservation=reservation,
                as_of=current_time,
            )
            event = decision.event
            if event is None or decision.result.outcome is not LocalMatchOutcome.MATCHED:
                raise SimulatedTradeExecutionBlocked(
                    "该撮合决定没有可入账的匹配事件",
                    code="OWNER_ORDER_DECISION_NOT_MATCHED",
                )
            try:
                return OwnerOrderFillTarget(
                    account_id=account_id,
                    user_id=user_id,
                    order_id=order_id,
                    reservation_id=reservation_row.pk,
                    decision_id=decision_id,
                    order_idempotency_key=reservation.identity.idempotency_key,
                    source_namespace=event.source_namespace,
                    fill_event_id=event.source_event_id,
                    expected_event_payload_hash=event.event_payload_hash,
                )
            except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
                raise _target_invalid() from error

    def resolve_cancel_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
    ) -> OwnerOrderCancelTarget:
        """Return the exact current owner reservation key under account locks."""

        _validate_ids(account_id=account_id, user_id=user_id, order_id=order_id)
        with transaction.atomic(using=self._using):
            self._lock_owner(account_id=account_id, user_id=user_id)
            reservation_row, reservation = self._lock_reservation(
                account_id=account_id,
                user_id=user_id,
                order_id=order_id,
            )
            try:
                return OwnerOrderCancelTarget(
                    account_id=account_id,
                    user_id=user_id,
                    order_id=order_id,
                    reservation_id=reservation_row.pk,
                    order_idempotency_key=reservation.identity.idempotency_key,
                )
            except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
                raise _target_invalid() from error

    def _lock_owner(self, *, account_id: int, user_id: int) -> SimulatedAccountModel:
        """Lock the simulated account then active actor and recheck current ownership."""

        account = (
            SimulatedAccountModel._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=account_id, account_type="simulated", user_id=user_id)
            .first()
        )
        if type(account) is not SimulatedAccountModel:
            raise SimulatedTradeAccountScopeUnavailable("模拟账户不存在或不属于当前用户")
        actor_query = (
            get_user_model()
            ._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=user_id)
            .values("is_active")
        )
        actor_state: _ActorState | None = cast(_ActorState | None, actor_query.first())
        if (
            type(actor_state) is not dict
            or set(actor_state) != {"is_active"}
            or type(actor_state["is_active"]) is not bool
            or actor_state["is_active"] is not True
        ):
            raise SimulatedTradeAccountScopeUnavailable("当前账户用户不可用")
        if type(account.user_id) is not int or account.user_id != user_id:
            raise SimulatedTradeAccountScopeUnavailable("模拟账户所有者已变化")
        return account

    def _lock_reservation(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
    ) -> tuple[SimulatedOrderReservationModel, OrderReservation]:
        """Lock one public order ID and revalidate its complete sealed reservation."""

        row = (
            SimulatedOrderReservationModel._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=order_id, account_id=account_id, owner_user_id=user_id)
            .first()
        )
        if type(row) is not SimulatedOrderReservationModel:
            raise SimulatedTradeAccountScopeUnavailable("订单不存在或不属于当前账户所有者")
        try:
            reservation = decode_order_reservation(row)
            if (
                type(row.pk) is not int
                or row.pk != order_id
                or type(row.account_id) is not int
                or row.account_id != account_id
                or type(row.owner_user_id) is not int
                or row.owner_user_id != user_id
                or reservation.identity.account_id != account_id
            ):
                raise ValueError("reservation does not match the requested owner order")
            return row, reservation
        except SimulatedTradeExecutionBlocked:
            raise
        except (
            ArithmeticError,
            AttributeError,
            ObjectDoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise _target_invalid() from error

    def _read_decision(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
        reservation_row: SimulatedOrderReservationModel,
        reservation: OrderReservation,
        as_of: datetime,
    ) -> LocalDailyMatchDecision:
        """Decode the locked immutable decision and bind it to the exact order."""

        rows = list(
            LocalDailyMatchModel._base_manager.using(self._using)
            .select_for_update()
            .select_related("account", "reservation")
            .filter(pk=decision_id, account_id=account_id, reservation_id=order_id)[:2]
        )
        if not rows:
            raise SimulatedTradeAccountScopeUnavailable("撮合决定不存在或不属于当前订单")
        if len(rows) != 1:
            raise _target_invalid()
        row = rows[0]
        try:
            decision = _decode_row(row, replayed=False)
            if type(decision) is not LocalDailyMatchDecision:
                raise ValueError("decision reader returned an unknown contract type")
            decision.__post_init__()
            command = decision.command
            if (
                type(row.pk) is not int
                or row.pk != decision_id
                or row.reservation_id != reservation_row.pk
                or row.account_id != account_id
                or command.account_id != account_id
                or command.user_id != user_id
                or command.order_idempotency_key != reservation.identity.idempotency_key
                or decision.result.outcome
                not in (LocalMatchOutcome.MATCHED, LocalMatchOutcome.NO_MATCH)
            ):
                raise ValueError("decision does not match its owner order scope")
            if row.recorded_at > as_of or (
                decision.event is not None and decision.event.recorded_at > as_of
            ):
                raise SimulatedTradeExecutionBlocked(
                    "未来记录的撮合决定不能用于当前操作",
                    code="OWNER_ORDER_DECISION_FUTURE",
                )
            return decision
        except SimulatedTradeExecutionBlocked:
            raise
        except (
            ArithmeticError,
            AttributeError,
            ObjectDoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise _target_invalid() from error

    def _current_time(self) -> datetime:
        """Read one exact aware cutoff from the injected execution clock."""

        current_time = self._clock.now()
        if type(current_time) is not datetime or current_time.tzinfo is None:
            raise SimulatedTradeExecutionInputError("订单操作读取时钟必须为带时区时间")
        try:
            if current_time.utcoffset() is None:
                raise ValueError("missing UTC offset")
        except (OverflowError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError("订单操作读取时钟无效") from error
        return current_time


def _validate_ids(
    *,
    account_id: int,
    user_id: int,
    order_id: int,
    decision_id: int | None = None,
) -> None:
    """Validate public IDs before querying any account or order rows."""

    if (
        type(account_id) is not int
        or account_id <= 0
        or type(user_id) is not int
        or user_id <= 0
        or type(order_id) is not int
        or order_id <= 0
        or (decision_id is not None and (type(decision_id) is not int or decision_id <= 0))
    ):
        raise SimulatedTradeExecutionInputError("订单操作标识必须为正整数")


def _target_invalid() -> SimulatedTradeExecutionBlocked:
    """Return one stable block for corrupted retained order or decision facts."""

    return SimulatedTradeExecutionBlocked(
        "订单操作目标无法与持久封存数据精确核对",
        code="OWNER_ORDER_OPERATION_TARGET_INVALID",
    )


__all__ = ("DjangoOwnerOrderOperationTargetReader",)
