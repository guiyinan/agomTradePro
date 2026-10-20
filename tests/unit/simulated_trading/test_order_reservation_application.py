"""Reservation orchestration must preserve source gates and exact replay."""

from dataclasses import replace
from decimal import Decimal
from unittest.mock import Mock

import pytest

from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    ExecutionInstrumentIdentityUnavailable,
    PreparedSimulatedTrade,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
    ReserveSimulatedOrderUseCase,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservationBook,
    reserve_order,
)
from tests.unit.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _calendar,
    _CalendarReader,
    _fee_policy,
    _FeeReader,
    _FixedClock,
    _IdentityReader,
    _intent,
    _qualified_identity_evidence,
    _RecordingRepository,
    _RuleReader,
)


def _preparer() -> tuple[ExecuteSettlementBoundSimulatedTradeUseCase, _RecordingRepository]:
    repo = _RecordingRepository()
    return (
        ExecuteSettlementBoundSimulatedTradeUseCase(
            rule_reader=_RuleReader(),
            identity_reader=_IdentityReader(_qualified_identity_evidence()),
            calendar_reader=_CalendarReader(_calendar(exchange="SSE"), expected_exchange="SSE"),
            fee_policy_reader=_FeeReader(),
            repository=repo,
            clock=_FixedClock(),
        ),
        repo,
    )


def test_prepare_uses_existing_exact_sources_without_ledger_execution() -> None:
    use_case, repo = _preparer()
    prepared = use_case.prepare(_intent(), as_of=AS_OF)
    assert type(prepared) is PreparedSimulatedTrade
    assert prepared.plan.intent == _intent()
    assert prepared.plan.fee_policy_v2.content_hash == _fee_policy().content_hash
    assert prepared.execution_bundle.content_hash == prepared.plan.settlement_bundle_hash
    assert repo.plans == []


def test_prepare_preserves_missing_identity_gate() -> None:
    use_case, repo = _preparer()
    use_case._identity_reader = _IdentityReader(evidence=None)
    with pytest.raises(ExecutionInstrumentIdentityUnavailable):
        use_case.prepare(_intent(), as_of=AS_OF)
    assert repo.plans == []


def test_reservation_exact_replay_does_not_reread_changed_sources() -> None:
    from apps.simulated_trading.application.order_reservation import reservation_request_from_intent

    request = reservation_request_from_intent(_intent(), fee_budget=Decimal("20"))
    book = OrderReservationBook(
        _intent().account_id, _intent().security_id, Decimal("2000"), None, Decimal("0"), ()
    )
    existing = reserve_order(book, request, _fee_policy(), reserved_at=AS_OF)
    replay = replace(existing, replayed=True)
    repo = Mock()
    repo.find_idempotent_reservation.return_value = replay
    preparer = Mock()
    use_case = ReserveSimulatedOrderUseCase(preparer=preparer, repository=repo, clock=_FixedClock())
    result = use_case.execute(_intent(), fee_budget=Decimal("20"), as_of=AS_OF)
    assert result is replay
    preparer.prepare.assert_not_called()
    repo.reserve_order.assert_not_called()


def test_reservation_new_order_uses_qualified_plan_and_exact_budget() -> None:
    from apps.simulated_trading.application.order_reservation import reservation_request_from_intent

    preparer, _ = _preparer()
    prepared = preparer.prepare(_intent(), as_of=AS_OF)
    book = OrderReservationBook(
        _intent().account_id, _intent().security_id, Decimal("2000"), None, Decimal("0"), ()
    )
    expected = reserve_order(
        book,
        reservation_request_from_intent(_intent(), fee_budget=Decimal("20")),
        _fee_policy(),
        reserved_at=AS_OF,
    )
    repo = Mock()
    repo.find_idempotent_reservation.return_value = None
    repo.reserve_order.return_value = expected
    source = Mock()
    source.prepare.return_value = prepared
    use_case = ReserveSimulatedOrderUseCase(preparer=source, repository=repo, clock=_FixedClock())
    assert use_case.execute(_intent(), fee_budget=Decimal("20"), as_of=AS_OF) is expected
    repo.reserve_order.assert_called_once_with(
        plan=prepared.plan,
        execution_bundle=prepared.execution_bundle,
        fee_budget=Decimal("20"),
        clock=use_case._clock,
    )


