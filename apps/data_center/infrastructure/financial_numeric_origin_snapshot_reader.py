"""Read immutable numeric capture origin snapshots for the future E1 v3 gate.

This reader verifies only configured provider/publisher origin and the exact
numeric capture's retained body/egress audit. It does not claim bundle
membership, legal status, Owner approval, or financial eligibility.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from django.db import DatabaseError, connections

from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3OfficialSourceOriginSnapshot,
)
from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_numeric_origin_snapshot import (
    FinancialNumericSourceOriginSnapshot,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    DjangoFinancialNumericSourceCaptureRepository,
    FinancialNumericCatalogEvidenceError,
    LockedFinancialNumericSourceCapture,
)
from apps.data_center.infrastructure.financial_numeric_catalog_models import (
    FinancialNumericSourceDocumentCaptureModel,
)
from apps.data_center.infrastructure.financial_numeric_origin_snapshot_capture import (
    load_origin_snapshot_seed,
    make_origin_snapshot,
)
from apps.data_center.infrastructure.financial_numeric_origin_snapshot_codec import (
    FinancialNumericOriginSnapshotCodecError,
    decode_origin_snapshot,
    encode_origin_snapshot,
)
from core.exceptions import DataValidationError


class FinancialNumericOriginSnapshotError(DataValidationError):
    """Stable failure for absent, changed, or cutoff-invisible origin evidence."""

    default_message = "Financial numeric origin snapshot is unavailable or invalid."
    default_code = "FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_INVALID"


def _block(message: str, code: str) -> FinancialNumericOriginSnapshotError:
    """Return a stable block without exposing configuration values or body bytes."""

    return FinancialNumericOriginSnapshotError(message, code=code)


def _utc(value: object, *, field_name: str) -> datetime:
    """Require one exact aware UTC time for persisted and caller cutoff checks."""

    if type(value) is not datetime or value.tzinfo is None:
        raise _block(f"{field_name} must be an aware UTC instant", "ORIGIN_CLOCK_INVALID")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise _block(f"{field_name} must be UTC", "ORIGIN_CLOCK_INVALID")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise _block(f"{field_name} is not representable", "ORIGIN_CLOCK_INVALID") from error


def _capture_reference_from_statutory(
    capture: StatutorySourceCaptureReference,
) -> FinancialNumericSourceDocumentCaptureReference:
    """Build the numeric selector from an independently read exact source capture."""

    if type(capture) is not StatutorySourceCaptureReference:
        raise TypeError("statutory capture must use the exact typed reference")
    return FinancialNumericSourceDocumentCaptureReference(
        capture_id=capture.capture_id,
        document_id=capture.document_id,
        issuer=capture.issuer,
        canonical_url=capture.canonical_url,
        body_sha256=capture.body_sha256,
        body_size_bytes=capture.body_size_bytes,
        captured_at=capture.capture_observed_at,
        content_type=capture.capture_content_type,
    )


def _server_clock(using: str) -> datetime:
    """Read PostgreSQL clock after verification, never transaction start time."""

    connection = connections[using]
    if connection.vendor != "postgresql":
        raise _block("Origin qualification requires PostgreSQL", "ORIGIN_DATABASE_REQUIRED")
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cursor.fetchone()
    except DatabaseError as error:
        raise _block("Database server clock is unavailable", "ORIGIN_CLOCK_INVALID") from error
    if row is None or len(row) != 1:
        raise _block("Database server clock is unavailable", "ORIGIN_CLOCK_INVALID")
    return _utc(row[0], field_name="database server clock")


def _reference_from_row(
    row: FinancialNumericSourceDocumentCaptureModel,
) -> FinancialNumericSourceDocumentCaptureReference:
    """Rebuild the exact numeric source selector stored on the immutable row."""

    return FinancialNumericSourceDocumentCaptureReference(
        capture_id=row.capture_id,
        document_id=row.document_id,
        issuer=row.issuer,
        canonical_url=row.canonical_url,
        body_sha256=row.body_sha256,
        body_size_bytes=row.body_size_bytes,
        captured_at=row.response_completed_at,
        content_type=row.content_type,
    )


def _read_stored_snapshot(
    row: FinancialNumericSourceDocumentCaptureModel,
    *,
    known_at: datetime,
) -> tuple[FinancialNumericSourceOriginSnapshot, str]:
    """Decode the snapshot and bind its hash, capture UUID, and record clock to the row."""

    payload: object = row.origin_snapshot
    digest: object = row.origin_snapshot_sha256
    if payload is None or digest is None:
        raise _block("Capture has no source-origin snapshot", "ORIGIN_SNAPSHOT_UNAVAILABLE")
    try:
        snapshot = decode_origin_snapshot(payload, digest)
    except (FinancialNumericOriginSnapshotCodecError, DataValidationError) as error:
        raise _block(
            "Stored source-origin snapshot failed integrity verification",
            "ORIGIN_SNAPSHOT_INVALID",
        ) from error
    if (
        snapshot.snapshot_id != row.capture_id
        or snapshot.recorded_at != row.recorded_at
        or snapshot.capture_reference != _reference_from_row(row)
        or snapshot.dataset_key != row.dataset_key
        or snapshot.deployment_region != row.deployment_region
        or snapshot.provider.provider_id != row.provider_id
        or snapshot.provider.name != row.provider_name_snapshot
        or snapshot.provider.source_type != row.provider_source_type_snapshot
        or snapshot.recorded_at > known_at
    ):
        raise _block(
            "Stored source-origin snapshot differs from the exact capture row",
            "ORIGIN_SNAPSHOT_INVALID",
        )
    return snapshot, cast(str, digest)


class DjangoFinancialNumericOriginSnapshotReader:
    """Verify configured-origin snapshots beside existing numeric capture checks."""

    def __init__(
        self,
        *,
        capture_repository: DjangoFinancialNumericSourceCaptureRepository,
    ) -> None:
        """Reuse the exact capture repository and its established DB alias."""

        if type(capture_repository) is not DjangoFinancialNumericSourceCaptureRepository:
            raise TypeError(
                "capture_repository must be the exact Django numeric capture repository"
            )
        self._capture_repository = capture_repository

    @property
    def database_alias(self) -> str:
        """Expose the alias shared by numeric captures and their successful egress audit."""

        return self._capture_repository.database_alias

    def verify_current(
        self,
        official_source: FinancialStatutorySourceIdentity,
        statutory_capture: StatutorySourceCaptureReference,
        *,
        known_at: datetime,
    ) -> FinancialV3OfficialSourceOriginSnapshot:
        """Lock the capture/provider/audit, then compare live config to its saved snapshot."""

        reference = _capture_reference_from_statutory(statutory_capture)
        cutoff = _utc(known_at, field_name="known_at")
        try:
            locked = self._capture_repository.lock_capture_for_uow(reference)
            verified = self._capture_repository.verify_locked_capture(locked, known_at=cutoff)
        except FinancialNumericCatalogEvidenceError as error:
            raise _block(
                "Exact numeric capture or audit is unavailable", "ORIGIN_CAPTURE_INVALID"
            ) from error
        if verified.reference != reference or not verified.body:
            raise _block(
                "Numeric response body does not match its exact capture", "ORIGIN_CAPTURE_INVALID"
            )
        snapshot, digest = self._read_current_snapshot(locked, reference=reference, known_at=cutoff)
        checked_at = _server_clock(self.database_alias)
        if cutoff > checked_at:
            raise _block(
                "Current origin cutoff is later than the database clock", "ORIGIN_FUTURE_CUTOFF"
            )
        return self._observation(
            official_source=official_source,
            statutory_capture=statutory_capture,
            numeric_capture=reference,
            snapshot=snapshot,
            snapshot_digest=digest,
            known_at=cutoff,
            checked_at=checked_at,
        )

    def verify_point_in_time(
        self,
        official_source: FinancialStatutorySourceIdentity,
        statutory_capture: StatutorySourceCaptureReference,
        *,
        known_at: datetime,
    ) -> FinancialV3OfficialSourceOriginSnapshot:
        """Use the original saved profile snapshot, exact numeric body, and audit at cutoff."""

        reference = _capture_reference_from_statutory(statutory_capture)
        cutoff = _utc(known_at, field_name="known_at")
        try:
            verified = self._capture_repository.read_verified_capture(reference, known_at=cutoff)
        except FinancialNumericCatalogEvidenceError as error:
            raise _block(
                "Exact numeric capture or historical audit is unavailable",
                "ORIGIN_CAPTURE_INVALID",
            ) from error
        row = (
            FinancialNumericSourceDocumentCaptureModel._default_manager.using(self.database_alias)
            .select_related("provider")
            .filter(capture_id=reference.capture_id)
            .first()
        )
        if row is None:
            raise _block("Exact numeric source capture is missing", "ORIGIN_CAPTURE_INVALID")
        snapshot, digest = _read_stored_snapshot(row, known_at=cutoff)
        if verified.capture_recorded_at != snapshot.recorded_at or verified.reference != reference:
            raise _block(
                "Historical capture differs from saved origin identity", "ORIGIN_SNAPSHOT_INVALID"
            )
        checked_at = _server_clock(self.database_alias)
        if cutoff > checked_at:
            raise _block(
                "PIT origin cutoff is later than the database clock", "ORIGIN_FUTURE_CUTOFF"
            )
        return self._observation(
            official_source=official_source,
            statutory_capture=statutory_capture,
            numeric_capture=reference,
            snapshot=snapshot,
            snapshot_digest=digest,
            known_at=cutoff,
            checked_at=checked_at,
        )

    def _read_current_snapshot(
        self,
        locked: LockedFinancialNumericSourceCapture,
        *,
        reference: FinancialNumericSourceDocumentCaptureReference,
        known_at: datetime,
    ) -> tuple[FinancialNumericSourceOriginSnapshot, str]:
        """Re-read locked live config and compare its exact serialized facts and hash."""

        snapshot, digest = _read_stored_snapshot(locked.row, known_at=known_at)
        try:
            seed = load_origin_snapshot_seed(
                provider=locked.provider,
                capture=reference,
                using=self.database_alias,
            )
            current = make_origin_snapshot(
                seed=seed,
                capture_reference=reference,
                dataset_key=locked.row.dataset_key,
                deployment_region=locked.row.deployment_region,
                recorded_at=locked.row.recorded_at,
            )
            current_payload, current_digest = encode_origin_snapshot(current)
        except (DataValidationError, TypeError, ValueError) as error:
            raise _block(
                "Current source configuration no longer matches its snapshot",
                "ORIGIN_CONFIG_CHANGED",
            ) from error
        if current_payload != locked.row.origin_snapshot or current_digest != digest:
            raise _block(
                "Current source configuration differs from capture-time snapshot",
                "ORIGIN_CONFIG_CHANGED",
            )
        return snapshot, digest

    @staticmethod
    def _observation(
        *,
        official_source: FinancialStatutorySourceIdentity,
        statutory_capture: StatutorySourceCaptureReference,
        numeric_capture: FinancialNumericSourceDocumentCaptureReference,
        snapshot: FinancialNumericSourceOriginSnapshot,
        snapshot_digest: str,
        known_at: datetime,
        checked_at: datetime,
    ) -> FinancialV3OfficialSourceOriginSnapshot:
        """Validate complete source/capture bindings and map to E1's typed origin port."""

        try:
            return FinancialV3OfficialSourceOriginSnapshot(
                official_source=official_source,
                statutory_capture=statutory_capture,
                numeric_capture=numeric_capture,
                profile=snapshot.profile,
                selected_rule_index=snapshot.selected_rule_index,
                provider_id=snapshot.provider.provider_id,
                provider_name=snapshot.provider.name,
                provider_source_type=snapshot.provider.source_type,
                provider_active=snapshot.provider.is_active,
                provider_updated_at=snapshot.provider.updated_at,
                publisher_code=snapshot.publisher.code,
                publisher_name=snapshot.publisher.canonical_name,
                publisher_class=snapshot.publisher.publisher_class,
                publisher_website=snapshot.publisher.website,
                publisher_active=snapshot.publisher.is_active,
                publisher_updated_at=snapshot.publisher.updated_at,
                numeric_capture_success_audit_count=1,
                configuration_sha256=snapshot.configuration_sha256,
                origin_snapshot_id=str(snapshot.snapshot_id),
                origin_snapshot_version=snapshot.schema_version,
                origin_snapshot_sha256=snapshot_digest,
                origin_snapshot_recorded_at=snapshot.recorded_at,
                known_at=known_at,
                checked_at=checked_at,
            )
        except (TypeError, ValueError) as error:
            raise _block(
                "Official source, capture, and origin snapshot disagree",
                "ORIGIN_BINDING_INVALID",
            ) from error


__all__ = [
    "DjangoFinancialNumericOriginSnapshotReader",
    "FinancialNumericOriginSnapshotError",
]
