"""Synthetic exact-body tests for the isolated v3 Main/Balance verifier."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
)
from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericVerificationContext,
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3FactVerificationRequest,
    FinancialV3OfficialSourceQualificationObservation,
)
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialSharedResponseSourceTimeContractV2,
    FinancialSharedResponseSourceTimeReferenceV2,
    match_shared_main_notice_date_v2,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialNativeRowBinding,
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
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
    FINANCIAL_FACT_DATASET_KEY,
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.infrastructure.financial_fact_v3_e1_verifier import (
    AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
    FinancialFactV3E1EvidenceVerifier,
    FinancialV3TemporalGateBlocked,
    FinancialV3TemporalGateResolution,
    _require_source_read,
)
from apps.data_center.infrastructure.financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
    _model_from_fact,
    _validate_existing_row_update,
)
from apps.data_center.infrastructure.financial_next_session_witness_codec import (
    encode_financial_next_session_witness_v3,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_raw_boundary import (
    BalanceCandidateContract,
    BalanceCandidateRequest,
    BalanceValueBinding,
    build_balance_candidate_query,
    parse_balance_candidate_body,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_API_URL,
    AKSHARE_BALANCE_REPORT_NAME,
    BalanceVerifiedOriginalResponse,
    _balance_native_row_id,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_PROVIDER_NAME,
)
from tests.unit.data_center.test_financial_next_session_witness import _witness
from tests.unit.data_center.test_financial_statutory_capture_binding import BODY as _STATUTORY_BODY
from tests.unit.data_center.test_financial_statutory_capture_binding import (
    _source_pair as _statutory_source_pair,
)

_PERIOD_END = date(2026, 6, 30)
_NOTICE_DATE = date(2026, 11, 16)
_TEST_UNIT = "test-unit-explicit"
_TEST_MAIN_METRIC = "test.revenue.metric"
_TEST_BALANCE_METRIC = "test.assets.metric"
_CURRENT_AT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _main_contract() -> FinancialSharedResponseSourceTimeContractV2:
    """Return one explicit test-only Main NOTICE parsing contract."""

    return FinancialSharedResponseSourceTimeContractV2(
        provider_name=AKSHARE_PROVIDER_NAME,
        dataset_key=FINANCIAL_FACT_DATASET_KEY,
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        contract_id="test.shared-main-notice",
        contract_version="test-v2",
        parser_version="test-row-parser-v2",
        source_timezone="Asia/Shanghai",
        success_key="success",
        success_value=True,
        code_key="code",
        success_code=0,
        result_key="result",
        data_key="data",
        count_key="count",
        asset_field="SECUCODE",
        period_end_field="REPORT_DATE",
        announcement_date_field="NOTICE_DATE",
        row_identity_prefix=AKSHARE_PROVIDER_NAME,
        projection_fields=("SECUCODE", "REPORT_DATE", "NOTICE_DATE"),
    )


def _balance_contract() -> BalanceCandidateContract:
    """Return a static unverified Balance parser contract for synthetic bytes."""

    return BalanceCandidateContract(
        contract_id="test.balance.raw.v1",
        evidence_state="static_candidate_unverified",
        endpoint_url=AKSHARE_BALANCE_API_URL,
        report_name=AKSHARE_BALANCE_REPORT_NAME,
        base_filter_terms=('(REPORT_DATE="test-explicit-period")',),
        security_filter_key="SECURITY_CODE",
        report_date_filter_key="REPORT_DATE",
        result_key="result",
        success_key="success",
        success_value=True,
        code_key="code",
        success_code=0,
        count_key="count",
        pages_key="pages",
        data_key="data",
        row_security_code_key="SECURITY_CODE",
        row_report_date_key="REPORT_DATE",
        row_notice_date_key="NOTICE_DATE",
        value_bindings=(
            BalanceValueBinding(_TEST_BALANCE_METRIC, "TOTAL_ASSETS", _TEST_UNIT),
            BalanceValueBinding("test.liabilities.metric", "TOTAL_LIABILITIES", _TEST_UNIT),
            BalanceValueBinding("test.equity.metric", "TOTAL_EQUITY", _TEST_UNIT),
        ),
    )


def _main_body(*, notice_text: str = "2026-11-16 00:00:00") -> bytes:
    """Return one synthetic response with all date text kept as source text."""

    return json.dumps(
        {
            "success": True,
            "code": 0,
            "result": {
                "count": 1,
                "data": [
                    {
                        "SECUCODE": "000001.SZ",
                        "REPORT_DATE": "2026-06-30 00:00:00",
                        "NOTICE_DATE": notice_text,
                        "TOTALOPERATEREVE": 123456789.25,
                    }
                ],
            },
        },
        separators=(",", ":"),
    ).encode()


def _balance_body(*, notice_text: str = "2026-11-16 00:00:00") -> bytes:
    """Return one synthetic Balance response with one row and one page."""

    return json.dumps(
        {
            "success": True,
            "code": 0,
            "result": {
                "count": 1,
                "pages": 1,
                "data": [
                    {
                        "SECURITY_CODE": "000001",
                        "REPORT_DATE": "2026-06-30 00:00:00",
                        "NOTICE_DATE": notice_text,
                        "TOTAL_ASSETS": 987654321.125,
                        "TOTAL_LIABILITIES": 123456789.75,
                        "TOTAL_EQUITY": 864197531.375,
                    }
                ],
            },
        },
        separators=(",", ":"),
    ).encode()


def _artifact_reference(
    body: bytes,
    *,
    endpoint: str,
    period_end: date = _PERIOD_END,
) -> FinancialResponseArtifactRef:
    """Bind exact synthetic bytes to the expected one-security response scope."""

    return FinancialResponseArtifactRef(
        capture_id=uuid4(),
        location="synthetic-only://financial-v3/body",
        evidence=FinancialResponseEvidence(
            body_sha256=hashlib.sha256(body).hexdigest(),
            body_size_bytes=len(body),
            response_completed_at=datetime(2026, 11, 16, 0, 1, tzinfo=UTC),
            request_scope=FinancialRequestScope(
                provider_name=AKSHARE_PROVIDER_NAME,
                dataset_key=FINANCIAL_FACT_DATASET_KEY,
                asset_code="000001.SZ",
                period_limit=8 if endpoint == AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT else 1,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=("000001.SZ",),
                period_ends=(period_end,),
                row_count=1,
            ),
            body_scope=FinancialResponseBodyScope.BATCH,
            response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
        ),
        format_version="synthetic-response-artifact.v1",
        encryption_algorithm="synthetic-test-only",
        encryption_key_ref="synthetic-test-only",
        encryption_key_version="synthetic-test-only",
    )


def _native_contract(
    *, metric_code: str, raw_field: str, unit: str = _TEST_UNIT
) -> FinancialMetricSourceContract:
    """Supply all numeric metric and unit meaning explicitly for a test row."""

    return FinancialMetricSourceContract(
        provider=AKSHARE_PROVIDER_NAME,
        dataset_key=FINANCIAL_FACT_DATASET_KEY,
        metric_code=metric_code,
        source_field=raw_field,
        source_unit=unit,
        canonical_unit=unit,
        scale_numerator=1,
        scale_denominator=1,
        contract_version="synthetic-test-only.v1",
        origin="native",
    )


def _qualified_source_observation(
    *,
    statutory_audit_count: int = 1,
    numeric_audit_count: int = 1,
) -> FinancialV3OfficialSourceQualificationObservation:
    """Build one synthetic, exact source-observation DTO for fail-closed checks."""

    identity, capture, _numeric_capture = _statutory_source_pair()
    known_at = capture.capture_recorded_at + timedelta(seconds=1)
    return FinancialV3OfficialSourceQualificationObservation(
        official_source=identity,
        statutory_capture=capture,
        profile_id="synthetic-profile",
        profile_version="synthetic-v1",
        publisher_code="synthetic-publisher",
        publisher_class="other",
        profile_content_sha256="b" * 64,
        configuration_sha256="c" * 64,
        verification_mode="current_exact_capture",
        statutory_capture_success_audit_count=statutory_audit_count,
        numeric_capture_success_audit_count=numeric_audit_count,
        origin_snapshot_id=str(capture.capture_id),
        origin_snapshot_version="financial-v3-official-source-origin-snapshot.v1",
        origin_snapshot_sha256="d" * 64,
        origin_snapshot_recorded_at=capture.capture_recorded_at,
        known_at=known_at,
        checked_at=known_at + timedelta(seconds=1),
    )


def _fact_and_witness(
    *,
    endpoint: str,
    notice_text: str = "2026-11-16 00:00:00",
    changed_contract_row_projection: str | None = None,
) -> tuple[
    FinancialFact,
    FinancialNextSessionSourceTimeWitnessV3,
    bytes,
    FinancialSharedResponseSourceTimeContractV2 | None,
    BalanceCandidateContract,
    dict[str, object],
]:
    """Construct matching typed v3 bindings over one synthetic endpoint body."""

    base_witness = _witness()
    assert type(base_witness) is FinancialNextSessionSourceTimeWitnessV3
    body = (
        _main_body(notice_text=notice_text)
        if endpoint == AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
        else _balance_body(notice_text=notice_text)
    )
    reference = _artifact_reference(body, endpoint=endpoint)
    balance_contract = _balance_contract()
    main_contract: FinancialSharedResponseSourceTimeContractV2 | None = None
    if endpoint == AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT:
        main_contract = _main_contract()
        source_time_reference = FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=reference,
            contract=main_contract,
            requested_asset_code="000001.SZ",
            requested_period_end=_PERIOD_END,
            requested_announcement_date=_NOTICE_DATE,
        )
        notice = match_shared_main_notice_date_v2(
            body,
            artifact_reference=source_time_reference,
        )
        assert notice is not None
        metric_code = _TEST_MAIN_METRIC
        raw_field = "TOTALOPERATEREVE"
        raw_value = Decimal("123456789.25")
        native_row_id = notice.native_row_id
        row_projection_sha256 = changed_contract_row_projection or notice.row_projection_sha256
        request_params: dict[str, object] = {"endpoint": endpoint}
    else:
        request = BalanceCandidateRequest("000001.SZ", "000001", _PERIOD_END)
        parsed = parse_balance_candidate_body(
            body,
            request=request,
            contract=balance_contract,
        )
        assert parsed.source_row_identity is not None
        metric_code = _TEST_BALANCE_METRIC
        raw_field = "TOTAL_ASSETS"
        raw_value = Decimal("987654321.125")
        native_row_id = _balance_native_row_id(parsed.source_row_identity)
        row_projection_sha256 = (
            changed_contract_row_projection or parsed.row_projection_sha256 or ""
        )
        request_params = dict(build_balance_candidate_query(request, balance_contract).parameters)
        request_params["endpoint"] = AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT

    observation = NativeFinancialMetricObservation.from_raw_value(
        contract=_native_contract(metric_code=metric_code, raw_field=raw_field),
        raw_value=raw_value,
        source_field=raw_field,
        body_sha256=reference.body_sha256,
        native_row_id=native_row_id,
    )
    row_binding = FinancialNativeRowBinding(
        artifact_reference=reference,
        asset_code="000001.SZ",
        period_end=_PERIOD_END,
        period_type=FinancialPeriodType.SEMI_ANNUAL,
        metric_code=metric_code,
        native_row_id=native_row_id,
        notice_date=_NOTICE_DATE,
        row_projection_sha256=row_projection_sha256,
        matched_row_count=1,
    )
    witness = replace(base_witness, financial_row=row_binding)
    fact = FinancialFact(
        asset_code="000001.SZ",
        period_end=_PERIOD_END,
        period_type=FinancialPeriodType.SEMI_ANNUAL,
        metric_code=metric_code,
        value=Decimal(observation.canonical_value),
        unit=_TEST_UNIT,
        source=AKSHARE_PROVIDER_NAME,
        report_date=_PERIOD_END,
        available_at=witness.available_at,
        fetched_at=reference.evidence.response_completed_at + timedelta(minutes=1),
        source_evidence=FinancialFactSourceEvidence(
            announced_at=None,
            source_record_id=native_row_id,
            raw_payload_hash=reference.body_sha256,
        ),
        decision_evidence=FinancialFactDecisionEvidence(
            artifact_reference=reference,
            native_asset_code="000001.SZ",
            native_period_end=_PERIOD_END,
            native_row_id=native_row_id,
            source_time_witness_v3=witness,
        ),
        numeric_schema="native-decimal-v2",
        numeric_evidence=observation,
    )
    return fact, witness, body, main_contract, balance_contract, request_params


class _ExactRoute:
    """Expose the test route selected from the already-bound artifact."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def resolve(self, reference: FinancialResponseArtifactRef) -> str:
        assert reference.evidence.request_scope.asset_code == "000001.SZ"
        return self.endpoint


