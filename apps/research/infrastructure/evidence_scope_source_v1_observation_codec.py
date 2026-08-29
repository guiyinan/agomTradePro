"""Strict canonical codec for the dormant Evidence scope observation DTO."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.research.application.evidence_scope_source_v1_lifecycle import (
    EvidenceScopeSourceV1Observation,
)
from apps.research.domain.evidence_contracts import ArtifactRef


class EvidenceScopeSourceV1ObservationCodecError(ValueError):
    """An observation payload is malformed, substituted, or non-canonical."""


_ARTIFACT_KEYS = frozenset(
    {"owner", "artifact_type", "artifact_id", "artifact_version", "content_hash"}
)
_OBSERVATION_KEYS = frozenset(
    {
        "observation_id",
        "observation_version",
        "owner_id",
        "tenant_id",
        "account_id",
        "actor_id",
        "artifact",
        "status",
        "recorded_at",
        "valid_until",
        "content_hash",
    }
)


def _mapping(value: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise EvidenceScopeSourceV1ObservationCodecError(f"{label} must be an exact object")
    payload = cast(dict[str, object], value)
    if frozenset(payload) != keys:
        raise EvidenceScopeSourceV1ObservationCodecError(f"{label} keys differ")
    return payload


def _token(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise EvidenceScopeSourceV1ObservationCodecError(f"{label} must be a canonical token")
    return value


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvidenceScopeSourceV1ObservationCodecError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _utc_text(value: datetime, label: str) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceScopeSourceV1ObservationCodecError(f"{label} must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _clock(value: object, label: str) -> datetime:
    text = _token(value, label)
    if not text.endswith("Z"):
        raise EvidenceScopeSourceV1ObservationCodecError(
            f"{label} must use canonical UTC Z microseconds"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise EvidenceScopeSourceV1ObservationCodecError(
            f"{label} is not canonical ISO-8601"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceScopeSourceV1ObservationCodecError(f"{label} must be timezone-aware")
    canonical = parsed.astimezone(UTC)
    if text != canonical.isoformat(timespec="microseconds").replace("+00:00", "Z"):
        raise EvidenceScopeSourceV1ObservationCodecError(
            f"{label} must use canonical UTC Z microseconds"
        )
    return canonical


def encode_evidence_scope_source_v1_observation(
    value: EvidenceScopeSourceV1Observation,
) -> dict[str, object]:
    """Encode one exact observation after revalidating its Domain invariants."""

    if type(value) is not EvidenceScopeSourceV1Observation:
        raise EvidenceScopeSourceV1ObservationCodecError(
            "observation must be an exact EvidenceScopeSourceV1Observation"
        )
    try:
        value.__post_init__()
        payload: dict[str, object] = {
            "account_id": value.account_id,
            "actor_id": value.actor_id,
            "artifact": value.artifact.to_payload(),
            "content_hash": value.content_hash,
            "observation_id": value.observation_id,
            "observation_version": value.observation_version,
            "owner_id": value.owner_id,
            "recorded_at": _utc_text(value.recorded_at, "recorded_at"),
            "status": value.status,
            "tenant_id": value.tenant_id,
            "valid_until": _utc_text(value.valid_until, "valid_until"),
        }
        _mapping(payload, _OBSERVATION_KEYS, "scope observation")
        _mapping(payload["artifact"], _ARTIFACT_KEYS, "scope observation artifact")
        return payload
    except EvidenceScopeSourceV1ObservationCodecError:
        raise
    except (TypeError, ValueError, AttributeError) as error:
        raise EvidenceScopeSourceV1ObservationCodecError("scope observation is invalid") from error


def decode_evidence_scope_source_v1_observation(
    value: object,
) -> EvidenceScopeSourceV1Observation:
    """Decode one exact canonical observation payload and reject substitutions."""

    payload = _mapping(value, _OBSERVATION_KEYS, "scope observation")
    artifact_payload = _mapping(payload["artifact"], _ARTIFACT_KEYS, "scope observation artifact")
    try:
        artifact = ArtifactRef(
            owner=_token(artifact_payload["owner"], "artifact.owner"),
            artifact_type=_token(artifact_payload["artifact_type"], "artifact.artifact_type"),
            artifact_id=_token(artifact_payload["artifact_id"], "artifact.artifact_id"),
            artifact_version=_token(
                artifact_payload["artifact_version"], "artifact.artifact_version"
            ),
            content_hash=_digest(artifact_payload["content_hash"], "artifact.content_hash"),
        )
        observation = EvidenceScopeSourceV1Observation(
            observation_id=_token(payload["observation_id"], "observation_id"),
            observation_version=_token(payload["observation_version"], "observation_version"),
            owner_id=_token(payload["owner_id"], "owner_id"),
            tenant_id=_token(payload["tenant_id"], "tenant_id"),
            account_id=_token(payload["account_id"], "account_id"),
            actor_id=_token(payload["actor_id"], "actor_id"),
            artifact=artifact,
            status=_token(payload["status"], "status"),
            recorded_at=_clock(payload["recorded_at"], "recorded_at"),
            valid_until=_clock(payload["valid_until"], "valid_until"),
            content_hash=_digest(payload["content_hash"], "content_hash"),
        )
        canonical = encode_evidence_scope_source_v1_observation(observation)
    except EvidenceScopeSourceV1ObservationCodecError:
        raise
    except (TypeError, ValueError, AttributeError) as error:
        raise EvidenceScopeSourceV1ObservationCodecError(
            "scope observation payload is invalid"
        ) from error
    if canonical != payload:
        raise EvidenceScopeSourceV1ObservationCodecError(
            "scope observation payload is not canonical"
        )
    return observation


__all__ = [
    "EvidenceScopeSourceV1ObservationCodecError",
    "decode_evidence_scope_source_v1_observation",
    "encode_evidence_scope_source_v1_observation",
]
