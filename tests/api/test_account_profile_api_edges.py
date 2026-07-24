from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.account.infrastructure.models import AccountProfileModel


@pytest.mark.django_db
def test_account_profile_get_exposes_authenticated_mcp_identity() -> None:
    user = get_user_model().objects.create_user(
        username="profile_identity_user",
        password="testpass123",
    )
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": "Identity User",
            "initial_capital": Decimal("1000000.00"),
            "risk_tolerance": "moderate",
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/account/profile/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["user_id"] == user.id
    assert payload["username"] == user.username


@pytest.mark.django_db
def test_account_profile_put_updates_profile_and_email() -> None:
    user = get_user_model().objects.create_user(
        username="profile_api_user",
        password="testpass123",
        email="before@example.com",
    )
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": "Before Name",
            "initial_capital": Decimal("1000000.00"),
            "risk_tolerance": "moderate",
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.put(
        "/api/account/profile/",
        {
            "display_name": "After Name",
            "risk_tolerance": "aggressive",
            "email": "after@example.com",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["display_name"] == "After Name"
    assert payload["risk_tolerance"] == "aggressive"

    user.refresh_from_db()
    profile = user.account_profile
    assert user.email == "after@example.com"
    assert profile.display_name == "After Name"
    assert profile.risk_tolerance == "aggressive"


@pytest.mark.django_db
def test_account_profile_put_rejects_invalid_email_and_unknown_fields() -> None:
    user = get_user_model().objects.create_user(
        username="profile_strict_user",
        password="testpass123",
        email="before@example.com",
    )
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": "Strict User",
            "initial_capital": Decimal("1000000.00"),
            "risk_tolerance": "moderate",
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )
    client = APIClient()
    client.force_authenticate(user=user)

    invalid_email = client.put(
        "/api/account/profile/",
        {"email": "not-an-email"},
        format="json",
    )
    unknown_field = client.put(
        "/api/account/profile/",
        {"rbac_role": "admin"},
        format="json",
    )

    assert invalid_email.status_code == 400
    assert unknown_field.status_code == 400
    user.refresh_from_db()
    assert user.email == "before@example.com"
