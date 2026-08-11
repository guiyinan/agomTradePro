"""Strict payload codec for the Research R8 monitoring policy owner."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.portfolio.infrastructure.governed_optimization_monitoring_codec import (
    decode_monitoring_policy,
    encode_monitoring_policy,
)
from apps.research.domain.r8_monitoring_policy_registry import (
    POLICY_DEFINITION_VERSION,
    R8MonitoringPolicyDefinition,
    R8MonitoringPolicySourceReceipt,
)


class R8MonitoringPolicyCodecError(ValueError):
    """A persisted policy owner payload is malformed or noncanonical."""


def _mapping(value: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise R8MonitoringPolicyCodecError(f"{label} must be an exact object")
    payload = cast(dict[str, object], value)
    if frozenset(payload) != keys:
        raise R8MonitoringPolicyCodecError(f"{label} keys differ")
    return payload


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise R8MonitoringPolicyCodecError(f"{label} must be an exact string")
    return value


def _utc_text(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R8MonitoringPolicyCodecError("policy owner clock is invalid")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _clock(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise R8MonitoringPolicyCodecError(f"{label} is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise R8MonitoringPolicyCodecError(f"{label} must be timezone-aware")
    canonical = parsed.astimezone(UTC)
    if text != canonical.isoformat(timespec="microseconds"):
        raise R8MonitoringPolicyCodecError(f"{label} must use canonical UTC text")
    return canonical


_DEFINITION_KEYS = frozenset({"definition_version", "policy", "content_hash"})
_SOURCE_KEYS = frozenset(
    {
        "source_receipt_id",
        "source_receipt_version",
        "source_owner",
        "policy_id",
        "policy_version",
        "definition_hash",
        "available_at",
        "valid_until",
        "evidence_ref",
        "content_hash",
    }
)


def encode_r8_monitoring_policy_definition(
    value: R8MonitoringPolicyDefinition,
) -> dict[str, object]:
    """Encode one exact recursively validated policy definition."""

    try:
        if type(value) is not R8MonitoringPolicyDefinition:
            raise TypeError("R8 monitoring policy definition type differs")
        definition = R8MonitoringPolicyDefinition.validated_copy(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise R8MonitoringPolicyCodecError("policy definition is invalid") from error
    return {
        "definition_version": definition.definition_version,
        "policy": encode_monitoring_policy(definition.policy),
        "content_hash": definition.content_hash,
    }


def decode_r8_monitoring_policy_definition(
    value: object,
) -> R8MonitoringPolicyDefinition:
    """Strictly restore one dedicated policy definition."""

    payload = _mapping(value, _DEFINITION_KEYS, "policy definition")
    try:
        if _text(payload["definition_version"], "definition_version") != POLICY_DEFINITION_VERSION:
            raise ValueError("policy definition version differs")
        definition = R8MonitoringPolicyDefinition.from_policy(
            decode_monitoring_policy(payload["policy"])
        )
        if definition.content_hash != _text(payload["content_hash"], "definition content_hash"):
            raise ValueError("policy definition seal differs")
        return definition
    except (AttributeError, TypeError, ValueError) as error:
        raise R8MonitoringPolicyCodecError("policy definition validation failed") from error


def encode_r8_monitoring_policy_source_receipt(
    value: R8MonitoringPolicySourceReceipt,
) -> dict[str, object]:
    """Encode one exact Research policy source receipt."""

    try:
        if type(value) is not R8MonitoringPolicySourceReceipt:
            raise TypeError("R8 monitoring policy source type differs")
        source = R8MonitoringPolicySourceReceipt.validated_copy(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise R8MonitoringPolicyCodecError("policy source receipt is invalid") from error
    return {
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_owner": source.source_owner,
        "policy_id": source.policy_id,
        "policy_version": source.policy_version,
        "definition_hash": source.definition_hash,
        "available_at": _utc_text(source.available_at),
        "valid_until": _utc_text(source.valid_until),
        "evidence_ref": source.evidence_ref,
        "content_hash": source.content_hash,
    }


def decode_r8_monitoring_policy_source_receipt(
    value: object,
) -> R8MonitoringPolicySourceReceipt:
    """Strictly restore one Research policy source receipt."""

    payload = _mapping(value, _SOURCE_KEYS, "policy source receipt")
    try:
        source = R8MonitoringPolicySourceReceipt.create(
            source_receipt_id=_text(payload["source_receipt_id"], "source_receipt_id"),
            source_receipt_version=_text(
                payload["source_receipt_version"], "source_receipt_version"
            ),
            policy_id=_text(payload["policy_id"], "policy_id"),
            policy_version=_text(payload["policy_version"], "policy_version"),
            definition_hash=_text(payload["definition_hash"], "definition_hash"),
            available_at=_clock(payload["available_at"], "available_at"),
            valid_until=_clock(payload["valid_until"], "valid_until"),
            evidence_ref=_text(payload["evidence_ref"], "evidence_ref"),
        )
        if source.source_owner != _text(payload["source_owner"], "source_owner"):
            raise ValueError("policy source owner differs")
        if source.content_hash != _text(payload["content_hash"], "source content_hash"):
            raise ValueError("policy source seal differs")
        return source
    except (AttributeError, TypeError, ValueError) as error:
        raise R8MonitoringPolicyCodecError("policy source validation failed") from error


__all__ = [
    "R8MonitoringPolicyCodecError",
    "decode_r8_monitoring_policy_definition",
    "decode_r8_monitoring_policy_source_receipt",
    "encode_r8_monitoring_policy_definition",
    "encode_r8_monitoring_policy_source_receipt",
]
