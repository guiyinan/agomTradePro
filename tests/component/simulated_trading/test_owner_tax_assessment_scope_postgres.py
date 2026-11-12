"""Actual non-staff V2 Owner/Audit fence with explicitly controlled tax qualification.

This module tests authorization and atomic persistence. Synthetic assessment
and qualifier facts do not count as the actual source/history model acceptance.
"""

from dataclasses import replace
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.simulated_corporate_action_write_issuance_composition import (
    issue_authenticated_simulated_corporate_action_grant,
)
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentAppendDisposition,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
)
from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
    build_audited_tax_assessment_use_case,
)
from apps.simulated_trading.corporate_action_tax_owner_scope_composition import (
    DjangoTaxAssessmentOwnerScopeVerifier,
)
from core.exceptions import BusinessLogicError
from tests.component.account.test_simulated_corporate_action_capability_issuance_postgres import (
    _v2_command,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.component.simulated_trading.test_corporate_action_tax_assessment_postgres import _counts
from tests.component.simulated_trading.test_owner_granted_corporate_action_postgres import (
    owner_service as owner_service,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import _assessment

pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Actual migrated Owner/Audit transaction; required PostgreSQL workflow.",
    ),
    pytest.mark.django_db(
        transaction=True,
        available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    ),
]


class _ControlledTaxFacts:
    """Explicit test-only current facts; actual Owner/grant/Audit readers remain concrete."""

    def __init__(self, canonical_account_id, fail_exit=False):
        self.canonical_account_id = canonical_account_id
        self.fail_exit = fail_exit
        self.calls = 0
        self.deadline = timezone.now() + timedelta(minutes=1)

    def read_current(self, assessment, *, canonical_account_id, environment, using, as_of):
        assert canonical_account_id == self.canonical_account_id
        assert environment == "development" and using == "default"
        self.calls += 1
        return CurrentTaxAssessmentQualification(
            assessment_semantic_sha256=assessment.semantic_sha256,
            account_id=assessment.account_id,
            owner_user_id=assessment.owner_user_id,
            canonical_account_id=canonical_account_id,
            environment=environment,
            qualification_id="controlled-native-tax-model",
            qualification_sha256="b" * 64 if self.fail_exit and self.calls > 1 else "a" * 64,
            runtime_profile_id="controlled-native-tax-profile",
            runtime_profile_content_sha256="c" * 64,
            runtime_snapshot_id="controlled-native-tax-snapshot",
            runtime_snapshot_sha256="d" * 64,
            valid_until=self.deadline,
        )


def _candidate(world):
    original = _assessment()
    history = original.history
    return replace(
        original,
        action=replace(original.action, account_id=world.row.pk, owner_user_id=world.user.pk),
        history=replace(
            history,
            account_id=world.row.pk,
            owner_user_id=world.user.pk,
            record_date_ownership_proof=replace(
                history.record_date_ownership_proof,
                account_id=world.row.pk,
                owner_user_id=world.user.pk,
            ),
            opening_anchor=replace(
                history.opening_anchor,
                account_id=world.row.pk,
                owner_user_id=world.user.pk,
            ),
            settlement_days=tuple(
                replace(row, account_id=world.row.pk, owner_user_id=world.user.pk)
                for row in history.settlement_days
            ),
        ),
    )


def _use_case(service, *, selected=(Capability.TAX_ASSESS,), fail_exit=False):
    world = service.world
    command = replace(
        _v2_command(world, selected=selected),
        expected_predecessor_content_hash=service.grant.content_hash,
        valid_until=timezone.now() + timedelta(minutes=2),
    )
    grant = issue_authenticated_simulated_corporate_action_grant(
        service.request,
        command=command,
        scope_locker=world.locker,
        using="default",
    )
    verifier = DjangoTaxAssessmentOwnerScopeVerifier(
        selector=grant.selector,
        scope_locker=world.locker,
        qualification_provider=_ControlledTaxFacts(world.source.account_id, fail_exit=fail_exit),
        using="default",
        environment="development",
    )
    return build_audited_tax_assessment_use_case(scope_verifier=verifier, using="default"), grant


def test_native_tax_assess_owner_commits_one_verified_set_and_exact_retry(owner_service):
    service = owner_service
    assert not service.world.user.is_staff and not service.world.user.is_superuser
    candidate = _candidate(service.world)
    use_case, grant = _use_case(service)
    before = _counts()
    first = use_case.execute(candidate, actor_user_id=service.world.user.pk)
    second = use_case.execute(candidate, actor_user_id=service.world.user.pk)
    assert first.assessment_revision_id == second.assessment_revision_id
    assert first.disposition is TaxAssessmentAppendDisposition.STORED
    assert second.disposition is TaxAssessmentAppendDisposition.EXACT_RETRY
    after = _counts()
    assert after == (
        before[0] + 1,
        before[1] + len(candidate.calculation.allocations),
        before[2] + 1,
        before[3] + 1,
    )
    assert grant.capabilities == (Capability.TAX_ASSESS,)
    service.world.row.refresh_from_db()
    assert service.world.row.current_cash == service.world.row.total_value == 10000


def test_native_owner_final_tax_fact_change_rolls_back_all_four_writes(owner_service):
    service = owner_service
    candidate = _candidate(service.world)
    use_case, _ = _use_case(service, fail_exit=True)
    before = _counts()
    with pytest.raises(BusinessLogicError, match="qualification changed"):
        use_case.execute(candidate, actor_user_id=service.world.user.pk)
    assert _counts() == before


def test_native_withholding_only_grant_cannot_assess_tax(owner_service):
    service = owner_service
    candidate = _candidate(service.world)
    use_case, _ = _use_case(service, selected=(Capability.TAX_WITHHOLD,))
    before = _counts()
    with pytest.raises(BusinessLogicError):
        use_case.execute(candidate, actor_user_id=service.world.user.pk)
    assert _counts() == before
