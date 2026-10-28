"""Pure identity, seal, and forward-only lifecycle contracts for calendar publication."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from .calendar_publication_window import (
    CalendarPublicationLifecycle,
    CalendarPublicationWindow,
    CalendarPublicationWindowError,
)
from .contracts import MAX_CATALOG_TTL_SECONDS, DatasetKey, PublicationPolicy
from .control_plane import (
    CalendarNullableMemberCodecVersion,
    CalendarPublicationMemberReference,
)
from .exchange_calendar import (
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotReference,
)
from .publication_evidence import (
    calendar_publication_hash,
    validate_calendar_publication_evidence,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXCHANGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_ACTIVATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,299}$")
_PUBLICATION_HASH_SCHEMA = "exchange-calendar-formal-publication-v1"


class CalendarFormalPublicationError(ValueError):
    """Recognized invalid calendar publication identity or transition."""

    def __init__(self, code: str, message: str) -> None:
        """Attach a stable machine-readable reason to the domain failure."""

        self.code = code
        super().__init__(message)


class CalendarPublicationTransition(StrEnum):
    """Allowed forward-only outcomes for one exact exchange pointer scope."""

    FIRST_PUBLISH = "first_publish"
    FORWARD_PUBLISH = "forward_publish"
    EXACT_CURRENT_REPLAY = "exact_current_replay"


@dataclass(frozen=True, slots=True)
class CalendarPublicationPointerExpectation:
    """Expected pointer identity, with ``updated_at`` used only as a CAS token.

    The persisted pointer has no numeric epoch. This value binds its row UUID,
    target id/hash, activation id, and exact database update timestamp instead.
    """

    dataset_key: str
    publication_key: str
    pointer_id: str | None
    publication_id: str | None
    publication_hash: str | None
    activation_id: str | None
    updated_at: datetime | None

    def __post_init__(self) -> None:
        """Reject partial pointer identities and malformed time tokens."""

        self.validate()

    @property
    def is_absent(self) -> bool:
        """Return whether this expectation represents an absent pointer row."""

        self.validate()
        return self.pointer_id is None

    def validate(self) -> None:
        """Recheck every field for callers that may bypass frozen DTO guards."""

        _require_text(self.dataset_key, "dataset_key", 160)
        _require_text(self.publication_key, "publication_key", 300)
        values = (
            self.pointer_id,
            self.publication_id,
            self.publication_hash,
            self.activation_id,
            self.updated_at,
        )
        if all(value is None for value in values):
            return
        if any(value is None for value in values):
            raise CalendarFormalPublicationError(
                "CALENDAR_POINTER_IDENTITY_INVALID",
                "pointer identity must be either wholly absent or fully bound",
            )
        _require_uuid(self.pointer_id, "pointer_id")
        _require_uuid(self.publication_id, "publication_id")
        _require_sha256(self.publication_hash, "publication_hash")
        _require_token(self.activation_id, "activation_id", 300)
        _require_utc(self.updated_at, "pointer.updated_at")


@dataclass(frozen=True, slots=True)
class CalendarFormalPublicationSeal:
    """Immutable formal identity derived from one exact snapshot and catalog pair.

    This is a content seal only. It is not proof that a database pointer moved,
    an Audit event was committed, or any consumer is authorized to execute.
    """

    dataset: DatasetKey
    exchange: str
    publication_key: str
    calendar_response_max_age_seconds: int
    contract_recorded_at: datetime
    policy: PublicationPolicy
    policy_recorded_at: datetime
    member_reference: CalendarPublicationMemberReference
    snapshot: ExchangeCalendarSnapshot
    snapshot_reference: ExchangeCalendarSnapshotReference
    snapshot_provider_name: str
    snapshot_first_seen_at: datetime
    snapshot_recorded_at: datetime
    member_manifest_hash: str
    publication_hash: str

    def __post_init__(self) -> None:
        """Verify exact source, catalog versions, nullable codec, and both hashes."""

        self.validate()

    @property
    def policy_identity(self) -> str:
        """Return the exact policy identity sealed into the publication hash."""

        self.validate()
        return self.policy.identity

    @property
    def policy_version(self) -> str:
        """Return the explicit versioned policy token."""

        self.validate()
        return self.policy.policy_version

    @property
    def codec_version(self) -> CalendarNullableMemberCodecVersion:
        """Return the policy-bound nullable member codec version."""

        self.validate()
        codec = self.policy.member_codec_version
        if type(codec) is not CalendarNullableMemberCodecVersion:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_POLICY_CODEC_INVALID",
                "calendar policy must bind a supported nullable-member codec",
            )
        return codec

    def validate(self) -> None:
        """Recompute the seal and revalidate nested source/catalog evidence."""

        if type(self.dataset) is not DatasetKey:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_DATASET_INVALID", "dataset must be a typed DatasetKey"
            )
        if type(self.policy) is not PublicationPolicy:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_POLICY_INVALID", "policy must be a typed PublicationPolicy"
            )
        if type(self.member_reference) is not CalendarPublicationMemberReference:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_MEMBER_INVALID",
                "member_reference must use the calendar nullable-member codec",
            )
        if type(self.snapshot_reference) is not ExchangeCalendarSnapshotReference:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_SNAPSHOT_INVALID",
                "snapshot_reference must be an exact typed snapshot reference",
            )
        if type(self.snapshot) is not ExchangeCalendarSnapshot:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_SNAPSHOT_INVALID",
                "snapshot must be the exact immutable snapshot fact",
            )
        try:
            self.dataset.__post_init__()
            self.policy.__post_init__()
            self.member_reference.__post_init__()
            self.snapshot.__post_init__()
            self.snapshot_reference.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_NESTED_EVIDENCE_INVALID",
                "nested dataset, policy, member, or snapshot evidence is invalid",
            ) from error

        if not _is_exchange_token(self.exchange):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_EXCHANGE_INVALID", "exchange must be an explicit bounded token"
            )
        if self.publication_key != exchange_calendar_publication_key(self.exchange):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_PUBLICATION_KEY_INVALID",
                "publication key must be derived from the exact exchange token",
            )
        if (
            type(self.calendar_response_max_age_seconds) is not int
            or self.calendar_response_max_age_seconds < 1
            or self.calendar_response_max_age_seconds > MAX_CATALOG_TTL_SECONDS
        ):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_TTL_INVALID",
                "calendar response TTL must be an explicitly configured positive integer",
            )
        _require_utc(self.contract_recorded_at, "contract_recorded_at")
        _require_utc(self.policy_recorded_at, "policy_recorded_at")
        _require_utc(self.snapshot_first_seen_at, "snapshot_first_seen_at")
        _require_utc(self.snapshot_recorded_at, "snapshot_recorded_at")
        _require_text(self.snapshot_provider_name, "snapshot_provider_name", 100)
        if self.snapshot_recorded_at < self.snapshot_first_seen_at:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_SNAPSHOT_KNOWLEDGE_INVALID",
                "snapshot recorded time cannot precede local response completion",
            )
        if self.policy.dataset != self.dataset:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_POLICY_DATASET_MISMATCH",
                "policy and active contract dataset versions must match exactly",
            )
        if (
            not self.policy.uses_versioned_evidence
            or self.policy.member_codec_version is not CalendarNullableMemberCodecVersion.V1
        ):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_POLICY_CODEC_INVALID",
                "a versioned policy must explicitly bind calendar-nullable-member-v1",
            )
        if self.member_reference.codec_version is not self.policy.member_codec_version:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_POLICY_CODEC_INVALID",
                "member codec must equal the version bound by the policy",
            )
        self._validate_snapshot_member_binding()

        knowledge_anchor = max(
            self.snapshot_recorded_at,
            self.contract_recorded_at,
            self.policy_recorded_at,
        )
        try:
            validate_calendar_publication_evidence(
                self.policy,
                (self.member_reference,),
                codec_version=CalendarNullableMemberCodecVersion.V1,
                published_at=knowledge_anchor,
                knowledge_cutoff=knowledge_anchor,
            )
            expected_manifest_hash = _calendar_member_manifest_hash(
                self.member_reference, self.policy
            )
        except (TypeError, ValueError) as error:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_POLICY_EVIDENCE_INVALID",
                "calendar member does not satisfy the exact versioned policy",
            ) from error
        if self.member_manifest_hash != expected_manifest_hash:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_MEMBER_MANIFEST_MISMATCH",
                "member manifest hash does not match the nullable calendar member",
            )
        _require_sha256(self.member_manifest_hash, "member_manifest_hash")
        expected_publication_hash = _publication_content_hash(self)
        if self.publication_hash != expected_publication_hash:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_PUBLICATION_HASH_MISMATCH",
                "formal publication hash does not match sealed inputs",
            )
        _require_sha256(self.publication_hash, "publication_hash")

    def _validate_snapshot_member_binding(self) -> None:
        """Require every member identity to refer to this exact retained snapshot."""

        member = self.member_reference.member
        snapshot = self.snapshot_reference
        if (
            self.snapshot.reference() != snapshot
            or self.snapshot.exchange != self.exchange
            or self.snapshot.provider_name != self.snapshot_provider_name
            or self.snapshot.first_seen_at != self.snapshot_first_seen_at
            or self.snapshot.recorded_at != self.snapshot_recorded_at
            or snapshot.exchange != self.exchange
            or self.member_reference.snapshot_content_hash != snapshot.content_hash
            or self.member_reference.snapshot_record_digest != snapshot.record_digest
            or snapshot.coverage_start > snapshot.coverage_end
        ):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_MEMBER_SNAPSHOT_MISMATCH",
                "member snapshot seals or exchange differ from the exact snapshot reference",
            )
        expected_natural_key = calendar_snapshot_natural_key(
            snapshot.exchange, snapshot.coverage_start, snapshot.coverage_end
        )
        if self.snapshot.candidate.raw_reference.dataset_key != self.dataset.value:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_MEMBER_RAW_DATASET_MISMATCH",
                "retained raw payload dataset differs from the active publication dataset",
            )
        if (
            member.source_record_id != snapshot.snapshot_id
            or member.fact_pk != snapshot.snapshot_id
        ):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_MEMBER_SNAPSHOT_MISMATCH",
                "member fact identity differs from the exact persisted snapshot",
            )
        if (
            member.dataset_key != self.dataset.value
            or member.source != self.snapshot_provider_name
            or member.natural_key != expected_natural_key
        ):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_MEMBER_SCOPE_MISMATCH",
                "member dataset, provider, snapshot identity, or coverage scope differs",
            )
        if member.raw_payload_hash != snapshot.raw_payload_hash:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_MEMBER_RAW_PAYLOAD_MISMATCH",
                "member RawPayload hash differs from the exact snapshot reference",
            )
        if member.fetched_at != self.snapshot_first_seen_at:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_MEMBER_TIME_MISMATCH",
                "member fetched_at must preserve local response completion exactly",
            )

    def to_payload(self) -> dict[str, object]:
        """Return the exact hash input for auditing and reproducible verification."""

        self.validate()
        return _publication_payload(self)


@dataclass(frozen=True, slots=True)
class CalendarFormalPublicationRecord:
    """Persisted forward-only publication state over one immutable formal seal."""

    seal: CalendarFormalPublicationSeal
    publication_id: str
    activation_id: str
    lifecycle: CalendarPublicationLifecycle
    published_at: datetime
    superseded_at: datetime | None = None

    def __post_init__(self) -> None:
        """Reject unsealed, unsupported, or temporally inconsistent publication rows."""

        self.validate()

    @property
    def window(self) -> CalendarPublicationWindow:
        """Return the existing response-age window over this persisted state."""

        self.validate()
        return self._make_window()

    def is_effective_at(self, as_of: datetime) -> bool:
        """Return whether this record's half-open publication window contains as_of."""

        self.validate()
        _require_utc(as_of, "as_of")
        if as_of < max(
            self.seal.contract_recorded_at,
            self.seal.policy_recorded_at,
            self.seal.snapshot_recorded_at,
        ):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN",
                "publication configuration or source fact was not known at this cutoff",
            )
        try:
            return self._make_window().is_effective_at(as_of)
        except CalendarPublicationWindowError as error:
            raise _window_error(error) from error

    def validate(self) -> None:
        """Revalidate the seal and exact publication knowledge clocks."""

        if type(self.seal) is not CalendarFormalPublicationSeal:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_SEAL_INVALID", "record must contain a formal calendar seal"
            )
        try:
            self.seal.validate()
        except CalendarFormalPublicationError:
            raise
        _require_uuid(self.publication_id, "publication_id")
        _require_token(self.activation_id, "activation_id", 300)
        if type(self.lifecycle) is not CalendarPublicationLifecycle:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_LIFECYCLE_INVALID", "publication lifecycle must be typed"
            )
        if self.lifecycle not in {
            CalendarPublicationLifecycle.PUBLISHED,
            CalendarPublicationLifecycle.SUPERSEDED,
        }:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_LIFECYCLE_UNSUPPORTED",
                "rollback, reinstatement, and unknown lifecycle are unsupported",
            )
        _require_utc(self.published_at, "published_at")
        if self.published_at < max(
            self.seal.snapshot_recorded_at,
            self.seal.contract_recorded_at,
            self.seal.policy_recorded_at,
        ):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN",
                "publication time precedes a required source or configuration knowledge time",
            )
        if self.lifecycle is CalendarPublicationLifecycle.PUBLISHED:
            if self.superseded_at is not None:
                raise CalendarFormalPublicationError(
                    "CALENDAR_FORMAL_LIFECYCLE_INVALID",
                    "a current publication cannot have a superseded_at time",
                )
        elif self.superseded_at is None:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_LIFECYCLE_INVALID",
                "a superseded publication requires the exact forward transition time",
            )
        try:
            self._make_window()
        except CalendarPublicationWindowError as error:
            raise _window_error(error) from error

    def _make_window(self) -> CalendarPublicationWindow:
        """Construct the shared pure TTL window from sealed source evidence."""

        return CalendarPublicationWindow(
            snapshot=self.seal.snapshot,
            calendar_response_max_age_seconds=self.seal.calendar_response_max_age_seconds,
            published_at=self.published_at,
            lifecycle=self.lifecycle,
            superseded_at=self.superseded_at,
        )


