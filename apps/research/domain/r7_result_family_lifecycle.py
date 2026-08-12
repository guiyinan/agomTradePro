"""Research-only R7 result-family Promotion, retirement, and rollback contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleEvent,
    R7ResultLifecycleStatus,
    derive_r7_result_lifecycle_state,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_token,
)

_FAMILY_VERSION = "r7-result-family.v1"
_OWNER_EVIDENCE_VERSION = "r7-family-result-owner-evidence.v1"
_LOCAL_LIFECYCLE_ATTESTATION_VERSION = "r7-local-lifecycle-attestation.v1"


def _require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _clock(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _flag(value: bool) -> str:
    return "true" if value else "false"


class R7FamilyLifecycleAction(StrEnum):
    """Manual family-level actions; separate from result-local v1 actions."""

    PROMOTE = "promote"
    RETIRE = "retire"
    ROLLBACK = "rollback"


class R7FamilyLifecycleStatus(StrEnum):
    """PIT state derived only by replaying the complete family stream."""

    PROMOTED = "promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"
    EXPIRED = "expired"


@dataclass(frozen=True)
class R7ResultFamilyIdentity:
    """Content-addressed policy/scope family shared by comparable R7 results."""

    family_id: str
    family_version: str
    policy_id: str
    policy_version: str
    policy_record_hash: str
    scope_content_hash: str
    content_hash: str

    @classmethod
    def from_result(
        cls,
        result: PersistedR7ResearchResult,
    ) -> R7ResultFamilyIdentity:
        """Derive one stable family from a live exact persisted result."""

        _validate_result_live(result)
        receipt = result.input_receipt
        digest = _family_hash(
            family_version=_FAMILY_VERSION,
            policy_id=receipt.policy_id,
            policy_version=receipt.policy_version,
            policy_record_hash=receipt.policy_record_hash,
            scope_content_hash=receipt.scope_content_hash,
        )
        return cls(
            family_id=f"r7-result-family:{digest[:32]}",
            family_version=_FAMILY_VERSION,
            policy_id=receipt.policy_id,
            policy_version=receipt.policy_version,
            policy_record_hash=receipt.policy_record_hash,
            scope_content_hash=receipt.scope_content_hash,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        for label, value in (
            ("family_id", self.family_id),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
        ):
            require_token(value, f"R7 result family {label}", maximum=192)
        if self.family_version != _FAMILY_VERSION:
            raise ValueError("R7 result family version is unsupported")
        for label, value in (
            ("policy_record_hash", self.policy_record_hash),
            ("scope_content_hash", self.scope_content_hash),
            ("content_hash", self.content_hash),
        ):
            require_sha256(value, f"R7 result family {label}")
        expected = _family_hash(
            family_version=self.family_version,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            policy_record_hash=self.policy_record_hash,
            scope_content_hash=self.scope_content_hash,
        )
        if self.content_hash != expected or self.family_id != (f"r7-result-family:{expected[:32]}"):
            raise ValueError("R7 result family identity or seal mismatch")


def _family_hash(
    *,
    family_version: str,
    policy_id: str,
    policy_version: str,
    policy_record_hash: str,
    scope_content_hash: str,
) -> str:
    return hash_components(
        family_version,
        policy_id,
        policy_version,
        policy_record_hash.lower(),
        scope_content_hash.lower(),
    )


@dataclass(frozen=True)
class R7LocalLifecycleStreamAttestation:
    """Research-owner head/count/seal attestation for one complete local stream."""

    attestation_id: str
    attestation_version: str
    result_ref: R7ResearchResultRef
    event_count: int
    head_event_id: str
    head_event_version: str
    head_event_hash: str
    stream_content_hash: str
    recorded_at: datetime
    owner: str = field(init=False, default="research")
    content_hash: str = field(init=False)

    @classmethod
    def from_stream(
        cls,
        *,
        attestation_id: str,
        attestation_version: str,
        complete_local_lifecycle_stream: tuple[R7ResultLifecycleEvent, ...],
        recorded_at: datetime,
    ) -> R7LocalLifecycleStreamAttestation:
        """Seal an already complete canonical result-local lifecycle stream."""

        if (
            type(complete_local_lifecycle_stream) is not tuple
            or not complete_local_lifecycle_stream
        ):
            raise ValueError("R7 local lifecycle attestation requires a complete stream")
        _require_aware(recorded_at, "R7 local lifecycle attestation recorded_at")
        result_ref = complete_local_lifecycle_stream[0].result_ref
        for event in complete_local_lifecycle_stream:
            if type(event) is not R7ResultLifecycleEvent:
                raise TypeError("R7 local lifecycle attestation event type is invalid")
            event.__post_init__()
            if event.result_ref != result_ref:
                raise ValueError("R7 local lifecycle attestation crosses results")
        derive_r7_result_lifecycle_state(
            complete_local_lifecycle_stream,
            evaluated_at=complete_local_lifecycle_stream[-1].recorded_at,
        )
        head = complete_local_lifecycle_stream[-1]
        if recorded_at < head.recorded_at:
            raise ValueError("R7 local lifecycle attestation predates its head")
        return cls(
            attestation_id=attestation_id,
            attestation_version=attestation_version,
            result_ref=result_ref,
            event_count=len(complete_local_lifecycle_stream),
            head_event_id=head.event_id,
            head_event_version=head.event_version,
            head_event_hash=head.content_hash,
            stream_content_hash=_local_lifecycle_stream_hash(
                result_ref,
                complete_local_lifecycle_stream,
            ),
            recorded_at=recorded_at,
        )

    def __post_init__(self) -> None:
        require_token(
            self.attestation_id,
            "R7 local lifecycle attestation_id",
            maximum=300,
        )
        if self.attestation_version != _LOCAL_LIFECYCLE_ATTESTATION_VERSION:
            raise ValueError("R7 local lifecycle attestation version is unsupported")
        self.result_ref.__post_init__()
        if type(self.event_count) is not int or self.event_count < 1:
            raise ValueError("R7 local lifecycle attestation count is invalid")
        require_token(self.head_event_id, "R7 local lifecycle head event_id", maximum=192)
        require_token(
            self.head_event_version,
            "R7 local lifecycle head event_version",
            maximum=192,
        )
        require_sha256(self.head_event_hash, "R7 local lifecycle head hash")
        require_sha256(self.stream_content_hash, "R7 local lifecycle stream hash")
        _require_aware(self.recorded_at, "R7 local lifecycle attestation recorded_at")
        if self.owner != "research":
            raise ValueError("R7 local lifecycle attestation owner is invalid")
        expected = _local_lifecycle_attestation_hash(self)
        try:
            current = object.__getattribute__(self, "content_hash")
        except AttributeError:
            object.__setattr__(self, "content_hash", expected)
        else:
            require_sha256(current, "R7 local lifecycle attestation content_hash")
            if current != expected:
                raise ValueError("R7 local lifecycle attestation seal mismatch")

    def validates_stream(
        self,
        stream: tuple[R7ResultLifecycleEvent, ...],
    ) -> bool:
        """Return whether this attestation exactly names the supplied full stream."""

        if type(stream) is not tuple or not stream or len(stream) != self.event_count:
            return False
        try:
            for event in stream:
                if type(event) is not R7ResultLifecycleEvent:
                    return False
                event.__post_init__()
            head = stream[-1]
            return (
                stream[0].result_ref == self.result_ref
                and all(event.result_ref == self.result_ref for event in stream)
                and head.event_id == self.head_event_id
                and head.event_version == self.head_event_version
                and head.content_hash == self.head_event_hash
                and _local_lifecycle_stream_hash(self.result_ref, stream)
                == self.stream_content_hash
            )
        except (AttributeError, TypeError, ValueError):
            return False


def _local_lifecycle_stream_hash(
    result_ref: R7ResearchResultRef,
    stream: tuple[R7ResultLifecycleEvent, ...],
) -> str:
    return hash_components(
        "r7-local-lifecycle-stream.v1",
        result_ref.result_id,
        result_ref.result_version,
        result_ref.content_hash,
        str(len(stream)),
        *(event.content_hash for event in stream),
    )


def _local_lifecycle_attestation_hash(
    value: R7LocalLifecycleStreamAttestation,
) -> str:
    return hash_components(
        value.attestation_version,
        value.attestation_id,
        value.result_ref.result_id,
        value.result_ref.result_version,
        value.result_ref.content_hash,
        str(value.event_count),
        value.head_event_id,
        value.head_event_version,
        value.head_event_hash,
        value.stream_content_hash,
        _clock(value.recorded_at),
        value.owner,
    )


@dataclass(frozen=True)
class R7FamilyResultOwnerEvidence:
    """Exact result plus its complete result-local approval stream at one cutoff."""

    evidence_version: str
    family: R7ResultFamilyIdentity
    result_ref: R7ResearchResultRef
    result_recorded_at: datetime
    local_lifecycle_status: R7ResultLifecycleStatus
    local_lifecycle_sequence: int
    local_lifecycle_head_hash: str
    local_lifecycle_event_count: int
    local_lifecycle_stream_hash: str
    local_lifecycle_attestation: R7LocalLifecycleStreamAttestation
    local_promoted_at: datetime
    local_retired_at: datetime | None
    evaluated_at: datetime
    evidence_valid_until: datetime
    research_only: bool = field(init=False, default=True)
    publishes_model_probability: bool = field(init=False, default=False)
    publishes_probability_current: bool = field(init=False, default=False)
    produces_decision: bool = field(init=False, default=False)
    executes_orders: bool = field(init=False, default=False)
    must_not_use_for_decision: bool = field(init=False, default=True)
    must_not_execute: bool = field(init=False, default=True)
    content_hash: str = field(init=False)

    @classmethod
    def from_owner_graph(
        cls,
        *,
        result: PersistedR7ResearchResult,
        complete_local_lifecycle_stream: tuple[R7ResultLifecycleEvent, ...],
        local_lifecycle_attestation: R7LocalLifecycleStreamAttestation,
        evaluated_at: datetime,
    ) -> R7FamilyResultOwnerEvidence:
        """Reread and seal one complete result-local lifecycle prefix."""

        _validate_result_live(result)
        _require_aware(evaluated_at, "R7 family owner evidence evaluated_at")
        if (
            type(complete_local_lifecycle_stream) is not tuple
            or not complete_local_lifecycle_stream
        ):
            raise ValueError("R7 family result requires a complete local lifecycle stream")
        expected_ref = R7ResearchResultRef(
            result.result_id,
            result.result_version,
            result.content_hash,
        )
        for event in complete_local_lifecycle_stream:
            if type(event) is not R7ResultLifecycleEvent:
                raise TypeError("R7 family local lifecycle event type is invalid")
            event.__post_init__()
            if event.result_ref != expected_ref:
                raise ValueError("R7 family local lifecycle crosses result identities")
        if tuple(event.sequence for event in complete_local_lifecycle_stream) != tuple(
            range(1, len(complete_local_lifecycle_stream) + 1)
        ):
            raise ValueError("R7 family local lifecycle stream is not canonical")
        if type(local_lifecycle_attestation) is not R7LocalLifecycleStreamAttestation:
            raise TypeError("R7 family local lifecycle attestation type is invalid")
        local_lifecycle_attestation.__post_init__()
        if (
            local_lifecycle_attestation.result_ref != expected_ref
            or local_lifecycle_attestation.recorded_at > evaluated_at
            or not local_lifecycle_attestation.validates_stream(complete_local_lifecycle_stream)
        ):
            raise ValueError("R7 family local lifecycle stream differs from owner attestation")
        state = derive_r7_result_lifecycle_state(
            complete_local_lifecycle_stream,
            evaluated_at=evaluated_at,
        )
        valid_until = _result_evidence_valid_until(result)
        return cls(
            evidence_version=_OWNER_EVIDENCE_VERSION,
            family=R7ResultFamilyIdentity.from_result(result),
            result_ref=expected_ref,
            result_recorded_at=result.recorded_at,
            local_lifecycle_status=state.status,
            local_lifecycle_sequence=state.sequence,
            local_lifecycle_head_hash=state.head_event_hash,
            local_lifecycle_event_count=local_lifecycle_attestation.event_count,
            local_lifecycle_stream_hash=(local_lifecycle_attestation.stream_content_hash),
            local_lifecycle_attestation=local_lifecycle_attestation,
            local_promoted_at=state.promoted_at,
            local_retired_at=state.retired_at,
            evaluated_at=evaluated_at,
            evidence_valid_until=valid_until,
        )

    def __post_init__(self) -> None:
        if self.evidence_version != _OWNER_EVIDENCE_VERSION:
            raise ValueError("R7 family owner evidence version is unsupported")
        self.family.__post_init__()
        self.result_ref.__post_init__()
        if type(self.local_lifecycle_status) is not R7ResultLifecycleStatus:
            raise TypeError("R7 family local lifecycle status is invalid")
        if type(self.local_lifecycle_sequence) is not int or self.local_lifecycle_sequence < 1:
            raise ValueError("R7 family local lifecycle sequence is invalid")
        require_sha256(
            self.local_lifecycle_head_hash,
            "R7 family local lifecycle head hash",
        )
        if (
            type(self.local_lifecycle_event_count) is not int
            or self.local_lifecycle_event_count < 1
            or self.local_lifecycle_event_count != self.local_lifecycle_sequence
        ):
            raise ValueError("R7 family local lifecycle event count is invalid")
        require_sha256(
            self.local_lifecycle_stream_hash,
            "R7 family local lifecycle stream hash",
        )
        if type(self.local_lifecycle_attestation) is not R7LocalLifecycleStreamAttestation:
            raise TypeError("R7 family local lifecycle attestation type is invalid")
        self.local_lifecycle_attestation.__post_init__()
        if (
            self.local_lifecycle_attestation.result_ref != self.result_ref
            or self.local_lifecycle_attestation.event_count != self.local_lifecycle_event_count
            or self.local_lifecycle_attestation.head_event_hash != self.local_lifecycle_head_hash
            or self.local_lifecycle_attestation.stream_content_hash
            != self.local_lifecycle_stream_hash
            or self.local_lifecycle_attestation.recorded_at > self.evaluated_at
        ):
            raise ValueError("R7 family local lifecycle attestation differs")
        for label, value in (
            ("result_recorded_at", self.result_recorded_at),
            ("local_promoted_at", self.local_promoted_at),
            ("evaluated_at", self.evaluated_at),
            ("evidence_valid_until", self.evidence_valid_until),
        ):
            _require_aware(value, f"R7 family owner evidence {label}")
        if self.local_retired_at is not None:
            _require_aware(self.local_retired_at, "R7 family owner evidence local_retired_at")
        if self.result_recorded_at > self.local_promoted_at:
            raise ValueError("R7 family result was locally promoted before recording")
        if self.evaluated_at < self.local_promoted_at:
            raise ValueError("R7 family owner evidence predates local Promotion")
        if (self.local_lifecycle_status is R7ResultLifecycleStatus.RETIRED) != (
            self.local_retired_at is not None
        ):
            raise ValueError("R7 family local retirement state is inconsistent")
        if not _strict_safety(self):
            raise ValueError("R7 family owner evidence must remain research-only")
        expected = _owner_evidence_hash(self)
        try:
            current = object.__getattribute__(self, "content_hash")
        except AttributeError:
            object.__setattr__(self, "content_hash", expected)
        else:
            require_sha256(current, "R7 family owner evidence content_hash")
            if current != expected:
                raise ValueError("R7 family owner evidence content hash mismatch")

    def is_activatable_at(self, as_of: datetime) -> bool:
        """Return whether this exact approved result may become family-active."""

        _require_aware(as_of, "R7 family activation as_of")
        return (
            self.local_lifecycle_status is R7ResultLifecycleStatus.PROMOTED
            and self.result_recorded_at <= as_of < self.evidence_valid_until
        )

    def validate_live(self) -> None:
        """Recheck all immutable projection fields and its content seal."""

        self.__post_init__()


def _owner_evidence_hash(value: R7FamilyResultOwnerEvidence) -> str:
    return hash_components(
        value.evidence_version,
        value.family.content_hash,
        value.result_ref.result_id,
        value.result_ref.result_version,
        value.result_ref.content_hash,
        _clock(value.result_recorded_at),
        value.local_lifecycle_status.value,
        str(value.local_lifecycle_sequence),
        value.local_lifecycle_head_hash.lower(),
        str(value.local_lifecycle_event_count),
        value.local_lifecycle_stream_hash.lower(),
        value.local_lifecycle_attestation.content_hash,
        _clock(value.local_promoted_at),
        "" if value.local_retired_at is None else _clock(value.local_retired_at),
        _clock(value.evaluated_at),
        _clock(value.evidence_valid_until),
        *(_flag(item) for item in _safety_values(value)),
    )


@dataclass(frozen=True)
class R7FamilyLifecycleAuthorization:
    """Research-owner authorization bound to one exact family head and action."""

    authorization_id: str
    authorization_version: str
    family: R7ResultFamilyIdentity
    event_id: str
    event_version: str
    action: R7FamilyLifecycleAction
    subject_ref: R7ResearchResultRef
    subject_owner_attestation_hash: str
    rollback_target_ref: R7ResearchResultRef | None
    rollback_target_owner_attestation_hash: str | None
    expected_sequence: int
    expected_previous_event_id: str | None
    expected_previous_event_version: str | None
    expected_previous_event_hash: str | None
    owner: str
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    reason_codes: tuple[str, ...]
    evidence_ref: str
    research_only: bool = field(init=False, default=True)
    publishes_model_probability: bool = field(init=False, default=False)
    publishes_probability_current: bool = field(init=False, default=False)
    produces_decision: bool = field(init=False, default=False)
    executes_orders: bool = field(init=False, default=False)
    must_not_use_for_decision: bool = field(init=False, default=True)
    must_not_execute: bool = field(init=False, default=True)
    content_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        authorization_id: str,
        authorization_version: str,
        family: R7ResultFamilyIdentity,
        event_id: str,
        event_version: str,
        action: R7FamilyLifecycleAction,
        subject_ref: R7ResearchResultRef,
        subject_owner_attestation_hash: str,
        rollback_target_ref: R7ResearchResultRef | None,
        rollback_target_owner_attestation_hash: str | None,
        expected_sequence: int,
        expected_previous_event_id: str | None,
        expected_previous_event_version: str | None,
        expected_previous_event_hash: str | None,
        owner: str,
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        reason_codes: tuple[str, ...],
        evidence_ref: str,
    ) -> R7FamilyLifecycleAuthorization:
        """Create one immutable authorization without accepting safety flags."""

        return cls(
            authorization_id=authorization_id,
            authorization_version=authorization_version,
            family=family,
            event_id=event_id,
            event_version=event_version,
            action=action,
            subject_ref=subject_ref,
            subject_owner_attestation_hash=subject_owner_attestation_hash,
            rollback_target_ref=rollback_target_ref,
            rollback_target_owner_attestation_hash=(rollback_target_owner_attestation_hash),
            expected_sequence=expected_sequence,
            expected_previous_event_id=expected_previous_event_id,
            expected_previous_event_version=expected_previous_event_version,
            expected_previous_event_hash=expected_previous_event_hash,
            owner=owner,
            issued_at=issued_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            reason_codes=reason_codes,
            evidence_ref=evidence_ref,
        )

    def __post_init__(self) -> None:
        for label, value in (
            ("authorization_id", self.authorization_id),
            ("authorization_version", self.authorization_version),
            ("event_id", self.event_id),
            ("event_version", self.event_version),
            ("evidence_ref", self.evidence_ref),
        ):
            require_token(value, f"R7 family authorization {label}", maximum=300)
        self.family.__post_init__()
        self.subject_ref.__post_init__()
        require_sha256(
            self.subject_owner_attestation_hash,
            "R7 family authorization subject owner attestation hash",
        )
        if type(self.action) is not R7FamilyLifecycleAction:
            raise TypeError("R7 family authorization action is invalid")
        if self.rollback_target_ref is not None:
            self.rollback_target_ref.__post_init__()
        if (self.action is R7FamilyLifecycleAction.ROLLBACK) != (
            self.rollback_target_ref is not None
        ):
            raise ValueError("R7 family rollback alone requires an exact target")
        if (self.rollback_target_ref is None) != (
            self.rollback_target_owner_attestation_hash is None
        ):
            raise ValueError("R7 family rollback target attestation is incomplete")
        if self.rollback_target_owner_attestation_hash is not None:
            require_sha256(
                self.rollback_target_owner_attestation_hash,
                "R7 family authorization rollback target attestation hash",
            )
        if type(self.expected_sequence) is not int or self.expected_sequence < 1:
            raise ValueError("R7 family authorization sequence is invalid")
        previous_fields = (
            self.expected_previous_event_id,
            self.expected_previous_event_version,
            self.expected_previous_event_hash,
        )
        if any(item is None for item in previous_fields) and not all(
            item is None for item in previous_fields
        ):
            raise ValueError("R7 family authorization previous head is incomplete")
        if self.expected_sequence == 1 and any(item is not None for item in previous_fields):
            raise ValueError("R7 family root authorization cannot bind a previous head")
        if self.expected_sequence > 1 and any(item is None for item in previous_fields):
            raise ValueError("R7 family continuation must bind the previous head")
        if self.expected_previous_event_id is not None:
            previous_version = self.expected_previous_event_version
            previous_hash = self.expected_previous_event_hash
            if previous_version is None or previous_hash is None:
                raise ValueError("R7 family authorization previous head is incomplete")
            require_token(
                self.expected_previous_event_id,
                "R7 family authorization previous event_id",
                maximum=192,
            )
            require_token(
                previous_version,
                "R7 family authorization previous event_version",
                maximum=192,
            )
            require_sha256(
                previous_hash,
                "R7 family authorization previous event_hash",
            )
        if self.owner != "research":
            raise ValueError("R7 family authorization owner must be research")
        for clock_label, clock_value in (
            ("issued_at", self.issued_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(clock_value, f"R7 family authorization {clock_label}")
        if not self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("R7 family authorization clocks are invalid")
        _require_reasons(self.reason_codes, "R7 family authorization")
        if not _strict_safety(self):
            raise ValueError("R7 family authorization must remain research-only")
        expected = _authorization_hash(self)
        try:
            current = object.__getattribute__(self, "content_hash")
        except AttributeError:
            object.__setattr__(self, "content_hash", expected)
        else:
            require_sha256(current, "R7 family authorization content_hash")
            if current != expected:
                raise ValueError("R7 family authorization content hash mismatch")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this owner instruction may create a new event."""

        _require_aware(as_of, "R7 family authorization as_of")
        return self.recorded_at <= as_of < self.valid_until


