from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.management import CommandError

from apps.simulated_trading.application import readiness_services
from apps.simulated_trading.application.readiness_services import (
    AccountReadinessRepairRequest,
    repair_personal_account_readiness,
)
from apps.simulated_trading.management.commands.repair_personal_account_readiness import (
    _parse_capital,
)


def test_repair_personal_account_readiness_dry_run_reports_missing_simulated_account(
    monkeypatch,
):
    monkeypatch.setattr(
        readiness_services,
        "list_active_account_targets",
        lambda: [{"user_id": 7, "account_id": 101}],
    )
    monkeypatch.setattr(
        readiness_services,
        "list_dashboard_account_payloads",
        lambda user_id: [
            {
                "id": 101,
                "type_code": "real",
                "is_active": True,
                "total_value": 0.0,
            }
        ],
    )
    monkeypatch.setattr(
        readiness_services,
        "get_application_user_by_id",
        lambda user_id: SimpleNamespace(id=user_id, username="alice"),
    )

    payload = repair_personal_account_readiness(AccountReadinessRepairRequest(dry_run=True))

    assert payload["status"] == "action_required"
    assert payload["results"][0]["status"] == "would_create"
    assert payload["results"][0]["zero_equity_account_ids"] == [101]


def test_repair_personal_account_readiness_creates_default_simulated_account(
    monkeypatch,
):
    created_payload: dict[str, object] = {}

    class FakeRepo:
        def create_account_model_for_user(self, **kwargs):
            created_payload.update(kwargs)
            return SimpleNamespace(id=202)

    monkeypatch.setattr(
        readiness_services,
        "list_active_account_targets",
        lambda: [{"user_id": 7, "account_id": 101}],
    )
    monkeypatch.setattr(
        readiness_services,
        "list_dashboard_account_payloads",
        lambda user_id: [
            {
                "id": 101,
                "type_code": "real",
                "is_active": True,
                "total_value": 0.0,
            }
        ],
    )
    monkeypatch.setattr(
        readiness_services,
        "get_application_user_by_id",
        lambda user_id: SimpleNamespace(id=user_id, username="alice"),
    )
    monkeypatch.setattr(
        readiness_services,
        "get_simulated_account_repository",
        lambda: FakeRepo(),
    )

    payload = repair_personal_account_readiness(
        AccountReadinessRepairRequest(
            dry_run=False,
            initial_capital=Decimal("200000.00"),
        )
    )

    assert payload["status"] == "repaired"
    assert payload["results"][0]["created_account_id"] == 202
    assert created_payload["account_name"] == "alice_投研验收模拟仓"
    assert created_payload["account_type"] == "simulated"
    assert created_payload["initial_capital"] == Decimal("200000.00")


def test_repair_personal_account_readiness_skips_when_positive_equity_exists(
    monkeypatch,
):
    monkeypatch.setattr(
        readiness_services,
        "list_active_account_targets",
        lambda: [{"user_id": 7, "account_id": 101}],
    )
    monkeypatch.setattr(
        readiness_services,
        "list_dashboard_account_payloads",
        lambda user_id: [
            {
                "id": 101,
                "type_code": "real",
                "is_active": True,
                "total_value": 0.0,
            },
            {
                "id": 102,
                "type_code": "simulated",
                "is_active": True,
                "total_value": 1000000.0,
            },
        ],
    )

    payload = repair_personal_account_readiness(AccountReadinessRepairRequest(dry_run=False))

    assert payload["status"] == "ok"
    assert payload["results"][0]["decision_ready_account_ids"] == [102]


def test_parse_capital_rejects_non_positive_values():
    with pytest.raises(CommandError):
        _parse_capital("0")