@dataclass(frozen=True, slots=True)
class CalendarPublicationTransitionDecision:
    """Typed decision for first publish, forward publish, or exact replay."""

    transition: CalendarPublicationTransition
    current_publication_id: str | None
    current_publication_hash: str | None

    def __post_init__(self) -> None:
        """Validate identity fields returned by the transition resolver."""

        if type(self.transition) is not CalendarPublicationTransition:
            raise CalendarFormalPublicationError(
                "CALENDAR_TRANSITION_INVALID", "transition must use the supported enum"
            )
        if self.transition is CalendarPublicationTransition.FIRST_PUBLISH:
            if self.current_publication_id is not None or self.current_publication_hash is not None:
                raise CalendarFormalPublicationError(
                    "CALENDAR_TRANSITION_INVALID", "first publish cannot name an old winner"
                )
        else:
            _require_uuid(self.current_publication_id, "current_publication_id")
            _require_sha256(self.current_publication_hash, "current_publication_hash")


def exchange_calendar_publication_key(exchange: str) -> str:
    """Return the stable pointer key for an exact explicit exchange token."""

    if not _is_exchange_token(exchange):
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_EXCHANGE_INVALID", "exchange must be an explicit bounded token"
        )
    return f"exchange-calendar:{exchange}"


def calendar_snapshot_natural_key(
    exchange: str, coverage_start: object, coverage_end: object
) -> str:
    """Build the deterministic full-coverage natural key for one calendar snapshot."""

    if not _is_exchange_token(exchange):
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_EXCHANGE_INVALID", "exchange must be an explicit bounded token"
        )
    if type(coverage_start) is not date or type(coverage_end) is not date:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_COVERAGE_INVALID", "calendar coverage endpoints must be dates"
        )
    if coverage_start > coverage_end:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_COVERAGE_INVALID", "calendar coverage endpoints are reversed"
        )
    return f"{exchange}:{coverage_start.isoformat()}:{coverage_end.isoformat()}"


