from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.simulated_trading.application.corporate_action_tax_payment_basis import (
    SimulatedDividendPaymentBasis,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import TaxLiabilityScope
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import (
    _RECORD_DATE,
    _assessment,
)


def _basis(**overrides: object) -> SimulatedDividendPaymentBasis:
    """Return one synthetic, internally exact, fully referenced payment basis."""

    common = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
    entitlement_posted = datetime(2026, 11, 12, 4, 2, tzinfo=UTC)
    entitlement_audit = datetime(2026, 11, 12, 4, 3, tzinfo=UTC)
    payment_qualified = datetime(2026, 11, 12, 4, 10, tzinfo=UTC)
    payment_posted = datetime(2026, 11, 12, 4, 11, tzinfo=UTC)
    payment_audit = datetime(2026, 11, 12, 4, 12, tzinfo=UTC)
    facts: dict[str, object] = {
        "account_id": 7,
        "owner_user_id": 11,
        "security_id": "600000.SH",
        "asset_code": "equity-cn",
        "asset_name": "Synthetic Equity",
        "corporate_action_id": "synthetic-cash-dividend-v1",
        "source_namespace": "synthetic-disclosure",
        "source_record_id": "synthetic-record-1",
        "source_event_id": "synthetic-event-1",
        "source_revision_id": "synthetic-action-revision-1",
        "source_revision_sha256": "4" * 64,
        "source_payload_sha256": "5" * 64,
        "record_date": _RECORD_DATE,
        "effective_date": date(2025, 3, 10),
        "payment_date": date(2026, 11, 12),
        "dividend_per_share": Decimal("0.50"),
        "eligible_quantity": Decimal("70.000000"),
        "gross_entitlement_amount": Decimal("35.00"),
        "tax_treatment": "deferred_withholding",
        "qualification_sha256": "6" * 64,
        "qualifier_identity": "synthetic-qualifier-v1",
        "ownership_snapshot_id": "synthetic-record-date-owner-proof",
        "ownership_snapshot_sha256": "7" * 64,
        "ownership_snapshot_observed_at": common,
        "entitlement_calculation_sha256": "8" * 64,
        "grant_account_namespace": "simulated",
        "grant_account_id": "canonical-account-7",
        "entitlement_entry_id": 101,
        "entitlement_account_revision": 8,
        "entitlement_request_payload_sha256": "9" * 64,
        "entitlement_stage_date": _RECORD_DATE,
        "entitlement_source_observed_at": common,
        "entitlement_qualified_at": common,
        "entitlement_posted_at": entitlement_posted,
        "entitlement_row_created_at": entitlement_posted,
        "entitlement_audit_event_id": "corporate-action-entitlement-1",
        "entitlement_audit_event_version": "1",
        "entitlement_audit_event_sha256": "a" * 64,
        "entitlement_audit_recorded_at": entitlement_audit,
        "entitlement_audit_persisted_at": entitlement_audit,
        "entitlement_audit_sequence_no": 10,
        "entitlement_audit_predecessor_hash": "b" * 64,
        "entitlement_outbox_record_id": "00000000-0000-4000-8000-000000000101",
        "entitlement_outbox_payload_sha256": "a" * 64,
        "entitlement_outbox_created_at": entitlement_audit,
        "entitlement_grant_id": "synthetic-cash-grant",
        "entitlement_grant_version": "v1",
        "entitlement_grant_content_sha256": "c" * 64,
        "payment_entry_id": 102,
        "payment_account_revision": 9,
        "payment_request_payload_sha256": "d" * 64,
        "payment_stage_date": date(2026, 11, 12),
        "payment_source_observed_at": common,
        "payment_qualified_at": payment_qualified,
        "payment_posted_at": payment_posted,
        "payment_row_created_at": payment_posted,
        "payment_audit_event_id": "corporate-action-payment-1",
        "payment_audit_event_version": "1",
        "payment_audit_event_sha256": "e" * 64,
        "payment_audit_recorded_at": payment_audit,
        "payment_audit_persisted_at": payment_audit,
        "payment_audit_sequence_no": 11,
        "payment_audit_predecessor_hash": "a" * 64,
        "payment_outbox_record_id": "00000000-0000-4000-8000-000000000102",
        "payment_outbox_payload_sha256": "e" * 64,
        "payment_outbox_created_at": payment_audit,
        "payment_grant_id": "synthetic-cash-grant",
        "payment_grant_version": "v1",
        "payment_grant_content_sha256": "c" * 64,
    }
    facts.update(overrides)
    return SimulatedDividendPaymentBasis(**facts)  # type: ignore[arg-type]


def _scope(*, disposition_id: str = "sale-a") -> TaxLiabilityScope:
    """Return one test disposition sharing the same account-wide payment."""

    return TaxLiabilityScope(
        account_id=7,
        owner_user_id=11,
        security_id="600000.SH",
        asset_code="equity-cn",
        corporate_action_id="synthetic-cash-dividend-v1",
        source_namespace="synthetic-disclosure",
        logical_source_event_id="synthetic-event-1",
        target_disposition_id=disposition_id,
        record_date=_RECORD_DATE,
        target_settlement_date=date(2025, 3, 3),
    )


def test_paid_basis_round_trips_and_supports_multiple_dispositions() -> None:
    basis = _basis()
    assessment = _assessment()
    as_of = datetime(2026, 11, 12, 4, 30, tzinfo=UTC)

    assert SimulatedDividendPaymentBasis.from_payload(basis.to_payload()) == basis
    assert (
        basis.content_sha256
        == SimulatedDividendPaymentBasis.from_payload(basis.to_payload()).content_sha256
    )
    basis.verify_for(assessment, as_of=as_of)
    basis.verify_scope(_scope(disposition_id="sale-a"), as_of=as_of)
    basis.verify_scope(_scope(disposition_id="sale-b"), as_of=as_of)


@pytest.mark.parametrize(
    "scope",
    (
        replace(_scope(), owner_user_id=12),
        replace(_scope(), security_id="000001.SZ"),
        replace(_scope(), source_namespace="different-source"),
        replace(_scope(), logical_source_event_id="different-event"),
        replace(_scope(), record_date=date(2025, 2, 27)),
    ),
)
def test_paid_basis_rejects_different_action_scope(scope: TaxLiabilityScope) -> None:
    with pytest.raises(BusinessLogicError, match="payment basis"):
        _basis().verify_scope(scope, as_of=datetime(2026, 11, 12, 4, 30, tzinfo=UTC))


def test_payment_date_is_compared_in_shanghai_local_time() -> None:
    basis = _basis()

    with pytest.raises(BusinessLogicError, match="payment date has not been reached"):
        basis.verify_scope(_scope(), as_of=datetime(2026, 11, 11, 15, 59, tzinfo=UTC))

    with pytest.raises(BusinessLogicError, match="recorded after the operation cutoff"):
        basis.verify_scope(_scope(), as_of=datetime(2026, 11, 11, 16, 0, tzinfo=UTC))
    basis.verify_scope(_scope(), as_of=datetime(2026, 11, 12, 4, 30, tzinfo=UTC))


def test_payment_basis_rejects_any_evidence_recorded_after_operation_cutoff() -> None:
    with pytest.raises(BusinessLogicError, match="recorded after the operation cutoff"):
        _basis().verify_scope(_scope(), as_of=datetime(2026, 11, 12, 0, 10, tzinfo=UTC))


def test_payment_basis_rejects_a_cash_stage_date_after_operation_cutoff() -> None:
    basis = _basis(payment_stage_date=date(2026, 11, 13))

    with pytest.raises(BusinessLogicError, match="cash stage date has not been reached"):
        basis.verify_scope(_scope(), as_of=datetime(2026, 11, 12, 4, 30, tzinfo=UTC))


@pytest.mark.parametrize(
    "change",
    (
        {"source_revision_id": "other-revision"},
        {"source_revision_sha256": "f" * 64},
        {"source_payload_sha256": "f" * 64},
        {"effective_date": date(2025, 3, 11)},
        {
            "eligible_quantity": Decimal("69.000000"),
            "gross_entitlement_amount": Decimal("34.50"),
        },
    ),
)
def test_paid_basis_rejects_assessment_revision_or_full_entitlement_mismatch(
    change: dict[str, object],
) -> None:
    assessment = _assessment()
    basis = _basis(**change)
    with pytest.raises(BusinessLogicError):
        basis.verify_for(assessment, as_of=datetime(2026, 11, 12, 4, 30, tzinfo=UTC))


def test_paid_basis_blocks_fractional_cash_and_strictly_decodes_payload() -> None:
    with pytest.raises(BusinessLogicError, match="exact supported cent amount"):
        _basis(dividend_per_share=Decimal("0.5001"), gross_entitlement_amount=Decimal("35.01"))

    with pytest.raises(BusinessLogicError, match="lowercase SHA-256 digest"):
        replace(_basis(), entitlement_calculation_sha256=None)

    payload = _basis().to_payload()
    payload["unexpected"] = "ignored fields are forbidden"
    with pytest.raises(BusinessLogicError, match="fields are missing or unsupported"):
        SimulatedDividendPaymentBasis.from_payload(payload)

    payload = _basis().to_payload()
    payload["gross_entitlement_amount"] = "35.01"
    with pytest.raises(BusinessLogicError):
        SimulatedDividendPaymentBasis.from_payload(payload)

    payload = _basis().to_payload()
    payload["gross_entitlement_amount"] = "1e100000000"
    with pytest.raises(BusinessLogicError):
        SimulatedDividendPaymentBasis.from_payload(payload)

    with pytest.raises(BusinessLogicError, match="UTF-8"):
        replace(_basis(), asset_name="\ud800")
