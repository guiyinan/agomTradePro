"""Independent recomputation gate for financial source-time evidence."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from apps.data_center.application.financial_source_time_verifier import (
    FinancialSourceTimeEvidenceVerifier,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.domain.financial_source_time_contract import (
    FinancialSourceTimeJoinField,
    FinancialSourceTimeJoinSemantic,
    FinancialSourceTimeMatchContract,
    financial_source_time_contract_sha256,
)
from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialAvailabilityBasis,
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimeWitness,
)

FINANCIAL_BODY = b'{"financial":"row-1"}'
SOURCE_TIME_BODY = b'{"source_time":"notice-1"}'
PERIOD_END = date(2026, 6, 30)
ANNOUNCEMENT_DATE = date(2026, 8, 28)
ANNOUNCED_AT = datetime(2026, 8, 28, 7, 30, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 8, 28, 7, 31, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 28, 7, 32, tzinfo=UTC)


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _contract() -> FinancialSourceTimeMatchContract:
    payload: dict[str, object] = {
        "provider_name": "provider-main",
        "financial_dataset_key": "equity.financial.fact",
        "source_time_dataset_key": FINANCIAL_SOURCE_TIME_DATASET_KEY,
        "endpoint": "synthetic_notice",
        "contract_id": "provider-main.financial-notice.exact",
        "contract_version": "v1",
        "parser_version": "synthetic-notice.v1",
        "source_timezone": "Asia/Shanghai",
        "join_fields": [
            {
                "semantic": "asset_code",
                "financial_field": "ts_code",
                "source_field": "asset_code",
            },
            {
                "semantic": "period_end",
                "financial_field": "end_date",
                "source_field": "period_end",
            },
            {
                "semantic": "announcement_date",
                "financial_field": "ann_date",
                "source_field": "announcement_date",
            },
        ],
        "source_row_id_field": "notice_id",
        "announced_at_field": "announced_at",
        "available_at_field": "available_at",
        "projection_fields": [
            "notice_id",
            "asset_code",
            "period_end",
            "announcement_date",
            "announced_at",
            "available_at",
        ],
    }
    return FinancialSourceTimeMatchContract(
        provider_name="provider-main",
        financial_dataset_key="equity.financial.fact",
        source_time_dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
        endpoint="synthetic_notice",
        contract_id="provider-main.financial-notice.exact",
        contract_version="v1",
        parser_version="synthetic-notice.v1",
        source_timezone="Asia/Shanghai",
        join_fields=(
            FinancialSourceTimeJoinField(
                FinancialSourceTimeJoinSemantic.ASSET_CODE, "ts_code", "asset_code"
            ),
            FinancialSourceTimeJoinField(
                FinancialSourceTimeJoinSemantic.PERIOD_END, "end_date", "period_end"
            ),
            FinancialSourceTimeJoinField(
                FinancialSourceTimeJoinSemantic.ANNOUNCEMENT_DATE,
                "ann_date",
                "announcement_date",
            ),
        ),
        source_row_id_field="notice_id",
        announced_at_field="announced_at",
        available_at_field="available_at",
        projection_fields=(
            "notice_id",
            "asset_code",
            "period_end",
            "announcement_date",
            "announced_at",
            "available_at",
        ),
        contract_sha256=financial_source_time_contract_sha256(payload),
    )


def _decision() -> FinancialFactDecisionEvidence:
    contract = _contract()
    financial_ref = FinancialResponseArtifactRef(
        capture_id=UUID("10000000-0000-4000-8000-000000000001"),
        location="financial-response/10/10000000-0000-4000-8000-000000000001.bin",
        evidence=FinancialResponseEvidence(
            body_sha256=_sha(FINANCIAL_BODY),
            body_size_bytes=len(FINANCIAL_BODY),
            response_completed_at=COMPLETED_AT,
            request_scope=FinancialRequestScope(
                provider_name="provider-main",
                dataset_key="equity.financial.fact",
                asset_code="000001.SZ",
                period_limit=1,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=("000001.SZ",),
                period_ends=(PERIOD_END,),
                row_count=1,
            ),
            response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
        ),
        format_version="financial-response-body-fernet-v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="config/financial-key",
        encryption_key_version="v1",
    )
    source_ref = FinancialSourceTimeArtifactRef(
        capture_id=UUID("20000000-0000-4000-8000-000000000002"),
        location="financial-source-time/20/20000000-0000-4000-8000-000000000002.bin",
        provider_name="provider-main",
        dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
        requested_asset_code="000001.SZ",
        requested_announcement_date=ANNOUNCEMENT_DATE,
        body_sha256=_sha(SOURCE_TIME_BODY),
        body_size_bytes=len(SOURCE_TIME_BODY),
        response_completed_at=COMPLETED_AT,
        response_row_count=1,
        format_version="financial-source-time-artifact.v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="config/financial-key",
        encryption_key_version="v1",
    )
    witness = FinancialSourceTimeWitness(
        artifact_reference=source_ref,
        native_asset_code="000001.SZ",
        native_period_end=PERIOD_END,
        financial_native_row_id="financial-row-1",
        financial_announced_date=ANNOUNCEMENT_DATE,
        source_native_row_id="notice-1",
        source_timezone="Asia/Shanghai",
        announced_at=ANNOUNCED_AT,
        available_at=AVAILABLE_AT,
        row_projection_sha256="a" * 64,
        governed_match_contract_id=contract.contract_id,
        governed_match_contract_version=contract.contract_version,
        governed_match_contract_sha256=contract.contract_sha256,
        matched_row_count=1,
        availability_basis=FinancialAvailabilityBasis.PROVIDER_NATIVE_EXACT,
    )
    return FinancialFactDecisionEvidence(
        artifact_reference=financial_ref,
        native_asset_code="000001.SZ",
        native_period_end=PERIOD_END,
        native_row_id="financial-row-1",
        source_time_witness=witness,
    )


def _audit(*, source_time: bool, content_hash: bool = True) -> RawAudit:
    decision = _decision()
    witness = decision.source_time_witness
    assert witness is not None
    reference = witness.artifact_reference if source_time else decision.artifact_reference
    audit = RawAudit(
        provider_name="provider-main",
        capability="financial_source_time" if source_time else "financial",
        request_params={},
        status="ok",
        row_count=(
            reference.response_row_count
            if source_time
            else reference.evidence.response_scope.row_count
        ),
        fetched_at=(
            reference.response_completed_at
            if source_time
            else reference.evidence.response_completed_at
        ),
        extra={"capture_id": str(reference.capture_id)},
        redacted=True,
        parser_version="synthetic-notice.v1" if source_time else "financial-response-artifact.v1",
        payload_size_bytes=(
            reference.body_size_bytes if source_time else reference.body_size_bytes
        ),
    )
    return replace(audit, content_hash=raw_audit_content_hash(audit) if content_hash else "")


class _Bodies:
    def read_financial(self, _reference: FinancialResponseArtifactRef) -> bytes | None:
        return FINANCIAL_BODY

    def read_source_time(self, _reference: FinancialSourceTimeArtifactRef) -> bytes | None:
        return SOURCE_TIME_BODY


class _Audits:
    def __init__(self, *, financial: tuple[RawAudit, ...], source: tuple[RawAudit, ...]) -> None:
        self.financial = financial
        self.source = source

    def list_financial(self, _capture_id: UUID) -> tuple[RawAudit, ...]:
        return self.financial

    def list_source_time(self, _capture_id: UUID) -> tuple[RawAudit, ...]:
        return self.source


class _Contracts:
    def __init__(self, contract: FinancialSourceTimeMatchContract | None) -> None:
        self.contract = contract

    def get(
        self,
        *,
        provider_name: str,
        contract_id: str,
        contract_version: str,
        contract_sha256: str,
    ) -> FinancialSourceTimeMatchContract | None:
        contract = self.contract
        if contract is None:
            return None
        if (
            provider_name,
            contract_id,
            contract_version,
            contract_sha256,
        ) != (
            contract.provider_name,
            contract.contract_id,
            contract.contract_version,
            contract.contract_sha256,
        ):
            return None
        return contract


class _Links:
    def __init__(self, *, financial_provider_id: int = 7, source_provider_id: int = 7) -> None:
        self.financial_provider_id = financial_provider_id
        self.source_provider_id = source_provider_id

    def verify_financial(
        self, audit: RawAudit, reference: FinancialResponseArtifactRef
    ) -> int | None:
        if audit.extra != {"capture_id": str(reference.capture_id)}:
            return None
        return self.financial_provider_id

    def verify_source_time(
        self, audit: RawAudit, reference: FinancialSourceTimeArtifactRef
    ) -> int | None:
        if audit.extra != {"capture_id": str(reference.capture_id)}:
            return None
        return self.source_provider_id


class _Matcher:
    def __init__(self, result: FinancialSourceTimeWitness | None) -> None:
        self.result = result

    def match(
        self,
        *,
        contract: FinancialSourceTimeMatchContract,
        financial_body: bytes,
        source_time_body: bytes,
        decision_evidence: FinancialFactDecisionEvidence,
    ) -> FinancialSourceTimeWitness | None:
        assert contract == _contract()
        assert financial_body == FINANCIAL_BODY
        assert source_time_body == SOURCE_TIME_BODY
        return self.result


def _verifier(
    *,
    contract: FinancialSourceTimeMatchContract | None | object = object(),
    financial_audits: tuple[RawAudit, ...] | None = None,
    source_audits: tuple[RawAudit, ...] | None = None,
    match: FinancialSourceTimeWitness | None | object = object(),
    financial_provider_id: int = 7,
    source_provider_id: int = 7,
) -> FinancialSourceTimeEvidenceVerifier:
    decision = _decision()
    resolved_contract = _contract() if type(contract) is object else contract
    matched = decision.source_time_witness if type(match) is object else match
    bodies = _Bodies()
    return FinancialSourceTimeEvidenceVerifier(
        financial_body_reader=bodies.read_financial,
        source_time_body_reader=bodies.read_source_time,
        audit_reader=_Audits(
            financial=(
                (_audit(source_time=False),) if financial_audits is None else financial_audits
            ),
            source=((_audit(source_time=True),) if source_audits is None else source_audits),
        ),
        contract_reader=_Contracts(resolved_contract),
        audit_link_verifier=_Links(
            financial_provider_id=financial_provider_id,
            source_provider_id=source_provider_id,
        ),
        matcher=_Matcher(matched),
    )


def test_exact_recomputation_accepts_one_complete_evidence_chain() -> None:
    assert _verifier().verify(_decision()) is True


def test_financial_and_source_time_audits_require_the_same_provider_id() -> None:
    assert _verifier(financial_provider_id=7, source_provider_id=8).verify(_decision()) is False


def test_empty_contract_registry_fails_before_body_acceptance() -> None:
    assert _verifier(contract=None).verify(_decision()) is False


@pytest.mark.parametrize("audit_count", [0, 2])
def test_each_artifact_requires_exactly_one_raw_audit(audit_count: int) -> None:
    audits = tuple(_audit(source_time=True) for _ in range(audit_count))
    assert _verifier(source_audits=audits).verify(_decision()) is False


def test_raw_audit_requires_a_nonempty_recomputed_content_hash() -> None:
    assert (
        _verifier(source_audits=(_audit(source_time=True, content_hash=False),)).verify(_decision())
        is False
    )
    tampered = replace(_audit(source_time=True), content_hash="f" * 64)
    assert _verifier(source_audits=(tampered,)).verify(_decision()) is False


def test_matcher_must_recompute_the_exact_witness() -> None:
    decision = _decision()
    witness = decision.source_time_witness
    assert witness is not None
    mismatched = replace(witness, row_projection_sha256="b" * 64)
    assert _verifier(match=mismatched).verify(decision) is False


def test_financial_and_source_time_capture_ids_must_be_distinct() -> None:
    decision = _decision()
    witness = decision.source_time_witness
    assert witness is not None
    forged_ref = replace(
        witness.artifact_reference,
        capture_id=decision.artifact_reference.capture_id,
    )
    forged = replace(decision, source_time_witness=replace(witness, artifact_reference=forged_ref))
    assert _verifier(match=forged.source_time_witness).verify(forged) is False
