"""Owner-route integration coverage for manual targets without a strategy."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from typing import Any, NoReturn, cast
from uuid import uuid4

import pytest
from django.db.models import Model
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.simulated_trading.domain.entities import SimulatedAccount
from apps.simulated_trading.infrastructure.account_mapper import SimulatedAccountMapper
from apps.simulated_trading.infrastructure.models import (
    DailyInspectionReportModel,
    RebalanceProposalModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from apps.strategy.infrastructure.models import (
    PortfolioStrategyAssignmentModel,
    PositionManagementRuleModel,
    StrategyModel,
)
from apps.strategy.infrastructure.repositories import DjangoStrategyGatewayRepository
from tests.integration.simulated_trading import (
    test_readonly_rebalance_plan_owner_api as owner_fixtures,
)

pytestmark = pytest.mark.django_db

ASSET_SELL = owner_fixtures.ASSET_SELL
ASSET_BUY = owner_fixtures.ASSET_BUY


def _post_manual_targets(
    *,
    client: APIClient,
    account_id: int,
    target_text: str,
) -> Response:
    """Call the real owner-scoped inspection endpoint without a strategy id."""

    return client.post(
        f"/api/account/accounts/{account_id}/inspections/run/",
        {
            "inspection_date": timezone.localdate().isoformat(),
            "auto_create_proposal": False,
            "temporary_target_weights": target_text,
        },
        format="json",
    )


def _response_report(response: Response) -> dict[str, Any]:
    """Narrow the API JSON envelope to its single report object."""

    payload = response.json()
    assert isinstance(payload, dict)
    reports = payload.get("reports")
    assert isinstance(reports, list) and len(reports) == 1
    report = reports[0]
    assert isinstance(report, dict)
    return cast(dict[str, Any], report)


def _response_plan(response: Response) -> dict[str, Any]:
    """Narrow the report JSON to its projected plan."""

    report = _response_report(response)
    plan = report.get("plan")
    assert isinstance(plan, dict)
    return cast(dict[str, Any], plan)


def _asset_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only object-shaped asset rows from a plan JSON payload."""

    rows = plan.get("asset_items")
    assert isinstance(rows, list)
    return [cast(dict[str, Any], row) for row in rows if isinstance(row, dict)]


def _reason_codes(*payloads: dict[str, Any]) -> set[str]:
    """Collect stable reason codes from report checks and preview rows."""

    found: set[str] = set()
    for payload in payloads:
        direct_codes = payload.get("reason_codes")
        if isinstance(direct_codes, list):
            found.update(code for code in direct_codes if isinstance(code, str))
        for key in ("checks", "asset_items"):
            rows = payload.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_codes = row.get("reason_codes")
                if isinstance(row_codes, list):
                    found.update(code for code in row_codes if isinstance(code, str))
                risk_reason = row.get("risk_rule_reason_code")
                if isinstance(risk_reason, str):
                    found.add(risk_reason)
    return found


def _configuration_snapshot() -> tuple[tuple[tuple[object, ...], ...], ...]:
    """Capture strategy, rule and account-binding tables in stable order."""

    models: tuple[type[Model], ...] = (
        StrategyModel,
        PositionManagementRuleModel,
        PortfolioStrategyAssignmentModel,
    )
    return tuple(owner_fixtures._table_snapshot(model) for model in models)


def _assert_read_only_result(
    *,
    account: SimulatedAccountModel,
    financial_before: tuple[tuple[tuple[object, ...], ...], ...],
    report_count_before: int,
    proposal_count_before: int,
    configuration_before: tuple[tuple[tuple[object, ...], ...], ...],
) -> None:
    """Require one audit upsert at most and no proposal, ledger or rule writes."""

    owner_fixtures._assert_no_financial_writes(
        before=financial_before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )
    assert _configuration_snapshot() == configuration_before


def _capture_write_baseline(
    account: SimulatedAccountModel,
) -> tuple[
    tuple[tuple[tuple[object, ...], ...], ...],
    int,
    int,
    tuple[tuple[tuple[object, ...], ...], ...],
]:
    """Capture financial, audit, proposal and strategy configuration state."""

    return (
        owner_fixtures._financial_snapshot(),
        DailyInspectionReportModel.objects.filter(account_id=account.pk).count(),
        RebalanceProposalModel.objects.filter(account_id=account.pk).count(),
        _configuration_snapshot(),
    )