def create_calendar_formal_publication_seal(
    *,
    dataset: DatasetKey,
    exchange: str,
    calendar_response_max_age_seconds: int,
    contract_recorded_at: datetime,
    policy: PublicationPolicy,
    policy_recorded_at: datetime,
    snapshot: ExchangeCalendarSnapshot,
    member_reference: CalendarPublicationMemberReference,
) -> CalendarFormalPublicationSeal:
    """Seal an exact snapshot, its nullable member, exact policy, and explicit TTL."""

    if type(snapshot) is not ExchangeCalendarSnapshot:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_SNAPSHOT_INVALID", "snapshot must be a persisted typed calendar fact"
        )
    if (
        type(calendar_response_max_age_seconds) is not int
        or calendar_response_max_age_seconds < 1
        or calendar_response_max_age_seconds > MAX_CATALOG_TTL_SECONDS
    ):
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_TTL_INVALID",
            "calendar response TTL must be an explicitly configured positive integer",
        )
    try:
        snapshot.__post_init__()
        if snapshot.exchange != exchange:
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_MEMBER_SNAPSHOT_MISMATCH",
                "snapshot exchange differs from the requested exchange",
            )
        member_manifest_hash = _calendar_member_manifest_hash(member_reference, policy)
        publication_key = exchange_calendar_publication_key(exchange)
        snapshot_reference = snapshot.reference()
        snapshot_provider_name = snapshot.provider_name
        publication_hash = _publication_content_hash_from_values(
            dataset=dataset,
            exchange=exchange,
            publication_key=publication_key,
            calendar_response_max_age_seconds=calendar_response_max_age_seconds,
            contract_recorded_at=contract_recorded_at,
            policy=policy,
            policy_recorded_at=policy_recorded_at,
            member_reference=member_reference,
            snapshot=snapshot,
            snapshot_reference=snapshot_reference,
            snapshot_provider_name=snapshot_provider_name,
            snapshot_first_seen_at=snapshot.first_seen_at,
            snapshot_recorded_at=snapshot.recorded_at,
            member_manifest_hash=member_manifest_hash,
        )
        return CalendarFormalPublicationSeal(
            dataset=dataset,
            exchange=exchange,
            publication_key=publication_key,
            calendar_response_max_age_seconds=calendar_response_max_age_seconds,
            contract_recorded_at=contract_recorded_at,
            policy=policy,
            policy_recorded_at=policy_recorded_at,
            member_reference=member_reference,
            snapshot=snapshot,
            snapshot_reference=snapshot_reference,
            snapshot_provider_name=snapshot_provider_name,
            snapshot_first_seen_at=snapshot.first_seen_at,
            snapshot_recorded_at=snapshot.recorded_at,
            member_manifest_hash=member_manifest_hash,
            publication_hash=publication_hash,
        )
    except CalendarFormalPublicationError:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_INPUT_INVALID", "formal publication inputs are invalid"
        ) from error


