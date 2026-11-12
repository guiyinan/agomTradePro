"""Actual nonstaff V2 withholding consent and financial UOW; synthetic tax facts.

This is the authorization/storage fence contract, separate from full concrete
source/instrument/history qualification. No source capture clock is refreshed.
"""

from dataclasses import replace
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.simulated_corporate_action_write_issuance_composition import (
    issue_authenticated_simulated_corporate_action_grant,
    revoke_authenticated_simulated_corporate_action_grant,
)
from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.simulated_trading.application.corporate_action_tax_liability import (
    TaxLiabilityAppendDisposition,
)
from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
    build_audited_tax_assessment_use_case,
)
from apps.simulated_trading.audited_corporate_action_tax_liability_composition import (
    build_audited_tax_liability_use_case,
)
from apps.simulated_trading.corporate_action_tax_liability_owner_scope_composition import (
    DjangoTaxLiabilityOwnerScopeVerifier,
)
from apps.simulated_trading.corporate_action_tax_owner_scope_composition import (
    DjangoTaxAssessmentOwnerScopeVerifier,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import TaxLiabilityCashAction
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel as Operation,
)
from core.exceptions import AuthorizationError, BusinessLogicError
from tests.component.account.test_simulated_corporate_action_capability_issuance_postgres import (
    _v2_command,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.component.simulated_trading.test_owner_granted_corporate_action_postgres import (
    owner_service as owner_service,
)
from tests.component.simulated_trading.test_owner_tax_assessment_scope_postgres import (
    _candidate,
    _ControlledTaxFacts,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS

pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Actual migrated nonstaff Owner financial contract",
    ),
    pytest.mark.django_db(transaction=True, available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS),
]


def _financial_service(service, *, fail_exit=False):
    world = service.world
    candidate = _candidate(world)
    policy = replace(
        candidate.policy,
        bands=(
            replace(candidate.policy.bands[0], maximum_holding_months=24),
            candidate.policy.bands[1],
        ),
    )
    candidate = replace(candidate, policy=policy)
    assert candidate.calculation.withholding_amount > 0
    command = replace(
        _v2_command(world, selected=(Capability.TAX_ASSESS, Capability.TAX_WITHHOLD)),
        expected_predecessor_content_hash=service.grant.content_hash,
        valid_until=timezone.now() + timedelta(minutes=2),
    )
    grant = issue_authenticated_simulated_corporate_action_grant(
        service.request, command=command, scope_locker=world.locker, using="default"
    )
    assessment_scope = DjangoTaxAssessmentOwnerScopeVerifier(
        selector=grant.selector,
        scope_locker=world.locker,
        qualification_provider=_ControlledTaxFacts(world.source.account_id),
        using="default",
        environment="development",
    )
    build_audited_tax_assessment_use_case(scope_verifier=assessment_scope, using="default").execute(
        candidate, actor_user_id=world.user.pk
    )
    audit = build_tax_assessment_audit_coordinator(using="default")
    qualifier = _ControlledTaxFacts(world.source.account_id, fail_exit=fail_exit)
    scope = DjangoTaxLiabilityOwnerScopeVerifier(
        selector=grant.selector,
        scope_locker=world.locker,
        qualification_provider=qualifier,
        audit=audit,
        using="default",
        environment="development",
    )
    use_case = build_audited_tax_liability_use_case(
        scope_verifier=scope, using="default", audit=audit
    )
    return candidate, grant, qualifier, use_case


def _execute(service, candidate, use_case, *, operation="actual-withholding-1"):
    return use_case.execute(
        candidate,
        actor_user_id=service.world.user.pk,
        operation_id=operation,
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )


