"""Default-database fenced persistence for source-only capture progress."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS, IntegrityError, router, transaction
from django.utils import timezone

from apps.data_center.application.instrument_reference_capture import (
    CaptureScopeProgressState,
    InstrumentReferenceCaptureLease,
    InstrumentReferenceCapturePersistencePort,
    InstrumentReferenceCaptureRetainedResponse,
    InstrumentReferenceCaptureScopeProgress,
)
from apps.data_center.application.instrument_reference_source import (
    InstrumentReferenceAuditOccurrence,
    InstrumentReferenceAuditOccurrenceReceipt,
    InstrumentReferenceAuditOccurrenceWriterPort,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    ProviderResponsePayloadRepositoryPort,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.control_plane import SyncItemState
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceCaptureScope,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.protocols import RawAuditRepositoryProtocol
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    canonical_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from apps.data_center.infrastructure.instrument_reference_capture_provider import (
    CaptureResponseStageStore,
)
from apps.data_center.infrastructure.instrument_reference_capture_receipt import (
    _SCOPE_PREFIX,
    scope_checkpoint_name,
    validate_progress_checkpoints,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)
from apps.data_center.infrastructure.models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
    RawAuditModel,
    RawPayloadModel,
    SyncBatchModel,
    SyncCheckpointModel,
    SyncItemAttemptModel,
    SyncRunModel,
)


class _FencedCompletionPort(Protocol):
    """Expose current-lease checks and the atomic finalization operation."""

    def is_current(self, lease: InstrumentReferenceCaptureLease) -> bool:
        """Return whether the in-memory capability owns the latest claim epoch."""

    def request_for_lease(
        self,
        lease: InstrumentReferenceCaptureLease,
    ) -> InstrumentReferenceCaptureRequest:
        """Rebuild the exact immutable request from its checkpoint descriptor."""

    def complete_snapshot(
        self,
        lease: InstrumentReferenceCaptureLease,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        """Persist snapshot, completion marker, and terminal controls atomically."""


class _ExactRawPayloadRepository(ProviderResponsePayloadRepositoryPort, Protocol):
    """Read and write exact immutable payloads on the default database alias."""

    @property
    def unit_of_work_key(self) -> str:
        """Identify the repository's transaction alias."""

    def get_by_id(self, payload_id: str) -> RawPayload | None:
        """Read one exact retained payload by its immutable ID."""


class _DefaultRawAuditRepository(RawAuditRepositoryProtocol, Protocol):
    """Require the capture's audit writer and reader to share default."""

    @property
    def unit_of_work_key(self) -> str:
        """Identify the repository's transaction alias."""


