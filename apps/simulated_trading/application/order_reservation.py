"""Owner-scoped orchestration of simulated-order resource commitments."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import (
    PreparedSimulatedTrade,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
    _require_aware_clock,
)
from apps.simulated_trading.domain.execution_current_reference import SettlementExecutionPlanV3
from apps.simulated_trading.domain.execution_settlement_identity import SettlementExecutionPlanV2
from apps.simulated_trading.domain.execution_settlement_primitives import _require_token
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationRequest,
    OrderReservationResult,
    OrderReservationStatus,
)


class SimulatedOrderPlanPreparer(Protocol):
    """Prepare the exact source contract shared with ordinary execution."""

    def prepare(
        self, intent: SimulatedTradeIntent, *, as_of: datetime | None = None
    ) -> PreparedSimulatedTrade:
        """Return evidence only; commit no trade or hold."""


class SimulatedOrderReservationRepository(Protocol):
    """Persist holds and ledger resource checks under the same account lock."""

    def find_idempotent_reservation(
        self, *, intent: SimulatedTradeIntent, fee_budget: Decimal | None
    ) -> OrderReservationResult | None:
        """Replay original exact intent and budget without refreshing its fee policy."""

    def reserve_order(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        fee_budget: Decimal | None,
        clock: SimulatedTradeExecutionClock,
    ) -> OrderReservationResult:
        """Recheck evidence and available resources, then persist atomically."""

    def find_order(
        self, *, account_id: int, user_id: int, idempotency_key: str
    ) -> OrderReservation | None:
        """Read an exact order only within its current owner scope."""

    def cancel_order(
        self,
        *,
        account_id: int,
        user_id: int,
        idempotency_key: str,
        clock: SimulatedTradeExecutionClock,
    ) -> OrderReservation:
        """Release remaining resources once while preserving original commitments."""


def reservation_request_from_intent(
    intent: SimulatedTradeIntent, *, fee_budget: Decimal | None
) -> OrderReservationRequest:
    """Validate exact intent and explicit fees before any source or ledger reads."""

    if type(intent) is not SimulatedTradeIntent:
        raise SimulatedTradeExecutionInputError("必须提供精确的模拟交易意图")
    try:
        intent.__post_init__()
        return OrderReservationRequest(
            account_id=intent.account_id,
            security_id=intent.security_id,
            idempotency_key=intent.idempotency_key,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.price,
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            fee_budget=fee_budget,
        )
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionInputError("订单预留意图或费用预算无效") from error


def _check_result(
    result: object, request: OrderReservationRequest, *, committed: bool
) -> OrderReservationResult:
    """Reject malformed or foreign port results without inventing a safe balance."""

    error_type = (
        SimulatedTradeExecutionResultUnknown if committed else SimulatedTradeExecutionBlocked
    )
    if type(result) is not OrderReservationResult:
        raise error_type("订单预留返回了不可验证的结果")
    if (
        type(result.book) is not OrderReservationBook
        or type(result.reservation) is not OrderReservation
    ):
        raise error_type("订单预留返回了不可验证的领域值")
    try:
        result.book.__post_init__()
        result.reservation.__post_init__()
        reservation = result.reservation
        if (
            result.book.account_id != request.account_id
            or result.book.security_id != request.security_id
            or type(result.replayed) is not bool
            or reservation.identity.account_id != request.account_id
            or reservation.identity.security_id != request.security_id
            or reservation.identity.idempotency_key != request.idempotency_key
            or reservation.side is not request.side
            or reservation.quantity != request.quantity
            or reservation.limit_price != request.limit_price
            or reservation.fee_budget != request.fee_budget
            or result.book.find_reservation(idempotency_key=request.idempotency_key) != reservation
        ):
            raise ValueError("reservation result differs from request")
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise error_type("订单预留结果与精确请求不一致") from error
    return result


def _validate_owner_key(*, account_id: int, user_id: int, idempotency_key: str) -> None:
    """Validate owner and key shape before repository access."""

    if type(account_id) is not int or account_id <= 0 or type(user_id) is not int or user_id <= 0:
        raise SimulatedTradeExecutionInputError("账户及所有者必须为有效标识")
    try:
        _require_token(idempotency_key, "idempotency_key", max_length=128)
    except (TypeError, ValueError) as error:
        raise SimulatedTradeExecutionInputError("订单幂等键无效") from error


class ReserveSimulatedOrderUseCase:
    """Reserve exact source-qualified resources without creating a trade."""

    def __init__(
        self,
        *,
        preparer: SimulatedOrderPlanPreparer,
        repository: SimulatedOrderReservationRepository,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Inject evidence, persistence and aware execution clock ports."""
        self._preparer = preparer
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        intent: SimulatedTradeIntent,
        *,
        fee_budget: Decimal | None,
        as_of: datetime | None = None,
    ) -> OrderReservationResult:
        """Replay an exact commitment or qualify and atomically establish a new one."""
        request = reservation_request_from_intent(intent, fee_budget=fee_budget)
        if as_of is not None:
            _require_aware_clock(as_of)
        previous = self._repository.find_idempotent_reservation(
            intent=intent, fee_budget=fee_budget
        )
        if previous is not None:
            result = _check_result(previous, request, committed=False)
            return result if result.replayed else replace(result, replayed=True)
        prepared = self._preparer.prepare(intent, as_of=as_of)
        if type(prepared) is not PreparedSimulatedTrade or prepared.plan.intent != intent:
            raise SimulatedTradeExecutionBlocked("预留计划与精确订单意图不一致")
        result = self._repository.reserve_order(
            plan=prepared.plan,
            execution_bundle=prepared.execution_bundle,
            fee_budget=fee_budget,
            clock=self._clock,
        )
        checked = _check_result(result, request, committed=True)
        if not checked.replayed and (
            checked.reservation.status is not OrderReservationStatus.ACTIVE
            or checked.reservation.identity
            != request.identity(fee_policy_hash=prepared.plan.fee_policy_v2.content_hash)
        ):
            raise SimulatedTradeExecutionResultUnknown("新订单预留未绑定已核验的费率与请求摘要")
        return checked


class CancelSimulatedOrderReservationUseCase:
    """Cancel a local unfilled simulated order using its persisted owner and key."""

    def __init__(
        self,
        *,
        repository: SimulatedOrderReservationRepository,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Inject one account-locking repository and aware clock."""
        self._repository = repository
        self._clock = clock

    def execute(self, *, account_id: int, user_id: int, idempotency_key: str) -> OrderReservation:
        """Release the remaining hold idempotently; preserve audit and book cash."""
        _validate_owner_key(account_id=account_id, user_id=user_id, idempotency_key=idempotency_key)
        result = self._repository.cancel_order(
            account_id=account_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            clock=self._clock,
        )
        if type(result) is not OrderReservation:
            raise SimulatedTradeExecutionResultUnknown("撤单返回了不可验证的预留")
        try:
            result.__post_init__()
            if (
                result.identity.account_id != account_id
                or result.identity.idempotency_key != idempotency_key
                or result.status is OrderReservationStatus.ACTIVE
            ):
                raise ValueError("foreign cancellation result")
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionResultUnknown("撤单结果与账户订单不一致") from error
        return result
