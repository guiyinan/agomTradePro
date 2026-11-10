"""Django persistence and availability-cutoff reads for source disclosure facts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.data_center.application.security_disclosure_event import (
    SecurityDisclosureEventRepositoryPort,
    SecurityDisclosureListingCoverageRepositoryPort,
)
from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    PersistedSecurityDisclosureListingCoverage,
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendDisposition,
    SecurityDisclosureEventAppendResult,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageAppendResult,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureListingCoverageReadScope,
    SecurityDisclosureListingEntry,
    SecurityDisclosureSource,
    SourceEventClock,
)
from apps.data_center.infrastructure.security_disclosure_event_models import (
    SecurityDisclosureEventModel,
    SecurityDisclosureListingCoverageModel,
    _activate_security_disclosure_event_uow,
    _claim_security_disclosure_event_insert,
)
from core.exceptions import DataValidationError


class _SecurityDisclosureEventClock(Protocol):
    """Trusted application clock used to reject future observations and cutoffs."""

    def now(self) -> datetime:
        """Return an aware current time."""


class _DjangoSecurityDisclosureEventClock:
    """Django timezone-backed clock for event source persistence."""

    def now(self) -> datetime:
        """Return the current aware application time."""

        return timezone.now()


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    """Require an aware datetime and normalize its instant to UTC."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise DataValidationError(
            f"{field_name} must be timezone-aware.",
            code="SECURITY_DISCLOSURE_EVENT_CLOCK_INVALID",
        )
    return value.astimezone(UTC)


def _clock_fields(value: SourceEventClock | None, *, prefix: str) -> dict[str, object]:
    """Preserve exact date or datetime source-clock precision in paired columns."""

    if value is None:
        return {f"{prefix}_at": None, f"{prefix}_on": None}
    if type(value) is date:
        return {f"{prefix}_at": None, f"{prefix}_on": value}
    if type(value) is datetime:
        return {f"{prefix}_at": value.astimezone(UTC), f"{prefix}_on": None}
    raise DataValidationError(
        f"{prefix} has unsupported source clock precision.",
        code="SECURITY_DISCLOSURE_EVENT_CLOCK_INVALID",
    )


def _restore_clock(
    *,
    timestamp: datetime | None,
    calendar_date: date | None,
    field_name: str,
    optional: bool,
) -> SourceEventClock | None:
    """Restore one stored source clock and reject ambiguous/corrupt precision."""

    if timestamp is not None and calendar_date is not None:
        raise DataValidationError(
            f"Stored {field_name} has conflicting precision columns.",
            code="SECURITY_DISCLOSURE_EVENT_STORAGE_INVALID",
        )
    if timestamp is not None:
        return _aware_utc(timestamp, field_name=field_name)
    if calendar_date is not None:
        if type(calendar_date) is not date:
            raise DataValidationError(
                f"Stored {field_name} date is invalid.",
                code="SECURITY_DISCLOSURE_EVENT_STORAGE_INVALID",
            )
        return calendar_date
    if optional:
        return None
    raise DataValidationError(
        f"Stored {field_name} is missing.",
        code="SECURITY_DISCLOSURE_EVENT_STORAGE_INVALID",
    )