class DjangoInstrumentReferenceCapturePersistence(InstrumentReferenceCapturePersistencePort):
    """Persist response, audit and snapshot evidence behind the claim fence."""

    def __init__(
        self,
        claims: _FencedCompletionPort,
        snapshot_repository: DjangoInstrumentReferenceSnapshotRepository,
        raw_payload_repository: _ExactRawPayloadRepository,
        raw_audit_repository: _DefaultRawAuditRepository,
        audit_writer: InstrumentReferenceAuditOccurrenceWriterPort,
        response_stages: CaptureResponseStageStore,
    ) -> None:
        """Inject same-alias evidence repositories and the volatile fetch stage."""

        if (
            snapshot_repository.unit_of_work_key != "django:default"
            or raw_payload_repository.unit_of_work_key != "django:default"
            or raw_audit_repository.unit_of_work_key != "django:default"
        ):
            raise ValueError("instrument reference capture requires the default alias")
        self._claims = claims
        self._snapshots = snapshot_repository
        self._raw_payloads = raw_payload_repository
        self._raw_audits = raw_audit_repository
        self._audit_writer = audit_writer
        self._response_stages = response_stages
        self._retainer = RetainProviderResponsePayloadUseCase(raw_payload_repository)
        self._using = DEFAULT_DB_ALIAS
        for model in (
            RawPayloadModel,
            RawAuditModel,
            InstrumentReferenceMappingModel,
            InstrumentReferenceSnapshotModel,
            SyncRunModel,
            SyncBatchModel,
            SyncCheckpointModel,
            SyncItemAttemptModel,
        ):
            aliases = (router.db_for_read(model), router.db_for_write(model))
            if any(alias is not None and alias != self._using for alias in aliases):
                raise ValueError("instrument reference capture requires one default alias")

    def read_scope_progress(
        self,
        lease: InstrumentReferenceCaptureLease,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> InstrumentReferenceCaptureScopeProgress:
        """Read exact response/audit checkpoint pointers under the current lease."""

        with transaction.atomic(using=self._using):
            self._require_current(lease, request, scope)
            return self._read_scope_progress_locked(request, scope)

    def retain_response(
        self,
        lease: InstrumentReferenceCaptureLease,
        scope: InstrumentReferenceCaptureScope,
        response: ProviderResponseCapture,
    ) -> ProviderResponsePayloadReference:
        """Redact, retain and checkpoint one exact response in the same transaction."""

        if type(response) is not ProviderResponseCapture:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_INVALID"
            )
        request = self._request_for_lease(lease)
        staged = self._response_stages.get(request, scope, response)
        if staged is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_STAGE_MISSING"
            )
        try:
            with transaction.atomic(using=self._using):
                self._require_current(lease, request, scope)
                existing = self._read_scope_progress_locked(request, scope)
                if existing.state is not CaptureScopeProgressState.NOT_CAPTURED:
                    retained = existing.retained_response
                    if retained is None or retained.reference != staged.reference:
                        raise InstrumentReferenceCaptureContractError(
                            "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_POINTER_CONFLICT"
                        )
                    return retained.reference
                reference = self._retainer.execute(
                    response,
                    provider_name=request.provider_contract.provider_name,
                    dataset_key=request.provider_contract.dataset_key,
                    api_name=request.provider_contract.api_name,
                    request_params=staged.request_params,
                    sensitive_values=staged.sensitive_values,
                )
                raw_payload = self._raw_payloads.get_by_id(reference.payload_id)
                if (
                    reference != staged.reference
                    or raw_payload != staged.raw_payload
                    or raw_payload is None
                    or not reference.verifies(raw_payload)
                ):
                    raise InstrumentReferenceCaptureContractError(
                        "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_READBACK_INVALID"
                    )
                self._insert_checkpoint(
                    request,
                    scope_checkpoint_name(scope, "response"),
                    raw_payload.payload_id,
                )
                return reference
        finally:
            self._response_stages.discard(request, scope, response)

    def record_occurrence(
        self,
        lease: InstrumentReferenceCaptureLease,
        occurrence: InstrumentReferenceAuditOccurrence,
    ) -> InstrumentReferenceAuditOccurrenceReceipt:
        """Write one exact RawAudit occurrence and its scope pointer under lock."""

        request = self._request_for_lease(lease)
        scope = self._scope_for_occurrence(request, occurrence)
        with transaction.atomic(using=self._using):
            self._require_current(lease, request, scope)
            progress = self._read_scope_progress_locked(request, scope)
            if progress.state is CaptureScopeProgressState.AUDIT_COMPLETE:
                if progress.occurrence != occurrence or progress.receipt is None:
                    raise InstrumentReferenceCaptureContractError(
                        "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_POINTER_CONFLICT"
                    )
                return progress.receipt
            if (
                progress.state is not CaptureScopeProgressState.RESPONSE_RETAINED
                or progress.retained_response is None
                or not self._occurrence_matches_response(request, scope, occurrence, progress)
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID"
                )
            receipt = self._audit_writer.record(occurrence)
            if not self._receipt_matches(request, scope, occurrence, receipt):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_READBACK_INVALID"
                )
            self._insert_checkpoint(
                request,
                scope_checkpoint_name(scope, "audit"),
                receipt.raw_audit_reference.raw_audit_id,
            )
            return receipt

    def complete_snapshot(
        self,
        lease: InstrumentReferenceCaptureLease,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        """Delegate final write to the locked claim repository transaction."""

        return self._claims.complete_snapshot(lease, content)

    def get_snapshot(self, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        """Read and revalidate one exact snapshot through the existing repository."""

        return self._snapshots.get_snapshot(snapshot_id)

    def _require_current(
        self,
        lease: InstrumentReferenceCaptureLease,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> None:
        """Reject a stale/superseded epoch before every durable write or read."""

        if (
            type(lease) is not InstrumentReferenceCaptureLease
            or type(request) is not InstrumentReferenceCaptureRequest
            or type(scope) is not InstrumentReferenceCaptureScope
            or lease.identity != request.identity
            or lease.request_sha256 != request.request_sha256
            or scope not in request.scopes
            or not self._claims.is_current(lease)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_LEASE_STALE"
            )

    def _request_for_lease(
        self,
        lease: InstrumentReferenceCaptureLease,
    ) -> InstrumentReferenceCaptureRequest:
        """Resolve the request descriptor from the exact claim checkpoints."""

        resolved = self._claims.request_for_lease(lease)
        if (
            type(resolved) is not InstrumentReferenceCaptureRequest
            or resolved.identity != lease.identity
            or resolved.request_sha256 != lease.request_sha256
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_LEASE_INVALID"
            )
        return resolved

    def _read_scope_progress_locked(
        self,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> InstrumentReferenceCaptureScopeProgress:
        """Rebuild exact retained response and optional audit receipt by pointer."""

        rows = list(
            SyncCheckpointModel._default_manager.using(self._using)
            .filter(
                run_id=request.identity.run_id,
                batch_id=request.identity.batch_id,
                cursor_name__startswith=_SCOPE_PREFIX,
            )
            .values_list("cursor_name", "cursor_value")
        )
        pointers = validate_progress_checkpoints(request, rows)
        payload_id = pointers.get((scope, "response"))
        audit_id = pointers.get((scope, "audit"))
        if payload_id is None:
            return InstrumentReferenceCaptureScopeProgress(
                request=request,
                request_sha256=request.request_sha256,
                provider_contract_hash=request.provider_contract.content_hash,
                scope=scope,
                state=CaptureScopeProgressState.NOT_CAPTURED,
            )
        raw_payload = self._raw_payloads.get_by_id(payload_id)
        if raw_payload is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_POINTER_MISSING"
            )
        reference = _reference_from_raw_payload(raw_payload)
        retained = InstrumentReferenceCaptureRetainedResponse(reference, raw_payload)
        if audit_id is None:
            return InstrumentReferenceCaptureScopeProgress(
                request=request,
                request_sha256=request.request_sha256,
                provider_contract_hash=request.provider_contract.content_hash,
                scope=scope,
                state=CaptureScopeProgressState.RESPONSE_RETAINED,
                retained_response=retained,
            )
        audit = self._raw_audits.get_by_id(audit_id)
        if audit is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_POINTER_MISSING"
            )
        occurrence, receipt = _audit_progress_values(
            request,
            scope,
            retained,
            audit,
        )
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

    def _insert_checkpoint(
        self,
        request: InstrumentReferenceCaptureRequest,
        cursor_name: str,
        cursor_value: str,
    ) -> None:
        """Append one scope pointer or accept its exact committed replay."""

        existing = list(
            SyncCheckpointModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                run_id=request.identity.run_id,
                batch_id=request.identity.batch_id,
                cursor_name=cursor_name,
            )
        )
        if existing:
            if len(existing) == 1 and existing[0].cursor_value == cursor_value:
                return
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_CONFLICT"
            )
        try:
            with transaction.atomic(using=self._using):
                SyncCheckpointModel._default_manager.using(self._using).create(
                    run_id=request.identity.run_id,
                    batch_id=request.identity.batch_id,
                    cursor_name=cursor_name,
                    cursor_value=cursor_value,
                    state=SyncItemState.SUCCEEDED.value,
                    processed=0,
                    failed=0,
                    recorded_at=self._now(),
                    error_code="",
                )
        except IntegrityError:
            winner = list(
                SyncCheckpointModel._default_manager.using(self._using)
                .select_for_update()
                .filter(
                    run_id=request.identity.run_id,
                    batch_id=request.identity.batch_id,
                    cursor_name=cursor_name,
                )
            )
            if len(winner) != 1 or winner[0].cursor_value != cursor_value:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_CONFLICT"
                ) from None

    def _occurrence_matches_response(
        self,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
        occurrence: InstrumentReferenceAuditOccurrence,
        progress: InstrumentReferenceCaptureScopeProgress,
    ) -> bool:
        """Bind the audit write to its exact request scope and response payload."""

        retained = progress.retained_response
        contract = request.provider_contract
        return (
            retained is not None
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
            and occurrence.response_reference == retained.reference
            and occurrence.raw_payload == retained.raw_payload
        )

    @staticmethod
    def _scope_for_occurrence(
        request: InstrumentReferenceCaptureRequest,
        occurrence: InstrumentReferenceAuditOccurrence,
    ) -> InstrumentReferenceCaptureScope:
        """Resolve only the exact exchange/status pair already in the request."""

        if type(occurrence) is not InstrumentReferenceAuditOccurrence:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID"
            )
        for scope in request.scopes:
            if (scope.exchange, scope.list_status) == (
                occurrence.exchange,
                occurrence.list_status,
            ):
                return scope
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_OUTSIDE_REQUEST"
        )

    @staticmethod
    def _receipt_matches(
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
        occurrence: InstrumentReferenceAuditOccurrence,
        receipt: InstrumentReferenceAuditOccurrenceReceipt,
    ) -> bool:
        """Require the writer receipt to identify this exact audited response."""

        return (
            type(receipt) is InstrumentReferenceAuditOccurrenceReceipt
            and receipt.occurrence_id == request.occurrence_id(scope)
            and receipt.repository_alias == "default"
            and receipt.raw_payload_id == occurrence.response_reference.payload_id
            and receipt.raw_payload_hash == occurrence.response_reference.payload_hash
            and receipt.response_body_sha256 == occurrence.response_reference.body_sha256
            and receipt.raw_audit_reference.run_id == str(request.identity.run_id)
            and receipt.raw_audit_reference.ingested_run_id == str(request.identity.batch_id)
        )

    @staticmethod
    def _now() -> datetime:
        """Return an aware local persistence clock for checkpoint metadata only."""

        value = timezone.now()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
            or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_REPOSITORY_CLOCK_INVALID"
            )
        return value


