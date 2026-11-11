"""Exact append/read persistence for unqualified statutory source evidence."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import TypeVar
from uuid import UUID

from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from apps.data_center.application.statutory_source_documents import (
    StatutorySourceBundleConflictError,
    StatutorySourceCaptureConflictError,
    StatutorySourceDocumentBodyStorePort,
    StatutorySourceDocumentBundleRepositoryPort,
    StatutorySourceDocumentRepositoryPort,
    StatutorySourceRevisionConflictError,
)
from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture,
    StatutorySourceAppendDisposition,
    StatutorySourceBodyReference,
    StatutorySourceBundleAppendResult,
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentAppendResult,
    StatutorySourceDocumentBundle,
    StatutorySourceDocumentRevision,
)
from apps.data_center.infrastructure.statutory_source_models import (
    StatutorySourceDocumentBundleMemberModel,
    StatutorySourceDocumentBundleModel,
    StatutorySourceDocumentCaptureModel,
    StatutorySourceDocumentRevisionModel,
    _activate_statutory_source_uow,
    _claim_statutory_source_insert,
    _StatutorySourceImmutableModel,
)
from core.exceptions import DataValidationError

_RowT = TypeVar("_RowT", bound=_StatutorySourceImmutableModel)


def _invalid(message: str, code: str = "STATUTORY_SOURCE_STORAGE_INVALID") -> DataValidationError:
    """Classify storage failures without exposing bodies or external input values."""
    return DataValidationError(message, code=code)


def _lookup_text(value: str, maximum: int) -> None:
    """Validate exact bounded identifiers before issuing an ORM query."""
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise _invalid("Statutory source lookup identity is invalid.")


def _insert_claimed(model_type: type[_RowT], values: dict[str, object], *, using: str) -> _RowT:
    """Insert one exact row inside the caller's same-alias atomic transaction."""
    with _activate_statutory_source_uow() as token:
        with _claim_statutory_source_insert(
            token=token, using=using, model_type=model_type, expected_values=values
        ):
            return model_type._default_manager.using(using).create(**values)


def _date_values(evidence: StatutorySourceDateEvidence, prefix: str) -> dict[str, object]:
    """Persist DATE/INSTANT/UNKNOWN without manufacturing a missing clock value."""
    return {
        f"{prefix}_precision": evidence.precision.value,
        f"{prefix}_date": evidence.date_value,
        f"{prefix}_instant": evidence.instant_value,
    }


def _revision_values(
    revision: StatutorySourceDocumentRevision, recorded_at: datetime
) -> dict[str, object]:
    """Build the exact insert claim for one validated source revision."""
    return {
        "issuer": revision.issuer,
        "document_id": revision.document_id,
        "source_version": revision.source_version,
        "canonical_url": revision.canonical_url,
        "title": revision.title,
        "legal_number": revision.legal_number,
        **_date_values(revision.publication_date, "publication"),
        **_date_values(revision.effective_date, "effective"),
        "body_sha256": revision.body_sha256,
        "body_size_bytes": revision.body_size_bytes,
        "source_revision_sha256": revision.source_revision_sha256,
        "recorded_at": recorded_at,
    }


def _restore_date(
    precision: str, date_value: date | None, instant_value: datetime | None
) -> StatutorySourceDateEvidence:
    """Narrow stored precision and date fields through their complete Domain definition."""
    return StatutorySourceDateEvidence(
        precision=StatutorySourceDatePrecision(precision),
        date_value=date_value,
        instant_value=instant_value,
    )