@pytest.mark.parametrize("budget", [None, Decimal("NaN"), Decimal("-1"), Decimal("0.001")])
def test_invalid_buy_budget_stops_before_repository_and_sources(budget: Decimal | None) -> None:
    repo = Mock()
    source = Mock()
    use_case = ReserveSimulatedOrderUseCase(preparer=source, repository=repo, clock=_FixedClock())
    with pytest.raises(SimulatedTradeExecutionInputError):
        use_case.execute(_intent(), fee_budget=budget)
    assert repo.mock_calls == []
    assert source.mock_calls == []


def test_cancellation_validates_scope_before_repository() -> None:
    repo = Mock()
    use_case = CancelSimulatedOrderReservationUseCase(repository=repo, clock=_FixedClock())
    with pytest.raises(SimulatedTradeExecutionInputError):
        use_case.execute(account_id=0, user_id=1, idempotency_key="order")
    assert repo.mock_calls == []


def test_foreign_reservation_readback_blocks_before_any_source_or_write() -> None:
    from apps.simulated_trading.application.order_reservation import reservation_request_from_intent

    other = _intent(key="other-order")
    book = OrderReservationBook(
        other.account_id, other.security_id, Decimal("2000"), None, Decimal("0"), ()
    )
    result = reserve_order(
        book,
        reservation_request_from_intent(other, fee_budget=Decimal("20")),
        _fee_policy(),
        reserved_at=AS_OF,
    )
    repo, source = Mock(), Mock()
    repo.find_idempotent_reservation.return_value = result
    use_case = ReserveSimulatedOrderUseCase(preparer=source, repository=repo, clock=_FixedClock())
    with pytest.raises(SimulatedTradeExecutionBlocked):
        use_case.execute(_intent(), fee_budget=Decimal("20"))
    source.prepare.assert_not_called()
    repo.reserve_order.assert_not_called()


def test_cancel_does_not_report_an_active_hold_as_cancelled() -> None:
    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionResultUnknown,
    )
    from apps.simulated_trading.application.order_reservation import reservation_request_from_intent

    intent = _intent()
    book = OrderReservationBook(
        intent.account_id, intent.security_id, Decimal("2000"), None, Decimal("0"), ()
    )
    active = reserve_order(
        book,
        reservation_request_from_intent(intent, fee_budget=Decimal("20")),
        _fee_policy(),
        reserved_at=AS_OF,
    ).reservation
    repo = Mock()
    repo.cancel_order.return_value = active
    use_case = CancelSimulatedOrderReservationUseCase(repository=repo, clock=_FixedClock())
    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        use_case.execute(
            account_id=intent.account_id,
            user_id=intent.user_id,
            idempotency_key=intent.idempotency_key,
        )


def test_fresh_reservation_result_must_still_hold_resources() -> None:
    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionResultUnknown,
    )
    from apps.simulated_trading.application.order_reservation import reservation_request_from_intent
    from apps.simulated_trading.domain.order_reservation import OrderReservationResult

    preparer, _ = _preparer()
    prepared = preparer.prepare(_intent(), as_of=AS_OF)
    book = OrderReservationBook(
        _intent().account_id, _intent().security_id, Decimal("2000"), None, Decimal("0"), ()
    )
    active = reserve_order(
        book,
        reservation_request_from_intent(_intent(), fee_budget=Decimal("20")),
        _fee_policy(),
        reserved_at=AS_OF,
    )
    cancelled = active.reservation.release_remaining()
    repo, source = Mock(), Mock()
    repo.find_idempotent_reservation.return_value = None
    repo.reserve_order.return_value = OrderReservationResult(
        replace(active.book, reservations=(cancelled,)), cancelled, False
    )
    source.prepare.return_value = prepared
    use_case = ReserveSimulatedOrderUseCase(preparer=source, repository=repo, clock=_FixedClock())
    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        use_case.execute(_intent(), fee_budget=Decimal("20"), as_of=AS_OF)
