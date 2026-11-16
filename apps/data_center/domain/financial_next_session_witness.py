"""Reference-only v3 binding for date-only financial notice availability.

The values here preserve the provider's NOTICE_DATE and reporting period as
dates. They do not manufacture an announcement instant or establish that any
claimed source, policy, Owner approval, calendar publication, or Audit event is
authoritative. A composition-owned reader must reload and verify those records
before decision use.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.contracts import MAX_CATALOG_TTL_SECONDS
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.exchange_calendar import ExchangeCalendarSnapshotReference
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningPhase,
    ExchangeSessionOpeningRule,
    FinancialNextSessionAvailability,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import FinancialResponseScopeBasis
from apps.data_center.domain.formal_exchange_calendar_publication import (
    exchange_calendar_publication_key,
    validate_current_calendar_publication,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_POLICY_HASH_DOMAIN = b"agomtradepro:financial-disclosure-availability-policy:v1\0"
_POLICY_KEYS = frozenset(
    {
        "policy_id",
        "policy_version",
        "exchange",
        "opening_phase",
        "effective_start",
        "effective_end",
        "calendar_response_max_age_seconds",
        "first_seen_at",
        "recorded_at",
    }
)


@dataclass(frozen=True, slots=True)
class FinancialNativeRowBinding:
    """Bind date-only financial source fields to one raw response row claim.

    ``matched_row_count`` and ``row_projection_sha256`` are parser-produced
    claims. This value checks their shape and response scope; it cannot reopen
    the encrypted bytes or prove that the parser selected the right row.
    """

    artifact_reference: FinancialResponseArtifactRef
    asset_code: str
    period_end: date
    period_type: FinancialPeriodType
    metric_code: str
    native_row_id: str
    notice_date: date
    row_projection_sha256: str
    matched_row_count: int

    def __post_init__(self) -> None:
        """Reject rows outside the exact body-verified request and response scope."""

        if type(self.artifact_reference) is not FinancialResponseArtifactRef:
            raise ValueError("native financial row requires a typed artifact reference")
        for name, value, maximum in (
            ("asset_code", self.asset_code, 64),
            ("metric_code", self.metric_code, 128),
            ("native_row_id", self.native_row_id, 256),
        ):
            _bounded_text(value, name, maximum)
        _require_date(self.period_end, "period_end")
        _require_date(self.notice_date, "notice_date")
        if type(self.period_type) is not FinancialPeriodType:
            raise ValueError("period_type must be an explicit FinancialPeriodType")
        if not _is_sha256(self.row_projection_sha256):
            raise ValueError("row_projection_sha256 must be lowercase SHA-256")
        if type(self.matched_row_count) is not int or self.matched_row_count != 1:
            raise ValueError("native financial row match must resolve exactly one row")
        evidence = self.artifact_reference.evidence
        request = evidence.request_scope
        response = evidence.response_scope
        if request.dataset_key != "equity.financial.fact":
            raise ValueError("native financial row artifact dataset is invalid")
        if evidence.response_scope_basis is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED:
            raise ValueError("native financial row requires body-verified response scope")
        if request.asset_code != self.asset_code:
            raise ValueError("native financial row asset differs from request scope")
        if (
            self.asset_code not in response.asset_codes
            or self.period_end not in response.period_ends
        ):
            raise ValueError("native financial row is outside the response coverage")
        if response.row_count < self.matched_row_count:
            raise ValueError("native financial row match exceeds response row count")

    def to_dict(self) -> dict[str, object]:
        """Return exact raw artifact identity and date-only row dimensions."""

        self.__post_init__()
        return {
            "artifact_reference": _artifact_reference_payload(self.artifact_reference),
            "asset_code": self.asset_code,
            "period_end": self.period_end.isoformat(),
            "period_type": self.period_type.value,
            "metric_code": self.metric_code,
            "native_row_id": self.native_row_id,
            "notice_date": self.notice_date.isoformat(),
            "row_projection_sha256": self.row_projection_sha256,
            "matched_row_count": self.matched_row_count,
        }


@dataclass(frozen=True, slots=True)
class FinancialCalendarPublicationReference:
    """Exact formal calendar, pointer, snapshot, freshness and as-of identity.

    ``lifecycle_at_resolution`` and ``superseded_at_at_resolution`` record the
    resolver input as observed when this reference was built. A later historical
    reader must compare immutable publication identity and check that the actual
    half-open window contained ``known_at``; it must not require a future
    lifecycle value to equal this captured value. The activation and pointer
    fields are resolver context, not an immutable activation receipt or proof
    of a committed Audit/outbox event.
    """

    dataset_key: str
    publication_key: str
    exchange: str
    publication_id: str
    publication_hash: str
    activation_id: str
    lifecycle_at_resolution: CalendarPublicationLifecycle
    superseded_at_at_resolution: datetime | None
    pointer_id: str
    pointer_updated_at: datetime
    contract_recorded_at: datetime
    policy_version: str
    policy_identity: str
    policy_recorded_at: datetime
    snapshot_reference: ExchangeCalendarSnapshotReference
    snapshot_first_seen_at: datetime
    snapshot_recorded_at: datetime
    published_at: datetime
    valid_until_at_resolution: datetime
    response_max_age_seconds: int
    known_at: datetime

    def __post_init__(self) -> None:
        """Validate the exact reference shape and its half-open freshness window."""

        for name, value, maximum in (
            ("dataset_key", self.dataset_key, 160),
            ("publication_key", self.publication_key, 300),
            ("exchange", self.exchange, 32),
            ("activation_id", self.activation_id, 300),
            ("policy_version", self.policy_version, 64),
            ("policy_identity", self.policy_identity, 512),
        ):
            _bounded_text(value, name, maximum)
        _require_uuid_text(self.publication_id, "publication_id")
        _require_uuid_text(self.pointer_id, "pointer_id")
        if not _is_sha256(self.publication_hash):
            raise ValueError("calendar publication_hash is invalid")
        if type(self.lifecycle_at_resolution) is not CalendarPublicationLifecycle:
            raise ValueError("calendar lifecycle must be typed")
        if self.lifecycle_at_resolution not in {
            CalendarPublicationLifecycle.PUBLISHED,
            CalendarPublicationLifecycle.SUPERSEDED,
        }:
            raise ValueError("calendar reference lifecycle is unsupported")
        if type(self.snapshot_reference) is not ExchangeCalendarSnapshotReference:
            raise ValueError("calendar snapshot reference must be typed")
        self.snapshot_reference.__post_init__()
        if self.publication_key != exchange_calendar_publication_key(self.exchange):
            raise ValueError("calendar publication key does not match exchange")
        if self.snapshot_reference.exchange != self.exchange:
            raise ValueError("calendar snapshot exchange does not match publication")
        for field_name in (
            "pointer_updated_at",
            "contract_recorded_at",
            "policy_recorded_at",
            "snapshot_first_seen_at",
            "snapshot_recorded_at",
            "published_at",
            "valid_until_at_resolution",
            "known_at",
        ):
            _require_utc(getattr(self, field_name), field_name)
        if self.superseded_at_at_resolution is not None:
            _require_utc(self.superseded_at_at_resolution, "superseded_at_at_resolution")
        if type(self.response_max_age_seconds) is not int or not (
            1 <= self.response_max_age_seconds <= MAX_CATALOG_TTL_SECONDS
        ):
            raise ValueError("calendar response max age must be explicit and positive")
        try:
            expected_valid_until = self.snapshot_first_seen_at + timedelta(
                seconds=self.response_max_age_seconds
            )
        except OverflowError as error:
            raise ValueError("calendar response expiry exceeds datetime range") from error
        if self.lifecycle_at_resolution is CalendarPublicationLifecycle.PUBLISHED:
            if self.superseded_at_at_resolution is not None:
                raise ValueError("published calendar reference cannot have superseded_at")
            expected_window_end = expected_valid_until
        else:
            if (
                self.superseded_at_at_resolution is None
                or self.superseded_at_at_resolution < self.published_at
            ):
                raise ValueError("superseded calendar reference requires its transition time")
            expected_window_end = min(expected_valid_until, self.superseded_at_at_resolution)
        if (
            self.valid_until_at_resolution != expected_window_end
            or self.valid_until_at_resolution <= self.published_at
        ):
            raise ValueError("calendar validity does not match exact response TTL")
        if not (
            self.snapshot_first_seen_at <= self.snapshot_recorded_at <= self.published_at
            and self.contract_recorded_at <= self.published_at
            and self.policy_recorded_at <= self.published_at
            and self.published_at <= self.known_at < self.valid_until_at_resolution
        ):
            raise ValueError("calendar reference is not current and fresh at known_at")
        if self.pointer_updated_at > self.known_at:
            raise ValueError("calendar pointer was updated after known_at")

    @classmethod
    def from_resolved_availability(
        cls, availability: FinancialNextSessionAvailability
    ) -> FinancialCalendarPublicationReference:
        """Project resolver identity for a later exact publication and history read."""

        if type(availability) is not FinancialNextSessionAvailability:
            raise TypeError("availability must be the exact resolver result type")
        availability.__post_init__()
        record = availability.calendar_record
        pointer = availability.calendar_pointer
        validate_current_calendar_publication(record, pointer, as_of=availability.known_at)
        seal = record.seal
        if pointer.pointer_id is None or pointer.updated_at is None:
            raise ValueError("resolved calendar pointer identity is absent")
        return cls(
            dataset_key=seal.dataset.value,
            publication_key=seal.publication_key,
            exchange=seal.exchange,
            publication_id=record.publication_id,
            publication_hash=seal.publication_hash,
            activation_id=record.activation_id,
            lifecycle_at_resolution=record.lifecycle,
            superseded_at_at_resolution=record.superseded_at,
            pointer_id=pointer.pointer_id,
            pointer_updated_at=pointer.updated_at,
            contract_recorded_at=seal.contract_recorded_at,
            policy_version=seal.policy_version,
            policy_identity=seal.policy_identity,
            policy_recorded_at=seal.policy_recorded_at,
            snapshot_reference=seal.snapshot_reference,
            snapshot_first_seen_at=seal.snapshot_first_seen_at,
            snapshot_recorded_at=seal.snapshot_recorded_at,
            published_at=record.published_at,
            valid_until_at_resolution=record.window.valid_until,
            response_max_age_seconds=seal.calendar_response_max_age_seconds,
            known_at=availability.known_at,
        )

    def to_dict(self) -> dict[str, object]:
        """Return an exact, closed reference projection for later repository reads."""

        self.__post_init__()
        return {
            "dataset_key": self.dataset_key,
            "publication_key": self.publication_key,
            "exchange": self.exchange,
            "publication_id": self.publication_id,
            "publication_hash": self.publication_hash,
            "activation_id": self.activation_id,
            "lifecycle_at_resolution": self.lifecycle_at_resolution.value,
            "superseded_at_at_resolution": (
                self.superseded_at_at_resolution.isoformat()
                if self.superseded_at_at_resolution
                else None
            ),
            "pointer_id": self.pointer_id,
            "pointer_updated_at": self.pointer_updated_at.isoformat(),
            "contract_recorded_at": self.contract_recorded_at.isoformat(),
            "policy_version": self.policy_version,
            "policy_identity": self.policy_identity,
            "policy_recorded_at": self.policy_recorded_at.isoformat(),
            "snapshot_reference": self.snapshot_reference.to_payload(),
            "snapshot_first_seen_at": self.snapshot_first_seen_at.isoformat(),
            "snapshot_recorded_at": self.snapshot_recorded_at.isoformat(),
            "published_at": self.published_at.isoformat(),
            "valid_until_at_resolution": self.valid_until_at_resolution.isoformat(),
            "response_max_age_seconds": self.response_max_age_seconds,
            "known_at": self.known_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class FinancialNextSessionAvailabilityReference:
    """Date-to-open projection of a validated resolver result.

    ``from_resolved_availability`` checks the actual complete calendar schedule
    and next-session calculation. A decoded reference cannot reproduce that
    proof because it deliberately stores immutable IDs, not every calendar day.
    """

    source_date: date
    next_session: date
    available_at: datetime
    known_at: datetime
    calendar: FinancialCalendarPublicationReference
    opening_rule: ExchangeSessionOpeningRule

    def __post_init__(self) -> None:
        """Validate date, clock, calendar and opening-rule identity consistency."""

        _require_date(self.source_date, "availability.source_date")
        _require_date(self.next_session, "availability.next_session")
        if self.next_session <= self.source_date:
            raise ValueError("next session must strictly follow notice date")
        _require_utc(self.available_at, "availability.available_at")
        _require_utc(self.known_at, "availability.known_at")
        if type(self.calendar) is not FinancialCalendarPublicationReference:
            raise TypeError("availability requires an exact calendar reference")
        self.calendar.__post_init__()
        if type(self.opening_rule) is not ExchangeSessionOpeningRule:
            raise TypeError("availability requires an exact opening rule")
        self.opening_rule.__post_init__()
        if self.calendar.known_at != self.known_at:
            raise ValueError("availability and calendar as-of identities differ")
        if self.calendar.exchange != self.opening_rule.exchange:
            raise ValueError("availability calendar and opening rule exchanges differ")
        if not (
            self.calendar.snapshot_reference.coverage_start
            <= self.source_date
            <= self.next_session
            <= self.calendar.snapshot_reference.coverage_end
        ):
            raise ValueError("availability dates exceed exact calendar coverage")
        if not (
            self.opening_rule.effective_start
            <= self.next_session
            <= self.opening_rule.effective_end
        ):
            raise ValueError("next session is outside opening rule effective dates")
        if not self.opening_rule.is_known_at(self.known_at):
            raise ValueError("opening rule knowledge postdates availability as-of")
        if self.available_at != _opening_clock_utc(self.next_session, self.opening_rule):
            raise ValueError("availability instant differs from explicit opening rule")

    @classmethod
    def from_resolved_availability(
        cls, availability: FinancialNextSessionAvailability
    ) -> FinancialNextSessionAvailabilityReference:
        """Capture a previously resolved, fully revalidated next-session result."""

        if type(availability) is not FinancialNextSessionAvailability:
            raise TypeError("availability must be the exact resolver result type")
        availability.__post_init__()
        return cls(
            source_date=availability.source_date,
            next_session=availability.next_session,
            available_at=availability.available_at,
            known_at=availability.known_at,
            calendar=FinancialCalendarPublicationReference.from_resolved_availability(
                availability,
            ),
            opening_rule=availability.opening_rule,
        )

    def to_dict(self) -> dict[str, object]:
        """Return the exact next-session, calendar and opening-rule references."""

        self.__post_init__()
        return {
            "schema": "financial-next-session-availability.reference.v1",
            "source_date": self.source_date.isoformat(),
            "next_session": self.next_session.isoformat(),
            "available_at": self.available_at.isoformat(),
            "known_at": self.known_at.isoformat(),
            "calendar": self.calendar.to_dict(),
            "opening_rule": self.opening_rule.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FinancialDisclosureAvailabilityPolicy:
    """Explicit policy content with no phase or TTL defaults."""

    policy_id: str
    policy_version: str
    exchange: str
    opening_phase: ExchangeSessionOpeningPhase
    effective_start: date
    effective_end: date
    calendar_response_max_age_seconds: int
    first_seen_at: datetime
    recorded_at: datetime
    policy_sha256: str

    def __post_init__(self) -> None:
        """Require complete policy content and its deterministic digest."""

        _bounded_text(self.policy_id, "policy_id", 200)
        _bounded_text(self.policy_version, "policy_version", 200)
        if _TOKEN_RE.fullmatch(self.policy_version) is None:
            raise ValueError("policy_version must be a bounded token")
        _bounded_text(self.exchange, "policy.exchange", 32)
        if type(self.opening_phase) is not ExchangeSessionOpeningPhase:
            raise ValueError("policy opening_phase must be explicit and typed")
        _require_date(self.effective_start, "policy.effective_start")
        _require_date(self.effective_end, "policy.effective_end")
        if self.effective_start > self.effective_end:
            raise ValueError("policy effective range is inverted")
        if type(self.calendar_response_max_age_seconds) is not int or not (
            1 <= self.calendar_response_max_age_seconds <= MAX_CATALOG_TTL_SECONDS
        ):
            raise ValueError("policy calendar response TTL must be explicit and positive")
        _require_utc(self.first_seen_at, "policy.first_seen_at")
        _require_utc(self.recorded_at, "policy.recorded_at")
        if self.first_seen_at > self.recorded_at:
            raise ValueError("policy knowledge times are not ordered")
        if not _is_sha256(self.policy_sha256):
            raise ValueError("policy_sha256 must be lowercase SHA-256")
        if self.policy_sha256 != financial_disclosure_availability_policy_sha256(self._payload()):
            raise ValueError("policy hash does not match its exact content")

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        exchange: str,
        opening_phase: ExchangeSessionOpeningPhase,
        effective_start: date,
        effective_end: date,
        calendar_response_max_age_seconds: int,
        first_seen_at: datetime,
        recorded_at: datetime,
    ) -> FinancialDisclosureAvailabilityPolicy:
        """Build one explicit policy value and calculate its content digest."""

        if type(opening_phase) is not ExchangeSessionOpeningPhase:
            raise ValueError("policy opening_phase must be explicit and typed")
        _require_date(effective_start, "policy.effective_start")
        _require_date(effective_end, "policy.effective_end")
        _require_utc(first_seen_at, "policy.first_seen_at")
        _require_utc(recorded_at, "policy.recorded_at")
        payload: dict[str, object] = {
            "policy_id": policy_id,
            "policy_version": policy_version,
            "exchange": exchange,
            "opening_phase": opening_phase.value,
            "effective_start": effective_start.isoformat(),
            "effective_end": effective_end.isoformat(),
            "calendar_response_max_age_seconds": calendar_response_max_age_seconds,
            "first_seen_at": first_seen_at.isoformat(),
            "recorded_at": recorded_at.isoformat(),
        }
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            exchange=exchange,
            opening_phase=opening_phase,
            effective_start=effective_start,
            effective_end=effective_end,
            calendar_response_max_age_seconds=calendar_response_max_age_seconds,
            first_seen_at=first_seen_at,
            recorded_at=recorded_at,
            policy_sha256=financial_disclosure_availability_policy_sha256(payload),
        )

    def to_dict(self) -> dict[str, object]:
        """Return the exact policy fields and their content identity."""

        self.__post_init__()
        return {**self._payload(), "policy_sha256": self.policy_sha256}

    def _payload(self) -> dict[str, str | int]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "exchange": self.exchange,
            "opening_phase": self.opening_phase.value,
            "effective_start": self.effective_start.isoformat(),
            "effective_end": self.effective_end.isoformat(),
            "calendar_response_max_age_seconds": self.calendar_response_max_age_seconds,
            "first_seen_at": self.first_seen_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
        }


def financial_disclosure_availability_policy_sha256(
    payload: Mapping[str, object],
) -> str:
    """Hash one exact, closed policy payload using a schema-specific domain."""

    if not isinstance(payload, Mapping) or frozenset(payload) != _POLICY_KEYS:
        raise ValueError("availability policy payload keys are invalid")
    for key, value in payload.items():
        if key == "calendar_response_max_age_seconds":
            if type(value) is not int:
                raise ValueError("availability policy TTL must be an integer")
        elif type(value) is not str:
            raise ValueError("availability policy text fields must be strings")
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_POLICY_HASH_DOMAIN + encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class FinancialOfficialSourceIdentity:
    """Opaque identity of the official original used to derive one rule.

    Hash, URI, capture, and timestamps are claims to re-read from the source
    document repository; this object does not authenticate the original bytes.
    """

    document_record_id: str
    capture_id: UUID
    source_uri: str
    body_sha256: str
    body_size_bytes: int
    artifact_location: str
    format_version: str
    encryption_algorithm: str
    encryption_key_ref: str
    encryption_key_version: str
    first_seen_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Validate a bounded non-secret pointer to one source original."""

        for name, value, maximum in (
            ("document_record_id", self.document_record_id, 200),
            ("source_uri", self.source_uri, 2048),
            ("artifact_location", self.artifact_location, 512),
            ("format_version", self.format_version, 128),
            ("encryption_algorithm", self.encryption_algorithm, 128),
            ("encryption_key_ref", self.encryption_key_ref, 256),
            ("encryption_key_version", self.encryption_key_version, 128),
        ):
            _bounded_text(value, name, maximum)
        if type(self.capture_id) is not UUID:
            raise ValueError("source capture_id must be a UUID")
        if not _is_sha256(self.body_sha256):
            raise ValueError("official source body_sha256 is invalid")
        if type(self.body_size_bytes) is not int or self.body_size_bytes <= 0:
            raise ValueError("official source body_size_bytes must be positive")
        _require_utc(self.first_seen_at, "source.first_seen_at")
        _require_utc(self.recorded_at, "source.recorded_at")
        if self.first_seen_at > self.recorded_at:
            raise ValueError("official source knowledge times are not ordered")

    def to_dict(self) -> dict[str, object]:
        """Return the exact original reference without its protected bytes."""

        self.__post_init__()
        return {
            "document_record_id": self.document_record_id,
            "capture_id": str(self.capture_id),
            "source_uri": self.source_uri,
            "body_sha256": self.body_sha256,
            "body_size_bytes": self.body_size_bytes,
            "artifact_location": self.artifact_location,
            "format_version": self.format_version,
            "encryption_algorithm": self.encryption_algorithm,
            "encryption_key_ref": self.encryption_key_ref,
            "encryption_key_version": self.encryption_key_version,
            "first_seen_at": self.first_seen_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class FinancialApprovalIdentity:
    """Opaque reference to an approval record and its claimed Owner principal.

    A decoded value never proves that the event exists, that the principal was
    a valid Owner, or that the actor and business scope were authorized then.
    """

    subject_record_id: str
    subject_sha256: str
    event_id: str
    event_sha256: str
    principal_id: str
    approved_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Validate exact subject/event hashes and non-future event clocks."""

        for name, value in (
            ("subject_record_id", self.subject_record_id),
            ("event_id", self.event_id),
            ("principal_id", self.principal_id),
        ):
            _bounded_text(value, name, 200)
        if not _is_sha256(self.subject_sha256) or not _is_sha256(self.event_sha256):
            raise ValueError("approval subject/event hashes must be lowercase SHA-256")
        _require_utc(self.approved_at, "approval.approved_at")
        _require_utc(self.recorded_at, "approval.recorded_at")
        if self.approved_at > self.recorded_at:
            raise ValueError("approval event recording precedes its claimed approval time")

    def to_dict(self) -> dict[str, str]:
        """Return the exact approval lookup reference without asserting validity."""

        self.__post_init__()
        return {
            "subject_record_id": self.subject_record_id,
            "subject_sha256": self.subject_sha256,
            "event_id": self.event_id,
            "event_sha256": self.event_sha256,
            "principal_id": self.principal_id,
            "approved_at": self.approved_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class FinancialNextSessionGovernanceBinding:
    """Bind explicit rule, source-original, policy and approval identities.

    This is a reference bundle only. Its typed IDs and hashes must be checked
    against source-document, policy, Owner-grant and Audit repositories by a
    composition-owned reader before it can support any qualified witness.
    """

    opening_rule_record_id: str
    official_source: FinancialOfficialSourceIdentity
    opening_rule_approval: FinancialApprovalIdentity
    policy: FinancialDisclosureAvailabilityPolicy
    policy_approval: FinancialApprovalIdentity

    def __post_init__(self) -> None:
        """Require exact hash and clock bindings across governance references."""

        _bounded_text(self.opening_rule_record_id, "opening_rule_record_id", 200)
        if type(self.official_source) is not FinancialOfficialSourceIdentity:
            raise TypeError("opening rule requires an official source identity")
        if type(self.opening_rule_approval) is not FinancialApprovalIdentity:
            raise TypeError("opening rule requires an approval identity")
        if type(self.policy) is not FinancialDisclosureAvailabilityPolicy:
            raise TypeError("availability policy must be explicitly typed")
        if type(self.policy_approval) is not FinancialApprovalIdentity:
            raise TypeError("availability policy requires an approval identity")
        self.official_source.__post_init__()
        self.opening_rule_approval.__post_init__()
        self.policy.__post_init__()
        self.policy_approval.__post_init__()
        if self.opening_rule_approval.subject_record_id != self.opening_rule_record_id:
            raise ValueError("opening rule approval references another record")
        if self.policy_approval.subject_record_id != self.policy.policy_id:
            raise ValueError("policy approval references another record")
        if self.policy_approval.subject_sha256 != self.policy.policy_sha256:
            raise ValueError("policy approval does not bind the exact policy content")
        if self.policy_approval.approved_at < self.policy.recorded_at:
            raise ValueError("policy approval predates policy recording")

    def validate_for(
        self,
        *,
        opening_rule: ExchangeSessionOpeningRule,
        calendar: FinancialCalendarPublicationReference,
        next_session: date,
        known_at: datetime,
    ) -> None:
        """Check reference equality, phase, TTL, effective dates and knowledge time."""

        self.__post_init__()
        opening_rule.__post_init__()
        _require_date(next_session, "next_session")
        _require_utc(known_at, "known_at")
        if (
            self.official_source.source_uri != opening_rule.source_uri
            or self.official_source.body_sha256 != opening_rule.source_body_sha256
            or self.official_source.first_seen_at != opening_rule.first_seen_at
            or self.official_source.recorded_at != opening_rule.recorded_at
        ):
            raise ValueError("opening rule does not match its official source identity")
        if (
            self.opening_rule_approval.subject_sha256 != opening_rule.rule_sha256
            or self.opening_rule_approval.subject_record_id != self.opening_rule_record_id
            or self.opening_rule_approval.approved_at != opening_rule.approved_at
        ):
            raise ValueError("opening rule approval does not bind exact rule content/time")
        if (
            self.policy.exchange != opening_rule.exchange
            or self.policy.exchange != calendar.exchange
            or self.policy.opening_phase is not opening_rule.phase
            or self.policy.calendar_response_max_age_seconds != calendar.response_max_age_seconds
        ):
            raise ValueError("availability policy scope, phase, or TTL differs from source")
        if not self.policy.effective_start <= next_session <= self.policy.effective_end:
            raise ValueError("availability policy is not effective on the next session")
        knowledge_times = (
            self.official_source.first_seen_at,
            self.official_source.recorded_at,
            self.opening_rule_approval.approved_at,
            self.opening_rule_approval.recorded_at,
            self.policy.first_seen_at,
            self.policy.recorded_at,
            self.policy_approval.approved_at,
            self.policy_approval.recorded_at,
        )
        if any(moment > known_at for moment in knowledge_times):
            raise ValueError("governance identity was not known by the availability cutoff")

    def to_dict(self) -> dict[str, object]:
        """Return the exact source, approval and policy lookup identities."""

        self.__post_init__()
        return {
            "opening_rule_record_id": self.opening_rule_record_id,
            "official_source": self.official_source.to_dict(),
            "opening_rule_approval": self.opening_rule_approval.to_dict(),
            "policy": self.policy.to_dict(),
            "policy_approval": self.policy_approval.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FinancialNextSessionSourceTimeWitnessV3:
    """Date-only source-time witness with an explicit, future next-open instant.

    This v3 value deliberately has no ``announced_at`` datetime. The source
    NOTICE_DATE and report period remain dates. ``available_at`` may be later
    than the financial response completion time; the consumer's earliest
    temporal usability is their maximum. The object remains evidence-only.
    """

    financial_row: FinancialNativeRowBinding
    availability: FinancialNextSessionAvailabilityReference
    governance: FinancialNextSessionGovernanceBinding

    @classmethod
    def from_resolved_availability(
        cls,
        *,
        financial_row: FinancialNativeRowBinding,
        availability: FinancialNextSessionAvailability,
        governance: FinancialNextSessionGovernanceBinding,
    ) -> FinancialNextSessionSourceTimeWitnessV3:
        """Build v3 from the existing resolver's fully checked result.

        This constructor preserves the exact resolution references. The
        returned witness remains reference-only and must be revalidated by a
        composition-owned source, catalog, Owner, Audit and PIT reader.
        """

        if type(availability) is not FinancialNextSessionAvailability:
            raise TypeError("availability must be the exact resolver result type")
        availability.__post_init__()
        return cls(
            financial_row=financial_row,
            availability=FinancialNextSessionAvailabilityReference.from_resolved_availability(
                availability
            ),
            governance=governance,
        )

    def __post_init__(self) -> None:
        """Recheck cross-source bindings without asserting external authority."""

        if type(self.financial_row) is not FinancialNativeRowBinding:
            raise TypeError("v3 witness requires one exact financial row binding")
        if type(self.availability) is not FinancialNextSessionAvailabilityReference:
            raise TypeError("v3 witness requires one next-session availability reference")
        if type(self.governance) is not FinancialNextSessionGovernanceBinding:
            raise TypeError("v3 witness requires explicit governance references")
        self.financial_row.__post_init__()
        self.availability.__post_init__()
        self.governance.validate_for(
            opening_rule=self.availability.opening_rule,
            calendar=self.availability.calendar,
            next_session=self.availability.next_session,
            known_at=self.availability.known_at,
        )
        if self.financial_row.notice_date != self.availability.source_date:
            raise ValueError("financial NOTICE_DATE differs from availability source date")
        if self.financial_row.artifact_reference.evidence.response_completed_at > self.known_at:
            raise ValueError("financial raw response was not known at witness cutoff")

    @property
    def known_at(self) -> datetime:
        """Return the exact as-of identity used by calendar and rule resolution."""

        return self.availability.known_at

    @property
    def available_at(self) -> datetime:
        """Return the governed opening instant, not a fabricated announcement time."""

        return self.availability.available_at

    @property
    def earliest_temporal_usability_at(self) -> datetime:
        """Return the later of source availability and local raw-response completion."""

        return max(
            self.available_at,
            self.financial_row.artifact_reference.evidence.response_completed_at,
        )

    @property
    def reference_only(self) -> bool:
        """Whether the object is a non-authorizing reference projection."""

        return True

    @property
    def must_not_use_for_decision(self) -> bool:
        """Decision consumers must reload catalogs and exact historical identities."""

        return True

    @property
    def must_not_execute(self) -> bool:
        """This witness has no order or execution capability."""

        return True

    def is_temporally_available_at(self, as_of: datetime) -> bool:
        """Check only necessary availability timing; this is not decision approval."""

        _require_utc(as_of, "as_of")
        self.__post_init__()
        return self.known_at <= as_of and self.earliest_temporal_usability_at <= as_of

    def to_dict(self) -> dict[str, object]:
        """Return the closed v3 reference payload without adding source timestamps."""

        self.__post_init__()
        payload = self._payload()
        return {**payload, "witness_sha256": _payload_sha256(payload)}

    def _payload(self) -> dict[str, object]:
        """Return the v3 payload covered by the local integrity digest."""

        return {
            "schema": "financial-next-session-source-time-witness.v3",
            "financial_row": self.financial_row.to_dict(),
            "availability": self.availability.to_dict(),
            "governance": self.governance.to_dict(),
            "reference_only": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }


def _artifact_reference_payload(reference: FinancialResponseArtifactRef) -> dict[str, object]:
    """Return full immutable response identity needed for an exact row reread."""

    evidence = reference.evidence
    return {
        "capture_id": str(reference.capture_id),
        "location": reference.location,
        "format_version": reference.format_version,
        "encryption_algorithm": reference.encryption_algorithm,
        "encryption_key_ref": reference.encryption_key_ref,
        "encryption_key_version": reference.encryption_key_version,
        **evidence.to_dict(),
    }


def _opening_clock_utc(session_date: date, rule: ExchangeSessionOpeningRule) -> datetime:
    """Convert an explicit wall clock and reject timezone gaps or overlaps."""

    _require_date(session_date, "session_date")
    try:
        zone = ZoneInfo(rule.timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("opening rule timezone is unknown") from error
    local_naive = datetime.combine(session_date, rule.local_open_time)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = local_naive.replace(tzinfo=zone, fold=fold)
        candidate_utc = candidate.astimezone(UTC)
        if candidate_utc.astimezone(zone).replace(tzinfo=None) == local_naive:
            candidates.add(candidate_utc)
    if len(candidates) != 1:
        raise ValueError("opening clock is nonexistent or ambiguous in its timezone")
    return next(iter(candidates))


def _bounded_text(value: object, field_name: str, maximum: int) -> None:
    """Require bounded, unpadded text with no control characters."""

    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be bounded canonical text")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} contains control characters")


def _require_date(value: object, field_name: str) -> None:
    """Require an exact date value and reject datetime subclasses."""

    if type(value) is not date:
        raise ValueError(f"{field_name} must be a date without a time component")


def _require_utc(value: object, field_name: str) -> None:
    """Require an exact aware zero-offset instant."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be an aware UTC datetime")


def _require_uuid_text(value: str, field_name: str) -> None:
    """Require one canonical UUID string."""

    if type(value) is not str:
        raise ValueError(f"{field_name} must be a UUID string")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a canonical UUID") from error


def _is_sha256(value: object) -> bool:
    """Return whether the value is one lowercase SHA-256 digest."""

    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _payload_sha256(payload: dict[str, object]) -> str:
    """Hash one canonical v3 payload to detect accidental projection changes."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(b"agomtradepro:financial-next-session-witness:v3\0" + encoded).hexdigest()


__all__ = [
    "FinancialApprovalIdentity",
    "FinancialCalendarPublicationReference",
    "FinancialDisclosureAvailabilityPolicy",
    "FinancialNativeRowBinding",
    "FinancialNextSessionAvailabilityReference",
    "FinancialNextSessionGovernanceBinding",
    "FinancialNextSessionSourceTimeWitnessV3",
    "FinancialOfficialSourceIdentity",
    "financial_disclosure_availability_policy_sha256",
]
