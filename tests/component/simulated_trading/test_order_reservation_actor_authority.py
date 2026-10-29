"""Active authenticated-user checks for reservation creation and exact replay."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
)
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
)
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus
from apps.simulated_trading.infrastructure.account_repository import (
    DjangoSimulatedAccountRepository,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel, SimulatedTradeModel
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import AS_OF as AS_OF
from tests.component.simulated_trading.test_execution_settlement_uow import _Clock as _Clock
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_repository import _Harness as _Harness
from tests.component.simulated_trading.test_order_reservation_repository import (
    _intent_for as _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


def _deactivate_actor(user_id: int) -> None:
    """Deactivate the authenticated actor without changing simulated-account state."""

    updated = get_user_model()._base_manager.filter(pk=user_id).update(is_active=False)
    assert updated == 1


def _ledger_state(harness: _Harness) -> tuple[object, ...]:
    """Capture financial account fields, reservation rows, and trade identities."""

    account = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    reservations = tuple(
        SimulatedOrderReservationModel.objects.filter(account_id=harness.account.pk)
        .order_by("pk")
        .values_list(
            "pk",
            "idempotency_key",
            "status",
            "cash_reserved",
            "shares_reserved",
            "filled_quantity",
            "cash_consumed",
            "cash_released",
            "shares_released",
            "plan_snapshot_hash",
            "updated_at",
        )
    )
    trades = tuple(
        SimulatedTradeModel.objects.filter(account_id=harness.account.pk)
        .order_by("pk")
        .values_list("pk")
    )
    return (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        reservations,
        trades,
    )


def _require_blocked_scope(call: Callable[[], object]) -> None:
    """Run a synchronous repository action and require its existing closed-scope error."""

    with pytest.raises(SimulatedTradeAccountScopeUnavailable):
        call()


def test_inactive_actor_cannot_start_a_new_reservation_before_source_reads(
    reservation_harness: _Harness,
) -> None:
    """A user disabled before reserve cannot qualify a new hold or read its plan sources."""

    intent = _intent_for(reservation_harness, key="inactive-actor-new-reservation")
    _deactivate_actor(reservation_harness.user_id)
    before = _ledger_state(reservation_harness)

    _require_blocked_scope(
        lambda: reservation_harness.reserve.execute(
            intent,
            fee_budget=Decimal("5.00"),
            as_of=AS_OF,
        )
    )

    assert reservation_harness.rule_reader.reads == 0
    assert _ledger_state(reservation_harness) == before


def test_inactive_actor_cannot_replay_through_idempotent_lookup(
    reservation_harness: _Harness,
) -> None:
    """A saved request is not replayed after its authenticated user is disabled."""

    intent = _intent_for(reservation_harness, key="inactive-actor-lookup-replay")
    original = reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    reads_after_create = reservation_harness.rule_reader.reads
    before = _ledger_state(reservation_harness)
    _deactivate_actor(reservation_harness.user_id)

    _require_blocked_scope(
        lambda: reservation_harness.reserve.execute(
            intent,
            fee_budget=Decimal("5.00"),
            as_of=AS_OF,
        )
    )

    assert original.replayed is False
    assert reservation_harness.rule_reader.reads == reads_after_create
    assert _ledger_state(reservation_harness) == before


def test_inactive_actor_cannot_create_through_direct_reservation_writer(
    reservation_harness: _Harness,
) -> None:
    """The repository writer independently rejects new work for a disabled actor."""

    intent = _intent_for(reservation_harness, key="inactive-actor-direct-create")
    prepared = reservation_harness.preparer.prepare(intent, as_of=AS_OF)
    _deactivate_actor(reservation_harness.user_id)
    before = _ledger_state(reservation_harness)

    _require_blocked_scope(
        lambda: reservation_harness.repository.reserve_order(
            plan=prepared.plan,
            execution_bundle=prepared.execution_bundle,
            fee_budget=Decimal("5.00"),
            clock=_Clock(AS_OF),
        )
    )

    assert _ledger_state(reservation_harness) == before


def test_inactive_actor_cannot_replay_through_direct_reservation_writer(
    reservation_harness: _Harness,
) -> None:
    """A direct repository retry enforces actor state before returning the stored hold."""

    intent = _intent_for(reservation_harness, key="inactive-actor-direct-replay")
    prepared = reservation_harness.preparer.prepare(intent, as_of=AS_OF)
    original = reservation_harness.repository.reserve_order(
        plan=prepared.plan,
        execution_bundle=prepared.execution_bundle,
        fee_budget=Decimal("5.00"),
        clock=_Clock(AS_OF),
    )
    before = _ledger_state(reservation_harness)
    _deactivate_actor(reservation_harness.user_id)

    _require_blocked_scope(
        lambda: reservation_harness.repository.reserve_order(
            plan=prepared.plan,
            execution_bundle=prepared.execution_bundle,
            fee_budget=Decimal("5.00"),
            clock=_Clock(AS_OF),
        )
    )

    assert original.replayed is False
    assert _ledger_state(reservation_harness) == before


def test_active_actor_can_replay_and_cancel_after_account_deactivation(
    reservation_harness: _Harness,
) -> None:
    """Actor revocation differs from account deactivation for replay and cancellation."""

    intent = _intent_for(reservation_harness, key="active-actor-inactive-account")
    original = reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    account_repository = DjangoSimulatedAccountRepository()
    account = account_repository.get_by_id(reservation_harness.account.pk)
    assert account is not None
    account_repository.save(replace(account, is_active=False, auto_trading_enabled=False))

    replay = reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    cancel = CancelSimulatedOrderReservationUseCase(
        repository=reservation_harness.repository,
        clock=_Clock(AS_OF),
    )
    cancelled = cancel.execute(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=intent.idempotency_key,
    )

    assert replay.replayed is True
    assert replay.reservation == original.reservation
    assert cancelled.status is OrderReservationStatus.CANCELLED
    assert cancelled.cash_released == original.reservation.cash_reserved
    assert (
        SimulatedOrderReservationModel.objects.get(
            account_id=reservation_harness.account.pk,
            idempotency_key=intent.idempotency_key,
        ).status
        == SimulatedOrderReservationModel.STATUS_CANCELLED
    )
