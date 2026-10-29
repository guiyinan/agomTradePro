"""Owner operation orchestration over server-resolved order targets."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
)
from apps.simulated_trading.application.order_reservation_fill import (
    ApplySimulatedOrderFillCommand,
    SimulatedOrderFillResult,
)
from apps.simulated_trading.application.owner_order_operations import (
    OwnerOrderCancelled,
    OwnerOrderCancelTarget,
    OwnerOrderFillApplied,
    OwnerOrderFillTarget,
    OwnerOrderOperationsUseCase,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationStatus,
)
from apps.simulated_trading.infrastructure import owner_order_operation_targets
from apps.simulated_trading.infrastructure.owner_order_operation_targets import (
    DjangoOwnerOrderOperationTargetReader,
)
from tests.unit.simulated_trading.test_order_reservation_fill_application import _scenario


@dataclass
class _Targets:
    """Return server-resolved targets and record locator requests."""

    fill_target: object
    cancel_target: object
    fill_calls: list[tuple[int, int, int, int]]
    cancel_calls: list[tuple[int, int, int]]

    def resolve_fill_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
    ) -> OwnerOrderFillTarget:
        """Return the configured exact retained-fill locator."""

        self.fill_calls.append((account_id, user_id, order_id, decision_id))
        return cast(OwnerOrderFillTarget, self.fill_target)

    def resolve_cancel_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
    ) -> OwnerOrderCancelTarget:
        """Return the configured exact cancellation locator."""

        self.cancel_calls.append((account_id, user_id, order_id))
        return cast(OwnerOrderCancelTarget, self.cancel_target)


@dataclass
class _Apply:
    """Capture the exact Apply command and return one configured result."""

    result: object
    commands: list[ApplySimulatedOrderFillCommand]

    def execute(self, command: ApplySimulatedOrderFillCommand) -> SimulatedOrderFillResult:
        """Return the configured typed result after recording the command."""

        self.commands.append(command)
        return cast(SimulatedOrderFillResult, self.result)


@dataclass
class _Cancel:
    """Capture the existing cancellation call and return its reservation."""

    reservation: object
    calls: list[tuple[int, int, str]]

    def execute(self, *, account_id: int, user_id: int, idempotency_key: str) -> OrderReservation:
        """Return the configured exact result after recording the call."""

        self.calls.append((account_id, user_id, idempotency_key))
        return cast(OrderReservation, self.reservation)


class _Clock:
    """Return an aware test instant if a valid reader request reaches the clock."""

    def now(self) -> datetime:
        """Return one fixed UTC instant."""

        return datetime(2026, 10, 19, 2, 0, tzinfo=UTC)


def _targets(*, scenario: object | None = None) -> _Targets:
    """Build a target pair from one exact source-event fixture."""

    source = _scenario() if scenario is None else scenario
    intent = source.intent
    event = source.event
    reservation_id = source.context.reservation_id
    return _Targets(
        fill_target=OwnerOrderFillTarget(
            account_id=intent.account_id,
            user_id=intent.user_id,
            order_id=reservation_id,
            reservation_id=reservation_id,
            decision_id=701,
            order_idempotency_key=intent.idempotency_key,
            source_namespace=event.source_namespace,
            fill_event_id=event.source_event_id,
            expected_event_payload_hash=event.event_payload_hash,
        ),
        cancel_target=OwnerOrderCancelTarget(
            account_id=intent.account_id,
            user_id=intent.user_id,
            order_id=reservation_id,
            reservation_id=reservation_id,
            order_idempotency_key=intent.idempotency_key,
        ),
        fill_calls=[],
        cancel_calls=[],
    )


def _use_case(
    *,
    targets: _Targets,
    apply_result: object,
    cancel_reservation: object,
) -> tuple[OwnerOrderOperationsUseCase, _Apply, _Cancel]:
    """Create one use case with recording versions of its two writer ports."""

    apply = _Apply(result=apply_result, commands=[])
    cancel = _Cancel(reservation=cancel_reservation, calls=[])
    return (
        OwnerOrderOperationsUseCase(
            target_reader=targets,
            apply_use_case=apply,
            cancel_use_case=cancel,
        ),
        apply,
        cancel,
    )


def test_apply_uses_only_the_server_resolved_retained_event_and_rechecks_result() -> None:
    """An explicit confirmation applies the exact persisted event locator."""

    scenario = _scenario()
    targets = _targets(scenario=scenario)
    use_case, apply, _cancel = _use_case(
        targets=targets,
        apply_result=scenario.result,
        cancel_reservation=scenario.result.reservation.release_remaining(),
    )

    result = use_case.apply_retained_fill(
        account_id=scenario.intent.account_id,
        user_id=scenario.intent.user_id,
        order_id=scenario.context.reservation_id,
        decision_id=701,
        confirmed=True,
    )

    assert type(result) is OwnerOrderFillApplied
    assert result.account_id == scenario.intent.account_id
    assert result.order_id == scenario.context.reservation_id
    assert result.decision_id == 701
    assert result.result is scenario.result
    assert targets.fill_calls == [
        (scenario.intent.account_id, scenario.intent.user_id, scenario.context.reservation_id, 701)
    ]
    assert apply.commands == [
        ApplySimulatedOrderFillCommand(
            account_id=scenario.intent.account_id,
            user_id=scenario.intent.user_id,
            order_idempotency_key=scenario.intent.idempotency_key,
            source_namespace=scenario.event.source_namespace,
            fill_event_id=scenario.event.source_event_id,
            expected_event_payload_hash=scenario.event.event_payload_hash,
        )
    ]


def test_apply_rejects_missing_confirmation_before_target_or_writer() -> None:
    """A missing or nonliteral confirmation cannot resolve or apply a target."""

    scenario = _scenario()
    targets = _targets(scenario=scenario)
    use_case, apply, _cancel = _use_case(
        targets=targets,
        apply_result=scenario.result,
        cancel_reservation=scenario.result.reservation.release_remaining(),
    )

    for confirmation in (False, 1, None):
        with pytest.raises(SimulatedTradeExecutionInputError):
            use_case.apply_retained_fill(
                account_id=scenario.intent.account_id,
                user_id=scenario.intent.user_id,
                order_id=scenario.context.reservation_id,
                decision_id=701,
                confirmed=cast(bool, confirmation),
            )

    assert targets.fill_calls == []
    assert apply.commands == []


def test_apply_blocks_when_target_resolves_under_another_owner_scope() -> None:
    """A typed but foreign server target never reaches the existing Apply port."""

    scenario = _scenario()
    targets = _targets(scenario=scenario)
    targets.fill_target = replace(targets.fill_target, user_id=scenario.intent.user_id + 1)
    use_case, apply, _cancel = _use_case(
        targets=targets,
        apply_result=scenario.result,
        cancel_reservation=scenario.result.reservation.release_remaining(),
    )

    with pytest.raises(SimulatedTradeAccountScopeUnavailable):
        use_case.apply_retained_fill(
            account_id=scenario.intent.account_id,
            user_id=scenario.intent.user_id,
            order_id=scenario.context.reservation_id,
            decision_id=701,
            confirmed=True,
        )

    assert apply.commands == []


@pytest.mark.parametrize(
    "change",
    [
        {"reservation_id": 999},
        {"event_payload_hash": "e" * 64},
        {"source_namespace": "another-source"},
    ],
)
def test_apply_rejects_a_result_that_does_not_match_the_resolved_target(
    change: dict[str, object],
) -> None:
    """A writer result with another reservation, digest, or source is indeterminate."""

    scenario = _scenario()
    targets = _targets(scenario=scenario)
    wrong_result = replace(scenario.result, **change)
    use_case, _apply, _cancel = _use_case(
        targets=targets,
        apply_result=wrong_result,
        cancel_reservation=scenario.result.reservation.release_remaining(),
    )

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        use_case.apply_retained_fill(
            account_id=scenario.intent.account_id,
            user_id=scenario.intent.user_id,
            order_id=scenario.context.reservation_id,
            decision_id=701,
            confirmed=True,
        )


def test_cancel_returns_the_writer_current_terminal_reservation_unchanged() -> None:
    """Cancellation reports stored cumulative releases without deriving a delta."""

    scenario = _scenario()
    targets = _targets(scenario=scenario)
    terminal = scenario.result.reservation.release_remaining()
    use_case, _apply, cancel = _use_case(
        targets=targets,
        apply_result=scenario.result,
        cancel_reservation=terminal,
    )

    result = use_case.cancel_remaining(
        account_id=scenario.intent.account_id,
        user_id=scenario.intent.user_id,
        order_id=scenario.context.reservation_id,
        confirmed=True,
    )

    assert type(result) is OwnerOrderCancelled
    assert result.reservation is terminal
    assert result.reservation.status is OrderReservationStatus.CANCELLED
    assert cancel.calls == [
        (
            scenario.intent.account_id,
            scenario.intent.user_id,
            scenario.intent.idempotency_key,
        )
    ]


def test_cancel_rejects_missing_confirmation_and_active_readback() -> None:
    """No confirmation or an active reservation cannot be reported as cancelled."""

    scenario = _scenario()
    targets = _targets(scenario=scenario)
    use_case, _apply, cancel = _use_case(
        targets=targets,
        apply_result=scenario.result,
        cancel_reservation=scenario.result.reservation,
    )

    with pytest.raises(SimulatedTradeExecutionInputError):
        use_case.cancel_remaining(
            account_id=scenario.intent.account_id,
            user_id=scenario.intent.user_id,
            order_id=scenario.context.reservation_id,
            confirmed=False,
        )
    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        use_case.cancel_remaining(
            account_id=scenario.intent.account_id,
            user_id=scenario.intent.user_id,
            order_id=scenario.context.reservation_id,
            confirmed=True,
        )

    assert cancel.calls == [
        (scenario.intent.account_id, scenario.intent.user_id, scenario.intent.idempotency_key)
    ]


def test_infrastructure_reader_rejects_bad_ids_before_opening_a_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public numeric IDs are narrowed before the Infrastructure opens a DB transaction."""

    reader = DjangoOwnerOrderOperationTargetReader(using="default", clock=_Clock())

    def transaction_forbidden(*_args: object, **_kwargs: object) -> None:
        """Fail if validation accidentally reaches the database boundary."""

        raise AssertionError("transaction must not start for invalid IDs")

    monkeypatch.setattr(owner_order_operation_targets.transaction, "atomic", transaction_forbidden)
    with pytest.raises(SimulatedTradeExecutionInputError):
        reader.resolve_fill_target(
            account_id=True,
            user_id=11,
            order_id=41,
            decision_id=701,
        )
    with pytest.raises(SimulatedTradeExecutionInputError):
        reader.resolve_cancel_target(account_id=7, user_id=0, order_id=41)
