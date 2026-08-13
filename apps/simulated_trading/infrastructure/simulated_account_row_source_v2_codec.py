"""Strict canonical codec for raw-observation-bound v2 row sources."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


class SimulatedAccountRowSourceV2CodecError(ValueError):
    """A stored v2 source record is malformed or non-canonical."""


def encode_simulated_account_row_source_v2_record(
    value: PersistedSimulatedAccountRowSourceV2,
) -> dict[str, object]:
    """Encode one complete v2 source without inferred persistence facts."""

    PersistedSimulatedAccountRowSourceV2.__post_init__(value)
    payload = value.source.to_payload()
    return {
        "source": {
            key: item
            for key, item in payload.items()
            if key not in {"activation_available", "must_not_execute"}
        }
    }


def decode_simulated_account_row_source_v2_record(
    payload: object,
) -> PersistedSimulatedAccountRowSourceV2:
    """Decode and canonical-roundtrip-check one stored v2 source."""

    envelope = _mapping(payload, "record")
    _exact_keys(envelope, {"source"}, "record")
    data = _mapping(envelope["source"], "source")
    _exact_keys(data, _SOURCE_KEYS, "source")
    try:
        source = SimulatedAccountRowSourceV2(
            source_id=_string(data["source_id"]),
            source_version=_string(data["source_version"]),
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
            observed_at=_datetime(data["observed_at"]),
            recorded_at=_datetime(data["recorded_at"]),
            source_valid_until=_datetime(data["source_valid_until"]),
            ttl_valid_until=_datetime(data["ttl_valid_until"]),
            valid_until=_datetime(data["valid_until"]),
            raw_observation_id=_string(data["raw_observation_id"]),
            raw_observation_version=_string(data["raw_observation_version"]),
            raw_observation_identity_hash=_string(data["raw_observation_identity_hash"]),
            raw_observation_content_hash=_string(data["raw_observation_content_hash"]),
            raw_observation_observed_at=_datetime(data["raw_observation_observed_at"]),
            raw_observation_valid_until=_datetime(data["raw_observation_valid_until"]),
            raw_observation_supersedes_content_hash=_optional_string(
                data["raw_observation_supersedes_content_hash"]
            ),
            supersedes_content_hash=_optional_string(data["supersedes_content_hash"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner_assignment_state=_string(data["owner_assignment_state"]),
            raw_observation_owner=_string(data["raw_observation_owner"]),
            raw_observation_artifact_type=_string(data["raw_observation_artifact_type"]),
            raw_observation_schema=_string(data["raw_observation_schema"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
        )
        record = PersistedSimulatedAccountRowSourceV2(source=source)
    except (KeyError, TypeError, ValueError) as error:
        raise SimulatedAccountRowSourceV2CodecError(
            "simulated account-row source v2 payload is invalid"
        ) from error
    if encode_simulated_account_row_source_v2_record(record) != payload:
        raise SimulatedAccountRowSourceV2CodecError(
            "simulated account-row source v2 payload is non-canonical"
        )
    return record


_SOURCE_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "source_id",
    "source_version",
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
    "observed_at",
    "recorded_at",
    "source_valid_until",
    "ttl_valid_until",
    "valid_until",
    "raw_observation_owner",
    "raw_observation_artifact_type",
    "raw_observation_schema",
    "raw_observation_id",
    "raw_observation_version",
    "raw_observation_identity_hash",
    "raw_observation_content_hash",
    "raw_observation_observed_at",
    "raw_observation_valid_until",
    "raw_observation_supersedes_content_hash",
    "owner_assignment_state",
    "supersedes_content_hash",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
}


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise SimulatedAccountRowSourceV2CodecError(f"{field_name} must be an exact mapping")
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise SimulatedAccountRowSourceV2CodecError(f"{field_name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise SimulatedAccountRowSourceV2CodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise SimulatedAccountRowSourceV2CodecError("expected an exact integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise SimulatedAccountRowSourceV2CodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise SimulatedAccountRowSourceV2CodecError("datetime must use canonical UTC Z form")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise SimulatedAccountRowSourceV2CodecError("datetime is non-canonical")
    return parsed


__all__ = [
    "SimulatedAccountRowSourceV2CodecError",
    "decode_simulated_account_row_source_v2_record",
    "encode_simulated_account_row_source_v2_record",
]
