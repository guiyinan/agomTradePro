"""Typed application ports for fenced, source-only reference capture.

This module declares composition boundaries only. It does not activate a
provider, persist rows, or make a source decision.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast
from uuid import UUID

from apps.data_center.application.instrument_reference_source import (
    InstrumentReferenceAuditOccurrence,
    InstrumentReferenceAuditOccurrenceReceipt,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_capture import (
    CaptureClaimEpoch,
    CaptureOwnerCapability,
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureIdentity,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceCaptureScope,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceOccurrence,
    InstrumentReferenceRecord,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    canonical_provider_response_json,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CaptureInvocationMode(StrEnum):
    """Operator invocation control kept outside the immutable request hash."""

    NORMAL = "normal"
    RESUME = "resume"


class CaptureClaimDisposition(StrEnum):
    """Possible outcomes from an atomic claim/replay boundary."""

    ACQUIRED = "acquired"
    IN_PROGRESS = "in_progress"
    RESUME_REQUIRED = "resume_required"
    COMPLETED = "completed"


class CaptureExecutionStatus(StrEnum):
    """Stable public outcome categories for a future capture use case."""

    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    RESUME_REQUIRED = "resume_required"
    BLOCKED = "blocked"


class CaptureScopeProgressState(StrEnum):
    """Durable progress stage for one exact request scope."""

    NOT_CAPTURED = "not_captured"
    RESPONSE_RETAINED = "response_retained"
    AUDIT_COMPLETE = "audit_complete"


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureRetainedResponse:
    """Exact verified response evidence that can be replayed without HTTP."""

    reference: ProviderResponsePayloadReference
    raw_payload: RawPayload

    def __post_init__(self) -> None:
        """Reject a retained row unless every reference digest still verifies."""

        if (
            type(self.reference) is not ProviderResponsePayloadReference
            or type(self.raw_payload) is not RawPayload
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RETAINED_RESPONSE_INVALID"
            )
        try:
            verified = self.reference.verifies(self.raw_payload)
        except (RecursionError, TypeError, ValueError) as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RETAINED_RESPONSE_INVALID"
            ) from exc
        if not verified:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RETAINED_RESPONSE_INVALID"
            )

    def to_provider_response_capture(self) -> ProviderResponseCapture:
        """Reconstruct the exact original response only when its body was retained."""

        if self.reference.original_body_retained is not True:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_ORIGINAL_RESPONSE_UNAVAILABLE"
            )
        try:
            verified = self.reference.verifies(self.raw_payload)
        except (RecursionError, TypeError, ValueError) as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RETAINED_RESPONSE_INVALID"
            ) from exc
        if not verified:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RETAINED_RESPONSE_INVALID"
            )
        envelope = self.raw_payload.payload
        retained_text = envelope.get("retained_response_json")
        status_code = envelope.get("status_code")
        content_type = envelope.get("content_type")
        if (
            type(retained_text) is not str
            or type(status_code) is not int
            or not 200 <= status_code < 300
            or (content_type is not None and type(content_type) is not str)
            or content_type != (self.raw_payload.content_type or None)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RETAINED_RESPONSE_INVALID"
            )
        try:
            body = retained_text.encode("utf-8")
            if (
                len(body) != self.reference.body_size_bytes
                or hashlib.sha256(body).hexdigest() != self.reference.body_sha256
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_RETAINED_RESPONSE_INVALID"
                )
            payload = parse_provider_response_json(body)
            return ProviderResponseCapture(
                body=body,
                payload=payload,
                body_sha256=self.reference.body_sha256,
                body_size_bytes=self.reference.body_size_bytes,
                response_completed_at=self.reference.response_completed_at,
                status_code=status_code,
                content_type=content_type,
                transport=self.reference.transport,
            )
        except (TypeError, ValueError) as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RETAINED_RESPONSE_INVALID"
            ) from exc


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureScopeProgress:
    """Verified progress for one scope, bound to immutable request evidence."""

    request: InstrumentReferenceCaptureRequest
    request_sha256: str
    provider_contract_hash: str
    scope: InstrumentReferenceCaptureScope
    state: CaptureScopeProgressState
    retained_response: InstrumentReferenceCaptureRetainedResponse | None = None
    occurrence: InstrumentReferenceAuditOccurrence | None = None
    receipt: InstrumentReferenceAuditOccurrenceReceipt | None = None

    def __post_init__(self) -> None:
        """Verify request, full contract, scope, response, and optional audit receipt."""

        if (
            type(self.request) is not InstrumentReferenceCaptureRequest
            or type(self.scope) is not InstrumentReferenceCaptureScope
            or self.scope not in self.request.scopes
            or type(self.state) is not CaptureScopeProgressState
            or type(self.request_sha256) is not str
            or self.request_sha256 != self.request.request_sha256
            or type(self.provider_contract_hash) is not str
            or self.provider_contract_hash != self.request.provider_contract.content_hash
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID"
            )
        if self.state is CaptureScopeProgressState.NOT_CAPTURED:
            if any(
                item is not None for item in (self.retained_response, self.occurrence, self.receipt)
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID"
                )
            return
        if (
            type(self.retained_response) is not InstrumentReferenceCaptureRetainedResponse
            or not _request_params_match_scope(
                self.retained_response.raw_payload.request_params,
                self.request,
                self.scope,
            )
            or self.retained_response.reference.provider_name
            != self.request.provider_contract.provider_name
            or self.retained_response.reference.dataset_key
            != self.request.provider_contract.dataset_key
            or self.retained_response.reference.run_id
            not in ("", str(self.request.identity.run_id))
            or self.retained_response.raw_payload.payload.get("api_name")
            != self.request.provider_contract.api_name
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID"
            )
        if self.state is CaptureScopeProgressState.RESPONSE_RETAINED:
            if self.occurrence is not None or self.receipt is not None:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID"
                )
            return
        if (
            type(self.occurrence) is not InstrumentReferenceAuditOccurrence
            or type(self.receipt) is not InstrumentReferenceAuditOccurrenceReceipt
            or type(self.receipt.raw_audit_reference) is not RawAuditReference
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID"
            )
        self._validate_audit_binding()

    def _validate_audit_binding(self) -> None:
        """Require the occurrence and receipt to identify this exact retained scope."""

        request = self.request
        scope = self.scope
        retained = self.retained_response
        occurrence = self.occurrence
        receipt = self.receipt
        if retained is None or occurrence is None or receipt is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_PROGRESS_INVALID"
            )
        contract = request.provider_contract
        raw_reference = receipt.raw_audit_reference
        expected_request_hash = _request_params_sha256(retained.raw_payload.request_params)
        if (
            retained.reference.original_body_retained is not True
            or retained.raw_payload.payload.get("api_name") != contract.api_name
            or type(occurrence.occurrence_id) is not UUID
            or occurrence.occurrence_id != request.occurrence_id(scope)
            or type(occurrence.run_id) is not UUID
            or type(occurrence.ingested_run_id) is not UUID
            or occurrence.run_id != request.identity.run_id
            or occurrence.ingested_run_id != request.identity.batch_id
            or occurrence.contract_id != contract.contract_id
            or occurrence.contract_version != contract.contract_version
            or occurrence.contract_hash != self.provider_contract_hash
            or occurrence.api_name != contract.api_name
            or occurrence.dataset_key != contract.dataset_key
            or occurrence.exchange != scope.exchange
            or occurrence.list_status != scope.list_status
            or occurrence.fields != contract.fields_csv
            or type(occurrence.row_count) is not int
            or occurrence.row_count < 0
            or type(occurrence.response_reference) is not ProviderResponsePayloadReference
            or type(occurrence.raw_payload) is not RawPayload
            or occurrence.response_reference != retained.reference
            or occurrence.raw_payload != retained.raw_payload
            or type(receipt.occurrence_id) is not UUID
            or receipt.occurrence_id != occurrence.occurrence_id
            or type(receipt.repository_alias) is not str
            or receipt.repository_alias != "default"
            or type(receipt.raw_payload_id) is not str
            or receipt.raw_payload_id != retained.reference.payload_id
            or type(receipt.raw_payload_hash) is not str
            or receipt.raw_payload_hash != retained.reference.payload_hash
            or type(receipt.response_body_sha256) is not str
            or receipt.response_body_sha256 != retained.reference.body_sha256
            or type(receipt.request_params_hash) is not str
            or receipt.request_params_hash != expected_request_hash
            or raw_reference.run_id != str(occurrence.run_id)
            or raw_reference.ingested_run_id != str(occurrence.ingested_run_id)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID"
            )

    def to_provider_response_capture(self) -> ProviderResponseCapture:
        """Return verified retained bytes without repeating a provider request."""

        if self.retained_response is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_NOT_RETAINED"
            )
        return self.retained_response.to_provider_response_capture()


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureParsedScope:
    """One parsed scope whose records all bind to its exact audit occurrence."""

    scope: InstrumentReferenceCaptureScope
    occurrence: InstrumentReferenceOccurrence
    records: tuple[InstrumentReferenceRecord, ...]

    def __post_init__(self) -> None:
        """Reject rows that do not carry the scope's occurrence and audit links."""

        if (
            type(self.scope) is not InstrumentReferenceCaptureScope
            or type(self.occurrence) is not InstrumentReferenceOccurrence
            or type(self.records) is not tuple
            or any(type(record) is not InstrumentReferenceRecord for record in self.records)
            or self.occurrence.exchange != self.scope.exchange
            or self.occurrence.list_status != self.scope.list_status
            or type(self.occurrence.row_count) is not int
            or self.occurrence.row_count < 0
            or type(self.occurrence.raw_audit_reference) is not RawAuditReference
            or len(self.records) != self.occurrence.row_count
            or any(
                record.occurrence_id != self.occurrence.occurrence_id
                or record.source_exchange != self.scope.exchange
                or record.source_list_status != self.scope.list_status
                or record.raw_audit_reference != self.occurrence.raw_audit_reference
                or record.raw_payload_id != self.occurrence.raw_payload_id
                or record.raw_payload_hash != self.occurrence.raw_payload_hash
                for record in self.records
            )
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PARSED_SCOPE_INVALID"
            )


