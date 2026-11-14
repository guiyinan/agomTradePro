"""Synthetic original window proofs are retained facts, never write authority."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
)
from apps.simulated_trading.application.corporate_action_tax_window_proof import (
    CorporateActionTaxWindowProof,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_window_codec import (
    decode_corporate_action_tax_window_proof,
    encode_corporate_action_tax_window_proof,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_current_official_window import (
    _NOW,
    _request,
)
from tests.unit.simulated_trading.test_corporate_action_window_audit_composition import _evidence


def _proof():
    return CorporateActionTaxWindowProof(
        "a" * 64, "synthetic-canonical-account", _request(), _evidence()
    )


def test_tax_window_proof_roundtrip_retains_all_original_fields_and_expiry():
    proof = _proof()
    payload = encode_corporate_action_tax_window_proof(proof)
    restored = decode_corporate_action_tax_window_proof(payload)
    assert restored == proof
    restored.assert_recorded_at(_NOW)
    with pytest.raises(BusinessLogicError):
        restored.assert_recorded_at(_NOW + timedelta(days=1))


def test_current_qualification_cannot_outlive_or_cross_the_retained_window():
    proof = _proof()
    qualification = CurrentTaxAssessmentQualification(
        assessment_semantic_sha256=proof.assessment_semantic_sha256,
        account_id=proof.source_reference.account_id,
        owner_user_id=proof.source_reference.owner_user_id,
        canonical_account_id=proof.canonical_account_id,
        environment=proof.evidence.runtime_environment,
        qualification_id="synthetic-current-tax-window",
        qualification_sha256="a" * 64,
        runtime_profile_id="synthetic-profile",
        runtime_profile_content_sha256="b" * 64,
        runtime_snapshot_id="synthetic-snapshot",
        runtime_snapshot_sha256="c" * 64,
        valid_until=proof.evidence.expires_at,
        official_window_proof=proof,
    )
    assert qualification.official_window_proof == proof
    with pytest.raises(BusinessLogicError):
        replace(qualification, valid_until=proof.evidence.expires_at + timedelta(seconds=1))
    with pytest.raises(BusinessLogicError):
        replace(qualification, owner_user_id=qualification.owner_user_id + 1)


def test_assessment_audit_rebuilds_original_window_without_live_sources():
    from apps.simulated_trading import audited_corporate_action_tax_assessment_composition as audit
    from apps.simulated_trading.corporate_action_tax_assessment_window_composition import (
        read_retained_tax_assessment_window_proof,
    )
    from tests.unit.simulated_trading.test_audited_corporate_action_tax_assessment_composition import (
        _header,
    )

    proof = _proof()
    source = proof.source_reference
    # This unsaved header tests serialization only; no assessment or source is issued.
    header = _header()
    header.recorded_at = _NOW
    header.semantic_sha256 = proof.assessment_semantic_sha256
    header.account_id = source.account_id
    header.owner_user_id = source.owner_user_id
    header.asset_code = source.asset_code
    header.security_id = source.security_id
    header.source_namespace = source.source_namespace
    header.source_event_id = source.source_event_id
    header.source_record_id = source.source_record_id
    header.action_source_revision_id = source.source_revision_id
    header.action_source_payload_sha256 = source.source_payload_sha256
    header.action_source_revision_sha256 = proof.evidence.selected_event_sha256
    header.record_date = source.record_date
    event = audit._build_event(
        header, sequence_no=1, predecessor_hash=None, official_window_proof=proof
    )
    original = read_retained_tax_assessment_window_proof(header, event)
    assert original == proof
    assert (
        audit._build_event(
            header, sequence_no=1, predecessor_hash=None, official_window_proof=original
        )
        == event
    )
    header.recorded_at = _NOW + timedelta(days=1)
    with pytest.raises(BusinessLogicError):
        read_retained_tax_assessment_window_proof(header, event)


def test_assessment_origin_rejects_a_window_from_another_lease_scope():
    from apps.audit.domain.system_audit_event import AuditScopeRef, AuditWritePolicy
    from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
        TaxAssessmentAuditOrigin,
    )
    from tests.unit.simulated_trading.test_corporate_action_tax_assessment import _assessment
    from tests.unit.simulated_trading.test_corporate_action_tax_assessment_application import _lease

    with pytest.raises(BusinessLogicError):
        TaxAssessmentAuditOrigin(
            _lease(_assessment()),
            AuditScopeRef("tenant", "owner"),
            "a" * 64,
            AuditWritePolicy.TRANSACTIONAL_OUTBOX,
            _proof(),
        )


@pytest.mark.parametrize("mutation", ("boolean", "extra", "owner", "source", "checked"))
def test_tax_window_proof_rejects_mutated_or_loosely_typed_original_material(mutation):
    payload = deepcopy(encode_corporate_action_tax_window_proof(_proof()))
    if mutation == "extra":
        payload["unknown"] = True
    elif mutation == "boolean":
        payload["evidence"]["window_ready"] = 1
    elif mutation == "owner":
        payload["evidence"]["owner_user_id"] += 1
    elif mutation == "source":
        payload["evidence"]["source_payload_sha256"] = "f" * 64
    else:
        payload["evidence"]["checked_at"] = (_NOW - timedelta(days=1)).isoformat()
    with pytest.raises(BusinessLogicError):
        decode_corporate_action_tax_window_proof(payload)
