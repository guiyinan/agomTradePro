"""Ports and integrity-checked use cases for statutory source evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture,
    StatutorySourceBodyReference,
    StatutorySourceBundleAppendResult,
    StatutorySourceDocumentAppendResult,
    StatutorySourceDocumentBundle,
    StatutorySourceDocumentRevision,
)
from core.exceptions import DataValidationError


class StatutorySourceDocumentBodyStorePort(Protocol):
    """Read and store exact source bodies through a Data Center-owned adapter."""

    def store(self, capture_id: UUID, body: bytes) -> StatutorySourceBodyReference:
        """Store exact bytes under a server-issued ID and issue a safe opaque reference.

        ``capture_id`` must come from the trusted server-side capture pipeline,
        never from an HTTP or configuration field.
        """
        ...

    def read(self, reference: StatutorySourceBodyReference) -> bytes:
        """Return integrity-checked exact bytes for a storage-issued reference."""
        ...


class StatutorySourceDocumentRepositoryPort(Protocol):
    """Append source revisions and capture observations, and read them exactly."""

    def append_capture(
        self,
        revision: StatutorySourceDocumentRevision,
        capture: RetainedStatutorySourceDocumentCapture,
    ) -> StatutorySourceDocumentAppendResult:
        """Atomically append a capture under two immutable identities.

        Native revision identity is ``(issuer, document_id, source_version)``.
        Reusing it with any different source facts or body digest must conflict;
        an exact existing revision may acquire a newly identified capture. A
        capture ID may only replay the exact same capture. Implementations must
        serialize concurrent insert collisions and compare the visible winner.
        """
        ...

    def get_revision_exact(
        self,
        *,
        issuer: str,
        document_id: str,
        source_version: str,
    ) -> StatutorySourceDocumentRevision | None:
        """Return one exact publisher-native revision, if it was retained."""
        ...

    def get_capture(self, capture_id: UUID) -> RetainedStatutorySourceDocumentCapture | None:
        """Return one exact capture observation by its server-issued UUID."""
        ...


class StatutorySourceDocumentBundleRepositoryPort(Protocol):
    """Append and read immutable source bundles and their capture manifests."""

    def append(
        self,
        bundle: StatutorySourceDocumentBundle,
    ) -> StatutorySourceBundleAppendResult:
        """Append once, return an exact duplicate, or reject identity conflicts."""
        ...

    def get_exact(
        self,
        *,
        bundle_id: str,
        version: str,
    ) -> StatutorySourceDocumentBundle | None:
        """Return one exact bundle identity and version, if it was retained."""
        ...


class StatutorySourceRevisionConflictError(DataValidationError):
    """Raised when a native source revision identity is reused for changed facts."""

    default_message = "Statutory source revision conflicts with retained native evidence."
    default_code = "STATUTORY_SOURCE_REVISION_CONFLICT"


class StatutorySourceCaptureConflictError(DataValidationError):
    """Raised when a capture UUID is reused for a different capture observation."""

    default_message = "Statutory source capture ID conflicts with retained evidence."
    default_code = "STATUTORY_SOURCE_CAPTURE_CONFLICT"


class StatutorySourceBundleConflictError(DataValidationError):
    """Raised when a retained bundle identity is reused for different facts."""

    default_message = "Statutory source bundle identity conflicts with retained evidence."
    default_code = "STATUTORY_SOURCE_BUNDLE_CONFLICT"


class RetainStatutorySourceDocumentUseCase:
    """Verify, store, read back, and append one unqualified source capture.

    This use case checks byte integrity only; it does not establish official
    publisher origin or current tax-policy status.
    """

    def __init__(
        self,
        *,
        body_store: StatutorySourceDocumentBodyStorePort,
        document_repository: StatutorySourceDocumentRepositoryPort,
    ) -> None:
        """Bind Data Center-owned body and metadata ports."""

        self._body_store = body_store
        self._document_repository = document_repository

    def execute(
        self,
        *,
        revision: StatutorySourceDocumentRevision,
        capture_id: UUID,
        captured_at: datetime,
        content_type: str,
        body: bytes,
    ) -> StatutorySourceDocumentAppendResult:
        """Append after exact readback; inputs come from a trusted capture composition.

        ``capture_id`` and ``captured_at`` are server-issued observation facts,
        not source publication time or caller-supplied authority.
        """

        if type(revision) is not StatutorySourceDocumentRevision:
            raise DataValidationError(
                "Statutory source revision metadata is invalid.",
                code="STATUTORY_SOURCE_REVISION_INPUT_INVALID",
            )
        if type(capture_id) is not UUID:
            raise DataValidationError(
                "Statutory source capture ID is invalid.",
                code="STATUTORY_SOURCE_CAPTURE_ID_INVALID",
            )
        if type(captured_at) is not datetime or captured_at.tzinfo is None:
            raise DataValidationError(
                "Statutory source capture time must be timezone-aware.",
                code="STATUTORY_SOURCE_CAPTURE_TIME_INVALID",
            )
        if captured_at.utcoffset() is None:
            raise DataValidationError(
                "Statutory source capture time must be timezone-aware.",
                code="STATUTORY_SOURCE_CAPTURE_TIME_INVALID",
            )
        try:
            captured_at.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise DataValidationError(
                "Statutory source capture time must be representable in UTC.",
                code="STATUTORY_SOURCE_CAPTURE_TIME_INVALID",
            ) from error
        _require_capture_text(content_type, field_name="content_type", maximum=200)
        if not revision.verifies_source_document(body):
            raise DataValidationError(
                "Statutory source bytes do not match native revision metadata.",
                code="STATUTORY_SOURCE_DOCUMENT_BODY_MISMATCH",
            )

        reference = self._body_store.store(capture_id, body)
        if (
            type(reference) is not StatutorySourceBodyReference
            or reference.capture_id != capture_id
            or reference.body_sha256 != revision.body_sha256
            or reference.body_size_bytes != revision.body_size_bytes
            or not reference.verifies(body)
        ):
            raise DataValidationError(
                "Body store returned an inconsistent statutory source reference.",
                code="STATUTORY_SOURCE_BODY_REFERENCE_MISMATCH",
            )

        readback = self._body_store.read(reference)
        if type(readback) is not bytes or readback != body or not reference.verifies(readback):
            raise DataValidationError(
                "Stored statutory source bytes failed exact readback verification.",
                code="STATUTORY_SOURCE_BODY_READBACK_FAILED",
            )

        capture = RetainedStatutorySourceDocumentCapture(
            capture_id=capture_id,
            revision=revision,
            captured_at=captured_at,
            content_type=content_type,
            body_reference=reference,
        )
        result = self._document_repository.append_capture(revision, capture)
        if type(result) is not StatutorySourceDocumentAppendResult:
            raise DataValidationError(
                "Statutory source repository returned an invalid append result.",
                code="STATUTORY_SOURCE_DOCUMENT_APPEND_RESULT_INVALID",
            )
        if result.revision != revision:
            raise StatutorySourceRevisionConflictError()
        if result.capture != capture:
            raise StatutorySourceCaptureConflictError()
        return result


class ReadStatutorySourceDocumentBodyUseCase:
    """Read exact retained bytes and verify the body reference independently."""

    def __init__(self, body_store: StatutorySourceDocumentBodyStorePort) -> None:
        """Bind the owning Data Center body store."""

        self._body_store = body_store

    def execute(self, reference: StatutorySourceBodyReference) -> bytes:
        """Return a body only when its exact digest and size match the reference."""

        if type(reference) is not StatutorySourceBodyReference:
            raise DataValidationError(
                "Statutory source body reference is invalid.",
                code="STATUTORY_SOURCE_BODY_REFERENCE_INVALID",
            )
        body = self._body_store.read(reference)
        if type(body) is not bytes or not reference.verifies(body):
            raise DataValidationError(
                "Retained statutory source body failed digest or size verification.",
                code="STATUTORY_SOURCE_BODY_INTEGRITY_FAILED",
            )
        return body


class QueryStatutorySourceDocumentUseCase:
    """Read one exact native revision or a capture by its immutable identity."""

    def __init__(self, repository: StatutorySourceDocumentRepositoryPort) -> None:
        """Bind the Data Center-owned revision and capture reader."""

        self._repository = repository

    def get_revision_exact(
        self,
        *,
        issuer: str,
        document_id: str,
        source_version: str,
    ) -> StatutorySourceDocumentRevision | None:
        """Return a revision only when all native identity fields match."""

        _require_capture_text(issuer, field_name="issuer", maximum=240)
        _require_capture_text(document_id, field_name="document_id", maximum=240)
        _require_capture_text(source_version, field_name="source_version", maximum=120)
        revision = self._repository.get_revision_exact(
            issuer=issuer,
            document_id=document_id,
            source_version=source_version,
        )
        if revision is None:
            return None
        if type(revision) is not StatutorySourceDocumentRevision or revision.identity_key != (
            issuer,
            document_id,
            source_version,
        ):
            raise DataValidationError(
                "Statutory source repository returned a different native revision.",
                code="STATUTORY_SOURCE_REVISION_READ_IDENTITY_MISMATCH",
            )
        return revision

    def get_capture(self, capture_id: UUID) -> RetainedStatutorySourceDocumentCapture | None:
        """Return a capture only when its server-issued UUID matches exactly."""

        if type(capture_id) is not UUID:
            raise DataValidationError(
                "Statutory source capture ID is invalid.",
                code="STATUTORY_SOURCE_CAPTURE_ID_INVALID",
            )
        capture = self._repository.get_capture(capture_id)
        if capture is None:
            return None
        if (
            type(capture) is not RetainedStatutorySourceDocumentCapture
            or capture.capture_id != capture_id
        ):
            raise DataValidationError(
                "Statutory source repository returned a different capture.",
                code="STATUTORY_SOURCE_CAPTURE_READ_IDENTITY_MISMATCH",
            )
        return capture


class AppendStatutorySourceDocumentBundleUseCase:
    """Append an assembled source bundle and its exact capture manifest."""

    def __init__(self, repository: StatutorySourceDocumentBundleRepositoryPort) -> None:
        """Bind the Data Center-owned bundle repository."""

        self._repository = repository

    def execute(
        self,
        bundle: StatutorySourceDocumentBundle,
    ) -> StatutorySourceBundleAppendResult:
        """Append the exact bundle and reject a changed identity winner."""

        if type(bundle) is not StatutorySourceDocumentBundle:
            raise DataValidationError(
                "Statutory source bundle input is invalid.",
                code="STATUTORY_SOURCE_BUNDLE_INPUT_INVALID",
            )
        result = self._repository.append(bundle)
        if type(result) is not StatutorySourceBundleAppendResult:
            raise DataValidationError(
                "Statutory source repository returned an invalid bundle result.",
                code="STATUTORY_SOURCE_BUNDLE_APPEND_RESULT_INVALID",
            )
        if result.record != bundle:
            raise StatutorySourceBundleConflictError()
        return result


class QueryStatutorySourceDocumentBundleUseCase:
    """Read one immutable source bundle by its explicit identity and version."""

    def __init__(self, repository: StatutorySourceDocumentBundleRepositoryPort) -> None:
        """Bind the Data Center-owned bundle repository."""

        self._repository = repository

    def get_exact(
        self,
        *,
        bundle_id: str,
        version: str,
    ) -> StatutorySourceDocumentBundle | None:
        """Return a retained bundle only when both identity fields match."""

        _require_capture_text(bundle_id, field_name="bundle_id", maximum=240)
        _require_capture_text(version, field_name="version", maximum=120)
        bundle = self._repository.get_exact(bundle_id=bundle_id, version=version)
        if bundle is None:
            return None
        if (
            type(bundle) is not StatutorySourceDocumentBundle
            or bundle.bundle_id != bundle_id
            or bundle.version != version
        ):
            raise DataValidationError(
                "Statutory source repository returned a different bundle identity.",
                code="STATUTORY_SOURCE_BUNDLE_READ_IDENTITY_MISMATCH",
            )
        return bundle


def _require_capture_text(value: str, *, field_name: str, maximum: int) -> str:
    """Require bounded exact text before capture or repository work."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DataValidationError(
            f"Statutory source {field_name} is invalid.",
            code="STATUTORY_SOURCE_INPUT_INVALID",
        )
    return value


__all__ = [
    "AppendStatutorySourceDocumentBundleUseCase",
    "QueryStatutorySourceDocumentBundleUseCase",
    "QueryStatutorySourceDocumentUseCase",
    "ReadStatutorySourceDocumentBodyUseCase",
    "RetainStatutorySourceDocumentUseCase",
    "StatutorySourceBundleConflictError",
    "StatutorySourceCaptureConflictError",
    "StatutorySourceDocumentBodyStorePort",
    "StatutorySourceDocumentBundleRepositoryPort",
    "StatutorySourceDocumentRepositoryPort",
    "StatutorySourceRevisionConflictError",
]