def _authorization_hash(value: R7FamilyLifecycleAuthorization) -> str:
    return hash_components(
        "r7-family-lifecycle-authorization.v1",
        value.authorization_id,
        value.authorization_version,
        value.family.content_hash,
        value.event_id,
        value.event_version,
        value.action.value,
        value.subject_ref.result_id,
        value.subject_ref.result_version,
        value.subject_ref.content_hash,
        value.subject_owner_attestation_hash,
        "" if value.rollback_target_ref is None else value.rollback_target_ref.result_id,
        "" if value.rollback_target_ref is None else value.rollback_target_ref.result_version,
        "" if value.rollback_target_ref is None else value.rollback_target_ref.content_hash,
        value.rollback_target_owner_attestation_hash or "",
        str(value.expected_sequence),
        value.expected_previous_event_id or "",
        value.expected_previous_event_version or "",
        value.expected_previous_event_hash or "",
        value.owner,
        _clock(value.issued_at),
        _clock(value.recorded_at),
        _clock(value.valid_until),
        *value.reason_codes,
        value.evidence_ref,
        *(_flag(item) for item in _safety_values(value)),
    )


@dataclass(frozen=True)
class R7FamilyLifecycleEvent:
    """One immutable family event with its exact owner and result evidence."""

    event_id: str
    event_version: str
    family: R7ResultFamilyIdentity
    action: R7FamilyLifecycleAction
    sequence: int
    subject_evidence: R7FamilyResultOwnerEvidence
    rollback_target_evidence: R7FamilyResultOwnerEvidence | None
    authorization: R7FamilyLifecycleAuthorization
    occurred_at: datetime
    recorded_at: datetime
    previous_event_hash: str | None
    research_only: bool = field(init=False, default=True)
    publishes_model_probability: bool = field(init=False, default=False)
    publishes_probability_current: bool = field(init=False, default=False)
    produces_decision: bool = field(init=False, default=False)
    executes_orders: bool = field(init=False, default=False)
    must_not_use_for_decision: bool = field(init=False, default=True)
    must_not_execute: bool = field(init=False, default=True)
    content_hash: str = field(init=False)

    @property
    def subject_ref(self) -> R7ResearchResultRef:
        """Return the exact result identity affected by this event."""

        return self.subject_evidence.result_ref

    @property
    def rollback_target_ref(self) -> R7ResearchResultRef | None:
        """Return the exact rollback target, if this is a rollback."""

        return (
            None
            if self.rollback_target_evidence is None
            else self.rollback_target_evidence.result_ref
        )

    def __post_init__(self) -> None:
        require_token(self.event_id, "R7 family event_id", maximum=192)
        require_token(self.event_version, "R7 family event_version", maximum=192)
        self.family.__post_init__()
        if type(self.action) is not R7FamilyLifecycleAction:
            raise TypeError("R7 family event action is invalid")
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("R7 family event sequence is invalid")
        if type(self.subject_evidence) is not R7FamilyResultOwnerEvidence:
            raise TypeError("R7 family event subject evidence is invalid")
        self.subject_evidence.validate_live()
        if self.rollback_target_evidence is not None:
            if type(self.rollback_target_evidence) is not R7FamilyResultOwnerEvidence:
                raise TypeError("R7 family event rollback target evidence is invalid")
            self.rollback_target_evidence.validate_live()
        if type(self.authorization) is not R7FamilyLifecycleAuthorization:
            raise TypeError("R7 family event authorization is invalid")
        self.authorization.__post_init__()
        if (
            self.family != self.authorization.family
            or self.subject_evidence.family != self.family
            or self.subject_ref != self.authorization.subject_ref
            or self.subject_evidence.local_lifecycle_attestation.content_hash
            != self.authorization.subject_owner_attestation_hash
            or self.rollback_target_ref != self.authorization.rollback_target_ref
            or (
                None
                if self.rollback_target_evidence is None
                else self.rollback_target_evidence.local_lifecycle_attestation.content_hash
            )
            != self.authorization.rollback_target_owner_attestation_hash
            or self.event_id != self.authorization.event_id
            or self.event_version != self.authorization.event_version
            or self.action is not self.authorization.action
            or self.sequence != self.authorization.expected_sequence
            or self.previous_event_hash != self.authorization.expected_previous_event_hash
        ):
            raise ValueError("R7 family event differs from its exact authorization")
        if (
            self.rollback_target_evidence is not None
            and self.rollback_target_evidence.family != self.family
        ):
            raise ValueError("R7 family rollback target crosses families")
        _require_aware(self.occurred_at, "R7 family event occurred_at")
        _require_aware(self.recorded_at, "R7 family event recorded_at")
        if not self.authorization.recorded_at <= self.occurred_at <= self.recorded_at:
            raise ValueError("R7 family event clocks are invalid")
        if self.previous_event_hash is not None:
            require_sha256(self.previous_event_hash, "R7 family previous_event_hash")
        if not _strict_safety(self):
            raise ValueError("R7 family event must remain research-only")
        expected = _event_hash(self)
        try:
            current = object.__getattribute__(self, "content_hash")
        except AttributeError:
            object.__setattr__(self, "content_hash", expected)
        else:
            require_sha256(current, "R7 family event content_hash")
            if current != expected:
                raise ValueError("R7 family event content hash mismatch")

    def validate_live(self) -> None:
        """Recheck nested owner evidence, authorization, clocks, and seal."""

        self.__post_init__()


