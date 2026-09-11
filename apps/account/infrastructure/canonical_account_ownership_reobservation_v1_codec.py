"""Strict JSON boundary for inactive current ownership evidence."""

from datetime import datetime
from typing import cast

from apps.account.application.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2Recorder,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.domain.physical_account_row_observation_v2 import PhysicalAccountRowObservationV2
from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    decode_canonical_account_creation_binding_v2,
)
from apps.account.infrastructure.physical_account_row_observation_v2_codec import (
    decode_physical_account_row_observation_v2_record,
)


class CanonicalAccountOwnershipReobservationV1CodecError(ValueError):
    """A stored observation has malformed facts, incomplete seals, or altered semantics."""


_KEYS = {
    "observation_id",
    "observation_version",
    "binding",
    "current_physical",
    "recorded_at",
    "valid_until",
    "identity_hash",
    "content_hash",
    "owner",
    "artifact_type",
    "schema",
    "permission",
    "status",
    "activation_available",
    "must_not_execute",
}


def _mapping(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise CanonicalAccountOwnershipReobservationV1CodecError("expected an exact JSON object")
    return cast(dict[str, object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise CanonicalAccountOwnershipReobservationV1CodecError("expected an exact string")
    return value


def _seal(value: object) -> str:
    result = _string(value)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise CanonicalAccountOwnershipReobservationV1CodecError("stored seals must be complete")
    return result


def _datetime(value: object) -> datetime:
    result = _string(value)
    if not result.endswith("Z"):
        raise CanonicalAccountOwnershipReobservationV1CodecError("clock must be canonical UTC")
    parsed = datetime.fromisoformat(result[:-1] + "+00:00")
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != result:
        raise CanonicalAccountOwnershipReobservationV1CodecError("clock must retain microseconds")
    return parsed


def _physical(payload: object) -> PhysicalAccountRowObservationV2:
    data = _mapping(payload)
    _seal(data["identity_hash"])
    _seal(data["content_hash"])
    if data.get("activation_available") is not False or data.get("must_not_execute") is not True:
        raise CanonicalAccountOwnershipReobservationV1CodecError(
            "physical evidence must be inactive"
        )
    # Decode through the existing record codec; this local adapter identity is
    # discarded and is neither a persisted recorder nor an authentication fact.
    adapter = PhysicalAccountRowObservationV2Recorder(
        recorder_id="ownership-reobservation-v1-codec",
        service_name="ownership-reobservation-v1-codec",
    )
    value = decode_physical_account_row_observation_v2_record(
        {
            "observation": {
                key: item
                for key, item in data.items()
                if key not in {"activation_available", "must_not_execute"}
            },
            "recorded_by": {
                "recorder_id": adapter.recorder_id,
                "service_name": adapter.service_name,
                "role": adapter.role,
                "kind": adapter.kind,
                "is_automated": adapter.is_automated,
            },
        }
    ).observation
    if value.to_payload() != data:
        raise CanonicalAccountOwnershipReobservationV1CodecError("noncanonical physical payload")
    return value


def encode_canonical_account_ownership_reobservation_v1(
    value: CanonicalAccountOwnershipReobservationV1,
) -> dict[str, object]:
    """Encode the complete evidence payload without granting authority."""
    if type(value) is not CanonicalAccountOwnershipReobservationV1:
        raise TypeError("expected exact ownership reobservation")
    return value.to_payload()


def decode_canonical_account_ownership_reobservation_v1(
    payload: object,
) -> CanonicalAccountOwnershipReobservationV1:
    """Require exact fields, sealed nested evidence, and a canonical round trip."""
    data = _mapping(payload)
    if set(data) != _KEYS:
        raise CanonicalAccountOwnershipReobservationV1CodecError("invalid observation shape")
    try:
        if data["activation_available"] is not False or data["must_not_execute"] is not True:
            raise CanonicalAccountOwnershipReobservationV1CodecError(
                "evidence must remain inactive"
            )
        binding_payload = _mapping(data["binding"])
        _seal(binding_payload["identity_hash"])
        _seal(binding_payload["content_hash"])
        value = CanonicalAccountOwnershipReobservationV1(
            observation_id=_string(data["observation_id"]),
            observation_version=_string(data["observation_version"]),
            binding=decode_canonical_account_creation_binding_v2(binding_payload),
            current_physical=_physical(data["current_physical"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_seal(data["identity_hash"]),
            content_hash=_seal(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
        )
        if value.to_payload() != data:
            raise CanonicalAccountOwnershipReobservationV1CodecError("noncanonical observation")
        return value
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, CanonicalAccountOwnershipReobservationV1CodecError):
            raise
        raise CanonicalAccountOwnershipReobservationV1CodecError(
            "invalid stored observation"
        ) from error