def _restore_revision(row: StatutorySourceDocumentRevisionModel) -> StatutorySourceDocumentRevision:
    """Rebuild and independently rehash every persisted source revision field."""
    try:
        revision = StatutorySourceDocumentRevision(
            issuer=row.issuer,
            document_id=row.document_id,
            source_version=row.source_version,
            canonical_url=row.canonical_url,
            title=row.title,
            legal_number=row.legal_number,
            publication_date=_restore_date(
                row.publication_precision, row.publication_date, row.publication_instant
            ),
            effective_date=_restore_date(
                row.effective_precision, row.effective_date, row.effective_instant
            ),
            body_sha256=row.body_sha256,
            body_size_bytes=row.body_size_bytes,
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise _invalid("Stored statutory source revision is invalid.") from error
    if revision.source_revision_sha256 != row.source_revision_sha256:
        raise _invalid("Stored statutory source revision digest is inconsistent.")
    return revision


def _restore_capture(
    row: StatutorySourceDocumentCaptureModel,
) -> RetainedStatutorySourceDocumentCapture:
    """Rebuild one capture with its exact source revision and storage-issued reference."""
    revision = _restore_revision(row.revision)
    try:
        capture = RetainedStatutorySourceDocumentCapture(
            capture_id=row.capture_id,
            revision=revision,
            captured_at=row.captured_at,
            content_type=row.content_type,
            body_reference=StatutorySourceBodyReference(
                capture_id=row.capture_id,
                reference=row.body_reference,
                body_sha256=revision.body_sha256,
                body_size_bytes=revision.body_size_bytes,
            ),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise _invalid("Stored statutory source capture is invalid.") from error
    if row.recorded_at < capture.captured_at:
        raise _invalid("Stored statutory source observation clocks are inconsistent.")
    return capture


class DjangoStatutorySourceRepository(
    StatutorySourceDocumentRepositoryPort, StatutorySourceDocumentBundleRepositoryPort
):
    """Append immutable source facts; integrity does not confer official origin or policy authority."""

    def __init__(
        self,
        *,
        body_store: StatutorySourceDocumentBodyStorePort,
        using: str = "default",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind one explicit byte store, database alias and trusted recording clock."""
        _lookup_text(using, 128)
        self._using = using
        self._body_store = body_store
        self._clock = clock or timezone.now

    def _now(self) -> datetime:
        """Reject missing, naive or unrepresentable trusted recording instants."""
        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise _invalid(
                "Statutory source recording clock is invalid.", "STATUTORY_SOURCE_CLOCK_INVALID"
            )
        try:
            return value.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise _invalid(
                "Statutory source recording clock is invalid.", "STATUTORY_SOURCE_CLOCK_INVALID"
            ) from error

    def _verify_body(self, capture: RetainedStatutorySourceDocumentCapture) -> None:
        """Read exact bytes before starting the repository's own metadata transaction."""
        body = self._body_store.read(capture.body_reference)
        if (
            type(body) is not bytes
            or not capture.body_reference.verifies(body)
            or not capture.revision.verifies_source_document(body)
        ):
            raise _invalid("Retained statutory source body failed integrity verification.")

    def _require_write_isolation(self) -> None:
        """Require READ COMMITTED so unique-key retries can read the committed winner."""
        database = connections[self._using]
        if database.vendor != "postgresql":
            return
        with database.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            row = cursor.fetchone()
        if row is None or row[0] != "read committed":
            raise _invalid(
                "Statutory source writes require PostgreSQL READ COMMITTED.",
                "STATUTORY_SOURCE_ISOLATION_UNSUPPORTED",
            )

    def append_capture(
        self,
        revision: StatutorySourceDocumentRevision,
        capture: RetainedStatutorySourceDocumentCapture,
    ) -> StatutorySourceDocumentAppendResult:
        """Serialize native revision and capture UUID conflicts without overwriting history."""
        if (
            type(revision) is not StatutorySourceDocumentRevision
            or type(capture) is not RetainedStatutorySourceDocumentCapture
        ):
            raise _invalid("Statutory source revision or capture input is invalid.")
        if capture.revision != revision:
            raise StatutorySourceRevisionConflictError()
        if revision.body_size_bytes > sys.maxsize:
            raise _invalid("Statutory source body size exceeds storage capacity.")
        recorded_at = self._now()
        if capture.captured_at > recorded_at:
            raise _invalid(
                "Statutory source capture cannot be recorded in its future.",
                "STATUTORY_SOURCE_CLOCK_INVALID",
            )
        self._verify_body(capture)
        with transaction.atomic(using=self._using):
            self._require_write_isolation()
            revision_row = self._append_revision(revision, recorded_at)
            existing = self._locked_capture(capture.capture_id)
            if existing is not None:
                return self._capture_winner(existing, revision, capture)
            try:
                with transaction.atomic(using=self._using):
                    created = _insert_claimed(
                        StatutorySourceDocumentCaptureModel,
                        {
                            "capture_id": capture.capture_id,
                            "revision_id": revision_row.pk,
                            "captured_at": capture.captured_at,
                            "content_type": capture.content_type,
                            "body_reference": capture.body_reference.reference,
                            "recorded_at": recorded_at,
                        },
                        using=self._using,
                    )
            except IntegrityError as error:
                winner = self._locked_capture(capture.capture_id)
                if winner is None:
                    raise _invalid(
                        "Statutory source capture violated a storage constraint."
                    ) from error
                return self._capture_winner(winner, revision, capture)
            return StatutorySourceDocumentAppendResult(
                disposition=StatutorySourceAppendDisposition.STORED,
                revision=_restore_revision(revision_row),
                capture=_restore_capture(created),
            )

    def _append_revision(
        self, revision: StatutorySourceDocumentRevision, recorded_at: datetime
    ) -> StatutorySourceDocumentRevisionModel:
        """Resolve a unique publisher revision collision inside the outer transaction."""
        identity = {
            "issuer": revision.issuer,
            "document_id": revision.document_id,
            "source_version": revision.source_version,
        }
        query = StatutorySourceDocumentRevisionModel._default_manager.using(
            self._using
        ).select_for_update()
        existing = query.filter(**identity).first()
        if existing is not None:
            if _restore_revision(existing) != revision:
                raise StatutorySourceRevisionConflictError()
            return existing
        try:
            with transaction.atomic(using=self._using):
                return _insert_claimed(
                    StatutorySourceDocumentRevisionModel,
                    _revision_values(revision, recorded_at),
                    using=self._using,
                )
        except IntegrityError as error:
            winner = query.filter(**identity).first()
            if winner is None:
                raise _invalid(
                    "Statutory source revision violated a storage constraint."
                ) from error
            if _restore_revision(winner) != revision:
                raise StatutorySourceRevisionConflictError() from error
            return winner

    def _locked_capture(self, capture_id: UUID) -> StatutorySourceDocumentCaptureModel | None:
        """Lock one exact capture and its source revision under the active alias."""
        return (
            StatutorySourceDocumentCaptureModel._default_manager.using(self._using)
            .select_related("revision")
            .select_for_update()
            .filter(capture_id=capture_id)
            .first()
        )

    @staticmethod
    def _capture_winner(
        row: StatutorySourceDocumentCaptureModel,
        revision: StatutorySourceDocumentRevision,
        capture: RetainedStatutorySourceDocumentCapture,
    ) -> StatutorySourceDocumentAppendResult:
        """Replay only the complete original capture, never a changed timestamp or locator."""
        restored = _restore_capture(row)
        if restored.revision != revision:
            raise StatutorySourceRevisionConflictError()
        if restored != capture:
            raise StatutorySourceCaptureConflictError()
        return StatutorySourceDocumentAppendResult(
            disposition=StatutorySourceAppendDisposition.DUPLICATE,
            revision=restored.revision,
            capture=restored,
        )

    def get_revision_exact(
        self, *, issuer: str, document_id: str, source_version: str
    ) -> StatutorySourceDocumentRevision | None:
        """Read one complete native revision identity without latest-version fallback."""
        for value, maximum in ((issuer, 240), (document_id, 240), (source_version, 120)):
            _lookup_text(value, maximum)
        row = (
            StatutorySourceDocumentRevisionModel._default_manager.using(self._using)
            .filter(issuer=issuer, document_id=document_id, source_version=source_version)
            .first()
        )
        return _restore_revision(row) if row is not None else None

    def get_capture(self, capture_id: UUID) -> RetainedStatutorySourceDocumentCapture | None:
        """Read historical capture metadata by its exact immutable server UUID."""
        if type(capture_id) is not UUID:
            raise _invalid("Statutory source capture lookup ID is invalid.")
        row = (
            StatutorySourceDocumentCaptureModel._default_manager.using(self._using)
            .select_related("revision")
            .filter(capture_id=capture_id)
            .first()
        )
        return _restore_capture(row) if row is not None else None

    def append(self, bundle: StatutorySourceDocumentBundle) -> StatutorySourceBundleAppendResult:
        """Atomically append the exact source set and every protected ordered member."""
        if type(bundle) is not StatutorySourceDocumentBundle:
            raise _invalid("Statutory source bundle input is invalid.")
        recorded_at = self._now()
        for capture in bundle.captures:
            if capture.captured_at > recorded_at:
                raise _invalid("Statutory source bundle contains a future capture.")
            self._verify_body(capture)
        with transaction.atomic(using=self._using):
            self._require_write_isolation()
            for capture in bundle.captures:
                stored = self._locked_capture(capture.capture_id)
                if stored is None or _restore_capture(stored) != capture:
                    raise _invalid("Statutory source bundle member is not retained exactly.")
            existing = self._bundle_row(bundle.bundle_id, bundle.version, lock=True)
            if existing is not None:
                return self._bundle_winner(existing, bundle)
            try:
                with transaction.atomic(using=self._using):
                    created = _insert_claimed(
                        StatutorySourceDocumentBundleModel,
                        {
                            "bundle_id": bundle.bundle_id,
                            "version": bundle.version,
                            "source_bundle_sha256": bundle.source_bundle_sha256,
                            "capture_manifest_sha256": bundle.capture_manifest_sha256,
                            "recorded_at": recorded_at,
                        },
                        using=self._using,
                    )
                    for ordinal, capture in enumerate(bundle.captures):
                        _insert_claimed(
                            StatutorySourceDocumentBundleMemberModel,
                            {
                                "bundle_id": created.pk,
                                "capture_id": capture.capture_id,
                                "ordinal": ordinal,
                                "recorded_at": recorded_at,
                            },
                            using=self._using,
                        )
            except IntegrityError as error:
                winner = self._bundle_row(bundle.bundle_id, bundle.version, lock=True)
                if winner is None:
                    raise _invalid(
                        "Statutory source bundle violated a storage constraint."
                    ) from error
                return self._bundle_winner(winner, bundle)
            return StatutorySourceBundleAppendResult(
                disposition=StatutorySourceAppendDisposition.STORED,
                record=self._restore_bundle(created),
            )

    def _bundle_row(
        self, bundle_id: str, version: str, *, lock: bool = False
    ) -> StatutorySourceDocumentBundleModel | None:
        """Query only the requested complete bundle identity."""
        query = StatutorySourceDocumentBundleModel._default_manager.using(self._using)
        if lock:
            query = query.select_for_update()
        return query.filter(bundle_id=bundle_id, version=version).first()

    def _restore_bundle(
        self, row: StatutorySourceDocumentBundleModel
    ) -> StatutorySourceDocumentBundle:
        """Restore all ordered FK members and verify both independent stored digests."""
        members = tuple(
            StatutorySourceDocumentBundleMemberModel._default_manager.using(self._using)
            .filter(bundle_id=row.pk)
            .select_related("capture__revision")
            .order_by("ordinal")
        )
        if not members or tuple(item.ordinal for item in members) != tuple(range(len(members))):
            raise _invalid("Stored statutory source bundle member sequence is incomplete.")
        try:
            bundle = StatutorySourceDocumentBundle(
                bundle_id=row.bundle_id,
                version=row.version,
                captures=tuple(_restore_capture(item.capture) for item in members),
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise _invalid("Stored statutory source bundle is invalid.") from error
        if (
            bundle.source_bundle_sha256 != row.source_bundle_sha256
            or bundle.capture_manifest_sha256 != row.capture_manifest_sha256
        ):
            raise _invalid("Stored statutory source bundle digests are inconsistent.")
        return bundle

    def _bundle_winner(
        self, row: StatutorySourceDocumentBundleModel, bundle: StatutorySourceDocumentBundle
    ) -> StatutorySourceBundleAppendResult:
        """Return an exact immutable bundle retry or reject identity reuse."""
        restored = self._restore_bundle(row)
        if restored != bundle:
            raise StatutorySourceBundleConflictError()
        return StatutorySourceBundleAppendResult(
            disposition=StatutorySourceAppendDisposition.DUPLICATE, record=restored
        )

    def get_exact(self, *, bundle_id: str, version: str) -> StatutorySourceDocumentBundle | None:
        """Read the requested historical bundle with no freshness or policy assertion."""
        _lookup_text(bundle_id, 240)
        _lookup_text(version, 120)
        row = self._bundle_row(bundle_id, version)
        return self._restore_bundle(row) if row is not None else None


__all__ = ["DjangoStatutorySourceRepository"]
