"""Counterexamples for bounded per-scope and completion checkpoint receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceCaptureScope,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingContent,
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
)
from apps.data_center.infrastructure.instrument_reference_capture_receipt import (
    CaptureCompletionMarker,
    scope_checkpoint_name,
    validate_progress_checkpoints,
)

_NOW = datetime(2026, 10, 22, 2, 0, tzinfo=UTC)


def _request() -> InstrumentReferenceCaptureRequest:
    """Build one explicit ordinary A-share scope with a persisted mapping shape."""

    contract = InstrumentReferenceProviderContract(
        contract_id="fixture.stock-basic",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key="fixture.stock-basic",
        api_name="stock_basic",
        fields=("ts_code", "name", "exchange", "market", "list_status", "list_date", "delist_date"),
        exchange_scope=("SSE",),
        list_status_scope=("L",),
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
    )
    mapping = make_instrument_reference_mapping_record(
        InstrumentReferenceMappingContent(
            mapping_id="fixture.mapping",
            mapping_version="fixture-v1",
            source_crosswalk=crosswalk,
            exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
            exchange_source_market_board_pairs=(("SSE", "fixture-market", "FIXTURE"),),
        ),
        mapping_record_id=UUID("c5d7a91a-17f2-43a2-8f55-0a74789be639"),
        recorded_at=_NOW,
    )
    return InstrumentReferenceCaptureRequest(
        capture_id=UUID("84c776c3-0db4-4aed-9d2c-62e18b917ed5"),
        provider_contract=contract,
        provider_route_id="tushare.stock_basic",
        provider_route_revision="fixture-route-rev-1",
        provider_configuration_id=17,
        mapping_record=mapping,
    )


def _snapshot_record() -> InstrumentReferenceSnapshotRecord:
    """Build a sealed source record using the real Domain digest format."""

    request = _request()
    scope = request.scopes[0]
    occurrence = InstrumentReferenceOccurrence(
        occurrence_id=request.occurrence_id(scope),
        exchange=scope.exchange,
        list_status=scope.list_status,
        raw_audit_reference=RawAuditReference(
            raw_audit_id="184467",
            version="fixture-v1",
            content_hash="a" * 64,
            run_id=str(request.identity.run_id),
            ingested_run_id=str(request.identity.batch_id),
        ),
        raw_payload_id="e3b0c442-98fc-1c14-9afc-d8c2f8b44a21",
        raw_payload_hash="sha256:" + "b" * 64,
        response_body_sha256="c" * 64,
        response_completed_at=_NOW,
        row_count=0,
    )
    candidate = InstrumentReferenceCandidate(
        provider_contract=request.provider_contract,
        crosswalk=request.mapping_record.content.source_crosswalk,
        occurrences=(occurrence,),
        records=(),
    )
    content = InstrumentReferenceSnapshotContent(
        run_id=request.identity.run_id,
        mapping_record=request.mapping_record,
        fetch_rounds=(InstrumentReferenceFetchRound(request.identity.capture_id, candidate),),
    )
    return make_instrument_reference_snapshot_record(
        content,
        snapshot_id=UUID("8d407a7e-9220-40ce-bdb1-5eb735e557bd"),
        recorded_at=_NOW,
    )


def test_progress_checkpoint_accepts_uuid_payload_and_numeric_raw_audit_ids() -> None:
    """Use the existing UUID payload and integer RawAudit primary-key formats."""

    request = _request()
    scope = request.scopes[0]
    pointers = validate_progress_checkpoints(
        request,
        [
            (scope_checkpoint_name(scope, "response"), "e3b0c442-98fc-1c14-9afc-d8c2f8b44a21"),
            (scope_checkpoint_name(scope, "audit"), "184467"),
        ],
    )

    assert pointers[(scope, "response")] == "e3b0c442-98fc-1c14-9afc-d8c2f8b44a21"
    assert pointers[(scope, "audit")] == "184467"


@pytest.mark.parametrize("audit_id", ["0", "01", "-1", "١", "audit-1"])
def test_progress_checkpoint_rejects_noncanonical_raw_audit_primary_key(audit_id: str) -> None:
    """Reject malformed integer audit pointers without coercing their text."""

    request = _request()
    scope = request.scopes[0]
    rows = [
        (scope_checkpoint_name(scope, "response"), "e3b0c442-98fc-1c14-9afc-d8c2f8b44a21"),
        (scope_checkpoint_name(scope, "audit"), audit_id),
    ]

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        validate_progress_checkpoints(request, rows)

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"


def test_progress_checkpoint_rejects_audit_without_retained_response() -> None:
    """Require a response receipt before the audit pointer can advance."""

    request = _request()
    scope: InstrumentReferenceCaptureScope = request.scopes[0]

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        validate_progress_checkpoints(
            request,
            [(scope_checkpoint_name(scope, "audit"), "184467")],
        )

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"


def test_completion_marker_roundtrips_domain_prefixed_snapshot_digests() -> None:
    """Roundtrip the snapshot's existing prefixed SHA-256 wire format."""

    snapshot = _snapshot_record()
    marker = CaptureCompletionMarker(
        request_sha256="a" * 64,
        epoch=1,
        claim_sha256="b" * 64,
        snapshot_id=snapshot.snapshot_id,
        snapshot_content_hash=snapshot.content_hash,
        snapshot_record_digest=snapshot.record_digest,
    )

    assert snapshot.content_hash.startswith("sha256:")
    assert snapshot.record_digest.startswith("sha256:")
    assert CaptureCompletionMarker.decode(marker.encode()) == marker


def test_completion_marker_rejects_unknown_snapshot_digest_prefix() -> None:
    """Reject a digest prefix that the snapshot Domain never emits."""

    snapshot = _snapshot_record()
    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        CaptureCompletionMarker(
            request_sha256="a" * 64,
            epoch=1,
            claim_sha256="b" * 64,
            snapshot_id=snapshot.snapshot_id,
            snapshot_content_hash="sha512:" + snapshot.content_hash.partition(":")[2],
            snapshot_record_digest=snapshot.record_digest,
        )

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
