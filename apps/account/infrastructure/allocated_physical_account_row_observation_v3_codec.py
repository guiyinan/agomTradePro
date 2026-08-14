"""Strict canonical codec for allocated Account Physical-v3 creation roots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Recorder,
    PersistedAllocatedPhysicalAccountRowObservationV3,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PersistedPhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationV2Recorder,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from apps.account.infrastructure.canonical_account_creation_codec import (
    CanonicalAccountCreationCodecError,
    decode_canonical_account_creation_allocation,
    encode_canonical_account_creation_allocation,
)
from apps.account.infrastructure.physical_account_row_observation_v2_codec import (
    PhysicalAccountRowObservationV2CodecError,
    decode_physical_account_row_observation_v2_record,
    encode_physical_account_row_observation_v2_record,
)


class AllocatedPhysicalAccountRowObservationV3CodecError(ValueError):
    """A stored allocated Physical-v3 record is malformed or non-canonical."""


_PHYSICAL_CODEC_RECORDER = PhysicalAccountRowObservationV2Recorder(
    recorder_id="allocated-physical-v3-codec",
    service_name="allocated-physical-v3-codec",
)


def encode_allocated_physical_account_row_observation_v3_record(
    value: PersistedAllocatedPhysicalAccountRowObservationV3,
) -> dict[str, object]:
    """Encode the complete creation root, both upstream roots, and projector."""

    if type(value) is not PersistedAllocatedPhysicalAccountRowObservationV3:
        raise TypeError("value must be an exact PersistedAllocatedPhysicalAccountRowObservationV3")
    value.__post_init__()
    observation = value.observation
    recorder = value.recorded_by
    return {
        "observation": {
            "owner": observation.owner,
            "artifact_type": observation.artifact_type,
            "schema": observation.schema,
            "observation_id": observation.observation_id,
            "observation_version": observation.observation_version,
            "allocation": encode_canonical_account_creation_allocation(observation.allocation),
            "physical_observation": _encode_physical(observation.physical_observation),
            "recorded_at": _utc(observation.recorded_at),
            "ttl_valid_until": _utc(observation.ttl_valid_until),
            "valid_until": _utc(observation.valid_until),
            "identity_anchor_kind": observation.identity_anchor_kind,
            "owner_assignment_state": observation.owner_assignment_state,
            "permission": observation.permission,
            "status": observation.status,
            "identity_hash": observation.identity_hash,
            "content_hash": observation.content_hash,
        },
        "recorded_by": {
            "service_id": recorder.service_id,
            "role": recorder.role,
            "kind": recorder.kind,
            "is_automated": recorder.is_automated,
        },
    }


def decode_allocated_physical_account_row_observation_v3_record(
    payload: object,
) -> PersistedAllocatedPhysicalAccountRowObservationV3:
    """Decode, revalidate, and canonical-roundtrip one creation-root record."""

    envelope = _mapping(payload, "record")
    _exact_keys(envelope, {"observation", "recorded_by"}, "record")
    data = _mapping(envelope["observation"], "observation")
    recorder_data = _mapping(envelope["recorded_by"], "recorded_by")
    _exact_keys(data, _OBSERVATION_KEYS, "observation")
    _exact_keys(recorder_data, _RECORDER_KEYS, "recorded_by")
    try:
        allocation = decode_canonical_account_creation_allocation(data["allocation"])
        physical = _decode_physical(data["physical_observation"])
        observation = AllocatedPhysicalAccountRowObservationV3(
            observation_id=_string(data["observation_id"]),
            observation_version=_string(data["observation_version"]),
            allocation=allocation,
            physical_observation=physical,
            recorded_at=_datetime(data["recorded_at"]),
            ttl_valid_until=_datetime(data["ttl_valid_until"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            identity_anchor_kind=_string(data["identity_anchor_kind"]),
            owner_assignment_state=_string(data["owner_assignment_state"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
        )
        recorder = AllocatedPhysicalAccountRowObservationV3Recorder(
            service_id=_string(recorder_data["service_id"]),
            role=_string(recorder_data["role"]),
            kind=_string(recorder_data["kind"]),
            is_automated=_boolean(recorder_data["is_automated"]),
        )
        record = PersistedAllocatedPhysicalAccountRowObservationV3(
            observation=observation,
            recorded_by=recorder,
        )
    except (
        CanonicalAccountCreationCodecError,
        KeyError,
        PhysicalAccountRowObservationV2CodecError,
        TypeError,
        ValueError,
    ) as error:
        raise AllocatedPhysicalAccountRowObservationV3CodecError(
            "allocated Physical-v3 payload is invalid"
        ) from error
    if encode_allocated_physical_account_row_observation_v3_record(record) != payload:
        raise AllocatedPhysicalAccountRowObservationV3CodecError(
            "allocated Physical-v3 payload is non-canonical"
        )
    return record


_OBSERVATION_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "observation_id",
    "observation_version",
    "allocation",
    "physical_observation",
    "recorded_at",
    "ttl_valid_until",
    "valid_until",
    "identity_anchor_kind",
    "owner_assignment_state",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
}
_RECORDER_KEYS = {"service_id", "role", "kind", "is_automated"}


def _encode_physical(value: PhysicalAccountRowObservationV2) -> dict[str, object]:
    record = PersistedPhysicalAccountRowObservationV2(
        observation=value,
        recorded_by=_PHYSICAL_CODEC_RECORDER,
    )
    encoded = encode_physical_account_row_observation_v2_record(record)
    return _mapping(encoded["observation"], "physical_observation")


def _decode_physical(payload: object) -> PhysicalAccountRowObservationV2:
    envelope = {
        "observation": payload,
        "recorded_by": {
            "recorder_id": _PHYSICAL_CODEC_RECORDER.recorder_id,
            "service_name": _PHYSICAL_CODEC_RECORDER.service_name,
            "role": _PHYSICAL_CODEC_RECORDER.role,
            "kind": _PHYSICAL_CODEC_RECORDER.kind,
            "is_automated": _PHYSICAL_CODEC_RECORDER.is_automated,
        },
    }
    return decode_physical_account_row_observation_v2_record(envelope).observation


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AllocatedPhysicalAccountRowObservationV3CodecError(
            f"{field_name} must be an exact mapping"
        )
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise AllocatedPhysicalAccountRowObservationV3CodecError(
            f"{field_name} has an invalid shape"
        )


def _string(value: object) -> str:
    if type(value) is not str:
        raise AllocatedPhysicalAccountRowObservationV3CodecError("expected an exact string")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise AllocatedPhysicalAccountRowObservationV3CodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise AllocatedPhysicalAccountRowObservationV3CodecError(
            "datetime must use canonical UTC Z form"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AllocatedPhysicalAccountRowObservationV3CodecError("datetime is invalid") from error
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise AllocatedPhysicalAccountRowObservationV3CodecError("datetime is non-canonical")
    return parsed


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "AllocatedPhysicalAccountRowObservationV3CodecError",
    "decode_allocated_physical_account_row_observation_v3_record",
    "encode_allocated_physical_account_row_observation_v3_record",
]
