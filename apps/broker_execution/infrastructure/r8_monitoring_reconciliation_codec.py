"""Strict JSON codec for Broker-owned R8 monitoring reconciliation receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from apps.broker_execution.domain.r8_monitoring_reconciliation import (
    R8BrokerMonitoringMetricKey,
    R8BrokerMonitoringMetricRawFact,
    R8BrokerMonitoringPeriodReceipt,
    R8BrokerReconciliationDefinition,
    R8BrokerReconciliationMember,
    R8BrokerReconciliationMemberKind,
    R8BrokerReconciliationSourceReceipt,
)

_MEMBER_KEYS = frozenset(
    {
        "member_id",
        "member_version",
        "member_kind",
        "content_hash",
        "observed_at",
        "available_at",
    }
)
_FACT_KEYS = frozenset(
    {
        "metric_key",
        "numerator_name",
        "numerator",
        "denominator_name",
        "denominator",
        "source_member_hashes",
        "content_hash",
    }
)
_DEFINITION_KEYS = frozenset(
    {
        "definition_id",
        "definition_version",
        "result_id",
        "result_hash",
        "portfolio_receipt_id",
        "portfolio_receipt_version",
        "portfolio_receipt_hash",
        "calendar_id",
        "calendar_version",
        "calendar_hash",
        "period_id",
        "period_start_at",
        "period_end_at",
        "planning_reference_id",
        "planning_reference_version",
        "planning_reference_hash",
        "reconciliation_manifest_id",
        "reconciliation_manifest_version",
        "reconciliation_manifest_hash",
        "members",
        "metric_facts",
        "observed_at",
        "available_at",
        "valid_until",
        "evidence_ref",
        "content_hash",
    }
)
_SOURCE_KEYS = frozenset(
    {
        "owner",
        "source_receipt_id",
        "source_receipt_version",
        "definition_hash",
        "available_at",
        "valid_until",
        "evidence_ref",
        "content_hash",
    }
)
_RECEIPT_KEYS = frozenset(
    {
        "owner",
        "receipt_id",
        "receipt_version",
        "definition",
        "source_receipt",
        "recorded_at",
        "research_only",
        "must_not_use_for_decision",
        "must_not_publish_current",
        "must_not_execute",
        "content_hash",
    }
)


class R8BrokerMonitoringCodecError(ValueError):
    """A Broker monitoring payload differs from its exact canonical schema."""


def _exact_dict(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise R8BrokerMonitoringCodecError(f"{label} must be an exact object")
    return value


def _keys(value: dict[str, object], expected: frozenset[str], label: str) -> None:
    if frozenset(value) != expected:
        raise R8BrokerMonitoringCodecError(f"{label} keys are invalid")


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise R8BrokerMonitoringCodecError(f"{label} must be a string")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise R8BrokerMonitoringCodecError(f"{label} must be an exact bool")
    return value


def _utc_text(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R8BrokerMonitoringCodecError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _datetime(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise R8BrokerMonitoringCodecError(f"{label} must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or _utc_text(parsed) != text:
        raise R8BrokerMonitoringCodecError(f"{label} must be canonical timezone-aware UTC text")
    return parsed


def _decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise R8BrokerMonitoringCodecError("decimal must be exact and finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _decimal(value: object, label: str) -> Decimal:
    text = _string(value, label)
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise R8BrokerMonitoringCodecError(f"{label} must be a Decimal") from error
    if not parsed.is_finite() or _decimal_text(parsed) != text:
        raise R8BrokerMonitoringCodecError(f"{label} must use canonical Decimal text")
    return parsed


def _strings(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise R8BrokerMonitoringCodecError(f"{label} must be an exact string list")
    return tuple(value)


def _member_to_payload(value: R8BrokerReconciliationMember) -> dict[str, object]:
    member = value.validated_copy()
    return {
        "member_id": member.member_id,
        "member_version": member.member_version,
        "member_kind": member.member_kind.value,
        "content_hash": member.content_hash,
        "observed_at": _utc_text(member.observed_at),
        "available_at": _utc_text(member.available_at),
    }


def _member_from_payload(value: object) -> R8BrokerReconciliationMember:
    payload = _exact_dict(value, "Broker reconciliation member")
    _keys(payload, _MEMBER_KEYS, "Broker reconciliation member")
    try:
        kind = R8BrokerReconciliationMemberKind(_string(payload["member_kind"], "member_kind"))
    except ValueError as error:
        raise R8BrokerMonitoringCodecError("member_kind is unsupported") from error
    return R8BrokerReconciliationMember.create(
        member_id=_string(payload["member_id"], "member_id"),
        member_version=_string(payload["member_version"], "member_version"),
        member_kind=kind,
        content_hash=_string(payload["content_hash"], "member content_hash"),
        observed_at=_datetime(payload["observed_at"], "member observed_at"),
        available_at=_datetime(payload["available_at"], "member available_at"),
    )


def _fact_to_payload(value: R8BrokerMonitoringMetricRawFact) -> dict[str, object]:
    fact = value.validated_copy()
    return {
        "metric_key": fact.metric_key.value,
        "numerator_name": fact.numerator_name,
        "numerator": _decimal_text(fact.numerator),
        "denominator_name": fact.denominator_name,
        "denominator": _decimal_text(fact.denominator),
        "source_member_hashes": list(fact.source_member_hashes),
        "content_hash": fact.content_hash,
    }


def _fact_from_payload(value: object) -> R8BrokerMonitoringMetricRawFact:
    payload = _exact_dict(value, "Broker monitoring raw fact")
    _keys(payload, _FACT_KEYS, "Broker monitoring raw fact")
    try:
        metric_key = R8BrokerMonitoringMetricKey(_string(payload["metric_key"], "metric_key"))
    except ValueError as error:
        raise R8BrokerMonitoringCodecError("metric_key is unsupported") from error
    fact = R8BrokerMonitoringMetricRawFact.create(
        metric_key=metric_key,
        numerator_name=_string(payload["numerator_name"], "numerator_name"),
        numerator=_decimal(payload["numerator"], "numerator"),
        denominator_name=_string(payload["denominator_name"], "denominator_name"),
        denominator=_decimal(payload["denominator"], "denominator"),
        source_member_hashes=_strings(payload["source_member_hashes"], "source_member_hashes"),
    )
    if fact.content_hash != _string(payload["content_hash"], "fact content_hash"):
        raise R8BrokerMonitoringCodecError("Broker raw fact seal differs")
    return fact


def encode_r8_broker_reconciliation_definition(
    value: R8BrokerReconciliationDefinition,
) -> dict[str, object]:
    """Encode one recursively validated reconciliation definition."""

    try:
        definition = value.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise R8BrokerMonitoringCodecError("Broker definition cannot be encoded") from error
    return {
        "definition_id": definition.definition_id,
        "definition_version": definition.definition_version,
        "result_id": definition.result_id,
        "result_hash": definition.result_hash,
        "portfolio_receipt_id": definition.portfolio_receipt_id,
        "portfolio_receipt_version": definition.portfolio_receipt_version,
        "portfolio_receipt_hash": definition.portfolio_receipt_hash,
        "calendar_id": definition.calendar_id,
        "calendar_version": definition.calendar_version,
        "calendar_hash": definition.calendar_hash,
        "period_id": definition.period_id,
        "period_start_at": _utc_text(definition.period_start_at),
        "period_end_at": _utc_text(definition.period_end_at),
        "planning_reference_id": definition.planning_reference_id,
        "planning_reference_version": definition.planning_reference_version,
        "planning_reference_hash": definition.planning_reference_hash,
        "reconciliation_manifest_id": definition.reconciliation_manifest_id,
        "reconciliation_manifest_version": definition.reconciliation_manifest_version,
        "reconciliation_manifest_hash": definition.reconciliation_manifest_hash,
        "members": [_member_to_payload(item) for item in definition.members],
        "metric_facts": [_fact_to_payload(item) for item in definition.metric_facts],
        "observed_at": _utc_text(definition.observed_at),
        "available_at": _utc_text(definition.available_at),
        "valid_until": _utc_text(definition.valid_until),
        "evidence_ref": definition.evidence_ref,
        "content_hash": definition.content_hash,
    }


def decode_r8_broker_reconciliation_definition(
    value: object,
) -> R8BrokerReconciliationDefinition:
    """Decode only the exact complete reconciliation-definition schema."""

    try:
        payload = _exact_dict(value, "Broker reconciliation definition")
        _keys(payload, _DEFINITION_KEYS, "Broker reconciliation definition")
        raw_members = payload["members"]
        raw_facts = payload["metric_facts"]
        if type(raw_members) is not list or type(raw_facts) is not list:
            raise R8BrokerMonitoringCodecError(
                "Broker definition members and facts must be exact lists"
            )
        definition = R8BrokerReconciliationDefinition.create(
            result_id=_string(payload["result_id"], "result_id"),
            result_hash=_string(payload["result_hash"], "result_hash"),
            portfolio_receipt_id=_string(payload["portfolio_receipt_id"], "portfolio_receipt_id"),
            portfolio_receipt_version=_string(
                payload["portfolio_receipt_version"], "portfolio_receipt_version"
            ),
            portfolio_receipt_hash=_string(
                payload["portfolio_receipt_hash"], "portfolio_receipt_hash"
            ),
            calendar_id=_string(payload["calendar_id"], "calendar_id"),
            calendar_version=_string(payload["calendar_version"], "calendar_version"),
            calendar_hash=_string(payload["calendar_hash"], "calendar_hash"),
            period_id=_string(payload["period_id"], "period_id"),
            period_start_at=_datetime(payload["period_start_at"], "period_start_at"),
            period_end_at=_datetime(payload["period_end_at"], "period_end_at"),
            planning_reference_id=_string(
                payload["planning_reference_id"], "planning_reference_id"
            ),
            planning_reference_version=_string(
                payload["planning_reference_version"], "planning_reference_version"
            ),
            planning_reference_hash=_string(
                payload["planning_reference_hash"], "planning_reference_hash"
            ),
            reconciliation_manifest_id=_string(
                payload["reconciliation_manifest_id"], "reconciliation_manifest_id"
            ),
            reconciliation_manifest_version=_string(
                payload["reconciliation_manifest_version"],
                "reconciliation_manifest_version",
            ),
            reconciliation_manifest_hash=_string(
                payload["reconciliation_manifest_hash"], "reconciliation_manifest_hash"
            ),
            members=tuple(_member_from_payload(item) for item in raw_members),
            metric_facts=tuple(_fact_from_payload(item) for item in raw_facts),
            valid_until=_datetime(payload["valid_until"], "valid_until"),
            evidence_ref=_string(payload["evidence_ref"], "evidence_ref"),
        )
        if (
            definition.definition_id != _string(payload["definition_id"], "definition_id")
            or definition.definition_version
            != _string(payload["definition_version"], "definition_version")
            or definition.observed_at != _datetime(payload["observed_at"], "observed_at")
            or definition.available_at != _datetime(payload["available_at"], "available_at")
            or definition.content_hash != _string(payload["content_hash"], "content_hash")
        ):
            raise R8BrokerMonitoringCodecError("Broker definition derived seal differs")
        return definition
    except R8BrokerMonitoringCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise R8BrokerMonitoringCodecError("Broker definition payload is invalid") from error


def encode_r8_broker_reconciliation_source_receipt(
    value: R8BrokerReconciliationSourceReceipt,
) -> dict[str, object]:
    """Encode one recursively validated source authorization."""

    try:
        source = value.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise R8BrokerMonitoringCodecError("Broker source cannot be encoded") from error
    return {
        "owner": source.owner,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "definition_hash": source.definition_hash,
        "available_at": _utc_text(source.available_at),
        "valid_until": _utc_text(source.valid_until),
        "evidence_ref": source.evidence_ref,
        "content_hash": source.content_hash,
    }


def decode_r8_broker_reconciliation_source_receipt(
    value: object,
) -> R8BrokerReconciliationSourceReceipt:
    """Decode only the exact source-authorization schema."""

    try:
        payload = _exact_dict(value, "Broker reconciliation source")
        _keys(payload, _SOURCE_KEYS, "Broker reconciliation source")
        source = R8BrokerReconciliationSourceReceipt.create(
            source_receipt_id=_string(payload["source_receipt_id"], "source_receipt_id"),
            source_receipt_version=_string(
                payload["source_receipt_version"], "source_receipt_version"
            ),
            definition_hash=_string(payload["definition_hash"], "definition_hash"),
            available_at=_datetime(payload["available_at"], "available_at"),
            valid_until=_datetime(payload["valid_until"], "valid_until"),
            evidence_ref=_string(payload["evidence_ref"], "evidence_ref"),
        )
        if source.owner != _string(payload["owner"], "owner") or source.content_hash != _string(
            payload["content_hash"], "content_hash"
        ):
            raise R8BrokerMonitoringCodecError("Broker source derived seal differs")
        return source
    except R8BrokerMonitoringCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise R8BrokerMonitoringCodecError("Broker source payload is invalid") from error


def encode_r8_broker_monitoring_period_receipt(
    value: R8BrokerMonitoringPeriodReceipt,
) -> dict[str, object]:
    """Encode one exact Broker owner receipt."""

    try:
        receipt = value.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise R8BrokerMonitoringCodecError("Broker period receipt cannot be encoded") from error
    return {
        "owner": receipt.owner,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "definition": encode_r8_broker_reconciliation_definition(receipt.definition),
        "source_receipt": encode_r8_broker_reconciliation_source_receipt(receipt.source_receipt),
        "recorded_at": _utc_text(receipt.recorded_at),
        "research_only": receipt.research_only,
        "must_not_use_for_decision": receipt.must_not_use_for_decision,
        "must_not_publish_current": receipt.must_not_publish_current,
        "must_not_execute": receipt.must_not_execute,
        "content_hash": receipt.content_hash,
    }


def decode_r8_broker_monitoring_period_receipt(
    value: object,
) -> R8BrokerMonitoringPeriodReceipt:
    """Decode only the exact complete Broker receipt schema."""

    try:
        payload = _exact_dict(value, "Broker monitoring period receipt")
        _keys(payload, _RECEIPT_KEYS, "Broker monitoring period receipt")
        receipt = R8BrokerMonitoringPeriodReceipt.record(
            definition=decode_r8_broker_reconciliation_definition(payload["definition"]),
            source_receipt=decode_r8_broker_reconciliation_source_receipt(
                payload["source_receipt"]
            ),
            owner_recorded_at=_datetime(payload["recorded_at"], "recorded_at"),
        )
        if (
            receipt.owner != _string(payload["owner"], "owner")
            or receipt.receipt_id != _string(payload["receipt_id"], "receipt_id")
            or receipt.receipt_version != _string(payload["receipt_version"], "receipt_version")
            or receipt.research_only != _boolean(payload["research_only"], "research_only")
            or receipt.must_not_use_for_decision
            != _boolean(payload["must_not_use_for_decision"], "must_not_use_for_decision")
            or receipt.must_not_publish_current
            != _boolean(payload["must_not_publish_current"], "must_not_publish_current")
            or receipt.must_not_execute != _boolean(payload["must_not_execute"], "must_not_execute")
            or receipt.content_hash != _string(payload["content_hash"], "content_hash")
        ):
            raise R8BrokerMonitoringCodecError("Broker period receipt derived seal differs")
        return receipt
    except R8BrokerMonitoringCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise R8BrokerMonitoringCodecError(
            "Broker monitoring period receipt payload is invalid"
        ) from error


__all__ = [
    "R8BrokerMonitoringCodecError",
    "decode_r8_broker_monitoring_period_receipt",
    "decode_r8_broker_reconciliation_definition",
    "decode_r8_broker_reconciliation_source_receipt",
    "encode_r8_broker_monitoring_period_receipt",
    "encode_r8_broker_reconciliation_definition",
    "encode_r8_broker_reconciliation_source_receipt",
]
