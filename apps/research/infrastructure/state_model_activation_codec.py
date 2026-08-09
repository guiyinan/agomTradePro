"""Strict canonical codecs for persisted R6 activation authorizations and events."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApprovalRef,
    R6ActivationAuthorization,
    R6ActivationEvent,
    R6ActivationScopeRef,
)

_AUTHORIZATION_SCHEMA = "r6-activation-authorization.v1"
_EVENT_SCHEMA = "r6-activation-event.v1"
_SAFE_KEYS = {
    "research_only",
    "must_not_use_for_decision",
    "must_not_replace_regime",
    "must_not_publish_current",
    "must_not_execute",
}


class R6ActivationCodecError(ValueError):
    """A persisted R6 activation payload is not the exact supported schema."""


def _object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise R6ActivationCodecError(f"{label} must be an object")
    return value


def _keys(value: dict[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise R6ActivationCodecError(f"{label} keys differ from the exact schema")


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise R6ActivationCodecError(f"{label} must be a string")
    return value


def _nullable_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise R6ActivationCodecError(f"{label} must be an integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise R6ActivationCodecError(f"{label} must be a boolean")
    return value


def _datetime(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise R6ActivationCodecError(f"{label} is not an ISO datetime") from error
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.astimezone(UTC).isoformat() != text
    ):
        raise R6ActivationCodecError(f"{label} is non-canonical")
    return parsed


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R6ActivationCodecError("activation datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _strings(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise R6ActivationCodecError(f"{label} must be an array")
    return tuple(_string(item, f"{label} item") for item in value)


def _scope_body(ref: R6ActivationScopeRef) -> dict[str, object]:
    ref.__post_init__()
    return {
        "scope_id": ref.scope_id,
        "scope_version": ref.scope_version,
        "scope_hash": ref.scope_hash,
    }


def _decode_scope(value: object, label: str) -> R6ActivationScopeRef:
    body = _object(value, label)
    _keys(body, {"scope_id", "scope_version", "scope_hash"}, label)
    return R6ActivationScopeRef(
        scope_id=_string(body["scope_id"], f"{label}.scope_id"),
        scope_version=_string(body["scope_version"], f"{label}.scope_version"),
        scope_hash=_string(body["scope_hash"], f"{label}.scope_hash"),
    )


def _approval_body(ref: R6ActivationApprovalRef) -> dict[str, object]:
    ref.__post_init__()
    return {
        "approval_id": ref.approval_id,
        "approval_version": ref.approval_version,
        "approval_hash": ref.approval_hash,
    }


def _decode_approval(value: object, label: str) -> R6ActivationApprovalRef:
    body = _object(value, label)
    _keys(body, {"approval_id", "approval_version", "approval_hash"}, label)
    return R6ActivationApprovalRef(
        approval_id=_string(body["approval_id"], f"{label}.approval_id"),
        approval_version=_string(body["approval_version"], f"{label}.approval_version"),
        approval_hash=_string(body["approval_hash"], f"{label}.approval_hash"),
    )


def _nullable_approval_body(ref: R6ActivationApprovalRef | None) -> object:
    return None if ref is None else _approval_body(ref)


def _decode_nullable_approval(
    value: object,
    label: str,
) -> R6ActivationApprovalRef | None:
    return None if value is None else _decode_approval(value, label)


def _safe_body(value: R6ActivationAuthorization | R6ActivationEvent) -> dict[str, object]:
    return {
        "research_only": value.research_only,
        "must_not_use_for_decision": value.must_not_use_for_decision,
        "must_not_replace_regime": value.must_not_replace_regime,
        "must_not_publish_current": value.must_not_publish_current,
        "must_not_execute": value.must_not_execute,
    }


def encode_r6_activation_authorization(
    authorization: R6ActivationAuthorization,
) -> dict[str, object]:
    """Encode one live-validated authorization using exact v1 keys."""

    authorization.__post_init__()
    return {
        "schema": _AUTHORIZATION_SCHEMA,
        "authorization": {
            "authorization_id": authorization.authorization_id,
            "authorization_version": authorization.authorization_version,
            "event_id": authorization.event_id,
            "event_version": authorization.event_version,
            "scope_ref": _scope_body(authorization.scope_ref),
            "action": authorization.action.value,
            "subject": _approval_body(authorization.subject),
            "rollback_target": _nullable_approval_body(authorization.rollback_target),
            "expected_sequence": authorization.expected_sequence,
            "expected_previous_event_hash": authorization.expected_previous_event_hash,
            "owner": authorization.owner,
            "issued_at": _datetime_text(authorization.issued_at),
            "recorded_at": _datetime_text(authorization.recorded_at),
            "valid_until": _datetime_text(authorization.valid_until),
            "reason_codes": list(authorization.reason_codes),
            "evidence_ref": authorization.evidence_ref,
            **_safe_body(authorization),
            "content_hash": authorization.content_hash,
        },
    }


def decode_r6_activation_authorization(payload: object) -> R6ActivationAuthorization:
    """Decode and reconstruct every authorization field and its live seal."""

    root = _object(payload, "authorization payload")
    _keys(root, {"schema", "authorization"}, "authorization payload")
    if _string(root["schema"], "authorization schema") != _AUTHORIZATION_SCHEMA:
        raise R6ActivationCodecError("authorization schema version is unsupported")
    body = _object(root["authorization"], "authorization")
    expected = {
        "authorization_id",
        "authorization_version",
        "event_id",
        "event_version",
        "scope_ref",
        "action",
        "subject",
        "rollback_target",
        "expected_sequence",
        "expected_previous_event_hash",
        "owner",
        "issued_at",
        "recorded_at",
        "valid_until",
        "reason_codes",
        "evidence_ref",
        "content_hash",
        *_SAFE_KEYS,
    }
    _keys(body, expected, "authorization")
    try:
        action = R6ActivationAction(_string(body["action"], "authorization.action"))
        result = R6ActivationAuthorization(
            authorization_id=_string(body["authorization_id"], "authorization.id"),
            authorization_version=_string(body["authorization_version"], "authorization.version"),
            event_id=_string(body["event_id"], "authorization.event_id"),
            event_version=_string(body["event_version"], "authorization.event_version"),
            scope_ref=_decode_scope(body["scope_ref"], "authorization.scope_ref"),
            action=action,
            subject=_decode_approval(body["subject"], "authorization.subject"),
            rollback_target=_decode_nullable_approval(
                body["rollback_target"], "authorization.rollback_target"
            ),
            expected_sequence=_integer(
                body["expected_sequence"], "authorization.expected_sequence"
            ),
            expected_previous_event_hash=_nullable_string(
                body["expected_previous_event_hash"],
                "authorization.expected_previous_event_hash",
            ),
            owner=_string(body["owner"], "authorization.owner"),
            issued_at=_datetime(body["issued_at"], "authorization.issued_at"),
            recorded_at=_datetime(body["recorded_at"], "authorization.recorded_at"),
            valid_until=_datetime(body["valid_until"], "authorization.valid_until"),
            reason_codes=_strings(body["reason_codes"], "authorization.reason_codes"),
            evidence_ref=_string(body["evidence_ref"], "authorization.evidence_ref"),
            research_only=_boolean(body["research_only"], "authorization.research_only"),
            must_not_use_for_decision=_boolean(
                body["must_not_use_for_decision"],
                "authorization.must_not_use_for_decision",
            ),
            must_not_replace_regime=_boolean(
                body["must_not_replace_regime"], "authorization.must_not_replace_regime"
            ),
            must_not_publish_current=_boolean(
                body["must_not_publish_current"], "authorization.must_not_publish_current"
            ),
            must_not_execute=_boolean(body["must_not_execute"], "authorization.must_not_execute"),
        )
    except (TypeError, ValueError) as error:
        raise R6ActivationCodecError("authorization fields are invalid") from error
    if result.content_hash != _string(body["content_hash"], "authorization.content_hash"):
        raise R6ActivationCodecError("authorization content seal differs")
    return result


def encode_r6_activation_event(event: R6ActivationEvent) -> dict[str, object]:
    """Encode one live-validated activation event using exact v1 keys."""

    event.__post_init__()
    return {
        "schema": _EVENT_SCHEMA,
        "event": {
            "event_id": event.event_id,
            "event_version": event.event_version,
            "scope_ref": _scope_body(event.scope_ref),
            "action": event.action.value,
            "subject": _approval_body(event.subject),
            "rollback_target": _nullable_approval_body(event.rollback_target),
            "authorization_id": event.authorization_id,
            "authorization_version": event.authorization_version,
            "authorization_hash": event.authorization_hash,
            "sequence": event.sequence,
            "occurred_at": _datetime_text(event.occurred_at),
            "recorded_at": _datetime_text(event.recorded_at),
            "previous_event_hash": event.previous_event_hash,
            "reason_codes": list(event.reason_codes),
            **_safe_body(event),
            "content_hash": event.content_hash,
        },
    }


def decode_r6_activation_event(payload: object) -> R6ActivationEvent:
    """Decode and reconstruct every event field and its live seal."""

    root = _object(payload, "event payload")
    _keys(root, {"schema", "event"}, "event payload")
    if _string(root["schema"], "event schema") != _EVENT_SCHEMA:
        raise R6ActivationCodecError("event schema version is unsupported")
    body = _object(root["event"], "event")
    expected = {
        "event_id",
        "event_version",
        "scope_ref",
        "action",
        "subject",
        "rollback_target",
        "authorization_id",
        "authorization_version",
        "authorization_hash",
        "sequence",
        "occurred_at",
        "recorded_at",
        "previous_event_hash",
        "reason_codes",
        "content_hash",
        *_SAFE_KEYS,
    }
    _keys(body, expected, "event")
    try:
        result = R6ActivationEvent(
            event_id=_string(body["event_id"], "event.id"),
            event_version=_string(body["event_version"], "event.version"),
            scope_ref=_decode_scope(body["scope_ref"], "event.scope_ref"),
            action=R6ActivationAction(_string(body["action"], "event.action")),
            subject=_decode_approval(body["subject"], "event.subject"),
            rollback_target=_decode_nullable_approval(
                body["rollback_target"], "event.rollback_target"
            ),
            authorization_id=_string(body["authorization_id"], "event.authorization_id"),
            authorization_version=_string(
                body["authorization_version"], "event.authorization_version"
            ),
            authorization_hash=_string(body["authorization_hash"], "event.authorization_hash"),
            sequence=_integer(body["sequence"], "event.sequence"),
            occurred_at=_datetime(body["occurred_at"], "event.occurred_at"),
            recorded_at=_datetime(body["recorded_at"], "event.recorded_at"),
            previous_event_hash=_nullable_string(
                body["previous_event_hash"], "event.previous_event_hash"
            ),
            reason_codes=_strings(body["reason_codes"], "event.reason_codes"),
            research_only=_boolean(body["research_only"], "event.research_only"),
            must_not_use_for_decision=_boolean(
                body["must_not_use_for_decision"], "event.must_not_use_for_decision"
            ),
            must_not_replace_regime=_boolean(
                body["must_not_replace_regime"], "event.must_not_replace_regime"
            ),
            must_not_publish_current=_boolean(
                body["must_not_publish_current"], "event.must_not_publish_current"
            ),
            must_not_execute=_boolean(body["must_not_execute"], "event.must_not_execute"),
        )
    except (TypeError, ValueError) as error:
        raise R6ActivationCodecError("event fields are invalid") from error
    if result.content_hash != _string(body["content_hash"], "event.content_hash"):
        raise R6ActivationCodecError("event content seal differs")
    return result


__all__ = [
    "R6ActivationCodecError",
    "decode_r6_activation_authorization",
    "decode_r6_activation_event",
    "encode_r6_activation_authorization",
    "encode_r6_activation_event",
]
