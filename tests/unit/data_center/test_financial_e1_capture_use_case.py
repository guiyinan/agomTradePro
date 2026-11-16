"""Fake-boundary tests for the canonical two-response E1 capture use case."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from apps.data_center.application import financial_e1_capture_use_case as e1_app
from apps.data_center.application.egress_service import (
    FinancialResponseAttemptBudget,
    FinancialResponseCaptureResult,
    FinancialResponseRequestFailed,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialProviderIdentity,
)
from apps.data_center.domain import financial_e1_capture_contract as financial_e1
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)
from apps.data_center.domain.financial_response_artifact import (
    FinancialResponseArtifact,
    FinancialResponseArtifactRef,
)
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
    raw_body_sha256,
)
from apps.data_center.infrastructure import financial_e1_capture_gateway as e1_infra
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
)
from core.exceptions import DataFetchError

PROVIDER = "akshare"
ASSET = "000858.SZ"
PERIOD_END = date(2026, 9, 30)
MAIN_NOTICE = date(2026, 10, 25)
BALANCE_NOTICE = date(2026, 10, 27)
BALANCE_ENDPOINT = "https://datacenter-web.eastmoney.com/api/data/v1/get"
MAIN_BODY = (
    b'{"success":true,"code":0,"result":{"count":1,"data":[{'
    b'"SECUCODE":"000858.SZ","REPORT_DATE":"2026-09-30 00:00:00",'
    b'"NOTICE_DATE":"2026-10-25 00:00:00","TOTALOPERATEREVE":123456789.1234567'
    b"}]}}"
)
BALANCE_BODY = (
    b'{"success":true,"code":0,"result":{"count":1,"data":[{'
    b'"SECUCODE":"000858.SZ","REPORT_DATE":"2026-09-30 00:00:00",'
    b'"NOTICE_DATE":"2026-10-27 00:00:00","BALANCE_FIELD_A":987654321.125,'
    b'"BALANCE_FIELD_B":123456789.875,"BALANCE_FIELD_C":555555555.25'
    b"}]}}"
)
RESPONSE_AT = datetime(2026, 10, 28, 1, 30, tzinfo=UTC)
KNOWN_AT = datetime(2026, 10, 28, 1, 31, tzinfo=UTC)


def _source_contract() -> object:
    """Build a synthetic Main NOTICE contract without claiming approval."""

    return financial_e1.FinancialSharedResponseSourceTimeContractV2(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        contract_id="test.shared-main-notice-date",
        contract_version="test-v2",
        parser_version="test-json-row-parser.v2",
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
        row_identity_prefix=PROVIDER,
        projection_fields=("SECUCODE", "REPORT_DATE", "NOTICE_DATE"),
    )


def _plan() -> object:
    """Create an explicit two-slot test plan with no retry or pagination."""

    main = financial_e1.FinancialE1EndpointRequest(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        roles=(
            financial_e1.FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
            financial_e1.FinancialE1ResponseRole.MAIN_NOTICE_DATE,
        ),
        request_asset_code=ASSET,
        request_period_end=PERIOD_END,
        request_announcement_date=MAIN_NOTICE,
        max_attempts=1,
        pagination_policy="one_response",
    )
    balance = financial_e1.FinancialE1EndpointRequest(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=BALANCE_ENDPOINT,
        roles=(financial_e1.FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,),
        request_asset_code=ASSET,
        request_period_end=PERIOD_END,
        request_announcement_date=None,
        max_attempts=1,
        pagination_policy="one_response",
    )
    return financial_e1.FinancialE1CaptureContractV1(
        provider_name=PROVIDER,
        asset_code=ASSET,
        period_end=PERIOD_END,
        announcement_date=MAIN_NOTICE,
        main_request=main,
        balance_request=balance,
        source_time_contract=_source_contract(),
        maximum_physical_attempts=2,
    )


class _MemoryBodyStore:
    """Store exact bytes behind typed test references for repository testing."""

    def __init__(self) -> None:
        self.rows: dict[UUID, tuple[FinancialResponseArtifactRef, bytes]] = {}
        self.read_count = 0

    def store(self, artifact: FinancialResponseArtifact) -> FinancialResponseArtifactRef:
        reference = FinancialResponseArtifactRef(
            capture_id=artifact.capture_id,
            location=f"financial-response:///v1/{artifact.capture_id}.frb",
            evidence=artifact.evidence,
            format_version="financial-response-artifact.v1",
            encryption_algorithm="fernet-aes128cbc-hmacsha256",
            encryption_key_ref="test.key",
            encryption_key_version="test-v1",
        )
        existing = self.rows.get(artifact.capture_id)
        if existing is not None and existing != (reference, artifact.body):
            raise ValueError("test body store capture conflict")
        self.rows[artifact.capture_id] = (reference, artifact.body)
        return reference

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        self.read_count += 1
        stored = self.rows.get(reference.capture_id)
        if stored is None or stored[0] != reference:
            raise ValueError("test body store reference mismatch")
        return stored[1]

    def inspect(self, reference: FinancialResponseArtifactRef) -> FinancialResponseArtifactRef:
        stored = self.rows.get(reference.capture_id)
        if stored is None or stored[0] != reference:
            raise ValueError("test body store reference mismatch")
        return reference


class _MemoryAuditRepository:
    """Mimic persisted identity/hash assignment while retaining all audit rows."""

    def __init__(self) -> None:
        self.rows: list[RawAudit] = []

    def log(self, audit: RawAudit) -> RawAudit:
        persisted = replace(
            audit,
            raw_audit_id=str(uuid4()),
            content_hash=raw_audit_content_hash(audit),
        )
        self.rows.append(persisted)
        return persisted

    def log_failure(self, audit: RawAudit) -> RawAudit:
        persisted = replace(
            audit,
            raw_audit_id=str(uuid4()),
            content_hash=raw_audit_content_hash(audit),
        )
        self.rows.append(persisted)
        return persisted

    def find_by_artifact_capture_id(self, capture_id: UUID) -> RawAudit | None:
        found = self.list_by_artifact_capture_id(capture_id)
        return found[0] if found else None

    def find_by_failure_capture_id(self, capture_id: UUID) -> RawAudit | None:
        found = [
            row
            for row in self.rows
            if row.extra.get("financial_response_failure", {}).get("capture_id") == str(capture_id)
        ]
        return found[0] if found else None

    def list_by_artifact_capture_id(self, capture_id: UUID) -> list[RawAudit]:
        return [
            row
            for row in self.rows
            if row.extra.get("financial_response_artifact", {}).get("capture_id") == str(capture_id)
        ]


class _RequestProjector:
    """Provide exact per-endpoint route input for the fake capture tests."""

    def project(self, request: object) -> object:
        assert type(request) is financial_e1.FinancialE1EndpointRequest
        target = (
            "https://datacenter.eastmoney.com/securities/api/data/get"
            if request.endpoint == AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
            else BALANCE_ENDPOINT
        )
        return e1_infra.FinancialE1RequestProjection(
            request=request,
            context=EgressRequestContext(
                provider_id=77,
                dataset_key=request.dataset_key,
                target_url=target,
                deployment_region="test-region",
            ),
            method="GET",
            params={
                "asset": request.request_asset_code,
                "period_end": request.request_period_end.isoformat(),
            },
            json_body=None,
            headers=None,
            request_scope=FinancialRequestScope(
                provider_name=request.provider_name,
                dataset_key=request.dataset_key,
                asset_code=request.request_asset_code,
                period_limit=1,
            ),
            declared_response_scope=FinancialResponseScope(
                asset_codes=(request.request_asset_code,),
                period_ends=(),
                row_count=0,
            ),
            provider_id=77,
        )


class _ProviderResolver:
    """Resolve a non-secret persisted provider identity for the capture route."""

    def __init__(self, *, source_type: str = PROVIDER, is_active: bool = True) -> None:
        self.source_type = source_type
        self.is_active = is_active
        self.calls: list[int] = []

    def resolve_by_id(self, provider_id: int) -> FinancialProviderIdentity | None:
        self.calls.append(provider_id)
        if provider_id != 77:
            return None
        return FinancialProviderIdentity(
            provider_id=77,
            name="AKShare display label",
            source_type=self.source_type,
            is_active=self.is_active,
        )


class _ScopeVerifier:
    """Promote only the synthetic requested asset/period coverage in unit tests."""

    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.calls: list[tuple[str, bytes]] = []

    def verify(
        self,
        request: object,
        *,
        raw_body: bytes,
        payload: object,
        evidence: FinancialResponseEvidence,
    ) -> FinancialResponseEvidence:
        assert type(request) is financial_e1.FinancialE1EndpointRequest
        self.calls.append((request.endpoint, raw_body))
        if self.reject:
            raise ValueError("synthetic body scope mismatch")
        if request.request_announcement_date is not None:
            assert request.request_announcement_date.isoformat() in raw_body.decode("utf-8")
        scope = FinancialResponseScope(
            asset_codes=(request.request_asset_code,),
            period_ends=(request.request_period_end,),
            row_count=1,
        )
        return replace(
            evidence,
            response_scope=scope,
            response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
        )


class _EgressRunner:
    """Return one synthetic raw capture after reserving one actual budget slot."""

    def __init__(self, *, extra_reservation: bool = False) -> None:
        self.extra_reservation = extra_reservation
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        request_id: UUID,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        request_scope: FinancialRequestScope,
        response_scope: FinancialResponseScope,
        max_attempts: int,
        attempt_budget: FinancialResponseAttemptBudget,
    ) -> FinancialResponseCaptureResult:
        self.calls.append(
            {
                "context": context,
                "request_id": request_id,
                "max_attempts": max_attempts,
                "budget": attempt_budget,
            }
        )
        if not attempt_budget.reserve():
            raise FinancialResponseRequestFailed(
                "budget exhausted",
                code="FINANCIAL_PROVIDER_REQUEST_HARD_LIMIT_EXCEEDED",
                observed_attempts=0,
            )
        if self.extra_reservation and not attempt_budget.reserve():
            raise FinancialResponseRequestFailed(
                "budget exhausted",
                code="FINANCIAL_PROVIDER_REQUEST_HARD_LIMIT_EXCEEDED",
                observed_attempts=1,
            )
        body = (
            MAIN_BODY
            if context.target_url.startswith("https://datacenter.eastmoney.com/")
            else BALANCE_BODY
        )
        evidence = FinancialResponseEvidence(
            body_sha256=raw_body_sha256(body),
            body_size_bytes=len(body),
            response_completed_at=RESPONSE_AT,
            request_scope=request_scope,
            response_scope=response_scope,
            body_scope=FinancialResponseBodyScope.BATCH,
            response_scope_basis=FinancialResponseScopeBasis.CALLER_DECLARED,
        )
        return FinancialResponseCaptureResult(
            payload=json.loads(body, parse_float=Decimal),
            evidence=evidence,
            raw_body=body,
            physical_request_attempts=1,
        )


class _Clock:
    """Return a fixed aware server clock for deterministic orchestration tests."""

    def now_utc(self) -> datetime:
        return KNOWN_AT


class _Qualification:
    """Record both pre-send and post-capture eligibility checks."""

    def __init__(self, *, reject_after_capture: bool = False) -> None:
        self.reject_after_capture = reject_after_capture
        self.ready_calls = 0
        self.complete_calls = 0

    def assert_capture_ready(self, plan: object, *, known_at: datetime) -> None:
        self.ready_calls += 1
        assert known_at == KNOWN_AT

    def assert_captured_pair_qualified(
        self,
        plan: object,
        *,
        main_response: object,
        balance_response: object,
        main_notice: object,
        main_numeric: object,
        balance_numeric: object,
        known_at: datetime,
    ) -> None:
        self.complete_calls += 1
        assert (
            main_response.retention.reference.capture_id
            != balance_response.retention.reference.capture_id
        )
        assert main_notice.row.notice_date == MAIN_NOTICE
        assert balance_numeric.row.notice_date == BALANCE_NOTICE
        if self.reject_after_capture:
            raise DataFetchError("synthetic qualification revoke", code="E1_QUALIFICATION_REVOKED")


class _RoleReplayer:
    """Independently replay Main NOTICE/numeric and Balance numeric test roles."""

    def replay_main_notice(self, request: object, response: object, *, plan: object) -> object:
        reference = financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=response.retention.reference,
            contract=plan.source_time_contract,
            requested_asset_code=request.request_asset_code,
            requested_period_end=request.request_period_end,
            requested_announcement_date=request.request_announcement_date,
        )
        binding = financial_e1.match_shared_main_notice_date_v2(
            response.raw_body, artifact_reference=reference
        )
        assert binding is not None
        row = self._main_row(request, response, binding)
        return e1_app.FinancialE1RoleReplay(
            role=financial_e1.FinancialE1ResponseRole.MAIN_NOTICE_DATE,
            row=row,
            native_observations=(),
            notice_binding=binding,
            provider_payload=response.provider_payload,
        )

    def replay_main_numeric(self, request: object, response: object, *, plan: object) -> object:
        reference = financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=response.retention.reference,
            contract=plan.source_time_contract,
            requested_asset_code=request.request_asset_code,
            requested_period_end=request.request_period_end,
            requested_announcement_date=plan.announcement_date,
        )
        binding = financial_e1.match_shared_main_notice_date_v2(
            response.raw_body, artifact_reference=reference
        )
        observation = financial_e1.build_shared_main_numeric_observation_v2(
            response.raw_body,
            artifact_reference=reference,
            metric_contract=_metric_contract("test.main.revenue", "TOTALOPERATEREVE"),
        )
        assert binding is not None and observation is not None
        row = self._main_row(request, response, binding)
        return e1_app.FinancialE1RoleReplay(
            role=financial_e1.FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
            row=row,
            native_observations=(observation,),
            notice_binding=None,
            provider_payload=response.provider_payload,
        )

    def replay_balance_numeric(self, request: object, response: object, *, plan: object) -> object:
        raw = json.loads(response.raw_body, parse_float=Decimal)["result"]["data"][0]
        if raw["SECUCODE"] != request.request_asset_code:
            raise ValueError("synthetic Balance row asset mismatch")
        notice_date = date.fromisoformat(raw["NOTICE_DATE"][:10])
        row_id = f"balance:{request.request_asset_code}:{request.request_period_end.isoformat()}"
        row_sha = hashlib.sha256(response.raw_body + b"/balance-row").hexdigest()
        observations = tuple(
            NativeFinancialMetricObservation.from_raw_value(
                contract=_metric_contract(f"test.balance.metric-{index}", field_name),
                raw_value=raw[field_name],
                source_field=field_name,
                body_sha256=response.retention.reference.body_sha256,
                native_row_id=row_id,
            )
            for index, field_name in enumerate(
                ("BALANCE_FIELD_A", "BALANCE_FIELD_B", "BALANCE_FIELD_C"),
                start=1,
            )
        )
        identity = e1_app.FinancialE1NativeRowIdentity(
            artifact_reference=response.retention.reference,
            provider_name=request.provider_name,
            dataset_key=request.dataset_key,
            endpoint=request.endpoint,
            asset_code=request.request_asset_code,
            period_end=request.request_period_end,
            period_type=FinancialPeriodType.QUARTERLY,
            notice_date=notice_date,
            native_row_id=row_id,
            row_projection_sha256=row_sha,
            matched_row_count=1,
        )
        return e1_app.FinancialE1RoleReplay(
            role=financial_e1.FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,
            row=identity,
            native_observations=observations,
            notice_binding=None,
            provider_payload=response.provider_payload,
        )

    @staticmethod
    def _main_row(request: object, response: object, binding: object) -> object:
        return e1_app.FinancialE1NativeRowIdentity(
            artifact_reference=response.retention.reference,
            provider_name=request.provider_name,
            dataset_key=request.dataset_key,
            endpoint=request.endpoint,
            asset_code=request.request_asset_code,
            period_end=request.request_period_end,
            period_type=FinancialPeriodType.QUARTERLY,
            notice_date=binding.notice_date,
            native_row_id=binding.native_row_id,
            row_projection_sha256=binding.row_projection_sha256,
            matched_row_count=1,
        )


class _FailMainNoticeReplayer(_RoleReplayer):
    """Raise after Main retention to exercise a parser-level non-success path."""

    def replay_main_notice(self, request: object, response: object, *, plan: object) -> object:
        raise DataFetchError("synthetic NOTICE row ambiguity", code="E1_NOTICE_REPLAY_BLOCKED")


def _metric_contract(metric: str, field_name: str) -> FinancialMetricSourceContract:
    """Construct explicit test-only units and scale, never production defaults."""

    return FinancialMetricSourceContract(
        provider=PROVIDER,
        dataset_key="equity.financial.fact",
        metric_code=metric,
        source_field=field_name,
        source_unit="source_unit",
        canonical_unit="canonical_unit",
        scale_numerator=1,
        scale_denominator=1,
        contract_version="test-v1",
        origin="native",
    )


def _gateway(
    *,
    runner: _EgressRunner | None = None,
    main_verifier: _ScopeVerifier | None = None,
    balance_verifier: _ScopeVerifier | None = None,
    duplicate_audit: bool = False,
    corrupt_readback: bool = False,
    provider_source_type: str = PROVIDER,
    provider_active: bool = True,
) -> tuple[
    object, _EgressRunner, _MemoryBodyStore, _MemoryAuditRepository, _ScopeVerifier, _ScopeVerifier
]:
    """Build the actual repository/gateway composition over in-memory ports."""

    egress = runner or _EgressRunner()
    main_scope = main_verifier or _ScopeVerifier()
    balance_scope = balance_verifier or _ScopeVerifier()
    body_store = _MemoryBodyStore()
    if corrupt_readback:
        original_read = body_store.read

        def read_corrupt(reference: FinancialResponseArtifactRef) -> bytes:
            return original_read(reference) + b"corrupt"

        body_store.read = read_corrupt  # type: ignore[method-assign]
    audits = _MemoryAuditRepository()
    if duplicate_audit:
        original_list = audits.list_by_artifact_capture_id

        def list_duplicate(capture_id: UUID) -> list[RawAudit]:
            found = original_list(capture_id)
            return found + found

        audits.list_by_artifact_capture_id = list_duplicate  # type: ignore[method-assign]
    repository = FinancialResponseArtifactRepository(
        body_store,  # type: ignore[arg-type]
        audits,  # type: ignore[arg-type]
        failure_audit_repository=audits,  # type: ignore[arg-type]
    )
    gateway = e1_infra.FinancialE1RetainedCaptureGateway(
        projection_port=_RequestProjector(),
        provider_identity_resolver=_ProviderResolver(
            source_type=provider_source_type,
            is_active=provider_active,
        ),
        scope_verifiers={
            AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT: main_scope,
            BALANCE_ENDPOINT: balance_scope,
        },
        artifact_repository=repository,
        audit_repository=audits,
        capture_runner=egress,
    )
    return gateway, egress, body_store, audits, main_scope, balance_scope


def _execute(
    *,
    reject_ready: bool = False,
    reject_after_capture: bool = False,
    extra_reservation: bool = False,
    main_scope_reject: bool = False,
    balance_scope_reject: bool = False,
    duplicate_audit: bool = False,
    corrupt_readback: bool = False,
    role_replayer: object | None = None,
) -> tuple[object, _EgressRunner, _MemoryBodyStore, _MemoryAuditRepository, _Qualification]:
    """Run the candidate application flow over the exact retention repository."""

    gateway, runner, store, audit, main_verifier, balance_verifier = _gateway(
        runner=_EgressRunner(extra_reservation=extra_reservation),
        main_verifier=_ScopeVerifier(reject=main_scope_reject),
        balance_verifier=_ScopeVerifier(reject=balance_scope_reject),
        duplicate_audit=duplicate_audit,
        corrupt_readback=corrupt_readback,
    )
    qualification = _Qualification(reject_after_capture=reject_after_capture)
    if reject_ready:

        def assert_not_ready(plan: object, *, known_at: datetime) -> None:
            qualification.ready_calls += 1
            raise DataFetchError("synthetic missing catalog row", code="E1_NOT_QUALIFIED")

        qualification.assert_capture_ready = assert_not_ready
    use_case = e1_app.CaptureFinancialE1UseCase(
        capture_gateway=gateway,
        role_replayer=role_replayer or _RoleReplayer(),
        qualification=qualification,
        clock=_Clock(),
        capture_id_factory=iter(
            (
                UUID("00000000-0000-4000-8000-000000000101"),
                UUID("00000000-0000-4000-8000-000000000102"),
            )
        ).__next__,
    )
    return use_case.execute(_plan()), runner, store, audit, qualification


def test_real_retention_gateway_and_use_case_preserve_each_endpoint_identity() -> None:
    """Main replays both roles from one audit; Balance retains its own row/date."""

    output, runner, store, audits, qualification = _execute()

    assert output.outcome == "captured", (output.failure_code, output.reserved_attempts)
    assert output.evidence_only is True
    assert output.production_ready is False
    assert output.must_not_use_for_decision is True
    assert output.reserved_attempts == 2
    assert len(runner.calls) == 2
    assert all(call["max_attempts"] == 1 for call in runner.calls)
    assert [row.request_params["endpoint"] for row in audits.rows] == [
        AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        BALANCE_ENDPOINT,
    ]
    assert all(
        row.request_params
        == {
            "endpoint": endpoint,
            "asset": ASSET,
            "period_end": PERIOD_END.isoformat(),
        }
        for row, endpoint in zip(
            audits.rows, (AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT, BALANCE_ENDPOINT), strict=True
        )
    )
    assert store.read_count == 2
    pair = output.captured_pair
    assert pair is not None
    main = pair.main
    balance = pair.balance
    assert main.notice.row.artifact_reference == main.numeric.row.artifact_reference
    assert main.notice.row.native_row_id == main.numeric.row.native_row_id
    assert main.response.retention.audit.raw_audit_id == next(
        row.raw_audit_id
        for row in audits.rows
        if row.extra["financial_response_artifact"]["capture_id"]
        == str(main.response.retention.reference.capture_id)
    )
    assert (
        balance.response.retention.reference.capture_id
        != main.response.retention.reference.capture_id
    )
    assert (
        balance.response.retention.audit.raw_audit_id != main.response.retention.audit.raw_audit_id
    )
    assert main.notice.row.notice_date == MAIN_NOTICE
    assert balance.numeric.row.notice_date == BALANCE_NOTICE
    assert balance.financial_rows[0].artifact_reference == balance.response.retention.reference
    assert balance.financial_rows[0].notice_date == BALANCE_NOTICE
    assert balance.financial_rows[0].native_row_id == balance.numeric.row.native_row_id
    assert len(balance.numeric.native_observations) == 3
    assert len(balance.financial_rows) == 3
    assert all(
        row.artifact_reference == balance.response.retention.reference
        and row.notice_date == BALANCE_NOTICE
        and row.native_row_id == balance.numeric.row.native_row_id
        for row in balance.financial_rows
    )
    assert qualification.ready_calls == 1
    assert qualification.complete_calls == 1
    with pytest.raises(ValueError, match="responses must exactly match"):
        replace(output, retained_responses=(balance.response, main.response))


def test_upstream_query_cannot_replace_the_audit_endpoint_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse an ambiguous audit identity before retaining or sending a request."""

    original_project = _RequestProjector.project

    def project_collision(self: _RequestProjector, request: object) -> object:
        projection = original_project(self, request)
        return replace(projection, params={"endpoint": "untrusted-upstream-marker"})

    monkeypatch.setattr(_RequestProjector, "project", project_collision)
    gateway, runner, store, audits, _main, _balance = _gateway()
    budget = FinancialResponseAttemptBudget(maximum_attempts=2)
    with pytest.raises(e1_infra.FinancialE1CaptureInfrastructureError) as blocked:
        gateway.capture_one(
            _plan().main_request,
            request_id=uuid4(),
            attempt_budget=budget,
            run_id=None,
        )
    assert blocked.value.code == "FINANCIAL_E1_REQUEST_PROJECTION_BLOCKED"
    assert budget.reserved_attempts == 0
    assert runner.calls == []
    assert store.rows == {}
    assert audits.rows == []


