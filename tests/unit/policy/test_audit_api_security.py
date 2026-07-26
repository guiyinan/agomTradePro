"""Authorization and validation contracts for Policy audit APIs."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_policy_audit_endpoints_require_staff_user() -> None:
    user = User._default_manager.create_user(username="ordinary_policy_user")
    client = APIClient()
    client.force_authenticate(user=user)

    responses = [
        client.get(reverse("api_policy:audit-queue")),
        client.post(
            reverse("api_policy:review-policy", kwargs={"policy_log_id": 1}),
            {"approved": True},
            format="json",
        ),
        client.post(
            reverse("api_policy:bulk-review"),
            {"policy_log_ids": [1], "approved": True},
            format="json",
        ),
        client.post(
            reverse("api_policy:auto-assign"),
            {"max_per_user": 10},
            format="json",
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert all(response["Content-Type"].startswith("application/json") for response in responses)


@pytest.mark.django_db
def test_policy_audit_inputs_fail_before_repository_access(monkeypatch) -> None:
    staff = User._default_manager.create_user(
        username="policy_staff_reviewer",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=staff)
    monkeypatch.setattr(
        "apps.policy.interface.audit_api_views.get_current_policy_repository",
        lambda: pytest.fail("repository must not be accessed for invalid input"),
    )

    responses = [
        client.get(reverse("api_policy:audit-queue"), {"limit": 0}),
        client.post(
            reverse("api_policy:review-policy", kwargs={"policy_log_id": 1}),
            {"notes": "missing approved"},
            format="json",
        ),
        client.post(
            reverse("api_policy:bulk-review"),
            {"policy_log_ids": [1, 1], "approved": True},
            format="json",
        ),
        client.post(
            reverse("api_policy:bulk-review"),
            {
                "policy_log_ids": [1],
                "approved": True,
                "modifications": {"summary": "must not be ignored"},
            },
            format="json",
        ),
        client.post(
            reverse("api_policy:auto-assign"),
            {"max_per_user": 0},
            format="json",
        ),
    ]

    assert [response.status_code for response in responses] == [400, 400, 400, 400, 400]
    assert all(response["Content-Type"].startswith("application/json") for response in responses)


@pytest.mark.django_db
def test_policy_audit_api_redacts_internal_failures(monkeypatch) -> None:
    staff = User._default_manager.create_user(
        username="policy_failure_reviewer",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=staff)
    monkeypatch.setattr(
        "apps.policy.interface.audit_api_views.get_current_policy_repository",
        lambda: (_ for _ in ()).throw(RuntimeError("database-secret-detail")),
    )

    response = client.get(reverse("api_policy:audit-queue"))

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "error": "audit_queue_unavailable",
    }
    assert "database-secret-detail" not in response.content.decode()