def test_native_nonstaff_withholding_and_old_source_retry_preserve_original_evidence(owner_service):
    service = owner_service
    candidate, grant, qualifier, use_case = _financial_service(service)
    assert not service.world.user.is_staff and not service.world.user.is_superuser
    first = _execute(service, candidate, use_case)
    calls = qualifier.calls
    service.world.row.refresh_from_db()
    updated_at = service.world.row.updated_at
    assert updated_at > service.world.source.row_updated_at
    second = _execute(service, candidate, use_case)
    assert second == replace(first, disposition=TaxLiabilityAppendDisposition.EXACT_RETRY)
    assert qualifier.calls == calls  # Original replay is read-only, not a new legal assessment.
    service.world.row.refresh_from_db()
    assert service.world.row.updated_at == updated_at
    assert service.world.row.current_cash == 10000 - candidate.calculation.withholding_amount
    assert Operation.objects.count() == 1
    assert grant.supports_capability(Capability.TAX_WITHHOLD)


@pytest.mark.parametrize("withdrawal", ["grant", "role"])
def test_native_withholding_retry_still_requires_current_consent_and_role(
    owner_service, withdrawal
):
    service = owner_service
    candidate, grant, _, use_case = _financial_service(service)
    _execute(service, candidate, use_case)
    if withdrawal == "grant":
        revoke_authenticated_simulated_corporate_action_grant(
            service.request,
            selector=grant.selector,
            revocation_id="native-financial-owner-withdrawal",
            revocation_version="1",
            using="default",
        )
    else:
        AccountProfileModel.objects.filter(user_id=service.world.user.pk).update(
            rbac_role="read_only"
        )
    with pytest.raises((BusinessLogicError, AuthorizationError)):
        _execute(service, candidate, use_case)
    assert Operation.objects.count() == 1


def test_native_old_source_replay_cannot_authorize_a_different_financial_operation(owner_service):
    service = owner_service
    candidate, _, _, use_case = _financial_service(service)
    first = _execute(service, candidate, use_case)
    with pytest.raises(BusinessLogicError):
        _execute(service, candidate, use_case, operation="different-operation-with-old-source")
    service.world.row.refresh_from_db()
    assert service.world.row.current_cash == 10000 + first.cash_delta
    assert Operation.objects.count() == 1


def test_native_final_current_tax_change_rolls_back_all_financial_effects(owner_service):
    service = owner_service
    candidate, _, _, use_case = _financial_service(service, fail_exit=True)
    with pytest.raises(BusinessLogicError, match="qualification changed"):
        _execute(service, candidate, use_case)
    service.world.row.refresh_from_db()
    assert service.world.row.current_cash == 10000
    assert service.world.row.updated_at == service.world.source.row_updated_at
    assert Operation.objects.count() == 0


def test_native_assessment_only_current_grant_cannot_collect_tax(owner_service):
    """A genuine current read/assessment consent supplies no cash-withholding right."""
    service = owner_service
    candidate, previous, _, _ = _financial_service(service)
    world = service.world
    command = replace(
        _v2_command(world, selected=(Capability.TAX_ASSESS,)),
        grant_version="assessment-only-successor",
        expected_predecessor_content_hash=previous.content_hash,
        valid_until=timezone.now() + timedelta(minutes=2),
    )
    grant = issue_authenticated_simulated_corporate_action_grant(
        service.request, command=command, scope_locker=world.locker, using="default"
    )
    assert grant.capabilities == (Capability.TAX_ASSESS,)
    audit = build_tax_assessment_audit_coordinator(using="default")
    scope = DjangoTaxLiabilityOwnerScopeVerifier(
        selector=grant.selector,
        scope_locker=world.locker,
        qualification_provider=_ControlledTaxFacts(world.source.account_id),
        audit=audit,
        using="default",
        environment="development",
    )
    use_case = build_audited_tax_liability_use_case(
        scope_verifier=scope, using="default", audit=audit
    )
    with pytest.raises(BusinessLogicError):
        _execute(service, candidate, use_case)
    world.row.refresh_from_db()
    assert world.row.current_cash == 10000
    assert Operation.objects.count() == 0