def _reference_from_raw_payload(
    raw_payload: RawPayload,
) -> ProviderResponsePayloadReference:
    """Rebuild the exact provider-response reference from its immutable envelope."""

    payload = raw_payload.payload
    response_completed_at = payload.get("response_completed_at")
    if type(response_completed_at) is not str:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_POINTER_INVALID"
        )
    try:
        completed_at = datetime.fromisoformat(response_completed_at)
        reference = ProviderResponsePayloadReference(
            payload_id=raw_payload.payload_id,
            payload_hash=raw_payload.payload_hash,
            record_digest=raw_payload_record_digest(raw_payload),
            body_sha256=_payload_text(payload, "response_body_sha256"),
            retained_content_sha256=_payload_text(payload, "retained_content_sha256"),
            original_body_retained=_payload_bool(payload, "original_body_retained"),
            retained_content_encoding=_payload_text(payload, "retained_content_encoding"),
            body_size_bytes=_payload_int(payload, "response_body_size_bytes"),
            response_completed_at=completed_at,
            provider_name=_payload_text(payload, "provider_name"),
            dataset_key=_payload_text(payload, "dataset_key"),
            transport=ProviderResponseTransport(_payload_text(payload, "transport")),
        )
    except (TypeError, ValueError) as exc:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_POINTER_INVALID"
        ) from exc
    if not reference.verifies(raw_payload):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_POINTER_INVALID"
        )
    return reference


