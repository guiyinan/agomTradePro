from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.account.infrastructure.models import AccountProfileModel


@pytest.mark.django_db
def test_account_profile_put_updates_profile_and_email():
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