class _MainBodyReader:
    """Return only the exact synthetic body expected by the test artifact."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def read_verified_body(self, reference: FinancialResponseArtifactRef) -> bytes:
        return self.body


class _BalanceBodyReader:
    """Return a synthetic exact response and its one-row query projection."""

    def __init__(self, body: bytes, params: dict[str, object]) -> None:
        self.body = body
        self.params = params

    def read_verified_response(
        self,
        reference: FinancialResponseArtifactRef,
    ) -> BalanceVerifiedOriginalResponse:
        return BalanceVerifiedOriginalResponse(self.body, self.params)


class _TemporalGate:
    """Record exact caller purpose and return a call-local test resolution."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime, FinancialNumericVerificationPurpose]] = []

    def resolve_current_in_uow(
        self,
        witness: FinancialNextSessionSourceTimeWitnessV3,
        *,
        purpose: FinancialNumericVerificationPurpose,
    ) -> FinancialV3TemporalGateResolution:
        self.calls.append(("current", witness.known_at, purpose))
        digest = encode_financial_next_session_witness_v3(witness)["witness_sha256"]
        return FinancialV3TemporalGateResolution(
            witness_sha256=str(digest),
            purpose=purpose,
            known_at=_CURRENT_AT,
            official_source_revision_sha256="a" * 64,
            statutory_capture_id=UUID("11111111-1111-4111-8111-111111111111"),
            numeric_document_capture_id=UUID("11111111-1111-4111-8111-111111111111"),
            official_profile_id="synthetic-profile",
            official_profile_version="synthetic-v1",
            official_publisher_code="synthetic-publisher",
            official_publisher_class="other",
            official_profile_content_sha256="b" * 64,
            official_configuration_sha256="c" * 64,
            verification_mode="current_exact_capture",
            statutory_capture_success_audit_count=1,
            numeric_capture_success_audit_count=1,
            origin_snapshot_id="11111111-1111-4111-8111-111111111111",
            origin_snapshot_version="financial-v3-official-source-origin-snapshot.v1",
            origin_snapshot_sha256="d" * 64,
            origin_snapshot_recorded_at=witness.known_at - timedelta(seconds=1),
        )

    def resolve_point_in_time(
        self,
        witness: FinancialNextSessionSourceTimeWitnessV3,
        *,
        known_at: datetime,
    ) -> FinancialV3TemporalGateResolution:
        self.calls.append(
            ("pit", witness.known_at, FinancialNumericVerificationPurpose.POINT_IN_TIME_READ)
        )
        assert known_at >= witness.earliest_temporal_usability_at
        digest = encode_financial_next_session_witness_v3(witness)["witness_sha256"]
        return FinancialV3TemporalGateResolution(
            witness_sha256=str(digest),
            purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
            known_at=witness.known_at,
            official_source_revision_sha256="a" * 64,
            statutory_capture_id=UUID("11111111-1111-4111-8111-111111111111"),
            numeric_document_capture_id=UUID("11111111-1111-4111-8111-111111111111"),
            official_profile_id="synthetic-profile",
            official_profile_version="synthetic-v1",
            official_publisher_code="synthetic-publisher",
            official_publisher_class="other",
            official_profile_content_sha256="b" * 64,
            official_configuration_sha256="c" * 64,
            verification_mode="point_in_time_exact_capture",
            statutory_capture_success_audit_count=1,
            numeric_capture_success_audit_count=1,
            origin_snapshot_id="11111111-1111-4111-8111-111111111111",
            origin_snapshot_version="financial-v3-official-source-origin-snapshot.v1",
            origin_snapshot_sha256="d" * 64,
            origin_snapshot_recorded_at=witness.known_at - timedelta(seconds=1),
        )


