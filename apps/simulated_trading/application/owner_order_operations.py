"""Resolve and apply explicit owner operations on retained simulated orders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
)
from apps.simulated_trading.application.order_reservation_fill import (
    ApplySimulatedOrderFillCommand,
    SimulatedOrderFillResult,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    _require_hash,
    _require_token,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationStatus,
)


@dataclass(frozen=True, slots=True)
class OwnerOrderFillTarget:
    """One server-resolved retained MATCHED event for an owner order."""

    account_id: int
    user_id: int
    order_id: int
    reservation_id: int
    decision_id: int
    order_idempotency_key: str
    source_namespace: str
    fill_event_id: str
    expected_event_payload_hash: str

    def __post_init__(self) -> None:
        """Require a complete positive locator with a canonical event digest."""

        _require_positive_id(self.account_id, "account_id")
        _require_positive_id(self.user_id, "user_id")
        _require_positive_id(self.order_id, "order_id")
        _require_positive_id(self.reservation_id, "reservation_id")
        _require_positive_id(self.decision_id, "decision_id")
        if self.order_id != self.reservation_id:
            raise ValueError("order_id and reservation_id must identify the same row")
        _require_token(self.order_idempotency_key, "order_idempotency_key", max_length=128)
        _require_token(self.source_namespace, "source_namespace", max_length=128)
        _require_token(self.fill_event_id, "fill_event_id", max_length=128)
        _require_hash(self.expected_event_payload_hash, "expected_event_payload_hash")


@dataclass(frozen=True, slots=True)
class OwnerOrderCancelTarget:
    """One server-resolved owner reservation key for releasing its remaining hold."""

    account_id: int
    user_id: int
    order_id: int
    reservation_id: int
    order_idempotency_key: str

    def __post_init__(self) -> None:
        """Require a positive same-row order locator and exact owner key."""

        _require_positive_id(self.account_id, "account_id")
        _require_positive_id(self.user_id, "user_id")
        _require_positive_id(self.order_id, "order_id")
        _require_positive_id(self.reservation_id, "reservation_id")
        if self.order_id != self.reservation_id:
            raise ValueError("order_id and reservation_id must identify the same row")
        _require_token(self.order_idempotency_key, "order_idempotency_key", max_length=128)


@dataclass(frozen=True, slots=True)
class OwnerOrderFillApplied:
    """A verified Apply result returned for one owner order and decision."""

    account_id: int
    order_id: int
    decision_id: int
    result: SimulatedOrderFillResult

    def __post_init__(self) -> None:
        """Recheck exact owner and order identities in the retained fill result."""

        _require_positive_id(self.account_id, "account_id")
        _require_positive_id(self.order_id, "order_id")
        _require_positive_id(self.decision_id, "decision_id")
        if type(self.result) is not SimulatedOrderFillResult:
            raise ValueError("result must be an exact simulated fill result")
        self.result.__post_init__()
        if (
            self.result.reservation_id != self.order_id
            or self.result.economics.reservation_identity.account_id != self.account_id
            or self.result.reservation.identity.account_id != self.account_id
        ):
            raise ValueError("fill result is outside the owner order scope")


@dataclass(frozen=True, slots=True)
class OwnerOrderCancelled:
    """The writer's current terminal reservation after releasing remaining holds."""

    account_id: int
    order_id: int
    reservation: OrderReservation

    def __post_init__(self) -> None:
        """Recheck the returned terminal reservation's account identity."""

        _require_positive_id(self.account_id, "account_id")
        _require_positive_id(self.order_id, "order_id")
        if type(self.reservation) is not OrderReservation:
            raise ValueError("reservation must be an exact order Domain value")
        self.reservation.__post_init__()
        if (
            self.reservation.identity.account_id != self.account_id
            or self.reservation.status is OrderReservationStatus.ACTIVE
        ):
            raise ValueError("cancellation result is not a terminal owner reservation")


