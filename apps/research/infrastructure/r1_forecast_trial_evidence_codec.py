"""Strict canonical codec for the Research R1 trial evidence ledger."""

from __future__ import annotations

from datetime import date, datetime
from typing import cast

from apps.equity.domain.forecast_baseline import (
    ActualRevisionRule,
    ActualVintageRule,
    ForecastEvaluationPolicy,
    ForecastFreezeRule,
)
from apps.research.domain.r1_forecast_trial_evidence import (
    PersistedR1ForecastTrialEvidence,
    R1ForecastTrialDefinition,
)


class R1ForecastTrialEvidenceCodecError(ValueError):
    """Stored payload is malformed, non-canonical, or has a broken live seal."""


def encode_r1_forecast_trial_evidence(
    evidence: PersistedR1ForecastTrialEvidence,
) -> dict[str, object]:
    """Encode one fully sealed receipt without dropping audit fields."""

    if type(evidence) is not PersistedR1ForecastTrialEvidence:
        raise R1ForecastTrialEvidenceCodecError("evidence type differs")
    PersistedR1ForecastTrialEvidence.__post_init__(evidence)
    return {
        "schema": "research-r1-forecast-trial-evidence-ledger.v1",
        "evidence_id": evidence.evidence_id,
        "evidence_version": evidence.evidence_version,
        "definition": _encode_definition(evidence.definition),
        "baseline_spec_approved_at": evidence.baseline_spec_approved_at.isoformat(),
        "forecast_origin_at": evidence.forecast_origin_at.isoformat(),
        "recorded_at": evidence.recorded_at.isoformat(),
        "content_hash": evidence.content_hash,
        "research_only": evidence.research_only,
        "must_not_use_for_decision": evidence.must_not_use_for_decision,
        "must_not_execute": evidence.must_not_execute,
    }


def decode_r1_forecast_trial_evidence(
    raw: object,
) -> PersistedR1ForecastTrialEvidence:
    """Decode and recompute every nested seal, rejecting extra or missing keys."""

    try:
        payload = _mapping(
            raw,
            {
                "schema",
                "evidence_id",
                "evidence_version",
                "definition",
                "baseline_spec_approved_at",
                "forecast_origin_at",
                "recorded_at",
                "content_hash",
                "research_only",
                "must_not_use_for_decision",
                "must_not_execute",
            },
            "evidence",
        )
        if payload["schema"] != "research-r1-forecast-trial-evidence-ledger.v1":
            raise ValueError("evidence schema differs")
        definition = _decode_definition(payload["definition"])
        evidence = PersistedR1ForecastTrialEvidence.create(
            evidence_id=_text(payload["evidence_id"], "evidence_id"),
            evidence_version=_text(payload["evidence_version"], "evidence_version"),
            definition=definition,
            baseline_spec_approved_at=_datetime(
                payload["baseline_spec_approved_at"], "baseline_spec_approved_at"
            ),
            forecast_origin_at=_datetime(payload["forecast_origin_at"], "forecast_origin_at"),
            recorded_at=_datetime(payload["recorded_at"], "recorded_at"),
        )
        if (
            evidence.content_hash != _text(payload["content_hash"], "content_hash")
            or payload["research_only"] is not True
            or payload["must_not_use_for_decision"] is not True
            or payload["must_not_execute"] is not True
        ):
            raise ValueError("evidence seal or safety flags differ")
        return evidence
    except R1ForecastTrialEvidenceCodecError:
        raise
    except Exception as error:
        raise R1ForecastTrialEvidenceCodecError("R1 trial evidence payload is invalid") from error


