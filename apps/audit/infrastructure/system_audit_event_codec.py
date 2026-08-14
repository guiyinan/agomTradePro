"""Strict JSON codec for the pure system audit event envelope."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, TypeAlias, cast

from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditSeverity,
    AuditWritePolicy,
    JSONValue,
    SystemAuditEvent,
)

_TOP_KEYS = frozenset(
    {
        "event_id",
        "event_version",
        "schema_version",
        "category",
        "event_type",
        "owner",
        "write_policy",
        "outcome",
        "severity",
        "reason_codes",
        "occurred_at",
        "recorded_at",
        "observed_at",
        "actor",
        "source_app",
        "source_component",
        "source_surface",
        "correlations",
        "resource",
        "dataset_key",
        "provider_key",
        "capability",
        "publication_id",
        "evidence_refs",
        "detail_schema",
        "detail",
        "stream_id",
        "sequence_no",
        "predecessor_hash",
        "idempotency_key",
        "identity_hash",
        "content_hash",
    }
)
_ACTOR_KEYS = frozenset({"actor_type", "actor_id", "actor_display"})
_CORRELATION_KEYS = frozenset(
    {
        "trace_id",
        "request_id",
        "task_id",
        "run_id",
        "ingested_run_id",
        "dataset_key",
        "provider_key",
        "capability",
        "publication_id",
        "evidence_ref",
    }
)
_RESOURCE_KEYS = frozenset({"resource_type", "resource_id", "resource_version"})
_EVIDENCE_KEYS = frozenset(
    {"owner", "artifact_type", "artifact_id", "artifact_version", "content_hash"}
)


def _mapping(value: object, field: str) -> Mapping[str, JSONValue]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object with string keys")
    return cast(Mapping[str, JSONValue], value)


def _exact(value: Mapping[str, JSONValue], keys: frozenset[str], field: str) -> None:
    if frozenset(value) != keys:
        raise ValueError(f"{field} has unknown or missing keys")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _nullable_text(value: object, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    return value


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    return value


def _time(value: object, field: str) -> datetime:
    text = _text(value, field)
    if len(text) != 27 or not text.endswith("Z") or "." not in text:
        raise ValueError(f"{field} must use canonical UTC-Z microseconds")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid UTC timestamp") from exc
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        raise ValueError(f"{field} is not canonical")
    return parsed


def _nullable_time(value: object, field: str) -> datetime | None:
    return None if value is None else _time(value, field)


def encode(event: SystemAuditEvent) -> Mapping[str, JSONValue]:
    """Encode and revalidate an event, rejecting stale/tampered hashes."""

    event.validate_hashes()
    return event.to_payload()


def decode(payload: Mapping[str, JSONValue]) -> SystemAuditEvent:
    """Decode an exact event payload and fail closed on any substitution."""

    value = _mapping(payload, "event")
    _exact(value, _TOP_KEYS, "event")
    actor_value = _mapping(value["actor"], "actor")
    _exact(actor_value, _ACTOR_KEYS, "actor")
    actor = AuditActorRef(
        actor_type=_text(actor_value["actor_type"], "actor.actor_type"),
        actor_id=_text(actor_value["actor_id"], "actor.actor_id"),
        actor_display=_nullable_text(actor_value["actor_display"], "actor.actor_display"),
    )
    correlation_value = _mapping(value["correlations"], "correlations")
    _exact(correlation_value, _CORRELATION_KEYS, "correlations")
    correlations = AuditCorrelations(
        **{
            key: _nullable_text(correlation_value[key], f"correlations.{key}")
            for key in _CORRELATION_KEYS
        }
    )
    resource_value = value["resource"]
    resource = None
    if resource_value is not None:
        resource_map = _mapping(resource_value, "resource")
        _exact(resource_map, _RESOURCE_KEYS, "resource")
        resource = AuditResourceRef(
            resource_type=_text(resource_map["resource_type"], "resource.resource_type"),
            resource_id=_text(resource_map["resource_id"], "resource.resource_id"),
            resource_version=_nullable_text(
                resource_map["resource_version"], "resource.resource_version"
            ),
        )
    reasons = value["reason_codes"]
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise ValueError("reason_codes must be a JSON string array")
    evidence_value = value["evidence_refs"]
    if not isinstance(evidence_value, list):
        raise ValueError("evidence_refs must be a JSON array")
    evidence_refs: list[AuditEvidenceRef] = []
    for index, item in enumerate(evidence_value):
        evidence_map = _mapping(item, f"evidence_refs[{index}]")
        _exact(evidence_map, _EVIDENCE_KEYS, f"evidence_refs[{index}]")
        evidence_refs.append(
            AuditEvidenceRef(
                owner=_text(evidence_map["owner"], "evidence.owner"),
                artifact_type=_text(evidence_map["artifact_type"], "evidence.artifact_type"),
                artifact_id=_text(evidence_map["artifact_id"], "evidence.artifact_id"),
                artifact_version=_text(
                    evidence_map["artifact_version"], "evidence.artifact_version"
                ),
                content_hash=_text(evidence_map["content_hash"], "evidence.content_hash"),
            )
        )
    detail = _mapping(value["detail"], "detail")
    event = SystemAuditEvent(
        event_id=_text(value["event_id"], "event_id"),
        event_version=_text(value["event_version"], "event_version"),
        schema_version=_text(value["schema_version"], "schema_version"),
        category=AuditCategory(_text(value["category"], "category")),
        event_type=_text(value["event_type"], "event_type"),
        owner=_text(value["owner"], "owner"),
        write_policy=AuditWritePolicy(_text(value["write_policy"], "write_policy")),
        outcome=AuditOutcome(_text(value["outcome"], "outcome")),
        severity=AuditSeverity(_text(value["severity"], "severity")),
        reason_codes=tuple(cast(list[str], reasons)),
        occurred_at=_time(value["occurred_at"], "occurred_at"),
        recorded_at=_time(value["recorded_at"], "recorded_at"),
        observed_at=_nullable_time(value["observed_at"], "observed_at"),
        actor=actor,
        source_app=_text(value["source_app"], "source_app"),
        source_component=_text(value["source_component"], "source_component"),
        source_surface=_text(value["source_surface"], "source_surface"),
        correlations=correlations,
        resource=resource,
        dataset_key=_nullable_text(value["dataset_key"], "dataset_key"),
        provider_key=_nullable_text(value["provider_key"], "provider_key"),
        capability=_nullable_text(value["capability"], "capability"),
        publication_id=_nullable_text(value["publication_id"], "publication_id"),
        evidence_refs=tuple(evidence_refs),
        detail_schema=_text(value["detail_schema"], "detail_schema"),
        detail=detail,
        stream_id=_text(value["stream_id"], "stream_id"),
        sequence_no=_integer(value["sequence_no"], "sequence_no"),
        predecessor_hash=_nullable_text(value["predecessor_hash"], "predecessor_hash"),
        idempotency_key=_text(value["idempotency_key"], "idempotency_key"),
        identity_hash=_text(value["identity_hash"], "identity_hash"),
        content_hash=_text(value["content_hash"], "content_hash"),
    )
    event.validate_hashes()
    if encode(event) != value:
        raise ValueError("event is not canonical")
    return event
