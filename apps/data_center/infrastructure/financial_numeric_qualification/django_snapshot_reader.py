"""Read actual catalog entry and Owner-event metadata for verifier resolutions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError

from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericCatalogEntrySnapshotReadPort,
)
from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogAction,
    FinancialNumericCatalogEntry,
    FinancialNumericCatalogOwnerEvent,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)
from apps.data_center.infrastructure.financial_numeric_catalog_models import (
    FinancialMetricSourceCatalogEntryModel,
    FinancialMetricSourceCatalogOwnerEventModel,
)


class DjangoFinancialNumericCatalogEntrySnapshotReader(
    FinancialNumericCatalogEntrySnapshotReadPort
):
    """Build one typed entry snapshot from the persisted entry, capture, and event rows.

    This reader returns metadata only. The authoritative repository must first
    resolve the qualification after checking retained documentation bytes,
    egress audit, provider identity, endpoint, source context, and clocks.
    """

    def __init__(self, *, using: str) -> None:
        """Bind the exact database alias used by catalog metadata queries."""

        if type(using) is not str or not using or using != using.strip() or len(using) > 128:
            raise ValueError("database alias must be explicit bounded text")
        self._using = using

    @property
    def database_alias(self) -> str:
        """Expose the alias used by the metadata reader."""

        return self._using

    def read_exact_entry(
        self,
        qualification: FinancialNumericSourceQualification,
        *,
        known_at: datetime,
    ) -> FinancialNumericCatalogEntry | None:
        """Read one uniquely matching persisted entry and only events known at cutoff."""

        if type(qualification) is not FinancialNumericSourceQualification:
            return None
        cutoff = _utc_cutoff(known_at)
        if cutoff is None:
            return None
        try:
            rows = tuple(
                FinancialMetricSourceCatalogEntryModel._default_manager.using(self._using)
                .filter(
                    qualification_identity=qualification.identity,
                    qualification_sha256=qualification.content_hash,
                    contract_identity=qualification.contract.identity,
                    contract_sha256=qualification.contract.content_hash,
                    document_capture_id=qualification.document_capture.capture_id,
                    recorded_at__lte=cutoff,
                )
                .select_related("document_capture")
                .order_by("entry_id")[:2]
            )
            if len(rows) != 1:
                return None
            row = rows[0]
            restored = self._restored_qualification(row)
            if restored != qualification:
                return None
            capture = row.document_capture
            capture_reference = FinancialNumericSourceDocumentCaptureReference(
                capture_id=capture.capture_id,
                document_id=capture.document_id,
                issuer=capture.issuer,
                canonical_url=capture.canonical_url,
                body_sha256=capture.body_sha256,
                body_size_bytes=capture.body_size_bytes,
                captured_at=capture.response_completed_at,
                content_type=capture.content_type,
            )
            if (
                capture_reference != qualification.document_capture
                or capture.recorded_at > cutoff
                or capture.response_completed_at > cutoff
            ):
                return None
            event_rows = tuple(
                FinancialMetricSourceCatalogOwnerEventModel._default_manager.using(self._using)
                .filter(entry_id=row.entry_id, recorded_at__lte=cutoff)
                .select_related("actor")
                .order_by("recorded_at", "event_id")[:3]
            )
            if len(event_rows) > 2:
                return None
            owner_events: list[FinancialNumericCatalogOwnerEvent] = []
            for event_row in event_rows:
                action = _catalog_action(event_row.action)
                actor_id = event_row.actor.pk
                actor_username = event_row.actor.get_username()
                if (
                    action is None
                    or type(actor_id) is not int
                    or actor_id <= 0
                    or event_row.actor_username_snapshot != actor_username
                    or event_row.qualification_identity != qualification.identity
                    or event_row.qualification_sha256 != qualification.content_hash
                ):
                    return None
                owner_events.append(
                    FinancialNumericCatalogOwnerEvent(
                        event_id=event_row.event_id,
                        entry_id=row.entry_id,
                        action=action,
                        qualification_identity=event_row.qualification_identity,
                        qualification_sha256=event_row.qualification_sha256,
                        actor_id=actor_id,
                        actor_username=actor_username,
                        event_at=event_row.event_at,
                        recorded_at=event_row.recorded_at,
                    )
                )
            return FinancialNumericCatalogEntry(
                entry_id=row.entry_id,
                qualification=restored,
                recorded_at=row.recorded_at,
                capture_recorded_at=capture.recorded_at,
                owner_events=tuple(owner_events),
            )
        except DatabaseError:
            raise
        except (AttributeError, ObjectDoesNotExist, TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _restored_qualification(
        row: FinancialMetricSourceCatalogEntryModel,
    ) -> FinancialNumericSourceQualification:
        """Restore exact row payload and verify its separately indexed identities."""

        qualification = FinancialNumericSourceQualification.from_payload(row.qualification)
        contract = qualification.contract
        if (
            qualification.identity != row.qualification_identity
            or qualification.content_hash != row.qualification_sha256
            or contract.identity != row.contract_identity
            or contract.content_hash != row.contract_sha256
            or contract.provider != row.contract_provider
            or contract.dataset_key != row.dataset_key
            or contract.metric_code != row.metric_code
            or qualification.document_capture.capture_id != row.document_capture_id
            or qualification.effective_from != row.effective_from
            or qualification.effective_until != row.effective_until
        ):
            raise ValueError("persisted catalog row differs from its exact qualification payload")
        return qualification


def _utc_cutoff(value: datetime) -> datetime | None:
    """Normalize only an explicitly aware UTC knowledge cutoff."""

    if type(value) is not datetime or value.tzinfo is None:
        return None
    try:
        if value.utcoffset() != timedelta(0):
            return None
        return value.astimezone(UTC)
    except (OverflowError, ValueError):
        return None


def _catalog_action(value: object) -> FinancialNumericCatalogAction | None:
    """Narrow only the two persisted Owner-event actions recognized by Domain."""

    if value == "apply":
        return "apply"
    if value == "revoke":
        return "revoke"
    return None


__all__ = ["DjangoFinancialNumericCatalogEntrySnapshotReader"]
