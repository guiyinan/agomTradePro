"""Regression tests for Beta Gate activation consistency."""

from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.beta_gate.infrastructure.models import GateConfigModel
from apps.beta_gate.interface.forms import GateConfigForm
from apps.beta_gate.interface.views import _save_gate_config_form


@pytest.mark.django_db
class TestBetaGateActivationConsistency(TestCase):
    """Ensure Beta Gate active-config transitions are atomic and singular."""

    def setUp(self) -> None:
        self.active_config = GateConfigModel.objects.create(
            config_id="cfg-active",
            risk_profile=GateConfigModel.BALANCED,
            version=1,
            is_active=True,
            regime_constraints={"current_regime": "Recovery"},
            policy_constraints={"current_level": 2},
            portfolio_constraints={"max_positions": 8},
        )
        self.inactive_config = GateConfigModel.objects.create(
            config_id="cfg-inactive",
            risk_profile=GateConfigModel.BALANCED,
            version=2,
            is_active=False,
            regime_constraints={"current_regime": "Overheat"},
            policy_constraints={"current_level": 3},
            portfolio_constraints={"max_positions": 5},
        )

    def test_create_active_config_deactivates_previous_config(self) -> None:
        """Creating an active config should only replace the active config in that profile."""
        response = self.client.post(
            "/beta-gate/config/new/",
            {
                "config_id": "cfg-new",
                "risk_profile": GateConfigModel.BALANCED,
                "is_active": "on",
                "effective_date": "2026-03-28",
                "expires_at": "",
                "regime_constraints_text": '{"current_regime": "Recovery"}',
                "policy_constraints_text": '{"current_level": 2}',
                "portfolio_constraints_text": '{"max_positions": 10}',
            },
        )

        active_ids = list(
            GateConfigModel.objects.filter(
                is_active=True,
                risk_profile=GateConfigModel.BALANCED,
            ).values_list("config_id", flat=True)
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(active_ids, ["cfg-new"])
        self.assertFalse(
            GateConfigModel.objects.get(config_id=self.active_config.config_id).is_active
        )

    def test_create_active_config_in_other_profile_preserves_existing_activation(self) -> None:
        """Different risk profiles may each keep one active config."""
        response = self.client.post(
            "/beta-gate/config/new/",
            {
                "config_id": "cfg-new-aggressive",
                "risk_profile": GateConfigModel.AGGRESSIVE,
                "is_active": "on",
                "effective_date": "2026-03-28",
                "expires_at": "",
                "regime_constraints_text": '{"current_regime": "Recovery"}',
                "policy_constraints_text": '{"current_level": 2}',
                "portfolio_constraints_text": '{"max_positions": 10}',
            },
        )

        active_ids = sorted(
            GateConfigModel.objects.filter(is_active=True).values_list("config_id", flat=True)
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(active_ids, ["cfg-active", "cfg-new-aggressive"])
        self.assertTrue(
            GateConfigModel.objects.get(config_id=self.active_config.config_id).is_active
        )

    def test_edit_active_config_deactivates_previous_config(self) -> None:
        """Editing a config into active state should atomically switch activation."""
        form = GateConfigForm(
            data={
                "config_id": self.inactive_config.config_id,
                "risk_profile": self.inactive_config.risk_profile,
                "is_active": True,
                "effective_date": str(self.inactive_config.effective_date)[:10],
                "expires_at": "",
                "regime_constraints_text": '{"current_regime": "Overheat"}',
                "policy_constraints_text": '{"current_level": 3}',
                "portfolio_constraints_text": '{"max_positions": 5}',
            },
            instance=self.inactive_config,
        )

        self.assertTrue(form.is_valid(), form.errors)
        instance = _save_gate_config_form(form)

        active_ids = list(
            GateConfigModel.objects.filter(is_active=True).values_list("config_id", flat=True)
        )

        self.assertEqual(instance.pk, self.inactive_config.pk)
        self.assertEqual(active_ids, [self.inactive_config.config_id])
        self.assertFalse(
            GateConfigModel.objects.get(config_id=self.active_config.config_id).is_active
        )

    def test_activate_view_rolls_back_on_save_error(self) -> None:
        """If activation fails mid-flight, the previous active config should remain active."""
        original_save = GateConfigModel.save

        def _raising_save(instance, *args, **kwargs):
            if instance.pk == self.inactive_config.pk and kwargs.get("update_fields"):
                raise RuntimeError("boom")
            return original_save(instance, *args, **kwargs)

        with patch.object(GateConfigModel, "save", autospec=True, side_effect=_raising_save):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/beta-gate/config/{self.inactive_config.config_id}/activate/")

        self.active_config.refresh_from_db()
        self.inactive_config.refresh_from_db()

        self.assertTrue(self.active_config.is_active)
        self.assertFalse(self.inactive_config.is_active)

    def test_database_constraint_blocks_second_active_config_in_same_profile(self) -> None:
        """DB constraint should reject multiple active configs for one risk profile."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GateConfigModel.objects.create(
                    config_id="cfg-duplicate-active",
                    risk_profile=GateConfigModel.BALANCED,
                    version=3,
                    is_active=True,
                    regime_constraints={"current_regime": "Recovery"},
                    policy_constraints={"current_level": 1},
                    portfolio_constraints={"max_positions": 6},
                )

    def test_database_constraint_allows_active_configs_for_different_profiles(self) -> None:
        """DB constraint should allow one active config per risk profile."""
        created = GateConfigModel.objects.create(
            config_id="cfg-aggressive-active",
            risk_profile=GateConfigModel.AGGRESSIVE,
            version=3,
            is_active=True,
            regime_constraints={"current_regime": "Recovery"},
            policy_constraints={"current_level": 1},
            portfolio_constraints={"max_positions": 6},
        )

        self.assertTrue(created.is_active)
