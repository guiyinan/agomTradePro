"""Native Owner review requests remain pending and do not issue approval authority.

Revision source and policy facts are synthetic test inputs. Account scope,
revision storage, exact reads, expiry checks, and the review status update use
the actual Portfolio and simulated-trading repositories on isolated PostgreSQL.
No external message or staff-review service is invoked.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.portfolio.application.transition_plan_lifecycle import (
    GetExactTransitionPlanRevisionQuery,
    GetExactTransitionPlanRevisionUseCase,
    RequestTransitionPlanRevisionReview,
    RequestTransitionPlanRevisionReviewUseCase,
    TransitionPlanRevisionBlocked,
)
from apps.portfolio.infrastructure.transition_models import PortfolioTransitionPlanModel
from apps.portfolio.infrastructure.transition_plan_inactive_approval_models import (
    TransitionPlanInactiveApprovalReceiptModel,
    TransitionPlanInactiveApprovalSubjectModel,
)
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanRevisionRepository,
)
from apps.simulated_trading.application.rebalance_journey_authorization import (
    RebalanceJourneyAccountAuthorizer,
)
from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyAccessDenied,
)
from apps.simulated_trading.composition import build_observer_grant_repository
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import AS_OF as AS_OF
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _clear_runtime_profile_history as _clear_runtime_profile_history,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _create_account as _create_account,
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
    _persist_revision as _persist_revision,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(transaction=True)


def _review_use_case(as_of: datetime) -> RequestTransitionPlanRevisionReviewUseCase:
    """Compose the real Owner scope reader and revision repository."""

    repository = DjangoTransitionPlanRevisionRepository(using="default")
    return RequestTransitionPlanRevisionReviewUseCase(
        repository=repository,
        authorizer=_owner_authorizer(),
        clock=_FixedClock(as_of),
    )


def _owner_authorizer() -> RebalanceJourneyAccountAuthorizer:
    """Compose the real account owner and delegated-read permission repository."""

    resource_reader = DjangoPortfolioRiskResourceRepository(
        using="default",
        observer_grant_repository=build_observer_grant_repository(using="default"),
    )
    return RebalanceJourneyAccountAuthorizer(resource_reader)


def _exact_reader(as_of: datetime) -> GetExactTransitionPlanRevisionUseCase:
    """Compose exact revision reads with the same owner-scope contract as review writes."""

    return GetExactTransitionPlanRevisionUseCase(
        repository=DjangoTransitionPlanRevisionRepository(using="default"),
        authorizer=_owner_authorizer(),
        clock=_FixedClock(as_of),
    )


def _require_native_database(django_db_use_migrations: bool) -> None:
    """Keep the review cases restricted to the isolated migrated PostgreSQL database."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("plan review lifecycle requires the isolated migrated PostgreSQL database")
    assert_native_postgres_test_database()


def test_owner_review_request_persists_pending_revision_without_approval_authority(
    qualified_caller_context: _QualifiedCallerContext,
    django_db_use_migrations: bool,
) -> None:
    """A regular Owner may request review; only the existing staff flow can approve."""

    _require_native_database(django_db_use_migrations)
    context = qualified_caller_context
    revision = _persist_revision(context)
    owner = get_user_model().objects.get(pk=context.owner_id)
    assert not owner.is_staff
    assert not owner.is_superuser
    assert revision.plan.status == "DRAFT"
    original_orders = revision.orders
    original_plan_hash = revision.identity.transition_plan_hash
    original_revision_hash = revision.identity.revision_hash
    expected_pending_clock = AS_OF + timedelta(seconds=1)
    row_before = PortfolioTransitionPlanModel._default_manager.get(
        plan_id=revision.identity.plan_id
    )
    stored_orders_before = row_before.orders
    stored_risk_contract_before = row_before.risk_contract
    stored_current_positions_before = row_before.current_positions_snapshot
    stored_target_positions_before = row_before.target_positions_snapshot

    submission = _review_use_case(expected_pending_clock).execute(
        RequestTransitionPlanRevisionReview(
            actor_user_id=context.owner_id,
            account_id=context.account.pk,
            plan_id=revision.identity.plan_id,
            version=revision.identity.version,
            expected_revision_hash=revision.identity.revision_hash,
        )
    )

    assert submission.revision.plan.status == "APPROVAL_PENDING"
    assert submission.revision.plan.status != "APPROVED"
    assert submission.revision.identity.transition_plan_hash == original_plan_hash
    assert submission.revision.identity.revision_hash == original_revision_hash
    assert submission.artifact_identity.revision_hash == original_revision_hash
    assert submission.revision.orders == original_orders
    assert submission.revision.orders[0].approved_quantity == original_orders[0].approved_quantity
    assert (
        submission.revision.orders[0].approved_limit_price
        == original_orders[0].approved_limit_price
    )

    row = PortfolioTransitionPlanModel._default_manager.get(plan_id=revision.identity.plan_id)
    assert row.status == "APPROVAL_PENDING"
    assert row.approval_request_id == submission.artifact_identity.subject_id
    assert row.immutable_payload_hash == original_plan_hash
    assert row.orders == stored_orders_before
    assert row.risk_contract == stored_risk_contract_before
    assert row.current_positions_snapshot == stored_current_positions_before
    assert row.target_positions_snapshot == stored_target_positions_before
    assert not TransitionPlanInactiveApprovalSubjectModel._default_manager.filter(
        plan_id=revision.identity.plan_id,
        plan_version=revision.identity.version,
    ).exists()
    assert not TransitionPlanInactiveApprovalReceiptModel._default_manager.filter(
        plan_id=revision.identity.plan_id,
        plan_version=revision.identity.version,
    ).exists()

    exact = _exact_reader(expected_pending_clock).execute(
        GetExactTransitionPlanRevisionQuery(
            actor_user_id=context.owner_id,
            account_id=context.account.pk,
            plan_id=revision.identity.plan_id,
            version=revision.identity.version,
            expected_revision_hash=original_revision_hash,
        )
    )
    assert exact is not None
    assert exact.plan.status == "APPROVAL_PENDING"
    assert exact.identity.revision_hash == original_revision_hash
    assert exact.orders == original_orders


