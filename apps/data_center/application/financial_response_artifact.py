"""Application ports and use case for retained financial response evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_response_artifact import (
    FinancialResponseArtifact,
    FinancialResponseArtifactRef,
)
from apps.data_center.domain.financial_response_evidence import FinancialResponseEvidence
from apps.data_center.domain.financial_response_failure import (
    FINANCIAL_RESPONSE_FAILURE_CAPABILITY,
    FINANCIAL_RESPONSE_FAILURE_LINK_KEY,
    FINANCIAL_RESPONSE_FAILURE_LINK_SCHEMA,
    FINANCIAL_RESPONSE_FAILURE_PARSER_VERSION,
    FINANCIAL_RESPONSE_FAILURE_STATUS,
    FinancialResponseFailure,
)
from core.exceptions import DataFetchError


class FinancialResponseBodyStorePort(Protocol):
    """Store and retrieve immutable encrypted response artifacts."""

    def store(self, artifact: FinancialResponseArtifact) -> FinancialResponseArtifactRef:
        """Persist one exact response body and return its opaque reference."""
        ...

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        """Read and independently verify the exact body for a reference."""
        ...

    def inspect(self, reference: FinancialResponseArtifactRef) -> FinancialResponseArtifactRef:
        """Validate an artifact envelope without returning its body."""
        ...


class FinancialResponseArtifactAuditPort(Protocol):
    """Persist and find audit rows bound to one captured response."""

    def log(self, audit: RawAudit) -> RawAudit:
        """Append one redacted audit row."""
        ...

    def find_by_artifact_capture_id(self, capture_id: UUID) -> RawAudit | None:
        """Return an existing audit row bound to one capture UUID."""
        ...


class FinancialResponseFailureAuditPort(FinancialResponseArtifactAuditPort, Protocol):
    """Persist and find provider-rejected response audit rows separately."""

    def log_failure(self, audit: RawAudit) -> RawAudit:
        """Append one redacted failure audit row."""
        ...

    def find_by_failure_capture_id(self, capture_id: UUID) -> RawAudit | None:
        """Return an existing failure row bound to one capture UUID."""
        ...


@dataclass(frozen=True, slots=True)
class FinancialResponseArtifactRetention:
    """Result of storing one exact body and its redacted audit link."""

    reference: FinancialResponseArtifactRef
    audit: RawAudit


@dataclass(frozen=True, slots=True)
class RetainedFinancialResponsePayload:
    """Carry a decoded provider payload with its exact retained body reference."""

    payload: object
    reference: FinancialResponseArtifactRef

    def __post_init__(self) -> None:
        """Reject an untyped artifact reference at the transport boundary."""

        if not isinstance(self.reference, FinancialResponseArtifactRef):
            raise ValueError("retained financial response reference must be typed")


class FinancialResponseArtifactAuditError(DataFetchError):
    """Raised when an encrypted body exists but its audit link was not committed."""

    default_message = "金融响应原件审计链接写入失败。"
    default_code = "FINANCIAL_RESPONSE_ARTIFACT_AUDIT_FAILED"

    def __init__(self, reference: FinancialResponseArtifactRef) -> None:
        """Keep the opaque reference available for orphan reconciliation."""

        self.reference = reference
        super().__init__(
            self.default_message,
            code=self.default_code,
            details={
                "capture_id": str(reference.capture_id),
                "location": reference.location,
                "body_sha256": reference.body_sha256,
            },
        )


class FinancialResponseArtifactAuditLookupError(DataFetchError):
    """Raised when the audit port cannot establish replay state."""

    default_message = "金融响应原件审计状态读取失败。"
    default_code = "FINANCIAL_RESPONSE_ARTIFACT_AUDIT_LOOKUP_FAILED"


class FinancialResponseArtifactOutcomeConflictError(DataFetchError):
    """Raised when one capture UUID is reused across success and failure outcomes."""

    default_message = "金融响应捕获标识已绑定其他结果。"
    default_code = "FINANCIAL_RESPONSE_ARTIFACT_OUTCOME_CONFLICT"


class FinancialResponseFailureAuditLookupError(FinancialResponseArtifactAuditLookupError):
    """Raised when a rejected-response audit lookup cannot establish replay state."""

    default_message = "金融响应失败原件审计状态读取失败。"
    default_code = "FINANCIAL_RESPONSE_FAILURE_AUDIT_LOOKUP_FAILED"


class FinancialResponseFailureAuditError(DataFetchError):
    """Raised when a rejected body exists but its failure audit link was not committed."""

    default_message = "金融响应失败原件审计链接写入失败。"
    default_code = "FINANCIAL_RESPONSE_FAILURE_AUDIT_FAILED"

    def __init__(
        self,
        reference: FinancialResponseArtifactRef,
        *,
        failure_code: str = "",
    ) -> None:
        """Keep only an opaque reference for later orphan reconciliation."""

        self.reference = reference
        super().__init__(
            self.default_message,
            code=self.default_code,
            details={
                "capture_id": str(reference.capture_id),
                "location": reference.location,
                "body_sha256": reference.body_sha256,
                "failure_code": failure_code,
            },
        )


class RetainFinancialResponseArtifactUseCase:
    """Coordinate an immutable body with its redacted RawAudit link."""

    def __init__(
        self,
        body_store: FinancialResponseBodyStorePort,
        audit_repository: FinancialResponseArtifactAuditPort,
        *,
        failure_audit_repository: FinancialResponseFailureAuditPort | None = None,
    ) -> None:
        """Inject storage and audit ports without importing infrastructure."""

        self._body_store = body_store
        self._audit_repository = audit_repository
        self._failure_audit_repository = failure_audit_repository

    def execute(
        self,
        *,
        capture_id: UUID,
        evidence: FinancialResponseEvidence,
        body: bytes,
        provider_name: str,
        request_params: Mapping[str, object],
        row_count: int = 0,
        provider_id: int | None = None,
    ) -> FinancialResponseArtifactRetention:
        """Store exact bytes, then append one versioned and redacted audit link.

        The body digest is independently validated by the Domain artifact and
        the encrypted store.  Parsed JSON is intentionally not reserialized or
        used as a replacement hash.  If audit persistence fails after the file
        is published, the raised error retains the opaque reference so an
        operator can identify the orphan without deleting it implicitly.
        """

        normalized_provider = _required_text(provider_name, "provider_name", 128)
        if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
            raise ValueError("financial artifact row_count must be non-negative")
        safe_params = _safe_request_params(request_params)
        artifact = FinancialResponseArtifact(
            capture_id=capture_id,
            evidence=evidence,
            body=body,
        )
        try:
            if self._failure_audit_repository is not None:
                existing_failure = self._failure_audit_repository.find_by_failure_capture_id(
                    capture_id
                )
                if existing_failure is not None:
                    raise FinancialResponseArtifactOutcomeConflictError()
            existing_audit = self._audit_repository.find_by_artifact_capture_id(capture_id)
        except Exception as exc:
            if isinstance(exc, FinancialResponseArtifactOutcomeConflictError):
                raise
            raise FinancialResponseArtifactAuditLookupError() from exc

        reference = self._body_store.store(artifact)
        expected_link = {
            "schema": "financial-response-artifact-link.v1",
            **reference.to_dict(),
            "provider_id": provider_id,
        }
        expected_extra = {"financial_response_artifact": expected_link}
        if existing_audit is not None:
            if not _artifact_audit_matches(
                existing_audit,
                provider_name=normalized_provider,
                request_params=safe_params,
                evidence=evidence,
                row_count=row_count,
                expected_extra=expected_extra,
            ):
                raise ValueError("financial artifact replay metadata conflicts")
            return FinancialResponseArtifactRetention(reference, existing_audit)

        audit = RawAudit(
            provider_name=normalized_provider,
            capability="financial",
            request_params=safe_params,
            status="ok",
            row_count=row_count,
            fetched_at=evidence.response_completed_at,
            extra=expected_extra,
            request_params_hash=_mapping_sha256(safe_params),
            response_payload_hash="",
            schema_fingerprint="",
            redacted=True,
            parser_version="financial-response-artifact.v1",
            payload_size_bytes=evidence.body_size_bytes,
        )
        try:
            persisted = self._audit_repository.log(audit)
        except Exception as exc:
            raise FinancialResponseArtifactAuditError(reference) from exc
        return FinancialResponseArtifactRetention(reference, persisted)


@dataclass(frozen=True, slots=True)
class FinancialResponseFailureRetention:
    """Result of storing one rejected body and its redacted failure audit link."""

    reference: FinancialResponseArtifactRef
    audit: RawAudit


class RetainFinancialResponseFailureUseCase:
    """Coordinate an encrypted rejected body with a distinct error audit row."""

    def __init__(
        self,
        body_store: FinancialResponseBodyStorePort,
        audit_repository: FinancialResponseFailureAuditPort,
    ) -> None:
        """Inject the shared body store and typed success/failure audit port."""

        self._body_store = body_store
        self._audit_repository = audit_repository

    def execute(
        self,
        *,
        capture_id: UUID,
        evidence: FinancialResponseEvidence,
        body: bytes,
        provider_name: str,
        request_params: Mapping[str, object],
        failure_code: str,
        provider_id: int | None = None,
    ) -> FinancialResponseFailureRetention:
        """Store exact rejected bytes without creating a successful audit or fact."""

        normalized_provider = _required_text(provider_name, "provider_name", 128)
        if normalized_provider != evidence.request_scope.provider_name:
            raise ValueError("financial failure provider does not match evidence")
        safe_params = _safe_request_params(request_params)
        failure = FinancialResponseFailure(
            capture_id=capture_id,
            evidence=evidence,
            body=body,
            failure_code=failure_code,
        )
        try:
            existing_success = self._audit_repository.find_by_artifact_capture_id(capture_id)
            existing_failure = self._audit_repository.find_by_failure_capture_id(capture_id)
        except Exception as exc:
            raise FinancialResponseFailureAuditLookupError() from exc
        if existing_success is not None:
            raise FinancialResponseArtifactOutcomeConflictError()

        reference = self._body_store.store(failure.as_artifact())
        expected_link = _failure_link(
            reference,
            failure_code=failure.failure_code,
            provider_id=provider_id,
        )
        if existing_failure is not None:
            if (
                existing_failure.capability != FINANCIAL_RESPONSE_FAILURE_CAPABILITY
                or existing_failure.status != FINANCIAL_RESPONSE_FAILURE_STATUS
            ):
                raise FinancialResponseArtifactOutcomeConflictError()
            existing_link = existing_failure.extra.get(FINANCIAL_RESPONSE_FAILURE_LINK_KEY)
            if not isinstance(existing_link, Mapping) or dict(existing_link) != expected_link:
                raise FinancialResponseArtifactOutcomeConflictError()
            if not _failure_audit_matches(
                existing_failure,
                provider_name=normalized_provider,
                request_params=safe_params,
                evidence=evidence,
                failure_code=failure.failure_code,
                expected_extra={FINANCIAL_RESPONSE_FAILURE_LINK_KEY: expected_link},
            ):
                raise FinancialResponseArtifactOutcomeConflictError()
            return FinancialResponseFailureRetention(reference, existing_failure)

        audit = RawAudit(
            provider_name=normalized_provider,
            capability=FINANCIAL_RESPONSE_FAILURE_CAPABILITY,
            request_params=safe_params,
            status=FINANCIAL_RESPONSE_FAILURE_STATUS,
            row_count=0,
            error_message=failure.failure_code,
            fetched_at=evidence.response_completed_at,
            extra={FINANCIAL_RESPONSE_FAILURE_LINK_KEY: expected_link},
            request_params_hash=_mapping_sha256(safe_params),
            response_payload_hash="",
            schema_fingerprint="",
            redacted=True,
            parser_version=FINANCIAL_RESPONSE_FAILURE_PARSER_VERSION,
            payload_size_bytes=evidence.body_size_bytes,
        )
        try:
            persisted = self._audit_repository.log_failure(audit)
        except Exception as exc:
            raise FinancialResponseFailureAuditError(
                reference,
                failure_code=failure.failure_code,
            ) from exc
        return FinancialResponseFailureRetention(reference, persisted)


def _failure_link(
    reference: FinancialResponseArtifactRef,
    *,
    failure_code: str,
    provider_id: int | None,
) -> dict[str, object]:
    """Build an allowlisted failure link without provider body or message text."""

    return {
        "schema": FINANCIAL_RESPONSE_FAILURE_LINK_SCHEMA,
        **reference.to_dict(),
        "provider_id": provider_id,
        "failure_code": failure_code,
    }


def _artifact_audit_matches(
    audit: RawAudit,
    *,
    provider_name: str,
    request_params: dict[str, object],
    evidence: FinancialResponseEvidence,
    row_count: int,
    expected_extra: Mapping[str, object],
) -> bool:
    """Require a replay to match the complete successful audit projection."""

    return (
        audit.capability == "financial"
        and audit.status == "ok"
        and audit.provider_name == provider_name
        and audit.request_params == request_params
        and audit.request_params_hash == _mapping_sha256(request_params)
        and audit.error_message == ""
        and audit.fetched_at == evidence.response_completed_at
        and audit.extra == expected_extra
        and audit.row_count == row_count
        and audit.latency_ms is None
        and audit.response_payload_hash == ""
        and audit.schema_fingerprint == ""
        and audit.redacted is True
        and audit.parser_version == "financial-response-artifact.v1"
        and audit.payload_size_bytes == evidence.body_size_bytes
        and audit.retention_until is None
        and audit.run_id == ""
        and audit.ingested_run_id == ""
        and _content_hash_matches(audit)
    )


def _failure_audit_matches(
    audit: RawAudit,
    *,
    provider_name: str,
    request_params: dict[str, object],
    evidence: FinancialResponseEvidence,
    failure_code: str,
    expected_extra: Mapping[str, object],
) -> bool:
    """Require every immutable failure-audit projection to match a replay."""

    return (
        audit.capability == FINANCIAL_RESPONSE_FAILURE_CAPABILITY
        and audit.status == FINANCIAL_RESPONSE_FAILURE_STATUS
        and audit.provider_name == provider_name
        and audit.request_params == request_params
        and audit.request_params_hash == _mapping_sha256(request_params)
        and audit.error_message == failure_code
        and audit.fetched_at == evidence.response_completed_at
        and audit.extra == expected_extra
        and audit.row_count == 0
        and audit.latency_ms is None
        and audit.response_payload_hash == ""
        and audit.schema_fingerprint == ""
        and audit.redacted is True
        and audit.parser_version == FINANCIAL_RESPONSE_FAILURE_PARSER_VERSION
        and audit.payload_size_bytes == evidence.body_size_bytes
        and audit.retention_until is None
        and audit.run_id == ""
        and audit.ingested_run_id == ""
        and _content_hash_matches(audit)
    )


def _content_hash_matches(audit: RawAudit) -> bool:
    """Verify supplied hashes while supporting legacy unhashed audit records."""

    return not audit.content_hash or audit.content_hash == raw_audit_content_hash(audit)


def _required_text(value: object, field_name: str, max_length: int) -> str:
    """Validate a bounded text value without silently stripping it."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    if len(value) > max_length or any(ord(char) < 32 for char in value):
        raise ValueError(f"{field_name} is invalid")
    return value


