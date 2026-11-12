"""Native owner-grant capability checks at the audited cash posting boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository,
)
from apps.account.simulated_corporate_action_consent_terms import (
    SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
)
from apps.account.simulated_corporate_action_write_issuance_composition import (
    issue_authenticated_simulated_corporate_action_grant,
    revoke_authenticated_simulated_corporate_action_grant,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
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
from core.exceptions import AuthorizationError
from tests.component.account.test_simulated_corporate_action_consent_capabilities_http import (
    TERMS_SHA256,
    _publish_known_policy,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    _request as authenticated_request,
)
from tests.component.simulated_trading.test_corporate_action_posting_postgres import (
    _OwnershipVerifier,
    _SourceVerifier,
)
from tests.component.simulated_trading.test_owner_granted_corporate_action_postgres import (
    owner_service as owner_service,
)
from tests.component.simulated_trading.test_owner_granted_corporate_action_postgres import (
    owner_world as owner_world,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Native PostgreSQL owner-grant contract; SQLite must skip explicitly.",
    ),
]


def _v2_cash_repository(service, *, capabilities, valid_for=timedelta(minutes=2)):
    """Upgrade the real V1 owner chain and bind a repository to its V2 schema."""
    _publish_known_policy(version="native-owner-capability-v2")
    policy = policies.read_current_simulated_action_write_policy(
        canonical_account_id=service.world.source.account_id,
        owner_user_id=service.world.user.pk,
        environment="development",
        as_of=timezone.now(),
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    )
    now = timezone.now()
    command = replace(
        service.world.command,
        grant_id=service.grant.grant_id,
        grant_version="native-owner-capability-v2",
        expected_binding=replace(
            service.world.command.expected_binding,
            policy_version=policy.policy_version,
            policy_content_hash=policy.content_hash,
        ),
        valid_until=min(now + valid_for, policy.valid_until),
        expected_predecessor_content_hash=service.grant.content_hash,
        grant_schema=policy.grant_schema,
        capabilities=capabilities,
        terms_version=policy.terms_version,
        terms_sha256=policy.terms_sha256,
    )
    assert policy.terms_version == SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2
    assert policy.terms_sha256 == TERMS_SHA256
    grant = issue_authenticated_simulated_corporate_action_grant(
        authenticated_request(service.world.user),
        command=command,
        scope_locker=service.world.locker,
        using="default",
    )
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=grant.selector,
        scope_locker=service.world.locker,
        using="default",
        environment="development",
        expected_grant_schema=policy.grant_schema,
    )
    repository = DjangoAuditedCorporateActionPostingRepositoryFactory(
        environment="development", owner_grant_gate=gate
    ).build_posting_repository(
        source_qualifier=_SourceVerifier(),
        ownership_verifier=_OwnershipVerifier(),
        tax_basis_verifier=None,
        using="default",
    )
    return grant, repository


def test_native_v2_cash_grant_posts_replays_and_withdrawal_blocks(owner_service):
    """A same-chain V2 cash grant is the exact Audit evidence and gates exact replay."""
    service = owner_service
    capabilities = tuple(
        sorted(
            (Capability.CASH_STAGE_WRITE, Capability.TAX_ASSESS),
            key=lambda capability: capability.value,
        )
    )
    grant, repository = _v2_cash_repository(service, capabilities=capabilities)
    assert grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    assert grant.identity_hash == service.grant.identity_hash
    assert grant.supersedes_content_hash == service.grant.content_hash
    assert grant.capabilities == capabilities
    assert grant.supports_capability(Capability.CASH_STAGE_WRITE)
    assert grant.supports_capability(Capability.TAX_ASSESS)
    assert not grant.supports_capability(Capability.TAX_WITHHOLD)

    before_events = SystemAuditEventModel.objects.count()
    before_outbox = SystemAuditOutboxModel.objects.count()
    first = repository.post_revision_with_audit((service.stage,))[0]
    replay = repository.post_revision_with_audit((service.stage,))[0]
    assert first.entry_id == replay.entry_id
    assert not first.replayed and replay.replayed
    assert CorporateActionPostingModel.objects.filter(account=service.world.row).count() == 1
    assert SystemAuditEventModel.objects.count() == before_events + 1
    assert SystemAuditOutboxModel.objects.count() == before_outbox + 1
    event = repository._coordinator.get_winner(
        event_id=_event_id(service.stage), event_version="1", as_of=timezone.now()
    )
    assert event is not None
    grant_refs = [ref for ref in event.evidence_refs if ref.owner == "account"]
    assert len(grant_refs) == 1
    assert grant_refs[0].artifact_id == grant.grant_id
    assert grant_refs[0].artifact_version == grant.grant_version
    assert grant_refs[0].content_hash == grant.content_hash
    with repository._coordinator.atomic():
        outbox = repository._coordinator.get_exact_outbox_winner_targeted(event)
        assert outbox is not None and outbox.event == event

    revoke_authenticated_simulated_corporate_action_grant(
        authenticated_request(service.world.user),
        selector=grant.selector,
        revocation_id="native-v2-cash-withdrawal",
        revocation_version="1",
        using="default",
    )
    committed_counts = (
        CorporateActionPostingModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )
    with pytest.raises((CorporateActionPostingBlockedError, AuthorizationError)):
        repository.post_revision_with_audit((service.stage,))
    assert committed_counts == (
        CorporateActionPostingModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )


def test_native_tax_only_v2_current_head_denies_cash_without_v1_fallback(owner_service):
    """A current tax-only successor cannot revive the historical V1 cash grant."""
    service = owner_service
    grant, repository = _v2_cash_repository(
        service,
        capabilities=(Capability.TAX_ASSESS,),
    )
    assert grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    assert grant.supersedes_content_hash == service.grant.content_hash
    assert not grant.supports_capability(Capability.CASH_STAGE_WRITE)
    heads = DjangoSimulatedCorporateActionWriteGrantRepository().get_current_for_scope(
        "simulated", service.world.source.account_id, as_of=timezone.now()
    )
    assert len(heads) == 1
    assert heads[0] == grant

    baseline = (
        CorporateActionPostingModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )
    with pytest.raises(CorporateActionPostingBlockedError):
        repository.post_revision_with_audit((service.stage,))
    assert baseline == (
        CorporateActionPostingModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 2
