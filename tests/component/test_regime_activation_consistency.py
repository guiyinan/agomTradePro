"""Regression tests for Regime config activation consistency."""

from unittest.mock import Mock, patch

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase
from django.urls import NoReverseMatch, reverse

from apps.regime.infrastructure.models import RegimeIndicatorThreshold, RegimeThresholdConfig
from apps.regime.infrastructure.repositories import RegimeConfigRepository
from apps.regime.interface.admin import (
    RegimeIndicatorThresholdAdminForm,
    RegimeThresholdConfigAdmin,
)


@pytest.mark.django_db
class TestRegimeActivationConsistency(TestCase):
    """Ensure Regime activation toggles remain atomic."""

    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.staff_user = User.objects.create_user(
            username="regime_admin",
            password="pass123456",
            is_staff=True,
            is_superuser=True,
        )
        self.active_config = RegimeThresholdConfig.objects.create(name="激活配置", is_active=True)
        self.inactive_config = RegimeThresholdConfig.objects.create(
            name="候选配置", is_active=False
        )
        for config in (self.active_config, self.inactive_config):
            RegimeIndicatorThreshold.objects.create(
                config=config,
                indicator_code="PMI",
                indicator_name="PMI",
                level_low=49.0,
                level_high=50.0,
            )
            RegimeIndicatorThreshold.objects.create(
                config=config,
                indicator_code="CPI",
                indicator_name="CPI",
                level_low=1.0,
                level_high=3.0,
            )

    def test_activate_regime_config_switches_active_state_and_invalidates_cache(self) -> None:
        """Activating a config should leave one active config and invalidate cache after commit."""
        invalidate = Mock()
        with patch(
            "apps.regime.infrastructure.repositories.CacheService.invalidate_regime",
            invalidate,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                activated_name = RegimeConfigRepository().activate_threshold_config(
                    self.inactive_config.pk
                )

        self.active_config.refresh_from_db()
        self.inactive_config.refresh_from_db()

        self.assertEqual(activated_name, self.inactive_config.name)
        self.assertFalse(self.active_config.is_active)
        self.assertTrue(self.inactive_config.is_active)
        invalidate.assert_called_once()

    def test_activate_regime_config_rolls_back_on_save_error(self) -> None:
        """A failing activation must keep the previous active config unchanged."""
        original_save = RegimeThresholdConfig.save

        def _raising_save(instance, *args, **kwargs):
            if instance.pk == self.inactive_config.pk:
                raise RuntimeError("boom")
            return original_save(instance, *args, **kwargs)

        with patch.object(RegimeThresholdConfig, "save", autospec=True, side_effect=_raising_save):
            with self.assertRaises(RuntimeError):
                RegimeConfigRepository().activate_threshold_config(self.inactive_config.pk)

        self.active_config.refresh_from_db()
        self.inactive_config.refresh_from_db()

        self.assertTrue(self.active_config.is_active)
        self.assertFalse(self.inactive_config.is_active)

    def test_admin_activation_is_post_only_and_requires_exactly_one_candidate(self) -> None:
        """The standard CSRF Admin action replaces the former state-changing GET route."""

        with self.assertRaises(NoReverseMatch):
            reverse("admin:regime_regimethresholdconfig_activate", args=[self.inactive_config.pk])

        client = Client()
        client.force_login(self.staff_user)
        changelist_url = reverse("admin:regime_regimethresholdconfig_changelist")
        response = client.post(
            changelist_url,
            {
                "action": "activate_selected_config",
                "_selected_action": [str(self.inactive_config.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.inactive_config.refresh_from_db()
        self.assertTrue(self.inactive_config.is_active)

        response = client.post(
            changelist_url,
            {
                "action": "activate_selected_config",
                "_selected_action": [
                    str(self.active_config.pk),
                    str(self.inactive_config.pk),
                ],
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_admin_threshold_summary_escapes_database_content(self) -> None:
        """Indicator metadata cannot inject markup into the Admin changelist."""

        RegimeIndicatorThreshold.objects.create(
            config=self.inactive_config,
            indicator_code='<img src=x onerror="alert(1)">',
            indicator_name="unsafe",
            level_low=1.0,
            level_high=2.0,
        )
        admin_instance = RegimeThresholdConfigAdmin(RegimeThresholdConfig, AdminSite())

        rendered = str(admin_instance.threshold_summary(self.inactive_config))

        self.assertIn("&lt;img", rendered)
        self.assertNotIn("<img", rendered)

    def test_activation_rejects_incomplete_candidate_without_deactivating_current(self) -> None:
        """Candidate completeness derives from the active database indicator set."""

        incomplete = RegimeThresholdConfig.objects.create(name="不完整候选", is_active=False)
        RegimeIndicatorThreshold.objects.create(
            config=incomplete,
            indicator_code="PMI",
            indicator_name="PMI",
            level_low=49.0,
            level_high=50.0,
        )

        with self.assertRaisesRegex(ValueError, "missing active indicator codes"):
            RegimeConfigRepository().activate_threshold_config(incomplete.pk)

        self.active_config.refresh_from_db()
        incomplete.refresh_from_db()
        self.assertTrue(self.active_config.is_active)
        self.assertFalse(incomplete.is_active)

    def test_threshold_admin_form_rejects_active_parent(self) -> None:
        """The standalone add form cannot append rows to the active configuration."""

        form = RegimeIndicatorThresholdAdminForm(
            data={
                "config": self.active_config.pk,
                "indicator_code": "GDP",
                "indicator_name": "GDP",
                "level_low": 1.0,
                "level_high": 2.0,
                "description": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("config", form.errors)

    def test_active_config_is_immutable_in_admin(self) -> None:
        """Active threshold rows cannot be edited in place without an activation audit event."""

        request = self.factory.get("/admin/regime/regimethresholdconfig/")
        request.user = self.staff_user
        admin_instance = RegimeThresholdConfigAdmin(RegimeThresholdConfig, AdminSite())

        self.assertFalse(admin_instance.has_change_permission(request, self.active_config))
        self.assertFalse(admin_instance.has_delete_permission(request, self.active_config))
        self.assertTrue(admin_instance.has_change_permission(request, self.inactive_config))

    def test_database_constraint_blocks_multiple_active_regime_configs(self) -> None:
        """DB constraint should allow at most one active threshold config."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RegimeThresholdConfig.objects.create(name="重复激活配置", is_active=True)
