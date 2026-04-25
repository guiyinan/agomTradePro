"""Strategy HTML page save flow regression tests."""

import json
import uuid

import pytest
from django.contrib.auth.models import User
from django.test import TestCase

from apps.account.infrastructure.models import AccountProfileModel
from apps.strategy.infrastructure.models import (
    AIStrategyConfigModel,
    PositionManagementRuleModel,
    RuleConditionModel,
    ScriptConfigModel,
    StrategyModel,
)


@pytest.mark.django_db
class TestStrategyPageSaveFlow(TestCase):
    """Verify strategy create/edit pages can persist submitted data."""

    def setUp(self) -> None:
        """Create an authenticated user with an account profile."""
        unique_id = str(uuid.uuid4())[:8]
        self.user = User.objects.create_user(
            username=f"strategy_page_{unique_id}",
            password="pass123456",
        )
        self.profile = AccountProfileModel.objects.get(user=self.user)
        self.client.force_login(self.user)

    def test_create_page_persists_strategy_rules_and_script(self) -> None:
        """POSTing the create page should save the strategy and nested config."""
        response = self.client.post(
            "/strategy/create/",
            {
                "name": "Hybrid Save Strategy",
                "strategy_type": "hybrid",
                "description": "hybrid smoke test",
                "max_position_pct": "25",
                "max_total_position_pct": "90",
                "stop_loss_pct": "8",
                "version": "1",
                "rules_data": json.dumps(
                    [
                        {
                            "rule_name": "PMI Rule",
                            "rule_type": "macro",
                            "condition_json": {
                                "operator": ">",
                                "indicator": "CN_PMI_MANUFACTURING",
                                "threshold": 50,
                            },
                            "action": "buy",
                            "weight": 0.2,
                            "target_assets": ["510300.SH"],
                            "priority": 10,
                            "is_enabled": True,
                        }
                    ]
                ),
                "script_code": 'signals = []\nprint("ok")',
                "script_language": "python",
            },
        )

        payload = response.json()
        strategy = StrategyModel.objects.get(id=payload["id"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertTrue(payload["success"])
        self.assertEqual(strategy.name, "Hybrid Save Strategy")
        self.assertEqual(strategy.strategy_type, "hybrid")
        self.assertEqual(strategy.created_by, self.profile)
        self.assertEqual(RuleConditionModel.objects.filter(strategy=strategy).count(), 1)
        self.assertTrue(ScriptConfigModel.objects.filter(strategy=strategy).exists())

    def test_edit_page_updates_strategy_and_replaces_nested_config(self) -> None:
        """POSTing the edit page should update fields, bump version, and replace config."""
        strategy = StrategyModel.objects.create(
            name="Editable Strategy",
            strategy_type="hybrid",
            version=1,
            is_active=False,
            description="before edit",
            max_position_pct=20.0,
            max_total_position_pct=95.0,
            stop_loss_pct=10.0,
            created_by=self.profile,
        )
        RuleConditionModel.objects.create(
            strategy=strategy,
            rule_name="Old Rule",
            rule_type="macro",
            condition_json={"operator": ">", "indicator": "CN_PMI_MANUFACTURING", "threshold": 50},
            action="buy",
            weight=0.1,
            target_assets=["510300.SH"],
            priority=10,
            is_enabled=True,
        )
        ScriptConfigModel.objects.create(
            strategy=strategy,
            script_language="python",
            script_code='print("old")',
            script_hash="old-script-hash",
            sandbox_config={"mode": "relaxed"},
            allowed_modules=["math"],
            is_active=True,
        )

        response = self.client.post(
            f"/strategy/{strategy.id}/edit/",
            {
                "name": "Editable Strategy Updated",
                "description": "after edit",
                "max_position_pct": "30",
                "max_total_position_pct": "85",
                "stop_loss_pct": "6",
                "rules_data": json.dumps(
                    [
                        {
                            "rule_name": "New Rule",
                            "rule_type": "macro",
                            "condition_json": {
                                "operator": "<",
                                "indicator": "CN_CPI_YOY",
                                "threshold": 3,
                            },
                            "action": "sell",
                            "weight": 0.15,
                            "target_assets": ["511010.SH"],
                            "priority": 20,
                            "is_enabled": True,
                        }
                    ]
                ),
                "script_code": 'signals = [1]\nprint("updated")',
                "script_language": "python",
            },
        )

        payload = response.json()
        strategy.refresh_from_db()
        new_rule_names = list(
            RuleConditionModel.objects.filter(strategy=strategy).values_list("rule_name", flat=True)
        )
        script_config = ScriptConfigModel.objects.get(strategy=strategy)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertTrue(payload["success"])
        self.assertEqual(strategy.name, "Editable Strategy Updated")
        self.assertEqual(strategy.description, "after edit")
        self.assertEqual(strategy.version, 2)
        self.assertEqual(new_rule_names, ["New Rule"])
        self.assertEqual(script_config.script_code, 'signals = [1]\nprint("updated")')

    def test_edit_page_can_clear_existing_script_config(self) -> None:
        """Clearing the script editor should remove the persisted script config."""
        strategy = StrategyModel.objects.create(
            name="Script Cleanup Strategy",
            strategy_type="script_based",
            version=1,
            is_active=False,
            description="before clear",
            max_position_pct=20.0,
            max_total_position_pct=95.0,
            stop_loss_pct=10.0,
            created_by=self.profile,
        )
        ScriptConfigModel.objects.create(
            strategy=strategy,
            script_language="python",
            script_code='print("stale")',
            script_hash="stale-script-hash",
            sandbox_config={"mode": "relaxed"},
            allowed_modules=["math"],
            is_active=True,
        )

        response = self.client.post(
            f"/strategy/{strategy.id}/edit/",
            {
                "name": "Script Cleanup Strategy",
                "description": "after clear",
                "max_position_pct": "20",
                "max_total_position_pct": "95",
                "stop_loss_pct": "10",
                "script_code": "",
                "script_language": "python",
            },
        )

        strategy.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ScriptConfigModel.objects.filter(strategy=strategy).exists())
        self.assertEqual(strategy.version, 2)

    def test_create_page_persists_ai_config_and_position_rule(self) -> None:
        """AI-driven page submissions should save AI parameters and position expressions."""
        response = self.client.post(
            "/strategy/create/",
            {
                "name": "AI Managed Strategy",
                "strategy_type": "ai_driven",
                "description": "ai strategy with position rule",
                "max_position_pct": "20",
                "max_total_position_pct": "95",
                "stop_loss_pct": "10",
                "version": "1",
                "ai_temperature": "0.3",
                "ai_max_tokens": "1200",
                "ai_approval_mode": "conditional",
                "ai_confidence_threshold": "0.75",
                "position_rule_is_active": "on",
                "position_rule_name": "ATR Rule",
                "position_rule_description": "ATR based rule",
                "position_rule_price_precision": "3",
                "position_rule_variables_schema": json.dumps(
                    [{"name": "current_price", "type": "number", "required": True}]
                ),
                "position_rule_buy_condition_expr": "current_price > 0",
                "position_rule_sell_condition_expr": "current_price < 0",
                "position_rule_buy_price_expr": "current_price",
                "position_rule_sell_price_expr": "current_price",
                "position_rule_stop_loss_expr": "current_price * 0.95",
                "position_rule_take_profit_expr": "current_price * 1.1",
                "position_rule_position_size_expr": "100",
                "position_rule_metadata": json.dumps({"template": "test"}),
            },
        )

        payload = response.json()
        strategy = StrategyModel.objects.get(id=payload["id"])
        ai_config = AIStrategyConfigModel.objects.get(strategy=strategy)
        position_rule = PositionManagementRuleModel.objects.get(strategy=strategy)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(ai_config.temperature, 0.3)
        self.assertEqual(ai_config.max_tokens, 1200)
        self.assertEqual(ai_config.approval_mode, "conditional")
        self.assertEqual(ai_config.confidence_threshold, 0.75)
        self.assertEqual(position_rule.name, "ATR Rule")
        self.assertEqual(position_rule.price_precision, 3)
        self.assertEqual(position_rule.position_size_expr, "100")

    def test_create_page_allows_duplicate_script_code_across_strategies(self) -> None:
        """Multiple strategies should be able to reuse the same script content."""
        payload = {
            "strategy_type": "script_based",
            "description": "shared template",
            "max_position_pct": "20",
            "max_total_position_pct": "95",
            "stop_loss_pct": "10",
            "version": "1",
            "script_code": 'signals = []\nprint("shared-template")',
            "script_language": "python",
        }

        response_1 = self.client.post("/strategy/create/", {"name": "Shared Script A", **payload})
        response_2 = self.client.post("/strategy/create/", {"name": "Shared Script B", **payload})

        self.assertEqual(response_1.status_code, 200)
        self.assertEqual(response_2.status_code, 200)
        self.assertTrue(response_1.json()["success"])
        self.assertTrue(response_2.json()["success"])
        self.assertEqual(
            ScriptConfigModel.objects.filter(script_code='signals = []\nprint("shared-template")').count(),
            2,
        )

    def test_edit_page_rejects_invalid_rules_without_deleting_existing_rules(self) -> None:
        """Invalid rule payloads should fail atomically and keep prior rules intact."""
        strategy = StrategyModel.objects.create(
            name="Atomic Rule Strategy",
            strategy_type="rule_based",
            version=1,
            is_active=False,
            description="before invalid edit",
            max_position_pct=20.0,
            max_total_position_pct=95.0,
            stop_loss_pct=10.0,
            created_by=self.profile,
        )
        RuleConditionModel.objects.create(
            strategy=strategy,
            rule_name="Stable Rule",
            rule_type="macro",
            condition_json={"operator": ">", "indicator": "CN_PMI_MANUFACTURING", "threshold": 50},
            action="buy",
            weight=0.1,
            target_assets=["510300.SH"],
            priority=10,
            is_enabled=True,
        )

        response = self.client.post(
            f"/strategy/{strategy.id}/edit/",
            {
                "name": "Atomic Rule Strategy",
                "description": "broken edit",
                "max_position_pct": "20",
                "max_total_position_pct": "95",
                "stop_loss_pct": "10",
                "rules_data": "{broken json",
            },
        )

        strategy.refresh_from_db()
        rule_names = list(
            RuleConditionModel.objects.filter(strategy=strategy).values_list("rule_name", flat=True)
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertEqual(rule_names, ["Stable Rule"])
        self.assertEqual(strategy.version, 1)
