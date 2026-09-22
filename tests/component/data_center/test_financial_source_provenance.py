"""Persisted financial policy3 source evidence and member binding contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from apps.data_center.application.publication_utils import publication_member_from_reference
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
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
from apps.data_center.infrastructure.catalog_models import DatasetPublicationPolicyModel
from apps.data_center.infrastructure.financial_decision_evidence_codec import (
    decode_financial_decision_evidence,
    encode_financial_decision_evidence,
)
from apps.data_center.infrastructure.financial_fact_repository import (
    FinancialFactProvenanceConflictError,
    FinancialFactRepository,
)
from apps.data_center.infrastructure.models import FinancialFactModel
from apps.data_center.infrastructure.publication_fact_evidence import (
    canonical_fact_content_hash,
)
from apps.data_center.infrastructure.publication_member_store import (
    publication_fact_content_hashes,
)

pytestmark = pytest.mark.django_db

DATASET_KEY = "equity.financial.fact"
ANNOUNCED_AT = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
AVAILABLE_AT = ANNOUNCED_AT + timedelta(minutes=5)
SOURCE_HASH = "a" * 64


def _decision_projection(
    *,
    asset_code: str = "000001.SZ",
    period_end: date = date(2026, 6, 30),
    provider_name: str = "provider-main",
    source_record_id: str = "provider-record-1",
    announced_at: datetime = ANNOUNCED_AT,
    available_at: datetime = AVAILABLE_AT,
    raw_payload_hash: str = SOURCE_HASH,
) -> dict[str, object]:
    """Return one exact retained-response binding for the persisted fixture row."""

    evidence = FinancialResponseEvidence(
        body_sha256=raw_payload_hash,
        body_size_bytes=128,
        response_completed_at=available_at + timedelta(minutes=1),
        request_scope=FinancialRequestScope(
            provider_name=provider_name,
            dataset_key=DATASET_KEY,
            asset_code=asset_code,
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=(asset_code,),
            period_ends=(period_end,),
            row_count=1,
        ),
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    decision = FinancialFactDecisionEvidence(
        artifact_reference=FinancialResponseArtifactRef(
            capture_id=UUID("30000000-0000-4000-8000-000000000001"),
            location="financial-response/source-provenance.bin",
            evidence=evidence,
            format_version="financial-response-artifact.v1",
            encryption_algorithm="fernet",
            encryption_key_ref="config_center.data02.test-key",
            encryption_key_version="v1",
        ),
        native_asset_code=asset_code,
        native_period_end=period_end,
        native_row_id=source_record_id,
        source_time_witness=FinancialSourceTimeWitness(
            artifact_reference=FinancialSourceTimeArtifactRef(
                capture_id=UUID("30000000-0000-4000-8000-000000000002"),
                location="financial-source-time/source-provenance.bin",
                provider_name=provider_name,
                dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
                requested_asset_code=asset_code,
                requested_announcement_date=announced_at.date(),
                body_sha256="b" * 64,
                body_size_bytes=96,
                response_completed_at=available_at + timedelta(minutes=1),
                response_row_count=1,
                format_version="financial-source-time-artifact.v1",
                encryption_algorithm="fernet",
                encryption_key_ref="config_center.data02.test-key",
                encryption_key_version="v1",
            ),
            native_asset_code=asset_code,
            native_period_end=period_end,
            financial_native_row_id=source_record_id,
            financial_announced_date=announced_at.date(),
            source_native_row_id=(
                f"{provider_name}:notice:{asset_code}:" f"{announced_at:%Y%m%d}:{source_record_id}"
            ),
            source_timezone="UTC",
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
    return encode_financial_decision_evidence(decision)


def _decision_transport_extra(
    decision_projection: dict[str, object],
) -> dict[str, object]:
    """Return the persisted transport columns bound by a v2 decision projection."""

    source_time = decision_projection["source_time_witness"]
    artifact = decision_projection["artifact_reference"]
    assert isinstance(source_time, dict)
    assert isinstance(artifact, dict)
    source_time_artifact = source_time["artifact_reference"]
    assert isinstance(source_time_artifact, dict)
    return {
        "financial_response_capture_id": artifact["capture_id"],
        "raw_payload_scope": "batch_response_body",
        "response_scope_basis": "provider_body_verified",
        "financial_source_time_capture_id": source_time_artifact["capture_id"],
        "financial_source_time_body_sha256": source_time_artifact["body_sha256"],
        "financial_source_time_row_sha256": source_time["row_projection_sha256"],
        "financial_source_time_match_contract_id": source_time["governed_match_contract_id"],
        "financial_source_time_match_contract_version": source_time[
            "governed_match_contract_version"
        ],
        "financial_source_time_match_contract_sha256": source_time[
            "governed_match_contract_sha256"
        ],
        "financial_source_time_matched_row_count": source_time["matched_row_count"],
    }


def _activate_policy3() -> None:
    """Install an isolated active financial policy3 row for this test transaction."""

    DatasetPublicationPolicyModel.objects.filter(dataset_key=DATASET_KEY).delete()
    DatasetPublicationPolicyModel.objects.create(
        dataset_key=DATASET_KEY,
        contract_version="1.0",
        schema_version="1.0",
        policy_version="3",
        minimum_coverage_ratio=1.0,
        allow_partial=True,
        conflict_action="quarantine",
        required_evidence=[
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "payload_hash",
            "fact_content_hash",
            "source_record_id",
            "published_at",
            "raw_payload_hash",
            "raw_payload_scope",
        ],
        retention_days=3650,
        active=True,
    )


def _fact(*, available_at: datetime = AVAILABLE_AT) -> FinancialFact:
    """Build the domain key used to resolve the persisted ORM row."""

    return FinancialFact(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code="revenue",
        value=123.45,
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 9),
        available_at=available_at,
        fetched_at=AVAILABLE_AT + timedelta(minutes=10),
    )


def test_policy3_uses_original_source_fields_through_member_store() -> None:
    """A persisted valid row remains bound after reference and member round-trip."""

    _activate_policy3()
    row = FinancialFactModel.objects.create(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type="quarterly",
        metric_code="revenue",
        value=Decimal("123.4500"),
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 9),
        announced_at=ANNOUNCED_AT,
        available_at=AVAILABLE_AT,
        source_record_id="provider-record-1",
        raw_payload_hash=SOURCE_HASH,
        extra={
            "financial_response_capture_id": "30000000-0000-4000-8000-000000000001",
            "raw_payload_scope": "batch_response_body",
            "response_scope_basis": "provider_body_verified",
            "financial_source_time_capture_id": "30000000-0000-4000-8000-000000000002",
            "financial_source_time_body_sha256": "b" * 64,
            "financial_source_time_row_sha256": "c" * 64,
            "financial_source_time_match_contract_id": (
                "provider-main.financial-announcement.exact"
            ),
            "financial_source_time_match_contract_version": "v1",
            "financial_source_time_match_contract_sha256": "d" * 64,
            "financial_source_time_matched_row_count": 1,
        },
        decision_evidence=_decision_projection(),
    )

    verified: list[FinancialFactDecisionEvidence] = []

    def verify(decision: FinancialFactDecisionEvidence) -> bool:
        verified.append(decision)
        return True

    with pytest.raises(
        FinancialFactProvenanceConflictError,
        match="independently reverified",
    ):
        FinancialFactRepository().list_publication_candidates([_fact()])

    references = FinancialFactRepository(
        source_time_evidence_verifier=verify
    ).list_publication_candidates([_fact()])

    assert len(references) == 1
    reference = references[0]
    assert reference.source_published_at == ANNOUNCED_AT
    assert reference.source_record_id == "provider-record-1"
    assert reference.raw_payload_hash == SOURCE_HASH
    assert reference.raw_payload_scope == "batch_response_body"
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=str(uuid4()),
        dataset_key=DATASET_KEY,
    )
    assert publication_fact_content_hashes((member,)) == {
        (row._meta.db_table, str(row.pk)): canonical_fact_content_hash(row)
    }
    assert verified == [decode_financial_decision_evidence(_decision_projection())]


def test_policy3_rejects_persisted_synthetic_financial_evidence() -> None:
    """A historical available_at without source proof cannot become a candidate."""

    _activate_policy3()
    FinancialFactModel.objects.create(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type="quarterly",
        metric_code="revenue",
        value=Decimal("123.4500"),
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 9),
        available_at=AVAILABLE_AT,
        source_record_id="provider-record-1",
        raw_payload_hash=SOURCE_HASH,
        extra={
            "financial_response_capture_id": "30000000-0000-4000-8000-000000000001",
            "raw_payload_scope": "batch_response_body",
            "response_scope_basis": "provider_body_verified",
        },
        decision_evidence=_decision_projection(),
    )

    with pytest.raises(FinancialFactProvenanceConflictError, match="source-time evidence"):
        FinancialFactRepository().list_publication_candidates([_fact()])
