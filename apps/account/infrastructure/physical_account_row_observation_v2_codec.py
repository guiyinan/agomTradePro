"""Strict canonical codec for actor-bound Account v2 row evidence."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.application.physical_account_row_observation_v2 import (
    PersistedPhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationActor,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)


class PhysicalAccountRowObservationV2CodecError(ValueError):
    """A stored Account v2 record is malformed or non-canonical."""


def encode_physical_account_row_observation_v2_record(
    value: PersistedPhysicalAccountRowObservationV2,
) -> dict[str, object]:
    """Encode one complete Account v2 observation and server actor."""

    PersistedPhysicalAccountRowObservationV2.__post_init__(value)
    payload = value.observation.to_payload()
    actor = value.captured_by
    return {
        "observation": {
            key: item
            for key, item in payload.items()
            if key not in {"activation_available", "must_not_execute"}
        },
        "captured_by": {
            "actor_id": actor.actor_id,
            "user_id": actor.user_id,
            "role": actor.role,
            "kind": actor.kind,
            "is_staff": actor.is_staff,
        },
    }


def decode_physical_account_row_observation_v2_record(
    payload: object,
) -> PersistedPhysicalAccountRowObservationV2:
    """Decode and canonical-roundtrip-check one stored Account v2 record."""

    envelope = _mapping(payload, "record")
    _exact_keys(envelope, {"observation", "captured_by"}, "record")
    data = _mapping(envelope["observation"], "observation")
    actor_data = _mapping(envelope["captured_by"], "captured_by")
    _exact_keys(data, _OBSERVATION_KEYS, "observation")
    _exact_keys(actor_data, _ACTOR_KEYS, "captured_by")
    try:
        observation = PhysicalAccountRowObservationV2(
            observation_id=_string(data["observation_id"]),
            observation_version=_string(data["observation_version"]),
            account_namespace=_string(data["account_namespace"]),
            account_id=_string(data["account_id"]),
            underlying_unified_account_namespace=_string(
                data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_integer(data["underlying_unified_account_id"]),
            row_user_id=_optional_integer(data["row_user_id"]),
            raw_account_type=_string(data["raw_account_type"]),
            is_active=_boolean(data["is_active"]),
            row_created_at=_datetime(data["row_created_at"]),
            row_updated_at=_datetime(data["row_updated_at"]),
            is_present=_boolean(data["is_present"]),
            is_tombstone=_boolean(data["is_tombstone"]),
            source_id=_string(data["source_id"]),
            source_version=_string(data["source_version"]),
            source_identity_hash=_string(data["source_identity_hash"]),
            source_content_hash=_string(data["source_content_hash"]),
            source_supersedes_content_hash=_optional_string(data["source_supersedes_content_hash"]),
            source_observed_at=_datetime(data["source_observed_at"]),
            source_recorded_at=_datetime(data["source_recorded_at"]),
            source_valid_until=_datetime(data["source_valid_until"]),
            source_ttl_valid_until=_datetime(data["source_ttl_valid_until"]),
            source_effective_valid_until=_datetime(data["source_effective_valid_until"]),
            raw_observation_id=_string(data["raw_observation_id"]),
            raw_observation_version=_string(data["raw_observation_version"]),
            raw_observation_identity_hash=_string(data["raw_observation_identity_hash"]),
            raw_observation_content_hash=_string(data["raw_observation_content_hash"]),
            raw_observation_supersedes_content_hash=_optional_string(
                data["raw_observation_supersedes_content_hash"]
            ),
            raw_observation_observed_at=_datetime(data["raw_observation_observed_at"]),
            raw_observation_valid_until=_datetime(data["raw_observation_valid_until"]),
            recorded_at=_datetime(data["recorded_at"]),
            ttl_valid_until=_datetime(data["ttl_valid_until"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_content_hash=_optional_string(data["supersedes_content_hash"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner_assignment_state=_string(data["owner_assignment_state"]),
            source_owner=_string(data["source_owner"]),
            source_artifact_type=_string(data["source_artifact_type"]),
            source_schema=_string(data["source_schema"]),
            raw_observation_owner=_string(data["raw_observation_owner"]),
            raw_observation_artifact_type=_string(data["raw_observation_artifact_type"]),
            raw_observation_schema=_string(data["raw_observation_schema"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
        )
        actor = PhysicalAccountRowObservationActor(
            actor_id=_string(actor_data["actor_id"]),
            user_id=_integer(actor_data["user_id"]),
            role=_string(actor_data["role"]),
            kind=_string(actor_data["kind"]),
            is_staff=_boolean(actor_data["is_staff"]),
        )
        record = PersistedPhysicalAccountRowObservationV2(
            observation=observation,
            captured_by=actor,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PhysicalAccountRowObservationV2CodecError(
            "physical account-row v2 payload is invalid"
        ) from error
    if encode_physical_account_row_observation_v2_record(record) != payload:
        raise PhysicalAccountRowObservationV2CodecError(
            "physical account-row v2 payload is non-canonical"
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
    "row_user_id",
    "raw_account_type",
    "is_active",
    "row_created_at",
    "row_updated_at",
    "is_present",
    "is_tombstone",
    "source_owner",
    "source_artifact_type",
    "source_schema",
    "source_id",
    "source_version",
    "source_identity_hash",
    "source_content_hash",
    "source_supersedes_content_hash",
    "source_observed_at",
    "source_recorded_at",
    "source_valid_until",
    "source_ttl_valid_until",
    "source_effective_valid_until",
    "raw_observation_owner",
    "raw_observation_artifact_type",
    "raw_observation_schema",
    "raw_observation_id",
    "raw_observation_version",
    "raw_observation_identity_hash",
    "raw_observation_content_hash",
    "raw_observation_supersedes_content_hash",
    "raw_observation_observed_at",
    "raw_observation_valid_until",
    "recorded_at",
    "ttl_valid_until",
    "valid_until",
    "owner_assignment_state",
    "supersedes_content_hash",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
}
_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise PhysicalAccountRowObservationV2CodecError(f"{field_name} must be an exact mapping")
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise PhysicalAccountRowObservationV2CodecError(f"{field_name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise PhysicalAccountRowObservationV2CodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise PhysicalAccountRowObservationV2CodecError("expected an exact integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise PhysicalAccountRowObservationV2CodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise PhysicalAccountRowObservationV2CodecError("datetime must use canonical UTC Z form")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise PhysicalAccountRowObservationV2CodecError("datetime is non-canonical")
    return parsed


__all__ = [
    "PhysicalAccountRowObservationV2CodecError",
    "decode_physical_account_row_observation_v2_record",
    "encode_physical_account_row_observation_v2_record",
]
