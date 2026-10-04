"""AKShare date-only source-time matcher recomputes witnesses from retained bodies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast
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
    FinancialSourceTimeMatchContract,
    financial_source_time_contract_sha256,
)
from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialAvailabilityBasis,
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimePrecision,
    FinancialSourceTimeWitness,
)
from apps.data_center.financial_source_time_composition import _resolve_contract_matcher
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AkshareNoticeDateSourceTimeMatcher,
    akshare_notice_date_match_contract,
)

ASSET = "000001.SZ"
PERIOD_END = date(2026, 6, 30)
ANNOUNCEMENT = date(2026, 8, 15)
# 2026-08-15 00:00 Asia/Shanghai and the next calendar day start, in UTC.
ANNOUNCED_AT = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 9, 13, 13, 45, 24, tzinfo=UTC)
ROW_ID = "akshare:000001.SZ:2026-06-30:2026-08-15"


def _row(
    *,
    asset: str = ASSET,
    report_date: object = "2026-06-30 00:00:00",
    notice_date: object = "2026-08-15 00:00:00",
) -> dict[str, object]:
    return {
        "SECUCODE": asset,
        "REPORT_DATE": report_date,
        "NOTICE_DATE": notice_date,
        "TOTALOPERATEREVE": 123456.0,
    }


def _body(rows: list[dict[str, object]], *, success: bool = True) -> bytes:
    return json.dumps(
        {
            "success": success,
            "code": 0,
            "message": "ok",
            "result": {"pages": 1, "count": len(rows), "data": rows},
        },
        ensure_ascii=False,
    ).encode("utf-8")


FINANCIAL_ROWS = [_row()]
SOURCE_TIME_ROWS = [_row()]
FINANCIAL_BODY = _body(FINANCIAL_ROWS)
SOURCE_TIME_BODY = _body(SOURCE_TIME_ROWS)


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _decision(
    *,
    completed_at: datetime = COMPLETED_AT,
    native_row_id: str = ROW_ID,
) -> FinancialFactDecisionEvidence:
    financial_ref = FinancialResponseArtifactRef(
        capture_id=UUID("10000000-0000-4000-8000-000000000001"),
        location="financial-response/10/10000000-0000-4000-8000-000000000001.bin",
        evidence=FinancialResponseEvidence(
            body_sha256=_sha(FINANCIAL_BODY),
            body_size_bytes=len(FINANCIAL_BODY),
            response_completed_at=completed_at,
            request_scope=FinancialRequestScope(
                provider_name="akshare",
                dataset_key="equity.financial.fact",
                asset_code=ASSET,
                period_limit=1,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=(ASSET,),
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
        provider_name="akshare",
        dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
        requested_asset_code=ASSET,
        requested_announcement_date=ANNOUNCEMENT,
        body_sha256=_sha(SOURCE_TIME_BODY),
        body_size_bytes=len(SOURCE_TIME_BODY),
        response_completed_at=completed_at,
        response_row_count=1,
        format_version="financial-source-time-artifact.v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="config/financial-key",
        encryption_key_version="v1",
    )
    contract = akshare_notice_date_match_contract()
    witness = FinancialSourceTimeWitness(
        artifact_reference=source_ref,
        native_asset_code=ASSET,
        native_period_end=PERIOD_END,
        financial_native_row_id=native_row_id,
        financial_announced_date=ANNOUNCEMENT,
        source_native_row_id=native_row_id,
        source_timezone="Asia/Shanghai",
        announced_at=ANNOUNCED_AT,
        available_at=AVAILABLE_AT,
        row_projection_sha256="0" * 64,
        governed_match_contract_id=contract.contract_id,
        governed_match_contract_version=contract.contract_version,
        governed_match_contract_sha256=contract.contract_sha256,
        matched_row_count=1,
        availability_basis=FinancialAvailabilityBasis.PROVIDER_DATE_NEXT_SESSION,
        source_time_precision=FinancialSourceTimePrecision.DATE,
    )
    return FinancialFactDecisionEvidence(
        artifact_reference=financial_ref,
        native_asset_code=ASSET,
        native_period_end=PERIOD_END,
        native_row_id=native_row_id,
        source_time_witness=witness,
    )


def _match(
    *,
    contract: FinancialSourceTimeMatchContract | None = None,
    financial_body: bytes = FINANCIAL_BODY,
    source_time_body: bytes = SOURCE_TIME_BODY,
    decision: FinancialFactDecisionEvidence | None = None,
) -> FinancialSourceTimeWitness | None:
    return AkshareNoticeDateSourceTimeMatcher().match(
        contract=contract or akshare_notice_date_match_contract(),
        financial_body=financial_body,
        source_time_body=source_time_body,
        decision_evidence=decision or _decision(),
    )


def test_matcher_recomputes_the_date_only_witness() -> None:
    recomputed = _match()
    claimed = _decision().source_time_witness

    assert recomputed is not None
    assert claimed is not None
    assert recomputed == replace(claimed, row_projection_sha256=recomputed.row_projection_sha256)
    assert recomputed.announced_at == ANNOUNCED_AT
    assert recomputed.available_at == AVAILABLE_AT
    assert recomputed.availability_basis is FinancialAvailabilityBasis.PROVIDER_DATE_NEXT_SESSION
    assert recomputed.source_time_precision is FinancialSourceTimePrecision.DATE
    assert recomputed.source_native_row_id == ROW_ID
    assert recomputed.matched_row_count == 1


def test_matcher_is_deterministic_for_identical_bodies() -> None:
    first = _match()
    second = _match()

    assert first is not None and first == second


@pytest.mark.parametrize(
    "source_rows",
    [
        [],
        [_row(), _row()],
        [_row(notice_date=None)],
        [_row(notice_date="2026-08-15 15:30:00")],
        [_row(notice_date="2026-08-15T00:00:00+08:00")],
        [_row(report_date="2026/06/30")],
        [_row(asset="600000.SH")],
    ],
)
def test_matcher_fails_closed_without_exactly_one_valid_source_row(
    source_rows: list[dict[str, object]],
) -> None:
    assert _match(source_time_body=_body(source_rows)) is None


def test_matcher_fails_closed_when_financial_row_is_not_unique() -> None:
    body = _body([_row(), _row()])

    assert _match(financial_body=body) is None


def test_matcher_selects_the_financial_row_named_by_decision_evidence() -> None:
    other = _row(notice_date="2026-08-20 00:00:00")
    body = _body([other, _row()])
    source_body = _body([_row(), other])

    recomputed = _match(financial_body=body, source_time_body=source_body)

    assert recomputed is not None
    assert recomputed.financial_announced_date == ANNOUNCEMENT


def test_matcher_rejects_an_unknown_native_row_id() -> None:
    assert (
        _match(decision=_decision(native_row_id="akshare:000001.SZ:2026-06-30:2026-08-16")) is None
    )


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b'{"success": true, "code": 0, "result": {"pages": 1, "count": 1}}',
        _body([], success=False),
        b'{"success": true, "code": 1, "result": {"pages": 1, "count": 0, "data": []}}',
        b'{"success": true, "code": 0, "result": {"pages": 1, "count": 2, "data": []}}',
        b'{"success": true, "success": true, "code": 0, "result": {"pages": 1, "count": 0, "data": []}}',
    ],
)
def test_matcher_rejects_ambiguous_or_unsuccessful_bodies(body: bytes) -> None:
    assert _match(source_time_body=body) is None


def test_claimed_witness_cannot_postdate_capture_by_construction() -> None:
    """The witness invariant structurally blocks availability after capture."""

    with pytest.raises(ValueError):
        _decision(completed_at=datetime(2026, 8, 15, 2, 0, tzinfo=UTC))


def test_matcher_rejects_any_contract_drift() -> None:
    contract = akshare_notice_date_match_contract()
    payload = contract.to_dict()
    payload["contract_version"] = "2099-01-01.v1"
    payload["contract_sha256"] = financial_source_time_contract_sha256(payload)
    drifted = FinancialSourceTimeMatchContract(
        **{
            key: value
            for key, value in payload.items()
            if key not in {"join_fields", "projection_fields"}
        },
        join_fields=contract.join_fields,
        projection_fields=contract.projection_fields,
    )

    assert _match(contract=drifted) is None


def test_composition_resolves_the_matcher_only_for_the_exact_contract_identity() -> None:
    contract = akshare_notice_date_match_contract()

    resolved = _resolve_contract_matcher(contract)

    assert isinstance(resolved, AkshareNoticeDateSourceTimeMatcher)
    tampered_digest = cast(
        FinancialSourceTimeMatchContract,
        SimpleNamespace(
            identity=(
                contract.provider_name,
                contract.contract_id,
                contract.contract_version,
                "0" * 64,
            )
        ),
    )
    wrong_provider = cast(
        FinancialSourceTimeMatchContract,
        SimpleNamespace(
            identity=(
                "tushare",
                contract.contract_id,
                contract.contract_version,
                contract.contract_sha256,
            )
        ),
    )
    assert _resolve_contract_matcher(tampered_digest) is None
    assert _resolve_contract_matcher(wrong_provider) is None


class _Bodies:
    def read_financial(self, _reference: FinancialResponseArtifactRef) -> bytes | None:
        return FINANCIAL_BODY

    def read_source_time(self, _reference: FinancialSourceTimeArtifactRef) -> bytes | None:
        return SOURCE_TIME_BODY


class _Audits:
    def __init__(self, decision: FinancialFactDecisionEvidence) -> None:
        self._decision = decision

    def _audit(self, *, source_time: bool) -> RawAudit:
        witness = self._decision.source_time_witness
        assert witness is not None
        reference = witness.artifact_reference if source_time else self._decision.artifact_reference
        audit = RawAudit(
            provider_name="akshare",
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
            parser_version=(
                akshare_notice_date_match_contract().parser_version
                if source_time
                else "financial-response-artifact.v1"
            ),
            payload_size_bytes=reference.body_size_bytes,
        )
        return replace(audit, content_hash=raw_audit_content_hash(audit))

    def list_financial(self, _capture_id: UUID) -> tuple[RawAudit, ...]:
        return (self._audit(source_time=False),)

    def list_source_time(self, _capture_id: UUID) -> tuple[RawAudit, ...]:
        return (self._audit(source_time=True),)


class _Contracts:
    def get(
        self,
        *,
        provider_name: str,
        contract_id: str,
        contract_version: str,
        contract_sha256: str,
    ) -> FinancialSourceTimeMatchContract | None:
        contract = akshare_notice_date_match_contract()
        if (provider_name, contract_id, contract_version, contract_sha256) != contract.identity:
            return None
        return contract


class _Links:
    def verify_financial(
        self, audit: RawAudit, reference: FinancialResponseArtifactRef
    ) -> int | None:
        return 3 if audit.extra == {"capture_id": str(reference.capture_id)} else None

    def verify_source_time(
        self, audit: RawAudit, reference: FinancialSourceTimeArtifactRef
    ) -> int | None:
        return 3 if audit.extra == {"capture_id": str(reference.capture_id)} else None


def _verifier(decision: FinancialFactDecisionEvidence) -> FinancialSourceTimeEvidenceVerifier:
    bodies = _Bodies()
    return FinancialSourceTimeEvidenceVerifier(
        financial_body_reader=bodies.read_financial,
        source_time_body_reader=bodies.read_source_time,
        audit_reader=_Audits(decision),
        contract_reader=_Contracts(),
        audit_link_verifier=_Links(),
        matcher=AkshareNoticeDateSourceTimeMatcher(),
    )


def test_verifier_accepts_a_witness_recomputed_by_the_real_matcher() -> None:
    decision = _decision()
    recomputed = _match(decision=decision)
    assert recomputed is not None
    witness = decision.source_time_witness
    assert witness is not None
    decision = replace(decision, source_time_witness=recomputed)

    assert _verifier(decision).verify(decision) is True

    tampered = replace(
        decision,
        source_time_witness=replace(recomputed, row_projection_sha256="f" * 64),
    )
    assert _verifier(tampered).verify(tampered) is False