def test_missing_qualification_blocks_before_any_physical_request() -> None:
    """An empty or missing real catalog must deny capture before egress."""

    output, runner, store, audit, qualification = _execute(reject_ready=True)

    assert output.outcome == "blocked"
    assert output.captured_pair is None
    assert output.reserved_attempts == 0
    assert runner.calls == []
    assert store.rows == {}
    assert audit.rows == []
    assert qualification.ready_calls == 1


def test_main_body_replay_failure_stops_before_second_endpoint() -> None:
    """A malformed Main row cannot be covered by a later Balance response."""

    output, runner, _store, _audit, _qualification = _execute(main_scope_reject=True)

    assert output.outcome == "failed"
    assert output.captured_pair is None
    assert output.reserved_attempts == 1
    assert len(runner.calls) == 1
    assert output.retained_responses == ()


def test_main_role_parser_failure_after_retention_is_blocked_without_balance_send() -> None:
    """A retained body with an ambiguous NOTICE row cannot expose a pair."""

    output, runner, _store, audit, _qualification = _execute(
        role_replayer=_FailMainNoticeReplayer()
    )

    assert output.outcome == "blocked"
    assert output.captured_pair is None
    assert output.reserved_attempts == 1
    assert len(runner.calls) == 1
    assert len(output.retained_responses) == 1
    assert len(audit.rows) == 1


