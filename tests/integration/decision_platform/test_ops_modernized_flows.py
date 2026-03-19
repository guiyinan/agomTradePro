import json
from datetime import date

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client

from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.beta_gate.infrastructure.models import GateConfigModel


@pytest.mark.django_db
class TestOpsModernizedFlows:
    @pytest.fixture(autouse=True)
    def _setup_client(self, monkeypatch):
        # Patch Django setting so FieldEncryptionService can initialize
        monkeypatch.setattr(settings, "AGOMSAAF_ENCRYPTION_KEY", "test-encryption-key-for-ci")
        user = User.objects.create_user(
            username="ops_user",
            email="ops@example.com",
            password="test_password",
        )
        self.client = Client()
        assert self.client.login(username="ops_user", password="test_password")

    def test_ai_provider_edit_form_updates_without_admin(self):
        provider = AIProviderConfig.objects.create(
            name="openai-main",
            provider_type="openai",
            is_active=True,
            priority=10,
            base_url="https://api.openai.com/v1",
            api_key="sk-test-original",
            default_model="gpt-4o-mini",
            extra_config={"timeout": 10},
        )

        get_response = self.client.get(f"/ai/detail/{provider.id}/edit/")
        assert get_response.status_code == 200

        post_response = self.client.post(
            f"/ai/detail/{provider.id}/edit/",
            data={
                "name": "openai-main",
                "provider_type": "openai",
                "is_active": "on",
                "priority": 5,
                "base_url": "https://api.openai.com/v1",
                "api_key": "",
                "default_model": "gpt-4o",
                "api_mode": "dual",
                "fallback_enabled": "on",
                "daily_budget_limit": "20.00",
                "monthly_budget_limit": "300.00",
                "description": "updated by test",
                "extra_config_text": '{"timeout": 30, "retry": 2}',
            },
        )
        assert post_response.status_code == 302

        provider.refresh_from_db()
        assert provider.priority == 5
        assert provider.default_model == "gpt-4o"
        # api_key is cleared after encryption; verify it was preserved via encrypted field
        assert provider.api_key == ""  # plaintext cleared after encryption
        assert provider.api_key_encrypted  # encrypted key should exist
        assert provider.extra_config == {"timeout": 30, "retry": 2}

    def test_beta_gate_create_edit_activate_without_admin(self):
        old_active = GateConfigModel(
            config_id="cfg-old",
            risk_profile=GateConfigModel.BALANCED,
            version=1,
            is_active=True,
            regime_constraints={"current_regime": "Recovery", "allowed_asset_classes": ["a_股票"]},
            policy_constraints={"current_level": 1, "max_risk_exposure": 80},
            portfolio_constraints={"max_positions": 8},
            effective_date=date.today(),
        )
        old_active.save()

        create_get = self.client.get("/beta-gate/config/new/")
        assert create_get.status_code == 200

        create_post = self.client.post(
            "/beta-gate/config/new/",
            data={
                "config_id": "cfg-new",
                "risk_profile": GateConfigModel.AGGRESSIVE,
                "is_active": "on",
                "effective_date": date.today().isoformat(),
                "expires_at": "",
                "regime_constraints_text": '{"current_regime":"Overheat","allowed_asset_classes":["美股","黄金"]}',
                "policy_constraints_text": '{"current_level":2,"max_risk_exposure":70,"hard_exclusions":["期货"]}',
                "portfolio_constraints_text": '{"max_positions":6,"max_single_position_weight":25,"max_concentration_ratio":65}',
            },
        )
        assert create_post.status_code == 302

        old_active.refresh_from_db()
        assert old_active.is_active is False
        new_config = GateConfigModel._default_manager.get(config_id="cfg-new")
        assert new_config.is_active is True
        assert new_config.version >= 2

        edit_post = self.client.post(
            f"/beta-gate/config/{new_config.config_id}/edit/",
            data={
                "config_id": new_config.config_id,
                "risk_profile": GateConfigModel.CONSERVATIVE,
                "effective_date": date.today().isoformat(),
                "expires_at": "",
                "regime_constraints_text": '{"current_regime":"Deflation","allowed_asset_classes":["a_债券"]}',
                "policy_constraints_text": '{"current_level":1,"max_risk_exposure":55}',
                "portfolio_constraints_text": '{"max_positions":5,"max_single_position_weight":20,"max_concentration_ratio":50}',
            },
        )
        assert edit_post.status_code == 302
        new_config.refresh_from_db()
        assert new_config.risk_profile == GateConfigModel.CONSERVATIVE
        assert new_config.regime_constraints.get("current_regime") == "Deflation"

        another = GateConfigModel(
            config_id="cfg-another",
            risk_profile=GateConfigModel.BALANCED,
            version=new_config.version + 1,
            is_active=False,
            regime_constraints={"current_regime": "Recovery"},
            policy_constraints={"current_level": 0},
            portfolio_constraints={"max_positions": 10},
            effective_date=date.today(),
        )
        another.save()
        activate_post = self.client.post(f"/beta-gate/config/{another.config_id}/activate/")
        assert activate_post.status_code == 302
        another.refresh_from_db()
        new_config.refresh_from_db()
        assert another.is_active is True
        assert new_config.is_active is False

    def test_beta_gate_version_compare_api_accepts_config_id(self):
        config_v1 = GateConfigModel(
            config_id="cfg-v1",
            risk_profile=GateConfigModel.BALANCED,
            version=1,
            is_active=True,
            regime_constraints={"current_regime": "Recovery"},
            policy_constraints={"current_level": 1},
            portfolio_constraints={"max_positions": 10},
            effective_date=date.today(),
        )
        config_v1.save()
        config_v2 = GateConfigModel(
            config_id="cfg-v2",
            risk_profile=GateConfigModel.AGGRESSIVE,
            version=2,
            is_active=False,
            regime_constraints={"current_regime": "Overheat"},
            policy_constraints={"current_level": 2},
            portfolio_constraints={"max_positions": 6},
            effective_date=date.today(),
        )
        config_v2.save()

        response = self.client.get(
            "/api/beta-gate/version/compare/?version1=cfg-v1&version2=cfg-v2"
        )
        assert response.status_code == 200
        payload = json.loads(response.content.decode("utf-8"))
        assert payload["success"] is True
        assert payload["config1"]["config_id"] == "cfg-v1"
        assert payload["config2"]["config_id"] == "cfg-v2"

    def test_beta_gate_config_suggest_api_fallback_template_without_ai_provider(self):
        response = self.client.post(
            "/api/beta-gate/config/suggest/",
            data=json.dumps(
                {
                    "target": "policy",
                    "requirement": "偏保守，限制高波动资产，风险暴露控制在 60%",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        payload = json.loads(response.content.decode("utf-8"))
        assert payload["success"] is True
        assert payload["fallback"] is True
        assert isinstance(payload["json_object"], dict)
        assert "max_risk_exposure" in payload["json_object"]

