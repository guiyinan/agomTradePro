"""
Integration test: GET /api/account/sizing-context/
"""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from rest_framework import status
from unittest.mock import patch

from apps.account.infrastructure.models import MacroSizingConfigModel


@pytest.fixture()
def user_with_portfolio(db):
    user = User.objects.create_user(username="sizing_test_user", password="testpass1234")
    user.portfolios.create(name="Test Portfolio", is_active=True)
    return user


@pytest.fixture()
def default_config(db):
    return MacroSizingConfigModel.objects.create(
        regime_tiers_json=[
            {"min_confidence": 0.6, "factor": 1.0},
            {"min_confidence": 0.4, "factor": 0.8},
            {"min_confidence": 0.0, "factor": 0.5},
        ],
        pulse_tiers_json=[
            {"min_composite": 0.3, "max_composite": 99, "factor": 1.00},
            {"min_composite": -0.3, "max_composite": 0.3, "factor": 0.85},
            {"min_composite": -99, "max_composite": -0.3, "factor": 0.70},
        ],
        warning_factor=0.5,
        drawdown_tiers_json=[
            {"min_drawdown": 0.15, "factor": 0.0},
            {"min_drawdown": 0.10, "factor": 0.5},
            {"min_drawdown": 0.05, "factor": 0.8},
            {"min_drawdown": 0.00, "factor": 1.0},
        ],
        version=1,
        is_active=True,
        description="integration test default",
    )


@pytest.fixture()
def auth_client(user_with_portfolio):
    client = Client()
    client.login(username="sizing_test_user", password="testpass1234")
    return client


@pytest.mark.django_db
class TestSizingContextAPI:
    def test_unauthenticated_returns_401_or_403(self):
        client = Client()
        resp = client.get("/api/account/sizing-context/")
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_authenticated_returns_200(self, auth_client, default_config):
        resp = auth_client.get("/api/account/sizing-context/")
        assert resp.status_code == status.HTTP_200_OK

    def test_response_has_required_fields(self, auth_client, default_config):
        resp = auth_client.get("/api/account/sizing-context/")
        data = resp.json()

        assert "multiplier" in data
        assert "action_hint" in data
        assert "reasoning" in data
        assert "components" in data
        assert "context" in data
        assert "config_version" in data
        assert "warnings" in data
        assert "calculated_at" in data

    def test_multiplier_in_valid_range(self, auth_client, default_config):
        resp = auth_client.get("/api/account/sizing-context/")
        data = resp.json()
        assert 0.0 <= data["multiplier"] <= 1.0

    def test_components_structure(self, auth_client, default_config):
        resp = auth_client.get("/api/account/sizing-context/")
        components = resp.json()["components"]
        assert "regime_factor" in components
        assert "pulse_factor" in components
        assert "drawdown_factor" in components

    def test_context_structure(self, auth_client, default_config):
        resp = auth_client.get("/api/account/sizing-context/")
        ctx = resp.json()["context"]
        assert "regime" in ctx
        assert "regime_confidence" in ctx
        assert "pulse_composite" in ctx
        assert "pulse_warning" in ctx
        assert "portfolio_drawdown_pct" in ctx

    def test_calculated_at_is_iso8601(self, auth_client, default_config):
        resp = auth_client.get("/api/account/sizing-context/")
        calculated_at = resp.json()["calculated_at"]
        assert isinstance(calculated_at, str)
        assert "T" in calculated_at
        assert "+" in calculated_at or calculated_at.endswith("Z")

    def test_action_hint_is_valid(self, auth_client, default_config):
        resp = auth_client.get("/api/account/sizing-context/")
        hint = resp.json()["action_hint"]
        assert hint in ("正常开仓", "减仓操作", "缩半开仓", "暂停新仓")

    def test_config_version_matches(self, auth_client, default_config):
        resp = auth_client.get("/api/account/sizing-context/")
        assert resp.json()["config_version"] == 1

    def test_warnings_is_list(self, auth_client, default_config):
        resp = auth_client.get("/api/account/sizing-context/")
        assert isinstance(resp.json()["warnings"], list)

    def test_regime_failure_degrades_to_200(self, auth_client, default_config):
        with patch(
            "apps.account.application.use_cases.resolve_current_regime",
            side_effect=RuntimeError("regime down"),
        ):
            resp = auth_client.get("/api/account/sizing-context/")

        data = resp.json()
        assert resp.status_code == status.HTTP_200_OK
        assert "regime_unavailable" in data["warnings"]
        assert "Regime数据不可用" in data["reasoning"]

    def test_snapshot_failure_degrades_to_200(self, auth_client, default_config):
        with patch(
            "apps.account.infrastructure.repositories.PortfolioSnapshotRepository.get_snapshots_for_volatility",
            side_effect=RuntimeError("snapshot down"),
        ):
            resp = auth_client.get("/api/account/sizing-context/")

        data = resp.json()
        assert resp.status_code == status.HTTP_200_OK
        assert "snapshot_unavailable" in data["warnings"]
        assert "组合回撤数据不可用" in data["reasoning"]

    def test_pulse_unreliable_degrades_to_neutral_context(self, auth_client, default_config):
        captured: dict[str, object] = {}

        def _fake_execute(self, *args, **kwargs):
            captured.update(kwargs)
            return None

        with patch(
            "apps.pulse.application.use_cases.GetLatestPulseUseCase.execute",
            new=_fake_execute,
        ):
            resp = auth_client.get("/api/account/sizing-context/")

        data = resp.json()
        assert resp.status_code == status.HTTP_200_OK
        assert captured["require_reliable"] is True
        assert captured["refresh_if_stale"] is True
        assert "pulse_unavailable" in data["warnings"]
        assert data["context"]["pulse_composite"] == 0.0
        assert data["context"]["pulse_warning"] is False
        assert "Pulse数据不可用" in data["reasoning"]