def _event_hash(value: R7FamilyLifecycleEvent) -> str:
    return hash_components(
        "r7-family-lifecycle-event.v1",
        value.event_id,
        value.event_version,
        value.family.content_hash,
        value.action.value,
        str(value.sequence),
        value.subject_evidence.content_hash,
        (
            ""
            if value.rollback_target_evidence is None
            else value.rollback_target_evidence.content_hash
        ),
        value.authorization.content_hash,
        _clock(value.occurred_at),
        _clock(value.recorded_at),
        value.previous_event_hash or "",
        *(_flag(item) for item in _safety_values(value)),
    )


@dataclass(frozen=True)
class R7FamilyLifecycleSnapshot:
    """PIT family state derived from one complete immutable event stream."""

    family: R7ResultFamilyIdentity
    status: R7FamilyLifecycleStatus
    approved_stack: tuple[R7ResearchResultRef, ...]
    active_result_ref: R7ResearchResultRef | None
    sequence: int
    head_event_hash: str
    evaluated_at: datetime
    research_only: bool = field(init=False, default=True)
    publishes_model_probability: bool = field(init=False, default=False)
    publishes_probability_current: bool = field(init=False, default=False)
    produces_decision: bool = field(init=False, default=False)
    executes_orders: bool = field(init=False, default=False)
    must_not_use_for_decision: bool = field(init=False, default=True)
    must_not_execute: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        self.family.__post_init__()
        if type(self.status) is not R7FamilyLifecycleStatus:
            raise TypeError("R7 family snapshot status is invalid")
        if type(self.approved_stack) is not tuple:
            raise TypeError("R7 family approved stack must be a tuple")
        for item in self.approved_stack:
            item.__post_init__()
        if len(self.approved_stack) != len(set(self.approved_stack)):
            raise ValueError("R7 family approved stack contains duplicates")
        if self.active_result_ref is not None:
            self.active_result_ref.__post_init__()
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("R7 family snapshot sequence is invalid")
        require_sha256(self.head_event_hash, "R7 family snapshot head_event_hash")
        _require_aware(self.evaluated_at, "R7 family snapshot evaluated_at")
        if not _strict_safety(self):
            raise ValueError("R7 family snapshot must remain research-only")


