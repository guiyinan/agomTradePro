"""Research-only lifecycle contracts for persisted R6 qualification evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from apps.research.domain.state_model_qualification_contracts import _canonical_hash


def _require_token(value: str, field_name: str, *, maximum: int = 192) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a bounded non-blank token")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_hash(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class R6QualificationLifecycleAction(str, Enum):
    """Manual Research-only lifecycle actions."""

    PROMOTE = "promote"
    RETIRE = "retire"


@dataclass(frozen=True)
class R6QualificationRef:
    """Content-bound identity of one persisted qualification assessment."""

    assessment_id: str
    assessment_hash: str

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "R6QualificationRef.assessment_id")
        _require_hash(self.assessment_hash, "R6QualificationRef.assessment_hash")


@dataclass(frozen=True, init=False)
class R6QualificationPromotionAuthorization:
    """Owner-authorized lifecycle transition; never an execution permission."""

    authorization_id: str
    authorization_version: str
    qualification_ref: R6QualificationRef
    event_id: str
    event_version: str
    action: R6QualificationLifecycleAction
    expected_sequence: int
    owner: str
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    reason_codes: tuple[str, ...]
    evidence_ref: str
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        authorization_id: str,
        authorization_version: str,
        qualification_ref: R6QualificationRef,
        event_id: str,
        event_version: str,
        action: R6QualificationLifecycleAction,
        expected_sequence: int,
        owner: str,
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        reason_codes: tuple[str, ...],
        evidence_ref: str,
        research_only: bool = True,
        must_not_use_for_decision: bool = True,
        must_not_replace_regime: bool = True,
    ) -> None:
        values = {
            "authorization_id": authorization_id,
            "authorization_version": authorization_version,
            "qualification_ref": qualification_ref,
            "event_id": event_id,
            "event_version": event_version,
            "action": action,
            "expected_sequence": expected_sequence,
            "owner": owner,
            "issued_at": issued_at,
            "recorded_at": recorded_at,
            "valid_until": valid_until,
            "reason_codes": reason_codes,
            "evidence_ref": evidence_ref,
            "research_only": research_only,
            "must_not_use_for_decision": must_not_use_for_decision,
            "must_not_replace_regime": must_not_replace_regime,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        self.__post_init__()

    def __post_init__(self) -> None:
        _require_token(self.authorization_id, "R6QualificationAuthorization.authorization_id")
        _require_token(
            self.authorization_version,
            "R6QualificationAuthorization.authorization_version",
        )
        _require_token(self.event_id, "R6QualificationAuthorization.event_id")
        _require_token(self.event_version, "R6QualificationAuthorization.event_version")
        _require_token(self.owner, "R6QualificationAuthorization.owner")
        if self.owner != "research":
            raise ValueError("R6 qualification authorization owner must be research")
        if not isinstance(self.action, R6QualificationLifecycleAction):
            raise ValueError("R6 qualification authorization action is invalid")
        if isinstance(self.expected_sequence, bool) or self.expected_sequence < 1:
            raise ValueError("R6 qualification authorization sequence is invalid")
        for field_name in ("issued_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), f"R6QualificationAuthorization.{field_name}")
        if not self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("R6 qualification authorization clocks are invalid")
        if not self.reason_codes or len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("R6 qualification authorization reasons must be unique")
        for reason in self.reason_codes:
            _require_token(reason, "R6QualificationAuthorization.reason_code", maximum=96)
        _require_token(self.evidence_ref, "R6QualificationAuthorization.evidence_ref", maximum=300)
        if not (
            self.research_only is True
            and self.must_not_use_for_decision is True
            and self.must_not_replace_regime is True
        ):
            raise ValueError("R6 qualification lifecycle must remain research-only")
        _require_hash(self.content_hash, "R6QualificationAuthorization.content_hash")
        if self.content_hash != self.calculated_content_hash:
            raise ValueError("R6 qualification authorization content hash mismatch")

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical authorization seal."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the manual authorization is valid at ``as_of``."""

        _require_aware(as_of, "R6 qualification authorization as_of")
        return self.issued_at <= as_of < self.valid_until