def calendar_formal_seals_have_same_evidence(
    left: CalendarFormalPublicationSeal,
    right: CalendarFormalPublicationSeal,
) -> bool:
    """Compare every sealed value except the two repository-assigned member IDs.

    Member row and publication row IDs are deliberately outside the existing
    nullable-member evidence encoding. Repositories assign these storage IDs;
    all source identities, policy values, knowledge clocks, and seals still
    require full value equality, rather than merely matching hash strings.
    """

    if (
        type(left) is not CalendarFormalPublicationSeal
        or type(right) is not CalendarFormalPublicationSeal
    ):
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_SEAL_INVALID", "seal comparison requires typed formal seals"
        )
    left.validate()
    right.validate()
    right_member = right.member_reference.member
    aligned_left = replace(
        left,
        member_reference=replace(
            left.member_reference,
            member=replace(
                left.member_reference.member,
                member_id=right_member.member_id,
                publication_id=right_member.publication_id,
            ),
        ),
    )
    return aligned_left == right


def decide_calendar_publication_transition(
    *,
    proposed_seal: CalendarFormalPublicationSeal,
    expected_pointer: CalendarPublicationPointerExpectation,
    actual_pointer: CalendarPublicationPointerExpectation,
    current_record: CalendarFormalPublicationRecord | None,
    activation_id: str,
) -> CalendarPublicationTransition:
    """Require exact pointer CAS and allow only forward publish or exact replay."""

    if type(proposed_seal) is not CalendarFormalPublicationSeal:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_SEAL_INVALID", "proposed_seal must be a formal calendar seal"
        )
    proposed_seal.validate()
    expected_pointer.validate()
    actual_pointer.validate()
    _require_token(activation_id, "activation_id", 300)
    scope = (proposed_seal.dataset.value, proposed_seal.publication_key)
    if scope != (expected_pointer.dataset_key, expected_pointer.publication_key):
        raise CalendarFormalPublicationError(
            "CALENDAR_POINTER_SCOPE_MISMATCH", "expected pointer is for another publication scope"
        )
    if scope != (actual_pointer.dataset_key, actual_pointer.publication_key):
        raise CalendarFormalPublicationError(
            "CALENDAR_POINTER_SCOPE_MISMATCH", "actual pointer is for another publication scope"
        )
    if actual_pointer != expected_pointer:
        raise CalendarFormalPublicationError(
            "CALENDAR_POINTER_CAS_MISMATCH", "current pointer differs from the supplied CAS token"
        )
    if expected_pointer.is_absent:
        if current_record is not None:
            raise CalendarFormalPublicationError(
                "CALENDAR_POINTER_TARGET_INVALID", "absent pointer cannot have a current winner"
            )
        return CalendarPublicationTransition.FIRST_PUBLISH
    if current_record is None:
        raise CalendarFormalPublicationError(
            "CALENDAR_POINTER_TARGET_INVALID", "present pointer requires its exact publication"
        )
    current_record.validate()
    if (
        current_record.seal.dataset.value != scope[0]
        or current_record.seal.publication_key != scope[1]
        or current_record.publication_id != expected_pointer.publication_id
        or current_record.seal.publication_hash != expected_pointer.publication_hash
        or current_record.activation_id != expected_pointer.activation_id
        or current_record.lifecycle is not CalendarPublicationLifecycle.PUBLISHED
    ):
        raise CalendarFormalPublicationError(
            "CALENDAR_POINTER_TARGET_INVALID",
            "pointer target is not the exact current published calendar winner",
        )
    _validate_pointer_publication_time(current_record, actual_pointer)
    if calendar_formal_seals_have_same_evidence(proposed_seal, current_record.seal):
        if activation_id != current_record.activation_id:
            raise CalendarFormalPublicationError(
                "CALENDAR_CURRENT_REPLAY_MISMATCH",
                "same-current replay must preserve the original activation identity",
            )
        return CalendarPublicationTransition.EXACT_CURRENT_REPLAY
    return CalendarPublicationTransition.FORWARD_PUBLISH


