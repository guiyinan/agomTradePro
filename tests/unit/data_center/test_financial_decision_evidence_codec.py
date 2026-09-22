"""Strict persistence projection tests for financial decision evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.infrastructure.financial_decision_evidence_codec import (
    FinancialDecisionEvidenceCodecError,
    decode_financial_decision_evidence,
    encode_financial_decision_evidence,
)


def _evidence() -> FinancialFactDecisionEvidence:
    response = FinancialResponseEvidence(
        body_sha256="a" * 64,
        body_size_bytes=128,
        response_completed_at=datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
        request_scope=FinancialRequestScope(
            provider_name="provider-main",
            dataset_key="equity.financial.fact",
            asset_code="000001.SZ",
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=("000001.SZ",),
            period_ends=(date(2026, 6, 30),),
            row_count=1,
        ),
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    return FinancialFactDecisionEvidence(
        artifact_reference=FinancialResponseArtifactRef(
            capture_id=UUID("20000000-0000-4000-8000-000000000004"),
            location="financial-response/codec-round-trip.bin",
            evidence=response,
            format_version="financial-response-artifact.v1",
            encryption_algorithm="fernet",
            encryption_key_ref="config_center.data02.test-key",
            encryption_key_version="v1",
        ),
        native_asset_code="000001.SZ",
        native_period_end=date(2026, 6, 30),
        native_row_id="provider-main:000001.SZ:20260630:roe",
    )


def test_financial_decision_evidence_projection_round_trips_exactly() -> None:
    """Every artifact and native-row dimension survives JSON persistence."""

    evidence = _evidence()

    assert (
        decode_financial_decision_evidence(encode_financial_decision_evidence(evidence)) == evidence
    )
    assert decode_financial_decision_evidence({}) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload.__setitem__("schema", "legacy"),
        lambda payload: payload["artifact_reference"].__setitem__("body_sha256", "bad"),
        lambda payload: payload["artifact_reference"]["request_scope"].__setitem__(
            "provider_name", ""
        ),
    ],
)
def test_financial_decision_evidence_projection_rejects_ambiguous_json(mutation) -> None:
    """Unknown, downgraded or malformed persisted evidence fails closed."""

    payload = encode_financial_decision_evidence(_evidence())
    mutation(payload)

    with pytest.raises((FinancialDecisionEvidenceCodecError, ValueError)):
        decode_financial_decision_evidence(payload)
