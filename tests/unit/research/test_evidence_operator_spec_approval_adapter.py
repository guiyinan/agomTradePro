"""Tests for the Risk Center to Research approval projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.evidence_operator_spec_approval_adapter import (
    ExternalOperatorSpecApprovalProjection,
    project_operator_spec_owner_approval,
)
from apps.research.application.evidence_operator_spec_lifecycle import (
    EvidenceOperatorSpecCorruption,
    EvidenceOperatorSpecOwnerApproval,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalActor,
    EvidenceOperatorSpecApprovalActorKind,
    EvidenceOperatorSpecApprovalRecord,
    EvidenceOperatorSpecApprovalSubject,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)
HASH = "a" * 64


def _approval() -> EvidenceOperatorSpecApprovalRecord:
    requester = EvidenceOperatorSpecApprovalActor(
        actor_id="research.operator-registry",
        kind=EvidenceOperatorSpecApprovalActorKind.SERVICE,
        is_staff=False,
    )
    approver = EvidenceOperatorSpecApprovalActor(
        actor_id="user:risk-owner",
        kind=EvidenceOperatorSpecApprovalActorKind.HUMAN,
        is_staff=True,
        user_id=41,
    )
    subject = EvidenceOperatorSpecApprovalSubject.create(
        subject_id="subject:sector-score:1",
        subject_version="1",
        operator_id="sector-score",
        operator_version="1",
        definition_hash=HASH,
        supersedes_activation_hash=None,
        requested_by=requester,
        requested_at=NOW - timedelta(hours=2),
        valid_until=NOW + timedelta(days=10),
    )
    return EvidenceOperatorSpecApprovalRecord.create(
        approval_id="approval:sector-score:1",
        approval_version="1",
        subject=subject,
        approved_by=approver,
        issued_at=NOW - timedelta(hours=1),
    )


def _projection(
    record: EvidenceOperatorSpecApprovalRecord,
) -> ExternalOperatorSpecApprovalProjection:
    subject = record.subject
    return ExternalOperatorSpecApprovalProjection(
        owner=record.owner,
        capability=record.capability,
        approval_id=record.approval_id,
        approval_version=record.approval_version,
        owner_record_hash=record.content_hash,
        operator_id=subject.operator_id,
        operator_version=subject.operator_version,
        definition_hash=subject.definition_hash,
        supersedes_activation_hash=subject.supersedes_activation_hash,
        approved_by=record.approved_by.actor_id,
        issued_at=record.issued_at,
        valid_until=record.valid_until,
    )


def _get(record: EvidenceOperatorSpecApprovalRecord) -> EvidenceOperatorSpecOwnerApproval:
    return project_operator_spec_owner_approval(
        _projection(record),
        approval_id="approval:sector-score:1",
        approval_version="1",
        operator_id="sector-score",
        operator_version="1",
        definition_hash=HASH,
        supersedes_activation_hash=None,
    )


def test_adapter_projects_exact_owner_record_identity_and_hash() -> None:
    approval = _approval()
    projected = _get(approval)

    assert projected is not None
    assert projected.owner_record_id == approval.approval_id
    assert projected.owner_record_version == approval.approval_version
    assert projected.owner_record_hash == approval.content_hash
    assert projected.approved_by == approval.approved_by.actor_id


def test_adapter_rejects_provider_selector_substitution() -> None:
    approval = _approval()
    subject = EvidenceOperatorSpecApprovalSubject.create(
        subject_id="subject:other-operator:1",
        subject_version="1",
        operator_id="other-operator",
        operator_version="1",
        definition_hash=HASH,
        supersedes_activation_hash=None,
        requested_by=approval.subject.requested_by,
        requested_at=approval.subject.requested_at,
        valid_until=approval.subject.valid_until,
    )
    substituted = EvidenceOperatorSpecApprovalRecord.create(
        approval_id=approval.approval_id,
        approval_version=approval.approval_version,
        subject=subject,
        approved_by=approval.approved_by,
        issued_at=approval.issued_at,
    )

    with pytest.raises(EvidenceOperatorSpecCorruption, match="selector mismatch"):
        _get(substituted)