def _install_manual_preview_ports(
    monkeypatch: pytest.MonkeyPatch,
    *,
    account: SimulatedAccountModel,
    user_id: int,
    classification_available: bool = True,
    quantity_rule_available: bool = True,
    fee_policy_available: bool = True,
    stale_quote: bool = False,
) -> tuple[
    owner_fixtures._FixturePriceReader,
    owner_fixtures._FixtureIdentityReader,
    owner_fixtures._FixtureFeePolicyReader,
    owner_fixtures._FixtureQuantityRuleReader,
]:
    """Install the existing typed external-evidence fixture around the real builder."""

    price_results: dict[str, MarketPriceResult | None] | None = None
    if stale_quote:
        price_results = {
            ASSET_BUY: owner_fixtures._fixture_price_result(
                asset_code=ASSET_BUY,
                freshness="close_fallback",
                as_of=timezone.localdate() - timedelta(days=30),
                source="fixture:stale-close",
                is_fallback=True,
                observed_at=None,
            )
        }
        valuation_module = import_module(
            "apps.simulated_trading.application.rebalance_preview_valuation"
        )
        monkeypatch.setattr(
            valuation_module,
            "latest_daily_market_observation_is_current",
            lambda **kwargs: False,
        )
    return owner_fixtures._install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user_id,
        classification_asset_types={ASSET_BUY: "equity"},
        missing_classification_codes=(
            frozenset() if classification_available else frozenset({ASSET_BUY})
        ),
        missing_quantity_rule_codes=(
            frozenset() if quantity_rule_available else frozenset({ASSET_BUY})
        ),
        fee_policy_available=fee_policy_available,
        price_results=price_results,
    )


