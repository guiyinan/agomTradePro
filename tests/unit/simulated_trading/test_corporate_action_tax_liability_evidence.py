"""Original financial context cannot be refreshed or rebound by public rehashing."""

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.application.corporate_action_tax_liability import (
    TaxLiabilityEvidenceReference,
)
from apps.simulated_trading.application.corporate_action_tax_liability_authority import (
    TaxLiabilityAuditOrigin,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    TaxLiabilityCashAction,
    TaxLiabilityCashRequest,
    plan_corporate_action_tax_liability,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_audit import (
    build_tax_liability_audit_event,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_codec import (
    canonical_liability_json,
    tax_liability_scope_sha256,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_evidence import (
    TaxLiabilityOperationMaterial,
    _instant,
    decode_operation_material,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_liability import _taxable_assessment
from tests.unit.simulated_trading.test_corporate_action_tax_liability_application import (
    _NOW,
    _lease,
    _snapshot,
)
from tests.unit.simulated_trading.test_corporate_action_tax_liability_identity import _identity
from tests.unit.simulated_trading.test_corporate_action_tax_payment_basis import _basis


def _material():
    assessment = _taxable_assessment()
    identity = _identity()
    lease = replace(
        _lease(assessment), operation_id=identity.operation_id, cash_action=identity.cash_action
    )
    qualification = CurrentTaxAssessmentQualification(
        assessment_semantic_sha256=assessment.semantic_sha256,
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        canonical_account_id=lease.canonical_account_id,
        environment="synthetic-test",
        qualification_id="synthetic-qualification",
        qualification_sha256="a" * 64,
        runtime_profile_id="synthetic-tax-profile",
        runtime_profile_content_sha256="b" * 64,
        runtime_snapshot_id="synthetic-tax-snapshot",
        runtime_snapshot_sha256="c" * 64,
        valid_until=lease.valid_until,
    )
    before = _NOW - timedelta(minutes=1)
    origin = TaxLiabilityAuditOrigin(
        lease=lease,
        environment="synthetic-test",
        account_source_id="synthetic-account-source",
        account_source_version="1",
        account_source_sha256="d" * 64,
        source_row_updated_at=before,
        qualification=qualification,
        write_mode="append",
    )
    snapshot = _snapshot(assessment, lease, book_cash=Decimal("0.50"), observed_at=_NOW)
    provenance = canonical_liability_json(
        {
            "schema": "simulated-tax-cash-snapshot.v1",
            "account_id": lease.physical_account_id,
            "owner_user_id": lease.owner_user_id,
            "canonical_account_namespace": "account",
            "canonical_account_id": lease.canonical_account_id,
            "currency": "CNY",
            "scope_sha256": tax_liability_scope_sha256(lease.scope),
            "book_cash": "0.5",
            "reserved_cash": "0",
            "physical_updated_at": _instant(before),
            "observed_at": _instant(_NOW),
            "active_holds": [],
        }
    )
    snapshot_hash = hashlib.sha256(provenance.encode()).hexdigest()
    snapshot = replace(
        snapshot,
        evidence=TaxLiabilityEvidenceReference(
            f"tax-cash-snapshot:{snapshot_hash}", "v1", snapshot_hash
        ),
    )
    transition = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=TaxLiabilityCashRequest(
            TaxLiabilityCashAction.COLLECT_AVAILABLE, Decimal("0.50"), Decimal("0")
        ),
    )
    return TaxLiabilityOperationMaterial(
        assessment_id=1,
        identity=identity,
        transition=transition,
        sequence=1,
        predecessor_operation_sha256=None,
        origin=origin,
        cash_snapshot=snapshot,
        cash_before=Decimal("0.50"),
        cash_after=Decimal("0"),
        physical_updated_before=before,
        physical_updated_after=_NOW,
        recorded_at=_NOW,
        cash_snapshot_provenance_json=provenance,
    )


def test_stored_financial_origin_round_trip_preserves_all_original_clocks_and_refs():
    original = _material()
    restored = decode_operation_material(
        original.payload_json,
        original.content_sha256,
        identity=original.identity,
        transition=original.transition,
    )
    assert restored == original
    assert restored.recorded_at == _NOW
    assert restored.origin.qualification == original.origin.qualification
    assert restored.cash_snapshot.evidence == original.cash_snapshot.evidence


def test_v1_financial_material_bytes_remain_exact_without_payment_basis():
    """Existing immutable receipts must retain their original canonical identity."""
    original = _material()
    assert len(original.payload_json.encode()) == 3513
    assert original.content_sha256 == (
        "ddf56f05e238528e7244e46e39664407714d63f70dab957c2b0076a0bc5d309a"
    )


def test_untyped_payment_basis_cannot_enter_a_financial_origin():
    """A JSON-like claim is not a verified typed payment basis."""
    with pytest.raises(BusinessLogicError):
        replace(_material().origin, payment_basis=object())


@pytest.mark.parametrize(
    "changes",
    [
        {"cash_after": Decimal("0.01")},
        {"sequence": 2},
        {"physical_updated_after": _NOW - timedelta(seconds=1)},
        {"cash_before": Decimal("1e-10000000")},
    ],
)
def test_inconsistent_financial_context_is_rejected_before_encoding(changes):
    with pytest.raises(BusinessLogicError):
        replace(_material(), **changes)


def test_read_only_retry_origin_cannot_create_a_new_financial_record():
    original = _material()
    with pytest.raises(BusinessLogicError):
        replace(original, origin=replace(original.origin, write_mode="exact_retry_only"))


def test_rehashed_unknown_provenance_field_cannot_be_silently_ignored():
    original = _material()
    fields = json.loads(original.payload_json)
    fields["origin"]["lease"]["implicit_permission"] = True
    payload = json.dumps(fields, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    with pytest.raises(BusinessLogicError):
        decode_operation_material(
            payload,
            hashlib.sha256(payload.encode()).hexdigest(),
            identity=original.identity,
            transition=original.transition,
        )


def _paid_material() -> TaxLiabilityOperationMaterial:
    """Bind the synthetic full-account payment to the exact taxable source fixture."""
    original = _material()
    action = _taxable_assessment().action
    basis = _basis(
        source_revision_id=action.source_revision_id,
        source_revision_sha256=action.source_revision_sha256,
        source_payload_sha256=action.source_payload_sha256,
        grant_account_id=original.origin.lease.canonical_account_id,
    )
    return replace(original, origin=replace(original.origin, payment_basis=basis))


def test_v2_financial_material_round_trips_complete_original_paid_basis():
    original = _paid_material()
    assert json.loads(original.payload_json)["schema"] == "simulated-tax-liability-material.v2"
    restored = decode_operation_material(
        original.payload_json,
        original.content_sha256,
        identity=original.identity,
        transition=original.transition,
    )
    assert restored == original
    assert restored.origin.payment_basis == original.origin.payment_basis


def test_paid_basis_for_another_canonical_account_cannot_enter_material():
    original = _paid_material()
    with pytest.raises(BusinessLogicError, match="canonical account"):
        replace(
            original,
            origin=replace(
                original.origin,
                payment_basis=replace(original.origin.payment_basis, grant_account_id="other"),
            ),
        )


def test_v1_audit_bytes_remain_exact_and_v2_links_the_complete_payment_proof():
    legacy = build_tax_liability_audit_event(_material(), predecessor_hash=None)
    assert legacy.content_hash == (
        "c9793131f1f6fa57502822b881344e68bfd8dbe0838dff08545f0ed4d5b54239"
    )
    material = _paid_material()
    event = build_tax_liability_audit_event(material, predecessor_hash=None)
    refs = {ref.artifact_type: ref for ref in event.evidence_refs}
    assert refs["tax_liability_operation"].artifact_version == "v2"
    assert refs["simulated_dividend_payment_basis"].content_hash == (
        material.origin.payment_basis.content_sha256
    )