def create_r7_family_lifecycle_event(
    *,
    previous_events: tuple[R7FamilyLifecycleEvent, ...],
    authorization: R7FamilyLifecycleAuthorization,
    subject_evidence: R7FamilyResultOwnerEvidence,
    rollback_target_evidence: R7FamilyResultOwnerEvidence | None,
    occurred_at: datetime,
    recorded_at: datetime,
) -> R7FamilyLifecycleEvent:
    """Replay the full family stream and create only the next authorized event."""

    if type(previous_events) is not tuple:
        raise TypeError("R7 family previous events must be a tuple")
    if type(authorization) is not R7FamilyLifecycleAuthorization:
        raise TypeError("R7 family authorization type is invalid")
    authorization.__post_init__()
    if type(subject_evidence) is not R7FamilyResultOwnerEvidence:
        raise TypeError("R7 family subject evidence type is invalid")
    subject_evidence.validate_live()
    if rollback_target_evidence is not None:
        if type(rollback_target_evidence) is not R7FamilyResultOwnerEvidence:
            raise TypeError("R7 family rollback target evidence type is invalid")
        rollback_target_evidence.validate_live()
    _require_aware(occurred_at, "R7 family event occurred_at")
    _require_aware(recorded_at, "R7 family event recorded_at")
    if not authorization.is_active_at(occurred_at) or recorded_at < occurred_at:
        raise ValueError("R7 family authorization is inactive at event occurrence")
    stack: list[R7ResearchResultRef]
    if previous_events:
        stack, _, previous = _replay_chain(previous_events)
        expected_head = (
            previous.event_id,
            previous.event_version,
            previous.content_hash,
        )
        actual_head = (
            authorization.expected_previous_event_id,
            authorization.expected_previous_event_version,
            authorization.expected_previous_event_hash,
        )
        if actual_head != expected_head:
            raise ValueError("R7 family authorization previous head mismatch")
        if not (
            authorization.issued_at > previous.recorded_at
            and authorization.recorded_at > previous.recorded_at
            and occurred_at > previous.recorded_at
            and recorded_at >= previous.recorded_at
        ):
            raise ValueError("R7 family authorization must strictly follow the previous head")
    else:
        stack = []
        if authorization.expected_previous_event_hash is not None:
            raise ValueError("R7 family root cannot bind a previous head")
        if authorization.action is not R7FamilyLifecycleAction.PROMOTE:
            raise ValueError("R7 family lifecycle root must promote")
    if authorization.expected_sequence != len(previous_events) + 1:
        raise ValueError("R7 family authorization sequence is stale")
    if subject_evidence.family != authorization.family:
        raise ValueError("R7 family subject evidence crosses families")
    if subject_evidence.result_ref != authorization.subject_ref:
        raise ValueError("R7 family subject differs from authorization")
    if (
        subject_evidence.local_lifecycle_attestation.content_hash
        != authorization.subject_owner_attestation_hash
    ):
        raise ValueError("R7 family subject owner attestation differs")
    if subject_evidence.evaluated_at > authorization.issued_at:
        raise ValueError("R7 family authorization predates its subject evidence")
    target_ref = None if rollback_target_evidence is None else rollback_target_evidence.result_ref
    if target_ref != authorization.rollback_target_ref:
        raise ValueError("R7 family rollback target differs from authorization")
    target_attestation_hash = (
        None
        if rollback_target_evidence is None
        else rollback_target_evidence.local_lifecycle_attestation.content_hash
    )
    if target_attestation_hash != authorization.rollback_target_owner_attestation_hash:
        raise ValueError("R7 family rollback target owner attestation differs")
    if (
        rollback_target_evidence is not None
        and rollback_target_evidence.evaluated_at > authorization.issued_at
    ):
        raise ValueError("R7 family authorization predates rollback target evidence")
    if authorization.action is R7FamilyLifecycleAction.PROMOTE:
        if not subject_evidence.is_activatable_at(occurred_at):
            raise ValueError("R7 family result cannot activate from retired or expired evidence")
        if subject_evidence.result_ref in stack:
            raise ValueError("R7 family cannot repromote an approved stack result")
    elif authorization.action is R7FamilyLifecycleAction.RETIRE:
        if not stack or stack[-1] != subject_evidence.result_ref:
            raise ValueError("R7 family retirement must clean up the active result")
    elif len(stack) < 2 or stack[-1] != subject_evidence.result_ref or target_ref != stack[-2]:
        raise ValueError("R7 family rollback target must be exactly stack[-2]")
    elif rollback_target_evidence is None or not rollback_target_evidence.is_activatable_at(
        occurred_at
    ):
        raise ValueError("R7 family rollback target cannot activate")
    event = R7FamilyLifecycleEvent(
        event_id=authorization.event_id,
        event_version=authorization.event_version,
        family=authorization.family,
        action=authorization.action,
        sequence=authorization.expected_sequence,
        subject_evidence=subject_evidence,
        rollback_target_evidence=rollback_target_evidence,
        authorization=authorization,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        previous_event_hash=authorization.expected_previous_event_hash,
    )
    _replay_chain((*previous_events, event))
    return event


