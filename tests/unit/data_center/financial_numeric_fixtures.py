"""Shared synthetic Main qualification fixtures; no production approvals."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from apps.data_center.application.financial_numeric_verification import (
    FinancialProviderIdentity,
)
from apps.data_center.domain.entities import FinancialFact, RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceContextRequirement,
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import (
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.infrastructure._provider_adapter_base import _period_type_from_period_end
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
)

BODY = (
    b'{"success":true,"code":0,"result":{"count":1,"data":['
    b'{"SECUCODE":"000001.SZ","REPORT_DATE":"2026-06-30",'
    b'"NOTICE_DATE":"2026-08-15","RAW_METRIC":123.456789012345}]}}'
)

ASSET = "000001.SZ"

PERIOD = date(2026, 6, 30)

ROW_ID = "akshare:000001.SZ:2026-06-30:2026-08-15"

FETCHED_AT = datetime(2026, 9, 13, 4, 5, 16, tzinfo=UTC)

RESPONSE_COMPLETED_AT = FETCHED_AT - timedelta(seconds=10)

KNOWN_NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)

DOCUMENT_CAPTURED_AT = datetime(2026, 9, 1, tzinfo=UTC)

EFFECTIVE_UNTIL = datetime(2026, 10, 1, tzinfo=UTC)

RECORDED_AT = datetime(2026, 9, 3, tzinfo=UTC)

APPROVED_AT = datetime(2026, 9, 5, tzinfo=UTC)

REVOKED_AT = datetime(2026, 10, 15, tzinfo=UTC)

CAPTURE_ID = UUID("20000000-0000-4000-8000-000000000001")

PROVIDER_ID = 37


def _contract(**changes: object) -> FinancialMetricSourceContract:
    """Return an explicit synthetic contract with no metric or unit defaults."""

    values: dict[str, object] = {
        "provider": "akshare",
        "dataset_key": "equity.financial.fact",
        "metric_code": "synthetic_metric",
        "source_field": "RAW_METRIC",
        "source_unit": "synthetic-source-unit",
        "canonical_unit": "synthetic-canonical-unit",
        "scale_numerator": 1,
        "scale_denominator": 1,
        "contract_version": "test-qualified-native-1",
        "origin": "native",
    }
    values.update(changes)
    return FinancialMetricSourceContract(**values)  # type: ignore[arg-type]


def _reference(
    body: bytes = BODY,
    *,
    response_completed_at: datetime = RESPONSE_COMPLETED_AT,
    row_count: int = 1,
) -> FinancialResponseArtifactRef:
    """Build an in-memory, body-hash-bound AKShare response reference."""

    evidence = FinancialResponseEvidence(
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=response_completed_at,
        request_scope=FinancialRequestScope(
            provider_name="akshare",
            dataset_key="equity.financial.fact",
            asset_code=ASSET,
            period_limit=2,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=(ASSET,),
            period_ends=(PERIOD,),
            row_count=row_count,
        ),
        body_scope=FinancialResponseBodyScope.BATCH,
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    return FinancialResponseArtifactRef(
        capture_id=CAPTURE_ID,
        location=f"financial-response:///v1/{CAPTURE_ID}.frb",
        evidence=evidence,
        format_version="financial-response-body-fernet-v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="config_center.data02.unit-test-key",
        encryption_key_version="test-v1",
    )


def _audit(
    reference: FinancialResponseArtifactRef,
    *,
    endpoint: str = AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
) -> RawAudit:
    """Bind one exact reference into a canonical synthetic financial RawAudit."""

    audit = RawAudit(
        provider_name="akshare",
        capability="financial",
        request_params={"endpoint": endpoint, "method": "GET"},
        status="ok",
        row_count=reference.evidence.response_scope.row_count,
        fetched_at=reference.evidence.response_completed_at,
        extra={
            "financial_response_artifact": {
                "schema": "financial-response-artifact-link.v1",
                **reference.to_dict(),
                "provider_id": PROVIDER_ID,
            }
        },
        response_payload_hash=reference.body_sha256,
        redacted=True,
        parser_version="financial-response-artifact.v1",
        payload_size_bytes=reference.body_size_bytes,
    )
    return replace(audit, content_hash=raw_audit_content_hash(audit))


def _fact(
    *,
    body: bytes = BODY,
    raw_value: object = Decimal("123.456789012345"),
    native_row_id: str = ROW_ID,
    fetched_at: datetime = FETCHED_AT,
    response_completed_at: datetime = RESPONSE_COMPLETED_AT,
    row_count: int = 1,
) -> FinancialFact:
    """Build a synthetic exact fact tied to one retained response reference."""

    contract = _contract()
    observation = NativeFinancialMetricObservation.from_raw_value(
        contract=contract,
        raw_value=raw_value,
        source_field=contract.source_field,
        body_sha256=sha256(body).hexdigest(),
        native_row_id=native_row_id,
    )
    reference = _reference(
        body,
        response_completed_at=response_completed_at,
        row_count=row_count,
    )
    return FinancialFact(
        asset_code=ASSET,
        period_end=PERIOD,
        period_type=_period_type_from_period_end(PERIOD),
        metric_code=contract.metric_code,
        value=Decimal(observation.canonical_value),
        unit=contract.canonical_unit,
        source=contract.provider,
        fetched_at=fetched_at,
        source_evidence=FinancialFactSourceEvidence(
            announced_at=datetime(2026, 8, 15, 1, 0, tzinfo=UTC),
            source_record_id=native_row_id,
            raw_payload_hash=reference.body_sha256,
        ),
        decision_evidence=FinancialFactDecisionEvidence(
            artifact_reference=reference,
            native_asset_code=ASSET,
            native_period_end=PERIOD,
            native_row_id=native_row_id,
        ),
        numeric_schema="native-decimal-v2",
        numeric_evidence=observation,
    )


def _qualification(
    contract: FinancialMetricSourceContract | None = None,
    *,
    endpoint: str = AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    context_requirement: FinancialNumericSourceContextRequirement | None = None,
    effective_from: datetime = DOCUMENT_CAPTURED_AT,
    effective_until: datetime | None = EFFECTIVE_UNTIL,
) -> FinancialNumericSourceQualification:
    """Create a synthetic qualification candidate for explicit row context."""

    selected_contract = contract or _contract()
    capture = FinancialNumericSourceDocumentCaptureReference(
        capture_id=UUID("30000000-0000-4000-8000-000000000001"),
        document_id="synthetic-doc-1",
        issuer="Synthetic Test Publisher",
        canonical_url="https://docs.example.test/financial/main",
        body_sha256="d" * 64,
        body_size_bytes=128,
        captured_at=DOCUMENT_CAPTURED_AT,
        content_type="text/html; charset=utf-8",
    )
    requirement = context_requirement or FinancialNumericSourceContextRequirement(
        field_name="REPORT_DATE",
        expected_value="2026-06-30",
    )
    return FinancialNumericSourceQualification(
        contract=selected_contract,
        endpoint=endpoint,
        source_applicability="synthetic-main-financial-context-v1",
        document_capture=capture,
        context_requirements=(requirement,),
        effective_from=effective_from,
        effective_until=effective_until,
    )


class _ArtifactRepository:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.reads = 0

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        self.reads += 1
        return self.body


class _AuditRepository:
    def __init__(self, audit: RawAudit) -> None:
        self.audit = audit

    def list_by_artifact_capture_id(self, capture_id: UUID) -> list[RawAudit]:
        return [self.audit]


class _ProviderIdentityResolver:
    def resolve_by_id(self, provider_id: int) -> FinancialProviderIdentity | None:
        if provider_id != PROVIDER_ID:
            return None
        return FinancialProviderIdentity(
            provider_id=PROVIDER_ID,
            name="akshare_primary",
            source_type="akshare",
            is_active=True,
        )
