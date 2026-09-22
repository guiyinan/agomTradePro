"""Exact RawAudit readers and typed link validation for source-time evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import TypeGuard
from uuid import UUID

from apps.data_center.application.financial_source_time_artifact import (
    SOURCE_TIME_AUDIT_CAPABILITY,
    SOURCE_TIME_AUDIT_LINK_KEY,
    SOURCE_TIME_AUDIT_LINK_SCHEMA,
)
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_source_time_evidence import FinancialSourceTimeArtifactRef
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    reference_from_audit,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository

_SOURCE_TIME_LINK_KEYS = frozenset(
    {
        "schema",
        "capture_id",
        "location",
        "provider_name",
        "dataset_key",
        "requested_asset_code",
        "requested_announcement_date",
        "body_sha256",
        "body_size_bytes",
        "response_completed_at",
        "response_row_count",
        "format_version",
        "encryption_algorithm",
        "encryption_key_ref",
        "encryption_key_version",
        "provider_id",
    }
)


class DjangoFinancialSourceTimeAuditReader:
    """Expose non-truncated audit queries through the Application verifier port."""

    def __init__(self, repository: RawAuditRepository) -> None:
        """Bind the canonical raw-audit repository."""

        self._repository = repository

    def list_financial(self, capture_id: UUID) -> Sequence[RawAudit]:
        """Return every financial-response audit with this capture identity."""

        return self._repository.list_by_artifact_capture_id(capture_id)

    def list_source_time(self, capture_id: UUID) -> Sequence[RawAudit]:
        """Return every source-time audit with this capture identity."""

        return self._repository.list_by_source_time_artifact_capture_id(capture_id)


class StrictFinancialSourceTimeAuditLinkVerifier:
    """Decode both audit links and require exact typed reference equality."""

    def __init__(self, *, expected_provider_id: int | None = None) -> None:
        """Optionally bind both links to the active provider row identity."""

        if expected_provider_id is not None and not _positive_int(expected_provider_id):
            raise ValueError("expected_provider_id must be a positive integer")
        self._expected_provider_id = expected_provider_id

    def verify_financial(
        self,
        audit: RawAudit,
        reference: FinancialResponseArtifactRef,
    ) -> int | None:
        """Return the exact financial-link provider id, or ``None``."""

        raw_link = audit.extra.get("financial_response_artifact")
        if not isinstance(raw_link, Mapping):
            return None
        provider_id = raw_link.get("provider_id")
        if not _positive_int(provider_id):
            return None
        if self._expected_provider_id is not None and provider_id != self._expected_provider_id:
            return None
        return provider_id if reference_from_audit(audit) == reference else None

    def verify_source_time(
        self,
        audit: RawAudit,
        reference: FinancialSourceTimeArtifactRef,
    ) -> int | None:
        """Return the exact source-time-link provider id, or ``None``."""

        try:
            decoded, provider_id = source_time_reference_from_audit(audit)
        except (KeyError, TypeError, ValueError):
            return None
        valid = (
            decoded == reference
            and (self._expected_provider_id is None or provider_id == self._expected_provider_id)
            and audit.response_payload_hash == reference.body_sha256
        )
        return provider_id if valid else None


def source_time_reference_from_audit(
    audit: RawAudit,
) -> tuple[FinancialSourceTimeArtifactRef, int]:
    """Decode one exact successful source-time audit reference and provider id."""

    if audit.capability != SOURCE_TIME_AUDIT_CAPABILITY or audit.status != "ok":
        raise ValueError("financial source-time audit outcome is invalid")
    raw_link = audit.extra.get(SOURCE_TIME_AUDIT_LINK_KEY)
    if not isinstance(raw_link, Mapping) or frozenset(raw_link) != _SOURCE_TIME_LINK_KEYS:
        raise ValueError("financial source-time audit link keys are invalid")
    if raw_link.get("schema") != SOURCE_TIME_AUDIT_LINK_SCHEMA:
        raise ValueError("financial source-time audit link schema is invalid")
    provider_id = raw_link.get("provider_id")
    if not _positive_int(provider_id):
        raise ValueError("financial source-time audit provider is invalid")
    reference = FinancialSourceTimeArtifactRef(
        capture_id=UUID(_text(raw_link, "capture_id")),
        location=_text(raw_link, "location"),
        provider_name=_text(raw_link, "provider_name"),
        dataset_key=_text(raw_link, "dataset_key"),
        requested_asset_code=_text(raw_link, "requested_asset_code"),
        requested_announcement_date=date.fromisoformat(
            _text(raw_link, "requested_announcement_date")
        ),
        body_sha256=_text(raw_link, "body_sha256"),
        body_size_bytes=_integer(raw_link, "body_size_bytes"),
        response_completed_at=datetime.fromisoformat(_text(raw_link, "response_completed_at")),
        response_row_count=_integer(raw_link, "response_row_count"),
        format_version=_text(raw_link, "format_version"),
        encryption_algorithm=_text(raw_link, "encryption_algorithm"),
        encryption_key_ref=_text(raw_link, "encryption_key_ref"),
        encryption_key_version=_text(raw_link, "encryption_key_version"),
    )
    return reference, int(provider_id)


def _text(value: Mapping[object, object], key: str) -> str:
    """Narrow one audit-link field to text without coercion."""

    item = value[key]
    if not isinstance(item, str):
        raise ValueError(f"financial source-time audit {key} must be text")
    return item


def _integer(value: Mapping[object, object], key: str) -> int:
    """Narrow one audit-link field to an integer without accepting booleans."""

    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"financial source-time audit {key} must be an integer")
    return item


def _positive_int(value: object) -> TypeGuard[int]:
    """Return whether a value is a strict positive integer."""

    return not isinstance(value, bool) and isinstance(value, int) and value > 0


__all__ = [
    "SOURCE_TIME_AUDIT_LINK_KEY",
    "SOURCE_TIME_AUDIT_LINK_SCHEMA",
    "DjangoFinancialSourceTimeAuditReader",
    "StrictFinancialSourceTimeAuditLinkVerifier",
    "source_time_reference_from_audit",
]