class _NumericVerifier:
    """Record contextual numeric replay inputs and return an explicit result."""

    def __init__(self, *, result: bool = True) -> None:
        self.result = result
        self.contexts: list[FinancialNumericVerificationContext] = []

    def verify(
        self,
        fact: FinancialFact,
        context: FinancialNumericVerificationContext,
    ) -> bool:
        assert fact.numeric_schema == "native-decimal-v2"
        self.contexts.append(context)
        return self.result


def _verifier(
    *,
    endpoint: str,
    body: bytes,
    main_contract: FinancialSharedResponseSourceTimeContractV2 | None,
    balance_contract: BalanceCandidateContract,
    request_params: dict[str, object],
    numeric_result: bool = True,
    reader_body: bytes | None = None,
) -> tuple[FinancialFactV3E1EvidenceVerifier, _TemporalGate, _NumericVerifier]:
    """Wire the exact body replay to test-only temporal and numeric boundaries."""

    gate = _TemporalGate()
    numeric = _NumericVerifier(result=numeric_result)
    return (
        FinancialFactV3E1EvidenceVerifier(
            numeric_verifier=numeric,
            temporal_gate=gate,
            route_resolver=_ExactRoute(endpoint),
            main_body_reader=_MainBodyReader(reader_body if reader_body is not None else body),
            balance_body_reader=_BalanceBodyReader(
                reader_body if reader_body is not None else body,
                request_params,
            ),
            main_notice_contract=main_contract or _main_contract(),
            balance_parser_contract=balance_contract,
        ),
        gate,
        numeric,
    )


