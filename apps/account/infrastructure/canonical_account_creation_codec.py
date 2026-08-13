"""Strict canonical codec for Account creation allocation and binding evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.application.physical_account_row_observation_v2 import (
    PersistedPhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationV2Recorder,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
    CanonicalAccountCreationRequester,
    CanonicalAccountCreationServiceRecorder,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from apps.account.infrastructure.physical_account_row_observation_v2_codec import (
    PhysicalAccountRowObservationV2CodecError,
    decode_physical_account_row_observation_v2_record,
    encode_physical_account_row_observation_v2_record,
)


class CanonicalAccountCreationCodecError(ValueError):
    """A creation allocation or binding payload is malformed or non-canonical."""


_PHYSICAL_RECORDER = PhysicalAccountRowObservationV2Recorder(
    recorder_id="canonical-creation-codec",
    service_name="canonical-creation-codec",
)


def encode_canonical_account_creation_allocation(
    value: CanonicalAccountCreationAllocation,
) -> dict[str, object]:
    """Encode one complete allocation including actors, fixed fields, and seals."""

    if type(value) is not CanonicalAccountCreationAllocation:
        raise TypeError("value must be exact CanonicalAccountCreationAllocation")
    value.__post_init__()
    return {
        **value.to_payload(),
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
    }


def decode_canonical_account_creation_allocation(
    payload: object,
) -> CanonicalAccountCreationAllocation:
    """Decode, rebuild, revalidate, and canonical-roundtrip one allocation."""

    data = _mapping(payload, "allocation")
    _exact_keys(data, _ALLOCATION_KEYS, "allocation")
    requester = _requester(data["requested_by"])
    recorder = _recorder(data["recorded_by"])
    try:
        value = CanonicalAccountCreationAllocation(
            allocation_id=_string(data["allocation_id"]),
            allocation_version=_string(data["allocation_version"]),
            canonical_account_namespace=_string(data["canonical_account_namespace"]),
            canonical_account_id=_string(data["canonical_account_id"]),
            requested_row_user_id=_integer(data["requested_row_user_id"]),
            requested_raw_account_type=_string(data["requested_raw_account_type"]),
            intended_underlying_unified_account_namespace=_string(
                data["intended_underlying_unified_account_namespace"]
            ),
            request_fingerprint_hash=_string(data["request_fingerprint_hash"]),
            requested_by=requester,
            allocated_at=_datetime(data["allocated_at"]),
            valid_until=_datetime(data["valid_until"]),
            recorded_by=recorder,
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            intended_purpose=_string(data["intended_purpose"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CanonicalAccountCreationCodecError("allocation payload is invalid") from error
    if encode_canonical_account_creation_allocation(value) != payload:
        raise CanonicalAccountCreationCodecError("allocation payload is non-canonical")
    return value


def encode_canonical_account_creation_binding(
    value: CanonicalAccountCreationBinding,
) -> dict[str, object]:
    """Encode a binding with complete nested allocation and Physical-v2 values."""

    if type(value) is not CanonicalAccountCreationBinding:
        raise TypeError("value must be exact CanonicalAccountCreationBinding")
    value.__post_init__()
    return {
        "binding_id": value.binding_id,
        "binding_version": value.binding_version,
        "allocation": encode_canonical_account_creation_allocation(value.allocation),
        "physical_observation": _encode_physical(value.physical_observation),
        "account_namespace_claim": value.account_namespace_claim,
        "account_id_claim": value.account_id_claim,
        "underlying_unified_account_namespace_claim": (
            value.underlying_unified_account_namespace_claim
        ),
        "underlying_unified_account_id_claim": value.underlying_unified_account_id_claim,
        "recorded_by": value.recorded_by.to_payload(),
        "recorded_at": _utc(value.recorded_at),
        "valid_until": _utc(value.valid_until),
        "account_claim_hash": value.account_claim_hash,
        "underlying_claim_hash": value.underlying_claim_hash,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "status": value.status,
        "binding_state": value.binding_state,
        "owner_assignment_state": value.owner_assignment_state,
    }


def decode_canonical_account_creation_binding(
    payload: object,
) -> CanonicalAccountCreationBinding:
    """Decode and revalidate both complete upstream values before roundtripping."""

    data = _mapping(payload, "binding")
    _exact_keys(data, _BINDING_KEYS, "binding")
    allocation = decode_canonical_account_creation_allocation(data["allocation"])
    physical = _decode_physical(data["physical_observation"])
    recorder = _recorder(data["recorded_by"])
    try:
        value = CanonicalAccountCreationBinding(
            binding_id=_string(data["binding_id"]),
            binding_version=_string(data["binding_version"]),
            allocation=allocation,
            physical_observation=physical,
            account_namespace_claim=_string(data["account_namespace_claim"]),
            account_id_claim=_string(data["account_id_claim"]),
            underlying_unified_account_namespace_claim=_string(
                data["underlying_unified_account_namespace_claim"]
            ),
            underlying_unified_account_id_claim=_integer(
                data["underlying_unified_account_id_claim"]
            ),
            recorded_by=recorder,
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            account_claim_hash=_string(data["account_claim_hash"]),
            underlying_claim_hash=_string(data["underlying_claim_hash"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
            binding_state=_string(data["binding_state"]),
            owner_assignment_state=_string(data["owner_assignment_state"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CanonicalAccountCreationCodecError("binding payload is invalid") from error
    if encode_canonical_account_creation_binding(value) != payload:
        raise CanonicalAccountCreationCodecError("binding payload is non-canonical")
    return value


_ALLOCATION_KEYS = {
    "allocation_id",
    "allocation_version",
    "canonical_account_namespace",
    "canonical_account_id",
    "requested_row_user_id",
    "requested_raw_account_type",
    "intended_underlying_unified_account_namespace",
    "request_fingerprint_hash",
    "requested_by",
    "allocated_at",
    "valid_until",
    "recorded_by",
    "identity_hash",
    "content_hash",
    "owner",
    "artifact_type",
    "schema",
    "intended_purpose",
    "permission",
    "status",
}
_BINDING_KEYS = {
    "binding_id",
    "binding_version",
    "allocation",
    "physical_observation",
    "account_namespace_claim",
    "account_id_claim",
    "underlying_unified_account_namespace_claim",
    "underlying_unified_account_id_claim",
    "recorded_by",
    "recorded_at",
    "valid_until",
    "account_claim_hash",
    "underlying_claim_hash",
    "identity_hash",
    "content_hash",
    "owner",
    "artifact_type",
    "schema",
    "permission",
    "status",
    "binding_state",
    "owner_assignment_state",
}
_REQUESTER_KEYS = {"actor_id", "user_id", "role", "kind", "is_authenticated"}
_RECORDER_KEYS = {"service_id", "role", "kind", "is_automated"}


def _requester(payload: object) -> CanonicalAccountCreationRequester:
    data = _mapping(payload, "requested_by")
    _exact_keys(data, _REQUESTER_KEYS, "requested_by")
    try:
        return CanonicalAccountCreationRequester(
            actor_id=_string(data["actor_id"]),
            user_id=_integer(data["user_id"]),
            role=_string(data["role"]),
            kind=_string(data["kind"]),
            is_authenticated=_boolean(data["is_authenticated"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CanonicalAccountCreationCodecError("requester payload is invalid") from error


def _recorder(payload: object) -> CanonicalAccountCreationServiceRecorder:
    data = _mapping(payload, "recorded_by")
    _exact_keys(data, _RECORDER_KEYS, "recorded_by")
    try:
        return CanonicalAccountCreationServiceRecorder(
            service_id=_string(data["service_id"]),
            role=_string(data["role"]),
            kind=_string(data["kind"]),
            is_automated=_boolean(data["is_automated"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CanonicalAccountCreationCodecError("recorder payload is invalid") from error


def _encode_physical(value: PhysicalAccountRowObservationV2) -> dict[str, object]:
    record = PersistedPhysicalAccountRowObservationV2(value, _PHYSICAL_RECORDER)
    encoded = encode_physical_account_row_observation_v2_record(record)
    return _mapping(encoded["observation"], "physical_observation")


def _decode_physical(payload: object) -> PhysicalAccountRowObservationV2:
    envelope = {
        "observation": payload,
        "recorded_by": {
            "recorder_id": _PHYSICAL_RECORDER.recorder_id,
            "service_name": _PHYSICAL_RECORDER.service_name,
            "role": _PHYSICAL_RECORDER.role,
            "kind": _PHYSICAL_RECORDER.kind,
            "is_automated": _PHYSICAL_RECORDER.is_automated,
        },
    }
    try:
        return decode_physical_account_row_observation_v2_record(envelope).observation
    except PhysicalAccountRowObservationV2CodecError as error:
        raise CanonicalAccountCreationCodecError("physical payload is invalid") from error


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise CanonicalAccountCreationCodecError(f"{field_name} must be an exact mapping")
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise CanonicalAccountCreationCodecError(f"{field_name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise CanonicalAccountCreationCodecError("expected an exact string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise CanonicalAccountCreationCodecError("expected an exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise CanonicalAccountCreationCodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise CanonicalAccountCreationCodecError("datetime must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise CanonicalAccountCreationCodecError("datetime is invalid") from error
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise CanonicalAccountCreationCodecError("datetime is non-canonical")
    return parsed


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "CanonicalAccountCreationCodecError",
    "decode_canonical_account_creation_allocation",
    "decode_canonical_account_creation_binding",
    "encode_canonical_account_creation_allocation",
    "encode_canonical_account_creation_binding",
]
