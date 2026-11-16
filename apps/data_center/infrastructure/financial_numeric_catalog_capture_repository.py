"""Exact retained-byte and provider-egress verification for numeric source docs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from django.db import DatabaseError, IntegrityError, connections, transaction
from django.utils import timezone

from apps.data_center.application.statutory_source_documents import (
    StatutorySourceDocumentBodyStorePort,
)
from apps.data_center.domain.egress_routing import target_hostname
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.provider_document_response import (
    PUBLIC_DOCUMENT_SOURCE_TYPE,
    ProviderDocumentResponseCapture,
    normalize_document_content_type,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.statutory_source_documents import StatutorySourceBodyReference
from apps.data_center.infrastructure.egress_models import EgressRequestAuditModel
from apps.data_center.infrastructure.financial_numeric_catalog_models import (
    FinancialNumericSourceDocumentCaptureModel,
)
from apps.data_center.infrastructure.financial_numeric_origin_snapshot_capture import (
    derive_origin_snapshot_for_capture,
    prepare_origin_snapshot_seed_for_capture,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.statutory_source_models import (
    _activate_statutory_source_uow,
    _claim_statutory_source_insert,
    _StatutorySourceImmutableModel,
)
from core.exceptions import DataValidationError

_RowT = TypeVar("_RowT", bound=_StatutorySourceImmutableModel)


class FinancialNumericCatalogEvidenceError(DataValidationError):
    """Stable failure for missing, conflicting, or corrupted catalog evidence."""

    default_message = "Financial numeric catalog evidence is unavailable or invalid."
    default_code = "FINANCIAL_NUMERIC_CATALOG_EVIDENCE_INVALID"


@dataclass(frozen=True, slots=True)
class VerifiedFinancialNumericSourceCapture:
    """Infrastructure-only result after exact metadata, audit, provider, and bytes checks."""

    reference: FinancialNumericSourceDocumentCaptureReference
    response_completed_at: datetime
    capture_recorded_at: datetime
    body: bytes


@dataclass(frozen=True, slots=True)
class LockedFinancialNumericSourceCapture:
    """Exact capture, provider, and audit rows locked by the caller's transaction."""

    reference: FinancialNumericSourceDocumentCaptureReference
    row: FinancialNumericSourceDocumentCaptureModel
    provider: ProviderConfigModel
    audit: EgressRequestAuditModel


def _invalid(
    message: str, code: str = "FINANCIAL_NUMERIC_CATALOG_EVIDENCE_INVALID"
) -> FinancialNumericCatalogEvidenceError:
    """Classify one persistence/evidence failure without exposing source bytes."""

    return FinancialNumericCatalogEvidenceError(message, code=code)


def _insert_claimed(model_type: type[_RowT], values: dict[str, object], *, using: str) -> _RowT:
    """Insert one exact immutable row using the existing private append-only guard."""

    with _activate_statutory_source_uow() as token:
        with _claim_statutory_source_insert(
            token=token,
            using=using,
            model_type=model_type,
            expected_values=values,
        ):
            return model_type._default_manager.using(using).create(**values)


def _same_reference(
    left: FinancialNumericSourceDocumentCaptureReference,
    right: FinancialNumericSourceDocumentCaptureReference,
) -> bool:
    """Compare the complete unversioned capture identity exactly."""

    return left.to_dict() == right.to_dict()