def test_official_source_observation_requires_one_audit_for_each_exact_capture() -> None:
    """Neither source origin nor numeric capture is accepted without one audit."""

    valid = _qualified_source_observation()
    assert valid.statutory_capture_success_audit_count == 1
    assert valid.numeric_capture_success_audit_count == 1
    with pytest.raises(ValueError):
        _qualified_source_observation(statutory_audit_count=0)
    with pytest.raises(ValueError):
        _qualified_source_observation(numeric_audit_count=2)


def test_source_read_requires_exact_capture_bytes_and_original_known_at() -> None:
    """C2 body bytes remain bound to the same capture and unchanged witness time."""

    identity, capture, _numeric_capture = _statutory_source_pair()
    known_at = capture.capture_recorded_at + timedelta(seconds=1)
    source_read = FinancialAvailabilitySourceRead(
        reference=capture,
        body=_STATUTORY_BODY,
        checked_at=known_at + timedelta(seconds=1),
        known_at=known_at,
    )
    assert (
        _require_source_read(
            source_read,
            expected_source=capture,
            known_at=known_at,
        )
        is source_read
    )
    with pytest.raises(FinancialV3TemporalGateBlocked):
        _require_source_read(
            source_read,
            expected_source=capture,
            known_at=known_at + timedelta(seconds=1),
        )
    wrong_capture = replace(capture, capture_id=uuid4())
    with pytest.raises(FinancialV3TemporalGateBlocked):
        _require_source_read(
            source_read,
            expected_source=wrong_capture,
            known_at=known_at,
        )


