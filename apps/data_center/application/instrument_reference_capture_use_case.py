"""Fenced source-only instrument-reference capture use case."""

from __future__ import annotations

from apps.data_center.application.instrument_reference_capture import (
    CaptureClaimDisposition,
    CaptureExecutionStatus,
    CaptureScopeProgressState,
    InstrumentReferenceCaptureClaimPort,
    InstrumentReferenceCaptureClaimResult,
    InstrumentReferenceCaptureInvocation,
    InstrumentReferenceCaptureLease,
    InstrumentReferenceCaptureParsedScope,
    InstrumentReferenceCapturePersistencePort,
    InstrumentReferenceCaptureProviderPort,
    InstrumentReferenceCaptureResult,
    InstrumentReferenceCaptureRetainedResponse,
    InstrumentReferenceCaptureScopeParserPort,
    InstrumentReferenceCaptureScopeProgress,
    InstrumentReferenceCaptureSnapshotAssemblerPort,
)
from apps.data_center.application.instrument_reference_source import (
    InstrumentReferenceAuditOccurrence,
    InstrumentReferenceAuditOccurrenceReceipt,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    _safe_content_type,
)
from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceCaptureScope,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceOccurrence,
)
from apps.data_center.domain.provider_response import ProviderResponseCapture
from apps.data_center.domain.raw_landing import RawPayload


