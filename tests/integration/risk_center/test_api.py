from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.risk_center.infrastructure.models import (
    AccountRiskPolicyModel,
    GlobalRiskFloorModel,
    RiskDailyReportModel,
    RiskPolicyAuditModel,
    RiskTemplateModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


def _user(username: str, *, is_staff: bool = False):
    return get_user_model().objects.create_user(
        username=username,
        password="pass123456",
        is_staff=is_staff,
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _account(user, name: str = "acct"):
    return SimulatedAccountModel._default_manager.create(
        user=user,
        account_name=name,
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )


@pytest.mark.django_db
def test_risk_center_api_returns_json_contract_for_core_endpoints():
    staff = _user("risk_api_staff", is_staff=True)
    account = _account(staff)
    client = _client(staff)

    for path in (
        "/api/risk-center/",
        "/api/risk-center/floor/",
        "/api/risk-center/templates/",
        "/api/risk-center/account-policies/",
        "/api/risk-center/exceptions/",
        f"/api/risk-center/effective-policy/?account_id={account.id}",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_risk_center_default_reads_do_not_persist_fallback_configuration():
    staff = _user("risk_read_only_staff", is_staff=True)
    account = _account(staff)
    client = _client(staff)
    before = {
        "floors": GlobalRiskFloorModel._default_manager.count(),
        "templates": RiskTemplateModel._default_manager.count(),
    }

    floor_response = client.get("/api/risk-center/floor/")
    templates_response = client.get("/api/risk-center/templates/")
    effective_response = client.get(
        f"/api/risk-center/effective-policy/?account_id={account.id}"
    )

    assert floor_response.status_code == 200
    assert templates_response.status_code == 200
    assert len(templates_response.data["data"]) >= 3
    assert effective_response.status_code == 200
    after = {
        "floors": GlobalRiskFloorModel._default_manager.count(),
        "templates": RiskTemplateModel._default_manager.count(),
    }
    assert after == before


@pytest.mark.django_db
def test_non_staff_cannot_update_floor_template_or_exception():
    user = _user("risk_regular")
    account = _account(user)
    client = _client(user)

    floor_response = client.put(
        "/api/risk-center/floor/",
        {"max_total_position_pct": 0.7},
        format="json",
    )
    template_response = client.post(
        "/api/risk-center/templates/",
        {
            "key": "blocked",
            "name": "Blocked",
            "risk_profile": "custom",
            "max_total_position_pct": 0.5,
        },
        format="json",
    )
    exception_response = client.post(
        "/api/risk-center/exceptions/",
        {
            "account_id": account.id,
            "field_name": "max_total_position_pct",
            "allowed_value": 0.9,
            "reason": "not staff",
            "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
        },
        format="json",
    )

    assert floor_response.status_code == 403
    assert template_response.status_code == 403
    assert exception_response.status_code == 403


@pytest.mark.django_db
def test_risk_floor_returns_active_floor_snapshot():
    staff = _user("risk_floor_staff", is_staff=True)
    client = _client(staff)

    update_response = client.put(
        "/api/risk-center/floor/",
        {
            "max_total_position_pct": 0.75,
            "max_single_position_pct": 0.2,
            "min_cash_pct": 0.1,
            "force_stop_loss": True,
            "reason": "tighten the integration-test floor",
        },
        format="json",
    )

    assert update_response.status_code == 200

    response = client.get("/api/risk-center/floor/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    data = response.data["data"]
    assert data["max_total_position_pct"] == 0.75
    assert data["max_single_position_pct"] == 0.2
    assert data["min_cash_pct"] == 0.1
    assert data["force_stop_loss"] is True
    assert data["is_active"] is True
    audit = RiskPolicyAuditModel._default_manager.get(
        target_type=RiskPolicyAuditModel.TARGET_FLOOR,
        target_id=str(data["id"]),
        action="update",
    )
    assert audit.reason == "tighten the integration-test floor"


@pytest.mark.django_db
def test_risk_template_list_returns_created_templates_with_status():
    staff = _user("risk_template_staff", is_staff=True)
    client = _client(staff)

    create_response = client.post(
        "/api/risk-center/templates/",
        {
            "key": "moderate",
            "name": "Moderate",
            "risk_profile": "moderate",
            "max_total_position_pct": 0.7,
            "max_single_position_pct": 0.2,
            "min_cash_pct": 0.1,
        },
        format="json",
    )
    assert create_response.status_code == 201

    inactive_response = client.post(
        "/api/risk-center/templates/",
        {
            "key": "legacy-off",
            "name": "Legacy Off",
            "risk_profile": "custom",
            "max_total_position_pct": 0.5,
            "is_active": False,
        },
        format="json",
    )
    assert inactive_response.status_code == 201

    response = client.get("/api/risk-center/templates/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    data = response.data["data"]
    by_key = {item["key"]: item for item in data}
    assert "moderate" in by_key
    assert "legacy-off" in by_key
    assert by_key["moderate"]["name"] == "Moderate"
    assert by_key["moderate"]["risk_profile"] == "moderate"
    assert by_key["moderate"]["max_total_position_pct"] == 0.7
    assert by_key["moderate"]["max_single_position_pct"] == 0.2
    assert by_key["moderate"]["min_cash_pct"] == 0.1
    assert by_key["moderate"]["is_active"] is True
    assert by_key["legacy-off"]["name"] == "Legacy Off"
    assert by_key["legacy-off"]["risk_profile"] == "custom"
    assert by_key["legacy-off"]["max_total_position_pct"] == 0.5
    assert by_key["legacy-off"]["is_active"] is False


@pytest.mark.django_db
def test_account_owner_can_upsert_and_read_own_policy():
    user = _user("risk_owner")
    account = _account(user)
    client = _client(user)

    response = client.post(
        "/api/risk-center/account-policies/",
        {
            "account_id": account.id,
            "risk_profile": "moderate",
            "max_total_position_pct": 0.72,
            "reason": "create owner policy",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["data"]["account_id"] == account.id
    update_response = client.post(
        "/api/risk-center/account-policies/",
        {
            "account_id": account.id,
            "risk_profile": "moderate",
            "max_total_position_pct": 0.68,
            "reason": "tighten owner policy",
        },
        format="json",
    )
    assert update_response.status_code == 201
    assert AccountRiskPolicyModel._default_manager.filter(account_id=account.id).count() == 1
    read_response = client.get(f"/api/risk-center/account-policies/by-account/{account.id}/")
    assert read_response.status_code == 200
    assert read_response.data["data"]["max_total_position_pct"] == 0.68
    audit_actions = list(
        RiskPolicyAuditModel._default_manager.filter(
            target_type=RiskPolicyAuditModel.TARGET_POLICY,
            target_id=str(read_response.data["data"]["id"]),
        )
        .order_by("created_at")
        .values_list("action", "reason")
    )
    assert audit_actions == [
        ("create", "create owner policy"),
        ("update", "tighten owner policy"),
    ]
    invalid_template_response = client.post(
        "/api/risk-center/account-policies/",
        {
            "account_id": account.id,
            "template_id": 999999,
            "reason": "invalid template must fail",
        },
        format="json",
    )
    assert invalid_template_response.status_code == 400
    stored_policy = AccountRiskPolicyModel._default_manager.get(account_id=account.id)
    assert stored_policy.template_id is None
    assert stored_policy.max_total_position_pct == 0.68
    assert (
        RiskPolicyAuditModel._default_manager.filter(
            target_type=RiskPolicyAuditModel.TARGET_POLICY,
            target_id=str(stored_policy.id),
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_risk_exception_list_returns_created_exceptions_for_account_filter():
    staff = _user("risk_exception_staff", is_staff=True)
    account = _account(staff)
    other_account = _account(_user("risk_exception_other"))
    client = _client(staff)

    response_a = client.post(
        "/api/risk-center/exceptions/",
        {
            "account_id": account.id,
            "field_name": "max_total_position_pct",
            "allowed_value": 0.85,
            "reason": "temporary rebalance",
            "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
        },
        format="json",
    )
    response_b = client.post(
        "/api/risk-center/exceptions/",
        {
            "account_id": other_account.id,
            "field_name": "min_cash_pct",
            "allowed_value": 0.08,
            "reason": "cash bridge",
            "expires_at": (timezone.now() + timedelta(hours=2)).isoformat(),
        },
        format="json",
    )

    assert response_a.status_code == 201
    assert response_b.status_code == 201

    response = client.get(f"/api/risk-center/exceptions/?account_id={account.id}")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    data = response.data["data"]
    assert len(data) == 1
    item = data[0]
    assert item["account_id"] == account.id
    assert item["field_name"] == "max_total_position_pct"
    assert item["allowed_value"] == 0.85
    assert item["reason"] == "temporary rebalance"
    assert item["is_active"] is True
    assert item["created_by_username"] == staff.username


@pytest.mark.django_db
def test_user_cannot_read_or_set_another_users_policy():
    owner = _user("risk_owner_a")
    other = _user("risk_owner_b")
    account = _account(owner)
    client = _client(other)

    response = client.post(
        "/api/risk-center/account-policies/",
        {"account_id": account.id, "max_total_position_pct": 0.7},
        format="json",
    )
    read_response = client.get(f"/api/risk-center/effective-policy/?account_id={account.id}")

    assert response.status_code == 403
    assert read_response.status_code == 403


@pytest.mark.django_db
def test_pre_trade_check_returns_human_actionable_risk_result():
    staff = _user("risk_pretrade_staff", is_staff=True)
    account = _account(staff)
    client = _client(staff)
    client.put(
        "/api/risk-center/floor/",
        {"max_total_position_pct": 0.75, "max_single_position_pct": 0.2, "min_cash_pct": 0.1},
        format="json",
    )

    response = client.post(
        "/api/risk-center/pre-trade-check/",
        {
            "account_id": account.id,
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 1000,
            "price": 10,
            "account_equity": 100000,
            "total_position_value": 70000,
            "cash_balance": 30000,
        },
        format="json",
    )

    assert response.status_code == 200
    data = response.data["data"]
    assert data["passed"] is False
    assert any("max_total_position_pct" in item for item in data["violations"])
    assert data["metrics"]["order_value"] == 10000
    assert data["effective_policy"]["account_id"] == account.id


@pytest.mark.django_db
def test_pre_trade_check_respects_account_permissions():
    owner = _user("risk_pretrade_owner")
    other = _user("risk_pretrade_other")
    account = _account(owner)
    client = _client(other)

    response = client.post(
        "/api/risk-center/pre-trade-check/",
        {
            "account_id": account.id,
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 100,
            "price": 10,
            "account_equity": 100000,
            "total_position_value": 0,
            "cash_balance": 100000,
        },
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_post_investment_check_returns_portfolio_tracking_result():
    staff = _user("risk_post_investment_staff", is_staff=True)
    account = _account(staff)
    client = _client(staff)
    client.put(
        "/api/risk-center/floor/",
        {
            "max_total_position_pct": 0.75,
            "max_single_position_pct": 0.2,
            "max_daily_loss_pct": 0.03,
            "max_drawdown_pct": 0.1,
            "max_stop_loss_pct": 0.08,
            "take_profit_pct": 0.2,
            "min_cash_pct": 0.1,
            "force_stop_loss": True,
            "hard_exclusions": ["000999.SZ"],
        },
        format="json",
    )

    response = client.post(
        "/api/risk-center/post-investment-check/",
        {
            "account_id": account.id,
            "account_equity": 100000,
            "cash_balance": 5000,
            "total_position_value": 95000,
            "daily_pnl_pct": -0.04,
            "drawdown_pct": 0.12,
            "positions": [
                {"symbol": "000001.SZ", "market_value": 30000, "unrealized_pnl_pct": -0.09},
                {"symbol": "000999.SZ", "market_value": 10000, "unrealized_pnl_pct": 0.25},
            ],
        },
        format="json",
    )

    assert response.status_code == 200
    data = response.data["data"]
    assert data["status"] == "breach"
    assert data["passed"] is False
    assert data["metrics"]["total_position_pct"] == 0.95
    assert any("max_total_position_pct" in item for item in data["violations"])
    assert any("max_daily_loss_pct" in item for item in data["violations"])
    assert any(alert["type"] == "stop_loss" for alert in data["position_alerts"])
    assert any(alert["type"] == "hard_exclusion" for alert in data["position_alerts"])
    assert any(alert["type"] == "take_profit" for alert in data["position_alerts"])


@pytest.mark.django_db
def test_post_investment_check_respects_account_permissions():
    owner = _user("risk_post_owner")
    other = _user("risk_post_other")
    account = _account(owner)
    client = _client(other)

    response = client.post(
        "/api/risk-center/post-investment-check/",
        {
            "account_id": account.id,
            "account_equity": 100000,
            "positions": [],
        },
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_daily_report_returns_risk_and_position_sections():
    staff = _user("risk_daily_report_staff", is_staff=True)
    account = _account(staff)
    client = _client(staff)

    response = client.post(
        "/api/risk-center/daily-report/",
        {
            "account_id": account.id,
            "report_date": "2026-06-28",
            "account_equity": 100000,
            "cash_balance": 5000,
            "total_position_value": 95000,
            "daily_pnl_pct": -0.04,
            "positions": [
                {"symbol": "000001.SZ", "market_value": 30000, "unrealized_pnl_pct": -0.09},
                {"symbol": "000002.SZ", "market_value": 15000, "unrealized_pnl_pct": 0.22},
            ],
        },
        format="json",
    )

    assert response.status_code == 200
    data = response.data["data"]
    assert data["report_date"] == "2026-06-28"
    assert data["risk_daily_report"]["status"] == "breach"
    assert data["risk_daily_report"]["breach_count"] >= 1
    assert data["position_daily_report"]["position_count"] == 2
    assert data["position_daily_report"]["top_positions"][0]["symbol"] == "000001.SZ"
    assert data["post_investment_check"]["effective_policy"]["account_id"] == account.id
    stored = RiskDailyReportModel._default_manager.get(id=data["report_id"])
    assert stored.generated_by_id == staff.id
    assert stored.account_id == account.id
    assert stored.report_date.isoformat() == "2026-06-28"

    default_date_response = client.post(
        "/api/risk-center/daily-report/",
        {
            "account_id": account.id,
            "account_equity": 100000,
            "positions": [],
        },
        format="json",
    )

    assert default_date_response.status_code == 200
    assert default_date_response.data["data"]["report_date"] == timezone.localdate().isoformat()


@pytest.mark.django_db
def test_daily_report_can_query_archived_history_by_day_and_range():
    staff = _user("risk_daily_history_staff", is_staff=True)
    account = _account(staff)
    client = _client(staff)

    first_response = client.post(
        "/api/risk-center/daily-report/",
        {
            "account_id": account.id,
            "report_date": "2026-06-27",
            "account_equity": 100000,
            "cash_balance": 20000,
            "positions": [
                {"symbol": "000001.SZ", "market_value": 30000, "unrealized_pnl_pct": 0.02},
            ],
        },
        format="json",
    )
    second_response = client.post(
        "/api/risk-center/daily-report/",
        {
            "account_id": account.id,
            "report_date": "2026-06-28",
            "account_equity": 100000,
            "cash_balance": 5000,
            "total_position_value": 95000,
            "positions": [
                {"symbol": "000002.SZ", "market_value": 95000, "unrealized_pnl_pct": -0.01},
            ],
        },
        format="json",
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert RiskDailyReportModel._default_manager.filter(account_id=account.id).count() == 2

    exact_response = client.get(
        f"/api/risk-center/daily-report/?account_id={account.id}&report_date=2026-06-28"
    )
    assert exact_response.status_code == 200
    exact_data = exact_response.data["data"]
    assert exact_data["report_date"] == "2026-06-28"
    assert exact_data["position_daily_report"]["top_positions"][0]["symbol"] == "000002.SZ"

    range_response = client.get(
        f"/api/risk-center/daily-report/?account_id={account.id}"
        "&start_date=2026-06-27&end_date=2026-06-28&limit=10"
    )
    assert range_response.status_code == 200
    range_data = range_response.data["data"]
    assert [item["report_date"] for item in range_data] == ["2026-06-28", "2026-06-27"]

    overwrite_response = client.post(
        "/api/risk-center/daily-report/",
        {
            "account_id": account.id,
            "report_date": "2026-06-28",
            "account_equity": 100000,
            "cash_balance": 90000,
            "positions": [],
        },
        format="json",
    )

    assert overwrite_response.status_code == 200
    assert RiskDailyReportModel._default_manager.filter(account_id=account.id).count() == 2
    assert overwrite_response.data["data"]["position_daily_report"]["position_count"] == 0


@pytest.mark.django_db
def test_daily_report_respects_account_permissions():
    owner = _user("risk_daily_owner")
    other = _user("risk_daily_other")
    account = _account(owner)
    client = _client(other)

    response = client.post(
        "/api/risk-center/daily-report/",
        {
            "account_id": account.id,
            "account_equity": 100000,
            "positions": [],
        },
        format="json",
    )

    assert response.status_code == 403

    RiskDailyReportModel._default_manager.create(
        account_id=account.id,
        report_date="2026-06-28",
        status="ok",
        risk_daily_report={"status": "ok"},
        position_daily_report={},
        post_investment_check={},
    )
    history_response = client.get(
        f"/api/risk-center/daily-report/?account_id={account.id}&report_date=2026-06-28"
    )
    assert history_response.status_code == 403


@pytest.mark.django_db
def test_effective_policy_returns_sources_floor_and_exception_notes():
    staff = _user("risk_effective_staff", is_staff=True)
    account = _account(staff)
    client = _client(staff)
    client.put(
        "/api/risk-center/floor/",
        {"max_total_position_pct": 0.75, "min_cash_pct": 0.1},
        format="json",
    )
    AccountRiskPolicyModel._default_manager.create(
        account_id=account.id,
        max_total_position_pct=0.9,
        min_cash_pct=0.02,
    )
    client.post(
        "/api/risk-center/exceptions/",
        {
            "account_id": account.id,
            "field_name": "max_total_position_pct",
            "allowed_value": 0.85,
            "reason": "temporary rebalance",
            "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
        },
        format="json",
    )

    response = client.get(f"/api/risk-center/effective-policy/?account_id={account.id}")

    assert response.status_code == 200
    data = response.data["data"]
    assert data["parameters"]["max_total_position_pct"] == 0.85
    assert data["parameters"]["min_cash_pct"] == 0.1
    assert data["sources"]["max_total_position_pct"] == "exception"
    assert data["floor_applied"][0]["field"] == "min_cash_pct"
    assert data["exceptions_applied"][0]["reason"] == "temporary rebalance"