def test_balance_body_replay_failure_returns_partial_not_complete_pair() -> None:
    """A rejected Balance response leaves Main evidence but no complete pair."""

    output, runner, _store, audit, _qualification = _execute(balance_scope_reject=True)

    assert output.outcome == "partial"
    assert output.captured_pair is None
    assert output.reserved_attempts == 2
    assert len(runner.calls) == 2
    assert len(output.retained_responses) == 1
    failure_audits = [row for row in audit.rows if row.capability == "financial_response_failure"]
    assert len(failure_audits) == 1


def test_post_capture_revocation_recheck_blocks_pair_but_keeps_both_audits() -> None:
    """A late current qualification failure cannot expose a success pair."""

    output, runner, _store, audit, qualification = _execute(reject_after_capture=True)

    assert output.outcome == "blocked"
    assert output.captured_pair is None
    assert output.reserved_attempts == 2
    assert len(runner.calls) == 2
    assert len(output.retained_responses) == 2
    assert len(audit.rows) == 2
    assert qualification.complete_calls == 1


def test_egress_attempt_budget_rejects_a_hidden_retry() -> None:
    """A runner reserving two sends in one slot is rejected before retention."""

    output, runner, store, audit, _qualification = _execute(extra_reservation=True)

    assert output.outcome == "failed"
    assert output.captured_pair is None
    assert output.reserved_attempts == 2
    assert len(runner.calls) == 1
    assert store.rows == {}
    assert audit.rows == []


