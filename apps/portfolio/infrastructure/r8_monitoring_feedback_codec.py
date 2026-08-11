"""Strict JSON codec for Portfolio-owned raw R8 monitoring feedback."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from apps.portfolio.domain.governed_optimization_monitoring_metrics import (
    MonitoringMetricKey,
)
from apps.portfolio.domain.r8_monitoring_feedback_registry import (
    FEEDBACK_DEFINITION_VERSION,
    PortfolioR8MonitoringFeedback,
    PortfolioR8MonitoringFeedbackDefinition,
    PortfolioR8MonitoringFeedbackSourceReceipt,
    PortfolioR8MonitoringMemberKind,
    PortfolioR8MonitoringRawRatio,
    PortfolioR8MonitoringSourceMember,
)


class PortfolioR8MonitoringFeedbackCodecError(ValueError):
    """A persisted raw feedback payload is malformed or noncanonical."""


def _mapping(value: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise PortfolioR8MonitoringFeedbackCodecError(f"{label} must be an exact object")
    payload = cast(dict[str, object], value)
    if frozenset(payload) != keys:
        raise PortfolioR8MonitoringFeedbackCodecError(f"{label} keys differ")
    return payload


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise PortfolioR8MonitoringFeedbackCodecError(f"{label} must be an exact string")
    return value


def _utc_text(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise PortfolioR8MonitoringFeedbackCodecError("feedback clock is invalid")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _clock(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise PortfolioR8MonitoringFeedbackCodecError(f"{label} is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PortfolioR8MonitoringFeedbackCodecError(f"{label} must be timezone-aware")
    canonical = parsed.astimezone(UTC)
    if text != canonical.isoformat(timespec="microseconds"):
        raise PortfolioR8MonitoringFeedbackCodecError(f"{label} must use canonical UTC text")
    return canonical


def _decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise PortfolioR8MonitoringFeedbackCodecError("raw decimal is invalid")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _decimal(value: object, label: str) -> Decimal:
    text = _text(value, label)
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise PortfolioR8MonitoringFeedbackCodecError(f"{label} is not decimal") from error
    if not parsed.is_finite() or text != _decimal_text(parsed):
        raise PortfolioR8MonitoringFeedbackCodecError(f"{label} is not canonical")
    return parsed


_MEMBER_KEYS = frozenset(
    {"member_id", "member_version", "member_kind", "content_hash", "observed_at", "available_at"}
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
_FEEDBACK_KEYS = frozenset(
    {
        "feedback_id",
        "feedback_version",
        "result_id",
        "result_version",
        "result_hash",
        "receipt_id",
        "receipt_version",
        "receipt_hash",
        "calendar_id",
        "calendar_version",
        "calendar_hash",
        "period_id",
        "period_start_at",
        "period_end_at",
        "members",
        "metric_facts",
        "observed_at",
        "available_at",
        "valid_until",
        "evidence_ref",
        "content_hash",
    }
)
_DEFINITION_KEYS = frozenset({"definition_version", "feedback", "content_hash"})
_SOURCE_KEYS = frozenset(
    {
        "source_receipt_id",
        "source_receipt_version",
        "source_owner",
        "feedback_id",
        "feedback_version",
        "definition_hash",
        "available_at",
        "valid_until",
        "evidence_ref",
        "content_hash",
    }
)


def _encode_member(value: PortfolioR8MonitoringSourceMember) -> dict[str, object]:
    if type(value) is not PortfolioR8MonitoringSourceMember:
        raise PortfolioR8MonitoringFeedbackCodecError("Portfolio R8 feedback member type differs")
    member = PortfolioR8MonitoringSourceMember.validated_copy(value)
    return {
        "member_id": member.member_id,
        "member_version": member.member_version,
        "member_kind": member.member_kind.value,
        "content_hash": member.content_hash,
        "observed_at": _utc_text(member.observed_at),
        "available_at": _utc_text(member.available_at),
    }


def _decode_member(value: object) -> PortfolioR8MonitoringSourceMember:
    payload = _mapping(value, _MEMBER_KEYS, "feedback member")
    try:
        return PortfolioR8MonitoringSourceMember.create(
            member_id=_text(payload["member_id"], "member_id"),
            member_version=_text(payload["member_version"], "member_version"),
            member_kind=PortfolioR8MonitoringMemberKind(
                _text(payload["member_kind"], "member_kind")
            ),
            content_hash=_text(payload["content_hash"], "member content_hash"),
            observed_at=_clock(payload["observed_at"], "member observed_at"),
            available_at=_clock(payload["available_at"], "member available_at"),
        )
    except (TypeError, ValueError) as error:
        raise PortfolioR8MonitoringFeedbackCodecError(
            "feedback member validation failed"
        ) from error


def _encode_fact(value: PortfolioR8MonitoringRawRatio) -> dict[str, object]:
    if type(value) is not PortfolioR8MonitoringRawRatio:
        raise PortfolioR8MonitoringFeedbackCodecError("Portfolio R8 feedback raw fact type differs")
    fact = PortfolioR8MonitoringRawRatio.validated_copy(value)
    return {
        "metric_key": fact.metric_key.value,
        "numerator_name": fact.numerator_name,
        "numerator": _decimal_text(fact.numerator),
        "denominator_name": fact.denominator_name,
        "denominator": _decimal_text(fact.denominator),
        "source_member_hashes": list(fact.source_member_hashes),
        "content_hash": fact.content_hash,
    }


def _decode_fact(value: object) -> PortfolioR8MonitoringRawRatio:
    payload = _mapping(value, _FACT_KEYS, "feedback raw fact")
    hashes = payload["source_member_hashes"]
    if type(hashes) is not list or any(type(item) is not str for item in hashes):
        raise PortfolioR8MonitoringFeedbackCodecError("source_member_hashes must be a string list")
    try:
        fact = PortfolioR8MonitoringRawRatio.create(
            metric_key=MonitoringMetricKey(_text(payload["metric_key"], "metric_key")),
            numerator=_decimal(payload["numerator"], "numerator"),
            denominator=_decimal(payload["denominator"], "denominator"),
            source_member_hashes=tuple(cast(list[str], hashes)),
        )
        if fact.numerator_name != _text(payload["numerator_name"], "numerator_name"):
            raise ValueError("numerator name differs")
        if fact.denominator_name != _text(payload["denominator_name"], "denominator_name"):
            raise ValueError("denominator name differs")
        if fact.content_hash != _text(payload["content_hash"], "raw fact content_hash"):
            raise ValueError("raw fact seal differs")
        return fact
    except (TypeError, ValueError) as error:
        raise PortfolioR8MonitoringFeedbackCodecError("raw fact validation failed") from error


def encode_portfolio_r8_monitoring_feedback(
    value: PortfolioR8MonitoringFeedback,
) -> dict[str, object]:
    """Encode a complete exact raw feedback graph."""

    try:
        if type(value) is not PortfolioR8MonitoringFeedback:
            raise TypeError("Portfolio R8 feedback type differs")
        feedback = PortfolioR8MonitoringFeedback.validated_copy(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise PortfolioR8MonitoringFeedbackCodecError("feedback is invalid") from error
    return {
        "feedback_id": feedback.feedback_id,
        "feedback_version": feedback.feedback_version,
        "result_id": feedback.result_id,
        "result_version": feedback.result_version,
        "result_hash": feedback.result_hash,
        "receipt_id": feedback.receipt_id,
        "receipt_version": feedback.receipt_version,
        "receipt_hash": feedback.receipt_hash,
        "calendar_id": feedback.calendar_id,
        "calendar_version": feedback.calendar_version,
        "calendar_hash": feedback.calendar_hash,
        "period_id": feedback.period_id,
        "period_start_at": _utc_text(feedback.period_start_at),
        "period_end_at": _utc_text(feedback.period_end_at),
        "members": [_encode_member(item) for item in feedback.members],
        "metric_facts": [_encode_fact(item) for item in feedback.metric_facts],
        "observed_at": _utc_text(feedback.observed_at),
        "available_at": _utc_text(feedback.available_at),
        "valid_until": _utc_text(feedback.valid_until),
        "evidence_ref": feedback.evidence_ref,
        "content_hash": feedback.content_hash,
    }


def decode_portfolio_r8_monitoring_feedback(value: object) -> PortfolioR8MonitoringFeedback:
    """Strictly restore a complete raw feedback graph."""

    payload = _mapping(value, _FEEDBACK_KEYS, "feedback")
    raw_members = payload["members"]
    raw_facts = payload["metric_facts"]
    if type(raw_members) is not list or type(raw_facts) is not list:
        raise PortfolioR8MonitoringFeedbackCodecError("feedback members/facts must be lists")
    try:
        feedback = PortfolioR8MonitoringFeedback.create(
            result_id=_text(payload["result_id"], "result_id"),
            result_version=_text(payload["result_version"], "result_version"),
            result_hash=_text(payload["result_hash"], "result_hash"),
            receipt_id=_text(payload["receipt_id"], "receipt_id"),
            receipt_version=_text(payload["receipt_version"], "receipt_version"),
            receipt_hash=_text(payload["receipt_hash"], "receipt_hash"),
            calendar_id=_text(payload["calendar_id"], "calendar_id"),
            calendar_version=_text(payload["calendar_version"], "calendar_version"),
            calendar_hash=_text(payload["calendar_hash"], "calendar_hash"),
            period_id=_text(payload["period_id"], "period_id"),
            period_start_at=_clock(payload["period_start_at"], "period_start_at"),
            period_end_at=_clock(payload["period_end_at"], "period_end_at"),
            members=tuple(_decode_member(item) for item in raw_members),
            metric_facts=tuple(_decode_fact(item) for item in raw_facts),
            valid_until=_clock(payload["valid_until"], "valid_until"),
            evidence_ref=_text(payload["evidence_ref"], "evidence_ref"),
        )
        for key, actual in (
            ("feedback_id", feedback.feedback_id),
            ("feedback_version", feedback.feedback_version),
            ("observed_at", _utc_text(feedback.observed_at)),
            ("available_at", _utc_text(feedback.available_at)),
            ("content_hash", feedback.content_hash),
        ):
            if actual != _text(payload[key], key):
                raise ValueError(f"{key} differs")
        return feedback
    except (TypeError, ValueError) as error:
        raise PortfolioR8MonitoringFeedbackCodecError("feedback validation failed") from error


def encode_portfolio_r8_monitoring_feedback_definition(
    value: PortfolioR8MonitoringFeedbackDefinition,
) -> dict[str, object]:
    """Encode one exact feedback definition."""

    if type(value) is not PortfolioR8MonitoringFeedbackDefinition:
        raise PortfolioR8MonitoringFeedbackCodecError(
            "Portfolio R8 feedback definition type differs"
        )
    definition = PortfolioR8MonitoringFeedbackDefinition.validated_copy(value)
    return {
        "definition_version": definition.definition_version,
        "feedback": encode_portfolio_r8_monitoring_feedback(definition.feedback),
        "content_hash": definition.content_hash,
    }


def decode_portfolio_r8_monitoring_feedback_definition(
    value: object,
) -> PortfolioR8MonitoringFeedbackDefinition:
    """Strictly restore one feedback definition."""

    payload = _mapping(value, _DEFINITION_KEYS, "feedback definition")
    try:
        if (
            _text(payload["definition_version"], "definition_version")
            != FEEDBACK_DEFINITION_VERSION
        ):
            raise ValueError("definition version differs")
        definition = PortfolioR8MonitoringFeedbackDefinition.from_feedback(
            decode_portfolio_r8_monitoring_feedback(payload["feedback"])
        )
        if definition.content_hash != _text(payload["content_hash"], "definition content_hash"):
            raise ValueError("definition seal differs")
        return definition
    except (TypeError, ValueError) as error:
        raise PortfolioR8MonitoringFeedbackCodecError("definition validation failed") from error


def encode_portfolio_r8_monitoring_feedback_source_receipt(
    value: PortfolioR8MonitoringFeedbackSourceReceipt,
) -> dict[str, object]:
    """Encode one exact Portfolio source receipt."""

    if type(value) is not PortfolioR8MonitoringFeedbackSourceReceipt:
        raise PortfolioR8MonitoringFeedbackCodecError("Portfolio R8 feedback source type differs")
    source = PortfolioR8MonitoringFeedbackSourceReceipt.validated_copy(value)
    return {
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_owner": source.source_owner,
        "feedback_id": source.feedback_id,
        "feedback_version": source.feedback_version,
        "definition_hash": source.definition_hash,
        "available_at": _utc_text(source.available_at),
        "valid_until": _utc_text(source.valid_until),
        "evidence_ref": source.evidence_ref,
        "content_hash": source.content_hash,
    }


def decode_portfolio_r8_monitoring_feedback_source_receipt(
    value: object,
) -> PortfolioR8MonitoringFeedbackSourceReceipt:
    """Strictly restore one Portfolio source receipt."""

    payload = _mapping(value, _SOURCE_KEYS, "feedback source receipt")
    try:
        source = PortfolioR8MonitoringFeedbackSourceReceipt.create(
            source_receipt_id=_text(payload["source_receipt_id"], "source_receipt_id"),
            source_receipt_version=_text(
                payload["source_receipt_version"], "source_receipt_version"
            ),
            feedback_id=_text(payload["feedback_id"], "feedback_id"),
            feedback_version=_text(payload["feedback_version"], "feedback_version"),
            definition_hash=_text(payload["definition_hash"], "definition_hash"),
            available_at=_clock(payload["available_at"], "available_at"),
            valid_until=_clock(payload["valid_until"], "valid_until"),
            evidence_ref=_text(payload["evidence_ref"], "evidence_ref"),
        )
        if source.source_owner != _text(payload["source_owner"], "source_owner"):
            raise ValueError("source owner differs")
        if source.content_hash != _text(payload["content_hash"], "source content_hash"):
            raise ValueError("source seal differs")
        return source
    except (TypeError, ValueError) as error:
        raise PortfolioR8MonitoringFeedbackCodecError("source validation failed") from error


__all__ = [
    "PortfolioR8MonitoringFeedbackCodecError",
    "decode_portfolio_r8_monitoring_feedback",
    "decode_portfolio_r8_monitoring_feedback_definition",
    "decode_portfolio_r8_monitoring_feedback_source_receipt",
    "encode_portfolio_r8_monitoring_feedback",
    "encode_portfolio_r8_monitoring_feedback_definition",
    "encode_portfolio_r8_monitoring_feedback_source_receipt",
]
