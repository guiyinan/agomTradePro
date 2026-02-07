from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.account.infrastructure.models import AccountProfileModel


class AccountAdminUserManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_u",
            email="admin@example.com",
            password="Pass123!@#",
        )
        self._create_profile(self.admin, approval_status="approved")
        self.client.force_login(self.admin)

    def _create_profile(self, user, approval_status="pending"):
        profile, _ = AccountProfileModel.objects.get_or_create(
            user=user,
            defaults={
                "display_name": user.username,
                "approval_status": approval_status,
            },
        )
        profile.approval_status = approval_status
        profile.display_name = profile.display_name or user.username
        profile.save(update_fields=["approval_status", "display_name", "updated_at"])
        return profile

    def test_reject_non_pending_user_is_blocked(self):
        user = User.objects.create_user(username="approved_u", password="x")
        profile = self._create_profile(user, approval_status="approved")
        user.is_active = True
        user.save(update_fields=["is_active"])
        Token.objects.create(user=user)

        resp = self.client.post(
            reverse("account:reject_user", args=[user.id]),
            {"rejection_reason": "invalid"},
        )
        self.assertEqual(resp.status_code, 302)

        profile.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(profile.approval_status, "approved")
        self.assertTrue(user.is_active)
        self.assertTrue(Token.objects.filter(user=user).exists())

    def test_reject_pending_user_deactivates_and_revokes_token(self):
        user = User.objects.create_user(username="pending_u", password="x")
        profile = self._create_profile(user, approval_status="pending")
        user.is_active = True
        user.save(update_fields=["is_active"])
        Token.objects.create(user=user)

        resp = self.client.post(
            reverse("account:reject_user", args=[user.id]),
            {"rejection_reason": "manual reject"},
        )
        self.assertEqual(resp.status_code, 302)

        profile.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(profile.approval_status, "rejected")
        self.assertFalse(user.is_active)
        self.assertFalse(Token.objects.filter(user=user).exists())

    def test_reset_self_is_blocked(self):
        Token.objects.get_or_create(user=self.admin)

        resp = self.client.post(reverse("account:reset_user_status", args=[self.admin.id]))
        self.assertEqual(resp.status_code, 302)

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertTrue(Token.objects.filter(user=self.admin).exists())

    def test_rotate_token_uses_session_payload_instead_of_plain_message(self):
        user = User.objects.create_user(username="token_u", password="x")
        self._create_profile(user, approval_status="approved")
        old_token = Token.objects.create(user=user).key

        resp = self.client.post(
            reverse("account:rotate_user_token", args=[user.id]),
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)

        new_token = Token.objects.get(user=user).key
        self.assertNotEqual(old_token, new_token)

        payload = resp.context["new_token_payload"]
        self.assertIsNotNone(payload)
        self.assertEqual(payload["username"], user.username)
        self.assertEqual(payload["token"], new_token)

        messages = list(resp.context["messages"])
        self.assertTrue(any("生成新 Token" in str(m) for m in messages))
        self.assertFalse(any(new_token in str(m) for m in messages))