def _encode_definition(definition: R1ForecastTrialDefinition) -> dict[str, object]:
    R1ForecastTrialDefinition.__post_init__(definition)
    policy = definition.evaluation_policy
    return {
        "schema": "research-r1-forecast-trial-definition.v1",
        "definition_id": definition.definition_id,
        "definition_version": definition.definition_version,
        "owner": definition.owner,
        "capability": definition.capability,
        "purpose": definition.purpose,
        "status": definition.status,
        "baseline_spec_id": definition.baseline_spec_id,
        "baseline_spec_version": definition.baseline_spec_version,
        "baseline_spec_content_hash": definition.baseline_spec_content_hash,
        "baseline_artifact_id": definition.baseline_artifact_id,
        "baseline_artifact_version": definition.baseline_artifact_version,
        "baseline_artifact_content_hash": definition.baseline_artifact_content_hash,
        "split_spec_hash": definition.split_spec_hash,
        "parameter_hash": definition.parameter_hash,
        "calendar_id": definition.calendar_id,
        "calendar_version": definition.calendar_version,
        "calendar_schedule_hash": definition.calendar_schedule_hash,
        "expected_period_ends": [item.isoformat() for item in definition.expected_period_ends],
        "metric_codes": list(definition.metric_codes),
        "evaluation_keys": [
            [period_end.isoformat(), metric_code]
            for period_end, metric_code in definition.evaluation_keys
        ],
        "evaluation_policy": {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "policy_content_hash": policy.policy_content_hash,
            "owner": policy.owner,
            "actual_dataset": policy.actual_dataset,
            "actual_knowledge_scope": policy.actual_knowledge_scope,
            "actual_revision_rule": policy.actual_revision_rule.value,
            "actual_vintage_rule": policy.actual_vintage_rule.value,
            "forecast_freeze_rule": policy.forecast_freeze_rule.value,
            "forecast_knowledge_cutoff_at": policy.forecast_knowledge_cutoff_at.isoformat(),
            "forecast_submission_deadline_at": policy.forecast_submission_deadline_at.isoformat(),
            "valid_until": policy.valid_until.isoformat(),
        },
        "activated_at": definition.activated_at.isoformat(),
        "valid_until": definition.valid_until.isoformat(),
        "content_hash": definition.content_hash,
        "research_only": definition.research_only,
        "must_not_use_for_decision": definition.must_not_use_for_decision,
        "must_not_execute": definition.must_not_execute,
    }