def _audit_progress_values(
    request: InstrumentReferenceCaptureRequest,
    scope: InstrumentReferenceCaptureScope,
    retained: InstrumentReferenceCaptureRetainedResponse,
    audit: RawAudit,
) -> tuple[InstrumentReferenceAuditOccurrence, InstrumentReferenceAuditOccurrenceReceipt]:
    """Rebuild and verify the exact occurrence receipt from one existing audit."""

    extra = audit.extra
    link_value = extra.get("instrument_reference_occurrence") if type(extra) is dict else None
    if type(link_value) is not dict or any(type(key) is not str for key in link_value):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_POINTER_INVALID"
        )
    link = cast(Mapping[str, object], link_value)
    reference_value = link.get("raw_payload_reference")
    if not isinstance(reference_value, Mapping) or any(
        type(key) is not str for key in reference_value
    ):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_POINTER_INVALID"
        )
    try:
        linked_reference = ProviderResponsePayloadReference.from_payload(reference_value)
    except (TypeError, ValueError) as exc:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_POINTER_INVALID"
        ) from exc
    contract = request.provider_contract
    request_params_hash = _request_params_hash(retained.raw_payload.request_params)
    if (
        request_params_hash is None
        or set(extra) != {"instrument_reference_occurrence"}
        or set(link)
        != {
            "schema",
            "occurrence_id",
            "contract_id",
            "contract_version",
            "contract_hash",
            "api_name",
            "dataset_key",
            "exchange",
            "list_status",
            "fields",
            "row_count",
            "database_alias",
            "raw_payload_reference",
        }
        or audit.run_id != str(request.identity.run_id)
        or audit.ingested_run_id != str(request.identity.batch_id)
        or audit.provider_name != contract.provider_name
        or audit.capability != "instrument_reference"
        or audit.status != "ok"
        or audit.request_params != retained.raw_payload.request_params
        or audit.request_params_hash != request_params_hash
        or audit.response_payload_hash != retained.reference.body_sha256
        or audit.schema_fingerprint != retained.raw_payload.schema_fingerprint
        or audit.parser_version != "instrument-reference-raw-audit.v1"
        or audit.payload_size_bytes != retained.reference.body_size_bytes
        or audit.row_count != link.get("row_count")
        or audit.fetched_at != retained.reference.response_completed_at
        or audit.redacted is not True
        or audit.content_hash != raw_audit_content_hash(audit)
        or linked_reference != retained.reference
        or link.get("schema") != "instrument-reference-raw-audit-occurrence.v1"
        or link.get("occurrence_id") != str(request.occurrence_id(scope))
        or link.get("contract_id") != contract.contract_id
        or link.get("contract_version") != contract.contract_version
        or link.get("contract_hash") != contract.content_hash
        or link.get("api_name") != contract.api_name
        or link.get("dataset_key") != contract.dataset_key
        or link.get("exchange") != scope.exchange
        or link.get("list_status") != scope.list_status
        or link.get("fields") != contract.fields_csv
        or link.get("database_alias") != "default"
        or type(audit.raw_audit_id) is not str
        or not audit.raw_audit_id
    ):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_POINTER_INVALID"
        )
    occurrence = InstrumentReferenceAuditOccurrence(
        occurrence_id=request.occurrence_id(scope),
        run_id=request.identity.run_id,
        ingested_run_id=request.identity.batch_id,
        contract_id=contract.contract_id,
        contract_version=contract.contract_version,
        contract_hash=contract.content_hash,
        api_name=contract.api_name,
        dataset_key=contract.dataset_key,
        exchange=scope.exchange,
        list_status=scope.list_status,
        fields=contract.fields_csv,
        row_count=audit.row_count,
        response_reference=retained.reference,
        raw_payload=retained.raw_payload,
    )
    receipt = InstrumentReferenceAuditOccurrenceReceipt(
        occurrence_id=occurrence.occurrence_id,
        raw_audit_reference=audit.exact_reference(),
        raw_payload_id=retained.reference.payload_id,
        raw_payload_hash=retained.reference.payload_hash,
        response_body_sha256=retained.reference.body_sha256,
        request_params_hash=request_params_hash,
        repository_alias="default",
    )
    return occurrence, receipt


def _request_params_hash(value: object) -> str | None:
    """Compute the writer's canonical request hash without coercion."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        return None
    try:
        encoded = canonical_provider_response_json(value).encode("utf-8")
    except (RecursionError, TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _payload_text(value: dict[str, object], key: str) -> str:
    """Read one exact text field from the stored RawPayload envelope."""

    item = value.get(key)
    if type(item) is not str:
        raise ValueError("capture_raw_payload_field_invalid")
    return item


def _payload_bool(value: dict[str, object], key: str) -> bool:
    """Read one exact boolean field from the stored RawPayload envelope."""

    item = value.get(key)
    if type(item) is not bool:
        raise ValueError("capture_raw_payload_field_invalid")
    return item


def _payload_int(value: dict[str, object], key: str) -> int:
    """Read one exact integer field while excluding bool values."""

    item = value.get(key)
    if type(item) is not int:
        raise ValueError("capture_raw_payload_field_invalid")
    return item


__all__ = ["DjangoInstrumentReferenceCapturePersistence"]
