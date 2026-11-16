"""Strict codec for C2 configuration rows and local Owner lifecycle events.

This module is a pure value codec. It does not read Django rows, authenticate
an Owner, verify source bytes, or prove any production qualification.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from typing import TypeAlias
from uuid import UUID

from apps.data_center.domain.financial_availability_governance import (
    ExchangeSessionOpeningRuleProposal,
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventAction,
    FinancialAvailabilityOwnerEventIdentity,
    FinancialAvailabilityRecordKind,
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningPhase,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialDisclosureAvailabilityPolicy,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
)

JsonObject: TypeAlias = dict[str, object]
_RECORD_SCHEMA = "data_center.financial-availability-record.v1"
_EVENT_SCHEMA = "data_center.financial-availability-owner-event.v1"


def _object(value: object, name: str) -> JsonObject:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _exact_keys(value: JsonObject, keys: frozenset[str], name: str) -> None:
    if frozenset(value) != keys:
        raise ValueError(f"{name} keys are invalid")


def _string(value: object, name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{name} must be text")
    return value


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _uuid(value: object, name: str) -> UUID:
    if type(value) is not str:
        raise ValueError(f"{name} must be a UUID string")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{name} must be a UUID string") from error
    if str(parsed) != value:
        raise ValueError(f"{name} must use canonical lowercase UUID form")
    return parsed


def _date(value: object, name: str) -> date:
    if type(value) is not str:
        raise ValueError(f"{name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO date") from error
    if type(parsed) is not date or parsed.isoformat() != value:
        raise ValueError(f"{name} must use canonical ISO date form")
    return parsed


def _datetime(value: object, name: str) -> datetime:
    if type(value) is not str:
        raise ValueError(f"{name} must be a canonical UTC datetime")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a canonical UTC datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be aware")
    try:
        normalized = parsed.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} is outside UTC range") from error
    offset = normalized.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{name} must be UTC")
    canonical_forms = {
        normalized.isoformat(),
        normalized.isoformat(timespec="microseconds"),
    }
    if value not in canonical_forms:
        raise ValueError(f"{name} must use canonical UTC ISO form")
    return normalized


def _date_evidence(value: object, name: str) -> StatutorySourceDateEvidence:
    data = _object(value, name)
    _exact_keys(data, frozenset({"precision", "date_value", "instant_value"}), name)
    try:
        precision = StatutorySourceDatePrecision(_string(data["precision"], f"{name}.precision"))
    except ValueError as error:
        raise ValueError(f"{name}.precision is unknown") from error
    date_text = _optional_string(data["date_value"], f"{name}.date_value")
    instant_text = _optional_string(data["instant_value"], f"{name}.instant_value")
    result = StatutorySourceDateEvidence(
        precision=precision,
        date_value=_date(date_text, f"{name}.date_value") if date_text is not None else None,
        instant_value=(
            _datetime(instant_text, f"{name}.instant_value") if instant_text is not None else None
        ),
    )
    result.__post_init__()
    return result


def _source_reference(value: object) -> StatutorySourceCaptureReference:
    data = _object(value, "source")
    expected = frozenset(
        {
            "issuer",
            "document_id",
            "source_version",
            "title",
            "legal_number",
            "source_revision_sha256",
            "capture_id",
            "capture_content_type",
            "body_reference",
            "canonical_url",
            "body_sha256",
            "body_size_bytes",
            "publication_date",
            "source_effective_date",
            "first_seen_at",
            "capture_observed_at",
            "revision_recorded_at",
            "capture_recorded_at",
        }
    )
    _exact_keys(data, expected, "source")
    result = StatutorySourceCaptureReference(
        issuer=_string(data["issuer"], "source.issuer"),
        document_id=_string(data["document_id"], "source.document_id"),
        source_version=_string(data["source_version"], "source.source_version"),
        title=_string(data["title"], "source.title"),
        legal_number=_string(data["legal_number"], "source.legal_number"),
        source_revision_sha256=_string(
            data["source_revision_sha256"], "source.source_revision_sha256"
        ),
        capture_id=_uuid(data["capture_id"], "source.capture_id"),
        capture_content_type=_string(data["capture_content_type"], "source.capture_content_type"),
        body_reference=_string(data["body_reference"], "source.body_reference"),
        canonical_url=_string(data["canonical_url"], "source.canonical_url"),
        body_sha256=_string(data["body_sha256"], "source.body_sha256"),
        body_size_bytes=_integer(data["body_size_bytes"], "source.body_size_bytes"),
        publication_date=_date_evidence(data["publication_date"], "source.publication_date"),
        source_effective_date=_date_evidence(
            data["source_effective_date"], "source.source_effective_date"
        ),
        first_seen_at=_datetime(data["first_seen_at"], "source.first_seen_at"),
        capture_observed_at=_datetime(data["capture_observed_at"], "source.capture_observed_at"),
        revision_recorded_at=_datetime(data["revision_recorded_at"], "source.revision_recorded_at"),
        capture_recorded_at=_datetime(data["capture_recorded_at"], "source.capture_recorded_at"),
    )
    result.__post_init__()
    return result


def _opening_rule(value: object) -> ExchangeSessionOpeningRuleProposal:
    data = _object(value, "content")
    expected = frozenset(
        {
            "schema",
            "exchange",
            "phase",
            "rule_version",
            "source_uri",
            "source_body_sha256",
            "effective_start",
            "effective_end",
            "timezone_name",
            "local_open_time",
            "first_seen_at",
            "source_recorded_at",
        }
    )
    _exact_keys(data, expected, "opening_rule proposal")
    if data["schema"] != "data_center.exchange-session-opening-rule-proposal.v1":
        raise ValueError("opening_rule proposal schema is unknown")
    try:
        phase = ExchangeSessionOpeningPhase(_string(data["phase"], "content.phase"))
    except ValueError as error:
        raise ValueError("content.phase is unknown") from error
    local_time_text = _string(data["local_open_time"], "content.local_open_time")
    try:
        local_open_time = time.fromisoformat(local_time_text)
    except ValueError as error:
        raise ValueError("content.local_open_time is invalid") from error
    if local_open_time.isoformat() != local_time_text:
        raise ValueError("content.local_open_time must use canonical ISO form")
    result = ExchangeSessionOpeningRuleProposal(
        exchange=_string(data["exchange"], "content.exchange"),
        phase=phase,
        rule_version=_string(data["rule_version"], "content.rule_version"),
        source_uri=_string(data["source_uri"], "content.source_uri"),
        source_body_sha256=_string(data["source_body_sha256"], "content.source_body_sha256"),
        effective_start=_date(data["effective_start"], "content.effective_start"),
        effective_end=_date(data["effective_end"], "content.effective_end"),
        timezone_name=_string(data["timezone_name"], "content.timezone_name"),
        local_open_time=local_open_time,
        first_seen_at=_datetime(data["first_seen_at"], "content.first_seen_at"),
        source_recorded_at=_datetime(data["source_recorded_at"], "content.source_recorded_at"),
    )
    result.__post_init__()
    return result


def _policy(value: object) -> FinancialDisclosureAvailabilityPolicy:
    data = _object(value, "content")
    expected = frozenset(
        {
            "policy_id",
            "policy_version",
            "exchange",
            "opening_phase",
            "effective_start",
            "effective_end",
            "calendar_response_max_age_seconds",
            "first_seen_at",
            "recorded_at",
            "policy_sha256",
        }
    )
    _exact_keys(data, expected, "disclosure policy")
    try:
        phase = ExchangeSessionOpeningPhase(_string(data["opening_phase"], "content.opening_phase"))
    except ValueError as error:
        raise ValueError("content.opening_phase is unknown") from error
    result = FinancialDisclosureAvailabilityPolicy.create(
        policy_id=_string(data["policy_id"], "content.policy_id"),
        policy_version=_string(data["policy_version"], "content.policy_version"),
        exchange=_string(data["exchange"], "content.exchange"),
        opening_phase=phase,
        effective_start=_date(data["effective_start"], "content.effective_start"),
        effective_end=_date(data["effective_end"], "content.effective_end"),
        calendar_response_max_age_seconds=_integer(
            data["calendar_response_max_age_seconds"],
            "content.calendar_response_max_age_seconds",
        ),
        first_seen_at=_datetime(data["first_seen_at"], "content.first_seen_at"),
        recorded_at=_datetime(data["recorded_at"], "content.recorded_at"),
    )
    if result.policy_sha256 != _string(data["policy_sha256"], "content.policy_sha256"):
        raise ValueError("disclosure policy hash differs from exact content")
    return result


def serialize_financial_availability_record(
    record: FinancialAvailabilityGovernanceRecord,
) -> bytes:
    """Serialize one strict config row and its separate row digest."""

    record.__post_init__()
    payload: JsonObject = {**record.to_payload(), "content_sha256": record.content_sha256}
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def deserialize_financial_availability_record(
    raw: bytes,
) -> FinancialAvailabilityGovernanceRecord:
    """Strictly decode and rehash one complete config row."""

    if type(raw) is not bytes or not raw or len(raw) > 131072:
        raise ValueError("record bytes must be bounded non-empty bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("record bytes are not strict UTF-8 JSON") from error
    data = _object(value, "record")
    expected = frozenset(
        {
            "schema",
            "record_id",
            "record_version",
            "exchange",
            "kind",
            "recorded_at",
            "content",
            "source",
            "content_sha256",
        }
    )
    _exact_keys(data, expected, "record")
    if data["schema"] != _RECORD_SCHEMA:
        raise ValueError("record schema is unknown")
    try:
        kind = FinancialAvailabilityRecordKind(_string(data["kind"], "record.kind"))
    except ValueError as error:
        raise ValueError("record.kind is unknown") from error
    source = _source_reference(data["source"]) if data["source"] is not None else None
    content = (
        _opening_rule(data["content"])
        if kind is FinancialAvailabilityRecordKind.OPENING_RULE
        else _policy(data["content"])
    )
    record = FinancialAvailabilityGovernanceRecord(
        record_id=_string(data["record_id"], "record.record_id"),
        record_version=_string(data["record_version"], "record.record_version"),
        exchange=_string(data["exchange"], "record.exchange"),
        kind=kind,
        content=content,
        recorded_at=_datetime(data["recorded_at"], "record.recorded_at"),
        source=source,
    )
    if record.content_sha256 != _string(data["content_sha256"], "record.content_sha256"):
        raise ValueError("record hash differs from exact row and source identity")
    return record


def serialize_financial_availability_owner_event(
    event: FinancialAvailabilityOwnerEventIdentity,
) -> bytes:
    """Serialize one local Owner event without implying SystemAudit authority."""

    event.__post_init__()
    payload: JsonObject = {
        "schema": _EVENT_SCHEMA,
        "action": event.action.value,
        "event_id": str(event.event_id),
        "event_sha256": event.event_sha256,
        "record_id": event.record_id,
        "record_version": event.record_version,
        "record_content_sha256": event.record_content_sha256,
        "resulting_content_sha256": event.resulting_content_sha256,
        "actor_user_id": event.actor_user_id,
        "permission_id": event.permission_id,
        "permission_app_label": event.permission_app_label,
        "permission_codename": event.permission_codename,
        "permission_verified_at": _canonical_datetime(event.permission_verified_at),
        "occurred_at": _canonical_datetime(event.occurred_at),
        "recorded_at": _canonical_datetime(event.recorded_at),
        "reason": event.reason,
        "predecessor_apply_event_id": (
            str(event.predecessor_apply_event_id)
            if event.predecessor_apply_event_id is not None
            else None
        ),
        "predecessor_apply_event_sha256": event.predecessor_apply_event_sha256,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def deserialize_financial_availability_owner_event(
    raw: bytes,
) -> FinancialAvailabilityOwnerEventIdentity:
    """Strictly decode and rehash one local Owner event."""

    if type(raw) is not bytes or not raw or len(raw) > 32768:
        raise ValueError("event bytes must be bounded non-empty bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("event bytes are not strict UTF-8 JSON") from error
    data = _object(value, "event")
    expected = frozenset(
        {
            "schema",
            "action",
            "event_id",
            "event_sha256",
            "record_id",
            "record_version",
            "record_content_sha256",
            "resulting_content_sha256",
            "actor_user_id",
            "permission_id",
            "permission_app_label",
            "permission_codename",
            "permission_verified_at",
            "occurred_at",
            "recorded_at",
            "reason",
            "predecessor_apply_event_id",
            "predecessor_apply_event_sha256",
        }
    )
    _exact_keys(data, expected, "event")
    if data["schema"] != _EVENT_SCHEMA:
        raise ValueError("event schema is unknown")
    try:
        action = FinancialAvailabilityOwnerEventAction(_string(data["action"], "event.action"))
    except ValueError as error:
        raise ValueError("event.action is unknown") from error
    predecessor_id_value = data["predecessor_apply_event_id"]
    event = FinancialAvailabilityOwnerEventIdentity(
        action=action,
        event_id=_uuid(data["event_id"], "event.event_id"),
        event_sha256=_string(data["event_sha256"], "event.event_sha256"),
        record_id=_string(data["record_id"], "event.record_id"),
        record_version=_string(data["record_version"], "event.record_version"),
        record_content_sha256=_string(data["record_content_sha256"], "event.record_content_sha256"),
        resulting_content_sha256=_string(
            data["resulting_content_sha256"], "event.resulting_content_sha256"
        ),
        actor_user_id=_integer(data["actor_user_id"], "event.actor_user_id"),
        permission_id=_integer(data["permission_id"], "event.permission_id"),
        permission_app_label=_string(data["permission_app_label"], "event.permission_app_label"),
        permission_codename=_string(data["permission_codename"], "event.permission_codename"),
        permission_verified_at=_datetime(
            data["permission_verified_at"], "event.permission_verified_at"
        ),
        occurred_at=_datetime(data["occurred_at"], "event.occurred_at"),
        recorded_at=_datetime(data["recorded_at"], "event.recorded_at"),
        reason=_string(data["reason"], "event.reason"),
        predecessor_apply_event_id=(
            _uuid(predecessor_id_value, "event.predecessor_apply_event_id")
            if predecessor_id_value is not None
            else None
        ),
        predecessor_apply_event_sha256=_optional_string(
            data["predecessor_apply_event_sha256"], "event.predecessor_apply_event_sha256"
        ),
    )
    event.__post_init__()
    return event


def _canonical_datetime(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="microseconds")


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


__all__ = [
    "deserialize_financial_availability_owner_event",
    "deserialize_financial_availability_record",
    "serialize_financial_availability_owner_event",
    "serialize_financial_availability_record",
]
