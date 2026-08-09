"""Strict typed canonical codec for persisted R6 monitoring evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessment,
    R6MonitoringAssessmentStatus,
    R6MonitoringBlockerCode,
    R6MonitoringMetricKey,
    R6MonitoringMetricObservation,
    R6MonitoringMetricResult,
    R6MonitoringObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPeriodEntry,
    R6MonitoringPolicy,
    R6MonitoringThreshold,
    R6MonitoringThresholdDirection,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef


class R6MonitoringCodecError(ValueError):
    """Persisted R6 monitoring payload is malformed or non-canonical."""


_POLICY_SCHEMA = "research.r6.monitoring-policy.v2"
_CALENDAR_SCHEMA = "research.r6.monitoring-period-calendar.v1"
_OBSERVATION_SCHEMA = "research.r6.monitoring-observation.v1"
_ASSESSMENT_SCHEMA = "research.r6.monitoring-assessment.v1"


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise R6MonitoringCodecError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise R6MonitoringCodecError(f"{label} must be a list")
    return value


def _keys(value: dict[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise R6MonitoringCodecError(f"{label} keys are missing or extra")


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise R6MonitoringCodecError(f"{label} must be a string")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise R6MonitoringCodecError(f"{label} must be boolean")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise R6MonitoringCodecError(f"{label} must be integer")
    return value


def _decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise R6MonitoringCodecError("R6 monitoring Decimal must be finite")
    return format(value, "f")


def _decimal(value: object, label: str) -> Decimal:
    text = _string(value, label)
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise R6MonitoringCodecError(f"{label} must be Decimal text") from error
    if not parsed.is_finite() or _decimal_text(parsed) != text:
        raise R6MonitoringCodecError(f"{label} is non-canonical")
    return parsed


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R6MonitoringCodecError("R6 monitoring datetime must be aware")
    return value.astimezone(UTC).isoformat()


def _datetime(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise R6MonitoringCodecError(f"{label} must be ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or _datetime_text(parsed) != text:
        raise R6MonitoringCodecError(f"{label} is non-canonical")
    return parsed


def _hash(value: object, label: str) -> str:
    text = _string(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise R6MonitoringCodecError(f"{label} must be lowercase SHA-256")
    return text


def _qualification_ref_body(ref: R6QualificationRef) -> dict[str, object]:
    return {
        "assessment_id": ref.assessment_id,
        "assessment_hash": ref.assessment_hash.lower(),
    }


def _qualification_ref(value: object, label: str) -> R6QualificationRef:
    body = _object(value, label)
    _keys(body, {"assessment_id", "assessment_hash"}, label)
    return R6QualificationRef(
        _string(body["assessment_id"], f"{label}.assessment_id"),
        _hash(body["assessment_hash"], f"{label}.assessment_hash"),
    )


def encode_r6_monitoring_policy(policy: R6MonitoringPolicy) -> dict[str, object]:
    """Encode one complete policy in canonical threshold order."""

    body: dict[str, object] = {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "qualification_ref": _qualification_ref_body(policy.qualification_ref),
        "thresholds": [
            {
                "metric_key": item.metric_key.value,
                "unit": item.unit,
                "direction": item.direction.value,
                "breach_threshold": _decimal_text(item.breach_threshold),
                "retirement_review_consecutive_breaches": (
                    item.retirement_review_consecutive_breaches
                ),
            }
            for item in sorted(policy.thresholds, key=lambda value: value.metric_key.value)
        ],
        "minimum_observation_count": policy.minimum_observation_count,
        "maximum_observation_age_seconds": policy.maximum_observation_age_seconds,
        "label_protocol_version": policy.label_protocol_version,
        "expected_label_set_hash": policy.expected_label_set_hash.lower(),
        "expected_source_owner": policy.expected_source_owner,
        "expected_pit_manifest_id": policy.expected_pit_manifest_id,
        "expected_pit_manifest_hash": policy.expected_pit_manifest_hash.lower(),
        "expected_period_calendar_owner": policy.expected_period_calendar_owner,
        "expected_period_calendar_id": policy.expected_period_calendar_id,
        "expected_period_calendar_version": policy.expected_period_calendar_version,
        "expected_period_calendar_hash": policy.expected_period_calendar_hash.lower(),
        "expected_evidence_ref_prefix": policy.expected_evidence_ref_prefix,
        "recorded_at": _datetime_text(policy.recorded_at),
        "active_from": _datetime_text(policy.active_from),
        "active_until": _datetime_text(policy.active_until),
        "content_hash": policy.content_hash,
    }
    return {"schema": _POLICY_SCHEMA, "body": body}


def decode_r6_monitoring_policy(payload: object) -> R6MonitoringPolicy:
    """Rebuild and re-seal every policy threshold and owner binding."""

    envelope = _object(payload, "R6 monitoring policy envelope")
    _keys(envelope, {"schema", "body"}, "R6 monitoring policy envelope")
    if envelope["schema"] != _POLICY_SCHEMA:
        raise R6MonitoringCodecError("unsupported R6 monitoring policy schema")
    body = _object(envelope["body"], "R6 monitoring policy body")
    expected = {
        "policy_id",
        "policy_version",
        "qualification_ref",
        "thresholds",
        "minimum_observation_count",
        "maximum_observation_age_seconds",
        "label_protocol_version",
        "expected_label_set_hash",
        "expected_source_owner",
        "expected_pit_manifest_id",
        "expected_pit_manifest_hash",
        "expected_period_calendar_owner",
        "expected_period_calendar_id",
        "expected_period_calendar_version",
        "expected_period_calendar_hash",
        "expected_evidence_ref_prefix",
        "recorded_at",
        "active_from",
        "active_until",
        "content_hash",
    }
    _keys(body, expected, "R6 monitoring policy body")
    try:
        thresholds: list[R6MonitoringThreshold] = []
        for index, raw in enumerate(_list(body["thresholds"], "thresholds")):
            item = _object(raw, f"thresholds[{index}]")
            _keys(
                item,
                {
                    "metric_key",
                    "unit",
                    "direction",
                    "breach_threshold",
                    "retirement_review_consecutive_breaches",
                },
                f"thresholds[{index}]",
            )
            thresholds.append(
                R6MonitoringThreshold(
                    metric_key=R6MonitoringMetricKey(_string(item["metric_key"], "metric_key")),
                    unit=_string(item["unit"], "unit"),
                    direction=R6MonitoringThresholdDirection(
                        _string(item["direction"], "direction")
                    ),
                    breach_threshold=_decimal(item["breach_threshold"], "breach_threshold"),
                    retirement_review_consecutive_breaches=_integer(
                        item["retirement_review_consecutive_breaches"],
                        "retirement_review_consecutive_breaches",
                    ),
                )
            )
        restored = R6MonitoringPolicy(
            policy_id=_string(body["policy_id"], "policy_id"),
            policy_version=_string(body["policy_version"], "policy_version"),
            qualification_ref=_qualification_ref(body["qualification_ref"], "qualification_ref"),
            thresholds=tuple(thresholds),
            minimum_observation_count=_integer(
                body["minimum_observation_count"], "minimum_observation_count"
            ),
            maximum_observation_age_seconds=_integer(
                body["maximum_observation_age_seconds"],
                "maximum_observation_age_seconds",
            ),
            label_protocol_version=_string(
                body["label_protocol_version"], "label_protocol_version"
            ),
            expected_label_set_hash=_hash(
                body["expected_label_set_hash"], "expected_label_set_hash"
            ),
            expected_source_owner=_string(body["expected_source_owner"], "expected_source_owner"),
            expected_pit_manifest_id=_string(
                body["expected_pit_manifest_id"], "expected_pit_manifest_id"
            ),
            expected_pit_manifest_hash=_hash(
                body["expected_pit_manifest_hash"], "expected_pit_manifest_hash"
            ),
            expected_period_calendar_owner=_string(
                body["expected_period_calendar_owner"],
                "expected_period_calendar_owner",
            ),
            expected_period_calendar_id=_string(
                body["expected_period_calendar_id"], "expected_period_calendar_id"
            ),
            expected_period_calendar_version=_string(
                body["expected_period_calendar_version"],
                "expected_period_calendar_version",
            ),
            expected_period_calendar_hash=_hash(
                body["expected_period_calendar_hash"],
                "expected_period_calendar_hash",
            ),
            expected_evidence_ref_prefix=_string(
                body["expected_evidence_ref_prefix"],
                "expected_evidence_ref_prefix",
            ),
            recorded_at=_datetime(body["recorded_at"], "recorded_at"),
            active_from=_datetime(body["active_from"], "active_from"),
            active_until=_datetime(body["active_until"], "active_until"),
        )
    except R6MonitoringCodecError:
        raise
    except (TypeError, ValueError) as error:
        raise R6MonitoringCodecError("R6 monitoring policy restore failed") from error
    if restored.content_hash != _hash(body["content_hash"], "content_hash"):
        raise R6MonitoringCodecError("R6 monitoring policy content hash mismatch")
    if encode_r6_monitoring_policy(restored) != envelope:
        raise R6MonitoringCodecError("R6 monitoring policy payload is non-canonical")
    return restored


def encode_r6_monitoring_period_calendar(
    calendar: R6MonitoringPeriodCalendar,
) -> dict[str, object]:
    """Encode an owner-recorded calendar and every exact member."""

    body: dict[str, object] = {
        "source_owner": calendar.source_owner,
        "calendar_id": calendar.calendar_id,
        "calendar_version": calendar.calendar_version,
        "recorded_at": _datetime_text(calendar.recorded_at),
        "valid_from": _datetime_text(calendar.valid_from),
        "valid_until": _datetime_text(calendar.valid_until),
        "entries": [
            {
                "period_id": item.period_id,
                "period_start": _datetime_text(item.period_start),
                "period_end": _datetime_text(item.period_end),
            }
            for item in sorted(
                calendar.entries,
                key=lambda value: (
                    value.period_start,
                    value.period_end,
                    value.period_id,
                ),
            )
        ],
        "content_hash": calendar.content_hash,
    }
    return {"schema": _CALENDAR_SCHEMA, "body": body}


def decode_r6_monitoring_period_calendar(
    payload: object,
) -> R6MonitoringPeriodCalendar:
    """Rebuild every calendar member and revalidate the manifest seal."""

    envelope = _object(payload, "R6 monitoring calendar envelope")
    _keys(envelope, {"schema", "body"}, "R6 monitoring calendar envelope")
    if envelope["schema"] != _CALENDAR_SCHEMA:
        raise R6MonitoringCodecError("unsupported R6 monitoring calendar schema")
    body = _object(envelope["body"], "R6 monitoring calendar body")
    _keys(
        body,
        {
            "source_owner",
            "calendar_id",
            "calendar_version",
            "recorded_at",
            "valid_from",
            "valid_until",
            "entries",
            "content_hash",
        },
        "R6 monitoring calendar body",
    )
    try:
        entries: list[R6MonitoringPeriodEntry] = []
        for index, raw in enumerate(_list(body["entries"], "entries")):
            item = _object(raw, f"entries[{index}]")
            _keys(
                item,
                {"period_id", "period_start", "period_end"},
                f"entries[{index}]",
            )
            entries.append(
                R6MonitoringPeriodEntry(
                    period_id=_hash(item["period_id"], "period_id"),
                    period_start=_datetime(item["period_start"], "period_start"),
                    period_end=_datetime(item["period_end"], "period_end"),
                )
            )
        restored = R6MonitoringPeriodCalendar(
            source_owner=_string(body["source_owner"], "source_owner"),
            calendar_id=_string(body["calendar_id"], "calendar_id"),
            calendar_version=_string(body["calendar_version"], "calendar_version"),
            recorded_at=_datetime(body["recorded_at"], "recorded_at"),
            valid_from=_datetime(body["valid_from"], "valid_from"),
            valid_until=_datetime(body["valid_until"], "valid_until"),
            entries=tuple(entries),
        )
    except R6MonitoringCodecError:
        raise
    except (TypeError, ValueError) as error:
        raise R6MonitoringCodecError("R6 monitoring calendar restore failed") from error
    if restored.content_hash != _hash(body["content_hash"], "content_hash"):
        raise R6MonitoringCodecError("R6 monitoring calendar content hash mismatch")
    if encode_r6_monitoring_period_calendar(restored) != envelope:
        raise R6MonitoringCodecError("R6 monitoring calendar payload is non-canonical")
    return restored


def encode_r6_monitoring_observation(
    observation: R6MonitoringObservation,
) -> dict[str, object]:
    """Encode one raw observation as a canonical metric set."""

    body: dict[str, object] = {
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "observation_period_id": observation.observation_period_id,
        "period_calendar_id": observation.period_calendar_id,
        "period_calendar_version": observation.period_calendar_version,
        "period_calendar_hash": observation.period_calendar_hash.lower(),
        "period_start": _datetime_text(observation.period_start),
        "period_end": _datetime_text(observation.period_end),
        "qualification_ref": _qualification_ref_body(observation.qualification_ref),
        "policy_id": observation.policy_id,
        "policy_version": observation.policy_version,
        "policy_hash": observation.policy_hash.lower(),
        "source_owner": observation.source_owner,
        "observed_at": _datetime_text(observation.observed_at),
        "available_at": _datetime_text(observation.available_at),
        "recorded_at": _datetime_text(observation.recorded_at),
        "valid_until": _datetime_text(observation.valid_until),
        "pit_manifest_id": observation.pit_manifest_id,
        "pit_manifest_hash": observation.pit_manifest_hash.lower(),
        "evidence_ref": observation.evidence_ref,
        "label_protocol_version": observation.label_protocol_version,
        "observed_label_set_hash": observation.observed_label_set_hash.lower(),
        "metrics": [
            {
                "metric_key": item.metric_key.value,
                "unit": item.unit,
                "value": _decimal_text(item.value),
            }
            for item in sorted(observation.metrics, key=lambda value: value.metric_key.value)
        ],
        "research_only": observation.research_only,
        "must_not_use_for_decision": observation.must_not_use_for_decision,
        "must_not_replace_regime": observation.must_not_replace_regime,
        "must_not_publish_current": observation.must_not_publish_current,
        "must_not_execute": observation.must_not_execute,
        "content_hash": observation.content_hash,
    }
    return {"schema": _OBSERVATION_SCHEMA, "body": body}


def decode_r6_monitoring_observation(payload: object) -> R6MonitoringObservation:
    """Rebuild every raw metric and revalidate its owner/content seal."""

    envelope = _object(payload, "R6 monitoring observation envelope")
    _keys(envelope, {"schema", "body"}, "R6 monitoring observation envelope")
    if envelope["schema"] != _OBSERVATION_SCHEMA:
        raise R6MonitoringCodecError("unsupported R6 monitoring observation schema")
    body = _object(envelope["body"], "R6 monitoring observation body")
    expected = {
        "observation_id",
        "observation_version",
        "observation_period_id",
        "period_calendar_id",
        "period_calendar_version",
        "period_calendar_hash",
        "period_start",
        "period_end",
        "qualification_ref",
        "policy_id",
        "policy_version",
        "policy_hash",
        "source_owner",
        "observed_at",
        "available_at",
        "recorded_at",
        "valid_until",
        "pit_manifest_id",
        "pit_manifest_hash",
        "evidence_ref",
        "label_protocol_version",
        "observed_label_set_hash",
        "metrics",
        "research_only",
        "must_not_use_for_decision",
        "must_not_replace_regime",
        "must_not_publish_current",
        "must_not_execute",
        "content_hash",
    }
    _keys(body, expected, "R6 monitoring observation body")
    try:
        metrics: list[R6MonitoringMetricObservation] = []
        for index, raw in enumerate(_list(body["metrics"], "metrics")):
            item = _object(raw, f"metrics[{index}]")
            _keys(item, {"metric_key", "unit", "value"}, f"metrics[{index}]")
            metrics.append(
                R6MonitoringMetricObservation(
                    metric_key=R6MonitoringMetricKey(_string(item["metric_key"], "metric_key")),
                    unit=_string(item["unit"], "unit"),
                    value=_decimal(item["value"], "value"),
                )
            )
        restored = R6MonitoringObservation(
            observation_id=_string(body["observation_id"], "observation_id"),
            observation_version=_string(body["observation_version"], "observation_version"),
            observation_period_id=_hash(body["observation_period_id"], "observation_period_id"),
            period_calendar_id=_string(body["period_calendar_id"], "period_calendar_id"),
            period_calendar_version=_string(
                body["period_calendar_version"], "period_calendar_version"
            ),
            period_calendar_hash=_hash(body["period_calendar_hash"], "period_calendar_hash"),
            period_start=_datetime(body["period_start"], "period_start"),
            period_end=_datetime(body["period_end"], "period_end"),
            qualification_ref=_qualification_ref(body["qualification_ref"], "qualification_ref"),
            policy_id=_string(body["policy_id"], "policy_id"),
            policy_version=_string(body["policy_version"], "policy_version"),
            policy_hash=_hash(body["policy_hash"], "policy_hash"),
            source_owner=_string(body["source_owner"], "source_owner"),
            observed_at=_datetime(body["observed_at"], "observed_at"),
            available_at=_datetime(body["available_at"], "available_at"),
            recorded_at=_datetime(body["recorded_at"], "recorded_at"),
            valid_until=_datetime(body["valid_until"], "valid_until"),
            pit_manifest_id=_string(body["pit_manifest_id"], "pit_manifest_id"),
            pit_manifest_hash=_hash(body["pit_manifest_hash"], "pit_manifest_hash"),
            evidence_ref=_string(body["evidence_ref"], "evidence_ref"),
            label_protocol_version=_string(
                body["label_protocol_version"], "label_protocol_version"
            ),
            observed_label_set_hash=_hash(
                body["observed_label_set_hash"], "observed_label_set_hash"
            ),
            metrics=tuple(metrics),
            research_only=_boolean(body["research_only"], "research_only"),
            must_not_use_for_decision=_boolean(
                body["must_not_use_for_decision"], "must_not_use_for_decision"
            ),
            must_not_replace_regime=_boolean(
                body["must_not_replace_regime"], "must_not_replace_regime"
            ),
            must_not_publish_current=_boolean(
                body["must_not_publish_current"], "must_not_publish_current"
            ),
            must_not_execute=_boolean(body["must_not_execute"], "must_not_execute"),
        )
    except R6MonitoringCodecError:
        raise
    except (TypeError, ValueError) as error:
        raise R6MonitoringCodecError("R6 monitoring observation restore failed") from error
    if restored.content_hash != _hash(body["content_hash"], "content_hash"):
        raise R6MonitoringCodecError("R6 monitoring observation content hash mismatch")
    if encode_r6_monitoring_observation(restored) != envelope:
        raise R6MonitoringCodecError("R6 monitoring observation payload is non-canonical")
    return restored


def encode_r6_monitoring_assessment(
    assessment: R6MonitoringAssessment,
) -> dict[str, object]:
    """Encode one recomputed research-only assessment."""

    body: dict[str, object] = {
        "qualification_ref": _qualification_ref_body(assessment.qualification_ref),
        "requested_policy_id": assessment.requested_policy_id,
        "requested_policy_version": assessment.requested_policy_version,
        "expected_policy_hash": assessment.expected_policy_hash.lower(),
        "qualification_content_hash": assessment.qualification_content_hash,
        "policy_hash": assessment.policy_hash,
        "evaluated_at": _datetime_text(assessment.evaluated_at),
        "status": assessment.status.value,
        "observation_hashes": list(assessment.observation_hashes),
        "metric_results": [
            {
                "metric_key": item.metric_key.value,
                "unit": item.unit,
                "latest_value": _decimal_text(item.latest_value),
                "breach_threshold": _decimal_text(item.breach_threshold),
                "direction": item.direction.value,
                "latest_breached": item.latest_breached,
                "trailing_consecutive_breaches": item.trailing_consecutive_breaches,
                "retirement_review_consecutive_breaches": (
                    item.retirement_review_consecutive_breaches
                ),
            }
            for item in assessment.metric_results
        ],
        "blockers": [item.value for item in assessment.blockers],
        "label_drift_detected": assessment.label_drift_detected,
        "retirement_review_required": assessment.retirement_review_required,
        "automatic_retirement": assessment.automatic_retirement,
        "research_only": assessment.research_only,
        "must_not_use_for_decision": assessment.must_not_use_for_decision,
        "must_not_replace_regime": assessment.must_not_replace_regime,
        "must_not_publish_current": assessment.must_not_publish_current,
        "must_not_execute": assessment.must_not_execute,
        "content_hash": assessment.content_hash,
    }
    return {"schema": _ASSESSMENT_SCHEMA, "body": body}


def decode_r6_monitoring_assessment(payload: object) -> R6MonitoringAssessment:
    """Rebuild every metric result/blocker and revalidate the assessment seal."""

    envelope = _object(payload, "R6 monitoring assessment envelope")
    _keys(envelope, {"schema", "body"}, "R6 monitoring assessment envelope")
    if envelope["schema"] != _ASSESSMENT_SCHEMA:
        raise R6MonitoringCodecError("unsupported R6 monitoring assessment schema")
    body = _object(envelope["body"], "R6 monitoring assessment body")
    expected = {
        "qualification_ref",
        "requested_policy_id",
        "requested_policy_version",
        "expected_policy_hash",
        "qualification_content_hash",
        "policy_hash",
        "evaluated_at",
        "status",
        "observation_hashes",
        "metric_results",
        "blockers",
        "label_drift_detected",
        "retirement_review_required",
        "automatic_retirement",
        "research_only",
        "must_not_use_for_decision",
        "must_not_replace_regime",
        "must_not_publish_current",
        "must_not_execute",
        "content_hash",
    }
    _keys(body, expected, "R6 monitoring assessment body")
    try:
        results: list[R6MonitoringMetricResult] = []
        for index, raw in enumerate(_list(body["metric_results"], "metric_results")):
            item = _object(raw, f"metric_results[{index}]")
            _keys(
                item,
                {
                    "metric_key",
                    "unit",
                    "latest_value",
                    "breach_threshold",
                    "direction",
                    "latest_breached",
                    "trailing_consecutive_breaches",
                    "retirement_review_consecutive_breaches",
                },
                f"metric_results[{index}]",
            )
            results.append(
                R6MonitoringMetricResult(
                    metric_key=R6MonitoringMetricKey(_string(item["metric_key"], "metric_key")),
                    unit=_string(item["unit"], "unit"),
                    latest_value=_decimal(item["latest_value"], "latest_value"),
                    breach_threshold=_decimal(item["breach_threshold"], "breach_threshold"),
                    direction=R6MonitoringThresholdDirection(
                        _string(item["direction"], "direction")
                    ),
                    latest_breached=_boolean(item["latest_breached"], "latest_breached"),
                    trailing_consecutive_breaches=_integer(
                        item["trailing_consecutive_breaches"],
                        "trailing_consecutive_breaches",
                    ),
                    retirement_review_consecutive_breaches=_integer(
                        item["retirement_review_consecutive_breaches"],
                        "retirement_review_consecutive_breaches",
                    ),
                )
            )
        restored = R6MonitoringAssessment(
            qualification_ref=_qualification_ref(body["qualification_ref"], "qualification_ref"),
            requested_policy_id=_string(body["requested_policy_id"], "requested_policy_id"),
            requested_policy_version=_string(
                body["requested_policy_version"], "requested_policy_version"
            ),
            expected_policy_hash=_hash(body["expected_policy_hash"], "expected_policy_hash"),
            qualification_content_hash=(
                None
                if body["qualification_content_hash"] is None
                else _hash(
                    body["qualification_content_hash"],
                    "qualification_content_hash",
                )
            ),
            policy_hash=(
                None if body["policy_hash"] is None else _hash(body["policy_hash"], "policy_hash")
            ),
            evaluated_at=_datetime(body["evaluated_at"], "evaluated_at"),
            status=R6MonitoringAssessmentStatus(_string(body["status"], "status")),
            observation_hashes=tuple(
                _hash(item, f"observation_hashes[{index}]")
                for index, item in enumerate(
                    _list(body["observation_hashes"], "observation_hashes")
                )
            ),
            metric_results=tuple(results),
            blockers=tuple(
                R6MonitoringBlockerCode(_string(item, f"blockers[{index}]"))
                for index, item in enumerate(_list(body["blockers"], "blockers"))
            ),
            label_drift_detected=_boolean(body["label_drift_detected"], "label_drift_detected"),
            retirement_review_required=_boolean(
                body["retirement_review_required"],
                "retirement_review_required",
            ),
            automatic_retirement=_boolean(body["automatic_retirement"], "automatic_retirement"),
            research_only=_boolean(body["research_only"], "research_only"),
            must_not_use_for_decision=_boolean(
                body["must_not_use_for_decision"], "must_not_use_for_decision"
            ),
            must_not_replace_regime=_boolean(
                body["must_not_replace_regime"], "must_not_replace_regime"
            ),
            must_not_publish_current=_boolean(
                body["must_not_publish_current"], "must_not_publish_current"
            ),
            must_not_execute=_boolean(body["must_not_execute"], "must_not_execute"),
        )
    except R6MonitoringCodecError:
        raise
    except (TypeError, ValueError) as error:
        raise R6MonitoringCodecError("R6 monitoring assessment restore failed") from error
    if restored.content_hash != _hash(body["content_hash"], "content_hash"):
        raise R6MonitoringCodecError("R6 monitoring assessment content hash mismatch")
    if encode_r6_monitoring_assessment(restored) != envelope:
        raise R6MonitoringCodecError("R6 monitoring assessment payload is non-canonical")
    return restored


__all__ = [
    "R6MonitoringCodecError",
    "decode_r6_monitoring_assessment",
    "decode_r6_monitoring_observation",
    "decode_r6_monitoring_period_calendar",
    "decode_r6_monitoring_policy",
    "encode_r6_monitoring_assessment",
    "encode_r6_monitoring_observation",
    "encode_r6_monitoring_period_calendar",
    "encode_r6_monitoring_policy",
]
