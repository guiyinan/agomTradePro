"""Strict canonical codec for actor-bound physical account-row evidence."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.application.physical_account_row_observation import (
    PersistedPhysicalAccountRowObservation,
    PhysicalAccountRowObservationActor,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
)


class PhysicalAccountRowObservationCodecError(ValueError):
    """A stored physical account-row record is malformed or non-canonical."""


def encode_physical_account_row_observation_record(
    value: PersistedPhysicalAccountRowObservation,
) -> dict[str, object]:
    """Encode one complete observation and authenticated server actor."""

    PersistedPhysicalAccountRowObservation.__post_init__(value)
    payload = value.observation.to_payload()
    observation = {
        key: item
        for key, item in payload.items()
        if key not in {"activation_available", "must_not_execute"}
    }
    actor = value.captured_by
    return {
        "observation": observation,
        "captured_by": {
            "actor_id": actor.actor_id,
            "user_id": actor.user_id,
            "role": actor.role,
            "kind": actor.kind,
            "is_staff": actor.is_staff,
        },
    }


def decode_physical_account_row_observation_record(
    payload: object,
) -> PersistedPhysicalAccountRowObservation:
    """Decode and canonical-roundtrip-check one stored observation record."""

    envelope = _mapping(payload, "record")
    _exact_keys(envelope, {"observation", "captured_by"}, "record")
    observation_data = _mapping(envelope["observation"], "observation")
    actor_data = _mapping(envelope["captured_by"], "captured_by")
    _exact_keys(observation_data, _OBSERVATION_KEYS, "observation")
    _exact_keys(actor_data, _ACTOR_KEYS, "captured_by")
    try:
        observation = PhysicalAccountRowObservation(
            observation_id=_string(observation_data["observation_id"]),
            observation_version=_string(observation_data["observation_version"]),
            account_namespace=_string(observation_data["account_namespace"]),
            account_id=_string(observation_data["account_id"]),
            underlying_unified_account_namespace=_string(
                observation_data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_integer(
                observation_data["underlying_unified_account_id"]
            ),
            raw_source_owner=_string(observation_data["raw_source_owner"]),
            raw_source_artifact_type=_string(observation_data["raw_source_artifact_type"]),
            raw_source_id=_string(observation_data["raw_source_id"]),
            raw_source_version=_string(observation_data["raw_source_version"]),
            raw_source_content_hash=_string(observation_data["raw_source_content_hash"]),
            row_user_id=_optional_integer(observation_data["row_user_id"]),
            account_type=_string(observation_data["account_type"]),
            is_active=_boolean(observation_data["is_active"]),
            row_created_at=_datetime(observation_data["row_created_at"]),
            row_updated_at=_datetime(observation_data["row_updated_at"]),
            observed_at=_datetime(observation_data["observed_at"]),
            recorded_at=_datetime(observation_data["recorded_at"]),
            raw_source_valid_until=_datetime(observation_data["raw_source_valid_until"]),
            ttl_valid_until=_datetime(observation_data["ttl_valid_until"]),
            valid_until=_datetime(observation_data["valid_until"]),
            supersedes_content_hash=_optional_string(observation_data["supersedes_content_hash"]),
            identity_hash=_string(observation_data["identity_hash"]),
            content_hash=_string(observation_data["content_hash"]),
            owner_assignment_state=_string(observation_data["owner_assignment_state"]),
            owner=_string(observation_data["owner"]),
            artifact_type=_string(observation_data["artifact_type"]),
            schema=_string(observation_data["schema"]),
            permission=_string(observation_data["permission"]),
            status=_string(observation_data["status"]),
            blocker_codes=_string_tuple(observation_data["blocker_codes"]),
        )
        actor = PhysicalAccountRowObservationActor(
            actor_id=_string(actor_data["actor_id"]),
            user_id=_integer(actor_data["user_id"]),
            role=_string(actor_data["role"]),
            kind=_string(actor_data["kind"]),
            is_staff=_boolean(actor_data["is_staff"]),
        )
        record = PersistedPhysicalAccountRowObservation(
            observation=observation,
            captured_by=actor,
        )
    except (TypeError, ValueError, KeyError) as error:
        raise PhysicalAccountRowObservationCodecError(
            "physical account-row payload is invalid"
        ) from error
    if encode_physical_account_row_observation_record(record) != payload:
        raise PhysicalAccountRowObservationCodecError(
            "physical account-row payload is non-canonical"
        )
    return record


_OBSERVATION_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "observation_id",
    "observation_version",
    "account_namespace",
    "account_id",
    "underlying_unified_account_namespace",
    "underlying_unified_account_id",
    "raw_source_owner",
    "raw_source_artifact_type",
    "raw_source_id",
    "raw_source_version",
    "raw_source_content_hash",
    "row_user_id",
    "account_type",
    "is_active",
    "row_created_at",
    "row_updated_at",
    "observed_at",
    "recorded_at",
    "raw_source_valid_until",
    "ttl_valid_until",
    "valid_until",
    "owner_assignment_state",
    "supersedes_content_hash",
    "permission",
    "status",
    "blocker_codes",
    "identity_hash",
    "content_hash",
}
_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise PhysicalAccountRowObservationCodecError(f"{field_name} must be an exact mapping")
    return cast(dict[str, object], value)


def _exact_keys(
    value: dict[str, object],
    expected: set[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise PhysicalAccountRowObservationCodecError(f"{field_name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise PhysicalAccountRowObservationCodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise PhysicalAccountRowObservationCodecError("expected an exact integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise PhysicalAccountRowObservationCodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise PhysicalAccountRowObservationCodecError("datetime must use canonical UTC Z form")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise PhysicalAccountRowObservationCodecError("datetime is non-canonical")
    return parsed


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise PhysicalAccountRowObservationCodecError("blocker_codes must be an exact list")
    return tuple(_string(item) for item in cast(list[object], value))


__all__ = [
    "PhysicalAccountRowObservationCodecError",
    "decode_physical_account_row_observation_record",
    "encode_physical_account_row_observation_record",
]
