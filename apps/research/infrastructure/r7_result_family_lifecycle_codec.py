"""Strict source-graph codecs for persisted R7 family lifecycle evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from apps.research.application.r7_result_family_lifecycle import (
    R7FamilyOwnerSourceGraph,
)
from apps.research.domain.r7_research_result_lifecycle import R7ResearchResultRef
from apps.research.domain.r7_result_family_lifecycle import (
    R7FamilyLifecycleAction,
    R7FamilyLifecycleAuthorization,
    R7FamilyLifecycleEvent,
    R7FamilyResultOwnerEvidence,
    R7LocalLifecycleStreamAttestation,
    R7ResultFamilyIdentity,
    create_r7_family_lifecycle_event,
)
from apps.research.infrastructure.r7_research_result_codec import (
    R7ResearchResultCodecError,
    decode_persisted_r7_research_result,
    encode_persisted_r7_research_result,
)
from apps.research.infrastructure.r7_research_result_lifecycle_codec import (
    R7ResultLifecycleCodecError,
    decode_r7_result_lifecycle_event,
    encode_r7_result_lifecycle_event,
)

_AUTHORIZATION_SCHEMA = "r7-family-lifecycle-authorization-payload.v1"
_EVENT_SCHEMA = "r7-family-lifecycle-event-source-graph.v1"
_OWNER_SOURCE_SCHEMA = "r7-family-result-owner-source-graph.v1"
_SAFETY_KEYS = {
    "research_only",
    "publishes_model_probability",
    "publishes_probability_current",
    "produces_decision",
    "executes_orders",
    "must_not_use_for_decision",
    "must_not_execute",
}


class R7FamilyLifecycleCodecError(ValueError):
    """A persisted R7 family payload is malformed or non-canonical."""


def encode_r7_family_lifecycle_authorization(
    authorization: R7FamilyLifecycleAuthorization,
) -> dict[str, object]:
    """Encode one exact owner authorization into canonical JSON values."""

    if type(authorization) is not R7FamilyLifecycleAuthorization:
        raise R7FamilyLifecycleCodecError("authorization type is invalid")
    authorization.__post_init__()
    return {
        "schema": _AUTHORIZATION_SCHEMA,
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "family": _encode_family(authorization.family),
        "event_id": authorization.event_id,
        "event_version": authorization.event_version,
        "action": authorization.action.value,
        "subject_ref": _encode_result_ref(authorization.subject_ref),
        "subject_owner_attestation_hash": authorization.subject_owner_attestation_hash,
        "rollback_target_ref": (
            None
            if authorization.rollback_target_ref is None
            else _encode_result_ref(authorization.rollback_target_ref)
        ),
        "rollback_target_owner_attestation_hash": (
            authorization.rollback_target_owner_attestation_hash
        ),
        "expected_sequence": authorization.expected_sequence,
        "expected_previous_event_id": authorization.expected_previous_event_id,
        "expected_previous_event_version": authorization.expected_previous_event_version,
        "expected_previous_event_hash": authorization.expected_previous_event_hash,
        "owner": authorization.owner,
        "issued_at": _encode_datetime(authorization.issued_at),
        "recorded_at": _encode_datetime(authorization.recorded_at),
        "valid_until": _encode_datetime(authorization.valid_until),
        "reason_codes": list(authorization.reason_codes),
        "evidence_ref": authorization.evidence_ref,
        **_encode_safety(authorization),
        "content_hash": authorization.content_hash,
    }


def decode_r7_family_lifecycle_authorization(
    payload: object,
) -> R7FamilyLifecycleAuthorization:
    """Restore one authorization through its validated Domain factory."""

    try:
        value = _mapping(payload, "authorization")
        _keys(
            value,
            {
                "schema",
                "authorization_id",
                "authorization_version",
                "family",
                "event_id",
                "event_version",
                "action",
                "subject_ref",
                "subject_owner_attestation_hash",
                "rollback_target_ref",
                "rollback_target_owner_attestation_hash",
                "expected_sequence",
                "expected_previous_event_id",
                "expected_previous_event_version",
                "expected_previous_event_hash",
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
        if _string(value, "schema") != _AUTHORIZATION_SCHEMA:
            raise ValueError("authorization schema is unsupported")
        target_payload = value["rollback_target_ref"]
        target = None if target_payload is None else _decode_result_ref(target_payload)
        authorization = R7FamilyLifecycleAuthorization.create(
            authorization_id=_string(value, "authorization_id"),
            authorization_version=_string(value, "authorization_version"),
            family=_decode_family(value["family"]),
            event_id=_string(value, "event_id"),
            event_version=_string(value, "event_version"),
            action=R7FamilyLifecycleAction(_string(value, "action")),
            subject_ref=_decode_result_ref(value["subject_ref"]),
            subject_owner_attestation_hash=_string(value, "subject_owner_attestation_hash"),
            rollback_target_ref=target,
            rollback_target_owner_attestation_hash=_optional_string(
                value, "rollback_target_owner_attestation_hash"
            ),
            expected_sequence=_integer(value, "expected_sequence"),
            expected_previous_event_id=_optional_string(value, "expected_previous_event_id"),
            expected_previous_event_version=_optional_string(
                value, "expected_previous_event_version"
            ),
            expected_previous_event_hash=_optional_string(value, "expected_previous_event_hash"),
            owner=_string(value, "owner"),
            issued_at=_datetime(value, "issued_at"),
            recorded_at=_datetime(value, "recorded_at"),
            valid_until=_datetime(value, "valid_until"),
            reason_codes=_strings(value, "reason_codes"),
            evidence_ref=_string(value, "evidence_ref"),
        )
        _require_safety(value, authorization)
        if authorization.content_hash != _string(value, "content_hash"):
            raise ValueError("authorization content_hash mismatch")
        if encode_r7_family_lifecycle_authorization(authorization) != dict(value):
            raise ValueError("authorization payload is non-canonical")
        return authorization
    except R7FamilyLifecycleCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise R7FamilyLifecycleCodecError("authorization payload is invalid") from error


def encode_r7_family_lifecycle_event(
    event: R7FamilyLifecycleEvent,
    *,
    subject_source: R7FamilyOwnerSourceGraph,
    rollback_target_source: R7FamilyOwnerSourceGraph | None,
) -> dict[str, object]:
    """Encode an event with the complete owner source graphs used to derive it."""

    if type(event) is not R7FamilyLifecycleEvent:
        raise R7FamilyLifecycleCodecError("event type is invalid")
    event.validate_live()
    subject_source.__post_init__()
    if subject_source.evidence != event.subject_evidence:
        raise R7FamilyLifecycleCodecError("event subject source graph differs")
    if rollback_target_source is not None:
        rollback_target_source.__post_init__()
    if (
        None if rollback_target_source is None else rollback_target_source.evidence
    ) != event.rollback_target_evidence:
        raise R7FamilyLifecycleCodecError("event rollback target source graph differs")
    encoded_target_source = (
        None if rollback_target_source is None else _encode_owner_source(rollback_target_source)
    )
    return {
        "schema": _EVENT_SCHEMA,
        "authorization": encode_r7_family_lifecycle_authorization(event.authorization),
        "subject_source": _encode_owner_source(subject_source),
        "rollback_target_source": encoded_target_source,
        "occurred_at": _encode_datetime(event.occurred_at),
        "recorded_at": _encode_datetime(event.recorded_at),
        "previous_event_hash": event.previous_event_hash,
        **_encode_safety(event),
        "content_hash": event.content_hash,
    }


def decode_r7_family_lifecycle_event(
    payload: object,
    *,
    previous_events: tuple[R7FamilyLifecycleEvent, ...],
) -> R7FamilyLifecycleEvent:
    """Rebuild an event from source graphs after replaying its exact prefix."""

    event, _, _ = decode_r7_family_lifecycle_event_source_graph(
        payload,
        previous_events=previous_events,
    )
    return event


def decode_r7_family_lifecycle_event_source_graph(
    payload: object,
    *,
    previous_events: tuple[R7FamilyLifecycleEvent, ...],
) -> tuple[
    R7FamilyLifecycleEvent,
    R7FamilyOwnerSourceGraph,
    R7FamilyOwnerSourceGraph | None,
]:
    """Restore the event and both authoritative owner source graphs."""

    try:
        if type(previous_events) is not tuple or any(
            type(event) is not R7FamilyLifecycleEvent for event in previous_events
        ):
            raise TypeError("previous_events must be an exact event tuple")
        for previous in previous_events:
            previous.validate_live()
        value = _mapping(payload, "event")
        _keys(
            value,
            {
                "schema",
                "authorization",
                "subject_source",
                "rollback_target_source",
                "occurred_at",
                "recorded_at",
                "previous_event_hash",
                "content_hash",
                *_SAFETY_KEYS,
            },
            "event",
        )
        if _string(value, "schema") != _EVENT_SCHEMA:
            raise ValueError("event schema is unsupported")
        authorization = decode_r7_family_lifecycle_authorization(value["authorization"])
        subject_source = _decode_owner_source(value["subject_source"])
        target_payload = value["rollback_target_source"]
        target_source = None if target_payload is None else _decode_owner_source(target_payload)
        event = create_r7_family_lifecycle_event(
            previous_events=previous_events,
            authorization=authorization,
            subject_evidence=subject_source.evidence,
            rollback_target_evidence=(None if target_source is None else target_source.evidence),
            occurred_at=_datetime(value, "occurred_at"),
            recorded_at=_datetime(value, "recorded_at"),
        )
        if event.previous_event_hash != _optional_string(value, "previous_event_hash"):
            raise ValueError("event previous hash mismatch")
        _require_safety(value, event)
        if event.content_hash != _string(value, "content_hash"):
            raise ValueError("event content_hash mismatch")
        if encode_r7_family_lifecycle_event(
            event,
            subject_source=subject_source,
            rollback_target_source=target_source,
        ) != dict(value):
            raise ValueError("event payload is non-canonical")
        return event, subject_source, target_source
    except R7FamilyLifecycleCodecError:
        raise
    except (
        AttributeError,
        KeyError,
        R7ResearchResultCodecError,
        R7ResultLifecycleCodecError,
        TypeError,
        ValueError,
    ) as error:
        raise R7FamilyLifecycleCodecError("event payload is invalid") from error


def _encode_owner_source(source: R7FamilyOwnerSourceGraph) -> dict[str, object]:
    if type(source) is not R7FamilyOwnerSourceGraph:
        raise R7FamilyLifecycleCodecError("owner source graph type is invalid")
    source.__post_init__()
    return _encode_owner_source_graph(
        result=source.result,
        stream=source.local_lifecycle_stream,
        attestation=source.local_lifecycle_attestation,
        evaluated_at=source.evaluated_at,
        content_hash=source.evidence.content_hash,
    )


def encode_r7_family_owner_source_graph(
    *,
    result: object,
    complete_local_lifecycle_stream: object,
    attestation: object,
    evaluated_at: object,
    expected_evidence_hash: object,
) -> dict[str, object]:
    """Encode explicit authoritative sources without accepting a minted projection."""

    return _encode_owner_source_graph(
        result=result,
        stream=complete_local_lifecycle_stream,
        attestation=attestation,
        evaluated_at=evaluated_at,
        content_hash=expected_evidence_hash,
    )


def _encode_owner_source_graph(
    *,
    result: object,
    stream: object,
    attestation: object,
    evaluated_at: object,
    content_hash: object,
) -> dict[str, object]:
    from apps.research.domain.r7_research_result_lifecycle import R7ResultLifecycleEvent
    from apps.research.domain.r7_research_result_persistence import (
        PersistedR7ResearchResult,
    )

    if type(result) is not PersistedR7ResearchResult:
        raise R7FamilyLifecycleCodecError("owner source result type is invalid")
    result.__post_init__()
    if (
        type(stream) is not tuple
        or not stream
        or any(type(event) is not R7ResultLifecycleEvent for event in stream)
    ):
        raise R7FamilyLifecycleCodecError("owner source local stream is invalid")
    if type(attestation) is not R7LocalLifecycleStreamAttestation:
        raise R7FamilyLifecycleCodecError("owner source attestation type is invalid")
    rebuilt = R7FamilyResultOwnerEvidence.from_owner_graph(
        result=result,
        complete_local_lifecycle_stream=stream,
        local_lifecycle_attestation=attestation,
        evaluated_at=_aware_value(evaluated_at, "owner evaluated_at"),
    )
    if type(content_hash) is not str or rebuilt.content_hash != content_hash:
        raise R7FamilyLifecycleCodecError("owner source evidence hash mismatch")
    return {
        "schema": _OWNER_SOURCE_SCHEMA,
        "result": encode_persisted_r7_research_result(result),
        "local_lifecycle_stream": [encode_r7_result_lifecycle_event(event) for event in stream],
        "attestation_id": attestation.attestation_id,
        "attestation_version": attestation.attestation_version,
        "attestation_recorded_at": _encode_datetime(attestation.recorded_at),
        "attestation_hash": attestation.content_hash,
        "evaluated_at": _encode_datetime(rebuilt.evaluated_at),
        "evidence_hash": rebuilt.content_hash,
    }


def _decode_owner_source(payload: object) -> R7FamilyOwnerSourceGraph:
    value = _mapping(payload, "owner source")
    _keys(
        value,
        {
            "schema",
            "result",
            "local_lifecycle_stream",
            "attestation_id",
            "attestation_version",
            "attestation_recorded_at",
            "attestation_hash",
            "evaluated_at",
            "evidence_hash",
        },
        "owner source",
    )
    if _string(value, "schema") != _OWNER_SOURCE_SCHEMA:
        raise ValueError("owner source schema is unsupported")
    result = decode_persisted_r7_research_result(value["result"])
    raw_stream = value["local_lifecycle_stream"]
    if type(raw_stream) is not list or not raw_stream:
        raise TypeError("owner source local stream must be a non-empty list")
    stream = tuple(decode_r7_result_lifecycle_event(item) for item in raw_stream)
    attestation = R7LocalLifecycleStreamAttestation.from_stream(
        attestation_id=_string(value, "attestation_id"),
        attestation_version=_string(value, "attestation_version"),
        complete_local_lifecycle_stream=stream,
        recorded_at=_datetime(value, "attestation_recorded_at"),
    )
    if attestation.content_hash != _string(value, "attestation_hash"):
        raise ValueError("owner source attestation hash mismatch")
    source = R7FamilyOwnerSourceGraph.from_owner_graph(
        result=result,
        local_lifecycle_stream=stream,
        local_lifecycle_attestation=attestation,
        evaluated_at=_datetime(value, "evaluated_at"),
    )
    evidence = source.evidence
    if evidence.content_hash != _string(value, "evidence_hash"):
        raise ValueError("owner source evidence hash mismatch")
    expected = _encode_owner_source_graph(
        result=result,
        stream=stream,
        attestation=attestation,
        evaluated_at=evidence.evaluated_at,
        content_hash=evidence.content_hash,
    )
    if expected != dict(value):
        raise ValueError("owner source payload is non-canonical")
    return source


def _encode_family(family: R7ResultFamilyIdentity) -> dict[str, str]:
    family.__post_init__()
    return {
        "family_id": family.family_id,
        "family_version": family.family_version,
        "policy_id": family.policy_id,
        "policy_version": family.policy_version,
        "policy_record_hash": family.policy_record_hash,
        "scope_content_hash": family.scope_content_hash,
        "content_hash": family.content_hash,
    }


def _decode_family(payload: object) -> R7ResultFamilyIdentity:
    value = _mapping(payload, "family")
    _keys(
        value,
        {
            "family_id",
            "family_version",
            "policy_id",
            "policy_version",
            "policy_record_hash",
            "scope_content_hash",
            "content_hash",
        },
        "family",
    )
    return R7ResultFamilyIdentity(
        family_id=_string(value, "family_id"),
        family_version=_string(value, "family_version"),
        policy_id=_string(value, "policy_id"),
        policy_version=_string(value, "policy_version"),
        policy_record_hash=_string(value, "policy_record_hash"),
        scope_content_hash=_string(value, "scope_content_hash"),
        content_hash=_string(value, "content_hash"),
    )


def _encode_result_ref(value: R7ResearchResultRef) -> dict[str, str]:
    value.__post_init__()
    return {
        "result_id": value.result_id,
        "result_version": value.result_version,
        "content_hash": value.content_hash,
    }


def _decode_result_ref(payload: object) -> R7ResearchResultRef:
    value = _mapping(payload, "result ref")
    _keys(value, {"result_id", "result_version", "content_hash"}, "result ref")
    return R7ResearchResultRef(
        result_id=_string(value, "result_id"),
        result_version=_string(value, "result_version"),
        content_hash=_string(value, "content_hash"),
    )


def _encode_safety(value: object) -> dict[str, bool]:
    return {key: bool(getattr(value, key)) for key in sorted(_SAFETY_KEYS)}


def _require_safety(payload: Mapping[str, object], value: object) -> None:
    for key in _SAFETY_KEYS:
        expected = getattr(value, key)
        if type(payload[key]) is not bool or payload[key] is not expected:
            raise ValueError(f"{key} differs from the fixed safety contract")


def _mapping(payload: object, label: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or any(type(key) is not str for key in payload):
        raise R7FamilyLifecycleCodecError(f"{label} must be an object")
    return payload


def _keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise R7FamilyLifecycleCodecError(f"{label} fields differ from canonical schema")


def _string(value: Mapping[str, object], key: str) -> str:
    result = value[key]
    if type(result) is not str:
        raise TypeError(f"{key} must be a string")
    return result


def _optional_string(value: Mapping[str, object], key: str) -> str | None:
    result = value[key]
    if result is not None and type(result) is not str:
        raise TypeError(f"{key} must be a string or null")
    return result


def _integer(value: Mapping[str, object], key: str) -> int:
    result = value[key]
    if type(result) is not int:
        raise TypeError(f"{key} must be an integer")
    return result


def _strings(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    result = value[key]
    if type(result) is not list or any(type(item) is not str for item in result):
        raise TypeError(f"{key} must be a string list")
    return tuple(result)


def _aware_value(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R7FamilyLifecycleCodecError(f"{label} must be timezone-aware")
    return value


def _encode_datetime(value: datetime) -> str:
    return _aware_value(value, "datetime").isoformat()


def _datetime(value: Mapping[str, object], key: str) -> datetime:
    raw = _string(value, key)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ValueError(f"{key} must be a canonical datetime") from error
    _aware_value(parsed, key)
    if parsed.isoformat() != raw:
        raise ValueError(f"{key} must be a canonical datetime")
    return parsed


__all__ = [
    "R7FamilyLifecycleCodecError",
    "decode_r7_family_lifecycle_authorization",
    "decode_r7_family_lifecycle_event",
    "decode_r7_family_lifecycle_event_source_graph",
    "encode_r7_family_lifecycle_authorization",
    "encode_r7_family_lifecycle_event",
    "encode_r7_family_owner_source_graph",
]
