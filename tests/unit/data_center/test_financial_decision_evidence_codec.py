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
from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialAvailabilityBasis,
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimeWitness,
)
from apps.data_center.infrastructure.financial_decision_evidence_codec import (
    FinancialDecisionEvidenceCodecError,
    decode_financial_decision_evidence,
    encode_financial_decision_evidence,
)


def _evidence() -> FinancialFactDecisionEvidence:
    announced_at = datetime(2026, 9, 14, 7, 59, tzinfo=UTC)
    available_at = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
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
        source_time_witness=FinancialSourceTimeWitness(
            artifact_reference=FinancialSourceTimeArtifactRef(
                capture_id=UUID("20000000-0000-4000-8000-000000000005"),
                location="financial-source-time/codec-round-trip.bin",
                provider_name="provider-main",
                dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
                requested_asset_code="000001.SZ",
                requested_announcement_date=date(2026, 9, 14),
                body_sha256="b" * 64,
                body_size_bytes=96,
                response_completed_at=available_at,
                response_row_count=1,
                format_version="financial-source-time-artifact.v1",
                encryption_algorithm="fernet",
                encryption_key_ref="config_center.data02.test-key",
                encryption_key_version="v1",
            ),
            native_asset_code="000001.SZ",
            native_period_end=date(2026, 6, 30),
            financial_native_row_id="provider-main:000001.SZ:20260630:roe",
            financial_announced_date=date(2026, 9, 14),
            source_native_row_id="provider-main:notice:000001.SZ:20260914:1",
            source_timezone="Asia/Shanghai",
            announced_at=announced_at,
            available_at=available_at,
            row_projection_sha256="c" * 64,
            governed_match_contract_id="provider-main.financial-announcement.exact",
            governed_match_contract_version="v1",
            governed_match_contract_sha256="d" * 64,
            matched_row_count=1,
            availability_basis=FinancialAvailabilityBasis.PROVIDER_NATIVE_EXACT,
        ),
    )


def test_financial_decision_evidence_projection_round_trips_exactly() -> None:
    """Every artifact and native-row dimension survives JSON persistence."""

    evidence = _evidence()

    assert (
        decode_financial_decision_evidence(encode_financial_decision_evidence(evidence)) == evidence
    )
    assert decode_financial_decision_evidence({}) is None


def test_legacy_v1_projection_remains_readable_but_has_no_source_time_witness() -> None:
    """Historical v1 rows can be read while downstream decision gates reject them."""

    evidence = _evidence()
    legacy = encode_financial_decision_evidence(
        FinancialFactDecisionEvidence(
            artifact_reference=evidence.artifact_reference,
            native_asset_code=evidence.native_asset_code,
            native_period_end=evidence.native_period_end,
            native_row_id=evidence.native_row_id,
        )
    )

    decoded = decode_financial_decision_evidence(legacy)

    assert decoded is not None
    assert decoded.source_time_witness is None
    assert legacy["schema"] == "financial-fact-decision-evidence.v1"


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