def derive_r7_family_lifecycle_state(
    events: tuple[R7FamilyLifecycleEvent, ...],
    *,
    evaluated_at: datetime,
) -> R7FamilyLifecycleSnapshot:
    """Replay one complete PIT stream and derive its non-operational state."""

    _require_aware(evaluated_at, "R7 family lifecycle evaluated_at")
    if type(events) is not tuple or not events:
        raise ValueError("R7 family lifecycle stream cannot be empty")
    if any(event.recorded_at > evaluated_at for event in events):
        raise ValueError("R7 family lifecycle stream contains future evidence")
    stack, evidence_stack, latest = _replay_chain(events)
    active: R7ResearchResultRef | None
    if not stack:
        status = R7FamilyLifecycleStatus.RETIRED
        active = None
    elif not evidence_stack[-1].is_activatable_at(evaluated_at):
        status = R7FamilyLifecycleStatus.EXPIRED
        active = None
    else:
        status = (
            R7FamilyLifecycleStatus.ROLLED_BACK
            if latest.action is R7FamilyLifecycleAction.ROLLBACK
            else R7FamilyLifecycleStatus.PROMOTED
        )
        active = stack[-1]
    return R7FamilyLifecycleSnapshot(
        family=latest.family,
        status=status,
        approved_stack=tuple(stack),
        active_result_ref=active,
        sequence=latest.sequence,
        head_event_hash=latest.content_hash,
        evaluated_at=evaluated_at,
    )


