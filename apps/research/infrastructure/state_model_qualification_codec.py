"""Strict canonical codec for R6 qualification assessment/lifecycle evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from apps.research.domain.state_model_qualification import (
    StateModelQualificationAssessment,
    StateModelQualificationBlockerCode,
    StateModelQualificationStatus,
    restore_state_model_qualification_assessment,
)
from apps.research.domain.state_model_qualification_contracts import (
    ComparativeMetricResult,
    MetricImprovementDirection,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationLifecycleAction,
    R6QualificationLifecycleEvent,
    R6QualificationPromotionAuthorization,
    R6QualificationRef,
)


class R6QualificationCodecError(ValueError):
    """Persisted R6 payload is malformed or non-canonical."""


_ASSESSMENT_SCHEMA = "research.r6.qualification-assessment.v1"
_AUTH_SCHEMA = "research.r6.qualification-authorization.v1"
_EVENT_SCHEMA = "research.r6.qualification-event.v1"


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise R6QualificationCodecError("R6 qualification Decimal must be finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R6QualificationCodecError("R6 qualification datetime must be aware")
    return value.astimezone(UTC).isoformat()


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise R6QualificationCodecError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise R6QualificationCodecError(f"{label} must be a list")
    return value


def _keys(value: dict[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise R6QualificationCodecError(f"{label} keys are missing or extra")


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise R6QualificationCodecError(f"{label} must be a string")
    return value


def _nullable_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise R6QualificationCodecError(f"{label} must be boolean")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise R6QualificationCodecError(f"{label} must be integer")
    return value


def _decimal(value: object, label: str) -> Decimal:
    text = _string(value, label)
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise R6QualificationCodecError(f"{label} must be Decimal text") from error
    if not parsed.is_finite() or _decimal_text(parsed) != text:
        raise R6QualificationCodecError(f"{label} is non-canonical")
    return parsed


def _datetime(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise R6QualificationCodecError(f"{label} must be ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or _datetime_text(parsed) != text:
        raise R6QualificationCodecError(f"{label} is non-canonical")
    return parsed


def _hash(value: object, label: str) -> str:
    text = _string(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise R6QualificationCodecError(f"{label} must be lowercase SHA-256")
    return text


def _assessment_body(assessment: StateModelQualificationAssessment) -> dict[str, object]:
    return {
        "status": assessment.status.value,
        "study_id": assessment.study_id,
        "candidate_id": assessment.candidate_id,
        "candidate_version": assessment.candidate_version,
        "study_hash": assessment.study_hash,
        "preregistration_hash": assessment.preregistration_hash,
        "baseline_shortfall_report_hash": assessment.baseline_shortfall_report_hash,
        "candidate_evidence_hash": assessment.candidate_evidence_hash,
        "advanced_assessment_hash": assessment.advanced_assessment_hash,
        "pit_manifest_canonical_hash": assessment.pit_manifest_canonical_hash,
        "artifact_attestation_hash": assessment.artifact_attestation_hash,
        "advanced_threshold_hash": assessment.advanced_threshold_hash,
        "derived_metric_bundle_hash": assessment.derived_metric_bundle_hash,
        "policy_hash": assessment.policy_hash,
        "assessed_at": _datetime_text(assessment.assessed_at),
        "metric_results": [
            {
                "metric_key": result.metric_key,
                "unit": result.unit,
                "direction": result.direction.value,
                "baseline_value": _decimal_text(result.baseline_value),
                "candidate_value": _decimal_text(result.candidate_value),
                "improvement_delta": _decimal_text(result.improvement_delta),
                "minimum_improvement_delta": _decimal_text(result.minimum_improvement_delta),
                "passed": result.passed,
            }
            for result in assessment.metric_results
        ],
        "blockers": [blocker.value for blocker in assessment.blockers],
        "may_request_promotion_review": assessment.may_request_promotion_review,
        "promotion_decision_present": assessment.promotion_decision_present,
        "research_only": assessment.research_only,
        "must_not_use_for_decision": assessment.must_not_use_for_decision,
        "must_not_replace_regime": assessment.must_not_replace_regime,
        "content_hash": assessment.content_hash,
    }


def encode_r6_qualification_assessment(
    assessment: StateModelQualificationAssessment,
) -> dict[str, object]:
    """Encode one complete assessment with canonical Decimal/UTC text."""

    return {"schema": _ASSESSMENT_SCHEMA, "body": _assessment_body(assessment)}


def decode_r6_qualification_assessment(payload: object) -> StateModelQualificationAssessment:
    """Strictly decode and revalidate one assessment payload."""

    envelope = _object(payload, "R6 qualification assessment envelope")
    _keys(envelope, {"schema", "body"}, "R6 qualification assessment envelope")
    if envelope["schema"] != _ASSESSMENT_SCHEMA:
        raise R6QualificationCodecError("unsupported R6 qualification assessment schema")
    body = _object(envelope["body"], "R6 qualification assessment body")
    expected = {
        "status",
        "study_id",
        "candidate_id",
        "candidate_version",
        "study_hash",
        "preregistration_hash",
        "baseline_shortfall_report_hash",
        "candidate_evidence_hash",
        "advanced_assessment_hash",
        "pit_manifest_canonical_hash",
        "artifact_attestation_hash",
        "advanced_threshold_hash",
        "derived_metric_bundle_hash",
        "policy_hash",
        "assessed_at",
        "metric_results",
        "blockers",
        "may_request_promotion_review",
        "promotion_decision_present",
        "research_only",
        "must_not_use_for_decision",
        "must_not_replace_regime",
        "content_hash",
    }
    _keys(body, expected, "R6 qualification assessment body")
    try:
        status = StateModelQualificationStatus(_string(body["status"], "status"))
        metrics: list[ComparativeMetricResult] = []
        for index, raw in enumerate(_list(body["metric_results"], "metric_results")):
            item = _object(raw, f"metric_results[{index}]")
            _keys(
                item,
                {
                    "metric_key",
                    "unit",
                    "direction",
                    "baseline_value",
                    "candidate_value",
                    "improvement_delta",
                    "minimum_improvement_delta",
                    "passed",
                },
                f"metric_results[{index}]",
            )
            metrics.append(
                ComparativeMetricResult(
                    metric_key=_string(item["metric_key"], "metric_key"),
                    unit=_string(item["unit"], "unit"),
                    direction=MetricImprovementDirection(_string(item["direction"], "direction")),
                    baseline_value=_decimal(item["baseline_value"], "baseline_value"),
                    candidate_value=_decimal(item["candidate_value"], "candidate_value"),
                    improvement_delta=_decimal(item["improvement_delta"], "improvement_delta"),
                    minimum_improvement_delta=_decimal(
                        item["minimum_improvement_delta"],
                        "minimum_improvement_delta",
                    ),
                    passed=_boolean(item["passed"], "passed"),
                )
            )
        blockers = tuple(
            StateModelQualificationBlockerCode(_string(item, f"blockers[{index}]"))
            for index, item in enumerate(_list(body["blockers"], "blockers"))
        )
        restored = restore_state_model_qualification_assessment(
            status=status,
            study_id=_string(body["study_id"], "study_id"),
            candidate_id=_nullable_string(body["candidate_id"], "candidate_id"),
            candidate_version=_nullable_string(body["candidate_version"], "candidate_version"),
            study_hash=_nullable_string(body["study_hash"], "study_hash"),
            preregistration_hash=_nullable_string(
                body["preregistration_hash"], "preregistration_hash"
            ),
            baseline_shortfall_report_hash=_nullable_string(
                body["baseline_shortfall_report_hash"],
                "baseline_shortfall_report_hash",
            ),
            candidate_evidence_hash=_nullable_string(
                body["candidate_evidence_hash"], "candidate_evidence_hash"
            ),
            advanced_assessment_hash=_nullable_string(
                body["advanced_assessment_hash"], "advanced_assessment_hash"
            ),
            pit_manifest_canonical_hash=_nullable_string(
                body["pit_manifest_canonical_hash"], "pit_manifest_canonical_hash"
            ),
            artifact_attestation_hash=_nullable_string(
                body["artifact_attestation_hash"], "artifact_attestation_hash"
            ),
            advanced_threshold_hash=_nullable_string(
                body["advanced_threshold_hash"], "advanced_threshold_hash"
            ),
            derived_metric_bundle_hash=_nullable_string(
                body["derived_metric_bundle_hash"], "derived_metric_bundle_hash"
            ),
            policy_hash=_nullable_string(body["policy_hash"], "policy_hash"),
            assessed_at=_datetime(body["assessed_at"], "assessed_at"),
            metric_results=tuple(metrics),
            blockers=blockers,
            may_request_promotion_review=_boolean(
                body["may_request_promotion_review"],
                "may_request_promotion_review",
            ),
            promotion_decision_present=_boolean(
                body["promotion_decision_present"],
                "promotion_decision_present",
            ),
            research_only=_boolean(body["research_only"], "research_only"),
            must_not_use_for_decision=_boolean(
                body["must_not_use_for_decision"],
                "must_not_use_for_decision",
            ),
            must_not_replace_regime=_boolean(
                body["must_not_replace_regime"],
                "must_not_replace_regime",
            ),
            content_hash=_hash(body["content_hash"], "content_hash"),
        )
    except R6QualificationCodecError:
        raise
    except (TypeError, ValueError) as error:
        raise R6QualificationCodecError("R6 qualification assessment restore failed") from error
    if encode_r6_qualification_assessment(restored) != envelope:
        raise R6QualificationCodecError("R6 qualification assessment payload is non-canonical")
    return restored


def _authorization_body(
    authorization: R6QualificationPromotionAuthorization,
) -> dict[str, object]:
    return {
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "assessment_id": authorization.qualification_ref.assessment_id,
        "assessment_hash": authorization.qualification_ref.assessment_hash,
        "event_id": authorization.event_id,
        "event_version": authorization.event_version,
        "action": authorization.action.value,
        "expected_sequence": authorization.expected_sequence,
        "owner": authorization.owner,
        "issued_at": _datetime_text(authorization.issued_at),
        "recorded_at": _datetime_text(authorization.recorded_at),
        "valid_until": _datetime_text(authorization.valid_until),
        "reason_codes": list(authorization.reason_codes),
        "evidence_ref": authorization.evidence_ref,
        "research_only": authorization.research_only,
        "must_not_use_for_decision": authorization.must_not_use_for_decision,
        "must_not_replace_regime": authorization.must_not_replace_regime,
        "content_hash": authorization.content_hash,
    }


def encode_r6_qualification_authorization(
    authorization: R6QualificationPromotionAuthorization,
) -> dict[str, object]:
    """Encode one manual lifecycle authorization."""

    return {"schema": _AUTH_SCHEMA, "body": _authorization_body(authorization)}


def decode_r6_qualification_authorization(
    payload: object,
) -> R6QualificationPromotionAuthorization:
    """Strictly decode one lifecycle authorization."""

    envelope = _object(payload, "R6 qualification authorization envelope")
    _keys(envelope, {"schema", "body"}, "R6 qualification authorization envelope")
    if envelope["schema"] != _AUTH_SCHEMA:
        raise R6QualificationCodecError("unsupported R6 qualification authorization schema")
    body = _object(envelope["body"], "R6 qualification authorization body")
    expected = set(_authorization_body_placeholder())
    _keys(body, expected, "R6 qualification authorization body")
    try:
        authorization = R6QualificationPromotionAuthorization(
            authorization_id=_string(body["authorization_id"], "authorization_id"),
            authorization_version=_string(body["authorization_version"], "authorization_version"),
            qualification_ref=R6QualificationRef(
                _string(body["assessment_id"], "assessment_id"),
                _hash(body["assessment_hash"], "assessment_hash"),
            ),
            event_id=_string(body["event_id"], "event_id"),
            event_version=_string(body["event_version"], "event_version"),
            action=R6QualificationLifecycleAction(_string(body["action"], "action")),
            expected_sequence=_integer(body["expected_sequence"], "expected_sequence"),
            owner=_string(body["owner"], "owner"),
            issued_at=_datetime(body["issued_at"], "issued_at"),
            recorded_at=_datetime(body["recorded_at"], "recorded_at"),
            valid_until=_datetime(body["valid_until"], "valid_until"),
            reason_codes=tuple(
                _string(item, "reason_code") for item in _list(body["reason_codes"], "reason_codes")
            ),
            evidence_ref=_string(body["evidence_ref"], "evidence_ref"),
            research_only=_boolean(body["research_only"], "research_only"),
            must_not_use_for_decision=_boolean(
                body["must_not_use_for_decision"], "must_not_use_for_decision"
            ),
            must_not_replace_regime=_boolean(
                body["must_not_replace_regime"], "must_not_replace_regime"
            ),
        )
    except (TypeError, ValueError) as error:
        raise R6QualificationCodecError("R6 qualification authorization restore failed") from error
    if authorization.content_hash != _hash(body["content_hash"], "content_hash"):
        raise R6QualificationCodecError("R6 qualification authorization content hash mismatch")
    if encode_r6_qualification_authorization(authorization) != envelope:
        raise R6QualificationCodecError("R6 qualification authorization payload is non-canonical")
    return authorization


def _authorization_body_placeholder() -> tuple[str, ...]:
    return (
        "authorization_id",
        "authorization_version",
        "assessment_id",
        "assessment_hash",
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
        "research_only",
        "must_not_use_for_decision",
        "must_not_replace_regime",
        "content_hash",
    )


def _event_body(event: R6QualificationLifecycleEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_version": event.event_version,
        "assessment_id": event.qualification_ref.assessment_id,
        "assessment_hash": event.qualification_ref.assessment_hash,
        "authorization_id": event.authorization_id,
        "authorization_version": event.authorization_version,
        "authorization_hash": event.authorization_hash,
        "action": event.action.value,
        "sequence": event.sequence,
        "occurred_at": _datetime_text(event.occurred_at),
        "recorded_at": _datetime_text(event.recorded_at),
        "previous_event_hash": event.previous_event_hash,
        "reason_codes": list(event.reason_codes),
        "research_only": event.research_only,
        "must_not_use_for_decision": event.must_not_use_for_decision,
        "must_not_replace_regime": event.must_not_replace_regime,
        "content_hash": event.content_hash,
    }


def encode_r6_qualification_event(event: R6QualificationLifecycleEvent) -> dict[str, object]:
    """Encode one immutable lifecycle event."""

    return {"schema": _EVENT_SCHEMA, "body": _event_body(event)}


def decode_r6_qualification_event(payload: object) -> R6QualificationLifecycleEvent:
    """Strictly decode one immutable lifecycle event."""

    envelope = _object(payload, "R6 qualification event envelope")
    _keys(envelope, {"schema", "body"}, "R6 qualification event envelope")
    if envelope["schema"] != _EVENT_SCHEMA:
        raise R6QualificationCodecError("unsupported R6 qualification event schema")
    body = _object(envelope["body"], "R6 qualification event body")
    expected = {
        "event_id",
        "event_version",
        "assessment_id",
        "assessment_hash",
        "authorization_id",
        "authorization_version",
        "authorization_hash",
        "action",
        "sequence",
        "occurred_at",
        "recorded_at",
        "previous_event_hash",
        "reason_codes",
        "research_only",
        "must_not_use_for_decision",
        "must_not_replace_regime",
        "content_hash",
    }
    _keys(body, expected, "R6 qualification event body")
    try:
        event = R6QualificationLifecycleEvent(
            event_id=_string(body["event_id"], "event_id"),
            event_version=_string(body["event_version"], "event_version"),
            qualification_ref=R6QualificationRef(
                _string(body["assessment_id"], "assessment_id"),
                _hash(body["assessment_hash"], "assessment_hash"),
            ),
            authorization_id=_string(body["authorization_id"], "authorization_id"),
            authorization_version=_string(body["authorization_version"], "authorization_version"),
            authorization_hash=_hash(body["authorization_hash"], "authorization_hash"),
            action=R6QualificationLifecycleAction(_string(body["action"], "action")),
            sequence=_integer(body["sequence"], "sequence"),
            occurred_at=_datetime(body["occurred_at"], "occurred_at"),
            recorded_at=_datetime(body["recorded_at"], "recorded_at"),
            previous_event_hash=(
                None
                if body["previous_event_hash"] is None
                else _hash(body["previous_event_hash"], "previous_event_hash")
            ),
            reason_codes=tuple(
                _string(item, "reason_code") for item in _list(body["reason_codes"], "reason_codes")
            ),
            research_only=_boolean(body["research_only"], "research_only"),
            must_not_use_for_decision=_boolean(
                body["must_not_use_for_decision"], "must_not_use_for_decision"
            ),
            must_not_replace_regime=_boolean(
                body["must_not_replace_regime"], "must_not_replace_regime"
            ),
        )
    except (TypeError, ValueError) as error:
        raise R6QualificationCodecError("R6 qualification event restore failed") from error
    if event.content_hash != _hash(body["content_hash"], "content_hash"):
        raise R6QualificationCodecError("R6 qualification event content hash mismatch")
    if encode_r6_qualification_event(event) != envelope:
        raise R6QualificationCodecError("R6 qualification event payload is non-canonical")
    return event


__all__ = [
    "R6QualificationCodecError",
    "decode_r6_qualification_assessment",
    "decode_r6_qualification_authorization",
    "decode_r6_qualification_event",
    "encode_r6_qualification_assessment",
    "encode_r6_qualification_authorization",
    "encode_r6_qualification_event",
]
