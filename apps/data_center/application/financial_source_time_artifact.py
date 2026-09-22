"""Contract-neutral retention for provider-native financial source-time bodies."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_source_time_evidence import (
    FinancialSourceTimeArtifactRef,
)
from core.exceptions import DataFetchError

SOURCE_TIME_AUDIT_CAPABILITY = "financial_source_time"
SOURCE_TIME_AUDIT_LINK_KEY = "financial_source_time_artifact"
SOURCE_TIME_AUDIT_LINK_SCHEMA = "financial-source-time-artifact-link.v1"


class FinancialSourceTimeBodyStorePort(Protocol):
    """Store and verify one immutable provider-native source-time body."""

    def store(
        self,
        reference: FinancialSourceTimeArtifactRef,
        body: bytes,
    ) -> FinancialSourceTimeArtifactRef:
        """Persist exact bytes under the precomputed typed reference."""

    def read(self, reference: FinancialSourceTimeArtifactRef) -> bytes:
        """Read the exact authenticated body."""

    def inspect(
        self,
        reference: FinancialSourceTimeArtifactRef,
    ) -> FinancialSourceTimeArtifactRef:
        """Verify the authenticated envelope without returning its body."""


class FinancialSourceTimeArtifactAuditPort(Protocol):
    """Append and list source-time audit rows by immutable capture UUID."""

    def log_source_time(self, audit: RawAudit) -> RawAudit:
        """Append one canonical financial-source-time audit row."""

    def list_by_source_time_artifact_capture_id(
        self,
        capture_id: UUID,
    ) -> Sequence[RawAudit]:
        """Return every matching row so cardinality cannot be truncated."""


@dataclass(frozen=True, slots=True)
class FinancialSourceTimeArtifactRetention:
    """Bind one retained source-time body to its canonical audit row."""

    reference: FinancialSourceTimeArtifactRef
    audit: RawAudit


@dataclass(frozen=True, slots=True)
class FinancialSourceTimeArtifactOrphan:
    """Expose body/audit reconciliation without returning provider bytes."""

    reference: FinancialSourceTimeArtifactRef
    audits: tuple[RawAudit, ...]
    body_verified: bool

    @property
    def audit_count(self) -> int:
        """Return the complete number of matching audit rows."""

        return len(self.audits)

    @property
    def is_orphan(self) -> bool:
        """Return whether a verified body has no audit row."""

        return self.body_verified and not self.audits

    @property
    def is_ambiguous(self) -> bool:
        """Return whether more than one audit claims the capture UUID."""

        return len(self.audits) > 1

    def to_dict(self) -> dict[str, object]:
        """Return bounded reconciliation metadata without provider content."""

        return {
            "capture_id": str(self.reference.capture_id),
            "body_verified": self.body_verified,
            "audit_count": self.audit_count,
            "is_orphan": self.is_orphan,
            "is_ambiguous": self.is_ambiguous,
            "reference": self.reference.to_dict(),
        }


class FinancialSourceTimeArtifactAuditError(DataFetchError):
    """Raised when a retained body cannot acquire its audit link."""

    default_message = "财务来源时间原件审计链接写入失败。"
    default_code = "FINANCIAL_SOURCE_TIME_ARTIFACT_AUDIT_FAILED"

    def __init__(self, reference: FinancialSourceTimeArtifactRef) -> None:
        """Expose only the opaque body identity for orphan reconciliation."""

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


class FinancialSourceTimeArtifactAuditLookupError(DataFetchError):
    """Raised when exact replay state cannot be established before storage."""

    default_message = "财务来源时间原件审计状态读取失败。"
    default_code = "FINANCIAL_SOURCE_TIME_ARTIFACT_AUDIT_LOOKUP_FAILED"


class FinancialSourceTimeArtifactReplayConflictError(DataFetchError):
    """Raised when one capture UUID has ambiguous or changed audit metadata."""

    default_message = "财务来源时间原件重放信息冲突。"
    default_code = "FINANCIAL_SOURCE_TIME_ARTIFACT_REPLAY_CONFLICT"


class RetainFinancialSourceTimeArtifactUseCase:
    """Store exact source-time bytes without interpreting their time semantics."""

    def __init__(
        self,
        body_store: FinancialSourceTimeBodyStorePort,
        audit_repository: FinancialSourceTimeArtifactAuditPort,
    ) -> None:
        """Inject storage and audit ports without importing infrastructure."""

        self._body_store = body_store
        self._audit_repository = audit_repository

    def execute(
        self,
        *,
        reference: FinancialSourceTimeArtifactRef,
        body: bytes,
        provider_id: int,
        request_params: Mapping[str, object],
        parser_version: str,
    ) -> FinancialSourceTimeArtifactRetention:
        """Retain one body and exact audit link, replaying only identical evidence."""

        if not isinstance(reference, FinancialSourceTimeArtifactRef):
            raise ValueError("financial source-time reference must be typed")
        if isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0:
            raise ValueError("financial source-time provider_id must be positive")
        normalized_parser = _required_text(parser_version, "parser_version", 128)
        safe_params = _safe_request_params(request_params)
        expected_extra = {
            SOURCE_TIME_AUDIT_LINK_KEY: {
                "schema": SOURCE_TIME_AUDIT_LINK_SCHEMA,
                **reference.to_dict(),
                "provider_id": provider_id,
            }
        }
        try:
            existing = tuple(
                self._audit_repository.list_by_source_time_artifact_capture_id(reference.capture_id)
            )
        except Exception as exc:
            raise FinancialSourceTimeArtifactAuditLookupError() from exc
        if len(existing) > 1:
            raise FinancialSourceTimeArtifactReplayConflictError()

        stored = self._body_store.store(reference, body)
        if len(existing) == 1:
            audit = existing[0]
            if not _audit_matches(
                audit,
                reference=stored,
                request_params=safe_params,
                parser_version=normalized_parser,
                expected_extra=expected_extra,
            ):
                raise FinancialSourceTimeArtifactReplayConflictError()
            return FinancialSourceTimeArtifactRetention(stored, audit)

        audit = RawAudit(
            provider_name=stored.provider_name,
            capability=SOURCE_TIME_AUDIT_CAPABILITY,
            request_params=safe_params,
            status="ok",
            row_count=stored.response_row_count,
            fetched_at=stored.response_completed_at,
            extra=expected_extra,
            request_params_hash=_mapping_sha256(safe_params),
            response_payload_hash=stored.body_sha256,
            schema_fingerprint="",
            redacted=True,
            parser_version=normalized_parser,
            payload_size_bytes=stored.body_size_bytes,
        )
        try:
            persisted = self._audit_repository.log_source_time(audit)
        except Exception as exc:
            raise FinancialSourceTimeArtifactAuditError(stored) from exc
        if not _audit_matches(
            persisted,
            reference=stored,
            request_params=safe_params,
            parser_version=normalized_parser,
            expected_extra=expected_extra,
        ):
            raise FinancialSourceTimeArtifactAuditError(stored)
        return FinancialSourceTimeArtifactRetention(stored, persisted)

    def inspect_orphan(
        self,
        reference: FinancialSourceTimeArtifactRef,
    ) -> FinancialSourceTimeArtifactOrphan:
        """Verify one body and expose zero, one, or ambiguous audit cardinality."""

        body_verified = False
        inspected = reference
        try:
            inspected = self._body_store.inspect(reference)
            body_verified = inspected == reference
        except (DataFetchError, OSError, TypeError, ValueError):
            pass
        try:
            audits = tuple(
                self._audit_repository.list_by_source_time_artifact_capture_id(reference.capture_id)
            )
        except Exception as exc:
            raise FinancialSourceTimeArtifactAuditLookupError() from exc
        return FinancialSourceTimeArtifactOrphan(
            reference=inspected,
            audits=audits,
            body_verified=body_verified,
        )


def _audit_matches(
    audit: RawAudit,
    *,
    reference: FinancialSourceTimeArtifactRef,
    request_params: Mapping[str, object],
    parser_version: str,
    expected_extra: Mapping[str, object],
) -> bool:
    """Require every immutable audit projection to match an exact replay."""

    return (
        isinstance(audit, RawAudit)
        and audit.capability == SOURCE_TIME_AUDIT_CAPABILITY
        and audit.status == "ok"
        and audit.provider_name == reference.provider_name
        and audit.request_params == request_params
        and audit.request_params_hash == _mapping_sha256(request_params)
        and audit.error_message == ""
        and audit.fetched_at == reference.response_completed_at
        and audit.extra == expected_extra
        and audit.row_count == reference.response_row_count
        and audit.latency_ms is None
        and audit.response_payload_hash == reference.body_sha256
        and audit.schema_fingerprint == ""
        and audit.redacted is True
        and audit.parser_version == parser_version
        and audit.payload_size_bytes == reference.body_size_bytes
        and audit.retention_until is None
        and audit.run_id == ""
        and audit.ingested_run_id == ""
        and bool(audit.content_hash)
        and audit.content_hash == raw_audit_content_hash(audit)
    )


def _required_text(value: object, field_name: str, max_length: int) -> str:
    """Validate bounded canonical text without silent normalization."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"financial source-time {field_name} must be non-empty text")
    if len(value) > max_length or any(ord(character) < 32 for character in value):
        raise ValueError(f"financial source-time {field_name} is invalid")
    return value


