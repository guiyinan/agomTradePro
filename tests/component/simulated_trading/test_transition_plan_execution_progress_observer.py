"""Delegated read of plan progress keeps owner facts and suppresses write actions.

The plan/source facts are explicitly synthetic test inputs. Exact Portfolio
revision reads, observer grants, account resources, history repository and
PostgreSQL transaction behavior use the real local implementations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.account.infrastructure.identity_models import PortfolioObserverGrantModel
from apps.portfolio.application.transition_plan_lifecycle import TransitionPlanRevision
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanRevisionRepository,
)
from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyAccessDenied,
)
from apps.simulated_trading.application.transition_plan_execution_progress import (
    GetTransitionPlanExecutionProgressUseCase,
    PlanExecutionProgressQuery,
    TransitionPlanExecutionProgress,
)
from apps.simulated_trading.infrastructure.models import (
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
    DjangoRebalanceResourceSnapshotRepository,
)
from apps.simulated_trading.infrastructure.transition_plan_execution_history_repository import (
    DjangoTransitionPlanExecutionHistoryRepository,
)
from apps.simulated_trading.transition_plan_journey_composition import (
    build_transition_plan_exact_reader,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import AS_OF as AS_OF
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _clear_runtime_profile_history as _clear_runtime_profile_history,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _freeze_auto_fixture_knowledge_clocks as _freeze_auto_fixture_knowledge_clocks,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _QualifiedCallerContext as _QualifiedCallerContext,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    persisted_source_snapshot as persisted_source_snapshot,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    qualified_caller_context as qualified_caller_context,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _FixedClock,
)
from tests.component.simulated_trading.test_transition_plan_execution_native import (
    _build_revision,
    _persist_sell_position,
)
from tests.support.ash03_auto_calendar_clock_v2 import advance_auto_uow_fixture_clocks

pytestmark = pytest.mark.django_db(transaction=True)


def _persist_current_revision(context: _QualifiedCallerContext) -> TransitionPlanRevision:
    """Persist a synthetic plan aligned to the fixture's explicit source cutoff."""

    position = _persist_sell_position(context.account)
    context.account.current_market_value = position.market_value
    context.account.total_value = context.account.current_cash + position.market_value
    context.account.save(
        update_fields=[
            "current_market_value",
            "total_value",
            "cash_known",
            "cash_reconciliation_status",
        ]
    )
    prepared_at = AS_OF
    revision = _build_revision(
        context=context,
        position_quantity=Decimal(position.quantity),
        prepared_at=prepared_at,
    )
    return DjangoTransitionPlanRevisionRepository(using="default").append_initial(
        revision,
        idempotency_key=revision.plan.idempotency_key,
    )


def _read_progress(
    *,
    revision: TransitionPlanRevision,
    actor_user_id: int,
    account_id: int,
) -> TransitionPlanExecutionProgress:
    """Read an exact revision through the real account grant and ledger ports."""

    return GetTransitionPlanExecutionProgressUseCase(
        revision_reader=build_transition_plan_exact_reader(using="default"),
        family_head_reader=DjangoTransitionPlanRevisionRepository(using="default"),
        history_reader=DjangoTransitionPlanExecutionHistoryRepository(using="default"),
        resource_reader=DjangoRebalanceResourceSnapshotRepository(using="default"),
        clock=_FixedClock(AS_OF),
    ).execute(
        PlanExecutionProgressQuery(
            actor_user_id=actor_user_id,
            account_id=account_id,
            plan_id=revision.identity.plan_id,
            plan_version=revision.identity.version,
            expected_revision_hash=revision.identity.revision_hash,
        )
    )


def test_authorized_observer_reads_owner_progress_without_mutation_capabilities(
    qualified_caller_context: _QualifiedCallerContext,
    django_db_use_migrations: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An actual portfolio-read grant exposes ledger facts but never an Owner action."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip(
            "delegated plan-progress scope requires the isolated migrated PostgreSQL database"
        )
    from tests.support.native_postgres_database import assert_native_postgres_test_database

    assert_native_postgres_test_database()
    context = qualified_caller_context
    revision = _persist_current_revision(context)
    advance_auto_uow_fixture_clocks(monkeypatch, as_of=AS_OF)
    user_model = get_user_model()
    owner = user_model.objects.get(pk=context.owner_id)
    observer = user_model.objects.create_user(
        username=f"ash08-progress-observer-{context.account.pk}",
    )
    assert owner.is_staff is False and owner.is_superuser is False
    assert observer.is_staff is False and observer.is_superuser is False
    grant_expires_at = datetime.now(UTC) + timedelta(hours=1)
    PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=observer,
        scope="portfolio_read",
        status="active",
        expires_at=grant_expires_at,
    )

    owner_progress = _read_progress(
        revision=revision,
        actor_user_id=context.owner_id,
        account_id=context.account.pk,
    )
    reservations_before = SimulatedOrderReservationModel._default_manager.filter(
        account_id=context.account.pk
    ).count()
    trades_before = SimulatedTradeModel._default_manager.filter(
        account_id=context.account.pk
    ).count()
    observer_progress = _read_progress(
        revision=revision,
        actor_user_id=observer.pk,
        account_id=context.account.pk,
    )
    reservations_after = SimulatedOrderReservationModel._default_manager.filter(
        account_id=context.account.pk
    ).count()
    trades_after = SimulatedTradeModel._default_manager.filter(
        account_id=context.account.pk
    ).count()

    assert owner_progress.read_status == "complete"
    assert owner_progress.current_head is True
    assert owner_progress.orders[0].outcome == "ready"
    assert owner_progress.orders[0].can_preview is True
    assert observer_progress.read_status == owner_progress.read_status
    assert observer_progress.current_head == owner_progress.current_head
    assert observer_progress.account is not None
    assert owner_progress.account is not None
    assert observer_progress.account.exact_cash == owner_progress.account.exact_cash
    assert observer_progress.orders[0].outcome == owner_progress.orders[0].outcome
    assert (
        observer_progress.orders[0].remaining_quantity
        == owner_progress.orders[0].remaining_quantity
    )
    assert observer_progress.orders[0].can_preview is False
    assert observer_progress.orders[0].can_cancel is False
    assert observer_progress.orders[0].can_recover is False
    assert "TRANSITION_PLAN_READ_ONLY_ACTOR" in observer_progress.reason_codes
    assert "TRANSITION_PLAN_READ_ONLY_ACTOR" in observer_progress.orders[0].reason_codes
    assert reservations_after == reservations_before
    assert trades_after == trades_before


def test_observer_grant_cannot_be_reused_for_another_account(
    qualified_caller_context: _QualifiedCallerContext,
    django_db_use_migrations: bool,
) -> None:
    """Exact reader authorization remains the gate before owner ledger reads."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip(
            "delegated plan-progress scope requires the isolated migrated PostgreSQL database"
        )
    from tests.support.native_postgres_database import assert_native_postgres_test_database

    assert_native_postgres_test_database()
    context = qualified_caller_context
    revision = _persist_current_revision(context)
    user_model = get_user_model()
    owner = user_model.objects.get(pk=context.owner_id)
    observer = user_model.objects.create_user(
        username=f"ash08-progress-foreign-{context.account.pk}",
    )
    PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=observer,
        scope="portfolio_read",
        status="active",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    with pytest.raises(RebalanceJourneyAccessDenied):
        _read_progress(
            revision=revision,
            actor_user_id=observer.pk,
            account_id=context.account.pk + 1,
        )
