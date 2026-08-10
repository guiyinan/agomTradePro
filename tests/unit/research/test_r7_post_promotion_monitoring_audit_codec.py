"""R7 monitoring audit cursors bind a complete immutable snapshot."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from django.test import override_settings

from apps.research.application.r7_post_promotion_monitoring_persistence import (
    R7MonitoringAssessmentRef,
    R7MonitoringAuditEntry,
    R7MonitoringPersistenceUnavailable,
    r7_monitoring_evidence_hash,
)
from apps.research.infrastructure.r7_post_promotion_monitoring_audit_codec import (
    create_r7_monitoring_audit_snapshot,
    decode_r7_monitoring_audit_cursor,
    decode_r7_monitoring_audit_snapshot,
    encode_r7_monitoring_audit_cursor,
    encode_r7_monitoring_audit_snapshot,
)
from tests.unit.research.test_r7_post_promotion_monitoring_persistence import (
    _evidence,
)


def _entry() -> tuple[R7MonitoringAuditEntry, object]:
    _, evidence = _evidence()
    assessment = evidence.assessment
    entry = R7MonitoringAuditEntry(
        reference=R7MonitoringAssessmentRef(
            assessment_id="r7-monitoring-assessment-ledger:" + "a" * 64,
            assessment_version=assessment.assessment_version,
            content_hash=r7_monitoring_evidence_hash(evidence),
        ),
        policy_id=evidence.policy.policy_id,
        policy_version=evidence.policy.policy_version,
        result_id=evidence.active.result_id,
        result_hash=evidence.active.result_hash,
        period_id=evidence.period.period_id,
        evaluated_at=assessment.evaluated_at,
        ledger_recorded_at=assessment.evaluated_at + timedelta(seconds=1),
        status=assessment.status,
        observation_count=len(evidence.realization_owner_record.members),
        blocker_codes=tuple(item.value for item in assessment.blocker_codes),
        manual_retirement_review_required=(assessment.manual_retirement_review_required),
    )
    return entry, evidence


def test_snapshot_and_signed_cursor_round_trip() -> None:
    entry, _ = _entry()
    second = replace(entry, reference=replace(entry.reference, assessment_id="b" * 64))
    snapshot = create_r7_monitoring_audit_snapshot(
        as_of=entry.evaluated_at,
        created_at=entry.ledger_recorded_at,
        entries=(entry, second),
    )

    assert (
        decode_r7_monitoring_audit_snapshot(encode_r7_monitoring_audit_snapshot(snapshot))
        == snapshot
    )
    cursor = encode_r7_monitoring_audit_cursor(snapshot=snapshot, next_offset=1)
    restored = decode_r7_monitoring_audit_cursor(cursor)
    assert restored is not None
    assert restored.snapshot_hash == snapshot.content_hash
    assert restored.next_offset == 1


def test_cursor_rejects_tamper_and_secret_key_change() -> None:
    entry, _ = _entry()
    second = replace(entry, reference=replace(entry.reference, assessment_id="b" * 64))
    snapshot = create_r7_monitoring_audit_snapshot(
        as_of=entry.evaluated_at,
        created_at=entry.ledger_recorded_at,
        entries=(entry, second),
    )
    cursor = encode_r7_monitoring_audit_cursor(snapshot=snapshot, next_offset=1)

    with pytest.raises(R7MonitoringPersistenceUnavailable):
        decode_r7_monitoring_audit_cursor(cursor + "x")
    with override_settings(SECRET_KEY="different-r7-monitoring-audit-secret"):
        with pytest.raises(R7MonitoringPersistenceUnavailable):
            decode_r7_monitoring_audit_cursor(cursor)
