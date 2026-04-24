from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.share.infrastructure.models import ShareLinkModel, ShareSnapshotModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


def _response_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "results" in payload:
            return payload["results"]
        if "data" in payload and isinstance(payload["data"], list):
            return payload["data"]
        if "items" in payload and isinstance(payload["items"], list):
            return payload["items"]
    return []


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="share_api_user",
        password="testpass123",
        email="share@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_share_links_list_is_owner_scoped(authenticated_client, auth_user):
    other_user = get_user_model().objects.create_user(
        username="share_other_user",
        password="testpass123",
    )
    ShareLinkModel.objects.create(
        owner=auth_user,
        account_id=101,
        short_code="ownerlink01",
        title="Owner Link",
    )
    ShareLinkModel.objects.create(
        owner=other_user,
        account_id=202,
        short_code="otherlink01",
        title="Other Link",
    )

    response = authenticated_client.get("/api/share/links/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    items = _response_items(response.json())
    assert [item["short_code"] for item in items] == ["ownerlink01"]
    assert items[0]["owner_username"] == auth_user.username


@pytest.mark.django_db
def test_share_create_rejects_foreign_account(authenticated_client):
    other_user = get_user_model().objects.create_user(
        username="share_foreign_owner",
        password="testpass123",
    )
    foreign_account = SimulatedAccountModel.objects.create(
        user=other_user,
        account_name="Foreign Account",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
    )

    response = authenticated_client.post(
        "/api/share/links/",
        {
            "account_id": foreign_account.id,
            "title": "Should Fail",
            "theme": "bloomberg",
            "share_level": "snapshot",
        },
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["error"] == "请求参数验证失败"
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["details"]["account_id"] == ["模拟账户不存在或无权分享此账户"]


@pytest.mark.django_db
def test_share_public_snapshot_hides_private_fields(api_client, auth_user):
    share_link = ShareLinkModel.objects.create(
        owner=auth_user,
        account_id=303,
        short_code="publicsnap01",
        title="Public Snapshot",
        show_amounts=False,
        show_positions=False,
        show_transactions=True,
        show_decision_summary=True,
        show_decision_evidence=False,
        show_invalidation_logic=False,
    )
    ShareSnapshotModel.objects.create(
        share_link=share_link,
        snapshot_version=1,
        summary_payload={
            "portfolio_type": "simulated",
            "cash_balance": 1200.0,
            "note": "kept",
        },
        performance_payload={
            "total_return": 8.5,
            "total_profit": 520.0,
        },
        positions_payload={
            "items": [
                {
                    "asset_code": "000001.SZ",
                    "market_value": 1500.0,
                    "weight": 60.0,
                    "current_price": 15.0,
                }
            ],
            "summary": {
                "total_assets": 2500.0,
                "asset_allocation": [{"key": "equity", "value": 1500.0, "count": 1}],
            },
        },
        transactions_payload={
            "items": [
                {
                    "asset_code": "000001.SZ",
                    "direction": "buy",
                    "execution_price": 12.3,
                    "amount": 1230.0,
                }
            ]
        },
        decision_payload={
            "items": [{"asset_code": "000001.SZ", "summary": "继续持有"}],
            "evidence": [{"metric": "PMI", "value": "up"}],
            "invalidation_logic": "PMI 跌破 50",
        },
    )

    response = api_client.get(f"/api/share/public/{share_link.short_code}/snapshot/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["summary"]["note"] == "kept"
    assert "cash_balance" not in payload["summary"]
    assert payload["performance"]["total_return"] == 8.5
    assert "total_profit" not in payload["performance"]
    assert "positions" not in payload
    assert payload["transactions"]["items"][0]["asset_code"] == "000001.SZ"
    assert payload["transactions"]["items"][0]["direction"] == "buy"
    assert "execution_price" not in payload["transactions"]["items"][0]
    assert "amount" not in payload["transactions"]["items"][0]
    assert payload["decisions"]["items"][0]["summary"] == "继续持有"
    assert "evidence" not in payload["decisions"]
    assert "invalidation_logic" not in payload["decisions"]

    share_link.refresh_from_db()
    assert share_link.access_count == 1
