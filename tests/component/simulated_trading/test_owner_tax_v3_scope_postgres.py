"""Actual V3 authority and audited payment/tax storage with synthetic tax facts.

These are concrete permission and financial-journal contracts. They do not
qualify actual current official windows, taxpayer status, or legal applicability.
"""

from dataclasses import replace

import pytest
from django.db import connection
from django.utils import timezone

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.simulated_corporate_action_write_issuance_composition import (
    issue_authenticated_simulated_corporate_action_grant,
    revoke_authenticated_simulated_corporate_action_grant,
)
from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentAppendDisposition,
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
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel as Operation,
)
from core.exceptions import AuthorizationError, BusinessLogicError
from tests.component.account.test_simulated_corporate_action_capability_issuance_postgres import (
    _v3_command,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.component.simulated_trading.test_owner_granted_corporate_action_postgres import (
    owner_service as owner_service,
)
from tests.component.simulated_trading.test_owner_tax_assessment_scope_postgres import (
    _ControlledTaxFacts,
)
from tests.component.simulated_trading.test_owner_tax_liability_scope_postgres import (
    _execute,
    _financial_service,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="Actual native V3 financial scope"
    ),
    pytest.mark.django_db(transaction=True, available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS),
]


@pytest.fixture(autouse=True)
def _isolated_tax_channels():
    """Keep real authority setup on the same isolated channels as the native cohort."""
    with isolated_task_channels():
        yield


def _v3_service(service, *, paid=True):
    """Upgrade explicit V2 consent without altering its retained assessment or payment."""
    candidate, predecessor, _, _ = _financial_service(service, paid=paid)
    world = service.world
    prepared = _v3_command(world, selected=(Capability.TAX_ASSESS, Capability.TAX_WITHHOLD))
    now = timezone.now()
    policy = policies.read_current_simulated_action_write_policy(
        canonical_account_id=world.source.account_id,
        owner_user_id=world.user.pk,
        environment="development",
        as_of=now,
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    command = replace(
        prepared,
        grant_id=predecessor.grant_id,
        expected_predecessor_content_hash=predecessor.content_hash,
        valid_until=policy.grant_valid_until(
            as_of=now, source_valid_until=world.source.valid_until
        ),
    )
    grant = issue_authenticated_simulated_corporate_action_grant(
        service.request, command=command, scope_locker=world.locker, using="default"
    )
    assert grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    assert not grant.supports_capability(Capability.SHARE_STAGE_WRITE)
    assert not grant.supports_capability(Capability.RIGHTS_NOT_EXERCISED)
    assessment_scope = DjangoTaxAssessmentOwnerScopeVerifier(
        selector=grant.selector,
        scope_locker=world.locker,
        qualification_provider=_ControlledTaxFacts(world.source.account_id),
        using="default",
        environment="development",
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    assessment = build_audited_tax_assessment_use_case(
        scope_verifier=assessment_scope, using="default"
    ).execute(candidate, actor_user_id=world.user.pk)
    assert assessment.disposition is TaxAssessmentAppendDisposition.EXACT_RETRY
    audit = build_tax_assessment_audit_coordinator(using="default")
    qualifier = _ControlledTaxFacts(world.source.account_id)
    financial_scope = DjangoTaxLiabilityOwnerScopeVerifier(
        selector=grant.selector,
        scope_locker=world.locker,
        qualification_provider=qualifier,
        audit=audit,
        using="default",
        environment="development",
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    use_case = build_audited_tax_liability_use_case(
        scope_verifier=financial_scope, using="default", audit=audit
    )
    return candidate, grant, qualifier, use_case


@pytest.mark.parametrize("withdrawal", ["grant", "role"])
def test_native_v3_paid_tax_collection_replays_original_then_requires_current_authority(
    owner_service, withdrawal
):
    """V3 tax-only consent preserves old payment/assessment evidence and current withdrawal."""
    service = owner_service
    candidate, grant, qualifier, use_case = _v3_service(service)
    assert not service.world.user.is_staff and not service.world.user.is_superuser
    first = _execute(service, candidate, use_case)
    assert first.payment_basis_reference is not None
    calls = qualifier.calls
    second = _execute(service, candidate, use_case)
    assert second == replace(first, disposition=TaxLiabilityAppendDisposition.EXACT_RETRY)
    assert qualifier.calls == calls
    service.world.row.refresh_from_db()
    assert (
        service.world.row.current_cash
        == service.financial_cash_before - candidate.calculation.withholding_amount
    )
    assert Operation.objects.count() == 1
    if withdrawal == "grant":
        revoke_authenticated_simulated_corporate_action_grant(
            service.request,
            selector=grant.selector,
            revocation_id="native-v3-tax-withdrawal",
            revocation_version="1",
            using="default",
        )
    else:
        AccountProfileModel.objects.filter(user_id=service.world.user.pk).update(
            rbac_role="read_only"
        )
    baseline = (
        Operation.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )
    with pytest.raises((BusinessLogicError, AuthorizationError)):
        _execute(service, candidate, use_case)
    assert baseline == (
        Operation.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )


def test_native_v3_current_tax_grant_cannot_collect_an_unpaid_dividend(owner_service):
    """Schema upgrade adds no substitute for the actual same-event audited cash payment."""
    service = owner_service
    candidate, _, _, use_case = _v3_service(service, paid=False)
    service.world.row.refresh_from_db()
    before = (service.world.row.current_cash, service.world.row.updated_at)
    baseline = (
        Operation.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )
    with pytest.raises(BusinessLogicError) as blocked:
        _execute(service, candidate, use_case)
    assert blocked.value.code == "SIMULATED_DIVIDEND_PAYMENT_BASIS_BLOCKED"
    service.world.row.refresh_from_db()
    assert (service.world.row.current_cash, service.world.row.updated_at) == before
    assert baseline == (
        Operation.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )
