"""Strict canonical payload codecs for R7 result lifecycle ledgers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import NoReturn

from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleAction,
    R7ResultLifecycleEvent,
    R7ResultPromotionAuthorization,
)

_AUTHORIZATION_SCHEMA = "r7-result-promotion-authorization-payload.v1"
_EVENT_SCHEMA = "r7-result-lifecycle-event-payload.v1"
_SAFETY_KEYS = {
    "research_only",
    "promotes_internal_research_record_only",
    "publishes_model_probability",
    "produces_decision",
    "executes_orders",
    "must_not_use_for_decision",
    "must_not_execute",
}


class R7ResultLifecycleCodecError(ValueError):
    """A lifecycle payload is relaxed, malformed, unknown, or tampered."""


def encode_r7_result_lifecycle_authorization(
    authorization: R7ResultPromotionAuthorization,
) -> dict[str, object]:
    """Encode one exact owner authorization as a JSON-compatible mapping."""

    return {
        "schema": _AUTHORIZATION_SCHEMA,
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "result_ref": _encode_result_ref(authorization.result_ref),
        "event_id": authorization.event_id,
        "event_version": authorization.event_version,
        "action": authorization.action.value,
        "expected_sequence": authorization.expected_sequence,
        "owner": authorization.owner,
        "issued_at": authorization.issued_at.isoformat(),
        "recorded_at": authorization.recorded_at.isoformat(),
        "valid_until": authorization.valid_until.isoformat(),
        "reason_codes": list(authorization.reason_codes),
        "evidence_ref": authorization.evidence_ref,
        **_encode_safety(authorization),
        "content_hash": authorization.content_hash,
    }


def decode_r7_result_lifecycle_authorization(
    payload: object,
) -> R7ResultPromotionAuthorization:
    """Strictly restore one exact owner authorization and verify its seal."""

    mapping = _mapping(payload, "authorization")
    _expect_keys(
        mapping,
        {
            "schema",
            "authorization_id",
            "authorization_version",
            "result_ref",
            "event_id",
            "event_version",
            "action",
            "expected_sequence",
            "owner",
            "issued_at",
            "recorded_at",
            "valid_until",
            "reason_codes",
            "evidence_ref",
            "content_hash",
            *_SAFETY_KEYS,
        },
        "authorization",
    )
    if _string(mapping, "schema") != _AUTHORIZATION_SCHEMA:
        _fail("authorization schema is unsupported")
    try:
        authorization = R7ResultPromotionAuthorization(
            authorization_id=_string(mapping, "authorization_id"),
            authorization_version=_string(mapping, "authorization_version"),
            result_ref=_decode_result_ref(mapping["result_ref"]),
            event_id=_string(mapping, "event_id"),
            event_version=_string(mapping, "event_version"),
            action=R7ResultLifecycleAction(_string(mapping, "action")),
            expected_sequence=_integer(mapping, "expected_sequence"),
            owner=_string(mapping, "owner"),
            issued_at=_datetime(mapping, "issued_at"),
            recorded_at=_datetime(mapping, "recorded_at"),
            valid_until=_datetime(mapping, "valid_until"),
            reason_codes=_strings(mapping, "reason_codes"),
            evidence_ref=_string(mapping, "evidence_ref"),
            **_decode_safety(mapping),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise R7ResultLifecycleCodecError("authorization payload is invalid") from error
    if authorization.content_hash != _string(mapping, "content_hash"):
        _fail("authorization content_hash mismatch")
    return authorization


def encode_r7_result_lifecycle_event(
    event: R7ResultLifecycleEvent,
) -> dict[str, object]:
    """Encode one immutable lifecycle event as a JSON-compatible mapping."""

    return {
        "schema": _EVENT_SCHEMA,
        "event_id": event.event_id,
        "event_version": event.event_version,
        "result_ref": _encode_result_ref(event.result_ref),
        "authorization_id": event.authorization_id,
        "authorization_version": event.authorization_version,
        "authorization_hash": event.authorization_hash,
        "action": event.action.value,
        "sequence": event.sequence,
        "occurred_at": event.occurred_at.isoformat(),
        "recorded_at": event.recorded_at.isoformat(),
        "previous_event_hash": event.previous_event_hash,
        "reason_codes": list(event.reason_codes),
        **_encode_safety(event),
        "content_hash": event.content_hash,
    }


def decode_r7_result_lifecycle_event(payload: object) -> R7ResultLifecycleEvent:
    """Strictly restore one immutable lifecycle event and verify its seal."""

    mapping = _mapping(payload, "event")
    _expect_keys(
        mapping,
        {
            "schema",
            "event_id",
            "event_version",
            "result_ref",
            "authorization_id",
            "authorization_version",
            "authorization_hash",
            "action",
            "sequence",
            "occurred_at",
            "recorded_at",
            "previous_event_hash",
            "reason_codes",
            "content_hash",
            *_SAFETY_KEYS,
        },
        "event",
    )
    if _string(mapping, "schema") != _EVENT_SCHEMA:
        _fail("event schema is unsupported")
    previous_hash = mapping["previous_event_hash"]
    if previous_hash is not None and not isinstance(previous_hash, str):
        _fail("event previous_event_hash must be a string or null")
    try:
        event = R7ResultLifecycleEvent(
            event_id=_string(mapping, "event_id"),
            event_version=_string(mapping, "event_version"),
            result_ref=_decode_result_ref(mapping["result_ref"]),
            authorization_id=_string(mapping, "authorization_id"),
            authorization_version=_string(mapping, "authorization_version"),
            authorization_hash=_string(mapping, "authorization_hash"),
            action=R7ResultLifecycleAction(_string(mapping, "action")),
            sequence=_integer(mapping, "sequence"),
            occurred_at=_datetime(mapping, "occurred_at"),
            recorded_at=_datetime(mapping, "recorded_at"),
            previous_event_hash=previous_hash,
            reason_codes=_strings(mapping, "reason_codes"),
            **_decode_safety(mapping),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise R7ResultLifecycleCodecError("event payload is invalid") from error
    if event.content_hash != _string(mapping, "content_hash"):
        _fail("event content_hash mismatch")
    return event


def _encode_result_ref(result_ref: R7ResearchResultRef) -> dict[str, str]:
    return {
        "result_id": result_ref.result_id,
        "result_version": result_ref.result_version,
        "content_hash": result_ref.content_hash,
    }


def _decode_result_ref(payload: object) -> R7ResearchResultRef:
    mapping = _mapping(payload, "result_ref")
    _expect_keys(
        mapping,
        {"result_id", "result_version", "content_hash"},
        "result_ref",
    )
    return R7ResearchResultRef(
        result_id=_string(mapping, "result_id"),
        result_version=_string(mapping, "result_version"),
        content_hash=_string(mapping, "content_hash"),
    )


def _encode_safety(
    item: R7ResultPromotionAuthorization | R7ResultLifecycleEvent,
) -> dict[str, bool]:
    return {
        "research_only": item.research_only,
        "promotes_internal_research_record_only": item.promotes_internal_research_record_only,
        "publishes_model_probability": item.publishes_model_probability,
        "produces_decision": item.produces_decision,
        "executes_orders": item.executes_orders,
        "must_not_use_for_decision": item.must_not_use_for_decision,
        "must_not_execute": item.must_not_execute,
    }


def _decode_safety(mapping: Mapping[str, object]) -> dict[str, bool]:
    return {key: _boolean(mapping, key) for key in _SAFETY_KEYS}


def _mapping(payload: object, label: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
        _fail(f"{label} must be a string-keyed mapping")
    return payload


def _expect_keys(
    mapping: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    if set(mapping) != expected:
        _fail(f"{label} fields differ from the canonical schema")


def _string(mapping: Mapping[str, object], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str):
        _fail(f"{key} must be a string")
    return value


def _integer(mapping: Mapping[str, object], key: str) -> int:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{key} must be an integer")
    return value


def _boolean(mapping: Mapping[str, object], key: str) -> bool:
    value = mapping[key]
    if not isinstance(value, bool):
        _fail(f"{key} must be a boolean")
    return value


def _datetime(mapping: Mapping[str, object], key: str) -> datetime:
    raw = _string(mapping, key)
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise R7ResultLifecycleCodecError(f"{key} is not an ISO datetime") from error
    if value.tzinfo is None or value.utcoffset() is None or value.isoformat() != raw:
        _fail(f"{key} must be a canonical timezone-aware datetime")
    return value


def _strings(mapping: Mapping[str, object], key: str) -> tuple[str, ...]:
    raw = mapping[key]
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        _fail(f"{key} must be a list of strings")
    return tuple(raw)


def _fail(message: str) -> NoReturn:
    raise R7ResultLifecycleCodecError(message)


__all__ = [
    "R7ResultLifecycleCodecError",
    "decode_r7_result_lifecycle_authorization",
    "decode_r7_result_lifecycle_event",
    "encode_r7_result_lifecycle_authorization",
    "encode_r7_result_lifecycle_event",
]
