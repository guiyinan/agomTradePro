"""Financial Audit identity does not refresh clocks or accept changed intent silently."""

from dataclasses import replace

from apps.audit.domain.system_audit_event import AuditWritePolicy
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_audit import (
    build_tax_liability_audit_event,
    tax_liability_operation_artifact_id,
)
from tests.unit.simulated_trading.test_corporate_action_tax_liability_evidence import _material


def test_original_partial_tax_cash_journal_has_exact_owner_grant_and_component_refs():
    material = _material()
    event = build_tax_liability_audit_event(material, predecessor_hash=None)
    event.validate_hashes()
    assert event == build_tax_liability_audit_event(material, predecessor_hash=None)
    assert event.scope == material.origin.scope
    assert event.write_policy is AuditWritePolicy.TRANSACTIONAL_OUTBOX
    assert event.recorded_at == material.recorded_at
    assert event.detail["cash_delta"] == "-0.5"
    assert event.detail["automatic_trade"] is False
    grant = [ref for ref in event.evidence_refs if ref.owner == "account"]
    assert (
        len(grant) == 1
        and grant[0].content_hash == material.origin.lease.authority_grant_content_sha256
    )


def test_same_operation_slot_retains_identity_when_intent_changes():
    material = _material()
    altered = replace(material.identity, cash_action=None)
    assert altered.request_sha256 != material.identity.request_sha256
    assert tax_liability_operation_artifact_id(altered) == tax_liability_operation_artifact_id(
        material.identity
    )