class CaptureInstrumentReferenceSnapshotUseCase:
    """Orchestrate one source-only capture through typed fenced ports."""

    def __init__(
        self,
        claim_port: InstrumentReferenceCaptureClaimPort,
        provider_port: InstrumentReferenceCaptureProviderPort,
        persistence_port: InstrumentReferenceCapturePersistencePort,
        parser_port: InstrumentReferenceCaptureScopeParserPort,
        assembler_port: InstrumentReferenceCaptureSnapshotAssemblerPort,
    ) -> None:
        """Inject claim, provider, persistence, parsing and assembly boundaries."""

        self._claim_port = claim_port
        self._provider_port = provider_port
        self._persistence_port = persistence_port
        self._parser_port = parser_port
        self._assembler_port = assembler_port

    def execute(
        self,
        invocation: InstrumentReferenceCaptureInvocation,
    ) -> InstrumentReferenceCaptureResult:
        """Claim, resume exact evidence, then append one complete source snapshot.

        All durable writes go through persistence operations that receive the
        current lease. Each response and audit write is followed by a fresh
        progress read; this method never treats a prior lease check as a write
        fence. Provider and unknown port failures propagate without being
        represented as a completed capture.
        """

        if type(invocation) is not InstrumentReferenceCaptureInvocation:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_INVOCATION_INVALID"
            )
        request = invocation.request
        claim = self._claim_port.claim(invocation)
        if (
            type(claim) is not InstrumentReferenceCaptureClaimResult
            or claim.identity != request.identity
            or claim.request_sha256 != request.request_sha256
        ):
            return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_BINDING_INVALID")

        if claim.disposition is CaptureClaimDisposition.COMPLETED:
            return self._read_completed(request, claim)
        if claim.disposition is CaptureClaimDisposition.IN_PROGRESS:
            return InstrumentReferenceCaptureResult(
                CaptureExecutionStatus.IN_PROGRESS,
                request.identity,
                request.request_sha256,
            )
        if claim.disposition is CaptureClaimDisposition.RESUME_REQUIRED:
            return InstrumentReferenceCaptureResult(
                CaptureExecutionStatus.RESUME_REQUIRED,
                request.identity,
                request.request_sha256,
            )
        if claim.disposition is not CaptureClaimDisposition.ACQUIRED or claim.lease is None:
            return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_BINDING_INVALID")

        lease = claim.lease
        parsed_scopes: list[InstrumentReferenceCaptureParsedScope] = []
        for scope in request.scopes:
            progress = self._read_progress(lease, request, scope)
            if progress is None:
                return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID")

            if progress.state is CaptureScopeProgressState.NOT_CAPTURED:
                response = self._provider_port.fetch_scope(request, scope)
                if type(response) is not ProviderResponseCapture:
                    return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_INVALID")
                retained_reference = self._persistence_port.retain_response(lease, scope, response)
                if type(retained_reference) is not ProviderResponsePayloadReference:
                    return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_INVALID")
                progress = self._read_progress(lease, request, scope)
                if (
                    progress is None
                    or progress.state
                    not in (
                        CaptureScopeProgressState.RESPONSE_RETAINED,
                        CaptureScopeProgressState.AUDIT_COMPLETE,
                    )
                    or progress.retained_response is None
                    or progress.retained_response.reference != retained_reference
                    or not _response_matches_retained_capture(
                        response,
                        progress.retained_response,
                    )
                ):
                    return self._blocked(
                        request,
                        "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_READBACK_INVALID",
                    )

            if progress.state is CaptureScopeProgressState.RESPONSE_RETAINED:
                retained = progress.retained_response
                if retained is None:
                    return self._blocked(
                        request,
                        "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID",
                    )
                occurrence = self._parser_port.build_audit_occurrence(request, progress)
                if not self._occurrence_matches_progress(request, scope, progress, occurrence):
                    return self._blocked(
                        request,
                        "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID",
                    )
                receipt = self._persistence_port.record_occurrence(lease, occurrence)
                expected_progress = self._audited_progress(
                    request, scope, retained, occurrence, receipt
                )
                if expected_progress is None:
                    return self._blocked(
                        request,
                        "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID",
                    )
                progress = self._read_progress(lease, request, scope)
                if progress != expected_progress:
                    return self._blocked(
                        request,
                        "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_READBACK_INVALID",
                    )

            if progress.state is not CaptureScopeProgressState.AUDIT_COMPLETE:
                return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_INCOMPLETE")
            progress.to_provider_response_capture()
            parsed = self._parser_port.parse_scope(request, progress)
            expected_occurrence = self._parsed_occurrence(progress)
            if (
                type(parsed) is not InstrumentReferenceCaptureParsedScope
                or parsed.scope != scope
                or parsed.occurrence != expected_occurrence
            ):
                return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_PARSED_SCOPE_INVALID")
            parsed_scopes.append(parsed)

        parsed_tuple = tuple(parsed_scopes)
        content = self._assembler_port.assemble_snapshot_content(request, parsed_tuple)
        if not self._snapshot_content_matches_request(request, content, parsed_tuple):
            return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_CONTENT_INVALID")
        snapshot = self._persistence_port.complete_snapshot(lease, content)
        if (
            type(snapshot) is not InstrumentReferenceSnapshotRecord
            or snapshot.content != content
            or not self._completed_snapshot_matches_request(request, snapshot)
        ):
            return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_READBACK_INVALID")
        return InstrumentReferenceCaptureResult(
            CaptureExecutionStatus.COMPLETED,
            request.identity,
            request.request_sha256,
            snapshot=snapshot,
        )

    def _read_completed(
        self,
        request: InstrumentReferenceCaptureRequest,
        claim: InstrumentReferenceCaptureClaimResult,
    ) -> InstrumentReferenceCaptureResult:
        """Re-read only the exact completed snapshot pointer; never refetch."""

        snapshot = claim.snapshot
        if snapshot is None or not self._completed_snapshot_matches_request(request, snapshot):
            return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_COMPLETED_POINTER_INVALID")
        readback = self._persistence_port.get_snapshot(snapshot.snapshot_id)
        if (
            type(readback) is not InstrumentReferenceSnapshotRecord
            or readback != snapshot
            or not self._completed_snapshot_matches_request(request, readback)
        ):
            return self._blocked(request, "INSTRUMENT_REFERENCE_CAPTURE_COMPLETED_READBACK_INVALID")
        return InstrumentReferenceCaptureResult(
            CaptureExecutionStatus.COMPLETED,
            request.identity,
            request.request_sha256,
            snapshot=readback,
        )

    def _read_progress(
        self,
        lease: InstrumentReferenceCaptureLease,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> InstrumentReferenceCaptureScopeProgress | None:
        """Read committed progress and verify its immutable request binding."""

        progress = self._persistence_port.read_scope_progress(lease, request, scope)
        if (
            type(progress) is not InstrumentReferenceCaptureScopeProgress
            or progress.request != request
            or progress.request_sha256 != request.request_sha256
            or progress.provider_contract_hash != request.provider_contract.content_hash
            or progress.scope != scope
        ):
            return None
        return progress

    @staticmethod
    def _occurrence_matches_progress(
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
        progress: InstrumentReferenceCaptureScopeProgress,
        occurrence: InstrumentReferenceAuditOccurrence,
    ) -> bool:
        """Bind the pre-audit occurrence to exact request and retained response."""

        retained = progress.retained_response
        if retained is None:
            return False
        progress.to_provider_response_capture()
        contract = request.provider_contract
        return (
            type(occurrence) is InstrumentReferenceAuditOccurrence
            and occurrence.occurrence_id == request.occurrence_id(scope)
            and occurrence.run_id == request.identity.run_id
            and occurrence.ingested_run_id == request.identity.batch_id
            and occurrence.contract_id == contract.contract_id
            and occurrence.contract_version == contract.contract_version
            and occurrence.contract_hash == contract.content_hash
            and occurrence.api_name == contract.api_name
            and occurrence.dataset_key == contract.dataset_key
            and occurrence.exchange == scope.exchange
            and occurrence.list_status == scope.list_status
            and occurrence.fields == contract.fields_csv
            and type(occurrence.row_count) is int
            and occurrence.row_count >= 0
            and type(occurrence.response_reference) is ProviderResponsePayloadReference
            and occurrence.response_reference == retained.reference
            and type(occurrence.raw_payload) is RawPayload
            and occurrence.raw_payload == retained.raw_payload
        )

    @staticmethod
    def _audited_progress(
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
        retained: InstrumentReferenceCaptureRetainedResponse,
        occurrence: InstrumentReferenceAuditOccurrence,
        receipt: InstrumentReferenceAuditOccurrenceReceipt,
    ) -> InstrumentReferenceCaptureScopeProgress | None:
        """Build the exact progress shape the fenced writer must read back."""

        if type(receipt) is not InstrumentReferenceAuditOccurrenceReceipt:
            return None
        try:
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
        except InstrumentReferenceCaptureContractError:
            return None

    @staticmethod
    def _parsed_occurrence(
        progress: InstrumentReferenceCaptureScopeProgress,
    ) -> InstrumentReferenceOccurrence | None:
        """Project only the receipt-bound domain occurrence after audit readback."""

        occurrence = progress.occurrence
        receipt = progress.receipt
        retained = progress.retained_response
        if occurrence is None or receipt is None or retained is None:
            return None
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

    @classmethod
    def _snapshot_content_matches_request(
        cls,
        request: InstrumentReferenceCaptureRequest,
        content: InstrumentReferenceSnapshotContent,
        parsed_scopes: tuple[InstrumentReferenceCaptureParsedScope, ...] | None = None,
    ) -> bool:
        """Require the full request, mapping and all scope evidence in one round."""

        if (
            type(content) is not InstrumentReferenceSnapshotContent
            or content.run_id != request.identity.run_id
            or content.mapping_record != request.mapping_record
            or content.source_observed_at is not None
            or content.source_available_at is not None
            or content.must_not_use_for_decision is not True
            or content.must_not_execute is not True
            or len(content.fetch_rounds) != 1
        ):
            return False
        fetch_round = content.fetch_rounds[0]
        if type(fetch_round) is not InstrumentReferenceFetchRound:
            return False
        candidate = fetch_round.candidate
        if (
            type(candidate) is not InstrumentReferenceCandidate
            or candidate.provider_contract != request.provider_contract
            or candidate.crosswalk != request.mapping_record.content.source_crosswalk
            or tuple((item.exchange, item.list_status) for item in candidate.occurrences)
            != tuple((scope.exchange, scope.list_status) for scope in request.scopes)
            or tuple(item.occurrence_id for item in candidate.occurrences)
            != tuple(request.occurrence_id(scope) for scope in request.scopes)
            or any(
                occurrence.raw_audit_reference.run_id != str(request.identity.run_id)
                or occurrence.raw_audit_reference.ingested_run_id != str(request.identity.batch_id)
                or type(occurrence.row_count) is not int
                or occurrence.row_count < 0
                for occurrence in candidate.occurrences
            )
        ):
            return False
        if parsed_scopes is None:
            return True
        return (
            tuple(item.scope for item in parsed_scopes) == request.scopes
            and candidate.occurrences == tuple(item.occurrence for item in parsed_scopes)
            and candidate.records
            == tuple(record for item in parsed_scopes for record in item.records)
        )

    @classmethod
    def _completed_snapshot_matches_request(
        cls,
        request: InstrumentReferenceCaptureRequest,
        snapshot: InstrumentReferenceSnapshotRecord,
    ) -> bool:
        """Verify a snapshot returned by a completed pointer or final write."""

        return type(
            snapshot
        ) is InstrumentReferenceSnapshotRecord and cls._snapshot_content_matches_request(
            request, snapshot.content
        )

    @staticmethod
    def _blocked(
        request: InstrumentReferenceCaptureRequest,
        reason_code: str,
    ) -> InstrumentReferenceCaptureResult:
        """Return a stable non-completed outcome without exposing provider data."""

        return InstrumentReferenceCaptureResult(
            CaptureExecutionStatus.BLOCKED,
            request.identity,
            request.request_sha256,
            reason_code=reason_code,
        )


def _response_matches_retained_capture(
    response: ProviderResponseCapture,
    retained: InstrumentReferenceCaptureRetainedResponse,
) -> bool:
    """Bind a fresh response to retained evidence, normalizing only Content-Type.

    RawPayload intentionally stores a safe media type rather than the original
    header parameters or casing. The body, digest, size, completion time,
    status, transport, and body-parsed payload remain exact readback bindings.
    A content type redacted as a credential cannot be matched without the
    original secret literals, so that case fails closed.
    """

    if type(response) is not ProviderResponseCapture:
        return False
    persisted = retained.to_provider_response_capture()
    return (
        response.body == persisted.body
        and response.body_sha256 == persisted.body_sha256
        and response.body_size_bytes == persisted.body_size_bytes
        and response.response_completed_at == persisted.response_completed_at
        and response.status_code == persisted.status_code
        and response.transport is persisted.transport
        and _safe_content_type(response.content_type, ())
        == _safe_content_type(persisted.content_type, ())
        and response.payload_matches_body()
        and persisted.payload_matches_body()
    )


__all__ = ["CaptureInstrumentReferenceSnapshotUseCase"]
