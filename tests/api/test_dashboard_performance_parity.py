"""Persisted owner, range and empty-state contracts for the replacement curve."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.simulated_trading.infrastructure.models import DailyNetValueModel, SimulatedAccountModel


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("range_code", "days"), [("1M", 30), ("3M", 90), ("6M", 180), ("1Y", 365), ("ALL", None)]
)
def test_curve_filters_real_history_and_never_reads_other_owner(
    client, auth_user, owned_account, range_code, days
):
    other = get_user_model().objects.create_user(username="curve_other")
    foreign = SimulatedAccountModel.objects.create(
        user=other, account_name="foreign", initial_capital=100, current_cash=100, total_value=100
    )
    today = date.today()
    offsets = [0, 29, 30, 89, 90, 179, 180, 364, 365, 730]
    for offset in offsets:
        for account, value in [(owned_account, Decimal("110000")), (foreign, Decimal("999999"))]:
            DailyNetValueModel.objects.create(
                account=account,
                record_date=today - timedelta(days=offset),
                net_value=value,
                cash=value,
                market_value=0,
            )
    client.force_login(auth_user)
    response = client.get("/api/dashboard/v1/equity-curve/", {"range": range_code})
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    expected_dates = sorted(
        (today - timedelta(days=offset)).isoformat()
        for offset in offsets
        if days is None or offset < days
    )
    assert [row["date"] for row in payload["series"]] == expected_dates
    assert {row["portfolio_value"] for row in payload["series"]} == {110000.0}
    assert payload["value_unit"] == "元"
    assert payload["return_unit"] == "%"


@pytest.mark.django_db
def test_curve_empty_invalid_range_and_anonymous_contracts(client, auth_user):
    assert client.get("/api/dashboard/v1/equity-curve/").status_code in {401, 403}
    client.force_login(auth_user)
    response = client.get("/api/dashboard/v1/equity-curve/")
    assert response.json()["has_history"] is False
    assert response.json()["series"] == []
    assert client.get("/api/dashboard/v1/equity-curve/?range=2Y").status_code == 400