def validate_current_calendar_publication(
    record: CalendarFormalPublicationRecord,
    pointer: CalendarPublicationPointerExpectation,
    *,
    as_of: datetime,
) -> None:
    """Validate a current-pointer read without claiming historical pointer replay."""

    if type(record) is not CalendarFormalPublicationRecord:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_RECORD_INVALID", "record must be a typed formal publication"
        )
    record.validate()
    pointer.validate()
    _require_utc(as_of, "as_of")
    if record.lifecycle is not CalendarPublicationLifecycle.PUBLISHED:
        raise CalendarFormalPublicationError(
            "CALENDAR_CURRENT_READ_HISTORY_UNSUPPORTED",
            "this reader only returns the current publication, not superseded history",
        )
    if (
        pointer.is_absent
        or pointer.dataset_key != record.seal.dataset.value
        or pointer.publication_key != record.seal.publication_key
        or pointer.publication_id != record.publication_id
        or pointer.publication_hash != record.seal.publication_hash
        or pointer.activation_id != record.activation_id
    ):
        raise CalendarFormalPublicationError(
            "CALENDAR_CURRENT_POINTER_MISMATCH",
            "publication does not exactly match the canonical current pointer",
        )
    if pointer.updated_at is None or pointer.updated_at > as_of:
        raise CalendarFormalPublicationError(
            "CALENDAR_CURRENT_POINTER_NOT_KNOWN_AT_CUTOFF",
            "current pointer update was not known at the requested cutoff",
        )
    if as_of < max(
        record.seal.contract_recorded_at,
        record.seal.policy_recorded_at,
        record.seal.snapshot_recorded_at,
    ):
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN",
            "required snapshot or catalog configuration was not known at this cutoff",
        )
    try:
        if as_of < record.published_at:
            raise CalendarFormalPublicationError(
                "CALENDAR_PUBLICATION_NOT_EFFECTIVE_AT_CUTOFF",
                "current publication was not effective at the requested cutoff",
            )
        _validate_pointer_publication_time(record, pointer)
        if not record.window.is_effective_at(as_of):
            raise CalendarFormalPublicationError(
                "CALENDAR_FORMAL_TTL_EXPIRED",
                "current calendar response-age window is expired at the requested cutoff",
            )
    except CalendarPublicationWindowError as error:
        raise _window_error(error) from error


