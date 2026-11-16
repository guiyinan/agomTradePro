"""Reverify one v3 statutory identity against existing 0116 document capture.

This adapter joins only existing Statutory Source and numeric document-capture
repositories. It creates no catalog, authority, approval, or publication row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from django.db import DatabaseError, connections
from django.db.backends.base.base import BaseDatabaseWrapper

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
    FinancialAvailabilitySourceReaderPort,
)
from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialOfficialSourceIdentity,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.financial_statutory_capture_binding import (
    FinancialStatutoryCaptureBinding,
    FinancialStatutoryCaptureBindingError,
    financial_numeric_capture_reference_for_statutory,
    verify_financial_statutory_capture_binding,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    FinancialNumericCatalogEvidenceError,
    LockedFinancialNumericSourceCapture,
    VerifiedFinancialNumericSourceCapture,
)
from core.exceptions import DataValidationError


class FinancialNumericSourceCaptureRepositoryPort(Protocol):
    """Expose only the existing 0116 capture methods this adapter needs."""

    @property
    def database_alias(self) -> str:
        """Return the alias containing the capture, provider, and audit rows."""

    def read_verified_capture(
        self,
        reference: FinancialNumericSourceDocumentCaptureReference,
        *,
        known_at: datetime,
    ) -> VerifiedFinancialNumericSourceCapture:
        """Verify exact historical capture metadata, successful audit, and body bytes."""

    def lock_capture_for_uow(
        self,
        reference: FinancialNumericSourceDocumentCaptureReference,
    ) -> LockedFinancialNumericSourceCapture:
        """Lock capture, provider, and matching audit in the caller's transaction."""

    def verify_locked_capture(
        self,
        locked_capture: LockedFinancialNumericSourceCapture,
        *,
        known_at: datetime,
    ) -> VerifiedFinancialNumericSourceCapture:
        """Recheck the locked capture bytes and clocks at the unchanged cutoff."""


