"""Pure request identity and fencing tests for source-reference capture."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
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
    InstrumentReferenceCaptureResult,
    InstrumentReferenceCaptureRetainedResponse,
    InstrumentReferenceCaptureScopeProgress,
)
from apps.data_center.application.instrument_reference_source import (
    InstrumentReferenceAuditOccurrence,
    InstrumentReferenceAuditOccurrenceReceipt,
)
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_capture import (
    CaptureClaimEpoch,
    CaptureClaimHistory,
    CaptureClaimMarker,
    CaptureClaimPayload,
    CaptureOwnerCapability,
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureIdentity,
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

_CAPTURE_ID = UUID("9f83a81d-5d16-4e6c-a11d-52aa23ad2b95")
_BASE_TIME = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def _crosswalk(exchanges: tuple[str, ...] = ("SSE",)) -> InstrumentReferenceExchangeSuffixCrosswalk:
    """Build the explicit source suffix mapping used by one request fixture."""

    suffixes = {"SSE": "SH", "SZSE": "SZ"}
    return InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.stock-basic-crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=tuple((exchange, suffixes[exchange]) for exchange in exchanges),
    )


def _contract(
    exchanges: tuple[str, ...] = ("SSE",),
    statuses: tuple[str, ...] = ("L", "D"),
) -> InstrumentReferenceProviderContract:
    """Create a complete stock-basic contract with an explicit ordered scope."""

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
        exchange_scope=exchanges,
        list_status_scope=statuses,
    )


def _mapping_record(
    exchanges: tuple[str, ...] = ("SSE",),
    mapping_record_id: UUID = UUID("3ac6010a-a132-4d80-a626-cc07fc3715c4"),
) -> InstrumentReferenceMappingRecord:
    """Create an existing immutable mapping receipt for capture identity tests."""

    crosswalk = _crosswalk(exchanges)
    content = InstrumentReferenceMappingContent(
        mapping_id="fixture.capture-map",
        mapping_version="fixture-v1",
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=tuple(
            (exchange, f"FIXTURE_{exchange}") for exchange in exchanges
        ),
        exchange_source_market_board_pairs=tuple(
            (exchange, "fixture-market", "FIXTURE_BOARD") for exchange in exchanges
        ),
    )
    return make_instrument_reference_mapping_record(
        content,
        mapping_record_id=mapping_record_id,
        recorded_at=_BASE_TIME,
    )


def _request(
    *,
    contract: InstrumentReferenceProviderContract | None = None,
    mapping: InstrumentReferenceMappingRecord | None = None,
    route_revision: str = "route-v1",
    provider_configuration_id: int = 17,
    actor_provenance: str | None = "operator-fixture-1",
) -> InstrumentReferenceCaptureRequest:
    """Compose a typed source-only request from pre-existing Domain contracts."""

    selected_contract = contract or _contract()
    selected_mapping = mapping or _mapping_record(selected_contract.exchange_scope)
    return InstrumentReferenceCaptureRequest(
        capture_id=_CAPTURE_ID,
        provider_contract=selected_contract,
        provider_route_id="tushare.stock_basic",
        provider_route_revision=route_revision,
        provider_configuration_id=provider_configuration_id,
        mapping_record=selected_mapping,
        actor_provenance=actor_provenance,
    )


def _issued_history() -> tuple[str, CaptureClaimEpoch, CaptureClaimEpoch]:
    """Build two consecutive safe claim payloads for validation tests."""

    request_sha256 = "a" * 64
    first = CaptureClaimEpoch.issue(
        1,
        request_sha256,
        None,
        CaptureOwnerCapability(b"first-owner-capability-00000000".ljust(32, b"0")),
    )
    second = CaptureClaimEpoch.issue(
        2,
        request_sha256,
        first.claim_sha256,
        CaptureOwnerCapability(b"second-owner-capability-000000".ljust(32, b"0")),
    )
    return request_sha256, first, second


def _marker_rows(*epochs: int) -> tuple[tuple[object, object], ...]:
    """Return exact marker checkpoint pairs for the requested epochs."""

    return tuple((CaptureClaimMarker.for_epoch(epoch).cursor_name, "v1") for epoch in epochs)


def _payload_rows(*claims: CaptureClaimEpoch) -> tuple[tuple[object, object], ...]:
    """Return exact reserved payload checkpoint pairs for claim values."""

    return tuple(
        (payload.cursor_name, payload.cursor_value)
        for payload in (CaptureClaimPayload.for_claim(claim) for claim in claims)
    )


def _assert_capture_error(code: str, callback: Callable[[], object]) -> None:
    """Assert one stable capture-contract error without matching its prose."""

    assert callable(callback)
    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        callback()
    assert caught.value.code == code


class _InMemoryRawPayloadStore:
    """Small pure-test adapter for the existing RawPayload retention port."""

    def __init__(self) -> None:
        """Start without a retained payload."""

        self.saved: RawPayload | None = None

    def save(self, payload: RawPayload) -> RawPayload:
        """Retain and return the exact value supplied by the use case."""

        self.saved = payload
        return payload


def _retained_response(
    request: InstrumentReferenceCaptureRequest,
    scope: InstrumentReferenceCaptureScope,
    *,
    secret_value: str | None = None,
) -> InstrumentReferenceCaptureRetainedResponse:
    """Use the existing response-retention contract to build exact test evidence."""

    contract = request.provider_contract
    suffix = "SH" if scope.exchange == "SSE" else "SZ"
    row: list[object] = [
        f"000001.{suffix}",
        secret_value or "Fixture security",
        scope.exchange,
        "",
        scope.list_status,
        "20200101",
        None,
    ]
    response_payload: dict[str, object] = {
        "code": 0,
        "data": {"fields": list(contract.fields), "items": [row]},
    }
    body = canonical_provider_response_json(response_payload).encode("utf-8")
    capture = ProviderResponseCapture(
        body=body,
        payload=response_payload,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=_BASE_TIME,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    store = _InMemoryRawPayloadStore()
    reference = RetainProviderResponsePayloadUseCase(store).execute(
        capture,
        provider_name=contract.provider_name,
        dataset_key=contract.dataset_key,
        api_name=contract.api_name,
        request_params={
            "exchange": scope.exchange,
            "list_status": scope.list_status,
            "fields": contract.fields_csv,
        },
        sensitive_values=(secret_value,) if secret_value is not None else (),
    )
    assert store.saved is not None
    return InstrumentReferenceCaptureRetainedResponse(reference, store.saved)


def _audited_progress(
    request: InstrumentReferenceCaptureRequest,
    scope: InstrumentReferenceCaptureScope,
    retained: InstrumentReferenceCaptureRetainedResponse,
) -> InstrumentReferenceCaptureScopeProgress:
    """Build the exact existing occurrence and receipt contracts for one scope."""

    ingested_run_id = request.identity.batch_id
    contract = request.provider_contract
    occurrence = InstrumentReferenceAuditOccurrence(
        occurrence_id=request.occurrence_id(scope),
        run_id=request.identity.run_id,
        ingested_run_id=ingested_run_id,
        contract_id=contract.contract_id,
        contract_version=contract.contract_version,
        contract_hash=contract.content_hash,
        api_name=contract.api_name,
        dataset_key=contract.dataset_key,
        exchange=scope.exchange,
        list_status=scope.list_status,
        fields=contract.fields_csv,
        row_count=1,
        response_reference=retained.reference,
        raw_payload=retained.raw_payload,
    )
    request_params_hash = hashlib.sha256(
        canonical_provider_response_json(retained.raw_payload.request_params).encode("utf-8")
    ).hexdigest()
    receipt = InstrumentReferenceAuditOccurrenceReceipt(
        occurrence_id=occurrence.occurrence_id,
        raw_audit_reference=RawAuditReference(
            raw_audit_id="fixture-raw-audit-id",
            version="fixture-v1",
            content_hash="a" * 64,
            run_id=str(occurrence.run_id),
            ingested_run_id=str(occurrence.ingested_run_id),
        ),
        raw_payload_id=retained.reference.payload_id,
        raw_payload_hash=retained.reference.payload_hash,
        response_body_sha256=retained.reference.body_sha256,
        request_params_hash=request_params_hash,
        repository_alias="default",
    )
    return InstrumentReferenceCaptureScopeProgress(
        request=request,
        request_sha256=request.request_sha256,
        provider_contract_hash=contract.content_hash,
        scope=scope,
        state=CaptureScopeProgressState.AUDIT_COMPLETE,
        retained_response=retained,
        occurrence=occurrence,
        receipt=receipt,
    )


def test_capture_identity_and_scope_occurrence_ids_have_stable_goldens() -> None:
    identity = InstrumentReferenceCaptureIdentity.for_capture(_CAPTURE_ID)
    scope = InstrumentReferenceCaptureScope("SSE", "L")

    assert str(identity.run_id) == "9f83a81d-5d16-4e6c-a11d-52aa23ad2b95"
    assert str(identity.batch_id) == "f46f0f4e-304f-5170-94eb-ae95ff55846d"
    assert identity.idempotency_key == (
        "instrument-reference-capture.v1:9f83a81d-5d16-4e6c-a11d-52aa23ad2b95"
    )
    assert str(identity.occurrence_id(scope)) == "0b7b9fc8-a2a3-5c32-bf5b-661fc9a07aee"
    assert identity.occurrence_id(scope) == identity.occurrence_id(scope)


def test_request_digest_binds_contract_route_mapping_and_asserted_provenance() -> None:
    request = _request()
    changed_route = _request(route_revision="route-v2")
    changed_configuration = _request(provider_configuration_id=18)
    changed_mapping = _request(
        mapping=_mapping_record(mapping_record_id=UUID("2b33d808-a9d8-4e40-b3d9-813d54c24ef8"))
    )
    changed_scope_order = _request(contract=_contract(statuses=("D", "L")))
    changed_actor = _request(actor_provenance="operator-fixture-2")

    assert len(request.request_sha256) == 64
    assert (
        len(
            {
                request.request_sha256,
                changed_route.request_sha256,
                changed_configuration.request_sha256,
                changed_mapping.request_sha256,
                changed_scope_order.request_sha256,
                changed_actor.request_sha256,
            }
        )
        == 6
    )
    assert request.identity == changed_route.identity
    assert request.request_sha256 != changed_route.request_sha256
    assert request.request_sha256 != changed_configuration.request_sha256
    assert request.request_payload["provider_configuration_id"] == 17
    assert request.request_payload["source_only"] is True
    assert "resume" not in request.request_payload
    assert "credential" not in request.request_payload
    assert tuple((scope.exchange, scope.list_status) for scope in request.scopes) == (
        ("SSE", "L"),
        ("SSE", "D"),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_OUTSIDE_REQUEST",
        lambda: request.occurrence_id(InstrumentReferenceCaptureScope("SZSE", "L")),
    )


def test_request_rejects_non_source_only_alias_and_unmapped_exchange() -> None:
    request = _request()

    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SOURCE_ONLY_REQUIRED",
        lambda: replace(request, source_only=False),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_ALIAS_INVALID",
        lambda: replace(request, repository_alias="replica"),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_MAPPING_SCOPE_MISMATCH",
        lambda: InstrumentReferenceCaptureRequest(
            capture_id=_CAPTURE_ID,
            provider_contract=_contract(exchanges=("SSE", "SZSE")),
            provider_route_id="tushare.stock_basic",
            provider_route_revision="route-v1",
            provider_configuration_id=17,
            mapping_record=_mapping_record(("SSE",)),
        ),
    )


def test_request_requires_a_strict_positive_provider_configuration_id() -> None:
    request = _request()
    for invalid_id in (True, 0, -1, None):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_PROVIDER_CONFIGURATION_INVALID",
            lambda invalid_id=invalid_id: replace(request, provider_configuration_id=invalid_id),
        )


def test_resume_mode_does_not_change_immutable_request_digest() -> None:
    request = _request()
    normal = InstrumentReferenceCaptureInvocation(request, CaptureInvocationMode.NORMAL)
    resume = InstrumentReferenceCaptureInvocation(request, CaptureInvocationMode.RESUME)

    assert normal.request_sha256 == resume.request_sha256 == request.request_sha256


def test_scope_progress_distinguishes_absent_response_and_complete_audit() -> None:
    request = _request()
    scope = request.scopes[0]
    missing = InstrumentReferenceCaptureScopeProgress(
        request=request,
        request_sha256=request.request_sha256,
        provider_contract_hash=request.provider_contract.content_hash,
        scope=scope,
        state=CaptureScopeProgressState.NOT_CAPTURED,
    )
    retained = _retained_response(request, scope)
    response_only = InstrumentReferenceCaptureScopeProgress(
        request=request,
        request_sha256=request.request_sha256,
        provider_contract_hash=request.provider_contract.content_hash,
        scope=scope,
        state=CaptureScopeProgressState.RESPONSE_RETAINED,
        retained_response=retained,
    )
    audited = _audited_progress(request, scope, retained)

    assert missing.state is CaptureScopeProgressState.NOT_CAPTURED
    assert response_only.state is CaptureScopeProgressState.RESPONSE_RETAINED
    assert audited.state is CaptureScopeProgressState.AUDIT_COMPLETE
    reconstructed = audited.to_provider_response_capture()
    assert reconstructed.body == retained.raw_payload.payload["retained_response_json"].encode(
        "utf-8"
    )
    assert reconstructed.body_sha256 == retained.reference.body_sha256
    assert audited.provider_contract_hash == request.provider_contract.content_hash


def test_scope_progress_rejects_wrong_request_scope_contract_and_audit_receipt() -> None:
    request = _request()
    scope = request.scopes[0]
    retained = _retained_response(request, scope)
    progress = _audited_progress(request, scope, retained)

    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID",
        lambda: replace(progress, request_sha256="0" * 64),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID",
        lambda: replace(progress, provider_contract_hash="0" * 64),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID",
        lambda: replace(
            progress,
            scope=InstrumentReferenceCaptureScope("SZSE", scope.list_status),
        ),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID",
        lambda: replace(progress, request=_request(provider_configuration_id=18)),
    )
    assert progress.receipt is not None
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID",
        lambda: replace(
            progress,
            receipt=replace(progress.receipt, response_body_sha256="0" * 64),
        ),
    )
    assert progress.occurrence is not None
    wrong_ingested_run_id = UUID("e9486591-5c61-4cb6-8c9e-baa98f7008ac")
    wrong_occurrence = replace(
        progress.occurrence,
        ingested_run_id=wrong_ingested_run_id,
    )
    assert progress.receipt is not None
    wrong_audit_reference = replace(
        progress.receipt.raw_audit_reference,
        ingested_run_id=str(wrong_ingested_run_id),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID",
        lambda: replace(
            progress,
            occurrence=wrong_occurrence,
            receipt=replace(progress.receipt, raw_audit_reference=wrong_audit_reference),
        ),
    )

    wrong_scope = _retained_response(
        request,
        InstrumentReferenceCaptureScope("SZSE", scope.list_status),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID",
        lambda: InstrumentReferenceCaptureScopeProgress(
            request=request,
            request_sha256=request.request_sha256,
            provider_contract_hash=request.provider_contract.content_hash,
            scope=scope,
            state=CaptureScopeProgressState.RESPONSE_RETAINED,
            retained_response=wrong_scope,
        ),
    )


def test_retained_response_refuses_to_reconstruct_redacted_original_bytes() -> None:
    request = _request()
    scope = request.scopes[0]
    retained = _retained_response(
        request,
        scope,
        secret_value="fixture-sensitive-name",
    )

    assert retained.reference.original_body_retained is False
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_ORIGINAL_RESPONSE_UNAVAILABLE",
        retained.to_provider_response_capture,
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID",
        lambda: _audited_progress(request, scope, retained),
    )


def test_retained_response_rechecks_mutable_raw_payload_before_replay() -> None:
    request = _request()
    retained = _retained_response(request, request.scopes[0])
    retained.raw_payload.payload["api_name"] = "different-api"

    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_RETAINED_RESPONSE_INVALID",
        retained.to_provider_response_capture,
    )


def test_owner_capability_is_opaque_and_claim_checkpoint_is_bounded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    raw_token = b"owner-capability-marker-12345678"
    capability = CaptureOwnerCapability(raw_token)
    request = _request()
    claim = CaptureClaimEpoch.issue(1, request.request_sha256, None, capability)
    lease = InstrumentReferenceCaptureLease(
        identity=request.identity,
        request_sha256=request.request_sha256,
        epoch=claim,
        owner_capability=capability,
    )
    serialized = claim.to_checkpoint_value()

    assert len(raw_token) == 32
    assert len(CaptureOwnerCapability.generate().token_sha256) == 64
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CAPABILITY_INVALID",
        lambda: CaptureOwnerCapability(b"too-short"),
    )
    assert capability.matches_digest(claim.owner_token_sha256)
    assert len(serialized.encode("ascii")) <= 500
    assert raw_token.decode("ascii") not in repr(capability)
    assert raw_token.decode("ascii") not in repr(lease)
    assert raw_token.decode("ascii") not in serialized
    assert raw_token.decode("ascii") not in request.canonical_request
    assert raw_token.decode("ascii") not in caplog.text
    assert CaptureClaimEpoch.from_checkpoint_value(serialized) == claim


def test_linear_claim_history_validates_marker_payload_pairs_and_resume_chain() -> None:
    request_sha256, first, second = _issued_history()
    history = CaptureClaimHistory.from_checkpoint_rows(
        request_sha256,
        _marker_rows(2, 1),
        _payload_rows(second, first),
    )

    assert history.next_epoch == 3
    assert history.latest == second
    assert [claim.epoch for claim in history.epochs] == [2, 1]


def test_claim_history_rejects_marker_count_and_duplicate_epoch_mismatches() -> None:
    request_sha256, first, second = _issued_history()
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_MARKER_PAYLOAD_MISMATCH",
        lambda: CaptureClaimHistory.from_checkpoint_rows(
            request_sha256,
            _marker_rows(1, 2),
            _payload_rows(first),
        ),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_DUPLICATE_EPOCH",
        lambda: CaptureClaimHistory.from_checkpoint_rows(
            request_sha256,
            _marker_rows(1, 1),
            _payload_rows(first, first),
        ),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_DUPLICATE_EPOCH",
        lambda: CaptureClaimHistory.from_checkpoint_rows(
            request_sha256,
            _marker_rows(1, 2),
            _payload_rows(first, first),
        ),
    )
    assert second.epoch == 2


def test_claim_history_rejects_gaps_forks_and_wrong_request_binding() -> None:
    request_sha256, first, _second = _issued_history()
    gap = CaptureClaimEpoch.issue(
        3,
        request_sha256,
        first.claim_sha256,
        CaptureOwnerCapability(b"third-owner-capability-0000000".ljust(32, b"0")),
    )
    fork = CaptureClaimEpoch.issue(
        2,
        request_sha256,
        "f" * 64,
        CaptureOwnerCapability(b"forked-owner-capability-000000".ljust(32, b"0")),
    )
    wrong_request = CaptureClaimEpoch.issue(
        1,
        "b" * 64,
        None,
        CaptureOwnerCapability(b"wrong-request-capability-000000".ljust(32, b"0")),
    )

    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_EPOCH_GAP",
        lambda: CaptureClaimHistory.from_checkpoint_rows(
            request_sha256,
            _marker_rows(1, 3),
            _payload_rows(first, gap),
        ),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_CHAIN_INVALID",
        lambda: CaptureClaimHistory.from_checkpoint_rows(
            request_sha256,
            _marker_rows(1, 2),
            _payload_rows(first, fork),
        ),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_DIGEST_MISMATCH",
        lambda: CaptureClaimHistory.from_checkpoint_rows(
            request_sha256,
            _marker_rows(1),
            _payload_rows(wrong_request),
        ),
    )


def test_claim_decoder_rejects_tampering_unknown_keys_duplicate_keys_and_bool_epoch() -> None:
    request_sha256, first, _second = _issued_history()
    payload = first.to_payload()
    payload["owner_token_sha256"] = "c" * 64
    tampered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    unknown = dict(first.to_payload())
    unknown["extra"] = "not-allowed"
    unknown_text = json.dumps(unknown, sort_keys=True, separators=(",", ":"))
    duplicate_key = first.to_checkpoint_value().replace('"epoch":1,', '"epoch":1,"epoch":1,', 1)
    bool_epoch = first.to_checkpoint_value().replace('"epoch":1', '"epoch":true', 1)

    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_SEAL_MISMATCH",
        lambda: CaptureClaimEpoch.from_checkpoint_value(tampered),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID",
        lambda: CaptureClaimEpoch.from_checkpoint_value(unknown_text),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID",
        lambda: CaptureClaimEpoch.from_checkpoint_value(duplicate_key),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID",
        lambda: CaptureClaimEpoch.from_checkpoint_value(bool_epoch),
    )
    assert request_sha256 == first.request_sha256


def test_claim_decoder_rejects_checkpoint_values_over_500_bytes_and_bad_markers() -> None:
    request_sha256, first, _second = _issued_history()
    payload = CaptureClaimPayload.for_claim(first)

    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_VALUE_TOO_LONG",
        lambda: CaptureClaimEpoch.from_checkpoint_value(" " * 501),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID",
        lambda: CaptureClaimMarker.from_checkpoint("ircap.v1.claim.marker.1", "v1"),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID",
        lambda: CaptureClaimPayload.from_checkpoint(
            "ircap.v1.other.payload.00000000000000000001", payload.cursor_value
        ),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID",
        lambda: CaptureClaimPayload.from_checkpoint(
            "ircap.v1.claim.payload.00000000000000000002", payload.cursor_value
        ),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID",
        lambda: CaptureClaimHistory.from_checkpoint_rows(
            request_sha256,
            (("ircap.v1.claim.marker.00000000000000000001", "bad"),),
            _payload_rows(first),
        ),
    )


def test_claim_epoch_rejects_values_outside_fixed_width_checkpoint_range() -> None:
    request = _request()
    capability = CaptureOwnerCapability(b"epoch-boundary-capability-000000".ljust(32, b"0"))
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID",
        lambda: CaptureClaimEpoch.issue(10**20, request.request_sha256, None, capability),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID",
        lambda: CaptureClaimMarker.for_epoch(10**20),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID",
        lambda: CaptureClaimPayload(
            10**20,
            "ircap.v1.claim.payload.100000000000000000000",
            "{}",
        ),
    )


def test_application_claim_result_requires_a_lease_only_for_acquired_state() -> None:
    request = _request()
    capability = CaptureOwnerCapability(b"result-owner-capability-0000000".ljust(32, b"0"))
    epoch = CaptureClaimEpoch.issue(1, request.request_sha256, None, capability)
    lease = InstrumentReferenceCaptureLease(
        identity=request.identity,
        request_sha256=request.request_sha256,
        epoch=epoch,
        owner_capability=capability,
    )
    acquired = InstrumentReferenceCaptureClaimResult(
        CaptureClaimDisposition.ACQUIRED,
        request.identity,
        request.request_sha256,
        lease=lease,
    )
    in_progress = InstrumentReferenceCaptureClaimResult(
        CaptureClaimDisposition.IN_PROGRESS,
        request.identity,
        request.request_sha256,
    )

    assert acquired.lease == lease
    assert in_progress.lease is None
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_RESULT_INVALID",
        lambda: InstrumentReferenceCaptureClaimResult(
            CaptureClaimDisposition.IN_PROGRESS,
            request.identity,
            request.request_sha256,
            lease=lease,
        ),
    )


def _source_only_snapshot(
    request: InstrumentReferenceCaptureRequest,
) -> InstrumentReferenceSnapshotRecord:
    """Build a complete, explicitly empty source batch with real snapshot seals."""
    occurrences = tuple(
        InstrumentReferenceOccurrence(
            occurrence_id=request.occurrence_id(scope),
            exchange=scope.exchange,
            list_status=scope.list_status,
            raw_audit_reference=RawAuditReference(
                raw_audit_id=str(request.scopes.index(scope) + 1),
                version="fixture-v1",
                content_hash="a" * 64,
                run_id=str(request.identity.run_id),
                ingested_run_id=str(request.identity.batch_id),
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
        fetch_rounds=(
            InstrumentReferenceFetchRound(UUID("fd034039-5706-419f-9e3f-2cf07f16b5a0"), candidate),
        ),
    )
    return make_instrument_reference_snapshot_record(
        content,
        snapshot_id=UUID("8ae082ac-9805-42dd-8955-e42fb2382c4c"),
        recorded_at=_BASE_TIME,
    )


def test_completed_and_pending_results_preserve_source_only_snapshot_semantics() -> None:
    request = _request()
    snapshot = _source_only_snapshot(request)
    result = InstrumentReferenceCaptureResult(
        CaptureExecutionStatus.COMPLETED,
        request.identity,
        request.request_sha256,
        snapshot,
    )
    replay = InstrumentReferenceCaptureClaimResult(
        CaptureClaimDisposition.COMPLETED,
        request.identity,
        request.request_sha256,
        snapshot=snapshot,
    )
    assert result.snapshot is replay.snapshot is snapshot
    assert snapshot.content.source_observed_at is None
    assert snapshot.content.source_available_at is None
    assert snapshot.content.must_not_use_for_decision is True
    assert snapshot.content.must_not_execute is True
    for status in (CaptureExecutionStatus.IN_PROGRESS, CaptureExecutionStatus.RESUME_REQUIRED):
        assert (
            InstrumentReferenceCaptureResult(
                status, request.identity, request.request_sha256
            ).snapshot
            is None
        )
    blocked = InstrumentReferenceCaptureResult(
        CaptureExecutionStatus.BLOCKED,
        request.identity,
        request.request_sha256,
        reason_code="INSTRUMENT_REFERENCE_CAPTURE_CONFLICT",
    )
    assert blocked.reason_code == "INSTRUMENT_REFERENCE_CAPTURE_CONFLICT"


def test_capture_outcome_cannot_publish_an_unmatched_or_incomplete_completion() -> None:
    request = _request()
    snapshot = _source_only_snapshot(request)
    completed = InstrumentReferenceCaptureResult(
        CaptureExecutionStatus.COMPLETED,
        request.identity,
        request.request_sha256,
        snapshot,
    )
    other_identity = InstrumentReferenceCaptureIdentity.for_capture(
        UUID("c60a348c-912b-4464-9cec-5c42180aa7ce")
    )
    for changes in (
        {"status": "completed"},
        {"identity": None},
        {"request_sha256": "corrupt"},
        {"snapshot": None},
        {"reason_code": "UNEXPECTED"},
        {"identity": other_identity},
        {"status": CaptureExecutionStatus.IN_PROGRESS},
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_RESULT_INVALID",
            lambda changes=changes: replace(completed, **changes),
        )
    for reason in (None, "", " padded ", 1):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_RESULT_INVALID",
            lambda reason=reason: InstrumentReferenceCaptureResult(
                CaptureExecutionStatus.BLOCKED,
                request.identity,
                request.request_sha256,
                reason_code=reason,
            ),
        )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_RESULT_INVALID",
        lambda: InstrumentReferenceCaptureResult(
            CaptureExecutionStatus.IN_PROGRESS,
            request.identity,
            request.request_sha256,
            reason_code="UNEXPECTED",
        ),
    )
    replay = InstrumentReferenceCaptureClaimResult(
        CaptureClaimDisposition.COMPLETED,
        request.identity,
        request.request_sha256,
        snapshot=snapshot,
    )
    for changes in (
        {"snapshot": None},
        {"identity": other_identity},
        {"request_sha256": True},
        {"disposition": "completed"},
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_RESULT_INVALID",
            lambda changes=changes: replace(replay, **changes),
        )


def test_parsed_empty_scope_cannot_borrow_other_scope_or_payload_evidence() -> None:
    request = _request()
    snapshot = _source_only_snapshot(request)
    occurrence = snapshot.content.fetch_rounds[0].candidate.occurrences[0]
    scope = request.scopes[0]
    parsed = InstrumentReferenceCaptureParsedScope(scope, occurrence, ())
    assert parsed.records == ()
    for changes in (
        {"scope": request.scopes[1]},
        {"scope": "SSE"},
        {"occurrence": None},
        {"records": []},
        {"records": (None,)},
        {"occurrence": replace(occurrence, row_count=1)},
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_PARSED_SCOPE_INVALID",
            lambda changes=changes: replace(parsed, **changes),
        )
    record = InstrumentReferenceRecord(
        ts_code="000001.SH",
        name="Fixture",
        source_exchange=scope.exchange,
        source_market=None,
        source_list_status=scope.list_status,
        list_date_raw=None,
        list_date=None,
        delist_date_raw=None,
        delist_date=None,
        exchange_suffix="SH",
        occurrence_id=occurrence.occurrence_id,
        raw_audit_reference=occurrence.raw_audit_reference,
        raw_payload_id=occurrence.raw_payload_id,
        raw_payload_hash=occurrence.raw_payload_hash,
    )
    one = InstrumentReferenceCaptureParsedScope(scope, replace(occurrence, row_count=1), (record,))
    assert one.records == (record,)
    for changed_record in (
        replace(record, occurrence_id=UUID("cedc9704-49b9-4e89-981a-3a77fcde9898")),
        replace(record, source_list_status=request.scopes[1].list_status),
        replace(record, raw_payload_id="other-response"),
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_PARSED_SCOPE_INVALID",
            lambda changed_record=changed_record: replace(one, records=(changed_record,)),
        )


def test_capture_invocation_and_lease_reject_cross_request_owner_capabilities() -> None:
    request = _request()
    capability = CaptureOwnerCapability.generate()
    epoch = CaptureClaimEpoch.issue(1, request.request_sha256, None, capability)
    lease = InstrumentReferenceCaptureLease(
        request.identity, request.request_sha256, epoch, capability
    )
    assert lease.owner_capability.matches_digest(epoch.owner_token_sha256)
    for changes in (
        {"identity": None},
        {"epoch": None},
        {"owner_capability": None},
        {"owner_capability": CaptureOwnerCapability.generate()},
        {"request_sha256": "b" * 64},
        {"request_sha256": True},
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_LEASE_INVALID",
            lambda changes=changes: replace(lease, **changes),
        )
    for request_value, mode in ((None, CaptureInvocationMode.NORMAL), (request, "resume")):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_INVOCATION_INVALID",
            lambda request_value=request_value, mode=mode: InstrumentReferenceCaptureInvocation(
                request_value, mode
            ),
        )


def test_scope_progress_requires_retained_response_before_reconstruction() -> None:
    request = _request()
    scope = request.scopes[0]
    progress = InstrumentReferenceCaptureScopeProgress(
        request,
        request.request_sha256,
        request.provider_contract.content_hash,
        scope,
        CaptureScopeProgressState.NOT_CAPTURED,
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_NOT_RETAINED", progress.to_provider_response_capture
    )
    retained = _retained_response(request, scope)
    audited = _audited_progress(request, scope, retained)
    assert (
        audited.to_provider_response_capture().body == retained.to_provider_response_capture().body
    )
    for changes in (
        {"retained_response": retained},
        {"state": CaptureScopeProgressState.RESPONSE_RETAINED},
        {"state": CaptureScopeProgressState.AUDIT_COMPLETE, "retained_response": retained},
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID",
            lambda changes=changes: replace(progress, **changes),
        )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID",
        lambda: replace(audited, state=CaptureScopeProgressState.RESPONSE_RETAINED),
    )


def test_capture_identifiers_reject_substituted_uuid_and_route_scope_values() -> None:
    request = _request()
    identity = request.identity
    other_uuid = UUID("07202991-13fe-4c5f-8be6-6ff15ccb4498")
    for changes in ({"run_id": other_uuid}, {"batch_id": other_uuid}, {"idempotency_key": "other"}):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_IDENTITY_INVALID",
            lambda changes=changes: replace(identity, **changes),
        )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_ID_INVALID",
        lambda: InstrumentReferenceCaptureIdentity.for_capture(str(_CAPTURE_ID)),
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_INVALID", lambda: identity.occurrence_id("SSE")
    )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_OUTSIDE_REQUEST",
        lambda: request.occurrence_id(InstrumentReferenceCaptureScope("SZSE", "L")),
    )
    for field, code, value in (
        ("capture_id", "ID_INVALID", str(_CAPTURE_ID)),
        ("provider_contract", "CONTRACT_INVALID", None),
        ("mapping_record", "MAPPING_INVALID", None),
        ("provider_route_id", "ROUTE_INVALID", " padded "),
        ("provider_route_revision", "ROUTE_INVALID", "bad\nroute"),
        ("actor_provenance", "ACTOR_INVALID", "x" * 241),
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_" + code,
            lambda field=field, value=value: replace(request, **{field: value}),
        )
    for exchange in (None, "", " SSE", "x\n", "x" * 33):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_INVALID",
            lambda exchange=exchange: InstrumentReferenceCaptureScope(exchange, "L"),
        )


def test_claim_decode_rejects_nontext_unicode_nonobject_and_broken_chain_values() -> None:
    digest, first, second = _issued_history()
    for value in (None, b"{}", "中文", "{", "[]", "null", "true"):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID",
            lambda value=value: CaptureClaimEpoch.from_checkpoint_value(value),
        )
    for field, value in (
        ("previous_claim_sha256", False),
        ("request_sha256", 1),
        ("owner_token_sha256", None),
    ):
        payload = first.to_payload()
        payload[field] = value
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID",
            lambda encoded=encoded: CaptureClaimEpoch.from_checkpoint_value(encoded),
        )
    for claim, changes in (
        (first, {"previous_claim_sha256": "a" * 64}),
        (second, {"previous_claim_sha256": None}),
        (first, {"claim_sha256": "b" * 64}),
    ):
        expected = "CLAIM_SEAL_MISMATCH" if "claim_sha256" in changes else "CLAIM_INVALID"
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_" + expected,
            lambda claim=claim, changes=changes: replace(claim, **changes),
        )
    for capability in (None, b"x" * 32):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_CAPABILITY_INVALID",
            lambda capability=capability: CaptureClaimEpoch.issue(1, digest, None, capability),
        )


def test_checkpoint_boundary_rejects_malformed_rows_and_mismatched_epoch_names() -> None:
    digest, first, second = _issued_history()
    marker = CaptureClaimMarker.for_epoch(1)
    payload = CaptureClaimPayload.for_claim(first)
    for changes in ({"epoch": True}, {"cursor_name": "foreign"}, {"cursor_value": "v2"}):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID",
            lambda changes=changes: replace(marker, **changes),
        )
    for changes in (
        {"epoch": True},
        {"cursor_name": "foreign"},
        {"cursor_value": None},
        {"cursor_value": second.to_checkpoint_value()},
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID",
            lambda changes=changes: replace(payload, **changes),
        )
    _assert_capture_error(
        "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID",
        lambda: CaptureClaimPayload.for_claim(None),
    )
    for cursor_name, cursor_value in ((None, "v1"), ("foreign", "v1")):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID",
            lambda cursor_name=cursor_name, cursor_value=cursor_value: (
                CaptureClaimMarker.from_checkpoint(cursor_name, cursor_value)
            ),
        )
    for cursor_name, cursor_value in (
        (None, first.to_checkpoint_value()),
        ("foreign", first.to_checkpoint_value()),
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID",
            lambda cursor_name=cursor_name, cursor_value=cursor_value: (
                CaptureClaimPayload.from_checkpoint(cursor_name, cursor_value)
            ),
        )
    for markers, payloads, code in (
        ([], (), "CLAIM_HISTORY_INVALID"),
        ((None,), (), "CLAIM_HISTORY_INVALID"),
        ((), (None,), "CLAIM_HISTORY_INVALID"),
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_" + code,
            lambda markers=markers, payloads=payloads: CaptureClaimHistory(
                digest, markers, payloads
            ),
        )
    for markers, payloads, code in (
        ([], (), "CLAIM_HISTORY_INVALID"),
        (([marker.cursor_name, marker.cursor_value],), (), "MARKER_INVALID"),
        ((), ((payload.cursor_name,),), "PAYLOAD_CHECKPOINT_INVALID"),
    ):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_" + code,
            lambda markers=markers, payloads=payloads: CaptureClaimHistory.from_checkpoint_rows(
                digest, markers, payloads
            ),
        )
    for token in (None, "x" * 32, b"short"):
        _assert_capture_error(
            "INSTRUMENT_REFERENCE_CAPTURE_CAPABILITY_INVALID",
            lambda token=token: CaptureOwnerCapability(token),
        )
    assert CaptureOwnerCapability.generate().matches_digest("not-a-digest") is False
