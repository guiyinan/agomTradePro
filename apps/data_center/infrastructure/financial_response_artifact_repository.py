"""Infrastructure adapter for retained financial response artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from apps.data_center.application.financial_response_artifact import (
    FinancialResponseArtifactAuditPort,
    FinancialResponseArtifactRetention,
    FinancialResponseFailureAuditLookupError,
    FinancialResponseFailureAuditPort,
    FinancialResponseFailureRetention,
    RetainFinancialResponseArtifactUseCase,
    RetainFinancialResponseFailureUseCase,
)
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import FinancialResponseEvidence
from apps.data_center.domain.financial_response_failure import (
    FINANCIAL_RESPONSE_FAILURE_CAPABILITY,
    FINANCIAL_RESPONSE_FAILURE_LINK_KEY,
    FINANCIAL_RESPONSE_FAILURE_LINK_SCHEMA,
    FINANCIAL_RESPONSE_FAILURE_STATUS,
)
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
_FAILURE_AUDIT_LINK_KEYS = _AUDIT_LINK_KEYS | frozenset({"failure_code"})


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
        *,
        failure_audit_repository: FinancialResponseFailureAuditPort | None = None,
    ) -> None:
        """Create the adapter from explicitly configured infrastructure ports."""

        self._body_store = body_store
        self._audit_repository = audit_repository
        self._failure_audit_repository = failure_audit_repository
        self._retainer = RetainFinancialResponseArtifactUseCase(
            body_store=body_store,
            audit_repository=audit_repository,
            failure_audit_repository=failure_audit_repository,
        )
        self._failure_retainer = (
            RetainFinancialResponseFailureUseCase(
                body_store=body_store,
                audit_repository=failure_audit_repository,
            )
            if failure_audit_repository is not None
            else None
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

    def retain_rejected(
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
        """Retain one rejected body under a failure-only audit capability."""

        if self._failure_retainer is None:
            raise FinancialResponseFailureAuditLookupError()
        return self._failure_retainer.execute(
            capture_id=capture_id,
            evidence=evidence,
            body=body,
            provider_name=provider_name,
            request_params=request_params,
            failure_code=failure_code,
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

    def inspect_rejected_orphan(
        self,
        reference: FinancialResponseArtifactRef,
    ) -> FinancialResponseArtifactOrphan:
        """Verify a rejected body and locate its failure-only audit row."""

        body_verified = False
        try:
            inspected = self._body_store.inspect(reference)
            body_verified = inspected == reference
        except FinancialResponseArtifactError:
            inspected = reference
        if self._failure_audit_repository is None:
            audit = None
        else:
            audit = self._failure_audit_repository.find_by_failure_capture_id(reference.capture_id)
            if audit is not None:
                try:
                    if failure_reference_from_audit(audit) != reference:
                        audit = None
                except ValueError:
                    audit = None
        return FinancialResponseArtifactOrphan(
            reference=inspected,
            audit=audit,
            body_verified=body_verified,
        )


def reference_from_audit(audit: RawAudit) -> FinancialResponseArtifactRef:
    """Decode an existing audit link at the Infrastructure boundary."""

    if audit.capability != "financial":
        raise ValueError("financial response artifact audit capability is invalid")
    if audit.status != "ok":
        raise ValueError("financial response artifact audit status is invalid")
    raw_link = audit.extra.get("financial_response_artifact")
    if not isinstance(raw_link, Mapping):
        raise ValueError("financial response artifact audit link is missing")
    return _reference_from_link(
        raw_link,
        expected_schema="financial-response-artifact-link.v1",
        expected_keys=_AUDIT_LINK_KEYS,
        error_prefix="financial response artifact audit",
    )


def failure_reference_from_audit(audit: RawAudit) -> FinancialResponseArtifactRef:
    """Decode a rejected-response audit link without treating it as success."""

    if audit.capability != FINANCIAL_RESPONSE_FAILURE_CAPABILITY:
        raise ValueError("financial response failure audit capability is invalid")
    if audit.status != FINANCIAL_RESPONSE_FAILURE_STATUS:
        raise ValueError("financial response failure audit status is invalid")
    raw_link = audit.extra.get(FINANCIAL_RESPONSE_FAILURE_LINK_KEY)
    if not isinstance(raw_link, Mapping):
        raise ValueError("financial response failure audit link is missing")
    failure_code = raw_link.get("failure_code")
    if not isinstance(failure_code, str) or not failure_code:
        raise ValueError("financial response failure audit code is invalid")
    if audit.error_message != failure_code:
        raise ValueError("financial response failure audit error code is invalid")
    return _reference_from_link(
        raw_link,
        expected_schema=FINANCIAL_RESPONSE_FAILURE_LINK_SCHEMA,
        expected_keys=_FAILURE_AUDIT_LINK_KEYS,
        error_prefix="financial response failure audit",
    )


def _reference_from_link(
    raw_link: Mapping[str, object],
    *,
    expected_schema: str,
    expected_keys: frozenset[str],
    error_prefix: str,
) -> FinancialResponseArtifactRef:
    """Decode common reference metadata for exactly one audit outcome."""

    if raw_link.get("schema") != expected_schema:
        raise ValueError(f"{error_prefix} schema is invalid")
    if frozenset(raw_link) != expected_keys:
        raise ValueError(f"{error_prefix} link keys are invalid")
    metadata = dict(raw_link)
    metadata.pop("schema", None)
    failure_code = metadata.pop("failure_code", None)
    if failure_code is not None and (
        not isinstance(failure_code, str)
        or not failure_code
        or len(failure_code) > 64
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in failure_code
        )
    ):
        raise ValueError(f"{error_prefix} failure code is invalid")
    provider_id = metadata.pop("provider_id", None)
    if provider_id is not None and (
        isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0
    ):
        raise ValueError(f"{error_prefix} provider is invalid")
    location = metadata.pop("location", None)
    if not isinstance(location, str):
        raise ValueError(f"{error_prefix} location is invalid")
    metadata.pop("evidence_basis", None)
    request_scope = metadata.get("request_scope")
    if not isinstance(request_scope, Mapping):
        raise ValueError(f"{error_prefix} request scope is invalid")
    dataset_key = request_scope.get("dataset_key")
    provider_name = request_scope.get("provider_name")
    if not isinstance(dataset_key, str) or not isinstance(provider_name, str):
        raise ValueError(f"{error_prefix} request scope is invalid")
    metadata["dataset_key"] = dataset_key
    metadata["provider_name"] = provider_name
    metadata["kind"] = "financial_response_artifact"
    try:
        reference = _reference_from_metadata(metadata)
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"{error_prefix} link is invalid") from exc
    if location != reference.location:
        raise ValueError(f"{error_prefix} location is invalid")
    return reference


__all__ = [
    "FinancialResponseArtifactOrphan",
    "FinancialResponseArtifactRepository",
    "failure_reference_from_audit",
    "reference_from_audit",
]