class DjangoFinancialStatutoryNumericCaptureAdapter:
    """Compare exact retained Statutory Source and numeric capture evidence.

    ``read_as_of`` uses the existing 0116 read verifier. ``read_current`` first
    obtains the Statutory Source table SHARE fence, then locks the numeric
    capture, provider, and successful egress Audit rows, leaving every lock in
    the caller's transaction through commit.
    """

    def __init__(
        self,
        *,
        statutory_reader: FinancialAvailabilitySourceReaderPort,
        numeric_capture_repository: FinancialNumericSourceCaptureRepositoryPort,
        using: str,
    ) -> None:
        """Bind both actual repository ports to the same explicit alias."""

        if type(using) is not str or not using or using != using.strip() or len(using) > 128:
            raise DataValidationError(
                "Dual-capture adapter requires one explicit bounded database alias.",
                code="FINANCIAL_DUAL_CAPTURE_ALIAS_INVALID",
            )
        aliases = (statutory_reader.database_alias, numeric_capture_repository.database_alias)
        if any(type(alias) is not str or not alias or alias != alias.strip() for alias in aliases):
            raise DataValidationError(
                "A capture repository exposes an invalid database alias.",
                code="FINANCIAL_DUAL_CAPTURE_ALIAS_INVALID",
            )
        if aliases[0] != using or aliases[1] != using:
            raise DataValidationError(
                "Statutory and numeric capture repositories must share one database alias.",
                code="FINANCIAL_DUAL_CAPTURE_ALIAS_MISMATCH",
            )
        self._statutory_reader = statutory_reader
        self._numeric_capture_repository = numeric_capture_repository
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the same alias used by both exact capture repositories."""

        return self._using

    def read_as_of(
        self,
        official_source: FinancialOfficialSourceIdentity | FinancialStatutorySourceIdentity,
        *,
        known_at: datetime,
    ) -> FinancialStatutoryCaptureBinding:
        """Reverify both immutable capture bodies at one explicit PIT cutoff."""

        identity = _require_statutory_identity(official_source)
        cutoff = _require_utc(known_at, "known_at")
        self._require_read_committed_uow(current=False)
        statutory = self._read_statutory(identity, known_at=cutoff)
        document_reference = _document_reference(statutory.reference)
        try:
            numeric = self._numeric_capture_repository.read_verified_capture(
                document_reference,
                known_at=cutoff,
            )
        except FinancialNumericCatalogEvidenceError as error:
            raise _numeric_read_error(error) from error
        return self._bind(
            identity=identity,
            statutory=statutory,
            numeric=numeric,
            known_at=cutoff,
        )

    def read_current(
        self,
        official_source: FinancialOfficialSourceIdentity | FinancialStatutorySourceIdentity,
        *,
        known_at: datetime,
    ) -> FinancialStatutoryCaptureBinding:
        """Reverify the exact response while holding current PostgreSQL row locks.

        The caller supplies the existing operation cutoff. This method does not
        replace it with transaction start time or a fresh application clock.
        It acquires source-table SHARE locks before the 0116 capture/provider/
        Audit row locks and leaves them held to the caller's commit.
        """

        identity = _require_statutory_identity(official_source)
        cutoff = _require_utc(known_at, "known_at")
        self._require_read_committed_uow(current=True)
        statutory = self._read_statutory(identity, known_at=cutoff)
        document_reference = _document_reference(statutory.reference)
        try:
            locked_capture = self._numeric_capture_repository.lock_capture_for_uow(
                document_reference
            )
            numeric = self._numeric_capture_repository.verify_locked_capture(
                locked_capture,
                known_at=cutoff,
            )
        except FinancialNumericCatalogEvidenceError as error:
            raise _numeric_read_error(error) from error
        return self._bind(
            identity=identity,
            statutory=statutory,
            numeric=numeric,
            known_at=cutoff,
        )

    def _read_statutory(
        self,
        identity: FinancialStatutorySourceIdentity,
        *,
        known_at: datetime,
    ) -> FinancialAvailabilitySourceRead:
        """Reread the identity's exact native revision, capture, and retained body."""

        try:
            result = self._statutory_reader.read_exact_capture(
                issuer=identity.issuer,
                document_id=identity.document_id,
                source_version=identity.source_version,
                capture_id=identity.capture_id,
                known_at=known_at,
            )
        except DataValidationError as error:
            raise DataValidationError(
                "The exact Statutory Source capture failed readback.",
                code="FINANCIAL_STATUTORY_CAPTURE_CHANGED",
            ) from error
        if result is None:
            raise DataValidationError(
                "The exact Statutory Source capture is missing at the requested cutoff.",
                code="FINANCIAL_STATUTORY_CAPTURE_MISSING",
            )
        if type(result) is not FinancialAvailabilitySourceRead:
            raise DataValidationError(
                "The Statutory Source reader returned an untyped result.",
                code="FINANCIAL_STATUTORY_CAPTURE_INVALID",
            )
        try:
            result.__post_init__()
        except (TypeError, ValueError) as error:
            raise DataValidationError(
                "The Statutory Source readback failed exact body or clock validation.",
                code="FINANCIAL_STATUTORY_CAPTURE_CHANGED",
            ) from error
        if result.known_at != known_at:
            raise DataValidationError(
                "The Statutory Source reader changed the explicit knowledge cutoff.",
                code="FINANCIAL_CAPTURE_KNOWLEDGE_CUTOFF_INVALID",
            )
        return result

    def _bind(
        self,
        *,
        identity: FinancialStatutorySourceIdentity,
        statutory: FinancialAvailabilitySourceRead,
        numeric: VerifiedFinancialNumericSourceCapture,
        known_at: datetime,
    ) -> FinancialStatutoryCaptureBinding:
        """Compare both exact identities, bytes, response clocks, and cutoff."""

        if type(numeric) is not VerifiedFinancialNumericSourceCapture:
            raise DataValidationError(
                "The 0116 repository returned an untyped capture result.",
                code="FINANCIAL_NUMERIC_CAPTURE_INVALID",
            )
        checked_at = _database_now(self._using)
        try:
            return verify_financial_statutory_capture_binding(
                official_source=identity,
                statutory_capture=statutory.reference,
                statutory_body=statutory.body,
                document_capture=numeric.reference,
                document_body=numeric.body,
                document_response_completed_at=numeric.response_completed_at,
                document_capture_recorded_at=numeric.capture_recorded_at,
                known_at=known_at,
                checked_at=checked_at,
                source_checked_at=statutory.checked_at,
            )
        except FinancialStatutoryCaptureBindingError as error:
            raise DataValidationError(str(error), code=error.code) from error

    def _require_read_committed_uow(self, *, current: bool) -> None:
        """Require one same-alias PostgreSQL RC transaction without opening one."""

        connection = connections[self._using]
        if (
            connection.alias != self._using
            or connection.vendor != "postgresql"
            or not connection.in_atomic_block
            or connection.get_autocommit()
            or (current and len(connection.atomic_blocks) != 1)
        ):
            raise DataValidationError(
                "Capture verification requires the caller's PostgreSQL READ COMMITTED UOW.",
                code="FINANCIAL_DUAL_CAPTURE_UOW_INVALID",
            )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                row = cursor.fetchone()
        except DatabaseError as error:
            raise DataValidationError(
                "Capture verification cannot read transaction isolation.",
                code="FINANCIAL_DUAL_CAPTURE_UOW_INVALID",
            ) from error
        if row is None or len(row) != 1 or row[0] != "read committed":
            raise DataValidationError(
                "Capture verification requires PostgreSQL READ COMMITTED isolation.",
                code="FINANCIAL_DUAL_CAPTURE_UOW_INVALID",
            )