@dataclass(frozen=True, init=False)
class R6QualificationLifecycleEvent:
    """Immutable scope-local qualification lifecycle event."""

    event_id: str
    event_version: str
    qualification_ref: R6QualificationRef
    authorization_id: str
    authorization_version: str
    authorization_hash: str
    action: R6QualificationLifecycleAction
    sequence: int
    occurred_at: datetime
    recorded_at: datetime
    previous_event_hash: str | None
    reason_codes: tuple[str, ...]
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        event_id: str,
        event_version: str,
        qualification_ref: R6QualificationRef,
        authorization_id: str,
        authorization_version: str,
        authorization_hash: str,
        action: R6QualificationLifecycleAction,
        sequence: int,
        occurred_at: datetime,
        recorded_at: datetime,
        previous_event_hash: str | None,
        reason_codes: tuple[str, ...],
        research_only: bool = True,
        must_not_use_for_decision: bool = True,
        must_not_replace_regime: bool = True,
    ) -> None:
        values = {
            "event_id": event_id,
            "event_version": event_version,
            "qualification_ref": qualification_ref,
            "authorization_id": authorization_id,
            "authorization_version": authorization_version,
            "authorization_hash": authorization_hash,
            "action": action,
            "sequence": sequence,
            "occurred_at": occurred_at,
            "recorded_at": recorded_at,
            "previous_event_hash": previous_event_hash,
            "reason_codes": reason_codes,
            "research_only": research_only,
            "must_not_use_for_decision": must_not_use_for_decision,
            "must_not_replace_regime": must_not_replace_regime,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        self.__post_init__()

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "event_version",
            "authorization_id",
            "authorization_version",
        ):
            _require_token(getattr(self, field_name), f"R6QualificationEvent.{field_name}")
        _require_hash(self.authorization_hash, "R6QualificationEvent.authorization_hash")
        if not isinstance(self.action, R6QualificationLifecycleAction):
            raise ValueError("R6 qualification event action is invalid")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("R6 qualification event sequence is invalid")
        _require_aware(self.occurred_at, "R6QualificationEvent.occurred_at")
        _require_aware(self.recorded_at, "R6QualificationEvent.recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("R6 qualification event recorded_at cannot precede occurrence")
        if self.previous_event_hash is not None:
            _require_hash(self.previous_event_hash, "R6QualificationEvent.previous_event_hash")
        if not self.reason_codes or len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("R6 qualification event reasons must be unique")
        for reason in self.reason_codes:
            _require_token(reason, "R6QualificationEvent.reason_code", maximum=96)
        if not (
            self.research_only is True
            and self.must_not_use_for_decision is True
            and self.must_not_replace_regime is True
        ):
            raise ValueError("R6 qualification events must remain research-only")
        _require_hash(self.content_hash, "R6QualificationEvent.content_hash")
        if self.content_hash != self.calculated_content_hash:
            raise ValueError("R6 qualification event content hash mismatch")

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical event seal."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))


@dataclass(frozen=True)
class R6QualificationLifecycleState:
    """Derived active state for one qualification stream."""

    qualification_ref: R6QualificationRef
    active: bool
    sequence: int
    head_event_hash: str | None


def create_r6_qualification_lifecycle_event(
    *,
    authorization: R6QualificationPromotionAuthorization,
    sequence: int,
    occurred_at: datetime,
    recorded_at: datetime,
    previous_event_hash: str | None,
) -> R6QualificationLifecycleEvent:
    """Build one event from exact owner authorization and chain position."""

    if authorization.expected_sequence != sequence:
        raise ValueError("R6 qualification authorization sequence differs")
    if not authorization.is_active_at(occurred_at):
        raise ValueError("R6 qualification authorization is inactive at occurrence")
    event = R6QualificationLifecycleEvent(
        event_id=authorization.event_id,
        event_version=authorization.event_version,
        qualification_ref=authorization.qualification_ref,
        authorization_id=authorization.authorization_id,
        authorization_version=authorization.authorization_version,
        authorization_hash=authorization.content_hash,
        action=authorization.action,
        sequence=sequence,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        previous_event_hash=previous_event_hash,
        reason_codes=authorization.reason_codes,
    )
    return event


def derive_r6_qualification_lifecycle_state(
    events: tuple[R6QualificationLifecycleEvent, ...],
    *,
    evaluated_at: datetime,
) -> R6QualificationLifecycleState:
    """Replay a complete prefix and reject forks, gaps, and invalid transitions."""

    _require_aware(evaluated_at, "R6 qualification lifecycle evaluated_at")
    if not events:
        raise ValueError("R6 qualification lifecycle has no events")
    ordered = tuple(sorted(events, key=lambda item: item.sequence))
    ref = ordered[0].qualification_ref
    active = False
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(ordered, start=1):
        if event.qualification_ref != ref:
            raise ValueError("R6 qualification lifecycle crosses assessment identities")
        if event.sequence != expected_sequence:
            raise ValueError("R6 qualification lifecycle sequence is discontinuous")
        if event.recorded_at > evaluated_at:
            raise ValueError("R6 qualification lifecycle contains future evidence")
        if event.previous_event_hash != previous_hash:
            raise ValueError("R6 qualification lifecycle hash chain is broken")
        if expected_sequence == 1 and event.action is not R6QualificationLifecycleAction.PROMOTE:
            raise ValueError("R6 qualification lifecycle root must promote")
        if event.action is R6QualificationLifecycleAction.PROMOTE:
            if active:
                raise ValueError("R6 qualification lifecycle promotes an already active item")
            active = True
        elif not active:
            raise ValueError("R6 qualification lifecycle retires an inactive item")
        else:
            active = False
        previous_hash = event.content_hash
    return R6QualificationLifecycleState(
        qualification_ref=ref,
        active=active,
        sequence=len(ordered),
        head_event_hash=previous_hash,
    )


__all__ = [
    "R6QualificationLifecycleAction",
    "R6QualificationLifecycleEvent",
    "R6QualificationLifecycleState",
    "R6QualificationPromotionAuthorization",
    "R6QualificationRef",
    "create_r6_qualification_lifecycle_event",
    "derive_r6_qualification_lifecycle_state",
]