class InstrumentReferenceCaptureScopeParserPort(Protocol):
    """Validate and parse one scope from its exact retained response and audit."""

    def build_audit_occurrence(
        self,
        request: InstrumentReferenceCaptureRequest,
        progress: InstrumentReferenceCaptureScopeProgress,
    ) -> InstrumentReferenceAuditOccurrence:
        """Build stable audit evidence from one exact, retained response.

        The implementation accepts only ``RESPONSE_RETAINED`` progress, parses
        the original body under the full request contract, and sets
        ``row_count`` to the number of successfully parsed source records. It
        must reject redacted or unsupported bodies before returning an
        occurrence. The application validates scope, request, IDs, contract,
        body reference and the non-negative integer shape before the fenced
        audit write; the concrete parser owns the actual parsed-row count.
        """

    def parse_scope(
        self,
        request: InstrumentReferenceCaptureRequest,
        progress: InstrumentReferenceCaptureScopeProgress,
    ) -> InstrumentReferenceCaptureParsedScope:
        """Use the full request contract and scope without narrowing its hash.

        Implementations require ``progress.request == request`` and a scope in
        that request, accept only ``AUDIT_COMPLETE`` progress, and parse the
        reconstructed exact retained body, not a provider refetch or redacted
        body whose original bytes are unavailable.
        """


