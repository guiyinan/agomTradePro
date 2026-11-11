"""Native non-staff grant-backed financial, Audit and Outbox transaction contracts."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.simulated_corporate_action_write_issuance_composition import (
    issue_authenticated_simulated_corporate_action_grant,
    revoke_authenticated_simulated_corporate_action_grant,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    DjangoAuditedCorporateActionPostingRepositoryFactory,
    _event_id,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from core.exceptions import AuthorizationError, BusinessLogicError
from core.integration.config_center_runtime import get_active_runtime_value_evidence
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    _request as authenticated_request,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.component.simulated_trading import (
    test_corporate_action_posting_postgres as posting_fixtures,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    audit_runtime_patch,
    create_owner_account_seed,
    issue_current_owner_audit_selector,
    publish_current_owner_policy,
)

pytestmark = pytest.mark.django_db(
    transaction=True, available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
)


@pytest.fixture
def owner_service(owner_world, settings):
    """Use independent real global Audit authority and a genuine non-staff consent."""
    world = owner_world
    settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
    audit_seed = create_owner_account_seed()
    publish_current_owner_policy(audit_seed)
    audit_selector = issue_current_owner_audit_selector(audit_seed)
    activate_runtime_profile_patch(
        environment="development",
        patch=audit_runtime_patch(audit_selector),
        actor="native-audit-service-bootstrap",
        reason="require real Audit and Outbox for owner stage writes",
    )
    evidence = get_active_runtime_value_evidence(
        environment="development",
        definition_key=policies.SIMULATED_ACTION_WRITE_POLICY_KEY,
        as_of=timezone.now(),
    )
    assert evidence is not None
    policy_hash = policies._hash(
        {
            "policy": evidence.value["policies"][0],
            "profile_id": evidence.profile_id,
            "profile_version": evidence.profile_version,
            "profile_hash": evidence.profile_content_hash,
            "snapshot_id": evidence.snapshot_id,
            "snapshot_hash": evidence.snapshot_hash,
            "effective_at": evidence.effective_at.isoformat(),
        }
    )
    command = replace(
        world.command,
        expected_binding=replace(world.command.expected_binding, policy_content_hash=policy_hash),
        valid_until=timezone.now() + timedelta(minutes=2),
    )
    request = authenticated_request(world.user)
    grant = issue_authenticated_simulated_corporate_action_grant(
        request, command=command, scope_locker=world.locker, using="default"
    )
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=grant.selector,
        scope_locker=world.locker,
        using="default",
        environment="development",
    )
    repository = DjangoAuditedCorporateActionPostingRepositoryFactory(
        environment="development", owner_grant_gate=gate
    ).build_posting_repository(
        source_qualifier=posting_fixtures._SourceVerifier(),
        ownership_verifier=posting_fixtures._OwnershipVerifier(),
        tax_basis_verifier=None,
        using="default",
    )
    yield SimpleNamespace(
        world=world,
        grant=grant,
        request=request,
        repository=repository,
        stage=posting_fixtures._request(world.row),
    )


def test_native_nonstaff_owner_stage_commits_exact_grant_audit_and_replays(owner_service):
    """A lost response reuses one signed grant, one ledger entry and one Audit/Outbox pair."""
    service = owner_service
    before_events = SystemAuditEventModel.objects.count()
    before_outbox = SystemAuditOutboxModel.objects.count()
    first = service.repository.post_revision_with_audit((service.stage,))[0]
    second = service.repository.post_revision_with_audit((service.stage,))[0]
    assert first.entry_id == second.entry_id
    assert not first.replayed and second.replayed
    assert CorporateActionPostingModel.objects.filter(account=service.world.row).count() == 1
    assert SystemAuditEventModel.objects.count() == before_events + 1
    assert SystemAuditOutboxModel.objects.count() == before_outbox + 1
    event = service.repository._coordinator.get_winner(
        event_id=_event_id(service.stage),
        event_version="1",
        as_of=timezone.now(),
    )
    assert event is not None
    grant_refs = [ref for ref in event.evidence_refs if ref.owner == "account"]
    assert len(grant_refs) == 1
    assert grant_refs[0].artifact_id == service.grant.grant_id
    assert grant_refs[0].artifact_version == service.grant.grant_version
    assert grant_refs[0].content_hash == service.grant.content_hash
    assert event.scope.tenant_id == service.grant.binding.tenant_id
    assert event.scope.owner_id == service.grant.binding.owner_id
    assert not service.world.user.is_staff and not service.world.user.is_superuser


@pytest.mark.parametrize("withdrawal", ["grant", "role"])
def test_native_owner_withdrawal_blocks_stage_and_its_exact_replay(owner_service, withdrawal):
    """An existing winner never bypasses current explicit consent and trading eligibility."""
    service = owner_service
    service.repository.post_revision_with_audit((service.stage,))
    baseline = (
        CorporateActionPostingModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )
    if withdrawal == "grant":
        revoke_authenticated_simulated_corporate_action_grant(
            service.request,
            selector=service.grant.selector,
            revocation_id="native-service-withdrawal",
            revocation_version="1",
            using="default",
        )
    else:
        AccountProfileModel.objects.filter(user_id=service.world.user.pk).update(
            rbac_role="read_only"
        )
    with pytest.raises((CorporateActionPostingBlockedError, AuthorizationError)):
        service.repository.post_revision_with_audit((service.stage,))
    assert baseline == (
        CorporateActionPostingModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )


@pytest.mark.parametrize("failure", ["audit_append", "late_role_revocation", "late_policy_change"])
def test_native_owner_authority_failure_rolls_back_financial_audit_and_outbox(
    owner_service, monkeypatch, failure
):
    """A failure after a real append rolls back every participant in the outer owner UOW."""
    service = owner_service
    service.world.row.refresh_from_db()
    original_value = service.world.row.total_value
    baseline = (
        CorporateActionPostingModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )
    coordinator = service.repository._coordinator
    original = type(coordinator).append_and_enqueue

    def append_then_fail(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self is not coordinator:
            return result
        if failure == "audit_append":
            raise BusinessLogicError("injected failure after durable Audit/Outbox inserts")
        if failure == "late_role_revocation":
            AccountProfileModel.objects.filter(user_id=service.world.user.pk).update(
                rbac_role="read_only"
            )
        else:
            activate_runtime_profile_patch(
                environment="development",
                patch={
                    policies.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                        "schema_version": "simulated-corporate-action-write-policies.v1",
                        "enabled": False,
                        "policies": [],
                    }
                },
                actor="native-late-policy-change",
                reason="invalidate the exact runtime lineage before financial commit",
            )
        return result

    monkeypatch.setattr(type(coordinator), "append_and_enqueue", append_then_fail)
    with pytest.raises((BusinessLogicError, AuthorizationError)):
        service.repository.post_revision_with_audit((service.stage,))
    assert baseline == (
        CorporateActionPostingModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )
    service.world.row.refresh_from_db()
    assert service.world.row.total_value == original_value
    assert AccountProfileModel.objects.get(user_id=service.world.user.pk).rbac_role != "read_only"