def test_owner_route_confirmed_unconfigured_empty_account_previews_exact_buy_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmed empty strategy selection may preview a qualified 10% BUY."""

    user, account = owner_fixtures._create_owner_account(
        username="r9-owner-no-strategy-buy",
        positions=(),
        cash=Decimal("100000.00"),
        max_position_pct=20.0,
        max_total_position_pct=95.0,
    )
    assert not PortfolioStrategyAssignmentModel.objects.filter(
        portfolio_id=account.pk,
        is_active=True,
    ).exists()
    assert not PositionManagementRuleModel.objects.filter(
        metadata__account_id=account.pk,
        is_active=True,
    ).exists()
    prices, identities, fees, quantity_rules = _install_manual_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
    )
    financial_before, report_count_before, proposal_count_before, configuration_before = (
        _capture_write_baseline(account)
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_manual_targets(
        client=client,
        account_id=account.pk,
        target_text=f"{ASSET_BUY},10",
    )

    assert response.status_code == 200
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    report = _response_report(response)
    plan = cast(dict[str, Any], report["plan"])
    assert plan["status"] == "ready"
    assert report["strategy_id"] is None
    assert report["position_rule_id"] is None
    assert report["strategy_selection_state"] == "confirmed_unconfigured"
    target_summary = cast(dict[str, Any], report["summary"]["temporary_target"])
    assert target_summary["target_weights"] == {ASSET_BUY: "0.1"}
    assert Decimal(target_summary["security_weight_total"]) == Decimal("0.1")
    assert Decimal(target_summary["residual_cash_weight"]) == Decimal("0.9")
    assert plan["plan_kind"] == "rebalance_preview"
    assert plan["read_only"] is True
    assert plan["execution_submitted"] is False
    assert plan["funding_status"] == "known"
    assert plan["sell_before_buy"]["required"] is False
    risk_context = cast(dict[str, Any], plan["risk_context"])
    assert risk_context["strategy_selection_state"] == "confirmed_unconfigured"
    assert risk_context["strategy_policy_applicability"] == "not_applicable"
    assert risk_context["strategy_id"] is None
    assert risk_context["strategy_max_position_pct"] is None
    assert risk_context["strategy_max_total_position_pct"] is None
    assert risk_context["strategy_stop_loss_pct"] is None
    assert Decimal(risk_context["account_max_position_pct"]) == Decimal("20")
    assert Decimal(risk_context["account_max_total_position_pct"]) == Decimal("95")

    rows = {row["asset_code"]: row for row in _asset_rows(plan)}
    assert set(rows) == {ASSET_BUY}
    buy = rows[ASSET_BUY]
    assert buy["target_mode"] == "user_target_difference"
    assert buy["action"] == "buy"
    assert buy["status"] == "ready"
    assert Decimal(buy["target_weight"]) == Decimal("0.1")
    assert Decimal(buy["target_amount"]) == Decimal("10000.00")
    assert Decimal(buy["suggested_quantity"]) > 0
    assert Decimal(buy["actionable_quantity"]) == Decimal(buy["suggested_quantity"])
    assert Decimal(buy["actionable_quantity"]) % Decimal("100") == 0
    assert buy["quantity_unit"] == "shares"
    assert buy["quantity_rule"]["rule_id"].startswith("fixture-")
    assert buy["quantity_rule"]["buy"]["step"] == "100"
    assert buy["classification_evidence"]["simulated_asset_type"] == "equity"
    assert buy["classification_evidence"]["must_not_use_for_decision"] is True
    assert buy["classification_evidence"]["must_not_execute"] is True
    assert buy["identity"]["purpose"] == "normal_simulated_current_reference"
    assert buy["identity"]["must_not_use_for_decision"] is True
    assert buy["identity"]["must_not_execute"] is True
    assert buy["price_source"] == owner_fixtures.PRICE_SOURCE
    assert buy["price_freshness"] == "realtime"
    assert buy["price_observed_at"] == prices.observed_at.isoformat()
    assert buy["price_observed_at"] != plan["as_of"]
    assert identities.calls
    assert quantity_rules.calls
    assert fees.calls

    fee = cast(dict[str, Any], buy["fee"])
    fee_components = sum(
        (Decimal(fee[key]) for key in ("commission", "transfer_fee", "stamp_duty", "slippage")),
        Decimal("0"),
    )
    assert fee["policy_id"] == "m1-read-only-preview-fixture"
    assert fee["content_hash"]
    assert fee["transaction_case"]["asset_type"] == "equity"
    assert fee["transaction_case"]["side"] == "buy"
    assert Decimal(fee["total"]) == fee_components
    assert Decimal(plan["cash_before"]) == Decimal("100000.00")
    assert Decimal(plan["available_cash_before"]) == Decimal("100000.00")
    assert Decimal(plan["estimated_buy_fees"]) == Decimal(fee["total"])
    assert Decimal(plan["estimated_buy_total"]) == (
        Decimal(plan["estimated_buy_gross"]) + Decimal(plan["estimated_buy_fees"])
    )
    assert Decimal(plan["projected_cash_after_buys"]) == (
        Decimal(plan["cash_before"]) - Decimal(plan["estimated_buy_total"])
    )
    _assert_read_only_result(
        account=account,
        financial_before=financial_before,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
        configuration_before=configuration_before,
    )


def test_owner_route_manual_targets_include_held_zero_sell_and_conditional_buy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real preview builder preserves SELL-to-zero before a user-target BUY."""

    user, account = owner_fixtures._create_owner_account(
        username="r9-owner-held-sell-buy",
        positions=((ASSET_SELL, "Explicit full-close holding", True),),
        cash=Decimal("100000.00"),
        max_position_pct=50.0,
        max_total_position_pct=95.0,
    )
    prices, _, fees, _ = _install_manual_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
    )
    financial_before, report_count_before, proposal_count_before, configuration_before = (
        _capture_write_baseline(account)
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_manual_targets(
        client=client,
        account_id=account.pk,
        target_text=f"{ASSET_SELL},0\n{ASSET_BUY},10",
    )

    assert response.status_code == 200
    report = _response_report(response)
    plan = cast(dict[str, Any], report["plan"])
    target_summary = cast(dict[str, Any], report["summary"]["temporary_target"])
    assert target_summary["target_weights"] == {
        ASSET_SELL: "0",
        ASSET_BUY: "0.1",
    }
    assert Decimal(target_summary["residual_cash_weight"]) == Decimal("0.9")
    assert plan["risk_context"]["strategy_selection_state"] == "confirmed_unconfigured"
    assert plan["risk_context"]["strategy_policy_applicability"] == "not_applicable"
    rows = {row["asset_code"]: row for row in _asset_rows(plan)}
    assert set(rows) == {ASSET_SELL, ASSET_BUY}
    sell = rows[ASSET_SELL]
    buy = rows[ASSET_BUY]
    assert sell["target_mode"] == "user_target_difference"
    assert sell["action"] == "sell"
    assert Decimal(sell["target_weight"]) == Decimal("0")
    assert Decimal(sell["target_quantity"]) == Decimal("0")
    assert Decimal(sell["actionable_quantity"]) > 0
    assert buy["target_mode"] == "user_target_difference"
    assert buy["action"] == "buy"
    assert buy["status"] == "conditional"
    assert "BUY_DEPENDS_ON_SETTLED_SALES" in buy["reason_codes"]
    assert buy["actionable_quantity"] is None
    assert Decimal(buy["suggested_quantity"]) > 0
    assert plan["sell_before_buy"]["required"] is True
    assert plan["sell_before_buy"]["sequence"] == "sell_then_buy"
    assert plan["funding_status"] == "conditional"
    assert all(row["price_observed_at"] == prices.observed_at.isoformat() for row in rows.values())
    assert all(row["fee"] is not None for row in rows.values())
    assert fees.calls
    _assert_read_only_result(
        account=account,
        financial_before=financial_before,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
        configuration_before=configuration_before,
    )


def test_owner_route_selection_query_failure_is_unavailable_not_manual_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed real selection query cannot be interpreted as no strategy."""

    user, account = owner_fixtures._create_owner_account(
        username="r9-owner-selection-unavailable",
        positions=(),
        cash=Decimal("100000.00"),
    )
    _install_manual_preview_ports(monkeypatch, account=account, user_id=user.pk)

    def fail_selection_query(
        repository: DjangoStrategyGatewayRepository,
        account_id: int,
        strategy_id: int | None = None,
    ) -> NoReturn:
        del repository, account_id, strategy_id
        raise RuntimeError("fixture selection query unavailable")

    monkeypatch.setattr(
        DjangoStrategyGatewayRepository,
        "get_inspection_selection",
        fail_selection_query,
    )
    financial_before, report_count_before, proposal_count_before, configuration_before = (
        _capture_write_baseline(account)
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_manual_targets(
        client=client,
        account_id=account.pk,
        target_text=f"{ASSET_BUY},10",
    )

    assert response.status_code == 200
    report = _response_report(response)
    plan = cast(dict[str, Any], report["plan"])
    risk_context = cast(dict[str, Any], plan["risk_context"])
    assert report["strategy_selection_state"] == "unavailable"
    assert risk_context["strategy_selection_state"] == "unavailable"
    assert risk_context["strategy_policy_applicability"] == "unknown"
    assert risk_context["strategy_max_position_pct"] is None
    assert risk_context["strategy_max_total_position_pct"] is None
    assert "STRATEGY_SELECTION_UNAVAILABLE" in _reason_codes(report, plan)
    assert all(
        row.get("target_mode") != "user_target_difference"
        and row.get("actionable_quantity") is None
        for row in _asset_rows(plan)
    )
    assert plan["status"] == "blocked"
    _assert_read_only_result(
        account=account,
        financial_before=financial_before,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
        configuration_before=configuration_before,
    )


def test_owner_route_incomplete_configured_policy_does_not_fall_through_to_manual_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active assignment without an active rule remains restrictive."""

    user, account = owner_fixtures._create_owner_account(
        username="r9-owner-incomplete-policy",
        positions=(),
        cash=Decimal("100000.00"),
    )
    profile = owner_fixtures.AccountProfileModel.objects.get(user=user)
    strategy = StrategyModel.objects.create(
        name=f"R9 incomplete strategy {uuid4().hex[:8]}",
        description="Test-only active assignment with no active rule",
        strategy_type="rule_based",
        created_by=profile,
        is_active=True,
        max_position_pct=20.0,
        max_total_position_pct=95.0,
    )
    PortfolioStrategyAssignmentModel.objects.create(
        portfolio=account,
        strategy=strategy,
        assigned_by=profile,
        is_active=True,
    )
    assert not PositionManagementRuleModel.objects.filter(
        strategy_id=strategy.pk,
        is_active=True,
    ).exists()
    _install_manual_preview_ports(monkeypatch, account=account, user_id=user.pk)
    financial_before, report_count_before, proposal_count_before, configuration_before = (
        _capture_write_baseline(account)
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_manual_targets(
        client=client,
        account_id=account.pk,
        target_text=f"{ASSET_BUY},10",
    )

    assert response.status_code == 200
    report = _response_report(response)
    plan = cast(dict[str, Any], report["plan"])
    risk_context = cast(dict[str, Any], plan["risk_context"])
    assert report["strategy_id"] == strategy.pk
    assert report["strategy_selection_state"] == "configured"
    assert risk_context["strategy_selection_state"] == "configured"
    assert risk_context["strategy_policy_applicability"] == "applicable"
    assert Decimal(risk_context["strategy_max_position_pct"]) == Decimal("20")
    assert Decimal(risk_context["strategy_max_total_position_pct"]) == Decimal("95")
    assert "STRATEGY_RULE_EVALUATION_UNAVAILABLE" in _reason_codes(report, plan)
    assert all(row.get("target_mode") != "user_target_difference" for row in _asset_rows(plan))
    assert plan["status"] == "blocked"
    _assert_read_only_result(
        account=account,
        financial_before=financial_before,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
        configuration_before=configuration_before,
    )


def test_owner_route_unknown_account_limit_blocks_unconfigured_buy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing cap stays unknown through both account and locked-resource reads."""

    user, account = owner_fixtures._create_owner_account(
        username="r9-owner-unknown-account-limit",
        positions=(),
        cash=Decimal("100000.00"),
    )
    original_to_entity = SimulatedAccountMapper.to_entity

    def map_with_unknown_position_cap(model: SimulatedAccountModel) -> SimulatedAccount:
        """Inject one absent cap at the shared ORM-to-Domain mapping boundary."""

        entity = original_to_entity(model)
        if model.pk == account.pk:
            # The persisted column is non-null. This test-only adapter injection
            # keeps the repository read and resource snapshot on the same facts.
            return replace(entity, max_position_pct=None)
        return entity

    monkeypatch.setattr(
        SimulatedAccountMapper,
        "to_entity",
        staticmethod(map_with_unknown_position_cap),
    )
    _install_manual_preview_ports(monkeypatch, account=account, user_id=user.pk)
    financial_before, report_count_before, proposal_count_before, configuration_before = (
        _capture_write_baseline(account)
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_manual_targets(
        client=client,
        account_id=account.pk,
        target_text=f"{ASSET_BUY},10",
    )

    assert response.status_code == 200
    report = _response_report(response)
    plan = cast(dict[str, Any], report["plan"])
    rows = {row["asset_code"]: row for row in _asset_rows(plan)}
    buy = rows[ASSET_BUY]
    assert report["strategy_selection_state"] == "confirmed_unconfigured"
    assert plan["risk_context"]["strategy_policy_applicability"] == "not_applicable"
    assert plan["risk_context"]["account_max_position_pct"] is None
    assert buy["status"] == "blocked"
    assert "ACCOUNT_MAX_POSITION_LIMIT_UNKNOWN" in buy["reason_codes"]
    assert buy["actionable_quantity"] is None
    _assert_read_only_result(
        account=account,
        financial_before=financial_before,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
        configuration_before=configuration_before,
    )


def test_owner_route_exceeded_account_cap_blocks_unconfigured_buy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manual target cannot exceed the account's independent position cap."""

    user, account = owner_fixtures._create_owner_account(
        username="r9-owner-exceeded-account-limit",
        positions=(),
        cash=Decimal("100000.00"),
        max_position_pct=5.0,
        max_total_position_pct=95.0,
    )
    _install_manual_preview_ports(monkeypatch, account=account, user_id=user.pk)
    financial_before, report_count_before, proposal_count_before, configuration_before = (
        _capture_write_baseline(account)
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_manual_targets(
        client=client,
        account_id=account.pk,
        target_text=f"{ASSET_BUY},10",
    )

    assert response.status_code == 200
    report = _response_report(response)
    plan = cast(dict[str, Any], report["plan"])
    row = next(item for item in _asset_rows(plan) if item["asset_code"] == ASSET_BUY)
    assert report["strategy_selection_state"] == "confirmed_unconfigured"
    assert row["status"] == "blocked"
    assert "ACCOUNT_MAX_POSITION_LIMIT_EXCEEDED" in row["reason_codes"]
    assert "STRATEGY_MAX_POSITION_LIMIT_EXCEEDED" not in row["reason_codes"]
    assert plan["risk_context"]["strategy_max_position_pct"] is None
    assert Decimal(plan["risk_context"]["account_max_position_pct"]) == Decimal("5")
    assert row["actionable_quantity"] is None
    _assert_read_only_result(
        account=account,
        financial_before=financial_before,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
        configuration_before=configuration_before,
    )


@pytest.mark.parametrize(
    ("missing_evidence", "expected_reason"),
    (
        ("stale-price", "QUOTE_OBSERVATION_STALE"),
        ("classification", "ASSET_TYPE_CLASSIFICATION_UNAVAILABLE"),
        ("quantity", "EXECUTION_QUANTITY_RULE_UNAVAILABLE"),
        ("fee-v2", "FEE_POLICY_UNAVAILABLE"),
    ),
    ids=("stale-price", "missing-classification", "missing-quantity-rule", "missing-fee-v2"),
)
def test_owner_route_manual_buy_with_missing_evidence_never_sizes_actionable_quantity(
    monkeypatch: pytest.MonkeyPatch,
    missing_evidence: str,
    expected_reason: str,
) -> None:
    """A confirmed absent strategy never weakens typed preview evidence gates."""

    user, account = owner_fixtures._create_owner_account(
        username=f"r9-owner-missing-{missing_evidence}",
        positions=(),
        cash=Decimal("100000.00"),
        max_position_pct=20.0,
        max_total_position_pct=95.0,
    )
    _install_manual_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        stale_quote=missing_evidence == "stale-price",
        classification_available=missing_evidence != "classification",
        quantity_rule_available=missing_evidence != "quantity",
        fee_policy_available=missing_evidence != "fee-v2",
    )
    financial_before, report_count_before, proposal_count_before, configuration_before = (
        _capture_write_baseline(account)
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_manual_targets(
        client=client,
        account_id=account.pk,
        target_text=f"{ASSET_BUY},10",
    )

    assert response.status_code == 200
    report = _response_report(response)
    plan = cast(dict[str, Any], report["plan"])
    rows = {row["asset_code"]: row for row in _asset_rows(plan)}
    buy = rows[ASSET_BUY]
    assert report["strategy_selection_state"] == "confirmed_unconfigured"
    assert plan["risk_context"]["strategy_policy_applicability"] == "not_applicable"
    assert buy["target_mode"] == "user_target_difference"
    assert buy["status"] == "blocked"
    assert expected_reason in buy["reason_codes"]
    assert buy["actionable_quantity"] is None
    assert buy["actionable_amount"] is None
    assert Decimal(str(plan["cash_before"])) == Decimal("100000.00")
    assert Decimal(str(plan["available_cash_before"])) == Decimal("100000.00")
    assert plan["projected_cash_after_buys"] is None
    _assert_read_only_result(
        account=account,
        financial_before=financial_before,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
        configuration_before=configuration_before,
    )


def test_owner_route_manual_buy_respects_active_cash_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-only target difference cannot spend cash already held in reserve."""

    user, account = owner_fixtures._create_owner_account(
        username="r9-owner-cash-reservation",
        positions=(),
        cash=Decimal("1000.00"),
        max_position_pct=60.0,
        max_total_position_pct=95.0,
    )
    reservation = owner_fixtures._create_active_order_reservation(
        account=account,
        user_id=user.pk,
        side=owner_fixtures.SimulatedTradeSide.BUY,
        quantity=Decimal("100"),
        price=Decimal("5.00"),
        min_commission=Decimal("1.00"),
        fee_budget=Decimal("10.00"),
    )
    assert reservation.cash_reserved == Decimal("510.00")
    _install_manual_preview_ports(monkeypatch, account=account, user_id=user.pk)
    financial_before, report_count_before, proposal_count_before, configuration_before = (
        _capture_write_baseline(account)
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_manual_targets(
        client=client,
        account_id=account.pk,
        target_text=f"{ASSET_BUY},50",
    )

    assert response.status_code == 200
    report = _response_report(response)
    plan = cast(dict[str, Any], report["plan"])
    buy = next(item for item in _asset_rows(plan) if item["asset_code"] == ASSET_BUY)
    assert report["strategy_selection_state"] == "confirmed_unconfigured"
    assert Decimal(plan["reserved_cash"]) == reservation.cash_reserved
    assert Decimal(plan["available_cash_before"]) == Decimal("490.00")
    assert buy["status"] == "blocked"
    assert "CASH_SHORTFALL" in buy["reason_codes"]
    assert buy["actionable_quantity"] is None
    assert Decimal(buy["suggested_quantity"]) > 0
    _assert_read_only_result(
        account=account,
        financial_before=financial_before,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
        configuration_before=configuration_before,
    )