class InstrumentReferenceCaptureSnapshotAssemblerPort(Protocol):
    """Assemble all parsed scopes into the existing complete snapshot contract."""

    def assemble_snapshot_content(
        self,
        request: InstrumentReferenceCaptureRequest,
        parsed_scopes: tuple[InstrumentReferenceCaptureParsedScope, ...],
    ) -> InstrumentReferenceSnapshotContent:
        """Require all request scopes and retain the full provider contract hash.

        The assembler must reject duplicates, omissions, and mixed mappings;
        it must not manufacture a narrower provider contract to fit one scope.
        """


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureInvocation:
    """Pair an immutable capture request with normal or explicit-resume intent."""

    request: InstrumentReferenceCaptureRequest
    mode: CaptureInvocationMode = CaptureInvocationMode.NORMAL

    def __post_init__(self) -> None:
        """Require typed values while leaving mode out of request identity."""

        if type(self.request) is not InstrumentReferenceCaptureRequest:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_INVOCATION_INVALID"
            )
        if type(self.mode) is not CaptureInvocationMode:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_INVOCATION_INVALID"
            )

    @property
    def request_sha256(self) -> str:
        """Return the immutable request digest, independent of invocation mode."""

        return self.request.request_sha256


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureLease:
    """In-memory current-owner capability bound to one validated claim epoch."""

    identity: InstrumentReferenceCaptureIdentity
    request_sha256: str
    epoch: CaptureClaimEpoch
    owner_capability: CaptureOwnerCapability = field(repr=False)

    def __post_init__(self) -> None:
        """Require the capability hash to match the safe persisted claim value."""

        if (
            type(self.identity) is not InstrumentReferenceCaptureIdentity
            or type(self.epoch) is not CaptureClaimEpoch
            or type(self.owner_capability) is not CaptureOwnerCapability
            or type(self.request_sha256) is not str
            or _SHA256.fullmatch(self.request_sha256) is None
            or self.epoch.request_sha256 != self.request_sha256
            or not self.owner_capability.matches_digest(self.epoch.owner_token_sha256)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_LEASE_INVALID"
            )


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureClaimResult:
    """Typed claim result with either one current lease or exact replay receipt."""

    disposition: CaptureClaimDisposition
    identity: InstrumentReferenceCaptureIdentity
    request_sha256: str
    lease: InstrumentReferenceCaptureLease | None = None
    snapshot: InstrumentReferenceSnapshotRecord | None = None

    def __post_init__(self) -> None:
        """Enforce mutually exclusive acquired, pending, and completed states."""

        if (
            type(self.disposition) is not CaptureClaimDisposition
            or type(self.identity) is not InstrumentReferenceCaptureIdentity
            or type(self.request_sha256) is not str
            or _SHA256.fullmatch(self.request_sha256) is None
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_RESULT_INVALID"
            )
        if self.disposition is CaptureClaimDisposition.ACQUIRED:
            if (
                type(self.lease) is not InstrumentReferenceCaptureLease
                or self.snapshot is not None
                or self.lease.identity != self.identity
                or self.lease.request_sha256 != self.request_sha256
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_RESULT_INVALID"
                )
            return
        if self.disposition is CaptureClaimDisposition.COMPLETED:
            if (
                self.lease is not None
                or type(self.snapshot) is not InstrumentReferenceSnapshotRecord
                or self.snapshot.content.run_id != self.identity.run_id
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_RESULT_INVALID"
                )
            return
        if self.lease is not None or self.snapshot is not None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_RESULT_INVALID"
            )


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureResult:
    """Outcome DTO that preserves exact source-only snapshot knowledge."""

    status: CaptureExecutionStatus
    identity: InstrumentReferenceCaptureIdentity
    request_sha256: str
    snapshot: InstrumentReferenceSnapshotRecord | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        """Require a snapshot only for completion and keep errors machine-stable."""

        if (
            type(self.status) is not CaptureExecutionStatus
            or type(self.identity) is not InstrumentReferenceCaptureIdentity
            or type(self.request_sha256) is not str
            or _SHA256.fullmatch(self.request_sha256) is None
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RESULT_INVALID"
            )
        if self.status is CaptureExecutionStatus.COMPLETED:
            if (
                type(self.snapshot) is not InstrumentReferenceSnapshotRecord
                or self.snapshot.content.run_id != self.identity.run_id
                or self.reason_code is not None
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_RESULT_INVALID"
                )
            return
        if self.snapshot is not None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RESULT_INVALID"
            )
        if self.status is CaptureExecutionStatus.BLOCKED:
            if (
                type(self.reason_code) is not str
                or not self.reason_code
                or self.reason_code != self.reason_code.strip()
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_RESULT_INVALID"
                )
        elif self.reason_code is not None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RESULT_INVALID"
            )


