"""Cutoff-aware exact rereader for retained statutory source captures.

This adapter uses the existing immutable source repository and body store. It
also reads source-row ``recorded_at`` values and all visible capture clocks,
which the current public source repository result objects do not expose.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from django.db import connections

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
)
from apps.data_center.application.statutory_source_documents import (
    StatutorySourceDocumentBodyStorePort,
    StatutorySourceDocumentRepositoryPort,
)
from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture,
)
from apps.data_center.infrastructure.statutory_source_models import (
    StatutorySourceDocumentCaptureModel,
    StatutorySourceDocumentRevisionModel,
)
from core.exceptions import DataValidationError


def _utc(value: object, name: str) -> datetime:
    """Require an aware UTC clock and return its UTC-normalized instant."""

    if type(value) is not datetime or value.tzinfo is None:
        raise DataValidationError(f"{name} is not an aware timestamp.")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise DataValidationError(f"{name} is not an explicit UTC timestamp.")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise DataValidationError(f"{name} is outside the UTC range.") from error


class FinancialAvailabilityStatutorySourceRepositoryPort(
    StatutorySourceDocumentRepositoryPort, Protocol
):
    """Exact source repository with a publicly verified database alias."""

    @property
    def database_alias(self) -> str:
        """Return the alias used by exact revision and capture reads."""


class DjangoFinancialAvailabilitySourceReader:
    """Read an exact bound capture and derive first-seen from a verified visible capture.

    The bound capture is independently restored and body-verified by its UUID;
    the earliest observed time from another capture cannot stand in for it.
    READ COMMITTED reads are fenced by ordered SHARE locks on the two immutable
    source tables; the caller's explicit ``known_at`` remains unchanged.
    """

    def __init__(
        self,
        *,
        repository: FinancialAvailabilityStatutorySourceRepositoryPort,
        body_store: StatutorySourceDocumentBodyStorePort,
        using: str,
    ) -> None:
        """Bind the existing exact repository, body store and PostgreSQL alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be one explicit database alias")
        if connections[using].vendor != "postgresql":
            raise DataValidationError("C2 source reads require PostgreSQL server clocks.")
        if repository.database_alias != using:
            raise DataValidationError("C2 source repository and ORM reads use different aliases.")
        self._repository = repository
        self._body_store = body_store
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the alias containing exact source revision and capture rows."""

        return self._using

    def read_exact_capture(
        self,
        *,
        issuer: str,
        document_id: str,
        source_version: str,
        capture_id: UUID,
        known_at: datetime,
    ) -> FinancialAvailabilitySourceRead | None:
        """Rebuild exact source facts and body visible at explicit ``known_at``."""

        self._require_read_committed_transaction()
        cutoff = _utc(known_at, "known_at")
        if type(capture_id) is not UUID:
            raise DataValidationError("C2 source capture selector is invalid.")
        for value, maximum in (
            (issuer, 240),
            (document_id, 240),
            (source_version, 120),
        ):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > maximum
            ):
                raise DataValidationError("C2 native source selector is invalid.")

        start_now = self._server_now()
        if cutoff > start_now:
            raise DataValidationError("C2 source cutoff is in the future.")
        self._lock_source_tables()
        revision_rows = tuple(
            StatutorySourceDocumentRevisionModel._default_manager.using(self._using).filter(
                issuer=issuer, document_id=document_id, source_version=source_version
            )[:2]
        )
        if not revision_rows:
            return None
        if len(revision_rows) != 1:
            raise DataValidationError("C2 native source revision is ambiguous.")
        revision_row = revision_rows[0]
        revision_recorded_at = _utc(revision_row.recorded_at, "revision_recorded_at")
        if revision_recorded_at > cutoff or revision_recorded_at > start_now:
            return None
        revision = self._repository.get_revision_exact(
            issuer=issuer,
            document_id=document_id,
            source_version=source_version,
        )
        if revision is None:
            raise DataValidationError("C2 native source revision cannot be restored.")
        if revision.source_revision_sha256 != revision_row.source_revision_sha256:
            raise DataValidationError("C2 source revision digest changed on reread.")

        exact_capture_rows = tuple(
            StatutorySourceDocumentCaptureModel._default_manager.using(self._using).filter(
                capture_id=capture_id, revision_id=revision_row.pk
            )[:2]
        )
        if not exact_capture_rows:
            return None
        if len(exact_capture_rows) != 1:
            raise DataValidationError("C2 source capture identity is ambiguous.")
        exact_capture_row = exact_capture_rows[0]
        capture_recorded_at = _utc(exact_capture_row.recorded_at, "capture_recorded_at")
        capture_observed_at = _utc(exact_capture_row.captured_at, "capture_observed_at")
        if capture_recorded_at > cutoff or capture_observed_at > cutoff:
            return None
        bound_capture: RetainedStatutorySourceDocumentCapture | None = None
        bound_body: bytes | None = None
        first_seen_at: datetime | None = None
        visible_capture_rows = (
            StatutorySourceDocumentCaptureModel._default_manager.using(self._using)
            .filter(revision_id=revision_row.pk, recorded_at__lte=cutoff)
            .order_by("captured_at", "capture_id")
            .values_list(
                "capture_id",
                "captured_at",
                "recorded_at",
                "content_type",
                "body_reference",
            )
        )
        for (
            visible_id,
            captured_at_value,
            recorded_at_value,
            content_type,
            body_reference,
        ) in visible_capture_rows:
            captured_at = _utc(captured_at_value, "visible_capture.captured_at")
            recorded_at = _utc(recorded_at_value, "visible_capture.recorded_at")
            if recorded_at > cutoff or captured_at > recorded_at or captured_at > cutoff:
                raise DataValidationError("C2 visible source capture clocks are inconsistent.")
            visible_capture = self._repository.get_capture(visible_id)
            if visible_capture is None:
                raise DataValidationError("C2 visible source capture cannot be restored.")
            if (
                visible_capture.revision != revision
                or visible_capture.captured_at != captured_at_value
                or visible_capture.content_type != content_type
                or visible_capture.body_reference.reference != body_reference
            ):
                raise DataValidationError("C2 source capture differs from its exact database row.")
            visible_body = self._body_store.read(visible_capture.body_reference)
            if not revision.verifies_source_document(visible_body):
                raise DataValidationError("C2 retained statutory source body failed digest checks.")
            if first_seen_at is None:
                first_seen_at = captured_at
            if visible_id == capture_id:
                bound_capture = visible_capture
                bound_body = visible_body
            if first_seen_at is not None and bound_capture is not None and bound_body is not None:
                break
        if first_seen_at is None:
            raise DataValidationError("C2 source revision has no verified visible capture.")
        if bound_capture is None or bound_body is None:
            raise DataValidationError("C2 bound source capture is not visible or verified.")
        if bound_capture.capture_id != exact_capture_row.capture_id:
            raise DataValidationError("C2 bound source capture identity changed.")

        reference = StatutorySourceCaptureReference(
            issuer=revision.issuer,
            document_id=revision.document_id,
            source_version=revision.source_version,
            title=revision.title,
            legal_number=revision.legal_number,
            source_revision_sha256=revision.source_revision_sha256,
            capture_id=bound_capture.capture_id,
            capture_content_type=bound_capture.content_type,
            body_reference=bound_capture.body_reference.reference,
            canonical_url=revision.canonical_url,
            body_sha256=revision.body_sha256,
            body_size_bytes=revision.body_size_bytes,
            publication_date=revision.publication_date,
            source_effective_date=revision.effective_date,
            first_seen_at=first_seen_at,
            capture_observed_at=bound_capture.captured_at,
            revision_recorded_at=revision_recorded_at,
            capture_recorded_at=capture_recorded_at,
        )
        checked_at = self._completion_now()
        if checked_at < cutoff:
            raise DataValidationError("C2 source read completed before its knowledge cutoff.")
        return FinancialAvailabilitySourceRead(
            reference=reference,
            body=bound_body,
            checked_at=checked_at,
            known_at=cutoff,
        )

    def _server_now(self) -> datetime:
        """Sample database wall time to reject future cutoffs only."""

        with connections[self._using].cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cursor.fetchone()
        if row is None:
            raise DataValidationError("Database server clock is unavailable.")
        return _utc(row[0], "database_server_time")

    def _completion_now(self) -> datetime:
        """Sample the actual database wall clock after retained bytes are checked."""

        with connections[self._using].cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cursor.fetchone()
        if row is None:
            raise DataValidationError("Database source-check clock is unavailable.")
        return _utc(row[0], "source_check_completed_at")

    def _require_read_committed_transaction(self) -> None:
        """Require the existing PostgreSQL READ COMMITTED caller UOW."""

        connection = connections[self._using]
        if not connection.in_atomic_block:
            raise DataValidationError("C2 source reads require a caller-owned transaction.")
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            row = cursor.fetchone()
        if row is None or row[0] != "read committed":
            raise DataValidationError("C2 source reads require READ COMMITTED isolation.")

    def _lock_source_tables(self) -> None:
        """Fence source appends using fixed revision-then-capture SHARE locks."""

        connection = connections[self._using]
        table_names = (
            (
                StatutorySourceDocumentRevisionModel._meta.db_table,
                "dc_statutory_source_revision",
            ),
            (
                StatutorySourceDocumentCaptureModel._meta.db_table,
                "dc_statutory_source_capture",
            ),
        )
        with connection.cursor() as cursor:
            for actual_table, expected_table in table_names:
                if actual_table != expected_table or "." in actual_table:
                    raise DataValidationError("C2 statutory source table identity is unexpected.")
                unqualified = actual_table
                qualified = f"public.{actual_table}"
                cursor.execute(
                    "SELECT to_regclass(%s)::oid, to_regclass(%s)::oid",
                    [unqualified, qualified],
                )
                before_lock = cursor.fetchone()
                if (
                    before_lock is None
                    or before_lock[0] is None
                    or before_lock[1] is None
                    or before_lock[0] != before_lock[1]
                ):
                    raise DataValidationError("C2 statutory source table resolution is ambiguous.")
                quoted_table = (
                    f"{connection.ops.quote_name('public')}"
                    f".{connection.ops.quote_name(actual_table)}"
                )
                cursor.execute(f"LOCK TABLE {quoted_table} IN SHARE MODE")
                cursor.execute(
                    "SELECT to_regclass(%s)::oid, to_regclass(%s)::oid",
                    [unqualified, qualified],
                )
                after_lock = cursor.fetchone()
                if after_lock != before_lock:
                    raise DataValidationError("C2 statutory source table identity changed.")


__all__ = [
    "DjangoFinancialAvailabilitySourceReader",
    "FinancialAvailabilityStatutorySourceRepositoryPort",
]