def test_ann_null_replacement_requires_same_call_v3_verification() -> None:
    """Legacy completeness stays strict; only a verified v3 row can replace it."""

    fact, _witness_value, _body, _main, _balance, _params = _fact_and_witness(
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
    )
    old_decision = fact.decision_evidence
    assert old_decision is not None
    old_witness = old_decision.source_time_witness_v3
    assert old_witness is not None
    old_artifact = old_decision.artifact_reference
    new_body_sha256 = "f" * 64
    new_artifact = replace(
        old_artifact,
        capture_id=uuid4(),
        evidence=replace(
            old_artifact.evidence,
            body_sha256=new_body_sha256,
        ),
    )
    new_row = replace(
        old_witness.financial_row,
        artifact_reference=new_artifact,
        row_projection_sha256="e" * 64,
    )
    new_witness = replace(old_witness, financial_row=new_row)
    new_fact = replace(
        fact,
        source_evidence=replace(
            fact.source_evidence,
            raw_payload_hash=new_body_sha256,
        ),
        decision_evidence=replace(
            old_decision,
            artifact_reference=new_artifact,
            source_time_witness_v3=new_witness,
        ),
        numeric_evidence=replace(
            fact.numeric_evidence,
            body_sha256=new_body_sha256,
        ),
    )
    new_fact.__post_init__()
    assert new_fact.source_evidence is not None
    assert not new_fact.source_evidence.is_complete
    assert new_fact.numeric_evidence is not None
    stored_row = _model_from_fact(fact, ingested_run_id=None)

    _validate_existing_row_update(
        new_fact,
        stored_row,
        ingested_run_id=None,
        v3_evidence_verified=True,
    )
    with pytest.raises(FinancialFactProvenanceConflictError):
        _validate_existing_row_update(
            new_fact,
            stored_row,
            ingested_run_id=None,
            v3_evidence_verified=False,
        )