class InstrumentReferenceCaptureClaimPort(Protocol):
    """Atomic claim, exact replay, and current-owner fence operations."""

    def claim(
        self, invocation: InstrumentReferenceCaptureInvocation
    ) -> InstrumentReferenceCaptureClaimResult:
        """Acquire, report in-progress, require resume, or return exact completion."""

    def is_current(self, lease: InstrumentReferenceCaptureLease) -> bool:
        """Verify the lease epoch/token against the locked durable claim chain."""


class InstrumentReferenceCaptureProviderPort(Protocol):
    """Per-scope read only; persistence must go through the fenced port."""

    def fetch_scope(
        self,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> ProviderResponseCapture:
        """Fetch the requested scope without persistence side effects.

        Implementations return exact response evidence. They must not write a
        RawPayload, RawAudit, occurrence pointer, or snapshot outside the
        current fenced persistence lease. Provider composition must resolve
        the exact persisted ``request.provider_configuration_id`` and may not
        fall back to a provider-name or route-name match.
        """


class InstrumentReferenceCapturePersistencePort(Protocol):
    """Fenced persistence operations composed from existing evidence contracts."""

    def read_scope_progress(
        self,
        lease: InstrumentReferenceCaptureLease,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> InstrumentReferenceCaptureScopeProgress:
        """Read exact committed progress so a new resume epoch can reuse it.

        Progress is selected by capture/request/scope identity, never by an
        unvalidated latest pointer. Require ``lease.identity`` and
        ``lease.request_sha256`` to match this request, then verify that lease
        is current. A retained response is not bound to an older lease token: a
        new valid epoch for the same immutable request may safely continue it.
        Any write following this read must still recheck the current epoch under
        lock.
        """

    def retain_response(
        self,
        lease: InstrumentReferenceCaptureLease,
        scope: InstrumentReferenceCaptureScope,
        response: ProviderResponseCapture,
    ) -> ProviderResponsePayloadReference:
        """Atomically retain the redacted RawPayload and exact scope pointer."""

    def record_occurrence(
        self,
        lease: InstrumentReferenceCaptureLease,
        occurrence: InstrumentReferenceAuditOccurrence,
    ) -> InstrumentReferenceAuditOccurrenceReceipt:
        """Persist/read back the existing source-owned RawAudit occurrence."""

    def complete_snapshot(
        self,
        lease: InstrumentReferenceCaptureLease,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        """Atomically append the existing source-only snapshot and final pointer."""

    def get_snapshot(self, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        """Read one exact immutable snapshot through the existing evidence verifier."""


def _request_params_match_scope(
    value: object,
    request: InstrumentReferenceCaptureRequest,
    scope: InstrumentReferenceCaptureScope,
) -> bool:
    """Match one retained stock-basic request shape to the exact requested scope."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        return False
    request_params = cast(dict[str, object], value)
    contract = request.provider_contract
    rest_keys = {"exchange", "list_status", "fields"}
    api_keys = {"api_name", "fields", "params"}
    sdk_keys = {"fields", "params"}
    if set(request_params) == rest_keys:
        return (
            request_params.get("exchange") == scope.exchange
            and request_params.get("list_status") == scope.list_status
            and request_params.get("fields") == contract.fields_csv
        )
    if set(request_params) not in (api_keys, sdk_keys):
        return False
    api_name = request_params.get("api_name", contract.api_name)
    params_value = request_params.get("params")
    if type(params_value) is not dict or any(type(key) is not str for key in params_value):
        return False
    params = cast(dict[str, object], params_value)
    return (
        api_name == contract.api_name
        and request_params.get("fields") == contract.fields_csv
        and set(params) == {"exchange", "list_status"}
        and params.get("exchange") == scope.exchange
        and params.get("list_status") == scope.list_status
    )


def _request_params_sha256(value: object) -> str:
    """Hash the exact retained query parameters using existing JSON rules."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID"
        )
    try:
        encoded = canonical_provider_response_json(cast(dict[str, object], value)).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_AUDIT_BINDING_INVALID"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CaptureClaimDisposition",
    "CaptureExecutionStatus",
    "CaptureInvocationMode",
    "CaptureScopeProgressState",
    "InstrumentReferenceCaptureClaimPort",
    "InstrumentReferenceCaptureClaimResult",
    "InstrumentReferenceCaptureInvocation",
    "InstrumentReferenceCaptureLease",
    "InstrumentReferenceCapturePersistencePort",
    "InstrumentReferenceCaptureProviderPort",
    "InstrumentReferenceCaptureParsedScope",
    "InstrumentReferenceCaptureResult",
    "InstrumentReferenceCaptureRetainedResponse",
    "InstrumentReferenceCaptureScopeParserPort",
    "InstrumentReferenceCaptureScopeProgress",
    "InstrumentReferenceCaptureSnapshotAssemblerPort",
]
