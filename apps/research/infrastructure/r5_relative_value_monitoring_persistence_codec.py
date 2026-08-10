"""Canonical row seals and restoration helpers for R5 monitoring ledgers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast

from apps.research.application.r5_relative_value_monitoring_persistence import (
    R5MonitoringPersistedAssessment,
    R5MonitoringPersistenceCorruption,
)
from apps.research.domain.r5_relative_value_monitoring import (
    R5PostPromotionMonitoringAssessment,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringCalendar,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringPolicy,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5PostPromotionMonitoringFact,
)
from apps.research.infrastructure.r5_relative_value_monitoring_audit_codec import (
    _R5MonitoringAuditSnapshot,
    decode_r5_monitoring_audit_snapshot,
    encode_r5_monitoring_audit_snapshot,
)
from apps.research.infrastructure.r5_relative_value_monitoring_codec import (
    encode_r5_monitoring_active_lifecycle,
    encode_r5_monitoring_assessment,
    encode_r5_monitoring_fact,
    encode_r5_monitoring_fixed_income,
    encode_r5_monitoring_period_calendar,
    encode_r5_monitoring_policy,
)
from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    R5MonitoringAuditSnapshotModel,
    R5MonitoringObservationLedgerModel,
)


def _aware_utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R5MonitoringPersistenceCorruption(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _ledger_value(value: object) -> object:
    if type(value) is datetime:
        return _aware_utc(value, "R5 monitoring ledger datetime").isoformat()
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise R5MonitoringPersistenceCorruption("R5 monitoring ledger keys must be strings")
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
    raise R5MonitoringPersistenceCorruption(
        f"unsupported R5 monitoring ledger value: {type(value).__name__}"
    )


def _ledger_header_hash(*, row_kind: str, values: dict[str, object]) -> str:
    payload = {
        "schema": "research-r5-monitoring-ledger-header.v1",
        "row_kind": row_kind,
        "values": {
            key: _ledger_value(value)
            for key, value in sorted(values.items(), key=lambda item: item[0])
            if key != "ledger_header_hash"
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _require_model_values(*, model: object, values: dict[str, object], label: str) -> None:
    try:
        differs = any(
            getattr(model, field_name) != expected for field_name, expected in values.items()
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise R5MonitoringPersistenceCorruption(
            f"R5 monitoring {label} row header is malformed"
        ) from error
    if differs:
        raise R5MonitoringPersistenceCorruption(f"R5 monitoring {label} row header differs")


def _persisted_fact_hash(
    assessment_id: str,
    fact: R5PostPromotionMonitoringFact,
) -> str:
    payload = {
        "schema": "research-r5-monitoring-observation-row.v1",
        "assessment_id": assessment_id,
        "domain_fact_hash": fact.content_hash,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _winner_matches_domain_evidence(
    *,
    winner: R5MonitoringPersistedAssessment,
    active: R5MonitoringActiveLifecycle,
    fixed_income: R5MonitoringFixedIncomeEvidence,
    policy: R5MonitoringPolicy,
    calendar: R5MonitoringCalendar,
    facts: tuple[R5PostPromotionMonitoringFact, ...],
    assessment: R5PostPromotionMonitoringAssessment,
) -> bool:
    return (
        winner.active_lifecycle == active
        and winner.fixed_income == fixed_income
        and winner.policy == policy
        and winner.calendar == calendar
        and winner.portfolio_facts == facts
        and winner.assessment == assessment
    )


def _observation_row_matches_domain_values(
    model: R5MonitoringObservationLedgerModel,
    values: dict[str, object],
) -> bool:
    ignored = {"ledger_header_hash", "ledger_recorded_at"}
    return all(getattr(model, key) == value for key, value in values.items() if key not in ignored)


def _observation_values(
    *,
    assessment_row_id: int,
    assessment_stable_id: str,
    decision_row_id: int,
    lifecycle_event_row_id: int,
    fact: R5PostPromotionMonitoringFact,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    source = fact.source_projection.owner_record
    values: dict[str, object] = {
        "assessment_id": assessment_row_id,
        "active_decision_id": decision_row_id,
        "lifecycle_event_id": lifecycle_event_row_id,
        "fact_id": fact.fact_id,
        "fact_version": fact.fact_version,
        "domain_fact_hash": fact.content_hash,
        "policy_id": fact.policy_id,
        "policy_version": fact.policy_version,
        "policy_hash": fact.policy_hash,
        "target_hash": fact.target_hash,
        "calendar_id": fact.calendar_id,
        "calendar_version": fact.calendar_version,
        "calendar_hash": fact.calendar_hash,
        "period_id": fact.period_id,
        "period_start": fact.period_start,
        "period_end": fact.period_end,
        "source_owner": source.owner,
        "source_owner_id": source.owner_id,
        "source_owner_version": source.owner_version,
        "source_owner_hash": source.content_hash,
        "source_observed_at": fact.source_projection.source_observed_at,
        "observed_at": fact.observed_at,
        "available_at": fact.available_at,
        "owner_recorded_at": fact.recorded_at,
        "valid_until": fact.valid_until,
        "observed_label_hash": fact.observed_label_hash,
        "observed_data_schema_hash": fact.observed_data_schema_hash,
        "canonical_payload": encode_r5_monitoring_fact(fact),
        "content_hash": _persisted_fact_hash(assessment_stable_id, fact),
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
    decision_row_id: int,
    lifecycle_event_row_id: int,
    active: R5MonitoringActiveLifecycle,
    fixed_income: R5MonitoringFixedIncomeEvidence,
    policy: R5MonitoringPolicy,
    calendar: R5MonitoringCalendar,
    facts: tuple[R5PostPromotionMonitoringFact, ...],
    assessment: R5PostPromotionMonitoringAssessment,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    if not facts:
        raise R5MonitoringPersistenceCorruption("R5 monitoring facts are incomplete")
    values: dict[str, object] = {
        "assessment_id": assessment.assessment_id,
        "assessment_version": assessment.assessment_version,
        "active_decision_id": decision_row_id,
        "lifecycle_event_id": lifecycle_event_row_id,
        "scope_id": active.scope_id,
        "scope_hash": active.scope_hash,
        "active_decision_stable_id": active.decision_id,
        "active_decision_version": active.decision_version,
        "active_decision_hash": active.decision_hash,
        "active_lifecycle_hash": active.content_hash,
        "fixed_income_result_id": fixed_income.result_id,
        "fixed_income_result_version": fixed_income.result_version,
        "fixed_income_result_hash": fixed_income.result_hash,
        "fixed_income_owner_seal_hash": fixed_income.owner_seal_hash,
        "requested_policy_id": policy.policy_id,
        "requested_policy_version": policy.policy_version,
        "expected_policy_hash": policy.content_hash,
        "calendar_id": calendar.owner.owner_id,
        "calendar_version": calendar.owner.owner_version,
        "calendar_hash": calendar.content_hash,
        "evaluated_at": assessment.evaluated_at,
        "active_owner_recorded_at": active.recorded_at,
        "fixed_income_owner_recorded_at": fixed_income.recorded_at,
        "policy_owner_recorded_at": policy.recorded_at,
        "calendar_owner_recorded_at": calendar.recorded_at,
        "latest_fact_owner_recorded_at": max(item.recorded_at for item in facts),
        "ledger_recorded_at": ledger_recorded_at,
        "status": assessment.status.value,
        "fact_count": len(facts),
        "fact_hashes": list(assessment.fact_hashes),
        "active_lifecycle_payload": encode_r5_monitoring_active_lifecycle(active),
        "fixed_income_payload": encode_r5_monitoring_fixed_income(fixed_income),
        "policy_payload": encode_r5_monitoring_policy(policy),
        "calendar_payload": encode_r5_monitoring_period_calendar(calendar),
        "assessment_payload": encode_r5_monitoring_assessment(assessment),
        "content_hash": assessment.content_hash,
        "automatic_retirement": assessment.automatic_retirement,
        "research_only": assessment.research_only,
        "must_not_use_for_decision": True,
        "must_not_publish_current": assessment.must_not_publish_current,
        "must_not_execute": assessment.must_not_execute,
    }
    values["ledger_header_hash"] = _ledger_header_hash(
        row_kind="assessment",
        values=values,
    )
    return values


def _snapshot_values(snapshot: _R5MonitoringAuditSnapshot) -> dict[str, object]:
    values: dict[str, object] = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "entry_count": len(snapshot.entries),
        "canonical_payload": encode_r5_monitoring_audit_snapshot(snapshot),
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
    model: R5MonitoringAuditSnapshotModel,
) -> _R5MonitoringAuditSnapshot:
    snapshot = decode_r5_monitoring_audit_snapshot(model.canonical_payload)
    _require_model_values(
        model=model,
        values=_snapshot_values(snapshot),
        label="audit snapshot",
    )
    return snapshot


__all__: list[str] = []