_SECRET_KEY_MARKERS = frozenset(
    {"token", "authorization", "password", "secret", "api_key", "apikey", "cookie"}
)


def _safe_request_params(value: Mapping[str, object]) -> dict[str, object]:
    """Copy JSON-safe request dimensions while rejecting credential-shaped keys."""

    if not isinstance(value, Mapping):
        raise ValueError("financial artifact request_params must be an object")
    return {str(key): _safe_json_value(item, str(key)) for key, item in value.items()}


def _safe_json_value(value: object, field_name: str) -> object:
    """Narrow one audit parameter without persisting headers or credentials."""

    lowered = field_name.casefold()
    if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
        raise ValueError("financial artifact request contains credential-shaped data")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("financial artifact request contains non-finite number")
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe_json_value(item, str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(item, field_name) for item in value]
    raise ValueError("financial artifact request contains unsupported value")


def _mapping_sha256(value: Mapping[str, object]) -> str:
    """Hash only the redacted request projection for the existing audit field."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("financial artifact request is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FinancialResponseArtifactAuditError",
    "FinancialResponseArtifactAuditLookupError",
    "FinancialResponseArtifactOutcomeConflictError",
    "FinancialResponseArtifactAuditPort",
    "FinancialResponseArtifactRetention",
    "FinancialResponseBodyStorePort",
    "FinancialResponseFailureAuditError",
    "FinancialResponseFailureAuditLookupError",
    "FinancialResponseFailureAuditPort",
    "FinancialResponseFailureRetention",
    "RetainedFinancialResponsePayload",
    "RetainFinancialResponseArtifactUseCase",
    "RetainFinancialResponseFailureUseCase",
]