def _validate_pointer_publication_time(
    record: CalendarFormalPublicationRecord,
    pointer: CalendarPublicationPointerExpectation,
) -> None:
    """Require the pointer and publication to retain their single activation clock."""

    if pointer.updated_at != record.published_at:
        raise CalendarFormalPublicationError(
            "CALENDAR_CURRENT_POINTER_TIME_MISMATCH",
            "current pointer time differs from the publication activation time",
        )


def _publication_content_hash(seal: CalendarFormalPublicationSeal) -> str:
    """Hash the complete seal fields using the fixed formal-publication encoding."""

    return _publication_content_hash_from_values(
        dataset=seal.dataset,
        exchange=seal.exchange,
        publication_key=seal.publication_key,
        calendar_response_max_age_seconds=seal.calendar_response_max_age_seconds,
        contract_recorded_at=seal.contract_recorded_at,
        policy=seal.policy,
        policy_recorded_at=seal.policy_recorded_at,
        member_reference=seal.member_reference,
        snapshot=seal.snapshot,
        snapshot_reference=seal.snapshot_reference,
        snapshot_provider_name=seal.snapshot_provider_name,
        snapshot_first_seen_at=seal.snapshot_first_seen_at,
        snapshot_recorded_at=seal.snapshot_recorded_at,
        member_manifest_hash=seal.member_manifest_hash,
    )


