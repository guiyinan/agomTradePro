"""Strict canonical codecs for Portfolio planning-policy activation ledgers."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.portfolio.domain.planning_policy_activation import (
    PlanningPolicyActivation,
    PlanningPolicyActivationActor,
    PlanningPolicyActivationSubject,
)


class PlanningPolicyActivationCodecError(ValueError):
    """A stored activation subject or record is malformed or non-canonical."""


def encode_planning_policy_activation_subject(
    value: PlanningPolicyActivationSubject,
) -> dict[str, object]:
    """Encode one complete immutable activation subject."""

    return value.to_payload()


def decode_planning_policy_activation_subject(
    payload: object,
) -> PlanningPolicyActivationSubject:
    """Restore and revalidate one exact canonical activation subject."""

    data = _mapping(
        payload,
        {
            "subject_id",
            "subject_version",
            "policy_id",
            "policy_version",
            "definition_identity_hash",
            "definition_content_hash",
            "definition_recorded_at",
            "requested_by",
            "requested_at",
            "valid_until",
            "supersedes_activation_hash",
            "content_hash",
        },
    )
    try:
        value = PlanningPolicyActivationSubject(
            subject_id=_string(data["subject_id"]),
            subject_version=_string(data["subject_version"]),
            policy_id=_string(data["policy_id"]),
            policy_version=_string(data["policy_version"]),
            definition_identity_hash=_string(data["definition_identity_hash"]),
            definition_content_hash=_string(data["definition_content_hash"]),
            definition_recorded_at=_datetime(data["definition_recorded_at"]),
            requested_by=_actor(data["requested_by"]),
            requested_at=_datetime(data["requested_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_activation_hash=_optional_string(data["supersedes_activation_hash"]),
            content_hash=_string(data["content_hash"]),
        )
    except (PlanningPolicyActivationCodecError, TypeError, ValueError) as error:
        raise PlanningPolicyActivationCodecError(
            "planning-policy activation subject is invalid"
        ) from error
    if payload != encode_planning_policy_activation_subject(value):
        raise PlanningPolicyActivationCodecError(
            "planning-policy activation subject is non-canonical"
        )
    return value


def encode_planning_policy_activation(
    value: PlanningPolicyActivation,
) -> dict[str, object]:
    """Encode one immutable activation without its derived execution marker."""

    return {key: item for key, item in value.to_payload().items() if key != "must_not_execute"}


def decode_planning_policy_activation(payload: object) -> PlanningPolicyActivation:
    """Restore and revalidate one exact canonical activation record."""

    data = _mapping(
        payload,
        {
            "owner",
            "capability",
            "schema",
            "activation_id",
            "activation_version",
            "subject",
            "approved_by",
            "issued_at",
            "valid_until",
            "permission",
            "content_hash",
        },
    )
    try:
        value = PlanningPolicyActivation(
            activation_id=_string(data["activation_id"]),
            activation_version=_string(data["activation_version"]),
            subject=decode_planning_policy_activation_subject(data["subject"]),
            approved_by=_actor(data["approved_by"]),
            issued_at=_datetime(data["issued_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            capability=_string(data["capability"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
        )
    except (PlanningPolicyActivationCodecError, TypeError, ValueError) as error:
        raise PlanningPolicyActivationCodecError("planning-policy activation is invalid") from error
    if payload != encode_planning_policy_activation(value):
        raise PlanningPolicyActivationCodecError("planning-policy activation is non-canonical")
    return value


def _actor(payload: object) -> PlanningPolicyActivationActor:
    data = _mapping(payload, {"actor_id", "user_id", "role", "kind", "is_staff"})
    return PlanningPolicyActivationActor(
        actor_id=_string(data["actor_id"]),
        user_id=_positive_integer(data["user_id"]),
        role=_string(data["role"]),
        kind=_string(data["kind"]),
        is_staff=_boolean(data["is_staff"]),
    )


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise PlanningPolicyActivationCodecError("activation payload shape is invalid")
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return result


__all__ = [
    "PlanningPolicyActivationCodecError",
    "decode_planning_policy_activation",
    "decode_planning_policy_activation_subject",
    "encode_planning_policy_activation",
    "encode_planning_policy_activation_subject",
]
