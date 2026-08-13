"""Strict canonical codec for persisted simulated-account row observations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.simulated_trading.application.simulated_account_raw_observation import (
    PersistedSimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)


class SimulatedAccountRawObservationCodecError(ValueError):
    """A stored raw observation record is malformed or non-canonical."""


def encode_simulated_account_raw_observation_record(
    value: PersistedSimulatedAccountRawObservation,
) -> dict[str, object]:
    """Encode one complete raw observation and its persistence clock."""

    PersistedSimulatedAccountRawObservation.__post_init__(value)
    payload = value.observation.to_payload()
    return {
        "observation": {
            key: item
            for key, item in payload.items()
            if key not in {"activation_available", "must_not_execute"}
        },
        "recorded_at": _utc_text(value.recorded_at),
    }


def decode_simulated_account_raw_observation_record(
    payload: object,
) -> PersistedSimulatedAccountRawObservation:
    """Decode and canonical-roundtrip-check one stored raw observation."""

    envelope = _mapping(payload, "record")
    _exact_keys(envelope, {"observation", "recorded_at"}, "record")
    data = _mapping(envelope["observation"], "observation")
    _exact_keys(data, _OBSERVATION_KEYS, "observation")
    try:
        observation = SimulatedAccountRawObservation(
            observation_id=_string(data["observation_id"]),
            observation_version=_string(data["observation_version"]),
            row_pk=_integer(data["row_pk"]),
            row_user_id=_optional_integer(data["row_user_id"]),
            raw_account_type=_string(data["raw_account_type"]),
            is_active=_boolean(data["is_active"]),
            row_created_at=_datetime(data["row_created_at"]),
            row_updated_at=_datetime(data["row_updated_at"]),
            is_present=_boolean(data["is_present"]),
            is_tombstone=_boolean(data["is_tombstone"]),
            observed_at=_datetime(data["observed_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_content_hash=_optional_string(data["supersedes_content_hash"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
        )
        record = PersistedSimulatedAccountRawObservation(
            observation=observation,
            recorded_at=_datetime(envelope["recorded_at"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SimulatedAccountRawObservationCodecError(
            "simulated account raw observation payload is invalid"
        ) from error
    if encode_simulated_account_raw_observation_record(record) != payload:
        raise SimulatedAccountRawObservationCodecError(
            "simulated account raw observation payload is non-canonical"
        )
    return record


_OBSERVATION_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "observation_id",
    "observation_version",
    "row_pk",
    "row_user_id",
    "raw_account_type",
    "is_active",
    "row_created_at",
    "row_updated_at",
    "is_present",
    "is_tombstone",
    "observed_at",
    "valid_until",
    "supersedes_content_hash",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
}


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise SimulatedAccountRawObservationCodecError(f"{field_name} must be an exact mapping")
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise SimulatedAccountRawObservationCodecError(f"{field_name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise SimulatedAccountRawObservationCodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise SimulatedAccountRawObservationCodecError("expected an exact integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise SimulatedAccountRawObservationCodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise SimulatedAccountRawObservationCodecError("datetime must use canonical UTC Z form")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if _utc_text(parsed) != text:
        raise SimulatedAccountRawObservationCodecError("datetime is non-canonical")
    return parsed


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "SimulatedAccountRawObservationCodecError",
    "decode_simulated_account_raw_observation_record",
    "encode_simulated_account_raw_observation_record",
]