def _decode_definition(raw: object) -> R1ForecastTrialDefinition:
    payload = _mapping(
        raw,
        {
            "schema",
            "definition_id",
            "definition_version",
            "owner",
            "capability",
            "purpose",
            "status",
            "baseline_spec_id",
            "baseline_spec_version",
            "baseline_spec_content_hash",
            "baseline_artifact_id",
            "baseline_artifact_version",
            "baseline_artifact_content_hash",
            "split_spec_hash",
            "parameter_hash",
            "calendar_id",
            "calendar_version",
            "calendar_schedule_hash",
            "expected_period_ends",
            "metric_codes",
            "evaluation_keys",
            "evaluation_policy",
            "activated_at",
            "valid_until",
            "content_hash",
            "research_only",
            "must_not_use_for_decision",
            "must_not_execute",
        },
        "definition",
    )
    if payload["schema"] != "research-r1-forecast-trial-definition.v1":
        raise R1ForecastTrialEvidenceCodecError("definition schema differs")
    policy_payload = _mapping(
        payload["evaluation_policy"],
        {
            "policy_id",
            "policy_version",
            "policy_content_hash",
            "owner",
            "actual_dataset",
            "actual_knowledge_scope",
            "actual_revision_rule",
            "actual_vintage_rule",
            "forecast_freeze_rule",
            "forecast_knowledge_cutoff_at",
            "forecast_submission_deadline_at",
            "valid_until",
        },
        "evaluation_policy",
    )
    policy = ForecastEvaluationPolicy.create(
        policy_id=_text(policy_payload["policy_id"], "policy_id"),
        policy_version=_text(policy_payload["policy_version"], "policy_version"),
        owner=_text(policy_payload["owner"], "policy owner"),
        actual_dataset=_text(policy_payload["actual_dataset"], "actual_dataset"),
        actual_knowledge_scope=_text(
            policy_payload["actual_knowledge_scope"], "actual_knowledge_scope"
        ),
        actual_revision_rule=ActualRevisionRule(
            _text(policy_payload["actual_revision_rule"], "actual_revision_rule")
        ),
        actual_vintage_rule=ActualVintageRule(
            _text(policy_payload["actual_vintage_rule"], "actual_vintage_rule")
        ),
        forecast_freeze_rule=ForecastFreezeRule(
            _text(policy_payload["forecast_freeze_rule"], "forecast_freeze_rule")
        ),
        forecast_knowledge_cutoff_at=_datetime(
            policy_payload["forecast_knowledge_cutoff_at"],
            "forecast_knowledge_cutoff_at",
        ),
        forecast_submission_deadline_at=_datetime(
            policy_payload["forecast_submission_deadline_at"],
            "forecast_submission_deadline_at",
        ),
        valid_until=_datetime(policy_payload["valid_until"], "policy valid_until"),
    )
    if policy.policy_content_hash != _text(
        policy_payload["policy_content_hash"], "policy_content_hash"
    ):
        raise R1ForecastTrialEvidenceCodecError("evaluation policy seal differs")
    periods = tuple(
        _date(item, "expected_period_end")
        for item in _sequence(payload["expected_period_ends"], "expected_period_ends")
    )
    metrics = tuple(
        _text(item, "metric_code") for item in _sequence(payload["metric_codes"], "metric_codes")
    )
    raw_keys = _sequence(payload["evaluation_keys"], "evaluation_keys")
    keys: list[tuple[date, str]] = []
    for raw_key in raw_keys:
        key = _sequence(raw_key, "evaluation_key")
        if len(key) != 2:
            raise R1ForecastTrialEvidenceCodecError("evaluation key shape differs")
        keys.append((_date(key[0], "evaluation period"), _text(key[1], "evaluation metric")))
    definition = R1ForecastTrialDefinition.create(
        definition_id=_text(payload["definition_id"], "definition_id"),
        definition_version=_text(payload["definition_version"], "definition_version"),
        baseline_spec_id=_text(payload["baseline_spec_id"], "baseline_spec_id"),
        baseline_spec_version=_text(payload["baseline_spec_version"], "baseline_spec_version"),
        baseline_spec_content_hash=_text(
            payload["baseline_spec_content_hash"], "baseline_spec_content_hash"
        ),
        baseline_artifact_id=_text(payload["baseline_artifact_id"], "baseline_artifact_id"),
        baseline_artifact_version=_text(
            payload["baseline_artifact_version"], "baseline_artifact_version"
        ),
        baseline_artifact_content_hash=_text(
            payload["baseline_artifact_content_hash"], "baseline_artifact_content_hash"
        ),
        split_spec_hash=_text(payload["split_spec_hash"], "split_spec_hash"),
        parameter_hash=_text(payload["parameter_hash"], "parameter_hash"),
        calendar_id=_text(payload["calendar_id"], "calendar_id"),
        calendar_version=_text(payload["calendar_version"], "calendar_version"),
        calendar_schedule_hash=_text(payload["calendar_schedule_hash"], "calendar_schedule_hash"),
        expected_period_ends=periods,
        metric_codes=metrics,
        evaluation_policy=policy,
        activated_at=_datetime(payload["activated_at"], "activated_at"),
        valid_until=_datetime(payload["valid_until"], "valid_until"),
    )
    if (
        definition.evaluation_keys != tuple(keys)
        or definition.content_hash != _text(payload["content_hash"], "definition hash")
        or payload["owner"] != "research"
        or payload["capability"] != "r1"
        or payload["purpose"] != "valuation"
        or payload["status"] != "running"
        or payload["research_only"] is not True
        or payload["must_not_use_for_decision"] is not True
        or payload["must_not_execute"] is not True
    ):
        raise R1ForecastTrialEvidenceCodecError("definition seal differs")
    return definition


def _mapping(value: object, keys: set[str], field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise R1ForecastTrialEvidenceCodecError(f"{field_name} must be an object")
    result = cast(dict[str, object], value)
    if set(result) != keys:
        raise R1ForecastTrialEvidenceCodecError(f"{field_name} keys differ")
    return result


def _sequence(value: object, field_name: str) -> list[object]:
    if type(value) is not list:
        raise R1ForecastTrialEvidenceCodecError(f"{field_name} must be a list")
    return cast(list[object], value)


def _text(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise R1ForecastTrialEvidenceCodecError(f"{field_name} must be text")
    return value


def _datetime(value: object, field_name: str) -> datetime:
    text = _text(value, field_name)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise R1ForecastTrialEvidenceCodecError(f"{field_name} must be aware")
    return parsed


def _date(value: object, field_name: str) -> date:
    return date.fromisoformat(_text(value, field_name))


__all__ = [
    "R1ForecastTrialEvidenceCodecError",
    "decode_r1_forecast_trial_evidence",
    "encode_r1_forecast_trial_evidence",
]
