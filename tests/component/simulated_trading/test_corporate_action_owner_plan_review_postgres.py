"""Current real disclosure policy revalidates an explicitly synthetic old plan basis."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanEventReviewRequired,
    require_transition_plan_event_review_clear,
)
from apps.portfolio.domain.transition_plan_event_review import TransitionPlanEventReviewState
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanRevisionRepository,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    DISCLOSURE_COVERAGE_POLICY_KEY,
)
from apps.simulated_trading.transition_plan_event_review_composition import (
    build_configured_transition_plan_event_review_validator,
)
from apps.simulated_trading.transition_plan_journey_composition import (
    build_transition_plan_locked_guard,
)
from core.integration.config_center_runtime import get_active_runtime_value
from shared.config.secrets import get_secrets
from tests.component.simulated_trading import test_transition_plan_execution_native as plan_fixture
from tests.component.simulated_trading.test_corporate_action_owner_workflow_http_postgres import (
    _WORKFLOW_URLCONF,
    _business_effect_counts,
    _refresh,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash05_owner_workflow_native_world import build_owner_workflow_native_world
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = pytest.mark.django_db(
    transaction=True, available_apps=(*ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS, "apps.portfolio")
)


@pytest.fixture(autouse=True)
def _isolated_task_channels() -> Iterator[None]:
    """Keep this native journey's cache and Celery channels isolated."""
    get_secrets.cache_clear()
    try:
        with isolated_task_channels():
            yield
    finally:
        get_secrets.cache_clear()


@dataclass(frozen=True)
class _PlanOwnerContext:
    """Exact persisted owner/account inputs consumed by the synthetic plan factory."""

    account: SimulatedAccountModel
    owner_id: int


def test_real_current_policy_requires_review_of_unpinned_old_owner_plan_without_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A proved disabled optional feature clears; its actual activation fences the old plan."""
    if connection.vendor != "postgresql":
        pytest.skip("owner plan review integration requires migrated PostgreSQL")
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(monkeypatch=monkeypatch, tmp_path=tmp_path)
        assert _refresh(world)["outcome"] == "success"
        assert world.owner.owner.is_staff is False and world.owner.owner.is_superuser is False
        original_policy = get_active_runtime_value(
            environment=world.owner.environment,
            definition_key=DISCLOSURE_COVERAGE_POLICY_KEY,
            as_of=timezone.now(),
        )
        assert isinstance(original_policy, dict) and original_policy["enabled"] is True
        activate_runtime_profile_patch(
            environment=world.owner.environment,
            patch={DISCLOSURE_COVERAGE_POLICY_KEY: {**original_policy, "enabled": False}},
            actor="ash05-explicit-synthetic-old-plan-operator",
            reason="model a retained old plan under a genuinely disabled optional policy",
        )
        monkeypatch.setattr(plan_fixture, "ASSET_CODE", world.asset_code)
        monkeypatch.setattr(plan_fixture, "SECURITY_ID", world.security_id)
        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        position = PositionModel.objects.get(
            account_id=world.account_id, asset_code=world.asset_code
        )
        assert position.quantity == Decimal("70.000000")
        revision = plan_fixture._build_revision(
            context=_PlanOwnerContext(account, world.owner.owner.pk),
            position_quantity=Decimal(position.quantity),
            order_quantity=70,
            prepared_at=timezone.now(),
        )
        # Valuation/risk/planning facts remain synthetic, not trading permission.
        # The actual owner account, immutable Portfolio storage, Config Center,
        # classification, origin and shared review/hold consumer below are real.
        validator = build_configured_transition_plan_event_review_validator(
            runtime_environment=world.owner.environment, using="default"
        )
        repository = DjangoTransitionPlanRevisionRepository(
            using="default", event_review_validator=validator
        )
        saved = repository.append_initial(revision, idempotency_key=revision.plan.idempotency_key)
        # Only unrelated valuation/risk/fee pin facts are controlled synthetic
        # inputs. The owner-scoped SQL lock and current event reader stay real.
        guard = build_transition_plan_locked_guard(
            using="default",
            current_policy_pins_validator=plan_fixture._PinnedPolicyReader(
                plan_fixture._current_synthetic_policy_hashes()
            ),
            event_review_validator=validator,
        )
        binding = saved.orders[0].to_execution_binding(
            saved.identity,
            owner_user_id=world.owner.owner.pk,
            action_attempt_key="ash05-old-owner-plan-current-event-review",
        )
        assert (
            guard.validate_locked_action(
                binding=binding,
                account_id=world.account_id,
                owner_user_id=world.owner.owner.pk,
                as_of=timezone.now(),
            )
            == saved
        )
        clear = validator.assess(saved, as_of=timezone.now())
        assert clear.state is TransitionPlanEventReviewState.UNCHANGED
        require_transition_plan_event_review_clear(saved, as_of=timezone.now(), validator=validator)
        before = _business_effect_counts(world.account_id)
        holds_before = SimulatedOrderReservationModel.objects.filter(
            account_id=world.account_id
        ).count()
        cash_before = (account.current_cash, account.updated_at)
        quantity_before = (position.quantity, position.available_quantity)
        activate_runtime_profile_patch(
            environment=world.owner.environment,
            patch={DISCLOSURE_COVERAGE_POLICY_KEY: original_policy},
            actor="ash05-explicit-synthetic-old-plan-operator",
            reason="restore actual current disclosure policy; old plan lacks coverage pins",
        )
        assessed = validator.assess(saved, as_of=timezone.now())
        assert assessed.state is TransitionPlanEventReviewState.REVIEW_REQUIRED
        assert assessed.reason_code == "EVENT_COVERAGE_PIN_MISSING"
        with pytest.raises(TransitionPlanEventReviewRequired):
            require_transition_plan_event_review_clear(
                saved, as_of=timezone.now(), validator=validator
            )
        with pytest.raises(TransitionPlanEventReviewRequired):
            guard.validate_locked_action(
                binding=binding,
                account_id=world.account_id,
                owner_user_id=world.owner.owner.pk,
                as_of=timezone.now(),
            )
        assert (
            repository.get_revision_by_id(
                plan_id=saved.identity.plan_id, version=saved.identity.version, as_of=timezone.now()
            )
            == saved
        )
        assert _business_effect_counts(world.account_id) == before
        assert (
            SimulatedOrderReservationModel.objects.filter(account_id=world.account_id).count()
            == holds_before
        )
        account.refresh_from_db()
        position.refresh_from_db()
        assert (account.current_cash, account.updated_at) == cash_before
        assert (position.quantity, position.available_quantity) == quantity_before
