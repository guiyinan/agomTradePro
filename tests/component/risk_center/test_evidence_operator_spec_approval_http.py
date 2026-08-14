"""HTTP integration for staff, CSRF, ID-only registration and approval."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.research.domain.evidence_contracts import (
    ClaimKind,
    DecisionPermission,
    DependencyFlag,
    EvidenceOperatorSpec,
    MethodKind,
)
from apps.research.infrastructure.evidence_repository import _build_evidence_store
from apps.risk_center.infrastructure.evidence_operator_spec_approval_models import (
    EvidenceOperatorSpecApprovalRecordModel,
    EvidenceOperatorSpecApprovalSubjectModel,
)


def _install_csrf(client: Client) -> str:
    request = HttpRequest()
    token = get_token(request)
    client.cookies[settings.CSRF_COOKIE_NAME] = request.META["CSRF_COOKIE"]
    return token


def _staff_client(*, username: str) -> tuple[Client, object, str]:
    user = get_user_model()._default_manager.create_user(
        username=username,
        password="test-password-not-production",
        is_staff=True,
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    return client, user, _install_csrf(client)


def _append_canonical_spec() -> EvidenceOperatorSpec:
    now = timezone.now()
    spec = EvidenceOperatorSpec.create(
        operator_id="sector-score",
        operator_version="1",
        research_family="sector",
        output_artifact_type="sector_score",
        claim_kind=ClaimKind.DERIVED,
        method_kind=MethodKind.DETERMINISTIC,
        required_input_roles=("sector_observations",),
        dependency_flags=frozenset({DependencyFlag.ESTIMATED_INPUT}),
        maximum_permission=DecisionPermission.DISPLAY_ONLY,
        requires_track_record=False,
        activated_at=now - timedelta(days=1),
        valid_until=now + timedelta(days=30),
    )
    store = _build_evidence_store()
    with store.atomic():
        store.append_operator_spec(spec, recorded_at=now)
    return spec


@pytest.mark.django_db
def test_staff_csrf_two_person_flow_uses_server_identities_and_exact_definition() -> None:
    spec = _append_canonical_spec()
    register_url = reverse("api_risk_center:evidence-operator-spec-approval-subject-register")
    approve_url = reverse("api_risk_center:evidence-operator-spec-approve")
    register_payload = {
        "subject_id": "operator-subject:sector-score:v1",
        "subject_version": "1",
        "operator_id": spec.operator_id,
        "operator_version": spec.operator_version,
    }
    requester_client, requester, requester_csrf = _staff_client(username="requester")

    assert requester_client.post(register_url, register_payload).status_code == 403
    response = requester_client.post(
        register_url,
        register_payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=requester_csrf,
    )
    assert response.status_code == 201
    assert response.headers["Content-Type"].startswith("application/json")
    subject_row = EvidenceOperatorSpecApprovalSubjectModel._default_manager.get()
    assert subject_row.operator_id == spec.operator_id
    assert subject_row.requested_actor_id == f"django-user:{requester.pk}"
    assert subject_row.requested_actor_user_id == requester.pk
    assert subject_row.definition_hash == response.json()["data"]["definition_hash"]

    approval_payload = {
        "subject_id": register_payload["subject_id"],
        "subject_version": register_payload["subject_version"],
        "approval_id": "operator-approval:sector-score:v1",
        "approval_version": "1",
    }
    self_approval = requester_client.post(
        approve_url,
        approval_payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=requester_csrf,
    )
    assert self_approval.status_code == 409
    assert EvidenceOperatorSpecApprovalRecordModel._default_manager.count() == 0

    approver_client, approver, approver_csrf = _staff_client(username="approver")
    approved = approver_client.post(
        approve_url,
        approval_payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=approver_csrf,
    )
    assert approved.status_code == 201
    approval_row = EvidenceOperatorSpecApprovalRecordModel._default_manager.get()
    assert approval_row.subject_id == subject_row.pk
    assert approval_row.approved_actor_id == f"django-user:{approver.pk}"
    assert approval_row.approved_actor_user_id == approver.pk
    assert approved.json()["data"]["approved_by"] == f"django-user:{approver.pk}"


@pytest.mark.django_db
def test_write_endpoints_reject_forged_semantics_permissions_and_wrong_methods() -> None:
    _append_canonical_spec()
    register_url = reverse("api_risk_center:evidence-operator-spec-approval-subject-register")
    forged_payload = {
        "subject_id": "operator-subject:sector-score:v1",
        "subject_version": "1",
        "operator_id": "sector-score",
        "operator_version": "1",
        "definition_hash": "a" * 64,
        "requested_by": "forged-admin",
    }
    assert Client(enforce_csrf_checks=True).post(register_url, forged_payload).status_code == 403

    staff_client, _, csrf = _staff_client(username="staff")
    forged = staff_client.post(
        register_url,
        forged_payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert forged.status_code == 400
    assert "Unknown fields" in str(forged.json())
    assert staff_client.get(register_url).status_code == 405

    nonstaff = get_user_model()._default_manager.create_user(
        username="nonstaff",
        password="test-password-not-production",
        is_staff=False,
    )
    nonstaff_client = Client(enforce_csrf_checks=True)
    nonstaff_client.force_login(nonstaff)
    nonstaff_csrf = _install_csrf(nonstaff_client)
    denied = nonstaff_client.post(
        register_url,
        {
            "subject_id": "subject:1",
            "subject_version": "1",
            "operator_id": "sector-score",
            "operator_version": "1",
        },
        content_type="application/json",
        HTTP_X_CSRFTOKEN=nonstaff_csrf,
    )
    assert denied.status_code == 403