def _replay_chain(
    events: tuple[R7FamilyLifecycleEvent, ...],
) -> tuple[
    list[R7ResearchResultRef],
    list[R7FamilyResultOwnerEvidence],
    R7FamilyLifecycleEvent,
]:
    if type(events) is not tuple or not events:
        raise ValueError("R7 family lifecycle chain cannot be empty")
    family = events[0].family
    stack: list[R7ResearchResultRef] = []
    evidence_stack: list[R7FamilyResultOwnerEvidence] = []
    previous: R7FamilyLifecycleEvent | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if type(event) is not R7FamilyLifecycleEvent:
            raise TypeError("R7 family lifecycle event type is invalid")
        event.validate_live()
        if event.family != family:
            raise ValueError("R7 family lifecycle chain crosses families")
        if event.sequence != expected_sequence:
            raise ValueError("R7 family lifecycle sequence is discontinuous")
        if previous is None:
            if event.previous_event_hash is not None:
                raise ValueError("R7 family root has a previous hash")
            if event.action is not R7FamilyLifecycleAction.PROMOTE:
                raise ValueError("R7 family lifecycle root must promote")
        else:
            if event.previous_event_hash != previous.content_hash:
                raise ValueError("R7 family lifecycle hash chain is discontinuous")
            if (
                event.occurred_at <= previous.recorded_at
                or event.recorded_at < previous.recorded_at
                or event.authorization.issued_at <= previous.recorded_at
                or event.authorization.recorded_at <= previous.recorded_at
            ):
                raise ValueError("R7 family lifecycle clocks are non-monotonic")
            expected_head = (
                previous.event_id,
                previous.event_version,
                previous.content_hash,
            )
            actual_head = (
                event.authorization.expected_previous_event_id,
                event.authorization.expected_previous_event_version,
                event.authorization.expected_previous_event_hash,
            )
            if actual_head != expected_head:
                raise ValueError("R7 family lifecycle authorization head is stale")
        subject_ref = event.subject_ref
        if event.action is R7FamilyLifecycleAction.PROMOTE:
            if not event.subject_evidence.is_activatable_at(event.occurred_at):
                raise ValueError("R7 family result cannot activate")
            if subject_ref in stack:
                raise ValueError("R7 family duplicates an approved stack result")
            stack.append(subject_ref)
            evidence_stack.append(event.subject_evidence)
        elif event.action is R7FamilyLifecycleAction.RETIRE:
            if not stack or stack[-1] != subject_ref:
                raise ValueError("R7 family retirement does not target active result")
            stack.clear()
            evidence_stack.clear()
        else:
            target = event.rollback_target_ref
            if len(stack) < 2 or stack[-1] != subject_ref or target != stack[-2]:
                raise ValueError("R7 family rollback does not target stack[-2]")
            if (
                event.rollback_target_evidence is None
                or not event.rollback_target_evidence.is_activatable_at(event.occurred_at)
            ):
                raise ValueError("R7 family rollback target cannot activate")
            stack.pop()
            evidence_stack.pop()
            evidence_stack[-1] = event.rollback_target_evidence
        previous = event
    assert previous is not None
    return stack, evidence_stack, previous