def test_expired_exact_revision_remains_readable_but_cannot_be_submitted_for_review(
    qualified_caller_context: _QualifiedCallerContext,
    django_db_use_migrations: bool,
) -> None:
    """Expiry blocks the review transition without rewriting the stored revision."""

    _require_native_database(django_db_use_migrations)
    context = qualified_caller_context
    revision = _persist_revision(context)
    expired_at = revision.identity.valid_until + timedelta(seconds=1)
    expired_exact = _exact_reader(expired_at).execute(
        GetExactTransitionPlanRevisionQuery(
            actor_user_id=context.owner_id,
            account_id=context.account.pk,
            plan_id=revision.identity.plan_id,
            version=revision.identity.version,
            expected_revision_hash=revision.identity.revision_hash,
        )
    )
    assert expired_exact is not None
    assert expired_exact.identity.valid_until < expired_at
    assert expired_exact.plan.status == "DRAFT"

    with pytest.raises(TransitionPlanRevisionBlocked, match="expired plan revisions"):
        _review_use_case(expired_at).execute(
            RequestTransitionPlanRevisionReview(
                actor_user_id=context.owner_id,
                account_id=context.account.pk,
                plan_id=revision.identity.plan_id,
                version=revision.identity.version,
                expected_revision_hash=revision.identity.revision_hash,
            )
        )

    row = PortfolioTransitionPlanModel._default_manager.get(plan_id=revision.identity.plan_id)
    assert row.status == "DRAFT"
    assert row.approval_request_id == ""
    assert row.immutable_payload_hash == revision.identity.transition_plan_hash
    assert not TransitionPlanInactiveApprovalSubjectModel._default_manager.filter(
        plan_id=revision.identity.plan_id,
        plan_version=revision.identity.version,
    ).exists()


def test_cross_account_actor_cannot_read_or_submit_an_owner_revision_for_review(
    qualified_caller_context: _QualifiedCallerContext,
    django_db_use_migrations: bool,
) -> None:
    """Exact revision visibility and review writes both retain account authorization."""

    _require_native_database(django_db_use_migrations)
    context = qualified_caller_context
    revision = _persist_revision(context)
    foreign_account = _create_account()
    assert foreign_account.pk != context.account.pk
    assert foreign_account.user_id != context.owner_id
    as_of = AS_OF + timedelta(seconds=1)

    with pytest.raises(RebalanceJourneyAccessDenied):
        _exact_reader(as_of).execute(
            GetExactTransitionPlanRevisionQuery(
                actor_user_id=context.owner_id,
                account_id=foreign_account.pk,
                plan_id=revision.identity.plan_id,
                version=revision.identity.version,
                expected_revision_hash=revision.identity.revision_hash,
            )
        )

    with pytest.raises(RebalanceJourneyAccessDenied):
        _review_use_case(as_of).execute(
            RequestTransitionPlanRevisionReview(
                actor_user_id=context.owner_id,
                account_id=foreign_account.pk,
                plan_id=revision.identity.plan_id,
                version=revision.identity.version,
                expected_revision_hash=revision.identity.revision_hash,
            )
        )

    row = PortfolioTransitionPlanModel._default_manager.get(plan_id=revision.identity.plan_id)
    assert row.status == "DRAFT"
    assert row.approval_request_id == ""
    assert row.immutable_payload_hash == revision.identity.transition_plan_hash
    assert not TransitionPlanInactiveApprovalSubjectModel._default_manager.filter(
        plan_id=revision.identity.plan_id,
        plan_version=revision.identity.version,
    ).exists()
