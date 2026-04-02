from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="equity_user",
        password="testpass123",
        email="equity@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_equity_pool_returns_empty_payload_when_no_pool(authenticated_client):
    regime = SimpleNamespace(dominant_regime="Recovery")

    with patch(
        "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
        return_value=[],
    ), patch(
        "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
        return_value=None,
    ), patch(
        "apps.regime.application.current_regime.resolve_current_regime",
        return_value=regime,
    ):
        response = authenticated_client.get("/api/equity/pool/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["regime"] == "Recovery"
    assert payload["count"] == 0
    assert payload["stocks"] == []


@pytest.mark.django_db
def test_equity_refresh_pool_returns_503_when_regime_missing(authenticated_client):
    with patch("apps.regime.application.current_regime.resolve_current_regime", return_value=None):
        response = authenticated_client.post("/api/equity/pool/refresh/", {}, format="json")

    assert response.status_code == 503
    assert response.json()["message"] == "无法获取当前 Regime，请先运行 Regime 判定"


@pytest.mark.django_db
def test_equity_multidim_screen_returns_500_on_exception(authenticated_client):
    with patch(
        "apps.equity.application.services.EquityMultiDimScorer.screen_stocks",
        side_effect=RuntimeError("boom"),
    ):
        response = authenticated_client.post(
            "/api/equity/multidim-screen/",
            {
                "filters": {"sector": "银行"},
                "context": {"regime": "Recovery", "policy_level": "P0", "sentiment_index": 0.1},
                "max_count": 10,
            },
            format="json",
        )

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert "筛选失败" in payload["message"]


@pytest.mark.django_db
def test_equity_sync_financial_data_returns_task_payload(authenticated_client):
    task_payload = {"success": True, "queued": True, "task_id": "sync-123"}

    with patch(
        "apps.equity.application.tasks_valuation_sync.sync_financial_data_task",
        return_value=task_payload,
    ) as mock_task:
        response = authenticated_client.post(
            "/api/equity/financial-data/sync/",
            {"stock_codes": ["600519.SH"], "periods": 4, "source": "akshare"},
            format="json",
        )

    assert response.status_code == 200
    assert response.json() == task_payload
    mock_task.assert_called_once_with(
        source="akshare",
        periods=4,
        stock_codes=["600519.SH"],
    )
