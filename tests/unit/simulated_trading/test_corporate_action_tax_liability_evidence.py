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