def _event_values(
    event: SecurityDisclosureEvent,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    """Build exact ORM values from a previously validated source event."""

    return {
        "source": event.source.value,
        "exchange": event.exchange.value,
        "asset_code": event.asset_code,
        "source_security_code": event.source_security_code,
        "source_event_id": event.source_event_id,
        "source_revision_id": event.source_revision_id,
        "raw_event_type": event.raw_event_type,
        "event_type": event.event_type.value,
        "source_url": event.source_url,
        "source_body_sha256": event.source_body_sha256,
        "content_hash": event.content_hash,
        **_clock_fields(event.announced_at, prefix="announced"),
        **_clock_fields(event.source_available_at, prefix="source_available"),
        **_clock_fields(event.effective_at, prefix="effective"),
        "available_at": _aware_utc(event.available_at, field_name="available_at"),
        "first_seen_at": _aware_utc(event.first_seen_at, field_name="first_seen_at"),
        "supersedes_source_event_id": event.supersedes_source_event_id or "",
        "supersedes_source_revision_id": event.supersedes_source_revision_id or "",
        "recorded_at": recorded_at,
    }


def _identity_filter(event: SecurityDisclosureEvent) -> dict[str, str]:
    """Return the exact native event revision identity used for idempotency."""

    return {
        "source": event.source.value,
        "exchange": event.exchange.value,
        "asset_code": event.asset_code,
        "source_event_id": event.source_event_id,
        "source_revision_id": event.source_revision_id,
    }


def _to_persisted_event(
    model: SecurityDisclosureEventModel,
) -> PersistedSecurityDisclosureEvent:
    """Restore and verify one ORM row before exposing it to Application callers."""

    announced_at = _restore_clock(
        timestamp=model.announced_at,
        calendar_date=model.announced_on,
        field_name="announced_at",
        optional=True,
    )
    source_available_at = _restore_clock(
        timestamp=model.source_available_at,
        calendar_date=model.source_available_on,
        field_name="source_available_at",
        optional=True,
    )
    effective_at = _restore_clock(
        timestamp=model.effective_at,
        calendar_date=model.effective_on,
        field_name="effective_at",
        optional=True,
    )
    try:
        event = SecurityDisclosureEvent(
            source=SecurityDisclosureSource(model.source),
            exchange=SecurityDisclosureExchange(model.exchange),
            asset_code=model.asset_code,
            source_security_code=model.source_security_code,
            source_event_id=model.source_event_id,
            source_revision_id=model.source_revision_id,
            raw_event_type=model.raw_event_type,
            event_type=SecurityDisclosureEventType(model.event_type),
            source_url=model.source_url,
            source_body_sha256=model.source_body_sha256,
            announced_at=announced_at,
            source_available_at=source_available_at,
            first_seen_at=_aware_utc(model.first_seen_at, field_name="first_seen_at"),
            effective_at=effective_at,
            supersedes_source_event_id=model.supersedes_source_event_id or None,
            supersedes_source_revision_id=model.supersedes_source_revision_id or None,
        )
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "Stored security disclosure event is invalid.",
            code="SECURITY_DISCLOSURE_EVENT_STORAGE_INVALID",
        ) from error
    if (
        event.content_hash != model.content_hash
        or _aware_utc(model.available_at, field_name="available_at") != event.available_at
    ):
        raise DataValidationError(
            "Stored security disclosure event content hash or availability bound is invalid.",
            code="SECURITY_DISCLOSURE_EVENT_STORAGE_INVALID",
        )
    try:
        return PersistedSecurityDisclosureEvent(
            event=event,
            recorded_at=_aware_utc(model.recorded_at, field_name="recorded_at"),
        )
    except ValueError as error:
        raise DataValidationError(
            "Stored security disclosure event record time is invalid.",
            code="SECURITY_DISCLOSURE_EVENT_STORAGE_INVALID",
        ) from error


