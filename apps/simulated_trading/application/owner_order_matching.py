"""Record explicitly confirmed daily matches for an owner's existing order."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    LocalDailyMatchDecision,
)


class OwnerOrderMatchTargetReader(Protocol):
    """Resolve a public owner order to its server-owned daily-match command."""

    def resolve_match_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        session_date: date,
    ) -> LocalDailyMatchCommand:
        """Return the original command or one newly selected QMT source binding."""


class _RecordLocalDailyMatchPort(Protocol):
    """Use the established durable producer without applying any ledger effect."""

    def execute(self, command: LocalDailyMatchCommand) -> LocalDailyMatchDecision:
        """Persist or exactly replay one source-qualified order decision."""


@dataclass(frozen=True, slots=True)
class OwnerOrderMatchRecorded:
    """One verified durable decision returned for an existing owner order."""

    account_id: int
    order_id: int
    decision: LocalDailyMatchDecision

    def __post_init__(self) -> None:
        """Require a real persisted decision within the reported account scope."""

        _require_positive_id(self.account_id, "account_id")
        _require_positive_id(self.order_id, "order_id")
        if type(self.decision) is not LocalDailyMatchDecision:
            raise ValueError("decision must be an exact local daily-match result")
        self.decision.__post_init__()
        if self.decision.command.account_id != self.account_id:
            raise ValueError("decision belongs to another account")


def owner_order_match_operation_key(order_id: int, session_date: date) -> str:
    """Build the stable server-side operation key for one order and session."""

    if type(order_id) is not int or order_id <= 0:
        raise SimulatedTradeExecutionInputError("order_id必须为正整数")
    if type(session_date) is not date:
        raise SimulatedTradeExecutionInputError("撮合交易日必须为精确日期")
    return f"owner-order-match.v1:{order_id}:{session_date.isoformat()}"


class OwnerOrderMatchUseCase:
    """Route a confirmed existing order through the durable local matcher."""

    def __init__(
        self,
        *,
        target_reader: OwnerOrderMatchTargetReader,
        record_use_case: _RecordLocalDailyMatchPort,
    ) -> None:
        """Inject server-side owner resolution and the existing decision producer."""

        self._target_reader = target_reader
        self._record_use_case = record_use_case

    def execute(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        session_date: date,
        confirmed: bool,
    ) -> OwnerOrderMatchRecorded:
        """Record or replay one explicitly confirmed historical daily decision."""

        _validate_request(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            session_date=session_date,
            confirmed=confirmed,
        )
        command = self._resolve_command(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            session_date=session_date,
        )
        decision = self._record_use_case.execute(command)
        checked = self._validate_decision(decision=decision, command=command)
        try:
            return OwnerOrderMatchRecorded(
                account_id=account_id,
                order_id=order_id,
                decision=checked,
            )
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionResultUnknown(
                "撮合决定与已确认订单无法精确核对"
            ) from error

    def _resolve_command(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        session_date: date,
    ) -> LocalDailyMatchCommand:
        """Validate that the target reader preserved public owner and session scope."""

        target = self._target_reader.resolve_match_target(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            session_date=session_date,
        )
        if type(target) is not LocalDailyMatchCommand:
            raise _target_invalid()
        try:
            target.__post_init__()
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise _target_invalid() from error
        if (
            target.account_id != account_id
            or target.user_id != user_id
            or target.session_date != session_date
        ):
            raise SimulatedTradeAccountScopeUnavailable("订单撮合目标不属于当前账户范围")
        return target

    @staticmethod
    def _validate_decision(
        *, decision: object, command: LocalDailyMatchCommand
    ) -> LocalDailyMatchDecision:
        """Treat an unverifiable post-producer result as an indeterminate effect."""

        if type(decision) is not LocalDailyMatchDecision:
            raise SimulatedTradeExecutionResultUnknown("撮合写入返回了不可验证的决定")
        try:
            decision.__post_init__()
            if decision.command != command:
                raise ValueError("producer returned a decision for another command")
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionResultUnknown(
                "撮合决定与服务端订单命令无法精确核对"
            ) from error
        return decision


def _validate_request(
    *,
    account_id: int,
    user_id: int,
    order_id: int,
    session_date: date,
    confirmed: bool,
) -> None:
    """Reject malformed public identity and absent literal confirmation before reads."""

    for value in (account_id, user_id, order_id):
        if type(value) is not int or value <= 0:
            raise SimulatedTradeExecutionInputError("账户、用户和订单标识必须为正整数")
    if type(session_date) is not date:
        raise SimulatedTradeExecutionInputError("撮合交易日必须为精确日期")
    if confirmed is not True:
        raise SimulatedTradeExecutionInputError("必须明确确认该订单的日线模拟撮合")


def _require_positive_id(value: object, field_name: str) -> None:
    """Require one exact positive numeric database identity."""

    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _target_invalid() -> SimulatedTradeExecutionBlocked:
    """Return the stable rejection for a malformed internal order target."""

    return SimulatedTradeExecutionBlocked(
        "订单撮合目标无法精确核对",
        code="OWNER_ORDER_MATCH_TARGET_INVALID",
    )


__all__ = (
    "OwnerOrderMatchRecorded",
    "OwnerOrderMatchTargetReader",
    "OwnerOrderMatchUseCase",
    "owner_order_match_operation_key",
)
