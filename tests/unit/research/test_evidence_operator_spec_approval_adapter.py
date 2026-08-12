"""Tests for the Risk Center to Research approval projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.evidence_operator_spec_approval_adapter import (
    RiskCenterOperatorSpecApprovalAdapter,
)
from apps.research.application.evidence_operator_spec_lifecycle import (
    EvidenceOperatorSpecCorruption,
    EvidenceOperatorSpecOwnerApproval,
)
from apps.risk_center.application.evidence_operator_spec_approval import (
    GetEvidenceOperatorSpecApprovalForDefinitionCommand,
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


class _Query:
    def __init__(self, value: EvidenceOperatorSpecApprovalRecord | None) -> None:
        self.value = value
        self.commands: list[GetEvidenceOperatorSpecApprovalForDefinitionCommand] = []

    def execute(
        self,
        command: GetEvidenceOperatorSpecApprovalForDefinitionCommand,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        self.commands.append(command)
        return self.value


def _get(
    adapter: RiskCenterOperatorSpecApprovalAdapter,
) -> EvidenceOperatorSpecOwnerApproval | None:
    return adapter.get_exact(
        approval_id="approval:sector-score:1",
        approval_version="1",
        operator_id="sector-score",
        operator_version="1",
        definition_hash=HASH,
        supersedes_activation_hash=None,
        as_of=NOW,
    )


def test_adapter_projects_exact_owner_record_identity_and_hash() -> None:
    approval = _approval()
    query = _Query(approval)

    projected = _get(RiskCenterOperatorSpecApprovalAdapter(query))

    assert projected is not None
    assert projected.owner_record_id == approval.approval_id
    assert projected.owner_record_version == approval.approval_version
    assert projected.owner_record_hash == approval.content_hash
    assert projected.approved_by == approval.approved_by.actor_id
    assert len(query.commands) == 1


def test_adapter_preserves_unavailable_as_fail_closed_none() -> None:
    assert _get(RiskCenterOperatorSpecApprovalAdapter(_Query(None))) is None


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
        _get(RiskCenterOperatorSpecApprovalAdapter(_Query(substituted)))