def test_capture_budget_itself_refuses_a_third_physical_send() -> None:
    """The shared egress budget has an atomic hard ceiling of two sends."""

    budget = FinancialResponseAttemptBudget(2)

    assert budget.reserve() is True
    assert budget.reserve() is True
    assert budget.reserve() is False
    assert budget.reserved_attempts == 2


def test_duplicate_raw_audit_or_corrupt_body_readback_never_returns_pair() -> None:
    """The real repository gateway checks unique audit identity and exact reread."""

    for options in ({"duplicate_audit": True}, {"corrupt_readback": True}):
        output, _runner, _store, _audit, _qualification = _execute(**options)
        assert output.outcome == "failed"
        assert output.captured_pair is None


def test_unknown_endpoint_has_no_fallback_verifier_or_transport_send() -> None:
    """The endpoint table is exact; an unregistered Balance alias cannot send."""

    plan = _plan()
    runner = _EgressRunner()
    body_store = _MemoryBodyStore()
    audits = _MemoryAuditRepository()
    repository = FinancialResponseArtifactRepository(
        body_store,  # type: ignore[arg-type]
        audits,  # type: ignore[arg-type]
        failure_audit_repository=audits,  # type: ignore[arg-type]
    )
    gateway = e1_infra.FinancialE1RetainedCaptureGateway(
        projection_port=_RequestProjector(),
        provider_identity_resolver=_ProviderResolver(),
        scope_verifiers={AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT: _ScopeVerifier()},
        artifact_repository=repository,
        audit_repository=audits,
        capture_runner=runner,
    )
    budget = FinancialResponseAttemptBudget(2)

    with pytest.raises(DataFetchError):
        gateway.capture_one(
            plan.balance_request,
            request_id=UUID("00000000-0000-4000-8000-000000000202"),
            attempt_budget=budget,
            run_id=None,
        )

    assert runner.calls == []
    assert budget.reserved_attempts == 0


@pytest.mark.parametrize(
    ("source_type", "is_active"),
    [("other-provider", True), (PROVIDER, False)],
)
def test_unmatched_or_inactive_provider_is_blocked_before_transport(
    source_type: str,
    is_active: bool,
) -> None:
    """The exact persisted source type and active state are checked before send."""

    gateway, runner, store, audits, _main, _balance = _gateway(
        provider_source_type=source_type,
        provider_active=is_active,
    )
    budget = FinancialResponseAttemptBudget(2)

    with pytest.raises(DataFetchError):
        gateway.capture_one(
            _plan().main_request,
            request_id=UUID("00000000-0000-4000-8000-000000000303"),
            attempt_budget=budget,
            run_id=None,
        )

    assert runner.calls == []
    assert budget.reserved_attempts == 0
    assert store.rows == {}
    assert audits.rows == []