def _coverage_values(
    proof: SecurityDisclosureListingCoverageProof,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    """Build exact ORM values while retaining every source row and both page passes."""

    return {
        "source": proof.source.value,
        "exchange": proof.exchange.value,
        "asset_code": proof.asset_code,
        "start_on": proof.start_on,
        "end_on": proof.end_on,
        "first_observed_at": _aware_utc(proof.first_observed_at, field_name="first_observed_at"),
        "verified_at": _aware_utc(proof.verified_at, field_name="verified_at"),
        "announcement_count": proof.announcement_count,
        "listing_entries": [item.to_manifest_payload() for item in proof.entries],
        "first_pass_page_body_sha256": list(proof.first_pass_page_body_sha256),
        "second_pass_page_body_sha256": list(proof.second_pass_page_body_sha256),
        "manifest_sha256": proof.source_manifest_sha256,
        "coverage_manifest_sha256": proof.coverage_manifest_sha256,
        "recorded_at": recorded_at,
    }


def _json_list(value: object, *, field_name: str) -> list[object]:
    """Narrow one persisted JSON array before decoding its typed members."""

    if type(value) is not list:
        raise DataValidationError(
            f"Stored {field_name} is not an array.",
            code="SECURITY_DISCLOSURE_LISTING_STORAGE_INVALID",
        )
    return cast(list[object], value)


def _json_object(value: object, *, field_name: str) -> dict[str, object]:
    """Narrow one persisted JSON object at the ORM boundary."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise DataValidationError(
            f"Stored {field_name} is not an object.",
            code="SECURITY_DISCLOSURE_LISTING_STORAGE_INVALID",
        )
    return cast(dict[str, object], value)


def _json_text(value: object, *, field_name: str) -> str:
    """Require one source text value from a stored JSON entry."""

    if type(value) is not str:
        raise DataValidationError(
            f"Stored {field_name} is not text.",
            code="SECURITY_DISCLOSURE_LISTING_STORAGE_INVALID",
        )
    return value


def _json_int(value: object, *, field_name: str) -> int:
    """Require one non-boolean integer from a stored JSON entry."""

    if type(value) is not int:
        raise DataValidationError(
            f"Stored {field_name} is not an integer.",
            code="SECURITY_DISCLOSURE_LISTING_STORAGE_INVALID",
        )
    return value


def _json_date(value: object, *, field_name: str) -> date:
    """Restore a pure date string from a stored JSON listing row."""

    text = _json_text(value, field_name=field_name)
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise DataValidationError(
            f"Stored {field_name} is not a valid date.",
            code="SECURITY_DISCLOSURE_LISTING_STORAGE_INVALID",
        ) from error


def _listing_entry_from_json(value: object) -> SecurityDisclosureListingEntry:
    """Restore one typed source row and preserve malformed JSON as a storage error."""

    raw = _json_object(value, field_name="listing entry")
    try:
        return SecurityDisclosureListingEntry(
            listing_id=_json_text(raw.get("listing_id"), field_name="listing_id"),
            announcement_id=_json_int(raw.get("announcement_id"), field_name="announcement_id"),
            title=_json_text(raw.get("title"), field_name="title"),
            published_on=_json_date(raw.get("published_on"), field_name="published_on"),
            raw_publish_time=_json_text(raw.get("raw_publish_time"), field_name="raw_publish_time"),
            source_document_id=_json_text(
                raw.get("source_document_id"), field_name="source_document_id"
            ),
            source_url=_json_text(raw.get("source_url"), field_name="source_url"),
        )
    except ValueError as error:
        raise DataValidationError(
            "Stored SZSE listing row is invalid.",
            code="SECURITY_DISCLOSURE_LISTING_STORAGE_INVALID",
        ) from error


def _to_persisted_listing_coverage(
    model: SecurityDisclosureListingCoverageModel,
) -> PersistedSecurityDisclosureListingCoverage:
    """Rebuild and authenticate one ORM proof before exposing historical coverage."""

    try:
        proof = SecurityDisclosureListingCoverageProof(
            source=SecurityDisclosureSource(model.source),
            exchange=SecurityDisclosureExchange(model.exchange),
            asset_code=model.asset_code,
            start_on=model.start_on,
            end_on=model.end_on,
            first_observed_at=_aware_utc(model.first_observed_at, field_name="first_observed_at"),
            verified_at=_aware_utc(model.verified_at, field_name="verified_at"),
            announcement_count=model.announcement_count,
            entries=tuple(
                _listing_entry_from_json(item)
                for item in _json_list(model.listing_entries, field_name="listing_entries")
            ),
            first_pass_page_body_sha256=tuple(
                _json_text(item, field_name="first_pass_page_body_sha256")
                for item in _json_list(
                    model.first_pass_page_body_sha256,
                    field_name="first_pass_page_body_sha256",
                )
            ),
            second_pass_page_body_sha256=tuple(
                _json_text(item, field_name="second_pass_page_body_sha256")
                for item in _json_list(
                    model.second_pass_page_body_sha256,
                    field_name="second_pass_page_body_sha256",
                )
            ),
        )
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "Stored security disclosure listing proof is invalid.",
            code="SECURITY_DISCLOSURE_LISTING_STORAGE_INVALID",
        ) from error
    if (
        proof.source_manifest_sha256 != model.manifest_sha256
        or proof.coverage_manifest_sha256 != model.coverage_manifest_sha256
    ):
        raise DataValidationError(
            "Stored security disclosure listing manifest does not match its exact rows.",
            code="SECURITY_DISCLOSURE_LISTING_STORAGE_INVALID",
        )
    try:
        return PersistedSecurityDisclosureListingCoverage(
            proof=proof,
            recorded_at=_aware_utc(model.recorded_at, field_name="recorded_at"),
        )
    except ValueError as error:
        raise DataValidationError(
            "Stored security disclosure listing record time is invalid.",
            code="SECURITY_DISCLOSURE_LISTING_STORAGE_INVALID",
        ) from error


class DjangoSecurityDisclosureEventRepository(SecurityDisclosureEventRepositoryPort):
    """Append and query official event facts using a conservative first-seen PIT bound."""

    def __init__(
        self,
        *,
        clock: _SecurityDisclosureEventClock | None = None,
        using: str = "default",
    ) -> None:
        """Bind the database alias and injectable trusted clock."""

        self._clock = clock or _DjangoSecurityDisclosureEventClock()
        self._using = using

    def append(
        self,
        event: SecurityDisclosureEvent,
        source_document_body: bytes,
    ) -> SecurityDisclosureEventAppendResult:
        """Append one verified revision or return its exact first-seen winner."""

        if type(event) is not SecurityDisclosureEvent:
            raise DataValidationError(
                "Security disclosure event input is invalid.",
                code="SECURITY_DISCLOSURE_EVENT_INPUT_INVALID",
            )
        if not event.verifies_source_document(source_document_body):
            raise DataValidationError(
                "Source document bytes do not match the disclosure evidence hash.",
                code="SECURITY_DISCLOSURE_EVENT_SOURCE_BODY_MISMATCH",
            )
        now = _aware_utc(self._clock.now(), field_name="repository clock")
        first_seen_at = _aware_utc(event.first_seen_at, field_name="first_seen_at")
        if first_seen_at > now:
            raise DataValidationError(
                "first_seen_at cannot be later than the repository clock.",
                code="SECURITY_DISCLOSURE_EVENT_CLOCK_INVALID",
            )
        values = _event_values(event, recorded_at=now)
        identity = _identity_filter(event)

        with transaction.atomic(using=self._using):
            existing = self._locked_identity_row(identity)
            if existing is not None:
                return self._resolve_existing(existing, event)
            try:
                with transaction.atomic(using=self._using):
                    with _activate_security_disclosure_event_uow() as token:
                        with _claim_security_disclosure_event_insert(
                            token=token,
                            model_type=SecurityDisclosureEventModel,
                            expected_values=values,
                        ):
                            created = SecurityDisclosureEventModel._default_manager.using(
                                self._using
                            ).create(**values)
            except IntegrityError as error:
                concurrent = self._locked_identity_row(identity)
                if concurrent is None:
                    raise DataValidationError(
                        "Security disclosure append violated a storage constraint.",
                        code="SECURITY_DISCLOSURE_EVENT_WRITE_CONFLICT",
                    ) from error
                return self._resolve_existing(concurrent, event)
            return SecurityDisclosureEventAppendResult(
                disposition=SecurityDisclosureEventAppendDisposition.STORED,
                record=_to_persisted_event(created),
            )

    def list_known_at(
        self,
        scope: SecurityDisclosureEventReadScope,
    ) -> tuple[PersistedSecurityDisclosureEvent, ...]:
        """Return every revision whose first-seen availability bound meets the cutoff."""

        if type(scope) is not SecurityDisclosureEventReadScope:
            raise DataValidationError(
                "Security disclosure event read scope is invalid.",
                code="SECURITY_DISCLOSURE_EVENT_SCOPE_INVALID",
            )
        as_of = _aware_utc(scope.as_of, field_name="as_of")
        now = _aware_utc(self._clock.now(), field_name="repository clock")
        if as_of > now:
            raise DataValidationError(
                "Security disclosure event cutoff cannot exceed the repository clock.",
                code="SECURITY_DISCLOSURE_EVENT_CUTOFF_INVALID",
            )
        queryset = SecurityDisclosureEventModel._default_manager.using(self._using).filter(
            available_at__lte=as_of
        )
        if scope.exchange is not None:
            queryset = queryset.filter(exchange=scope.exchange.value)
        if scope.asset_code is not None:
            queryset = queryset.filter(asset_code=scope.asset_code)
        return tuple(_to_persisted_event(row) for row in queryset)

    def _locked_identity_row(
        self,
        identity: dict[str, str],
    ) -> SecurityDisclosureEventModel | None:
        """Read one exact existing revision inside the active append transaction."""

        return (
            SecurityDisclosureEventModel._default_manager.using(self._using)
            .select_for_update()
            .filter(**identity)
            .first()
        )

    @staticmethod
    def _resolve_existing(
        model: SecurityDisclosureEventModel,
        event: SecurityDisclosureEvent,
    ) -> SecurityDisclosureEventAppendResult:
        """Return an exact duplicate or fail closed on native-identity reuse."""

        persisted = _to_persisted_event(model)
        if persisted.event.content_hash != event.content_hash:
            raise DataValidationError(
                "Source event revision identity already has different evidence or normalized content.",
                code="SECURITY_DISCLOSURE_EVENT_IDENTITY_CONFLICT",
            )
        return SecurityDisclosureEventAppendResult(
            disposition=SecurityDisclosureEventAppendDisposition.DUPLICATE,
            record=persisted,
        )


class DjangoSecurityDisclosureListingCoverageRepository(
    SecurityDisclosureListingCoverageRepositoryPort
):
    """Append exact SZSE listing proofs and read only proofs known by a cutoff."""

    def __init__(
        self,
        *,
        clock: _SecurityDisclosureEventClock | None = None,
        using: str = "default",
    ) -> None:
        """Bind the database alias and trusted source-knowledge clock."""

        self._clock = clock or _DjangoSecurityDisclosureEventClock()
        self._using = using

    def append(
        self,
        proof: SecurityDisclosureListingCoverageProof,
    ) -> SecurityDisclosureListingCoverageAppendResult:
        """Append one completed proof or preserve the original idempotent winner."""

        if type(proof) is not SecurityDisclosureListingCoverageProof:
            raise DataValidationError(
                "Security disclosure listing proof is invalid.",
                code="SECURITY_DISCLOSURE_LISTING_PROOF_INVALID",
            )
        now = _aware_utc(self._clock.now(), field_name="repository clock")
        verified_at = _aware_utc(proof.verified_at, field_name="verified_at")
        if verified_at > now:
            raise DataValidationError(
                "Listing proof verification cannot be later than its persistence clock.",
                code="SECURITY_DISCLOSURE_LISTING_CLOCK_INVALID",
            )
        values = _coverage_values(proof, recorded_at=now)
        identity = self._identity_filter(proof)

        with transaction.atomic(using=self._using):
            existing = self._locked_identity_row(identity)
            if existing is not None:
                return self._resolve_existing(existing, proof)
            try:
                with transaction.atomic(using=self._using):
                    with _activate_security_disclosure_event_uow() as token:
                        with _claim_security_disclosure_event_insert(
                            token=token,
                            model_type=SecurityDisclosureListingCoverageModel,
                            expected_values=values,
                        ):
                            created = SecurityDisclosureListingCoverageModel._default_manager.using(
                                self._using
                            ).create(**values)
            except IntegrityError as error:
                concurrent = self._locked_identity_row(identity)
                if concurrent is None:
                    raise DataValidationError(
                        "Listing proof append violated a storage constraint.",
                        code="SECURITY_DISCLOSURE_LISTING_WRITE_CONFLICT",
                    ) from error
                return self._resolve_existing(concurrent, proof)
            return SecurityDisclosureListingCoverageAppendResult(
                disposition=SecurityDisclosureEventAppendDisposition.STORED,
                record=_to_persisted_listing_coverage(created),
            )

    def get_known_at(
        self,
        scope: SecurityDisclosureListingCoverageReadScope,
    ) -> PersistedSecurityDisclosureListingCoverage | None:
        """Return the latest exact-window proof durably recorded by ``as_of``."""

        if type(scope) is not SecurityDisclosureListingCoverageReadScope:
            raise DataValidationError(
                "Security disclosure listing scope is invalid.",
                code="SECURITY_DISCLOSURE_LISTING_SCOPE_INVALID",
            )
        as_of = _aware_utc(scope.as_of, field_name="as_of")
        now = _aware_utc(self._clock.now(), field_name="repository clock")
        if as_of > now:
            raise DataValidationError(
                "Security disclosure listing cutoff cannot exceed the repository clock.",
                code="SECURITY_DISCLOSURE_LISTING_CUTOFF_INVALID",
            )
        model = (
            SecurityDisclosureListingCoverageModel._default_manager.using(self._using)
            .filter(
                source=SecurityDisclosureSource.SZSE_OFFICIAL.value,
                exchange=SecurityDisclosureExchange.SZSE.value,
                asset_code=scope.asset_code,
                start_on=scope.start_on,
                end_on=scope.end_on,
                first_observed_at__lte=as_of,
                verified_at__lte=as_of,
                recorded_at__lte=as_of,
            )
            .order_by("-recorded_at", "-verified_at", "-pk")
            .first()
        )
        if model is None:
            return None
        return _to_persisted_listing_coverage(model)

    @staticmethod
    def _identity_filter(
        proof: SecurityDisclosureListingCoverageProof,
    ) -> dict[str, str | date | datetime]:
        """Return the exact append identity for this verification episode."""

        return {
            "source": proof.source.value,
            "exchange": proof.exchange.value,
            "asset_code": proof.asset_code,
            "start_on": proof.start_on,
            "end_on": proof.end_on,
            "coverage_manifest_sha256": proof.coverage_manifest_sha256,
            "verified_at": _aware_utc(proof.verified_at, field_name="verified_at"),
        }

    def _locked_identity_row(
        self,
        identity: dict[str, str | date | datetime],
    ) -> SecurityDisclosureListingCoverageModel | None:
        """Lock one exact prior proof inside the append transaction."""

        return (
            SecurityDisclosureListingCoverageModel._default_manager.using(self._using)
            .select_for_update()
            .filter(**identity)
            .first()
        )

    @staticmethod
    def _resolve_existing(
        model: SecurityDisclosureListingCoverageModel,
        proof: SecurityDisclosureListingCoverageProof,
    ) -> SecurityDisclosureListingCoverageAppendResult:
        """Return an exact same-content winner or reject conflicting stored evidence."""

        persisted = _to_persisted_listing_coverage(model)
        if (
            persisted.proof.source_manifest_sha256 != proof.source_manifest_sha256
            or persisted.proof.coverage_manifest_sha256 != proof.coverage_manifest_sha256
            or persisted.proof.verified_at != proof.verified_at
        ):
            raise DataValidationError(
                "Listing proof identity already has different source content.",
                code="SECURITY_DISCLOSURE_LISTING_IDENTITY_CONFLICT",
            )
        return SecurityDisclosureListingCoverageAppendResult(
            disposition=SecurityDisclosureEventAppendDisposition.DUPLICATE,
            record=persisted,
        )


__all__ = [
    "DjangoSecurityDisclosureEventRepository",
    "DjangoSecurityDisclosureListingCoverageRepository",
]
