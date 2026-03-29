"""Regression tests for Regime config activation consistency."""

import sys
import types
from unittest.mock import Mock, patch

import pytest
from django.db import IntegrityError, transaction
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from apps.regime.infrastructure.models import RegimeThresholdConfig
from apps.regime.infrastructure.views import activate_regime_config


def _attach_session_and_messages(request) -> None:
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()
    setattr(request, "_messages", FallbackStorage(request))


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
        self.inactive_config = RegimeThresholdConfig.objects.create(name="候选配置", is_active=False)

    def test_activate_regime_config_switches_active_state_and_invalidates_cache(self) -> None:
        """Activating a config should leave one active config and invalidate cache after commit."""
        request = self.factory.get("/admin/regime/regimethresholdconfig/")
        _attach_session_and_messages(request)
        request.user = self.staff_user

        invalidate = Mock()
        cache_service_module = types.SimpleNamespace(
            CacheService=types.SimpleNamespace(invalidate_regime=invalidate)
        )
        with patch.dict(sys.modules, {"shared.infrastructure.cache_service": cache_service_module}):
            with self.captureOnCommitCallbacks(execute=True):
                response = activate_regime_config(request, str(self.inactive_config.pk))

        self.active_config.refresh_from_db()
        self.inactive_config.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.active_config.is_active)
        self.assertTrue(self.inactive_config.is_active)
        invalidate.assert_called_once()

    def test_activate_regime_config_rolls_back_on_save_error(self) -> None:
        """A failing activation must keep the previous active config unchanged."""
        request = self.factory.get("/admin/regime/regimethresholdconfig/")
        _attach_session_and_messages(request)
        request.user = self.staff_user
        original_save = RegimeThresholdConfig.save

        def _raising_save(instance, *args, **kwargs):
            if instance.pk == self.inactive_config.pk:
                raise RuntimeError("boom")
            return original_save(instance, *args, **kwargs)

        with patch.object(RegimeThresholdConfig, "save", autospec=True, side_effect=_raising_save):
            with self.assertRaises(RuntimeError):
                activate_regime_config(request, str(self.inactive_config.pk))

        self.active_config.refresh_from_db()
        self.inactive_config.refresh_from_db()

        self.assertTrue(self.active_config.is_active)
        self.assertFalse(self.inactive_config.is_active)

    def test_database_constraint_blocks_multiple_active_regime_configs(self) -> None:
        """DB constraint should allow at most one active threshold config."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RegimeThresholdConfig.objects.create(name="重复激活配置", is_active=True)
