"""Regression tests for Equity scoring-weight Admin publication controls."""

from unittest.mock import Mock, patch

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from apps.equity.infrastructure.config_repositories import ScoringWeightConfigRepository
from apps.equity.infrastructure.models import ScoringWeightConfigModel
from apps.equity.interface.admin import ScoringWeightConfigAdmin


@pytest.mark.django_db
class TestEquityScoringWeightAdminControls(TestCase):
    """Ensure scoring-weight publication remains atomic and explicit."""

    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="equity_weight_admin",
            password="pass123456",
            email="equity-weight@example.com",
        )
        self.active = ScoringWeightConfigModel._default_manager.create(
            name="active",
            is_active=True,
        )
        self.candidate = ScoringWeightConfigModel._default_manager.create(
            name="candidate",
            is_active=False,
        )

    def test_repository_activation_is_atomic_and_switches_exact_candidate(self) -> None:
        """Publishing a candidate leaves exactly one active configuration."""

        activated_name = ScoringWeightConfigRepository().activate_config(self.candidate.pk)

        self.active.refresh_from_db()
        self.candidate.refresh_from_db()
        self.assertEqual(activated_name, "candidate")
        self.assertFalse(self.active.is_active)
        self.assertTrue(self.candidate.is_active)

    def test_repository_activation_rolls_back_when_candidate_save_fails(self) -> None:
        """A failed candidate save cannot leave the application without active weights."""

        original_save = ScoringWeightConfigModel.save

        def _raising_save(instance, *args, **kwargs):
            if instance.pk == self.candidate.pk:
                raise RuntimeError("boom")
            return original_save(instance, *args, **kwargs)

        with patch.object(
            ScoringWeightConfigModel,
            "save",
            autospec=True,
            side_effect=_raising_save,
        ):
            with self.assertRaises(RuntimeError):
                ScoringWeightConfigRepository().activate_config(self.candidate.pk)

        self.active.refresh_from_db()
        self.candidate.refresh_from_db()
        self.assertTrue(self.active.is_active)
        self.assertFalse(self.candidate.is_active)

    def test_admin_action_activates_one_candidate_and_rejects_multiple_selection(self) -> None:
        """The CSRF-protected Admin action never silently chooses among multiple rows."""

        client = Client()
        client.force_login(self.user)
        changelist_url = reverse("admin:equity_scoringweightconfigmodel_changelist")
        response = client.post(
            changelist_url,
            {
                "action": "activate_selected_config",
                "_selected_action": [str(self.candidate.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        self.assertTrue(self.candidate.is_active)

        response = client.post(
            changelist_url,
            {
                "action": "activate_selected_config",
                "_selected_action": [str(self.active.pk), str(self.candidate.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_active_config_is_immutable_and_new_config_is_forced_inactive(self) -> None:
        """Editing and creation cannot bypass the candidate publication workflow."""

        request = RequestFactory().post("/admin/equity/scoringweightconfigmodel/add/")
        request.user = self.user
        admin_instance = ScoringWeightConfigAdmin(ScoringWeightConfigModel, AdminSite())
        self.assertFalse(admin_instance.has_change_permission(request, self.active))
        self.assertFalse(admin_instance.has_delete_permission(request, self.active))
        self.assertTrue(admin_instance.has_change_permission(request, self.candidate))

        new_config = ScoringWeightConfigModel(name="new", is_active=True)
        admin_instance.save_model(request, new_config, Mock(), change=False)
        new_config.refresh_from_db()
        self.assertFalse(new_config.is_active)