class OwnerOrderTargetReader(Protocol):
    """Resolve numeric order IDs to retained server-side reservation locators."""

    def resolve_fill_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
    ) -> OwnerOrderFillTarget:
        """Return one exact owner decision and its retained MATCHED event locator."""

    def resolve_cancel_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
    ) -> OwnerOrderCancelTarget:
        """Return one exact owner reservation key without changing its hold."""


class _ApplySimulatedOrderFillPort(Protocol):
    """Narrow inward port for the established Apply use case."""

    def execute(self, command: ApplySimulatedOrderFillCommand) -> SimulatedOrderFillResult:
        """Apply or replay one exact retained source event."""


class _CancelSimulatedOrderReservationPort(Protocol):
    """Narrow inward port for the established Cancel use case."""

    def execute(self, *, account_id: int, user_id: int, idempotency_key: str) -> OrderReservation:
        """Release the current remaining hold and return its exact state."""


class OwnerOrderOperationsUseCase:
    """Route explicit owner confirmations through the existing safe writers."""

    def __init__(
        self,
        *,
        target_reader: OwnerOrderTargetReader,
        apply_use_case: _ApplySimulatedOrderFillPort,
        cancel_use_case: _CancelSimulatedOrderReservationPort,
    ) -> None:
        """Inject a target resolver and the established Apply and Cancel use cases."""

        self._target_reader = target_reader
        self._apply_use_case = apply_use_case
        self._cancel_use_case = cancel_use_case

    def apply_retained_fill(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
        confirmed: bool,
    ) -> OwnerOrderFillApplied:
        """Apply one persisted MATCHED decision after explicit owner confirmation."""

        _validate_operation(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            decision_id=decision_id,
            confirmed=confirmed,
        )
        target = self._read_fill_target(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            decision_id=decision_id,
        )
        command = ApplySimulatedOrderFillCommand(
            account_id=target.account_id,
            user_id=target.user_id,
            order_idempotency_key=target.order_idempotency_key,
            source_namespace=target.source_namespace,
            fill_event_id=target.fill_event_id,
            expected_event_payload_hash=target.expected_event_payload_hash,
        )
        result = self._apply_use_case.execute(command)
        checked = self._validate_applied_result(result=result, target=target)
        try:
            return OwnerOrderFillApplied(
                account_id=account_id,
                order_id=order_id,
                decision_id=decision_id,
                result=checked,
            )
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionResultUnknown(
                "成交结果与已确认订单无法精确核对"
            ) from error

    def cancel_remaining(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        confirmed: bool,
    ) -> OwnerOrderCancelled:
        """Cancel the owner's remaining reservation through the existing writer."""

        _validate_operation(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            decision_id=None,
            confirmed=confirmed,
        )
        target = self._read_cancel_target(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
        )
        reservation = self._cancel_use_case.execute(
            account_id=target.account_id,
            user_id=target.user_id,
            idempotency_key=target.order_idempotency_key,
        )
        checked = self._validate_cancel_result(reservation=reservation, target=target)
        try:
            return OwnerOrderCancelled(
                account_id=account_id,
                order_id=order_id,
                reservation=checked,
            )
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionResultUnknown(
                "撤单结果与已确认订单无法精确核对"
            ) from error

    def _read_fill_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
    ) -> OwnerOrderFillTarget:
        """Validate the owner and event locator returned by the infrastructure port."""

        target = self._target_reader.resolve_fill_target(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            decision_id=decision_id,
        )
        if type(target) is not OwnerOrderFillTarget:
            raise _target_invalid()
        try:
            target.__post_init__()
        except (ArithmeticError, TypeError, ValueError) as error:
            raise _target_invalid() from error
        if (
            target.account_id != account_id
            or target.user_id != user_id
            or target.order_id != order_id
            or target.reservation_id != order_id
            or target.decision_id != decision_id
        ):
            raise SimulatedTradeAccountScopeUnavailable("订单或撮合决定不属于当前所有者")
        return target

    def _read_cancel_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
    ) -> OwnerOrderCancelTarget:
        """Validate the owner and reservation key returned by infrastructure."""

        target = self._target_reader.resolve_cancel_target(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
        )
        if type(target) is not OwnerOrderCancelTarget:
            raise _target_invalid()
        try:
            target.__post_init__()
        except (ArithmeticError, TypeError, ValueError) as error:
            raise _target_invalid() from error
        if (
            target.account_id != account_id
            or target.user_id != user_id
            or target.order_id != order_id
            or target.reservation_id != order_id
        ):
            raise SimulatedTradeAccountScopeUnavailable("订单不属于当前所有者")
        return target

    @staticmethod
    def _validate_applied_result(
        *,
        result: object,
        target: OwnerOrderFillTarget,
    ) -> SimulatedOrderFillResult:
        """Require the writer result to match the retained event exactly."""

        if type(result) is not SimulatedOrderFillResult:
            raise SimulatedTradeExecutionResultUnknown("成交写入返回了不可验证的回执")
        try:
            result.__post_init__()
            economics = result.economics
            identity = economics.reservation_identity
            if (
                result.reservation_id != target.reservation_id
                or result.source_namespace != target.source_namespace
                or result.event_payload_hash != target.expected_event_payload_hash
                or economics.fill_event_id != target.fill_event_id
                or economics.user_id != target.user_id
                or identity.account_id != target.account_id
                or identity.idempotency_key != target.order_idempotency_key
                or result.reservation.identity != identity
            ):
                raise ValueError("fill result differs from the retained owner target")
        except SimulatedTradeExecutionResultUnknown:
            raise
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionResultUnknown(
                "成交回执与已确认撮合决定无法精确核对"
            ) from error
        return result

    @staticmethod
    def _validate_cancel_result(
        *,
        reservation: object,
        target: OwnerOrderCancelTarget,
    ) -> OrderReservation:
        """Require the current nonactive reservation identity without deriving deltas."""

        if type(reservation) is not OrderReservation:
            raise SimulatedTradeExecutionResultUnknown("撤单写入返回了不可验证的订单")
        try:
            reservation.__post_init__()
            if (
                reservation.identity.account_id != target.account_id
                or reservation.identity.idempotency_key != target.order_idempotency_key
                or reservation.status is OrderReservationStatus.ACTIVE
            ):
                raise ValueError("cancellation result differs from the owner reservation")
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionResultUnknown(
                "撤单结果与已确认订单无法精确核对"
            ) from error
        return reservation


