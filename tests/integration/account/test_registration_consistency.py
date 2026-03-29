"""Regression tests for account registration consistency."""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import TestCase

from apps.account.infrastructure.models import AccountProfileModel, PortfolioModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


@pytest.mark.django_db
class TestRegistrationConsistency(TestCase):
    """Ensure registration writes all related records atomically."""

    def _post_registration(self, username: str):
        return self.client.post(
            "/account/register/",
            {
                "username": username,
                "email": f"{username}@example.com",
                "password": "pass123456",
                "password_confirm": "pass123456",
                "display_name": "测试用户",
                "user_agreement": "on",
                "risk_warning": "on",
            },
        )

    def test_register_creates_complete_user_scaffolding_once(self) -> None:
        """Successful registration should create one profile, one default portfolio, and default accounts."""
        response = self._post_registration("reg_consistency_user")
        user = User.objects.get(username="reg_consistency_user")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(AccountProfileModel.objects.filter(user=user).count(), 1)
        self.assertEqual(PortfolioModel.objects.filter(user=user, name="默认组合").count(), 1)
        self.assertEqual(SimulatedAccountModel.objects.filter(user=user).count(), 2)

    def test_register_rolls_back_user_when_provisioning_fails(self) -> None:
        """A provisioning failure should not leave a half-created user behind."""
        with patch(
            "apps.account.interface.views._provision_registered_user",
            side_effect=RuntimeError("boom"),
        ):
            response = self._post_registration("reg_consistency_failure")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="reg_consistency_failure").exists())
        self.assertFalse(AccountProfileModel.objects.filter(user__username="reg_consistency_failure").exists())
        self.assertFalse(PortfolioModel.objects.filter(user__username="reg_consistency_failure").exists())
        self.assertFalse(
            SimulatedAccountModel.objects.filter(user__username="reg_consistency_failure").exists()
        )