def _result_evidence_valid_until(result: PersistedR7ResearchResult) -> datetime:
    candidates: list[datetime] = []
    observations = result.evidence_graph.forecast_observations
    if not observations or any(item.outcome_evidence_valid_until is None for item in observations):
        return result.recorded_at
    candidates.extend(
        item.outcome_evidence_valid_until
        for item in observations
        if item.outcome_evidence_valid_until is not None
    )
    analogy = result.evidence_graph.historical_analogy
    path = result.evidence_graph.path_study
    if analogy is None or path is None:
        return result.recorded_at
    candidates.extend((analogy.valid_until, path.valid_until))
    return min(candidates)


def _validate_result_live(result: PersistedR7ResearchResult) -> None:
    if type(result) is not PersistedR7ResearchResult:
        raise TypeError("R7 family result owner object is invalid")
    for observation in result.evidence_graph.forecast_observations:
        if type(observation) is not ForecastLedgerOutcomeObservation:
            raise TypeError("R7 family forecast observation type is invalid")
        observation.__post_init__()
    result.evidence_graph.__post_init__()
    result.input_receipt.__post_init__()
    result.calibration.subjective.__post_init__()
    result.calibration.model_inferred.__post_init__()
    result.calibration.__post_init__()
    result.historical_analogy.__post_init__()
    result.path_research.__post_init__()
    result.__post_init__()