@pytest.mark.parametrize(
    ("endpoint", "purpose"),
    [
        (AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT, FinancialNumericVerificationPurpose.CURRENT_READ),
        (AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT, FinancialNumericVerificationPurpose.CURRENT_READ),
    ],
)
def test_current_v3_replays_the_fact_own_notice_row_and_numeric_context(
    endpoint: str,
    purpose: FinancialNumericVerificationPurpose,
) -> None:
    """Each endpoint body independently supplies its own exact NOTICE binding."""

    fact, witness, body, main_contract, balance_contract, request_params = _fact_and_witness(
        endpoint=endpoint
    )
    verifier, gate, numeric = _verifier(
        endpoint=endpoint,
        body=body,
        main_contract=main_contract,
        balance_contract=balance_contract,
        request_params=request_params,
    )

    assert verifier.verify(fact, FinancialV3FactVerificationRequest(purpose)) is True
    assert gate.calls == [("current", witness.known_at, purpose)]
    assert numeric.contexts == [
        FinancialNumericVerificationContext(known_at=_CURRENT_AT, purpose=purpose)
    ]


def test_pit_reuses_original_witness_known_at_and_uses_explicit_query_cutoff() -> None:
    """PIT never replaces the persisted witness clock with its later query cutoff."""

    endpoint = AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
    fact, witness, body, main_contract, balance_contract, request_params = _fact_and_witness(
        endpoint=endpoint
    )
    verifier, gate, numeric = _verifier(
        endpoint=endpoint,
        body=body,
        main_contract=main_contract,
        balance_contract=balance_contract,
        request_params=request_params,
    )
    cutoff = witness.earliest_temporal_usability_at + timedelta(minutes=2)
    request = FinancialV3FactVerificationRequest(
        FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
        cutoff,
    )

    assert verifier.verify(fact, request) is True
    assert gate.calls == [
        ("pit", witness.known_at, FinancialNumericVerificationPurpose.POINT_IN_TIME_READ)
    ]
    assert numeric.contexts == [
        FinancialNumericVerificationContext(
            known_at=cutoff,
            purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
        )
    ]