def _publication_content_hash_from_values(
    *,
    dataset: DatasetKey,
    exchange: str,
    publication_key: str,
    calendar_response_max_age_seconds: int,
    contract_recorded_at: datetime,
    policy: PublicationPolicy,
    policy_recorded_at: datetime,
    member_reference: CalendarPublicationMemberReference,
    snapshot: ExchangeCalendarSnapshot,
    snapshot_reference: ExchangeCalendarSnapshotReference,
    snapshot_provider_name: str,
    snapshot_first_seen_at: datetime,
    snapshot_recorded_at: datetime,
    member_manifest_hash: str,
) -> str:
    """Compute the SHA-256 formal hash from versioned inputs and knowledge times."""

    if type(dataset) is not DatasetKey or type(policy) is not PublicationPolicy:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_INPUT_INVALID", "dataset and policy must be typed values"
        )
    if type(member_reference) is not CalendarPublicationMemberReference:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_MEMBER_INVALID", "member reference is invalid"
        )
    if type(snapshot_reference) is not ExchangeCalendarSnapshotReference:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_SNAPSHOT_INVALID", "snapshot reference is invalid"
        )
    if type(snapshot) is not ExchangeCalendarSnapshot:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_SNAPSHOT_INVALID", "snapshot fact is invalid"
        )
    if snapshot.reference() != snapshot_reference:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_SNAPSHOT_INVALID", "snapshot fact and reference differ"
        )
    _require_text(snapshot_provider_name, "snapshot_provider_name", 100)
    _require_utc(contract_recorded_at, "contract_recorded_at")
    _require_utc(policy_recorded_at, "policy_recorded_at")
    _require_utc(snapshot_first_seen_at, "snapshot_first_seen_at")
    _require_utc(snapshot_recorded_at, "snapshot_recorded_at")
    payload = _publication_payload_from_values(
        dataset=dataset,
        exchange=exchange,
        publication_key=publication_key,
        calendar_response_max_age_seconds=calendar_response_max_age_seconds,
        contract_recorded_at=contract_recorded_at,
        policy=policy,
        policy_recorded_at=policy_recorded_at,
        member_reference=member_reference,
        snapshot=snapshot,
        snapshot_reference=snapshot_reference,
        snapshot_provider_name=snapshot_provider_name,
        snapshot_first_seen_at=snapshot_first_seen_at,
        snapshot_recorded_at=snapshot_recorded_at,
        member_manifest_hash=member_manifest_hash,
    )
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_INPUT_INVALID", "formal hash payload is not canonical JSON"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _publication_payload_from_values(
    *,
    dataset: DatasetKey,
    exchange: str,
    publication_key: str,
    calendar_response_max_age_seconds: int,
    contract_recorded_at: datetime,
    policy: PublicationPolicy,
    policy_recorded_at: datetime,
    member_reference: CalendarPublicationMemberReference,
    snapshot: ExchangeCalendarSnapshot,
    snapshot_reference: ExchangeCalendarSnapshotReference,
    snapshot_provider_name: str,
    snapshot_first_seen_at: datetime,
    snapshot_recorded_at: datetime,
    member_manifest_hash: str,
) -> dict[str, object]:
    """Build the one canonical formal-publication payload before hashing."""

    return {
        "encoding": _PUBLICATION_HASH_SCHEMA,
        "dataset_key": dataset.value,
        "contract_version": dataset.contract_version,
        "schema_version": dataset.schema_version,
        "exchange": exchange,
        "publication_key": publication_key,
        "calendar_response_max_age_seconds": calendar_response_max_age_seconds,
        "contract_recorded_at": _utc_text(contract_recorded_at),
        "policy_version": policy.policy_version,
        "policy_identity": policy.identity,
        "policy_recorded_at": _utc_text(policy_recorded_at),
        "member_codec_version": (
            policy.member_codec_version.value if policy.member_codec_version is not None else None
        ),
        "member_manifest_hash": member_manifest_hash,
        "snapshot_provider_name": snapshot_provider_name,
        "member": member_reference.to_payload(),
        "snapshot": {
            "snapshot_id": snapshot_reference.snapshot_id,
            "exchange": snapshot_reference.exchange,
            "coverage_start": snapshot_reference.coverage_start.isoformat(),
            "coverage_end": snapshot_reference.coverage_end.isoformat(),
            "content_hash": snapshot_reference.content_hash,
            "record_digest": snapshot_reference.record_digest,
            "raw_payload_id": snapshot_reference.raw_payload_id,
            "raw_payload_hash": snapshot_reference.raw_payload_hash,
            "raw_record_digest": snapshot_reference.raw_record_digest,
            "first_seen_at": _utc_text(snapshot_first_seen_at),
            "recorded_at": _utc_text(snapshot_recorded_at),
        },
    }


