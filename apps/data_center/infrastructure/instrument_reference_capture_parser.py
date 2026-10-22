"""Strict stock-basic parser and snapshot assembler for source capture."""

from __future__ import annotations

from apps.data_center.application.instrument_reference_capture import (
    CaptureScopeProgressState,
    InstrumentReferenceCaptureParsedScope,
    InstrumentReferenceCaptureRetainedResponse,
    InstrumentReferenceCaptureScopeParserPort,
    InstrumentReferenceCaptureScopeProgress,
    InstrumentReferenceCaptureSnapshotAssemblerPort,
)
from apps.data_center.application.instrument_reference_source import (
    InstrumentReferenceAuditOccurrence,
    InstrumentReferenceAuditOccurrenceReceipt,
)
from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceSnapshotContent,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceOccurrence,
)
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    _bind_rows_to_occurrence,
    _parse_stock_basic_rows,
)


class TushareStockBasicCaptureParser(
    InstrumentReferenceCaptureScopeParserPort,
    InstrumentReferenceCaptureSnapshotAssemblerPort,
):
    """Reuse the strict stock-basic parser for capture-only typed ports."""

    def build_audit_occurrence(
        self,
        request: InstrumentReferenceCaptureRequest,
        progress: InstrumentReferenceCaptureScopeProgress,
    ) -> InstrumentReferenceAuditOccurrence:
        """Parse the retained exact body and derive the audit row count."""

        self._validate_progress(request, progress, CaptureScopeProgressState.RESPONSE_RETAINED)
        retained = progress.retained_response
        if retained is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID"
            )
        capture = retained.to_provider_response_capture()
        if not capture.payload_matches_body():
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_INVALID"
            )
        rows = _parse_stock_basic_rows(
            retained.raw_payload,
            retained.reference,
            provider_contract=request.provider_contract,
            crosswalk=request.mapping_record.content.source_crosswalk,
            exchange=progress.scope.exchange,
            list_status=progress.scope.list_status,
        )
        contract = request.provider_contract
        return InstrumentReferenceAuditOccurrence(
            occurrence_id=request.occurrence_id(progress.scope),
            run_id=request.identity.run_id,
            ingested_run_id=request.identity.batch_id,
            contract_id=contract.contract_id,
            contract_version=contract.contract_version,
            contract_hash=contract.content_hash,
            api_name=contract.api_name,
            dataset_key=contract.dataset_key,
            exchange=progress.scope.exchange,
            list_status=progress.scope.list_status,
            fields=contract.fields_csv,
            row_count=len(rows),
            response_reference=retained.reference,
            raw_payload=retained.raw_payload,
        )

    def parse_scope(
        self,
        request: InstrumentReferenceCaptureRequest,
        progress: InstrumentReferenceCaptureScopeProgress,
    ) -> InstrumentReferenceCaptureParsedScope:
        """Parse one audited scope from its verified retained response body."""

        self._validate_progress(request, progress, CaptureScopeProgressState.AUDIT_COMPLETE)
        retained = progress.retained_response
        occurrence = progress.occurrence
        receipt = progress.receipt
        if retained is None or occurrence is None or receipt is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID"
            )
        retained.to_provider_response_capture()
        rows = _parse_stock_basic_rows(
            retained.raw_payload,
            retained.reference,
            provider_contract=request.provider_contract,
            crosswalk=request.mapping_record.content.source_crosswalk,
            exchange=progress.scope.exchange,
            list_status=progress.scope.list_status,
        )
        records = tuple(
            _bind_rows_to_occurrence(
                rows,
                occurrence=self._to_domain_occurrence(occurrence, receipt, retained),
                crosswalk=request.mapping_record.content.source_crosswalk,
            )
        )
        return InstrumentReferenceCaptureParsedScope(
            scope=progress.scope,
            occurrence=self._to_domain_occurrence(occurrence, receipt, retained),
            records=records,
        )

    def assemble_snapshot_content(
        self,
        request: InstrumentReferenceCaptureRequest,
        parsed_scopes: tuple[InstrumentReferenceCaptureParsedScope, ...],
    ) -> InstrumentReferenceSnapshotContent:
        """Assemble every explicit request scope into one deterministic round."""

        if (
            type(parsed_scopes) is not tuple
            or tuple(item.scope for item in parsed_scopes) != request.scopes
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_CONTENT_INVALID"
            )
        candidate = InstrumentReferenceCandidate(
            provider_contract=request.provider_contract,
            crosswalk=request.mapping_record.content.source_crosswalk,
            occurrences=tuple(item.occurrence for item in parsed_scopes),
            records=tuple(record for item in parsed_scopes for record in item.records),
        )
        return InstrumentReferenceSnapshotContent(
            run_id=request.identity.run_id,
            mapping_record=request.mapping_record,
            fetch_rounds=(
                InstrumentReferenceFetchRound(
                    fetch_round_id=request.identity.capture_id,
                    candidate=candidate,
                ),
            ),
        )

    @staticmethod
    def _validate_progress(
        request: InstrumentReferenceCaptureRequest,
        progress: InstrumentReferenceCaptureScopeProgress,
        required_state: CaptureScopeProgressState,
    ) -> None:
        """Require the exact request and stage before parsing provider data."""

        if (
            type(request) is not InstrumentReferenceCaptureRequest
            or type(progress) is not InstrumentReferenceCaptureScopeProgress
            or progress.request != request
            or progress.request_sha256 != request.request_sha256
            or progress.provider_contract_hash != request.provider_contract.content_hash
            or progress.scope not in request.scopes
            or progress.state is not required_state
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID"
            )

    @staticmethod
    def _to_domain_occurrence(
        occurrence: InstrumentReferenceAuditOccurrence,
        receipt: InstrumentReferenceAuditOccurrenceReceipt,
        retained: InstrumentReferenceCaptureRetainedResponse,
    ) -> InstrumentReferenceOccurrence:
        """Build the source-domain occurrence from a verified audit receipt."""

        if (
            type(receipt) is not InstrumentReferenceAuditOccurrenceReceipt
            or type(retained) is not InstrumentReferenceCaptureRetainedResponse
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID"
            )
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