@pytest.mark.parametrize(
    ("endpoint", "wrong_projection"),
    [
        (AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT, "f" * 64),
        (AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT, "e" * 64),
    ],
)
def test_projection_hash_is_replayed_from_each_own_raw_body(
    endpoint: str,
    wrong_projection: str,
) -> None:
    """A parser-produced row digest cannot be carried over after body drift."""

    fact, _witness_value, body, main_contract, balance_contract, request_params = _fact_and_witness(
        endpoint=endpoint,
        changed_contract_row_projection=wrong_projection,
    )
    verifier, _gate, _numeric = _verifier(
        endpoint=endpoint,
        body=body,
        main_contract=main_contract,
        balance_contract=balance_contract,
        request_params=request_params,
    )

    assert (
        verifier.verify(
            fact,
            FinancialV3FactVerificationRequest(FinancialNumericVerificationPurpose.CURRENT_READ),
        )
        is False
    )


@pytest.mark.parametrize(
    "endpoint",
    [AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT, AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT],
)
def test_notice_text_from_body_cannot_be_replaced_by_other_endpoint_or_caller_date(
    endpoint: str,
) -> None:
    """The exact fact body must contain the NOTICE_DATE used by its witness."""

    fact, _witness_value, body, main_contract, balance_contract, request_params = _fact_and_witness(
        endpoint=endpoint
    )
    body_reader = (
        _main_body(notice_text="2026-11-17 00:00:00")
        if endpoint == AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
        else _balance_body(notice_text="2026-11-17 00:00:00")
    )
    verifier, _gate, _numeric = _verifier(
        endpoint=endpoint,
        body=body,
        main_contract=main_contract,
        balance_contract=balance_contract,
        request_params=request_params,
        reader_body=body_reader,
    )

    assert (
        verifier.verify(
            fact,
            FinancialV3FactVerificationRequest(FinancialNumericVerificationPurpose.CURRENT_READ),
        )
        is False
    )


def test_v3_write_without_composite_verifier_blocks_before_database_access() -> None:
    """Missing qualified v3 wiring cannot fall through to the v2 timestamp path."""

    from apps.data_center.infrastructure.financial_fact_write_guard import (
        FinancialFactProvenanceConflictError,
        bulk_upsert_financial_facts,
    )

    fact, _witness_value, _body, _main_contract_value, _balance_contract_value, _params = (
        _fact_and_witness(endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT)
    )

    with pytest.raises(FinancialFactProvenanceConflictError, match="v3 financial fact"):
        bulk_upsert_financial_facts([fact])


def test_repository_v3_read_and_publication_keep_announcement_date_absent() -> None:
    """The guarded candidate returns available_at while preserving date-only NOTICE."""

    from apps.data_center.application.financial_v3_e1_verification import (
        FinancialV3FactVerificationRequest,
    )
    from apps.data_center.infrastructure.financial_fact_repository import (
        FinancialFactRepository,
        _financial_publication_reference,
    )
    from apps.data_center.infrastructure.financial_fact_write_guard import _model_from_fact

    fact, _witness_value, body, main_contract, balance_contract, request_params = _fact_and_witness(
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
    )
    verifier, _gate, _numeric = _verifier(
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        body=body,
        main_contract=main_contract,
        balance_contract=balance_contract,
        request_params=request_params,
    )
    row = _model_from_fact(fact, ingested_run_id=None)
    row.pk = 991
    row.fetched_at = fact.fetched_at
    repository = FinancialFactRepository(v3_evidence_verifier=verifier)
    current_read = FinancialV3FactVerificationRequest(
        FinancialNumericVerificationPurpose.CURRENT_READ
    )
    hydrated = repository._read_model(row, verification_request=current_read)
    assert hydrated.source_evidence is not None
    assert hydrated.source_evidence.announced_at is None
    assert hydrated.available_at == fact.available_at

    current_publication = FinancialV3FactVerificationRequest(
        FinancialNumericVerificationPurpose.CURRENT_PUBLICATION
    )
    publication = _financial_publication_reference(
        row,
        require_verified_source_evidence=True,
        v3_evidence_verifier=verifier,
        v3_verification_request=current_publication,
    )
    assert publication.source_published_at is None
    assert publication.available_at == fact.available_at
