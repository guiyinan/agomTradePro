"""HTTP contract coverage for human operator-spec approval writes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.risk_center.application.evidence_operator_spec_approval import (
    ApproveEvidenceOperatorSpecCommand,
    RegisterEvidenceOperatorSpecApprovalSubjectCommand,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalActor,
    EvidenceOperatorSpecApprovalActorKind,
    EvidenceOperatorSpecApprovalRecord,
    EvidenceOperatorSpecApprovalSubject,
)
from apps.risk_center.interface import evidence_operator_spec_approval_api_views as views
from apps.risk_center.interface.evidence_operator_spec_approval_serializers import (
    ApproveOperatorSpecSerializer,
    RegisterOperatorSpecApprovalSubjectSerializer,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)
VALID_UNTIL = NOW + timedelta(days=30)
HASH_A = "a" * 64


def _actor(*, user_id: int) -> EvidenceOperatorSpecApprovalActor:
    return EvidenceOperatorSpecApprovalActor(
        actor_id=f"django-user:{user_id}",
        kind=EvidenceOperatorSpecApprovalActorKind.HUMAN,
        is_staff=True,
        user_id=user_id,
    )


def _subject() -> EvidenceOperatorSpecApprovalSubject:
    return EvidenceOperatorSpecApprovalSubject.create(
        subject_id="operator-subject:sector-score:v1",
        subject_version="1",
        operator_id="sector-score",
        operator_version="1",
        definition_hash=HASH_A,
        supersedes_activation_hash=None,
        requested_by=_actor(user_id=41),
        requested_at=NOW,
        valid_until=VALID_UNTIL,
    )


class CommandRecorder:
    def __init__(self, result: object) -> None:
        self.result = result
        self.commands: list[object] = []

    def execute(self, command: object) -> object:
        self.commands.append(command)
        return self.result


def test_write_serializers_accept_only_identity_selectors() -> None:
    register = RegisterOperatorSpecApprovalSubjectSerializer(
        data={
            "subject_id": "subject:1",
            "subject_version": "1",
            "operator_id": "operator:1",
            "operator_version": "1",
        }
    )
    assert register.is_valid(), register.errors

    for forbidden_field in ("actor", "requested_by", "definition_hash", "as_of"):
        forged = RegisterOperatorSpecApprovalSubjectSerializer(
            data={
                "subject_id": "subject:1",
                "subject_version": "1",
                "operator_id": "operator:1",
                "operator_version": "1",
                forbidden_field: "forged",
            }
        )
        assert not forged.is_valid()
        assert "Unknown fields" in str(forged.errors)

    for forbidden_field in ("actor", "approved_by", "subject_hash", "definition_hash"):
        forged = ApproveOperatorSpecSerializer(
            data={
                "subject_id": "subject:1",
                "subject_version": "1",
                "approval_id": "approval:1",
                "approval_version": "1",
                forbidden_field: "forged",
            }
        )
        assert not forged.is_valid()


@pytest.mark.parametrize(
    "view_type",
    [
        views.RegisterEvidenceOperatorSpecApprovalSubjectView,
        views.ApproveEvidenceOperatorSpecView,
    ],
)
def test_write_views_are_session_csrf_staff_post_only(view_type: type[object]) -> None:
    assert view_type.authentication_classes == [SessionAuthentication]
    assert view_type.permission_classes == [IsAuthenticated, IsAdminUser]
    assert view_type.http_method_names == ["post", "options"]


def test_register_view_passes_request_user_and_id_only_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    register = CommandRecorder(subject)
    approve = CommandRecorder(None)
    captured_users: list[object] = []

    def build_runtime(*, authenticated_user: object) -> object:
        captured_users.append(authenticated_user)
        return SimpleNamespace(register_subject=register, approve=approve)

    monkeypatch.setattr(
        views,
        "build_evidence_operator_spec_approval_write_runtime",
        build_runtime,
    )
    user = SimpleNamespace(is_authenticated=True, is_staff=True, pk=41)
    request = APIRequestFactory().post(
        "/api/risk-center/evidence/operator-spec-approval-subjects/",
        {
            "subject_id": subject.subject_id,
            "subject_version": subject.subject_version,
            "operator_id": subject.operator_id,
            "operator_version": subject.operator_version,
        },
        format="json",
    )
    force_authenticate(request, user=user)

    response = views.RegisterEvidenceOperatorSpecApprovalSubjectView.as_view()(request)
    response.render()

    assert response.status_code == 201
    assert response["Content-Type"] == "application/json"
    assert captured_users == [user]
    command = register.commands[0]
    assert isinstance(command, RegisterEvidenceOperatorSpecApprovalSubjectCommand)
    assert tuple(command.__dict__) == (
        "subject_id",
        "subject_version",
        "operator_id",
        "operator_version",
        "as_of",
    )


def test_approve_view_passes_request_user_and_id_only_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    approval = EvidenceOperatorSpecApprovalRecord.create(
        approval_id="operator-approval:sector-score:v1",
        approval_version="1",
        subject=subject,
        approved_by=_actor(user_id=42),
        issued_at=NOW + timedelta(seconds=1),
    )
    register = CommandRecorder(None)
    approve = CommandRecorder(approval)
    user = SimpleNamespace(is_authenticated=True, is_staff=True, pk=42)
    monkeypatch.setattr(
        views,
        "build_evidence_operator_spec_approval_write_runtime",
        lambda *, authenticated_user: SimpleNamespace(
            register_subject=register,
            approve=approve,
            authenticated_user=authenticated_user,
        ),
    )
    request = APIRequestFactory().post(
        "/api/risk-center/evidence/operator-spec-approvals/",
        {
            "subject_id": subject.subject_id,
            "subject_version": subject.subject_version,
            "approval_id": approval.approval_id,
            "approval_version": approval.approval_version,
        },
        format="json",
    )
    force_authenticate(request, user=user)

    response = views.ApproveEvidenceOperatorSpecView.as_view()(request)

    assert response.status_code == 201
    command = approve.commands[0]
    assert isinstance(command, ApproveEvidenceOperatorSpecCommand)
    assert tuple(command.__dict__) == (
        "subject_id",
        "subject_version",
        "approval_id",
        "approval_version",
        "as_of",
    )
