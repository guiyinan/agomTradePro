"""Append-only qualification and authenticated Owner-event repository."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.utils import timezone

from apps.data_center.application.financial_numeric_catalog import (
    FinancialNumericSourceCatalogRepositoryPort,
)
from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogAction,
    FinancialNumericCatalogEntry,
    FinancialNumericCatalogOwnerEvent,
    FinancialNumericCatalogResolutionPurpose,
    resolve_financial_numeric_source_qualification,
)
from apps.data_center.domain.financial_numeric_evidence import FinancialMetricSourceContract
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    DjangoFinancialNumericSourceCaptureRepository,
    FinancialNumericCatalogEvidenceError,
    LockedFinancialNumericSourceCapture,
    _insert_claimed,
    _invalid,
)
from apps.data_center.infrastructure.financial_numeric_catalog_models import (
    FinancialMetricSourceCatalogEntryModel,
    FinancialMetricSourceCatalogOwnerEventModel,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
)

_MAX_OWNER_USERNAME_LENGTH = 150
_MAX_CONTRACT_REVISIONS = 256


@dataclass(frozen=True, slots=True)
class _AuthenticatedCatalogOwner:
    """Narrow persisted user identity checked inside the current transaction."""

    actor_id: int
    username: str


class DjangoFinancialMetricSourceCatalogRepository(FinancialNumericSourceCatalogRepositoryPort):
    """Persist exact source contracts, authentication events, and qualification reads.

    Unit/scale configuration comes only from the explicit Domain payload. This
    repository does not create default units, metrics, scale rules, or approvals.
    The accepted endpoint is the existing owner source-time contract endpoint;
    no other endpoint or similar-looking URL is inferred to be equivalent.
    """

    def __init__(
        self,
        *,
        capture_repository: DjangoFinancialNumericSourceCaptureRepository,
        using: str,
        clock: Callable[[], datetime] = timezone.now,
    ) -> None:
        """Bind the verified capture reader, explicit database alias, and server clock."""

        if capture_repository is None:
            raise TypeError("verified financial source capture repository is required")
        if type(using) is not str or not using or using != using.strip() or len(using) > 128:
            raise ValueError("database alias must be explicit bounded text")
        if capture_repository.database_alias != using:
            raise ValueError(
                "catalog and retained capture repositories must share one database alias"
            )
        self._capture_repository = capture_repository
        self._using = using
        self._clock = clock

    def _now(self) -> datetime:
        """Sample one trusted server-side event/recording timestamp in UTC."""

        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise _invalid(
                "Trusted Owner event clock is invalid.",
                "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
            )
        try:
            return value.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise _invalid(
                "Trusted Owner event clock is invalid.",
                "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
            ) from error

    def _require_locking_uow(self) -> None:
        """Require a caller-owned PostgreSQL READ COMMITTED transaction."""

        database = connections[self._using]
        if not database.in_atomic_block or database.vendor != "postgresql":
            raise _invalid(
                "Qualification fencing requires a caller-owned PostgreSQL transaction.",
                "FINANCIAL_NUMERIC_CATALOG_UOW_REQUIRED",
            )
        try:
            with database.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                row = cursor.fetchone()
        except DatabaseError as error:
            raise _invalid(
                "Qualification transaction isolation is unavailable.",
                "FINANCIAL_NUMERIC_CATALOG_UOW_INVALID",
            ) from error
        if row is None or len(row) != 1 or row[0] != "read committed":
            raise _invalid(
                "Qualification fencing requires PostgreSQL READ COMMITTED isolation.",
                "FINANCIAL_NUMERIC_CATALOG_UOW_INVALID",
            )

    def _lock_contract_scope(self, contract_identity: str) -> None:
        """Serialize qualification insertion and resolution for one exact contract."""

        self._require_locking_uow()
        lock_key = int.from_bytes(
            hashlib.sha256(contract_identity.encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )
        database = connections[self._using]
        try:
            with database.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
                cursor.fetchone()
        except DatabaseError as error:
            raise _invalid(
                "Qualification contract scope lock is unavailable.",
                "FINANCIAL_NUMERIC_CATALOG_UOW_INVALID",
            ) from error

    def _authenticated_actor(
        self, actor_id: int, actor_username: str
    ) -> _AuthenticatedCatalogOwner:
        """Recheck the authenticated command user is still this active superuser."""

        if (
            type(actor_id) is not int
            or actor_id <= 0
            or type(actor_username) is not str
            or not actor_username
            or len(actor_username) > _MAX_OWNER_USERNAME_LENGTH
            or actor_username != actor_username.strip()
        ):
            raise _invalid(
                "Authenticated Owner identity is invalid.",
                "FINANCIAL_NUMERIC_OWNER_AUTH_REQUIRED",
            )
        user_model = get_user_model()
        actor = (
            user_model._default_manager.using(self._using)
            .select_for_update()
            .filter(pk=actor_id)
            .first()
        )
        if (
            actor is None
            or type(actor.pk) is not int
            or actor.is_active is not True
            or actor.is_superuser is not True
            or actor.get_username() != actor_username
        ):
            raise _invalid(
                "Owner event requires the exact active authenticated superuser.",
                "FINANCIAL_NUMERIC_OWNER_AUTH_REQUIRED",
            )
        return _AuthenticatedCatalogOwner(
            actor_id=actor.pk,
            username=actor.get_username(),
        )

    def append_qualification(
        self,
        qualification: FinancialNumericSourceQualification,
        *,
        actor_id: int,
        actor_username: str,
    ) -> UUID:
        """Append an exact qualification and real authenticated apply event atomically."""

        if type(qualification) is not FinancialNumericSourceQualification:
            raise _invalid("A complete typed financial source qualification is required.")
        if qualification.endpoint != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT:
            raise _invalid(
                "Only the approved Main financial-data endpoint is supported.",
                "FINANCIAL_NUMERIC_ENDPOINT_UNSUPPORTED",
            )
        qualification_payload = qualification.to_dict()
        qualification_hash = qualification.content_hash
        qualification_identity = qualification.identity
        contract = qualification.contract
        capture_ref = qualification.document_capture
        entry_id = uuid4()
        try:
            with transaction.atomic(using=self._using):
                actor = self._authenticated_actor(actor_id, actor_username)
                self._lock_contract_scope(contract.identity)
                locked_capture = self._capture_repository.lock_capture_for_uow(capture_ref)
                capture_known_at = self._now()
                retained = self._capture_repository.verify_locked_capture(
                    locked_capture,
                    known_at=capture_known_at,
                )
                if (
                    retained.reference != capture_ref
                    or retained.capture_recorded_at > capture_known_at
                    or retained.response_completed_at > capture_known_at
                ):
                    raise _invalid(
                        "Qualification document capture is not fully known at apply time."
                    )
                exact_existing = (
                    FinancialMetricSourceCatalogEntryModel._default_manager.using(self._using)
                    .select_for_update()
                    .filter(qualification_identity=qualification_identity)
                    .first()
                )
                if exact_existing is not None:
                    raise _invalid(
                        "This exact qualification identity is already in the catalog.",
                        "FINANCIAL_NUMERIC_CATALOG_DUPLICATE",
                    )
                now = self._now()
                if now < capture_known_at:
                    raise _invalid(
                        "Owner apply event clock preceded completed capture verification.",
                        "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
                    )
                entry_values: dict[str, object] = {
                    "entry_id": entry_id,
                    "qualification_identity": qualification_identity,
                    "qualification_sha256": qualification_hash,
                    "contract_identity": contract.identity,
                    "contract_sha256": contract.content_hash,
                    "contract_provider": contract.provider,
                    "dataset_key": contract.dataset_key,
                    "metric_code": contract.metric_code,
                    "qualification": qualification_payload,
                    "document_capture_id": capture_ref.capture_id,
                    "effective_from": qualification.effective_from,
                    "effective_until": qualification.effective_until,
                    "recorded_at": now,
                }
                with transaction.atomic(using=self._using):
                    entry = _insert_claimed(
                        FinancialMetricSourceCatalogEntryModel,
                        entry_values,
                        using=self._using,
                    )
                event_id = uuid4()
                event_values: dict[str, object] = {
                    "event_id": event_id,
                    "entry_id": entry.entry_id,
                    "action": "apply",
                    "qualification_identity": qualification_identity,
                    "qualification_sha256": qualification_hash,
                    "actor_id": actor.actor_id,
                    "actor_username_snapshot": actor.username,
                    "event_at": now,
                    "recorded_at": now,
                }
                with transaction.atomic(using=self._using):
                    _insert_claimed(
                        FinancialMetricSourceCatalogOwnerEventModel,
                        event_values,
                        using=self._using,
                    )
        except IntegrityError as error:
            raise _invalid(
                "Qualification or Owner event violates an exact uniqueness constraint.",
                "FINANCIAL_NUMERIC_CATALOG_DUPLICATE",
            ) from error
        return entry_id

    def append_revocation(
        self,
        entry_id: UUID,
        *,
        expected_qualification_identity: str,
        expected_qualification_sha256: str,
        actor_id: int,
        actor_username: str,
    ) -> UUID:
        """Append a separate authenticated revoke event for the exact immutable entry."""

        if (
            type(entry_id) is not UUID
            or type(expected_qualification_identity) is not str
            or not expected_qualification_identity
            or expected_qualification_identity != expected_qualification_identity.strip()
            or len(expected_qualification_identity) > 256
            or type(expected_qualification_sha256) is not str
            or len(expected_qualification_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in expected_qualification_sha256
            )
        ):
            raise _invalid("Exact catalog entry identity and hash are required.")
        try:
            with transaction.atomic(using=self._using):
                self._require_locking_uow()
                actor = self._authenticated_actor(actor_id, actor_username)
                entry = (
                    FinancialMetricSourceCatalogEntryModel._default_manager.using(self._using)
                    .select_for_update()
                    .filter(entry_id=entry_id)
                    .first()
                )
                if entry is None:
                    raise _invalid("Exact financial numeric catalog entry is missing.")
                qualification = self._restore_qualification(entry)
                if (
                    entry.qualification_identity != expected_qualification_identity
                    or entry.qualification_sha256 != expected_qualification_sha256
                    or qualification.identity != expected_qualification_identity
                    or qualification.content_hash != expected_qualification_sha256
                ):
                    raise _invalid("Revocation does not match the exact qualification hash.")
                existing_events = tuple(
                    FinancialMetricSourceCatalogOwnerEventModel._default_manager.using(self._using)
                    .filter(entry_id=entry_id)
                    .select_related("actor")
                    .order_by("recorded_at", "event_id")
                )
                now = self._now()
                if len(existing_events) != 1 or existing_events[0].action != "apply":
                    raise _invalid("Only one current applied entry can be revoked.")
                applied = existing_events[0]
                if (
                    applied.qualification_identity != qualification.identity
                    or applied.qualification_sha256 != qualification.content_hash
                    or applied.actor_username_snapshot != applied.actor.get_username()
                ):
                    raise _invalid(
                        "The existing apply event is not bound to its authenticated identity."
                    )
                if now < applied.recorded_at or now < applied.event_at:
                    raise _invalid(
                        "Revocation cannot precede its apply event.",
                        "FINANCIAL_NUMERIC_CATALOG_CLOCK_INVALID",
                    )
                event_id = uuid4()
                event_values: dict[str, object] = {
                    "event_id": event_id,
                    "entry_id": entry_id,
                    "action": "revoke",
                    "qualification_identity": expected_qualification_identity,
                    "qualification_sha256": expected_qualification_sha256,
                    "actor_id": actor.actor_id,
                    "actor_username_snapshot": actor.username,
                    "event_at": now,
                    "recorded_at": now,
                }
                with transaction.atomic(using=self._using):
                    _insert_claimed(
                        FinancialMetricSourceCatalogOwnerEventModel,
                        event_values,
                        using=self._using,
                    )
        except IntegrityError as error:
            raise _invalid(
                "Owner revoke event is already present or violates a catalog constraint.",
                "FINANCIAL_NUMERIC_CATALOG_REVOKE_CONFLICT",
            ) from error
        return event_id

    @staticmethod
    def _restore_qualification(
        row: FinancialMetricSourceCatalogEntryModel,
    ) -> FinancialNumericSourceQualification:
        """Decode and cross-check the complete immutable contract/qualification payload."""

        raw_payload: object = row.qualification
        try:
            qualification = FinancialNumericSourceQualification.from_payload(raw_payload)
        except (TypeError, ValueError, OverflowError) as error:
            raise _invalid("Stored financial metric qualification is malformed.") from error
        contract: FinancialMetricSourceContract = qualification.contract
        if (
            qualification.identity != row.qualification_identity
            or qualification.content_hash != row.qualification_sha256
            or contract.identity != row.contract_identity
            or contract.content_hash != row.contract_sha256
            or contract.provider != row.contract_provider
            or contract.dataset_key != row.dataset_key
            or contract.metric_code != row.metric_code
            or qualification.endpoint != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
            or qualification.document_capture.capture_id != row.document_capture_id
            or qualification.effective_from != row.effective_from
            or qualification.effective_until != row.effective_until
        ):
            raise _invalid("Stored qualification differs from its exact indexed identities.")
        return qualification

    def _restore_events(
        self,
        row: FinancialMetricSourceCatalogEntryModel,
        *,
        known_at: datetime,
        qualification: FinancialNumericSourceQualification,
    ) -> tuple[FinancialNumericCatalogOwnerEvent, ...]:
        """Restore only append-only event rows recorded by the requested knowledge cutoff."""

        event_rows = tuple(
            FinancialMetricSourceCatalogOwnerEventModel._default_manager.using(self._using)
            .filter(entry_id=row.entry_id, recorded_at__lte=known_at)
            .select_related("actor")
            .order_by("recorded_at", "event_id")[:3]
        )
        if len(event_rows) > 2:
            raise _invalid("Catalog Owner event history is ambiguous.")
        restored: list[FinancialNumericCatalogOwnerEvent] = []
        for event_row in event_rows:
            actor_pk = event_row.actor.pk
            actor_username = event_row.actor.get_username()
            if (
                type(actor_pk) is not int
                or actor_pk <= 0
                or event_row.actor_username_snapshot != actor_username
                or event_row.qualification_identity != qualification.identity
                or event_row.qualification_sha256 != qualification.content_hash
            ):
                raise _invalid(
                    "Owner event identity differs from its actor or exact qualification."
                )
            action: FinancialNumericCatalogAction
            if event_row.action == "apply":
                action = "apply"
            elif event_row.action == "revoke":
                action = "revoke"
            else:
                raise _invalid("Unknown financial numeric catalog Owner event action.")
            try:
                restored.append(
                    FinancialNumericCatalogOwnerEvent(
                        event_id=event_row.event_id,
                        entry_id=row.entry_id,
                        action=action,
                        qualification_identity=event_row.qualification_identity,
                        qualification_sha256=event_row.qualification_sha256,
                        actor_id=actor_pk,
                        actor_username=actor_username,
                        event_at=event_row.event_at,
                        recorded_at=event_row.recorded_at,
                    )
                )
            except (TypeError, ValueError) as error:
                raise _invalid("Persisted Owner event is malformed.") from error
        return tuple(restored)

    def resolve_exact(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        known_at: datetime,
    ) -> FinancialNumericSourceQualification | None:
        """Resolve one exact metric qualification after raw document and Owner verification.

        The endpoint must be the exact existing AKShare Main endpoint. Every
        candidate row is re-decoded from its stored payload; its document
        capture, body store, provider identity, and persisted egress audit are
        independently rechecked. The returned qualification remains
        evidence-only and is not a D1 or production-ready decision result.
        """

        if (
            type(contract_identity) is not str
            or not contract_identity
            or contract_identity != contract_identity.strip()
            or len(contract_identity) > 160
            or endpoint != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
            or not isinstance(source_context, Mapping)
            or any(type(key) is not str for key in source_context)
            or type(source_response_completed_at) is not datetime
            or source_response_completed_at.tzinfo is None
            or source_response_completed_at.utcoffset() is None
            or type(known_at) is not datetime
            or known_at.tzinfo is None
            or known_at.utcoffset() is None
        ):
            return None
        try:
            cutoff = known_at.astimezone(UTC)
            response_at = source_response_completed_at.astimezone(UTC)
        except (OverflowError, ValueError):
            return None
        if response_at > cutoff:
            return None
        try:
            rows = tuple(
                FinancialMetricSourceCatalogEntryModel._default_manager.using(self._using)
                .filter(contract_identity=contract_identity, recorded_at__lte=cutoff)
                .select_related("document_capture__provider")
                .order_by("recorded_at", "entry_id")
            )
            entries: list[FinancialNumericCatalogEntry] = []
            for row in rows:
                qualification = self._restore_qualification(row)
                retained = self._capture_repository.read_verified_capture(
                    qualification.document_capture,
                    known_at=cutoff,
                )
                if retained.capture_recorded_at > cutoff:
                    continue
                events = self._restore_events(
                    row,
                    known_at=cutoff,
                    qualification=qualification,
                )
                try:
                    entries.append(
                        FinancialNumericCatalogEntry(
                            entry_id=row.entry_id,
                            qualification=qualification,
                            recorded_at=row.recorded_at,
                            capture_recorded_at=retained.capture_recorded_at,
                            owner_events=events,
                        )
                    )
                except (TypeError, ValueError) as error:
                    raise _invalid("Stored catalog entry timeline is invalid.") from error
        except DatabaseError as error:
            raise _invalid("Financial numeric catalog database evidence is unavailable.") from error
        except FinancialNumericCatalogEvidenceError:
            raise
        return resolve_financial_numeric_source_qualification(
            tuple(entries),
            contract_identity=contract_identity,
            endpoint=endpoint,
            source_response_completed_at=response_at,
            source_context=source_context,
            known_at=cutoff,
        )

    def resolve_exact_in_uow(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        purpose: FinancialNumericCatalogResolutionPurpose,
        known_at: datetime,
    ) -> FinancialNumericSourceQualification | None:
        """Resolve under caller-held row locks, retained through its outer UOW commit.

        The caller must already own a PostgreSQL READ COMMITTED transaction on
        this repository's database alias. Current purposes block if any catalog
        entry or Owner event became known after known_at while this call waited
        for its locks; callers must retry with a fresh current cutoff. A PIT
        purpose filters by the exact supplied cutoff and preserves later events
        as future knowledge. This method does not begin or commit a transaction.
        """

        if (
            type(contract_identity) is not str
            or not contract_identity
            or contract_identity != contract_identity.strip()
            or len(contract_identity) > 160
            or type(endpoint) is not str
            or endpoint != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
            or not isinstance(source_context, Mapping)
            or any(type(key) is not str for key in source_context)
            or type(purpose) is not FinancialNumericCatalogResolutionPurpose
            or type(known_at) is not datetime
            or known_at.tzinfo is None
            or known_at.utcoffset() != timedelta(0)
            or type(source_response_completed_at) is not datetime
            or source_response_completed_at.tzinfo is None
            or source_response_completed_at.utcoffset() != timedelta(0)
        ):
            return None
        try:
            cutoff = known_at.astimezone(UTC)
            response_at = source_response_completed_at.astimezone(UTC)
        except (OverflowError, ValueError):
            return None
        if response_at > cutoff:
            return None
        try:
            self._require_locking_uow()
            self._lock_contract_scope(contract_identity)
            entry_query = FinancialMetricSourceCatalogEntryModel._default_manager.using(
                self._using
            ).filter(contract_identity=contract_identity)
            if purpose is FinancialNumericCatalogResolutionPurpose.POINT_IN_TIME_READ:
                entry_query = entry_query.filter(recorded_at__lte=cutoff)
            entry_rows = tuple(
                entry_query.select_for_update(of=("self",)).order_by("entry_id")[
                    : _MAX_CONTRACT_REVISIONS + 1
                ]
            )
            if len(entry_rows) > _MAX_CONTRACT_REVISIONS:
                return None
            if purpose is not FinancialNumericCatalogResolutionPurpose.POINT_IN_TIME_READ and any(
                row.recorded_at > cutoff for row in entry_rows
            ):
                return None

            locked_entries: list[
                tuple[
                    FinancialMetricSourceCatalogEntryModel,
                    FinancialNumericSourceQualification,
                    LockedFinancialNumericSourceCapture,
                ]
            ] = []
            for row in entry_rows:
                qualification = self._restore_qualification(row)
                locked_capture = self._capture_repository.lock_capture_for_uow(
                    qualification.document_capture
                )
                locked_entries.append((row, qualification, locked_capture))

            entries: list[FinancialNumericCatalogEntry] = []
            for row, qualification, locked_capture in locked_entries:
                if purpose is not FinancialNumericCatalogResolutionPurpose.POINT_IN_TIME_READ:
                    later_event_exists = (
                        FinancialMetricSourceCatalogOwnerEventModel._default_manager.using(
                            self._using
                        )
                        .filter(entry_id=row.entry_id, recorded_at__gt=cutoff)
                        .exists()
                    )
                    if later_event_exists:
                        return None
                retained = self._capture_repository.verify_locked_capture(
                    locked_capture,
                    known_at=cutoff,
                )
                events = self._restore_events(
                    row,
                    known_at=cutoff,
                    qualification=qualification,
                )
                try:
                    entries.append(
                        FinancialNumericCatalogEntry(
                            entry_id=row.entry_id,
                            qualification=qualification,
                            recorded_at=row.recorded_at,
                            capture_recorded_at=retained.capture_recorded_at,
                            owner_events=events,
                        )
                    )
                except (TypeError, ValueError):
                    return None
        except (DatabaseError, FinancialNumericCatalogEvidenceError):
            return None
        return resolve_financial_numeric_source_qualification(
            tuple(entries),
            contract_identity=contract_identity,
            endpoint=endpoint,
            source_response_completed_at=response_at,
            source_context=source_context,
            known_at=cutoff,
        )


__all__ = ["DjangoFinancialMetricSourceCatalogRepository"]
