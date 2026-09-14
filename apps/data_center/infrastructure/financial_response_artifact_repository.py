"""Infrastructure adapter for retained financial response artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from apps.data_center.application.financial_response_artifact import (
    FinancialResponseArtifactAuditPort,
    FinancialResponseArtifactRetention,
    RetainFinancialResponseArtifactUseCase,
)
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import FinancialResponseEvidence
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseArtifactError,
    FinancialResponseBodyStore,
    _reference_from_metadata,
)

_AUDIT_LINK_KEYS = frozenset(
    {
        "schema",
        "capture_id",
        "location",
        "format_version",
        "encryption_algorithm",
        "encryption_key_ref",
        "encryption_key_version",
        "evidence_basis",
        "body_sha256",
        "body_size_bytes",
        "response_completed_at",
        "request_scope",
        "response_scope",
        "response_scope_basis",
        "body_scope",
        "provider_id",
    }
)


@dataclass(frozen=True, slots=True)
class FinancialResponseArtifactOrphan:
    """Result of checking whether a stored body has its audit link."""

    reference: FinancialResponseArtifactRef
    audit: RawAudit | None
    body_verified: bool

    @property
    def is_orphan(self) -> bool:
        """Return whether a verified body has no corresponding audit row."""

        return self.body_verified and self.audit is None

    def to_dict(self) -> dict[str, object]:
        """Return bounded reconciliation metadata without the body."""

        return {
            "capture_id": str(self.reference.capture_id),
            "body_verified": self.body_verified,
            "audit_found": self.audit is not None,
            "is_orphan": self.is_orphan,
            "reference": self.reference.to_dict(),
        }


class FinancialResponseArtifactRepository:
    """Compose encrypted body storage with the existing raw-audit repository."""

    def __init__(
        self,
        body_store: FinancialResponseBodyStore,
        audit_repository: FinancialResponseArtifactAuditPort,
    ) -> None:
        """Create the adapter from explicitly configured infrastructure ports."""

        self._body_store = body_store
        self._audit_repository = audit_repository
        self._retainer = RetainFinancialResponseArtifactUseCase(
            body_store=body_store,
            audit_repository=audit_repository,
        )

    def retain(
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
        """Retain one exact body and its versioned redacted audit link."""

        return self._retainer.execute(
            capture_id=capture_id,
            evidence=evidence,
            body=body,
            provider_name=provider_name,
            request_params=request_params,
            row_count=row_count,
            provider_id=provider_id,
        )

    def inspect_orphan(
        self,
        reference: FinancialResponseArtifactRef,
    ) -> FinancialResponseArtifactOrphan:
        """Verify a body reference and locate its corresponding audit row."""

        body_verified = False
        try:
            inspected = self._body_store.inspect(reference)
            body_verified = inspected == reference
        except FinancialResponseArtifactError:
            inspected = reference
        audit = self._audit_repository.find_by_artifact_capture_id(reference.capture_id)
        return FinancialResponseArtifactOrphan(
            reference=inspected,
            audit=audit,
            body_verified=body_verified,
        )


def reference_from_audit(audit: RawAudit) -> FinancialResponseArtifactRef:
    """Decode an existing audit link at the Infrastructure boundary."""

    if audit.capability != "financial":
        raise ValueError("financial response artifact audit capability is invalid")
    raw_link = audit.extra.get("financial_response_artifact")
    if not isinstance(raw_link, Mapping):
        raise ValueError("financial response artifact audit link is missing")
    if raw_link.get("schema") != "financial-response-artifact-link.v1":
        raise ValueError("financial response artifact audit schema is invalid")
    if frozenset(raw_link) != _AUDIT_LINK_KEYS:
        raise ValueError("financial response artifact audit link keys are invalid")
    metadata = dict(raw_link)
    metadata.pop("schema", None)
    provider_id = metadata.pop("provider_id", None)
    if provider_id is not None and (
        isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0
    ):
        raise ValueError("financial response artifact audit provider is invalid")
    location = metadata.pop("location", None)
    if not isinstance(location, str):
        raise ValueError("financial response artifact audit location is invalid")
    metadata.pop("evidence_basis", None)
    request_scope = metadata.get("request_scope")
    if not isinstance(request_scope, Mapping):
        raise ValueError("financial response artifact audit request scope is invalid")
    dataset_key = request_scope.get("dataset_key")
    provider_name = request_scope.get("provider_name")
    if not isinstance(dataset_key, str) or not isinstance(provider_name, str):
        raise ValueError("financial response artifact audit request scope is invalid")
    metadata["dataset_key"] = dataset_key
    metadata["provider_name"] = provider_name
    metadata["kind"] = "financial_response_artifact"
    try:
        reference = _reference_from_metadata(metadata)
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("financial response artifact audit link is invalid") from exc
    if location != reference.location:
        raise ValueError("financial response artifact audit location is invalid")
    return reference


__all__ = [
    "FinancialResponseArtifactOrphan",
    "FinancialResponseArtifactRepository",
    "reference_from_audit",
]
