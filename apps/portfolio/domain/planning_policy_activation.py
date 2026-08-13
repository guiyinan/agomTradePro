"""Two-person activation contract for exact Portfolio planning policies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .planning_policy_definition import PlanningPolicyDefinition

PLANNING_POLICY_ACTIVATION_OWNER = "portfolio"
PLANNING_POLICY_ACTIVATION_CAPABILITY = "planning_policy_activation"
PLANNING_POLICY_ACTIVATION_SCHEMA = "portfolio-planning-policy-activation.v1"
PLANNING_POLICY_ACTIVATION_PERMISSION = "policy_configuration_only"


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _require_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_optional_hash(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_hash(value, field_name)


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PlanningPolicyActivationActor:
    """Server-authenticated human staff identity."""

    actor_id: str
    user_id: int
    role: str
    kind: str = "human"
    is_staff: bool = True

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        _require_token(self.role, "role")
        if self.kind != "human" or self.is_staff is not True:
            raise ValueError("planning policy activation actor must be human staff")

    def to_payload(self) -> dict[str, object]:
        """Return the sealed server actor identity."""

        return {
            "actor_id": self.actor_id,
            "user_id": self.user_id,
            "role": self.role,
            "kind": self.kind,
            "is_staff": self.is_staff,
        }


@dataclass(frozen=True, slots=True)
class PlanningPolicyActivationSubject:
    """Immutable request to activate one exact policy definition."""

    subject_id: str
    subject_version: str
    policy_id: str
    policy_version: str
    definition_identity_hash: str
    definition_content_hash: str
    definition_recorded_at: datetime
    requested_by: PlanningPolicyActivationActor
    requested_at: datetime
    valid_until: datetime
    supersedes_activation_hash: str | None = None
    content_hash: str = ""

    @classmethod
    def create(
        cls,
        *,
        subject_id: str,
        subject_version: str,
        definition: PlanningPolicyDefinition,
        requested_by: PlanningPolicyActivationActor,
        requested_at: datetime,
        supersedes_activation_hash: str | None,
    ) -> PlanningPolicyActivationSubject:
        """Seal a request for one exact, currently knowable definition."""

        if type(definition) is not PlanningPolicyDefinition:
            raise TypeError("definition must be an exact PlanningPolicyDefinition")
        PlanningPolicyDefinition.__post_init__(definition)
        _require_aware(requested_at, "requested_at")
        if not definition.is_knowable_at(requested_at):
            raise ValueError("planning policy definition is not active at request time")
        return cls(
            subject_id=subject_id,
            subject_version=subject_version,
            policy_id=definition.policy_id,
            policy_version=definition.policy_version,
            definition_identity_hash=definition.identity_hash,
            definition_content_hash=definition.content_hash,
            definition_recorded_at=definition.recorded_at,
            requested_by=requested_by,
            requested_at=requested_at,
            valid_until=definition.valid_until,
            supersedes_activation_hash=supersedes_activation_hash,
        )

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "policy_id",
            "policy_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.definition_identity_hash, "definition_identity_hash")
        _require_hash(self.definition_content_hash, "definition_content_hash")
        _require_optional_hash(self.supersedes_activation_hash, "supersedes_activation_hash")
        _require_aware(self.definition_recorded_at, "definition_recorded_at")
        if type(self.requested_by) is not PlanningPolicyActivationActor:
            raise TypeError("requested_by must be an exact activation actor")
        PlanningPolicyActivationActor.__post_init__(self.requested_by)
        _require_aware(self.requested_at, "requested_at")
        _require_aware(self.valid_until, "valid_until")
        if not self.definition_recorded_at <= self.requested_at < self.valid_until:
            raise ValueError("activation subject validity window is invalid")
        expected = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected:
                raise ValueError("activation subject content_hash is invalid")

    def is_valid_at(self, as_of: datetime) -> bool:
        """Return whether the subject is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.requested_at <= as_of < self.valid_until

    def _content_payload(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "definition_identity_hash": self.definition_identity_hash,
            "definition_content_hash": self.definition_content_hash,
            "definition_recorded_at": _utc_text(self.definition_recorded_at),
            "requested_by": self.requested_by.to_payload(),
            "requested_at": _utc_text(self.requested_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_activation_hash": self.supersedes_activation_hash,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the sealed activation request."""

        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class PlanningPolicyActivation:
    """Two-person activation of one exact definition; never execution authority."""

    activation_id: str
    activation_version: str
    subject: PlanningPolicyActivationSubject
    approved_by: PlanningPolicyActivationActor
    issued_at: datetime
    valid_until: datetime
    content_hash: str = ""
    owner: str = PLANNING_POLICY_ACTIVATION_OWNER
    capability: str = PLANNING_POLICY_ACTIVATION_CAPABILITY
    schema: str = PLANNING_POLICY_ACTIVATION_SCHEMA
    permission: str = PLANNING_POLICY_ACTIVATION_PERMISSION

    @classmethod
    def create(
        cls,
        *,
        activation_id: str,
        activation_version: str,
        subject: PlanningPolicyActivationSubject,
        approved_by: PlanningPolicyActivationActor,
        issued_at: datetime,
    ) -> PlanningPolicyActivation:
        """Create an activation after exact two-person checks."""

        if type(subject) is not PlanningPolicyActivationSubject:
            raise TypeError("subject must be an exact activation subject")
        return cls(
            activation_id=activation_id,
            activation_version=activation_version,
            subject=subject,
            approved_by=approved_by,
            issued_at=issued_at,
            valid_until=subject.valid_until,
        )

    def __post_init__(self) -> None:
        _require_token(self.activation_id, "activation_id")
        _require_token(self.activation_version, "activation_version")
        if type(self.subject) is not PlanningPolicyActivationSubject:
            raise TypeError("subject must be an exact activation subject")
        PlanningPolicyActivationSubject.__post_init__(self.subject)
        if type(self.approved_by) is not PlanningPolicyActivationActor:
            raise TypeError("approved_by must be an exact activation actor")
        PlanningPolicyActivationActor.__post_init__(self.approved_by)
        if (
            self.approved_by.actor_id == self.subject.requested_by.actor_id
            or self.approved_by.user_id == self.subject.requested_by.user_id
        ):
            raise ValueError("planning policy activation forbids self approval")
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until != self.subject.valid_until:
            raise ValueError("activation validity must equal its subject validity")
        if not self.subject.requested_at <= self.issued_at < self.valid_until:
            raise ValueError("activation issued outside its subject validity window")
        if (
            self.owner != PLANNING_POLICY_ACTIVATION_OWNER
            or self.capability != PLANNING_POLICY_ACTIVATION_CAPABILITY
            or self.schema != PLANNING_POLICY_ACTIVATION_SCHEMA
            or self.permission != PLANNING_POLICY_ACTIVATION_PERMISSION
        ):
            raise ValueError("planning policy activation authority is fixed")
        expected = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected:
                raise ValueError("planning policy activation content_hash is invalid")

    @property
    def must_not_execute(self) -> bool:
        """Remain true because policy activation is not trade authorization."""

        return True

    def is_valid_at(self, as_of: datetime) -> bool:
        """Return whether this immutable activation is effective at a cutoff."""

        _require_aware(as_of, "as_of")
        return self.issued_at <= as_of < self.valid_until

    def _content_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "capability": self.capability,
            "schema": self.schema,
            "activation_id": self.activation_id,
            "activation_version": self.activation_version,
            "subject": self.subject.to_payload(),
            "approved_by": self.approved_by.to_payload(),
            "issued_at": _utc_text(self.issued_at),
            "valid_until": _utc_text(self.valid_until),
            "permission": self.permission,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the activation with its explicit non-execution marker."""

        return {
            **self._content_payload(),
            "content_hash": self.content_hash,
            "must_not_execute": True,
        }


def validate_planning_policy_activation_successor(
    previous: PlanningPolicyActivation,
    successor: PlanningPolicyActivation,
) -> None:
    """Validate one adjacent activation-chain transition."""

    if (
        type(previous) is not PlanningPolicyActivation
        or type(successor) is not PlanningPolicyActivation
    ):
        raise TypeError("activation chain values must be exact activations")
    PlanningPolicyActivation.__post_init__(previous)
    PlanningPolicyActivation.__post_init__(successor)
    if (
        previous.subject.policy_id != successor.subject.policy_id
        or previous.owner != successor.owner
        or previous.capability != successor.capability
    ):
        raise ValueError("activation successor changes its logical policy")
    if successor.subject.supersedes_activation_hash != previous.content_hash:
        raise ValueError("activation successor predecessor hash is invalid")
    if successor.issued_at <= previous.issued_at:
        raise ValueError("activation successor clock must advance")


__all__ = [
    "PLANNING_POLICY_ACTIVATION_CAPABILITY",
    "PLANNING_POLICY_ACTIVATION_OWNER",
    "PLANNING_POLICY_ACTIVATION_PERMISSION",
    "PLANNING_POLICY_ACTIVATION_SCHEMA",
    "PlanningPolicyActivation",
    "PlanningPolicyActivationActor",
    "PlanningPolicyActivationSubject",
    "validate_planning_policy_activation_successor",
]
