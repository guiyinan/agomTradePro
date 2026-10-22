from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID

import pytest

from apps.data_center.application.instrument_reference_capture import (
    CaptureClaimDisposition,
    CaptureExecutionStatus,
    CaptureInvocationMode,
    CaptureScopeProgressState,
    InstrumentReferenceCaptureClaimResult,
    InstrumentReferenceCaptureInvocation,
    InstrumentReferenceCaptureLease,
    InstrumentReferenceCaptureParsedScope,
    InstrumentReferenceCaptureRetainedResponse,
    InstrumentReferenceCaptureScopeProgress,
)
from apps.data_center.application.instrument_reference_capture_use_case import (
    CaptureInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.application.instrument_reference_source import (
    InstrumentReferenceAuditOccurrence,
    InstrumentReferenceAuditOccurrenceReceipt,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_capture import (
    CaptureClaimEpoch,
    CaptureOwnerCapability,
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceCaptureScope,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
    make_instrument_reference_mapping_record,
    make_instrument_reference_snapshot_record,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceOccurrence,
    InstrumentReferenceProviderContract,
    InstrumentReferenceRecord,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    canonical_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload

_CAPTURE_ID = UUID("4b3a287f-945c-494d-bf5a-832e43826908")
_BASE_TIME = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
_SNAPSHOT_ID = UUID("8762e980-45e2-4d85-aa4a-4f3864d7991b")
_FETCH_ROUND_ID = UUID("d87b7496-50ab-4a6a-96d4-24b735db3bc4")
_RAW_AUDIT_IDS_BY_SCOPE = {("SSE", "L"): "1001", ("SSE", "D"): "1002"}


def _contract() -> InstrumentReferenceProviderContract:
    """Return the full stock-basic provider contract used by the capture request."""

    return InstrumentReferenceProviderContract(
        contract_id="tushare.stock_basic.reference",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key="tushare.stock_basic.reference",
        api_name="stock_basic",
        fields=(
            "ts_code",
            "name",
            "exchange",
            "market",
            "list_status",
            "list_date",
            "delist_date",
        ),
        exchange_scope=("SSE",),
        list_status_scope=("L", "D"),
    )


def _mapping_record() -> InstrumentReferenceMappingRecord:
    """Build an explicit immutable mapping receipt for the fixture request."""

    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.stock-basic-crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
    )
    content = InstrumentReferenceMappingContent(
        mapping_id="fixture.capture-map",
        mapping_version="fixture-v1",
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
        exchange_source_market_board_pairs=(("SSE", "fixture-market", "FIXTURE_BOARD"),),
    )
    return make_instrument_reference_mapping_record(
        content,
        mapping_record_id=UUID("78f80a1e-95e5-45a9-8274-05c91a12e784"),
        recorded_at=_BASE_TIME,
    )


def _request() -> InstrumentReferenceCaptureRequest:
    """Compose one source-only request with two explicit stock-basic scopes."""

    return InstrumentReferenceCaptureRequest(
        capture_id=_CAPTURE_ID,
        provider_contract=_contract(),
        provider_route_id="tushare.stock_basic",
        provider_route_revision="fixture-route-v1",
        provider_configuration_id=17,
        mapping_record=_mapping_record(),
        actor_provenance="unit-fixture",
    )


class _RawPayloadStore:
    """Retain one payload value for the existing response retention use case."""

    def __init__(self) -> None:
        """Start with no retained payload."""

        self.saved: RawPayload | None = None

    def save(self, payload: RawPayload) -> RawPayload:
        """Store and return the exact immutable payload supplied by the use case."""

        self.saved = payload
        return payload


def _retained_response(
    request: InstrumentReferenceCaptureRequest,
    scope: InstrumentReferenceCaptureScope,
    *,
    redact: bool = False,
) -> InstrumentReferenceCaptureRetainedResponse:
    """Build exact existing provider-response and RawPayload evidence."""

    code = "000001.SH" if scope.list_status == "L" else "000002.SH"
    secret = "fixture-secret-value" if redact else None
    payload: dict[str, object] = {
        "code": 0,
        "data": {
            "fields": list(request.provider_contract.fields),
            "items": [
                [
                    code,
                    secret or "Fixture security",
                    scope.exchange,
                    "fixture-market",
                    scope.list_status,
                    "20200101",
                    None,
                ]
            ],
        },
    }
    body = canonical_provider_response_json(payload).encode("utf-8")
    capture = ProviderResponseCapture(
        body=body,
        payload=payload,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=_BASE_TIME,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    store = _RawPayloadStore()
    reference = RetainProviderResponsePayloadUseCase(store).execute(
        capture,
        provider_name=request.provider_contract.provider_name,
        dataset_key=request.provider_contract.dataset_key,
        api_name=request.provider_contract.api_name,
        request_params={
            "exchange": scope.exchange,
            "list_status": scope.list_status,
            "fields": request.provider_contract.fields_csv,
        },
        sensitive_values=(secret,) if secret is not None else (),
    )
    assert store.saved is not None
    return InstrumentReferenceCaptureRetainedResponse(reference, store.saved)


def _not_captured_progress(
    request: InstrumentReferenceCaptureRequest,
    scope: InstrumentReferenceCaptureScope,
) -> InstrumentReferenceCaptureScopeProgress:
    """Return the exact empty progress value for one scope."""

    return InstrumentReferenceCaptureScopeProgress(
        request=request,
        request_sha256=request.request_sha256,
        provider_contract_hash=request.provider_contract.content_hash,
        scope=scope,
        state=CaptureScopeProgressState.NOT_CAPTURED,
    )


def _build_occurrence(
    request: InstrumentReferenceCaptureRequest,
    scope: InstrumentReferenceCaptureScope,
    retained: InstrumentReferenceCaptureRetainedResponse,
    *,
    row_count: object = 1,
) -> InstrumentReferenceAuditOccurrence:
    """Create the stable, full-contract occurrence before its audit write."""

    return InstrumentReferenceAuditOccurrence(
        occurrence_id=request.occurrence_id(scope),
        run_id=request.identity.run_id,
        ingested_run_id=request.identity.batch_id,
        contract_id=request.provider_contract.contract_id,
        contract_version=request.provider_contract.contract_version,
        contract_hash=request.provider_contract.content_hash,
        api_name=request.provider_contract.api_name,
        dataset_key=request.provider_contract.dataset_key,
        exchange=scope.exchange,
        list_status=scope.list_status,
        fields=request.provider_contract.fields_csv,
        row_count=cast(int, row_count),
        response_reference=retained.reference,
        raw_payload=retained.raw_payload,
    )


def _receipt(
    occurrence: InstrumentReferenceAuditOccurrence,
) -> InstrumentReferenceAuditOccurrenceReceipt:
    """Create a receipt bound to the exact raw payload and request parameters."""

    params_hash = hashlib.sha256(
        canonical_provider_response_json(occurrence.raw_payload.request_params).encode("utf-8")
    ).hexdigest()
    return InstrumentReferenceAuditOccurrenceReceipt(
        occurrence_id=occurrence.occurrence_id,
        raw_audit_reference=RawAuditReference(
            raw_audit_id=_RAW_AUDIT_IDS_BY_SCOPE[(occurrence.exchange, occurrence.list_status)],
            version="fixture-v1",
            content_hash="a" * 64,
            run_id=str(occurrence.run_id),
            ingested_run_id=str(occurrence.ingested_run_id),
        ),
        raw_payload_id=occurrence.response_reference.payload_id,
        raw_payload_hash=occurrence.response_reference.payload_hash,
        response_body_sha256=occurrence.response_reference.body_sha256,
        request_params_hash=params_hash,
        repository_alias="default",
    )


def _audit_complete_progress(
    request: InstrumentReferenceCaptureRequest,
    scope: InstrumentReferenceCaptureScope,
    retained: InstrumentReferenceCaptureRetainedResponse,
    occurrence: InstrumentReferenceAuditOccurrence,
    receipt: InstrumentReferenceAuditOccurrenceReceipt,
) -> InstrumentReferenceCaptureScopeProgress:
    """Build the validated, durable audit-complete progress value."""

    return InstrumentReferenceCaptureScopeProgress(
        request=request,
        request_sha256=request.request_sha256,
        provider_contract_hash=request.provider_contract.content_hash,
        scope=scope,
        state=CaptureScopeProgressState.AUDIT_COMPLETE,
        retained_response=retained,
        occurrence=occurrence,
        receipt=receipt,
    )


def _domain_occurrence(
    progress: InstrumentReferenceCaptureScopeProgress,
) -> InstrumentReferenceOccurrence:
    """Project the fully receipt-bound domain occurrence used by parsed rows."""

    occurrence = progress.occurrence
    receipt = progress.receipt
    retained = progress.retained_response
    assert occurrence is not None and receipt is not None and retained is not None
    return InstrumentReferenceOccurrence(
        occurrence_id=occurrence.occurrence_id,
        exchange=occurrence.exchange,
        list_status=occurrence.list_status,
        raw_audit_reference=receipt.raw_audit_reference,
        raw_payload_id=receipt.raw_payload_id,
        raw_payload_hash=receipt.raw_payload_hash,
        response_body_sha256=receipt.response_body_sha256,
        response_completed_at=retained.reference.response_completed_at,
        row_count=occurrence.row_count,
    )


def _record(
    request: InstrumentReferenceCaptureRequest,
    occurrence: InstrumentReferenceOccurrence,
) -> InstrumentReferenceRecord:
    """Build the one source row represented by the exact retained fixture body."""

    code = "000001.SH" if occurrence.list_status == "L" else "000002.SH"
    return InstrumentReferenceRecord(
        ts_code=code,
        name="Fixture security",
        source_exchange=occurrence.exchange,
        source_market="fixture-market",
        source_list_status=occurrence.list_status,
        list_date_raw="20200101",
        list_date=date(2020, 1, 1),
        delist_date_raw=None,
        delist_date=None,
        exchange_suffix=request.mapping_record.content.source_crosswalk.suffix_for(
            occurrence.exchange
        )
        or "",
        occurrence_id=occurrence.occurrence_id,
        raw_audit_reference=occurrence.raw_audit_reference,
        raw_payload_id=occurrence.raw_payload_id,
        raw_payload_hash=occurrence.raw_payload_hash,
    )


def _source_only_snapshot(
    request: InstrumentReferenceCaptureRequest,
    *,
    ingested_run_id: str | None = None,
) -> InstrumentReferenceSnapshotRecord:
    """Build a completed sealed snapshot for exact-replay tests."""

    occurrences = tuple(
        InstrumentReferenceOccurrence(
            occurrence_id=request.occurrence_id(scope),
            exchange=scope.exchange,
            list_status=scope.list_status,
            raw_audit_reference=RawAuditReference(
                raw_audit_id=_RAW_AUDIT_IDS_BY_SCOPE[(scope.exchange, scope.list_status)],
                version="fixture-v1",
                content_hash="a" * 64,
                run_id=str(request.identity.run_id),
                ingested_run_id=(
                    ingested_run_id
                    if ingested_run_id is not None
                    else str(request.identity.batch_id)
                ),
            ),
            raw_payload_id=f"payload-{scope.exchange}-{scope.list_status}",
            raw_payload_hash="sha256:" + "b" * 64,
            response_body_sha256="c" * 64,
            response_completed_at=_BASE_TIME,
            row_count=0,
        )
        for scope in request.scopes
    )
    candidate = InstrumentReferenceCandidate(
        provider_contract=request.provider_contract,
        crosswalk=request.mapping_record.content.source_crosswalk,
        occurrences=occurrences,
        records=(),
    )
    content = InstrumentReferenceSnapshotContent(
        run_id=request.identity.run_id,
        mapping_record=request.mapping_record,
        fetch_rounds=(InstrumentReferenceFetchRound(_FETCH_ROUND_ID, candidate),),
    )
    return make_instrument_reference_snapshot_record(
        content,
        snapshot_id=_SNAPSHOT_ID,
        recorded_at=_BASE_TIME,
    )


def _lease(request: InstrumentReferenceCaptureRequest) -> InstrumentReferenceCaptureLease:
    """Create a stable test owner capability and first claim epoch."""

    capability = CaptureOwnerCapability(b"capture-usecase-capability-00000")
    epoch = CaptureClaimEpoch.issue(1, request.request_sha256, None, capability)
    return InstrumentReferenceCaptureLease(
        identity=request.identity,
        request_sha256=request.request_sha256,
        epoch=epoch,
        owner_capability=capability,
    )


class _ClaimPort:
    """Return one predetermined typed claim result and record its invocation."""

    def __init__(self, result: InstrumentReferenceCaptureClaimResult) -> None:
        """Store the typed claim result used by this test."""

        self.result = result
        self.calls: list[InstrumentReferenceCaptureInvocation] = []

    def claim(
        self,
        invocation: InstrumentReferenceCaptureInvocation,
    ) -> InstrumentReferenceCaptureClaimResult:
        """Return the prepared claim without a database dependency."""

        self.calls.append(invocation)
        return self.result


class _ProviderPort:
    """Return captured fixture bodies or fail if a retry must not perform HTTP."""

    def __init__(
        self,
        responses: dict[
            InstrumentReferenceCaptureScope,
            InstrumentReferenceCaptureRetainedResponse,
        ],
        *,
        forbidden: bool = False,
        failure: Exception | None = None,
    ) -> None:
        """Keep fixture responses and an optional no-network/failure boundary."""

        self.responses = responses
        self.forbidden = forbidden
        self.failure = failure
        self.calls: list[InstrumentReferenceCaptureScope] = []

    def fetch_scope(
        self,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> ProviderResponseCapture:
        """Return one exact capture and never make a network request."""

        self.calls.append(scope)
        if self.forbidden:
            raise AssertionError("retained progress must not issue a provider request")
        if self.failure is not None:
            raise self.failure
        return self.responses[scope].to_provider_response_capture()


class _PersistencePort:
    """Record fenced protocol calls and serve exact in-memory progress values."""

    def __init__(
        self,
        request: InstrumentReferenceCaptureRequest,
        responses: dict[
            InstrumentReferenceCaptureScope,
            InstrumentReferenceCaptureRetainedResponse,
        ],
        *,
        initial_state: CaptureScopeProgressState = CaptureScopeProgressState.NOT_CAPTURED,
    ) -> None:
        """Seed one immutable response state per request scope."""

        self.request = request
        self.responses = responses
        self.progress: dict[
            InstrumentReferenceCaptureScope,
            InstrumentReferenceCaptureScopeProgress,
        ] = {}
        for scope in request.scopes:
            if initial_state is CaptureScopeProgressState.NOT_CAPTURED:
                self.progress[scope] = _not_captured_progress(request, scope)
            elif initial_state is CaptureScopeProgressState.RESPONSE_RETAINED:
                retained = responses[scope]
                self.progress[scope] = InstrumentReferenceCaptureScopeProgress(
                    request=request,
                    request_sha256=request.request_sha256,
                    provider_contract_hash=request.provider_contract.content_hash,
                    scope=scope,
                    state=initial_state,
                    retained_response=retained,
                )
            else:
                raise AssertionError("unsupported fixture initial state")
        self.events: list[tuple[str, InstrumentReferenceCaptureScope | UUID | None]] = []
        self.audit_writes = 0
        self.snapshot_writes = 0
        self.snapshot: InstrumentReferenceSnapshotRecord | None = None

    def read_scope_progress(
        self,
        lease: InstrumentReferenceCaptureLease,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> InstrumentReferenceCaptureScopeProgress:
        """Read one exact in-memory scope state after checking lease identity."""

        assert lease.identity == request.identity
        assert lease.request_sha256 == request.request_sha256
        self.events.append(("read", scope))
        return self.progress[scope]

    def retain_response(
        self,
        lease: InstrumentReferenceCaptureLease,
        scope: InstrumentReferenceCaptureScope,
        response: ProviderResponseCapture,
    ) -> ProviderResponsePayloadReference:
        """Record a response pointer and make the exact retained body readable."""

        self.events.append(("retain", scope))
        retained = self.responses[scope]
        assert response == retained.to_provider_response_capture()
        self.progress[scope] = InstrumentReferenceCaptureScopeProgress(
            request=self.request,
            request_sha256=self.request.request_sha256,
            provider_contract_hash=self.request.provider_contract.content_hash,
            scope=scope,
            state=CaptureScopeProgressState.RESPONSE_RETAINED,
            retained_response=retained,
        )
        return retained.reference

    def record_occurrence(
        self,
        lease: InstrumentReferenceCaptureLease,
        occurrence: InstrumentReferenceAuditOccurrence,
    ) -> InstrumentReferenceAuditOccurrenceReceipt:
        """Record one exact test receipt through the fenced persistence port."""

        scope = InstrumentReferenceCaptureScope(occurrence.exchange, occurrence.list_status)
        self.events.append(("audit", scope))
        self.audit_writes += 1
        retained = self.responses[scope]
        receipt = _receipt(occurrence)
        self.progress[scope] = _audit_complete_progress(
            self.request,
            scope,
            retained,
            occurrence,
            receipt,
        )
        return receipt

    def complete_snapshot(
        self,
        lease: InstrumentReferenceCaptureLease,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        """Append one sealed fixture snapshot through the persistence boundary."""

        self.events.append(("complete", None))
        self.snapshot_writes += 1
        self.snapshot = make_instrument_reference_snapshot_record(
            content,
            snapshot_id=_SNAPSHOT_ID,
            recorded_at=_BASE_TIME,
        )
        return self.snapshot

    def get_snapshot(self, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        """Read back only the exact supplied test snapshot ID."""

        self.events.append(("get_snapshot", snapshot_id))
        if self.snapshot is None or self.snapshot.snapshot_id != snapshot_id:
            return None
        return self.snapshot


class _ParserPort:
    """Build auditable occurrence fixtures and parse only audited progress."""

    def __init__(
        self,
        responses: dict[
            InstrumentReferenceCaptureScope,
            InstrumentReferenceCaptureRetainedResponse,
        ],
        *,
        mutation: str | None = None,
    ) -> None:
        """Store response fixtures and an optional hostile occurrence mutation."""

        self.responses = responses
        self.mutation = mutation
        self.events: list[tuple[str, InstrumentReferenceCaptureScope]] = []

    def build_audit_occurrence(
        self,
        request: InstrumentReferenceCaptureRequest,
        progress: InstrumentReferenceCaptureScopeProgress,
    ) -> InstrumentReferenceAuditOccurrence:
        """Require original retained bytes and build one stable occurrence."""

        scope = progress.scope
        self.events.append(("build", scope))
        progress.to_provider_response_capture()
        retained = self.responses[scope]
        occurrence = _build_occurrence(request, scope, retained)
        if self.mutation == "scope":
            return replace(occurrence, exchange="SZSE")
        if self.mutation == "id":
            return replace(occurrence, occurrence_id=UUID("4e524b82-e19b-4138-b245-ae5bdfe5e4f5"))
        if self.mutation == "contract":
            return replace(occurrence, contract_hash="f" * 64)
        if self.mutation == "raw":
            other_scope = request.scopes[1]
            return replace(occurrence, raw_payload=self.responses[other_scope].raw_payload)
        if self.mutation == "bool-count":
            return replace(occurrence, row_count=True)
        if self.mutation == "negative-count":
            return replace(occurrence, row_count=-1)
        if self.mutation == "positive-wrong-count":
            return replace(occurrence, row_count=2)
        return occurrence

    def parse_scope(
        self,
        request: InstrumentReferenceCaptureRequest,
        progress: InstrumentReferenceCaptureScopeProgress,
    ) -> InstrumentReferenceCaptureParsedScope:
        """Return a record bound to the exact occurrence and audit receipt."""

        scope = progress.scope
        self.events.append(("parse", scope))
        if self.mutation == "positive-wrong-count":
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PARSED_SCOPE_INVALID"
            )
        occurrence = _domain_occurrence(progress)
        return InstrumentReferenceCaptureParsedScope(
            scope=scope,
            occurrence=occurrence,
            records=(_record(request, occurrence),),
        )


class _AssemblerPort:
    """Assemble the complete ordered scope set into one full-contract round."""

    def __init__(self) -> None:
        """Start without assembly calls."""

        self.calls = 0

    def assemble_snapshot_content(
        self,
        request: InstrumentReferenceCaptureRequest,
        parsed_scopes: tuple[InstrumentReferenceCaptureParsedScope, ...],
    ) -> InstrumentReferenceSnapshotContent:
        """Create the existing snapshot DTO without persistence or clock access."""

        self.calls += 1
        candidate = InstrumentReferenceCandidate(
            provider_contract=request.provider_contract,
            crosswalk=request.mapping_record.content.source_crosswalk,
            occurrences=tuple(item.occurrence for item in parsed_scopes),
            records=tuple(record for item in parsed_scopes for record in item.records),
        )
        return InstrumentReferenceSnapshotContent(
            run_id=request.identity.run_id,
            mapping_record=request.mapping_record,
            fetch_rounds=(InstrumentReferenceFetchRound(_FETCH_ROUND_ID, candidate),),
        )


def _harness(
    *,
    request: InstrumentReferenceCaptureRequest | None = None,
    disposition: CaptureClaimDisposition = CaptureClaimDisposition.ACQUIRED,
    initial_state: CaptureScopeProgressState = CaptureScopeProgressState.NOT_CAPTURED,
    mutation: str | None = None,
    provider_forbidden: bool = False,
    provider_failure: Exception | None = None,
) -> tuple[
    CaptureInstrumentReferenceSnapshotUseCase,
    _ClaimPort,
    _ProviderPort,
    _PersistencePort,
    _ParserPort,
    _AssemblerPort,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceCaptureInvocation,
]:
    """Wire in-memory typed ports while keeping the unit tests off Django/HTTP."""

    selected_request = request or _request()
    responses = {
        scope: _retained_response(selected_request, scope) for scope in selected_request.scopes
    }
    lease = _lease(selected_request)
    claim_result = InstrumentReferenceCaptureClaimResult(
        disposition=disposition,
        identity=selected_request.identity,
        request_sha256=selected_request.request_sha256,
        lease=lease if disposition is CaptureClaimDisposition.ACQUIRED else None,
        snapshot=(
            _source_only_snapshot(selected_request)
            if disposition is CaptureClaimDisposition.COMPLETED
            else None
        ),
    )
    claim = _ClaimPort(claim_result)
    provider = _ProviderPort(
        responses,
        forbidden=provider_forbidden,
        failure=provider_failure,
    )
    persistence = _PersistencePort(selected_request, responses, initial_state=initial_state)
    parser = _ParserPort(responses, mutation=mutation)
    assembler = _AssemblerPort()
    invocation = InstrumentReferenceCaptureInvocation(
        selected_request,
        CaptureInvocationMode.RESUME,
    )
    use_case = CaptureInstrumentReferenceSnapshotUseCase(
        claim,
        provider,
        persistence,
        parser,
        assembler,
    )
    return use_case, claim, provider, persistence, parser, assembler, selected_request, invocation


def test_capture_claims_fetches_retains_audits_then_parses_and_completes_all_scopes() -> None:
    use_case, claim, provider, persistence, parser, assembler, request, invocation = _harness()

    result = use_case.execute(invocation)

    assert result.status is CaptureExecutionStatus.COMPLETED
    assert result.snapshot is persistence.snapshot
    assert result.snapshot is not None
    assert (
        result.snapshot.content.fetch_rounds[0].candidate.provider_contract.content_hash
        == request.provider_contract.content_hash
    )
    assert result.snapshot.content.source_observed_at is None
    assert result.snapshot.content.source_available_at is None
    assert result.snapshot.content.must_not_use_for_decision is True
    assert result.snapshot.content.must_not_execute is True
    assert provider.calls == list(request.scopes)
    assert persistence.audit_writes == len(request.scopes)
    assert persistence.snapshot_writes == 1
    assert parser.events == [
        (stage, scope) for scope in request.scopes for stage in ("build", "parse")
    ]
    assert [event[0] for event in persistence.events] == [
        "read",
        "retain",
        "read",
        "audit",
        "read",
        "read",
        "retain",
        "read",
        "audit",
        "read",
        "complete",
    ]
    assert claim.calls == [invocation]
    assert assembler.calls == 1


@pytest.mark.parametrize(
    ("disposition", "expected"),
    (
        (CaptureClaimDisposition.IN_PROGRESS, CaptureExecutionStatus.IN_PROGRESS),
        (CaptureClaimDisposition.RESUME_REQUIRED, CaptureExecutionStatus.RESUME_REQUIRED),
    ),
)
def test_pending_claim_dispositions_return_without_scope_io(
    disposition: CaptureClaimDisposition,
    expected: CaptureExecutionStatus,
) -> None:
    use_case, _claim, provider, persistence, _parser, _assembler, _request_value, invocation = (
        _harness(disposition=disposition)
    )

    result = use_case.execute(invocation)

    assert result.status is expected
    assert result.snapshot is None
    assert provider.calls == []
    assert persistence.events == []


def test_completed_claim_rereads_exact_snapshot_without_provider_or_scope_reads() -> None:
    use_case, _claim, provider, persistence, _parser, _assembler, request, invocation = _harness(
        disposition=CaptureClaimDisposition.COMPLETED,
        provider_forbidden=True,
    )
    expected = _source_only_snapshot(request)
    persistence.snapshot = expected

    result = use_case.execute(invocation)

    assert result.status is CaptureExecutionStatus.COMPLETED
    assert result.snapshot == expected
    assert persistence.events == [("get_snapshot", expected.snapshot_id)]
    assert provider.calls == []


def test_completed_claim_rejects_exact_snapshot_with_wrong_ingested_run_id_before_io() -> None:
    use_case, claim, provider, persistence, parser, assembler, request, invocation = _harness(
        disposition=CaptureClaimDisposition.COMPLETED,
        provider_forbidden=True,
    )
    wrong_ingested_run_id = str(UUID(int=(request.identity.batch_id.int + 1) % (1 << 128)))
    expected = _source_only_snapshot(request, ingested_run_id=wrong_ingested_run_id)
    assert expected.content.run_id == request.identity.run_id
    assert all(
        occurrence.raw_audit_reference.run_id == str(request.identity.run_id)
        and occurrence.raw_audit_reference.ingested_run_id == wrong_ingested_run_id
        for fetch_round in expected.content.fetch_rounds
        for occurrence in fetch_round.candidate.occurrences
    )
    claim.result = replace(claim.result, snapshot=expected)
    persistence.snapshot = expected

    result = use_case.execute(invocation)

    assert result.status is CaptureExecutionStatus.BLOCKED
    assert result.reason_code == "INSTRUMENT_REFERENCE_CAPTURE_COMPLETED_POINTER_INVALID"
    assert result.snapshot is None
    assert claim.calls == [invocation]
    assert provider.calls == []
    assert persistence.events == []
    assert persistence.audit_writes == 0
    assert persistence.snapshot_writes == 0
    assert parser.events == []
    assert assembler.calls == 0


def test_retained_response_resume_reuses_exact_body_and_does_not_refetch() -> None:
    use_case, _claim, provider, persistence, _parser, _assembler, request, invocation = _harness(
        initial_state=CaptureScopeProgressState.RESPONSE_RETAINED,
        provider_forbidden=True,
    )

    result = use_case.execute(invocation)

    assert result.status is CaptureExecutionStatus.COMPLETED
    assert result.snapshot is not None
    assert provider.calls == []
    assert persistence.audit_writes == len(request.scopes)
    assert persistence.snapshot_writes == 1


@pytest.mark.parametrize(
    "mutation",
    ("scope", "id", "contract", "raw", "bool-count", "negative-count"),
)
def test_invalid_pre_audit_occurrence_is_blocked_before_audit_or_snapshot(
    mutation: str,
) -> None:
    use_case, _claim, provider, persistence, _parser, _assembler, request, invocation = _harness(
        initial_state=CaptureScopeProgressState.RESPONSE_RETAINED,
        mutation=mutation,
        provider_forbidden=True,
    )

    result = use_case.execute(invocation)

    assert result.status is CaptureExecutionStatus.BLOCKED
    assert result.reason_code == "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID"
    assert provider.calls == []
    assert persistence.audit_writes == 0
    assert persistence.snapshot_writes == 0
    assert request.request_sha256 == result.request_sha256


def test_redacted_retained_body_fails_before_audit_and_snapshot() -> None:
    request = _request()
    responses = {
        scope: _retained_response(request, scope, redact=scope == request.scopes[0])
        for scope in request.scopes
    }
    assert responses[request.scopes[0]].reference.original_body_retained is False
    (
        use_case,
        _claim,
        _provider,
        persistence,
        parser,
        _assembler,
        _request_value,
        invocation,
    ) = _harness(
        request=request,
        initial_state=CaptureScopeProgressState.RESPONSE_RETAINED,
        provider_forbidden=True,
    )
    for scope in request.scopes:
        retained = responses[scope]
        persistence.progress[scope] = InstrumentReferenceCaptureScopeProgress(
            request=request,
            request_sha256=request.request_sha256,
            provider_contract_hash=request.provider_contract.content_hash,
            scope=scope,
            state=CaptureScopeProgressState.RESPONSE_RETAINED,
            retained_response=retained,
        )
    parser.responses = responses

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        use_case.execute(invocation)

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_ORIGINAL_RESPONSE_UNAVAILABLE"
    assert persistence.audit_writes == 0
    assert persistence.snapshot_writes == 0


def test_wrong_positive_parser_row_count_never_writes_a_snapshot() -> None:
    (
        use_case,
        _claim,
        provider,
        persistence,
        _parser,
        _assembler,
        _request_value,
        invocation,
    ) = _harness(
        initial_state=CaptureScopeProgressState.RESPONSE_RETAINED,
        mutation="positive-wrong-count",
        provider_forbidden=True,
    )

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        use_case.execute(invocation)

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_PARSED_SCOPE_INVALID"
    assert provider.calls == []
    assert persistence.audit_writes == 1
    assert persistence.snapshot_writes == 0


def test_unknown_provider_failure_does_not_become_a_completed_capture() -> None:
    use_case, _claim, provider, persistence, _parser, _assembler, request, invocation = _harness(
        provider_failure=RuntimeError("fixture transport failure")
    )

    with pytest.raises(RuntimeError, match="fixture transport failure"):
        use_case.execute(invocation)

    assert provider.calls == [request.scopes[0]]
    assert persistence.audit_writes == 0
    assert persistence.snapshot_writes == 0
