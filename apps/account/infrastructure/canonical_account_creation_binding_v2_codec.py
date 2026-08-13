"""Strict canonical codec for durable Account creation bindings v2."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.application.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2Recorder,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationServiceRecorder,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from apps.account.infrastructure.canonical_account_creation_codec import (
    CanonicalAccountCreationCodecError,
    decode_canonical_account_creation_allocation,
)
from apps.account.infrastructure.physical_account_row_observation_v2_codec import (
    PhysicalAccountRowObservationV2CodecError,
    decode_physical_account_row_observation_v2_record,
)


class CanonicalAccountCreationBindingV2CodecError(ValueError):
    """A durable creation-binding v2 payload is malformed or non-canonical."""


_PHYSICAL_RECORDER = PhysicalAccountRowObservationV2Recorder(
    recorder_id="canonical-creation-binding-v2-codec",
    service_name="canonical-creation-binding-v2-codec",
)


def encode_canonical_account_creation_binding_v2(
    value: CanonicalAccountCreationBindingV2,
) -> dict[str, object]:
    """Encode one complete durable binding and every nested canonical value."""

    if type(value) is not CanonicalAccountCreationBindingV2:
        raise TypeError("value must be exact CanonicalAccountCreationBindingV2")
    CanonicalAccountCreationBindingV2.__post_init__(value)
    return value.to_payload()


def decode_canonical_account_creation_binding_v2(
    payload: object,
) -> CanonicalAccountCreationBindingV2:
    """Decode, revalidate, and exact-roundtrip one complete durable binding."""

    data = _mapping(payload, "binding")
    _exact_keys(data, _BINDING_KEYS, "binding")
    try:
        allocation = decode_canonical_account_creation_allocation(data["allocation"])
        creation_root = _decode_creation_root(data["creation_root"])
        recorder = _service_recorder(data["recorded_by"])
        _fixed_boolean(data["activation_available"], False, "activation_available")
        _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
        _fixed_boolean(data["mapping_reusable"], False, "mapping_reusable")
        value = CanonicalAccountCreationBindingV2(
            binding_id=_string(data["binding_id"]),
            binding_version=_string(data["binding_version"]),
            allocation=allocation,
            creation_root=creation_root,
            account_namespace_claim=_string(data["account_namespace_claim"]),
            account_id_claim=_string(data["account_id_claim"]),
            underlying_unified_account_namespace_claim=_string(
                data["underlying_unified_account_namespace_claim"]
            ),
            underlying_unified_account_id_claim=_integer(
                data["underlying_unified_account_id_claim"]
            ),
            creation_root_identity_hash=_string(data["creation_root_identity_hash"]),
            creation_root_content_hash=_string(data["creation_root_content_hash"]),
            physical_observation_content_hash=_string(data["physical_observation_content_hash"]),
            physical_source_content_hash=_string(data["physical_source_content_hash"]),
            physical_raw_observation_content_hash=_string(
                data["physical_raw_observation_content_hash"]
            ),
            recorded_by=recorder,
            recorded_at=_datetime(data["recorded_at"]),
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
    except (
        CanonicalAccountCreationBindingV2CodecError,
        CanonicalAccountCreationCodecError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, CanonicalAccountCreationBindingV2CodecError):
            raise
        raise CanonicalAccountCreationBindingV2CodecError(
            "durable creation-binding v2 payload is invalid"
        ) from error
    if encode_canonical_account_creation_binding_v2(value) != payload:
        raise CanonicalAccountCreationBindingV2CodecError(
            "durable creation-binding v2 payload is non-canonical"
        )
    return value


def _decode_creation_root(payload: object) -> AllocatedPhysicalAccountRowObservationV3:
    data = _mapping(payload, "creation_root")
    _exact_keys(data, _CREATION_ROOT_KEYS, "creation_root")
    try:
        allocation = decode_canonical_account_creation_allocation(data["allocation"])
        physical = _decode_physical(data["physical_observation"])
        _fixed_boolean(data["activation_available"], False, "activation_available")
        _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
        value = AllocatedPhysicalAccountRowObservationV3(
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
    except (
        CanonicalAccountCreationBindingV2CodecError,
        CanonicalAccountCreationCodecError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, CanonicalAccountCreationBindingV2CodecError):
            raise
        raise CanonicalAccountCreationBindingV2CodecError(
            "creation_root payload is invalid"
        ) from error
    if value.to_payload() != payload:
        raise CanonicalAccountCreationBindingV2CodecError("creation_root payload is non-canonical")
    return value


def _decode_physical(payload: object) -> PhysicalAccountRowObservationV2:
    data = _mapping(payload, "physical_observation")
    if "activation_available" not in data or "must_not_execute" not in data:
        raise CanonicalAccountCreationBindingV2CodecError(
            "physical_observation has an invalid shape"
        )
    _fixed_boolean(data["activation_available"], False, "activation_available")
    _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
    observation = {
        key: item
        for key, item in data.items()
        if key not in {"activation_available", "must_not_execute"}
    }
    recorder = {
        "recorder_id": _PHYSICAL_RECORDER.recorder_id,
        "service_name": _PHYSICAL_RECORDER.service_name,
        "role": _PHYSICAL_RECORDER.role,
        "kind": _PHYSICAL_RECORDER.kind,
        "is_automated": _PHYSICAL_RECORDER.is_automated,
    }
    try:
        value = decode_physical_account_row_observation_v2_record(
            {"observation": observation, "recorded_by": recorder}
        ).observation
    except PhysicalAccountRowObservationV2CodecError as error:
        raise CanonicalAccountCreationBindingV2CodecError(
            "physical_observation payload is invalid"
        ) from error
    if value.to_payload() != payload:
        raise CanonicalAccountCreationBindingV2CodecError(
            "physical_observation payload is non-canonical"
        )
    return value


def _service_recorder(payload: object) -> CanonicalAccountCreationServiceRecorder:
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
        raise CanonicalAccountCreationBindingV2CodecError(
            "recorded_by payload is invalid"
        ) from error


_BINDING_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "binding_id",
    "binding_version",
    "allocation",
    "creation_root",
    "account_namespace_claim",
    "account_id_claim",
    "account_claim_hash",
    "underlying_unified_account_namespace_claim",
    "underlying_unified_account_id_claim",
    "underlying_claim_hash",
    "creation_root_identity_hash",
    "creation_root_content_hash",
    "physical_observation_content_hash",
    "physical_source_content_hash",
    "physical_raw_observation_content_hash",
    "recorded_by",
    "recorded_at",
    "permission",
    "status",
    "binding_state",
    "owner_assignment_state",
    "identity_hash",
    "content_hash",
    "activation_available",
    "must_not_execute",
    "mapping_reusable",
}
_CREATION_ROOT_KEYS = {
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
    "activation_available",
    "must_not_execute",
}
_RECORDER_KEYS = {"service_id", "role", "kind", "is_automated"}


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise CanonicalAccountCreationBindingV2CodecError(f"{field_name} must be an exact mapping")
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise CanonicalAccountCreationBindingV2CodecError(f"{field_name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise CanonicalAccountCreationBindingV2CodecError("expected an exact string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise CanonicalAccountCreationBindingV2CodecError("expected an exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise CanonicalAccountCreationBindingV2CodecError("expected an exact boolean")
    return value


def _fixed_boolean(value: object, expected: bool, field_name: str) -> None:
    if _boolean(value) is not expected:
        raise CanonicalAccountCreationBindingV2CodecError(f"{field_name} is fixed")


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise CanonicalAccountCreationBindingV2CodecError("datetime must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise CanonicalAccountCreationBindingV2CodecError("datetime is invalid") from error
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise CanonicalAccountCreationBindingV2CodecError("datetime is non-canonical")
    return parsed


__all__ = [
    "CanonicalAccountCreationBindingV2CodecError",
    "decode_canonical_account_creation_binding_v2",
    "encode_canonical_account_creation_binding_v2",
]