def _require_statutory_identity(
    value: FinancialOfficialSourceIdentity | FinancialStatutorySourceIdentity,
) -> FinancialStatutorySourceIdentity:
    """Accept only the explicit public-storage v3 branch, never legacy encryption."""

    if type(value) is not FinancialStatutorySourceIdentity:
        raise DataValidationError(
            "The exact v3 statutory source identity is required; the legacy encrypted branch is unsupported.",
            code="FINANCIAL_STATUTORY_IDENTITY_UNSUPPORTED",
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "The v3 statutory source identity is malformed.",
            code="FINANCIAL_STATUTORY_IDENTITY_INVALID",
        ) from error
    return value


def _document_reference(
    reference: StatutorySourceCaptureReference,
) -> FinancialNumericSourceDocumentCaptureReference:
    """Build the exact 0116 lookup key without normalizing source metadata."""

    try:
        return financial_numeric_capture_reference_for_statutory(reference)
    except FinancialStatutoryCaptureBindingError as error:
        raise DataValidationError(str(error), code=error.code) from error
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "The Statutory Source reference cannot form an exact numeric capture selector.",
            code="FINANCIAL_STATUTORY_CAPTURE_INVALID",
        ) from error


def _numeric_read_error(error: FinancialNumericCatalogEvidenceError) -> DataValidationError:
    """Map a missing numeric row separately from corrupt or unverifiable evidence."""

    if error.code == "FINANCIAL_NUMERIC_CAPTURE_UNAVAILABLE":
        code = "FINANCIAL_NUMERIC_CAPTURE_MISSING"
    elif error.code == "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID":
        code = "FINANCIAL_CAPTURE_KNOWLEDGE_CUTOFF_INVALID"
    else:
        code = "FINANCIAL_NUMERIC_CAPTURE_CHANGED"
    return DataValidationError(
        "The existing 0116 numeric capture failed exact readback.",
        code=code,
    )


def _require_utc(value: object, name: str) -> datetime:
    """Require an explicit zero-offset timestamp without changing its instant."""

    if type(value) is not datetime or value.tzinfo is None:
        raise DataValidationError(
            f"{name} must be an explicit aware UTC datetime.",
            code="FINANCIAL_CAPTURE_KNOWLEDGE_CUTOFF_INVALID",
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise DataValidationError(
            f"{name} must be an explicit aware UTC datetime.",
            code="FINANCIAL_CAPTURE_KNOWLEDGE_CUTOFF_INVALID",
        )
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise DataValidationError(
            f"{name} is outside the UTC range.",
            code="FINANCIAL_CAPTURE_KNOWLEDGE_CUTOFF_INVALID",
        ) from error


def _database_now(using: str) -> datetime:
    """Read database wall time after both repositories have verified the bytes."""

    connection: BaseDatabaseWrapper = connections[using]
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cursor.fetchone()
    except DatabaseError as error:
        raise DataValidationError(
            "Capture verification cannot read the database completion clock.",
            code="FINANCIAL_CAPTURE_CHECK_CLOCK_INVALID",
        ) from error
    if row is None or len(row) != 1:
        raise DataValidationError(
            "Capture verification cannot read the database completion clock.",
            code="FINANCIAL_CAPTURE_CHECK_CLOCK_INVALID",
        )
    return _require_utc(row[0], "database check time")


__all__ = [
    "DjangoFinancialStatutoryNumericCaptureAdapter",
    "FinancialNumericSourceCaptureRepositoryPort",
]
