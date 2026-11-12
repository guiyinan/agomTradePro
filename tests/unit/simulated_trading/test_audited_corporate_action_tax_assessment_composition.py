"""Audit provenance and orphan-proof rejection without substituting live authority."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditScopeRef, AuditWritePolicy
from apps.simulated_trading import (
    audited_corporate_action_tax_assessment_composition as composition,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_repository import (
    StoredTaxAssessment,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import _assessment
from tests.unit.simulated_trading.test_corporate_action_tax_assessment_application import _lease


def _header() -> Header:
    assessment = _assessment()
    return Header(
        pk=1,
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        authority_grant_id="fixture-grant",
        authority_grant_version="actual-opaque-version",
        authority_grant_sha256="e" * 64,
        audit_tenant_id="synthetic-tax-tenant",
        audit_owner_id="user:11",
        assessment_revision_id=assessment.assessment_revision_id,
        asset_code=assessment.asset_code,
        security_id=assessment.security_id,
        corporate_action_id=assessment.action.corporate_action_id,
        source_event_id=assessment.action.source_event_id,
        action_source_revision_id=assessment.action.source_revision_id,
        record_date=assessment.history.record_date,
        settlement_date=assessment.target_settlement_date,
        policy_source_identity=assessment.policy.source_identity,
        policy_sha256=assessment.policy.policy_sha256,
        statutory_revision_set_sha256=assessment.statutory_source_bundle.source_revision_set_sha256,
        disposition_id=assessment.calculation.disposition_id,
        idempotency_key=assessment.calculation.idempotency_key,
        semantic_sha256=assessment.semantic_sha256,
        observation_manifest_json=assessment.observation_manifest_json,
        observation_manifest_sha256=assessment.observation_manifest_sha256,
        withholding_amount_text="1",
        recorded_at=timezone.now(),
    )


def test_grant_evidence_preserves_exact_original_opaque_version_and_content_hash() -> None:
    header = _header()
    event = composition._build_event(header, sequence_no=1, predecessor_hash=None)
    evidence = next(ref for ref in event.evidence_refs if ref.owner == "account")
    assert evidence.artifact_id == header.authority_grant_id
    assert evidence.artifact_version == header.authority_grant_version
    assert evidence.content_hash == header.authority_grant_sha256


def test_orphan_outbox_blocks_before_any_audit_append(monkeypatch: pytest.MonkeyPatch) -> None:
    assessment = _assessment()
    header = _header()
    lease = replace(
        _lease(assessment),
        authority_grant_id=header.authority_grant_id,
        authority_grant_version=header.authority_grant_version,
    )
    origin = composition.TaxAssessmentAuditOrigin(
        lease,
        AuditScopeRef(header.audit_tenant_id, header.audit_owner_id),
        header.authority_grant_sha256,
        AuditWritePolicy.TRANSACTIONAL_OUTBOX,
    )
    verifier = Mock(database_alias="default")
    verifier.get_locked_audit_origin.return_value = origin
    audit = Mock(database_alias="default")
    audit.get_winner_targeted.return_value = None
    audit.get_current_head_targeted.return_value = None
    audit.get_exact_outbox_winner_targeted.return_value = object()
    audit.append_and_enqueue_targeted.side_effect = (
        lambda event, **kwargs: SystemAuditEventOutboxCommit(
            event, uuid4(), event.event_id, event.idempotency_key
        )
    )
    clock = Mock()
    # Keep the explicit test lease live independently of the actual wall clock.
    clock.now.return_value = header.recorded_at
    lease = replace(lease, valid_until=header.recorded_at.replace(year=header.recorded_at.year + 1))
    verifier.get_locked_audit_origin.return_value = replace(origin, lease=lease)
    unit = composition.DjangoTaxAssessmentAtomicUnitOfWork(
        using="default", scope_verifier=verifier, audit=audit, clock=clock
    )
    unit._active = True
    unit._repository = Mock()
    unit._repository.append_locked.return_value = StoredTaxAssessment(header, False)
    monkeypatch.setattr(
        composition, "connections", {"default": SimpleNamespace(in_atomic_block=True)}
    )
    with pytest.raises(BusinessLogicError):
        unit.append_with_audit_outbox(assessment, actor_user_id=assessment.owner_user_id)
    audit.append_and_enqueue_targeted.assert_not_called()
