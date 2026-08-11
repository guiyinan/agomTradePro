"""Strict canonical codec for the Research R2 trial-policy registry."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.research.domain.r2_market_structure_trial_policy_registry import (
    PersistedR2MarketStructureTrialPolicy,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_codec import (
    R2TrialMonitoringCodecError,
    decode_r2_trial_policy,
    encode_r2_trial_policy,
)


class R2TrialPolicyRegistryCodecError(ValueError):
    """Stored policy record is malformed, noncanonical, or live-tampered."""


def encode_r2_trial_policy_record(
    record: PersistedR2MarketStructureTrialPolicy,
) -> dict[str, object]:
    """Encode the complete policy and server-ledger seal without omissions."""

    try:
        if type(record) is not PersistedR2MarketStructureTrialPolicy:
            raise TypeError("R2 trial policy record type differs")
        PersistedR2MarketStructureTrialPolicy.__post_init__(record)
        return {
            "schema": "research-r2-trial-policy-registry.v1",
            "policy": encode_r2_trial_policy(record.policy),
            "ledger_recorded_at": _utc_text(record.ledger_recorded_at),
            "record_hash": record.record_hash,
            "research_only": record.research_only,
            "must_not_publish_current": record.must_not_publish_current,
            "must_not_use_for_decision": record.must_not_use_for_decision,
            "must_not_execute": record.must_not_execute,
        }
    except R2TrialPolicyRegistryCodecError:
        raise
    except (AttributeError, TypeError, ValueError, R2TrialMonitoringCodecError) as error:
        raise R2TrialPolicyRegistryCodecError("invalid R2 trial policy registry record") from error


def decode_r2_trial_policy_record(
    raw: object,
) -> PersistedR2MarketStructureTrialPolicy:
    """Strictly restore and recompute both policy and ledger record seals."""

    try:
        payload = _mapping(
            raw,
            {
                "schema",
                "policy",
                "ledger_recorded_at",
                "record_hash",
                "research_only",
                "must_not_publish_current",
                "must_not_use_for_decision",
                "must_not_execute",
            },
        )
        if payload["schema"] != "research-r2-trial-policy-registry.v1":
            raise ValueError("R2 trial policy registry schema differs")
        record = PersistedR2MarketStructureTrialPolicy.create(
            policy=decode_r2_trial_policy(payload["policy"]),
            ledger_recorded_at=_datetime(payload["ledger_recorded_at"]),
        )
        if (
            record.record_hash != _text(payload["record_hash"], "record_hash")
            or payload["research_only"] is not True
            or payload["must_not_publish_current"] is not True
            or payload["must_not_use_for_decision"] is not True
            or payload["must_not_execute"] is not True
        ):
            raise ValueError("R2 trial policy record seal differs")
        if encode_r2_trial_policy_record(record) != payload:
            raise ValueError("R2 trial policy record is not canonical")
        return record
    except R2TrialPolicyRegistryCodecError:
        raise
    except (AttributeError, TypeError, ValueError, R2TrialMonitoringCodecError) as error:
        raise R2TrialPolicyRegistryCodecError(
            "R2 trial policy registry payload is invalid"
        ) from error


def _mapping(value: object, expected_keys: set[str]) -> dict[str, object]:
    if type(value) is not dict:
        raise R2TrialPolicyRegistryCodecError("registry payload must be an object")
    result = cast(dict[str, object], value)
    if set(result) != expected_keys:
        raise R2TrialPolicyRegistryCodecError("registry payload keys differ")
    return result


def _text(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise R2TrialPolicyRegistryCodecError(f"{field_name} must be a string")
    return value


def _datetime(value: object) -> datetime:
    text = _text(value, "ledger_recorded_at")
    try:
        result = datetime.fromisoformat(text)
    except ValueError as error:
        raise R2TrialPolicyRegistryCodecError(
            "ledger_recorded_at must be an ISO datetime"
        ) from error
    if result.tzinfo is None or result.utcoffset() is None or _utc_text(result) != text:
        raise R2TrialPolicyRegistryCodecError(
            "ledger_recorded_at must be canonical and timezone-aware"
        )
    return result


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R2TrialPolicyRegistryCodecError("ledger_recorded_at must be timezone-aware")
    return value.astimezone(UTC).isoformat()


__all__ = [
    "R2TrialPolicyRegistryCodecError",
    "decode_r2_trial_policy_record",
    "encode_r2_trial_policy_record",
]