_SECRET_KEY_MARKERS = frozenset(
    {"token", "authorization", "password", "secret", "api_key", "apikey", "cookie"}
)


def _safe_request_params(value: Mapping[str, object]) -> dict[str, object]:
    """Copy JSON-safe request dimensions while rejecting credential-shaped keys."""

    if not isinstance(value, Mapping):
        raise ValueError("financial source-time request_params must be an object")
    return {str(key): _safe_json_value(item, str(key)) for key, item in value.items()}


def _safe_json_value(value: object, field_name: str) -> object:
    """Narrow one redacted audit parameter to canonical JSON values."""

    lowered = field_name.casefold()
    if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
        raise ValueError("financial source-time request contains credential-shaped data")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("financial source-time request contains non-finite number")
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe_json_value(item, str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(item, field_name) for item in value]
    raise ValueError("financial source-time request contains unsupported value")


def _mapping_sha256(value: Mapping[str, object]) -> str:
    """Hash the exact redacted request projection."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("financial source-time request is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "SOURCE_TIME_AUDIT_CAPABILITY",
    "SOURCE_TIME_AUDIT_LINK_KEY",
    "SOURCE_TIME_AUDIT_LINK_SCHEMA",
    "FinancialSourceTimeArtifactAuditError",
    "FinancialSourceTimeArtifactAuditLookupError",
    "FinancialSourceTimeArtifactAuditPort",
    "FinancialSourceTimeArtifactOrphan",
    "FinancialSourceTimeArtifactReplayConflictError",
    "FinancialSourceTimeArtifactRetention",
    "FinancialSourceTimeBodyStorePort",
    "RetainFinancialSourceTimeArtifactUseCase",
]
