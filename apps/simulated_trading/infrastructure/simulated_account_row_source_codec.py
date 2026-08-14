"""Strict canonical codec for actor-bound simulated account-row sources."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.simulated_trading.application.simulated_account_row_source import (
    PersistedSimulatedAccountRowSource,
    SimulatedAccountRowSourceActor,
)
from apps.simulated_trading.domain.simulated_account_row_source import (
    SimulatedAccountRowSource,
)


class SimulatedAccountRowSourceCodecError(ValueError):
    """A stored simulated account-row source is malformed or non-canonical."""


def encode_simulated_account_row_source_record(
    value: PersistedSimulatedAccountRowSource,
) -> dict[str, object]:
    """Encode one complete source and authenticated server actor."""

    PersistedSimulatedAccountRowSource.__post_init__(value)
    payload = value.source.to_payload()
    source = {
        key: item
        for key, item in payload.items()
        if key not in {"activation_available", "must_not_execute"}
    }
    actor = value.captured_by
    return {
        "source": source,
        "captured_by": {
            "actor_id": actor.actor_id,
            "user_id": actor.user_id,
            "role": actor.role,
            "kind": actor.kind,
            "is_staff": actor.is_staff,
        },
    }


def decode_simulated_account_row_source_record(
    payload: object,
) -> PersistedSimulatedAccountRowSource:
    """Decode and canonical-roundtrip-check one stored source record."""

    envelope = _mapping(payload, "record")
    _exact_keys(envelope, {"source", "captured_by"}, "record")
    source_data = _mapping(envelope["source"], "source")
    actor_data = _mapping(envelope["captured_by"], "captured_by")
    _exact_keys(source_data, _SOURCE_KEYS, "source")
    _exact_keys(actor_data, _ACTOR_KEYS, "captured_by")
    try:
        source = SimulatedAccountRowSource(
            source_id=_string(source_data["source_id"]),
            source_version=_string(source_data["source_version"]),
            account_namespace=_string(source_data["account_namespace"]),
            account_id=_string(source_data["account_id"]),
            underlying_unified_account_namespace=_string(
                source_data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_integer(source_data["underlying_unified_account_id"]),
            row_user_id=_optional_integer(source_data["row_user_id"]),
            raw_account_type=_string(source_data["raw_account_type"]),
            is_active=_boolean(source_data["is_active"]),
            row_created_at=_datetime(source_data["row_created_at"]),
            row_updated_at=_datetime(source_data["row_updated_at"]),
            is_present=_boolean(source_data["is_present"]),
            is_tombstone=_boolean(source_data["is_tombstone"]),
            observed_at=_datetime(source_data["observed_at"]),
            recorded_at=_datetime(source_data["recorded_at"]),
            source_valid_until=_datetime(source_data["source_valid_until"]),
            ttl_valid_until=_datetime(source_data["ttl_valid_until"]),
            valid_until=_datetime(source_data["valid_until"]),
            supersedes_content_hash=_optional_string(source_data["supersedes_content_hash"]),
            identity_hash=_string(source_data["identity_hash"]),
            content_hash=_string(source_data["content_hash"]),
            owner_assignment_state=_string(source_data["owner_assignment_state"]),
            owner=_string(source_data["owner"]),
            artifact_type=_string(source_data["artifact_type"]),
            schema=_string(source_data["schema"]),
            permission=_string(source_data["permission"]),
            status=_string(source_data["status"]),
        )
        actor = SimulatedAccountRowSourceActor(
            actor_id=_string(actor_data["actor_id"]),
            user_id=_integer(actor_data["user_id"]),
            role=_string(actor_data["role"]),
            kind=_string(actor_data["kind"]),
            is_staff=_boolean(actor_data["is_staff"]),
        )
        record = PersistedSimulatedAccountRowSource(
            source=source,
            captured_by=actor,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SimulatedAccountRowSourceCodecError(
            "simulated account-row source payload is invalid"
        ) from error
    if encode_simulated_account_row_source_record(record) != payload:
        raise SimulatedAccountRowSourceCodecError(
            "simulated account-row source payload is non-canonical"
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
        raise SimulatedAccountRowSourceCodecError(f"{field_name} must be an exact mapping")
    return cast(dict[str, object], value)


def _exact_keys(
    value: dict[str, object],
    expected: set[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise SimulatedAccountRowSourceCodecError(f"{field_name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise SimulatedAccountRowSourceCodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise SimulatedAccountRowSourceCodecError("expected an exact integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise SimulatedAccountRowSourceCodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise SimulatedAccountRowSourceCodecError("datetime must use canonical UTC Z form")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise SimulatedAccountRowSourceCodecError("datetime is non-canonical")
    return parsed


__all__ = [
    "SimulatedAccountRowSourceCodecError",
    "decode_simulated_account_row_source_record",
    "encode_simulated_account_row_source_record",
]
