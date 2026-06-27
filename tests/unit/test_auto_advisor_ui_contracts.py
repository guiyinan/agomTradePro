from __future__ import annotations

from pathlib import Path

import pytest

from apps.terminal.application.services import CommandExecutionService
from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository


def test_decision_workspace_template_contains_auto_advisor_panel():
    template = Path("core/templates/decision/workspace.html").read_text(encoding="utf-8")

    assert "今日自动投顾" in template
    assert "advisor-order-list" in template
    assert "/api/decision/advisor/sheet/" in template
    assert "copyAdvisorManualList" in template


@pytest.mark.django_db
def test_tui_metadata_injects_auto_advisor_screen_and_action(settings):
    payload = PublishedTuiMetadataRepository().load_published()

    screens = {screen["key"]: screen for screen in payload["screens"]}
    actions = {action["key"]: action for action in payload["actions"]}

    assert "command-center.auto-advisor" in screens
    assert screens["command-center.auto-advisor"]["default_action_key"] == "advisor.today_sheet"
    assert "advisor.today_sheet" in actions
    assert actions["advisor.today_sheet"]["endpoint"] == "/api/decision/advisor/sheet/"
    assert actions["advisor.today_sheet"]["fields"][0]["key"] == "account_id"


@pytest.mark.django_db
def test_tui_metadata_injects_risk_center_screen_and_actions(settings):
    payload = PublishedTuiMetadataRepository().load_published()

    modules = {module["key"]: module for module in payload["modules"]}
    screens = {screen["key"]: screen for screen in payload["screens"]}
    actions = {action["key"]: action for action in payload["actions"]}

    assert modules["risk-center"]["label"] == "风控中心"
    assert screens["risk-center.overview"]["default_action_key"] == "risk-center.effective-policy"
    assert actions["risk-center.floor"]["endpoint"] == "/api/risk-center/floor/"
    assert actions["risk-center.effective-policy"]["fields"][0]["key"] == "account_id"
    assert actions["risk-center.pre-trade-check"]["endpoint"] == "/api/risk-center/pre-trade-check/"
    assert actions["risk-center.pre-trade-check"]["fields"][1]["key"] == "symbol"
    assert actions["risk-center.update-floor"]["risk"] == "write"
    assert actions["risk-center.update-floor"]["confirmation_required"] is True
    assert actions["risk-center.upsert-policy"]["method"] == "POST"


def test_advisor_today_terminal_formatter_outputs_account_order_summary():
    output = CommandExecutionService._format_advisor_today_output(
        {
            "success": True,
            "data": {
                "account": {
                    "account_id": "1",
                    "account_name": "A",
                    "account_type_label": "模拟盘账户",
                    "total_asset": 100000,
                    "available_cash": 20000,
                    "holding_count": 2,
                },
                "baseline": "existing_positions",
                "today_conclusion": "ACT",
                "order_summary": {
                    "total": 2,
                    "buy": 1,
                    "add": 0,
                    "reduce": 1,
                    "exit": 0,
                    "blocked": 0,
                },
                "order_intents": [
                    {
                        "side": "BUY",
                        "asset_code": "AAA",
                        "asset_name": "Alpha",
                        "delta_quantity": 100,
                        "estimated_amount": 1000,
                        "price_band": {"label": "9.90 - 10.10"},
                        "blocking_status": "OK",
                    }
                ],
                "blockers": [],
                "next_actions": [{"label": "刷新推荐", "hint": "重新生成账户推荐输入。"}],
            },
        }
    )

    assert "账户: A" in output
    assert "今日结论: ACT" in output
    assert "建议订单: 共 2 单" in output
    assert "BUY AAA Alpha" in output
