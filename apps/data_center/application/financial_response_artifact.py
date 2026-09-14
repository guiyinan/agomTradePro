"""Application ports and use case for retained financial response evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.financial_response_artifact import (
    FinancialResponseArtifact,
    FinancialResponseArtifactRef,
)
from apps.data_center.domain.financial_response_evidence import FinancialResponseEvidence
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


@dataclass(frozen=True, slots=True)
class FinancialResponseArtifactRetention:
    """Result of storing one exact body and its redacted audit link."""

    reference: FinancialResponseArtifactRef
    audit: RawAudit


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


class RetainFinancialResponseArtifactUseCase:
    """Coordinate an immutable body with its redacted RawAudit link."""

    def __init__(
        self,
        body_store: FinancialResponseBodyStorePort,
        audit_repository: FinancialResponseArtifactAuditPort,
    ) -> None:
        """Inject storage and audit ports without importing infrastructure."""

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
            existing_audit = self._audit_repository.find_by_artifact_capture_id(capture_id)
        except Exception as exc:
            raise FinancialResponseArtifactAuditLookupError() from exc

        reference = self._body_store.store(artifact)
        expected_link = {
            "schema": "financial-response-artifact-link.v1",
            **reference.to_dict(),
            "provider_id": provider_id,
        }
        if existing_audit is not None:
            existing_link = existing_audit.extra.get("financial_response_artifact")
            if not isinstance(existing_link, Mapping) or dict(existing_link) != expected_link:
                raise ValueError("financial artifact replay metadata conflicts")
            return FinancialResponseArtifactRetention(reference, existing_audit)

        audit = RawAudit(
            provider_name=normalized_provider,
            capability="financial",
            request_params=safe_params,
            status="ok",
            row_count=row_count,
            fetched_at=evidence.response_completed_at,
            extra={
                "financial_response_artifact": {
                    "schema": "financial-response-artifact-link.v1",
                    **reference.to_dict(),
                    "provider_id": provider_id,
                }
            },
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
    "FinancialResponseArtifactAuditPort",
    "FinancialResponseArtifactRetention",
    "FinancialResponseBodyStorePort",
    "RetainFinancialResponseArtifactUseCase",
]
