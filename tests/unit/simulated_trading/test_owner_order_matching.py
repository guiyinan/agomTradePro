"""Owner confirmation contract for the existing durable daily matcher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    LocalDailyMatchDecision,
    local_daily_match_request_hash,
)
from apps.simulated_trading.application.owner_order_matching import (
    OwnerOrderMatchRecorded,
    OwnerOrderMatchUseCase,
    owner_order_match_operation_key,
)
from apps.simulated_trading.domain.local_order_matching import (
    LocalMatchOutcome,
    LocalOrderMatchResult,
)

_ACCOUNT_ID = 71
_USER_ID = 81
_ORDER_ID = 91
_SESSION_DATE = date(2026, 10, 28)
_BINDING_ID = str(UUID("10000000-0000-4000-8000-000000000001"))


def _command(
    *,
    account_id: int = _ACCOUNT_ID,
    user_id: int = _USER_ID,
    session_date: date = _SESSION_DATE,
    binding_id: str = _BINDING_ID,
) -> LocalDailyMatchCommand:
    """Build one exact internal command bound to an owner order and session."""

    return LocalDailyMatchCommand(
        account_id=account_id,
        user_id=user_id,
        order_idempotency_key="owner-order-key-91",
        operation_key=owner_order_match_operation_key(_ORDER_ID, session_date),
        session_date=session_date,
        qmt_binding_id=binding_id,
    )


def _decision(command: LocalDailyMatchCommand) -> LocalDailyMatchDecision:
    """Build one valid immutable NO_MATCH decision for the exact command."""

    return LocalDailyMatchDecision(
        command=command,
        request_hash=local_daily_match_request_hash(command),
        result=LocalOrderMatchResult(
            outcome=LocalMatchOutcome.NO_MATCH,
            reason_code="LIMIT_NOT_CROSSED",
            matched_quantity=Decimal("0.000000"),
            matched_price=None,
        ),
        event=None,
        replayed=False,
    )


@dataclass
class _TargetReader:
    """Record the public owner/order resolution and return a configured command."""

    command: object
    calls: list[tuple[int, int, int, date]]

    def resolve_match_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        session_date: date,
    ) -> LocalDailyMatchCommand:
        """Return the configured server-owned local match command."""

        self.calls.append((account_id, user_id, order_id, session_date))
        return cast(LocalDailyMatchCommand, self.command)


@dataclass
class _Recorder:
    """Capture the sole producer call and return a configured durable decision."""

    decision: object
    commands: list[LocalDailyMatchCommand]

    def execute(self, command: LocalDailyMatchCommand) -> LocalDailyMatchDecision:
        """Return the configured record result after preserving its exact command."""

        self.commands.append(command)
        return cast(LocalDailyMatchDecision, self.decision)


def _use_case(
    *, command: object | None = None, decision: object | None = None
) -> tuple[OwnerOrderMatchUseCase, _TargetReader, _Recorder]:
    """Build the Application with narrow recording ports and no persistence access."""

    target = _command() if command is None else command
    record = _decision(target) if decision is None else decision
    targets = _TargetReader(command=target, calls=[])
    recorder = _Recorder(decision=record, commands=[])
    return (
        OwnerOrderMatchUseCase(target_reader=targets, record_use_case=recorder),
        targets,
        recorder,
    )


def test_owner_match_reaches_existing_recorder_and_preserves_its_decision() -> None:
    """A literal confirmation records one server-resolved decision without applying it."""

    use_case, target, recorder = _use_case()

    result = use_case.execute(
        account_id=_ACCOUNT_ID,
        user_id=_USER_ID,
        order_id=_ORDER_ID,
        session_date=_SESSION_DATE,
        confirmed=True,
    )

    assert type(result) is OwnerOrderMatchRecorded
    assert result.account_id == _ACCOUNT_ID
    assert result.order_id == _ORDER_ID
    assert result.decision is recorder.decision
    assert target.calls == [(_ACCOUNT_ID, _USER_ID, _ORDER_ID, _SESSION_DATE)]
    assert recorder.commands == [_command()]


@pytest.mark.parametrize("confirmed", [False, 1, None])
def test_owner_match_requires_literal_confirmation_before_target_or_producer(
    confirmed: object,
) -> None:
    """False, truthy integers, and absent confirmation are rejected before reads."""

    use_case, target, recorder = _use_case()

    with pytest.raises(SimulatedTradeExecutionInputError):
        use_case.execute(
            account_id=_ACCOUNT_ID,
            user_id=_USER_ID,
            order_id=_ORDER_ID,
            session_date=_SESSION_DATE,
            confirmed=cast(bool, confirmed),
        )

    assert target.calls == []
    assert recorder.commands == []


@pytest.mark.parametrize(
    ("account_id", "user_id", "order_id", "session_date"),
    [
        (True, _USER_ID, _ORDER_ID, _SESSION_DATE),
        (_ACCOUNT_ID, 0, _ORDER_ID, _SESSION_DATE),
        (_ACCOUNT_ID, _USER_ID, 0, _SESSION_DATE),
        (
            _ACCOUNT_ID,
            _USER_ID,
            _ORDER_ID,
            datetime(2026, 10, 28, 0, 0, tzinfo=UTC),
        ),
    ],
)
def test_owner_match_rejects_invalid_public_identifiers_before_resolution(
    account_id: object,
    user_id: int,
    order_id: object,
    session_date: object,
) -> None:
    """Boolean IDs and datetime-as-date inputs cannot reach target or producer ports."""

    use_case, target, recorder = _use_case()

    with pytest.raises(SimulatedTradeExecutionInputError):
        use_case.execute(
            account_id=cast(int, account_id),
            user_id=user_id,
            order_id=cast(int, order_id),
            session_date=cast(date, session_date),
            confirmed=True,
        )

    assert target.calls == []
    assert recorder.commands == []


@pytest.mark.parametrize(
    "command",
    [
        _command(account_id=_ACCOUNT_ID + 1),
        _command(user_id=_USER_ID + 1),
        _command(session_date=date(2026, 10, 27)),
    ],
)
def test_owner_match_rejects_target_that_changed_public_scope(
    command: LocalDailyMatchCommand,
) -> None:
    """A target cannot switch the account, user, or selected historical session."""

    use_case, _target, recorder = _use_case(command=command)

    with pytest.raises(SimulatedTradeAccountScopeUnavailable):
        use_case.execute(
            account_id=_ACCOUNT_ID,
            user_id=_USER_ID,
            order_id=_ORDER_ID,
            session_date=_SESSION_DATE,
            confirmed=True,
        )

    assert recorder.commands == []


def test_owner_match_rejects_post_record_result_mismatch_as_indeterminate() -> None:
    """A producer result for another internal command cannot be reported as success."""

    command = _command()
    foreign_decision = _decision(_command(binding_id=str(UUID(int=2))))
    use_case, target, recorder = _use_case(command=command, decision=foreign_decision)

    with pytest.raises(SimulatedTradeExecutionResultUnknown) as blocked:
        use_case.execute(
            account_id=_ACCOUNT_ID,
            user_id=_USER_ID,
            order_id=_ORDER_ID,
            session_date=_SESSION_DATE,
            confirmed=True,
        )

    assert blocked.value.effects_indeterminate is True
    assert target.calls == [(_ACCOUNT_ID, _USER_ID, _ORDER_ID, _SESSION_DATE)]
    assert recorder.commands == [command]