def _validate_operation(
    *,
    account_id: int,
    user_id: int,
    order_id: int,
    decision_id: int | None,
    confirmed: bool,
) -> None:
    """Reject malformed identifiers and absent literal confirmation before reads."""

    for value in (account_id, user_id, order_id):
        if type(value) is not int or value <= 0:
            raise SimulatedTradeExecutionInputError("账户、所有者及订单标识必须为正整数")
    if decision_id is not None and (type(decision_id) is not int or decision_id <= 0):
        raise SimulatedTradeExecutionInputError("撮合决定标识必须为正整数")
    if confirmed is not True:
        raise SimulatedTradeExecutionInputError("必须明确确认该模拟订单操作")


def _require_positive_id(value: object, field_name: str) -> None:
    """Require one exact positive integer identity field."""

    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _target_invalid() -> SimulatedTradeExecutionBlocked:
    """Return a stable block for a malformed server-resolved target."""

    return SimulatedTradeExecutionBlocked(
        "订单操作目标无法精确核对",
        code="OWNER_ORDER_OPERATION_TARGET_INVALID",
    )


__all__ = (
    "OwnerOrderCancelTarget",
    "OwnerOrderCancelled",
    "OwnerOrderFillApplied",
    "OwnerOrderFillTarget",
    "OwnerOrderOperationsUseCase",
    "OwnerOrderTargetReader",
)