def _publication_payload(seal: CalendarFormalPublicationSeal) -> dict[str, object]:
    """Return the explicit versioned hash payload for audit and stable tests."""

    return _publication_payload_from_values(
        dataset=seal.dataset,
        exchange=seal.exchange,
        publication_key=seal.publication_key,
        calendar_response_max_age_seconds=seal.calendar_response_max_age_seconds,
        contract_recorded_at=seal.contract_recorded_at,
        policy=seal.policy,
        policy_recorded_at=seal.policy_recorded_at,
        member_reference=seal.member_reference,
        snapshot=seal.snapshot,
        snapshot_reference=seal.snapshot_reference,
        snapshot_provider_name=seal.snapshot_provider_name,
        snapshot_first_seen_at=seal.snapshot_first_seen_at,
        snapshot_recorded_at=seal.snapshot_recorded_at,
        member_manifest_hash=seal.member_manifest_hash,
    )


def _calendar_member_manifest_hash(
    reference: CalendarPublicationMemberReference,
    policy: PublicationPolicy,
) -> str:
    """Match the existing nullable calendar member hash using pure Domain code."""

    if type(reference) is not CalendarPublicationMemberReference:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_MEMBER_INVALID", "calendar member reference is invalid"
        )
    if type(policy) is not PublicationPolicy:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_POLICY_INVALID", "calendar publication policy is invalid"
        )
    if (
        not policy.uses_versioned_evidence
        or policy.member_codec_version is not CalendarNullableMemberCodecVersion.V1
        or reference.codec_version is not CalendarNullableMemberCodecVersion.V1
        or reference.member.dataset_key != policy.dataset.value
    ):
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_POLICY_CODEC_INVALID",
            "calendar member must match the versioned policy and nullable codec",
        )
    try:
        return calendar_publication_hash(
            [reference],
            policy=policy,
            codec_version=CalendarNullableMemberCodecVersion.V1,
        )
    except (TypeError, ValueError) as error:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_MEMBER_INVALID", "calendar member hash input is not canonical"
        ) from error


def _window_error(error: CalendarPublicationWindowError) -> CalendarFormalPublicationError:
    """Preserve the established calendar-window reason code at this boundary."""

    return CalendarFormalPublicationError(error.code, str(error))


def _is_exchange_token(value: object) -> bool:
    """Return whether an exchange is an explicit bounded opaque token."""

    return type(value) is str and _EXCHANGE_RE.fullmatch(value) is not None


def _require_text(value: object, field_name: str, max_length: int) -> None:
    """Require bounded, nonempty, already-trimmed text."""

    if type(value) is not str or not value or len(value) > max_length or value.strip() != value:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_TEXT_INVALID", f"{field_name} must be bounded nonempty text"
        )


def _require_token(value: object, field_name: str, max_length: int) -> None:
    """Require a bounded activation token with no whitespace."""

    if type(value) is not str or _ACTIVATION_RE.fullmatch(value) is None or len(value) > max_length:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_TOKEN_INVALID", f"{field_name} must be a bounded token"
        )


def _require_uuid(value: object, field_name: str) -> None:
    """Require one canonical lowercase UUID string."""

    if type(value) is not str:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_UUID_INVALID", f"{field_name} must be a canonical UUID"
        )
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_UUID_INVALID", f"{field_name} must be a canonical UUID"
        ) from error
    if str(parsed) != value:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_UUID_INVALID", f"{field_name} must be a canonical UUID"
        )


def _require_sha256(value: object, field_name: str) -> None:
    """Require one lowercase unprefixed SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_HASH_INVALID", f"{field_name} must be lowercase SHA-256"
        )


def _require_utc(value: object, field_name: str) -> None:
    """Require a timezone-aware UTC instant without coercing caller input."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise CalendarFormalPublicationError(
            "CALENDAR_FORMAL_TIME_INVALID", f"{field_name} must be an aware UTC instant"
        )


def _utc_text(value: datetime) -> str:
    """Render a validated UTC instant as canonical RFC 3339 text with Z."""

    _require_utc(value, "canonical datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "CalendarFormalPublicationError",
    "CalendarFormalPublicationRecord",
    "CalendarFormalPublicationSeal",
    "CalendarPublicationPointerExpectation",
    "CalendarPublicationTransition",
    "CalendarPublicationTransitionDecision",
    "calendar_snapshot_natural_key",
    "create_calendar_formal_publication_seal",
    "decide_calendar_publication_transition",
    "exchange_calendar_publication_key",
    "validate_current_calendar_publication",
]
