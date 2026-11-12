"""HTTP contracts for the read-only two-portfolio comparison endpoint."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.account.infrastructure.models import PortfolioObserverGrantModel
from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
)
from apps.simulated_trading.infrastructure.models import (
    DailyNetValueModel,
    PositionModel,
    SimulatedAccountModel,
    UnifiedAccountCashFlowModel,
)

pytestmark = pytest.mark.django_db
URL = "/api/simulated-trading/portfolio-comparison/"


def _account(user, name: str) -> SimulatedAccountModel:
    return SimulatedAccountModel.objects.create(
        user=user,
        account_name=name,
        account_type="simulated",
        initial_capital=Decimal("100000"),
        current_cash=Decimal("50000"),
        current_market_value=Decimal("50000"),
        total_value=Decimal("100000"),
    )


def _history(account: SimulatedAccountModel, daily_gain: Decimal) -> None:
    UnifiedAccountCashFlowModel.objects.create(
        account=account,
        flow_type="initial_capital",
        amount=Decimal("100000"),
        flow_date=date(2024, 1, 1),
        source_app="simulated_trading",
    )
    for index in range(3):
        total = Decimal("100000") + daily_gain * index
        DailyNetValueModel.objects.create(
            account=account,
            record_date=date(2024, 1, 1) + timedelta(days=index),
            correction_event_watermark=0,
            correction_event_watermark_sha256=fee_correction_account_genesis_sha256(account.pk),
            net_value=total,
            cash=Decimal("50000"),
            market_value=total - Decimal("50000"),
        )


def _position(account: SimulatedAccountModel, code: str, value: str) -> None:
    PositionModel.objects.create(
        account=account,
        asset_code=code,
        asset_name=code,
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        avg_cost=Decimal("10"),
        total_cost=Decimal("1000"),
        current_price=Decimal("10"),
        market_value=Decimal(value),
        first_buy_date=date(2024, 1, 1),
    )


@pytest.fixture
def comparison_data(db):
    user = get_user_model().objects.create_user(username="comparison-owner", password="pass123")
    other = get_user_model().objects.create_user(username="comparison-other", password="pass123")
    observer = get_user_model().objects.create_user(
        username="comparison-observer", password="pass123"
    )
    left = _account(user, "稳健组合")
    right = _account(user, "进取组合")
    foreign = _account(other, "他人组合")
    _history(left, Decimal("1000"))
    _history(right, Decimal("500"))
    _position(left, "000001.SZ", "60000")
    _position(left, "000002.SZ", "40000")
    _position(right, "000001.SZ", "50000")
    _position(right, "600000.SH", "50000")
    return user, other, observer, left, right, foreign


def _params(left: int, right: int) -> dict[str, str | int]:
    return {
        "left_account_id": left,
        "right_account_id": right,
        "start_date": "2024-01-01",
        "end_date": "2024-01-03",
    }


def test_owner_receives_metrics_curves_and_current_holding_differences(comparison_data) -> None:
    user, _, _, left, right, _ = comparison_data
    client = APIClient()
    client.force_authenticate(user)
    history_count = DailyNetValueModel.objects.count()

    response = client.get(URL, _params(left.pk, right.pk))

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["left_account"]["account_name"] == "稳健组合"
    assert payload["right_account"]["account_name"] == "进取组合"
    assert payload["relative_twr_percentage_points"] > 0
    assert {row["key"] for row in payload["metrics"]} >= {"twr", "max_drawdown", "sharpe"}
    assert payload["curve"][-1]["left"] > payload["curve"][-1]["right"]
    assert payload["holdings"]["shared_count"] == 1
    assert payload["holdings"]["left_only_count"] == 1
    assert payload["holdings"]["right_only_count"] == 1
    assert len(payload["holdings"]["rows"]) == 3
    assert payload["holdings"]["overlap_rows"] == [
        {"overlap_label": "共同持仓权重重合度", "overlap_percentage": 50.0}
    ]
    assert payload["holdings"]["industry_rows"][0]["industry"] == "行业未知"
    assert DailyNetValueModel.objects.count() == history_count


def test_observer_can_compare_but_cross_account_access_is_denied(comparison_data) -> None:
    user, _, observer, left, right, foreign = comparison_data
    PortfolioObserverGrantModel.objects.create(owner_user_id=user, observer_user_id=observer)
    client = APIClient()
    client.force_authenticate(observer)

    allowed = client.get(URL, _params(left.pk, right.pk))
    denied = client.get(URL, _params(left.pk, foreign.pk))

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied.headers["Content-Type"].startswith("application/json")


@pytest.mark.parametrize(
    ("left_key", "right_key", "start", "end"),
    [
        ("left", "left", "2024-01-01", "2024-01-03"),
        ("left", "right", "2024-01-03", "2024-01-01"),
        ("left", "right", "2024-01-01", "2024-01-01"),
    ],
)
def test_invalid_selection_or_period_returns_400(
    comparison_data, left_key: str, right_key: str, start: str, end: str
) -> None:
    user, _, _, left, right, _ = comparison_data
    client = APIClient()
    client.force_authenticate(user)
    accounts = {"left": left.pk, "right": right.pk}
    params = _params(accounts[left_key], accounts[right_key])
    params["start_date"] = start
    params["end_date"] = end

    response = client.get(URL, params)

    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/json")