def _require_reasons(values: tuple[str, ...], label: str) -> None:
    if (
        type(values) is not tuple
        or not values
        or values != tuple(sorted(values))
        or len(values) != len(set(values))
    ):
        raise ValueError(f"{label} reasons must be unique and canonical")
    for value in values:
        require_token(value, f"{label} reason", maximum=96)


def _safety_values(
    value: (
        R7FamilyResultOwnerEvidence
        | R7FamilyLifecycleAuthorization
        | R7FamilyLifecycleEvent
        | R7FamilyLifecycleSnapshot
    ),
) -> tuple[bool, ...]:
    return (
        value.research_only,
        value.publishes_model_probability,
        value.publishes_probability_current,
        value.produces_decision,
        value.executes_orders,
        value.must_not_use_for_decision,
        value.must_not_execute,
    )


def _strict_safety(
    value: (
        R7FamilyResultOwnerEvidence
        | R7FamilyLifecycleAuthorization
        | R7FamilyLifecycleEvent
        | R7FamilyLifecycleSnapshot
    ),
) -> bool:
    return _safety_values(value) == (True, False, False, False, False, True, True)


__all__ = [
    "R7FamilyLifecycleAction",
    "R7FamilyLifecycleAuthorization",
    "R7FamilyLifecycleEvent",
    "R7FamilyLifecycleSnapshot",
    "R7FamilyLifecycleStatus",
    "R7FamilyResultOwnerEvidence",
    "R7LocalLifecycleStreamAttestation",
    "R7ResultFamilyIdentity",
    "create_r7_family_lifecycle_event",
    "derive_r7_family_lifecycle_state",
]