class DjangoFinancialNumericSourceCaptureRepository:
    """Retain exact capture bytes and metadata without creating a statutory revision.

    The adapter reuses only ``StatutorySourceBodyStore``'s exact byte persistence
    port and append-only insert guard. It never constructs a statutory revision
    or publisher-native ``source_version``. A successful egress audit and stable
    provider id/name/source_type are required before a capture can be read back.
    Provider ``is_active`` is checked when acquiring a new capture, but is not a
    condition for later historical byte verification.
    """

    def __init__(
        self,
        *,
        body_store: StatutorySourceDocumentBodyStorePort,
        using: str,
        clock: Callable[[], datetime] = timezone.now,
    ) -> None:
        """Bind a byte store, explicit database alias, and trusted UTC clock."""

        if body_store is None:
            raise TypeError("financial numeric source body store is required")
        if type(using) is not str or not using or using != using.strip() or len(using) > 128:
            raise ValueError("database alias must be explicit bounded text")
        self._body_store = body_store
        self._using = using
        self._clock = clock

    def _now(self) -> datetime:
        """Sample and normalize a trusted server recording clock."""

        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise _invalid(
                "Trusted catalog recording time is invalid.",
                "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
            )
        try:
            return value.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise _invalid(
                "Trusted catalog recording time is invalid.",
                "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
            ) from error

    def _require_postgres_read_committed_uow(self) -> None:
        """Require existing caller transaction and PostgreSQL READ COMMITTED semantics."""

        database = connections[self._using]
        if not database.in_atomic_block or database.vendor != "postgresql":
            raise _invalid(
                "Capture evidence locking requires a caller-owned PostgreSQL transaction.",
                "FINANCIAL_NUMERIC_CAPTURE_UOW_REQUIRED",
            )
        try:
            with database.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                row = cursor.fetchone()
        except DatabaseError as error:
            raise _invalid(
                "Capture evidence transaction isolation is unavailable.",
                "FINANCIAL_NUMERIC_CATALOG_UOW_INVALID",
            ) from error
        if row is None or len(row) != 1 or row[0] != "read committed":
            raise _invalid(
                "Capture evidence locking requires PostgreSQL READ COMMITTED isolation.",
                "FINANCIAL_NUMERIC_CATALOG_UOW_INVALID",
            )

    @property
    def database_alias(self) -> str:
        """Expose the exact database alias used for capture metadata and audits."""

        return self._using

    def _provider(
        self,
        provider_id: int,
        *,
        require_active: bool,
        for_update: bool = False,
    ) -> ProviderConfigModel:
        """Load the exact public-document provider identity without credential access."""

        query = ProviderConfigModel._default_manager.using(self._using)
        if for_update:
            query = query.select_for_update()
        provider = query.filter(pk=provider_id).first()
        if (
            provider is None
            or provider.source_type != PUBLIC_DOCUMENT_SOURCE_TYPE
            or (require_active and provider.is_active is not True)
        ):
            raise _invalid("A matching public-document provider is unavailable.")
        return provider

    def _require_successful_audit(
        self,
        *,
        capture_id: UUID,
        provider_id: int,
        dataset_key: str,
        deployment_region: str,
        target_host: str,
        egress_id: int | None,
        attempt: int,
        response_completed_at: datetime,
        known_at: datetime,
    ) -> None:
        """Require one persisted successful audit for this precise routed attempt."""

        query = EgressRequestAuditModel._default_manager.using(self._using).filter(
            request_id=capture_id,
            provider_id=provider_id,
            dataset_key=dataset_key,
            deployment_region=deployment_region,
            target_host=target_host,
            egress_id=egress_id,
            attempt=attempt,
            outcome="success",
            created_at__gte=response_completed_at,
        )
        audits = tuple(query.filter(created_at__lte=known_at).order_by("pk")[:2])
        if len(audits) != 1:
            raise _invalid(
                "Exact successful controlled-egress audit is missing or ambiguous.",
                "FINANCIAL_NUMERIC_CAPTURE_AUDIT_UNAVAILABLE",
            )
        if audits[0].created_at > known_at:
            raise _invalid(
                "Successful controlled-egress audit is later than the requested cutoff.",
                "FINANCIAL_NUMERIC_CAPTURE_AUDIT_UNAVAILABLE",
            )

    def _lock_successful_audit(
        self,
        *,
        capture_id: UUID,
        provider_id: int,
        dataset_key: str,
        deployment_region: str,
        target_host: str,
        egress_id: int | None,
        attempt: int,
        response_completed_at: datetime,
    ) -> EgressRequestAuditModel:
        """Lock one exact successful audit row without sampling a pre-lock cutoff."""

        audits = tuple(
            EgressRequestAuditModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                request_id=capture_id,
                provider_id=provider_id,
                dataset_key=dataset_key,
                deployment_region=deployment_region,
                target_host=target_host,
                egress_id=egress_id,
                attempt=attempt,
                outcome="success",
                created_at__gte=response_completed_at,
            )
            .order_by("pk")[:2]
        )
        if len(audits) != 1:
            raise _invalid(
                "Exact successful controlled-egress audit is missing or ambiguous.",
                "FINANCIAL_NUMERIC_CAPTURE_AUDIT_UNAVAILABLE",
            )
        return audits[0]

    @staticmethod
    def _audit_matches_capture(
        audit: EgressRequestAuditModel,
        *,
        capture_id: UUID,
        provider_id: int,
        dataset_key: str,
        deployment_region: str,
        target_host: str,
        egress_id: int | None,
        attempt: int,
        response_completed_at: datetime,
        known_at: datetime,
    ) -> bool:
        """Require a locked audit row to match every exact route and time field."""

        return (
            audit.request_id == capture_id
            and audit.provider_id == provider_id
            and audit.dataset_key == dataset_key
            and audit.deployment_region == deployment_region
            and audit.target_host == target_host
            and audit.egress_id == egress_id
            and audit.attempt == attempt
            and audit.outcome == "success"
            and response_completed_at <= audit.created_at <= known_at
        )

    def append_document_capture(
        self,
        *,
        provider_id: int,
        dataset_key: str,
        deployment_region: str,
        reference: FinancialNumericSourceDocumentCaptureReference,
        response: ProviderDocumentResponseCapture,
    ) -> FinancialNumericSourceDocumentCaptureReference:
        """Read back the exact body, verify successful egress, and append capture metadata."""

        if (
            type(provider_id) is not int
            or provider_id <= 0
            or type(dataset_key) is not str
            or not dataset_key
            or dataset_key != dataset_key.strip()
            or len(dataset_key) > 120
            or type(deployment_region) is not str
            or not deployment_region
            or deployment_region != deployment_region.strip()
            or len(deployment_region) > 40
            or type(reference) is not FinancialNumericSourceDocumentCaptureReference
            or type(response) is not ProviderDocumentResponseCapture
        ):
            raise _invalid("Financial numeric document capture input is invalid.")
        try:
            media_type = normalize_document_content_type(response.content_type)
            expected_host = target_hostname(reference.canonical_url)
        except (TypeError, ValueError) as error:
            raise _invalid("Financial numeric document capture address is invalid.") from error
        if (
            response.request_id != reference.capture_id
            or response.body_sha256 != reference.body_sha256
            or response.body_size_bytes != reference.body_size_bytes
            or response.response_completed_at != reference.captured_at
            or response.content_type != reference.content_type
            or response.target_url_sha256
            != hashlib.sha256(reference.canonical_url.encode("utf-8")).hexdigest()
            or response.target_host != expected_host
            or response.transport is not ProviderResponseTransport.EGRESS
            or not 200 <= response.status_code < 300
            or media_type != normalize_document_content_type(reference.content_type)
        ):
            raise _invalid("Document response differs from its exact request/capture reference.")
        try:
            with transaction.atomic(using=self._using):
                self._require_postgres_read_committed_uow()
                existing = (
                    FinancialNumericSourceDocumentCaptureModel._default_manager.using(self._using)
                    .select_for_update(of=("self",))
                    .filter(capture_id=response.request_id)
                    .first()
                )
                provider = self._provider(
                    provider_id,
                    require_active=True,
                    for_update=True,
                )
                audit = self._lock_successful_audit(
                    capture_id=response.request_id,
                    provider_id=provider_id,
                    dataset_key=dataset_key,
                    deployment_region=deployment_region,
                    target_host=response.target_host,
                    egress_id=response.egress_id,
                    attempt=response.attempt,
                    response_completed_at=response.response_completed_at,
                )
                if existing is not None:
                    now = self._now()
                    existing_body = self._verify_model_capture(
                        existing,
                        known_at=now,
                        locked_provider=provider,
                        locked_audit=audit,
                    )
                    if not _same_reference(self._reference_from_model(existing), reference):
                        raise _invalid(
                            "Capture UUID is already bound to different document metadata."
                        )
                    if existing_body != response.body:
                        raise _invalid("Capture UUID is already bound to different body bytes.")
                    return reference
                body_reference = self._body_store.store(response.request_id, response.body)
                readback = self._body_store.read(body_reference)
                if (
                    type(body_reference) is not StatutorySourceBodyReference
                    or body_reference.capture_id != response.request_id
                    or not body_reference.verifies(response.body)
                    or readback != response.body
                ):
                    raise _invalid(
                        "Source document body store failed exact write/readback verification."
                    )
                origin_seed = prepare_origin_snapshot_seed_for_capture(
                    provider=provider,
                    capture_reference=reference,
                    using=self._using,
                )
                now = self._now()
                if response.response_completed_at > now or audit.created_at > now:
                    raise _invalid(
                        "Document response and successful audit must be known at capture time.",
                        "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
                    )
                origin_snapshot, origin_snapshot_digest = derive_origin_snapshot_for_capture(
                    seed=origin_seed,
                    capture_reference=reference,
                    dataset_key=dataset_key,
                    deployment_region=deployment_region,
                    recorded_at=now,
                )
                values: dict[str, object] = {
                    "capture_id": response.request_id,
                    "provider_id": provider_id,
                    "provider_name_snapshot": provider.name,
                    "provider_source_type_snapshot": provider.source_type,
                    "dataset_key": dataset_key,
                    "deployment_region": deployment_region,
                    "issuer": reference.issuer,
                    "document_id": reference.document_id,
                    "canonical_url": reference.canonical_url,
                    "target_url_sha256": response.target_url_sha256,
                    "target_host": response.target_host,
                    "request_attempt": response.attempt,
                    "egress_id": response.egress_id,
                    "transport": response.transport.value,
                    "status_code": response.status_code,
                    "content_type": response.content_type,
                    "response_completed_at": response.response_completed_at,
                    "body_sha256": response.body_sha256,
                    "body_size_bytes": response.body_size_bytes,
                    "body_reference": body_reference.reference,
                    "origin_snapshot": origin_snapshot,
                    "origin_snapshot_sha256": origin_snapshot_digest,
                    "recorded_at": now,
                }
                with transaction.atomic(using=self._using):
                    created = _insert_claimed(
                        FinancialNumericSourceDocumentCaptureModel,
                        values,
                        using=self._using,
                    )
        except IntegrityError as error:
            raise _invalid("Document capture metadata violates a catalog constraint.") from error
        if created.capture_id != reference.capture_id:
            raise _invalid("Document capture metadata failed exact identity readback.")
        return self._reference_from_model(created)

    def lock_capture_for_uow(
        self,
        reference: FinancialNumericSourceDocumentCaptureReference,
    ) -> LockedFinancialNumericSourceCapture:
        """Lock the exact capture, provider, and matching audit in the caller's transaction.

        The lock order is capture, provider, then egress audit. This method
        requires an existing transaction and leaves it open for the caller to
        verify the bytes and commit its owning operation.
        """

        if type(reference) is not FinancialNumericSourceDocumentCaptureReference:
            raise _invalid(
                "Capture UOW locking requires a typed reference and caller transaction.",
                "FINANCIAL_NUMERIC_CAPTURE_UOW_REQUIRED",
            )
        self._require_postgres_read_committed_uow()
        row = (
            FinancialNumericSourceDocumentCaptureModel._default_manager.using(self._using)
            .select_for_update(of=("self",))
            .filter(capture_id=reference.capture_id)
            .first()
        )
        if row is None:
            raise _invalid(
                "Exact retained document capture is missing.",
                "FINANCIAL_NUMERIC_CAPTURE_UNAVAILABLE",
            )
        actual_reference = self._reference_from_model(row)
        if not _same_reference(actual_reference, reference):
            raise _invalid("Persisted document capture differs from qualification reference.")
        provider = self._provider(row.provider_id, require_active=False, for_update=True)
        audit = self._lock_successful_audit(
            capture_id=row.capture_id,
            provider_id=row.provider_id,
            dataset_key=row.dataset_key,
            deployment_region=row.deployment_region,
            target_host=row.target_host,
            egress_id=row.egress_id,
            attempt=row.request_attempt,
            response_completed_at=row.response_completed_at,
        )
        return LockedFinancialNumericSourceCapture(
            reference=reference,
            row=row,
            provider=provider,
            audit=audit,
        )

    def verify_locked_capture(
        self,
        locked_capture: LockedFinancialNumericSourceCapture,
        *,
        known_at: datetime,
    ) -> VerifiedFinancialNumericSourceCapture:
        """Verify bytes and clocks after the caller has acquired every related row lock."""

        if type(locked_capture) is not LockedFinancialNumericSourceCapture:
            raise _invalid("Capture lock handle is not the infrastructure's typed result.")
        if not connections[self._using].in_atomic_block:
            raise _invalid(
                "Locked capture verification requires the caller's open transaction.",
                "FINANCIAL_NUMERIC_CAPTURE_UOW_REQUIRED",
            )
        cutoff = self._utc_cutoff(known_at)
        body = self._verify_model_capture(
            locked_capture.row,
            known_at=cutoff,
            locked_provider=locked_capture.provider,
            locked_audit=locked_capture.audit,
        )
        actual_reference = self._reference_from_model(locked_capture.row)
        if not _same_reference(actual_reference, locked_capture.reference):
            raise _invalid("Locked capture no longer matches its exact identity.")
        return VerifiedFinancialNumericSourceCapture(
            reference=actual_reference,
            response_completed_at=locked_capture.row.response_completed_at,
            capture_recorded_at=locked_capture.row.recorded_at,
            body=body,
        )

    @staticmethod
    def _utc_cutoff(known_at: datetime) -> datetime:
        """Normalize one explicit aware cutoff or fail closed."""

        if (
            type(known_at) is not datetime
            or known_at.tzinfo is None
            or known_at.utcoffset() is None
        ):
            raise _invalid(
                "Capture knowledge cutoff must be timezone-aware.",
                "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
            )
        try:
            return known_at.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise _invalid(
                "Capture knowledge cutoff is invalid.",
                "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
            ) from error

    def read_verified_capture(
        self,
        reference: FinancialNumericSourceDocumentCaptureReference,
        *,
        known_at: datetime,
    ) -> VerifiedFinancialNumericSourceCapture:
        """Verify persisted capture metadata, source provider identity, audit, and body bytes."""

        if type(reference) is not FinancialNumericSourceDocumentCaptureReference:
            raise _invalid("Document capture reference is not typed.")
        if (
            type(known_at) is not datetime
            or known_at.tzinfo is None
            or known_at.utcoffset() is None
        ):
            raise _invalid(
                "Capture knowledge cutoff must be timezone-aware.",
                "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
            )
        try:
            cutoff = known_at.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise _invalid(
                "Capture knowledge cutoff is invalid.", "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID"
            ) from error
        row = (
            FinancialNumericSourceDocumentCaptureModel._default_manager.using(self._using)
            .select_related("provider")
            .filter(capture_id=reference.capture_id)
            .first()
        )
        if row is None:
            raise _invalid(
                "Exact retained document capture is missing.",
                "FINANCIAL_NUMERIC_CAPTURE_UNAVAILABLE",
            )
        body = self._verify_model_capture(row, known_at=cutoff)
        actual_reference = self._reference_from_model(row)
        if not _same_reference(actual_reference, reference):
            raise _invalid("Persisted document capture differs from qualification reference.")
        return VerifiedFinancialNumericSourceCapture(
            reference=actual_reference,
            response_completed_at=row.response_completed_at,
            capture_recorded_at=row.recorded_at,
            body=body,
        )

    def _verify_model_capture(
        self,
        row: FinancialNumericSourceDocumentCaptureModel,
        *,
        known_at: datetime,
        locked_provider: ProviderConfigModel | None = None,
        locked_audit: EgressRequestAuditModel | None = None,
    ) -> bytes:
        """Recheck capture identity, provider, audit, and return verified retained bytes."""

        provider = locked_provider if locked_provider is not None else row.provider
        if (
            row.recorded_at > known_at
            or row.response_completed_at > known_at
            or row.transport != ProviderResponseTransport.EGRESS.value
            or row.status_code < 200
            or row.status_code >= 300
            or provider.pk != row.provider_id
            or provider.source_type != row.provider_source_type_snapshot
            or provider.name != row.provider_name_snapshot
            or row.provider_source_type_snapshot != PUBLIC_DOCUMENT_SOURCE_TYPE
        ):
            raise _invalid("Stored capture time, transport, or provider identity is inconsistent.")
        try:
            media_type = normalize_document_content_type(row.content_type)
            expected_host = target_hostname(row.canonical_url)
            reference = self._reference_from_model(row)
        except (TypeError, ValueError) as error:
            raise _invalid("Stored document capture metadata is invalid.") from error
        if (
            media_type != normalize_document_content_type(reference.content_type)
            or hashlib.sha256(row.canonical_url.encode("utf-8")).hexdigest()
            != row.target_url_sha256
            or expected_host != row.target_host
            or row.recorded_at < row.response_completed_at
        ):
            raise _invalid("Stored document capture metadata differs from its request identity.")
        if locked_audit is None:
            self._require_successful_audit(
                capture_id=row.capture_id,
                provider_id=row.provider_id,
                dataset_key=row.dataset_key,
                deployment_region=row.deployment_region,
                target_host=row.target_host,
                egress_id=row.egress_id,
                attempt=row.request_attempt,
                response_completed_at=row.response_completed_at,
                known_at=known_at,
            )
        elif not self._audit_matches_capture(
            locked_audit,
            capture_id=row.capture_id,
            provider_id=row.provider_id,
            dataset_key=row.dataset_key,
            deployment_region=row.deployment_region,
            target_host=row.target_host,
            egress_id=row.egress_id,
            attempt=row.request_attempt,
            response_completed_at=row.response_completed_at,
            known_at=known_at,
        ):
            raise _invalid("Locked successful egress audit differs from capture metadata.")
        body_reference = StatutorySourceBodyReference(
            capture_id=row.capture_id,
            reference=row.body_reference,
            body_sha256=row.body_sha256,
            body_size_bytes=row.body_size_bytes,
        )
        try:
            body = self._body_store.read(body_reference)
        except (DataValidationError, OSError, TypeError, ValueError) as error:
            raise _invalid("Retained document bytes are unavailable or corrupt.") from error
        if not body_reference.verifies(body):
            raise _invalid("Retained document bytes do not match capture metadata.")
        return body

    @staticmethod
    def _reference_from_model(
        row: FinancialNumericSourceDocumentCaptureModel,
    ) -> FinancialNumericSourceDocumentCaptureReference:
        """Rebuild a local document-capture reference without a fake source version."""

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


__all__ = [
    "DjangoFinancialNumericSourceCaptureRepository",
    "FinancialNumericCatalogEvidenceError",
    "LockedFinancialNumericSourceCapture",
    "VerifiedFinancialNumericSourceCapture",
]
