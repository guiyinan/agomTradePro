"""Canonical row seals and restoration helpers for R8 monitoring ledgers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast

from apps.portfolio.application.governed_optimization_monitoring_persistence import (
    GovernedOptimizationMonitoringPersistedAssessment,
    GovernedOptimizationMonitoringPersistenceCorruption,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.governed_optimization_monitoring import (
    ActiveGovernedOptimizationResultEvidence,
    GovernedOptimizationMonitoringAssessment,
    GovernedOptimizationMonitoringCalendar,
    GovernedOptimizationMonitoringPolicy,
    OptimizationMonitoringPeriodObservation,
    OptimizationMonitoringSourceEvidence,
)
from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_audit_codec import (
    _GovernedOptimizationMonitoringAuditSnapshot,
    decode_monitoring_audit_snapshot,
    encode_monitoring_audit_snapshot,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_codec import (
    encode_monitoring_assessment,
    encode_monitoring_calendar,
    encode_monitoring_observation,
    encode_monitoring_policy,
    encode_monitoring_promotions,
    encode_monitoring_source_evidence,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_models import (
    GovernedOptimizationMonitoringAuditSnapshotModel,
    GovernedOptimizationMonitoringObservationModel,
)


def _aware_utc(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise GovernedOptimizationMonitoringPersistenceCorruption(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _ledger_value(value: object) -> object:
    if isinstance(value, datetime):
        return _aware_utc(value, "R8 monitoring ledger datetime").isoformat()
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring ledger keys must be strings"
            )
        typed_mapping = cast(dict[str, object], mapping)
        return {
            key: _ledger_value(item)
            for key, item in sorted(typed_mapping.items(), key=lambda pair: pair[0])
        }
    if type(value) in {list, tuple}:
        items = cast(list[object] | tuple[object, ...], value)
        return [_ledger_value(item) for item in items]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise GovernedOptimizationMonitoringPersistenceCorruption(
        f"unsupported R8 monitoring ledger value: {type(value).__name__}"
    )


def _ledger_header_hash(*, row_kind: str, values: dict[str, object]) -> str:
    payload = {
        "schema": "governed-optimization-monitoring-ledger-header.v1",
        "row_kind": row_kind,
        "values": {
            key: _ledger_value(value)
            for key, value in sorted(values.items(), key=lambda item: item[0])
            if key != "ledger_header_hash"
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _require_model_values(
    *,
    model: object,
    values: dict[str, object],
    label: str,
) -> None:
    try:
        differs = any(
            getattr(model, field_name) != expected for field_name, expected in values.items()
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            f"R8 monitoring {label} row header is malformed"
        ) from exc
    if differs:
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            f"R8 monitoring {label} row header differs"
        )


def _persisted_observation_hash(
    assessment_id: str,
    observation: OptimizationMonitoringPeriodObservation,
) -> str:
    payload = {
        "schema": "governed-optimization-monitoring-observation-row.v1",
        "assessment_id": assessment_id,
        "domain_observation_hash": observation.content_hash,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _observation_row_matches_domain_values(
    model: GovernedOptimizationMonitoringObservationModel,
    values: dict[str, object],
) -> bool:
    ignored = {"ledger_header_hash", "ledger_recorded_at"}
    return all(getattr(model, key) == value for key, value in values.items() if key not in ignored)


def _observation_id(
    assessment_id: str,
    observation: OptimizationMonitoringPeriodObservation,
) -> str:
    return f"r8-monitoring-observation:{_persisted_observation_hash(assessment_id, observation)}"


def _winner_matches_domain_evidence(
    *,
    winner: GovernedOptimizationMonitoringPersistedAssessment,
    active_result: ActiveGovernedOptimizationResultEvidence,
    receipt: GovernedOptimizationInputReceipt,
    promotions: tuple[ExactPromotionAttestation, ...],
    policy: GovernedOptimizationMonitoringPolicy,
    calendar: GovernedOptimizationMonitoringCalendar,
    observations: tuple[OptimizationMonitoringPeriodObservation, ...],
    portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    assessment: GovernedOptimizationMonitoringAssessment,
) -> bool:
    return (
        winner.active_result == active_result
        and winner.receipt == receipt
        and winner.upstream_promotions == promotions
        and winner.policy == policy
        and winner.calendar == calendar
        and winner.observations == observations
        and winner.portfolio_evidence == portfolio_evidence
        and winner.broker_evidence == broker_evidence
        and winner.assessment == assessment
    )


def _owner_available_at(
    *groups: tuple[OptimizationMonitoringSourceEvidence, ...],
    observation: OptimizationMonitoringPeriodObservation,
) -> datetime:
    values = [item.available_at for group in groups for item in group]
    values.extend(item.available_at for item in observation.metrics)
    if not values:
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            "R8 monitoring owner evidence clocks are incomplete"
        )
    return max(values)


def _observation_values(
    *,
    result_row_id: str,
    receipt_row_id: str,
    assessment_id: str,
    result_hash: str,
    receipt_hash: str,
    policy_id: str,
    policy_version: str,
    policy_hash: str,
    calendar_id: str,
    calendar_version: str,
    calendar_hash: str,
    period_start_at: datetime,
    period_end_at: datetime,
    observation: OptimizationMonitoringPeriodObservation,
    portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    if not portfolio_evidence or not broker_evidence:
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            "R8 monitoring observation owner evidence is incomplete"
        )
    values: dict[str, object] = {
        "result_id": result_row_id,
        "input_receipt_id": receipt_row_id,
        "assessment_id": assessment_id,
        "observation_id": _observation_id(assessment_id, observation),
        "observation_version": observation.observation_version,
        "result_hash": result_hash,
        "receipt_hash": receipt_hash,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "policy_hash": policy_hash,
        "calendar_id": calendar_id,
        "calendar_version": calendar_version,
        "calendar_hash": calendar_hash,
        "period_id": observation.period_id,
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "latest_owner_available_at": _owner_available_at(
            portfolio_evidence,
            broker_evidence,
            observation=observation,
        ),
        "portfolio_evidence_payload": encode_monitoring_source_evidence(portfolio_evidence),
        "broker_evidence_payload": encode_monitoring_source_evidence(broker_evidence),
        "canonical_payload": encode_monitoring_observation(observation),
        "domain_observation_hash": observation.content_hash,
        "content_hash": _persisted_observation_hash(assessment_id, observation),
        "ledger_recorded_at": ledger_recorded_at,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _ledger_header_hash(
        row_kind="observation",
        values=values,
    )
    return values


def _assessment_values(
    *,
    result_row_id: str,
    receipt_row_id: str,
    active_result: ActiveGovernedOptimizationResultEvidence,
    receipt: GovernedOptimizationInputReceipt,
    promotions: tuple[ExactPromotionAttestation, ...],
    policy: GovernedOptimizationMonitoringPolicy,
    calendar: GovernedOptimizationMonitoringCalendar,
    observations: tuple[OptimizationMonitoringPeriodObservation, ...],
    portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    assessment: GovernedOptimizationMonitoringAssessment,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    owner_clocks = [
        receipt.recorded_at,
        policy.recorded_at,
        calendar.recorded_at,
        *(item.recorded_at for item in active_result.lifecycle_events),
        *(item.approved_at for item in promotions),
        *(item.available_at for item in portfolio_evidence),
        *(item.available_at for item in broker_evidence),
        *(metric.available_at for item in observations for metric in item.metrics),
    ]
    values: dict[str, object] = {
        "assessment_id": assessment.assessment_id,
        "assessment_version": assessment.assessment_version,
        "result_id": result_row_id,
        "input_receipt_id": receipt_row_id,
        "result_hash": active_result.result.content_hash,
        "receipt_hash": receipt.content_hash,
        "promotion_event_id": active_result.promotion_event_id,
        "promotion_event_hash": active_result.promotion_event_hash,
        "requested_policy_id": policy.policy_id,
        "requested_policy_version": policy.policy_version,
        "expected_policy_hash": policy.content_hash,
        "calendar_id": calendar.calendar_id,
        "calendar_version": calendar.calendar_version,
        "calendar_hash": calendar.content_hash,
        "evaluated_at": assessment.evaluated_at,
        "latest_owner_available_at": max(owner_clocks),
        "ledger_recorded_at": ledger_recorded_at,
        "status": assessment.status.value,
        "observation_count": len(observations),
        "observation_hashes": list(assessment.observation_hashes),
        "upstream_promotions_payload": encode_monitoring_promotions(promotions),
        "policy_payload": encode_monitoring_policy(policy),
        "calendar_payload": encode_monitoring_calendar(calendar),
        "assessment_payload": encode_monitoring_assessment(assessment),
        "content_hash": assessment.content_hash,
        "automatic_retirement": assessment.automatic_retirement,
        "research_only": assessment.research_only,
        "must_not_use_for_decision": assessment.must_not_use_for_decision,
        "must_not_publish_current": assessment.must_not_publish_current,
        "must_not_execute": assessment.must_not_execute,
    }
    values["ledger_header_hash"] = _ledger_header_hash(
        row_kind="assessment",
        values=values,
    )
    return values


def _snapshot_values(
    snapshot: _GovernedOptimizationMonitoringAuditSnapshot,
) -> dict[str, object]:
    values: dict[str, object] = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "entry_count": len(snapshot.entries),
        "canonical_payload": encode_monitoring_audit_snapshot(snapshot),
        "content_hash": snapshot.content_hash,
        "internal_audit_only": True,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _ledger_header_hash(
        row_kind="audit_snapshot",
        values=values,
    )
    return values


def _restore_snapshot(
    model: GovernedOptimizationMonitoringAuditSnapshotModel,
) -> _GovernedOptimizationMonitoringAuditSnapshot:
    snapshot = decode_monitoring_audit_snapshot(model.canonical_payload)
    _require_model_values(
        model=model,
        values=_snapshot_values(snapshot),
        label="audit snapshot",
    )
    return snapshot
