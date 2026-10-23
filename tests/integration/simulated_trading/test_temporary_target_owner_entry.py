"""Real owner HTTP coverage for one-request target input and read-only preview."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import (
    DailyInspectionReportModel,
    RebalanceProposalModel,
)
from apps.strategy.infrastructure.models import PositionManagementRuleModel
from tests.integration.simulated_trading.test_readonly_rebalance_plan_owner_api import (
    ASSET_BUY,
    ASSET_SELL,
    _assert_no_financial_writes,
    _create_owner_account,
    _create_strategy,
    _financial_snapshot,
    _install_preview_ports,
)

pytestmark = pytest.mark.django_db


def test_owner_temporary_targets_are_exact_read_only_and_audited_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject bad targets before audit, then persist only one inspection report."""

    user, account = _create_owner_account(
        username="m1-temporary-target",
        positions=((ASSET_SELL, "Temporary target held asset", True),),
        cash=Decimal("5000.00"),
        max_position_pct=100.0,
        max_total_position_pct=100.0,
        stop_loss_pct=8.0,
    )
    account.auto_trading_enabled = False
    account.save(update_fields=("auto_trading_enabled",))
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_SELL: 0.0, ASSET_BUY: 1.0},
        max_position_pct=100.0,
        max_total_position_pct=100.0,
        stop_loss_pct=10.0,
    )
    rule = PositionManagementRuleModel.objects.get(strategy_id=strategy.pk)
    rule.metadata = {**rule.metadata, "account_id": account.pk}
    rule.save(update_fields=("metadata",))
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        classification_asset_types={ASSET_BUY: "equity"},
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)
    endpoint = f"/api/account/accounts/{account.pk}/inspections/run/"
    target_text = f"{ASSET_SELL},0\n{ASSET_BUY},90.000001"

    explicit_strategy = client.post(
        endpoint,
        {"strategy_id": strategy.pk, "temporary_target_weights": target_text},
        format="json",
    )
    duplicate_target = client.post(
        endpoint,
        {
            "temporary_target_weights": f"{ASSET_SELL},0\n{ASSET_SELL},0",
        },
        format="json",
    )

    assert explicit_strategy.status_code == 400
    assert duplicate_target.status_code == 400
    assert _financial_snapshot() == before
    assert DailyInspectionReportModel.objects.filter(account_id=account.pk).count() == (
        report_count_before
    )
    assert RebalanceProposalModel.objects.filter(account_id=account.pk).count() == (
        proposal_count_before
    )

    response = client.post(
        endpoint,
        {"temporary_target_weights": target_text},
        format="json",
    )

    assert response.status_code == 200
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    report: dict[str, Any] = response.json()["reports"][0]
    plan = report["plan"]
    assert report["strategy_id"] == strategy.pk
    target_record = next(
        row for row in report["checks"] if row.get("scope") == "temporary_target_entry"
    )
    assert target_record["source"] == "user_entered_temporary"
    assert target_record["target_weights"] == {
        ASSET_SELL: "0",
        ASSET_BUY: "0.90000001",
    }
    assert target_record["residual_cash_weight"] == "0.09999999"
    check_by_code = {
        row["asset_code"]: row for row in report["checks"] if row.get("scope") == "asset"
    }
    assert Decimal(check_by_code[ASSET_BUY]["strategy_target_weight"]) == Decimal("1")
    assert check_by_code[ASSET_BUY]["target_weight"] == "0.90000001"
    assert plan["read_only"] is True
    assert plan["execution_submitted"] is False
    assert plan["allocation_items"] == []
    assert plan["funding_status"] == "conditional"
    assert plan["sell_before_buy"]["buy_requires_settled_sales"] is True
    assert plan["sell_before_buy"]["sequence"] == "sell_then_buy"
    assert Decimal(plan["projected_cash_after_sells"]) == (
        Decimal(plan["cash_before"]) + Decimal(plan["estimated_sell_net"])
    )
    assert Decimal(plan["estimated_sell_fees"]) > 0
    assert Decimal(plan["estimated_buy_total"]) == (
        Decimal(plan["estimated_buy_gross"]) + Decimal(plan["estimated_buy_fees"])
    )
    assert Decimal(plan["projected_cash_after_buys"]) == (
        Decimal(plan["projected_cash_after_sells"]) - Decimal(plan["estimated_buy_total"])
    )
    rows = {row["asset_code"]: row for row in plan["asset_items"]}
    assert set(rows) == {ASSET_SELL, ASSET_BUY}
    assert rows[ASSET_SELL]["action"] == "sell"
    assert Decimal(rows[ASSET_SELL]["target_weight"]) == Decimal("0")
    assert rows[ASSET_BUY]["action"] == "buy"
    assert rows[ASSET_BUY]["asset_type"] == "equity"
    assert rows[ASSET_BUY]["status"] == "conditional"
    assert Decimal(rows[ASSET_BUY]["target_weight"]) == Decimal("0.90000001")
    assert "BUY_DEPENDS_ON_SETTLED_SALES" in rows[ASSET_BUY]["reason_codes"]
    buy_fee = rows[ASSET_BUY]["fee"]
    assert Decimal(buy_fee["total"]) > 0
    assert Decimal(buy_fee["total"]) == sum(
        Decimal(buy_fee[key]) for key in ("commission", "transfer_fee", "stamp_duty", "slippage")
    )
    risk_context = plan["risk_context"]
    assert Decimal(risk_context["strategy_max_position_pct"]) == Decimal("100")
    assert Decimal(risk_context["strategy_max_total_position_pct"]) == Decimal("100")
    assert Decimal(risk_context["strategy_stop_loss_pct"]) == Decimal("10")
    assert Decimal(risk_context["account_max_position_pct"]) == Decimal("100")
    assert Decimal(risk_context["account_max_total_position_pct"]) == Decimal("100")
    assert Decimal(risk_context["account_stop_loss_pct"]) == Decimal("8")
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )
