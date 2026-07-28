from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.backtest.infrastructure.models import BacktestResultModel


@pytest.mark.django_db
def test_backtest_list_success_contract(authenticated_client):
    with patch(
        "apps.backtest.interface.views.list_backtests_payload",
        return_value={
            "backtests": [
                {
                    "id": 17,
                    "name": "Recovery allocation",
                    "status": "completed",
                    "start_date": "2026-01-01",
                    "end_date": "2026-06-30",
                    "total_return": 0.12,
                    "created_at": "2026-07-01T08:00:00+00:00",
                }
            ],
            "total_count": 1,
        },
    ) as mock_list:
        response = authenticated_client.get("/api/backtest/backtests/?status=completed&limit=10")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "backtests": [
            {
                "id": 17,
                "name": "Recovery allocation",
                "status": "completed",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "total_return": 0.12,
                "created_at": "2026-07-01T08:00:00+00:00",
            }
        ],
        "total_count": 1,
    }
    mock_list.assert_called_once_with(status_filter="completed", limit=10)


@pytest.mark.django_db
def test_backtest_detail_success_contract(authenticated_client):
    with patch(
        "apps.backtest.interface.views.get_backtest_result_payload",
        return_value={
            "backtest_id": 17,
            "name": "Recovery allocation",
            "status": "completed",
            "result": {
                "total_return": 0.12,
                "annualized_return": 0.08,
                "max_drawdown": -0.05,
                "sharpe_ratio": 1.4,
            },
            "error": None,
        },
    ) as mock_detail:
        response = authenticated_client.get("/api/backtest/backtests/17/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "id": 17,
        "name": "Recovery allocation",
        "status": "completed",
        "result": {
            "total_return": 0.12,
            "annualized_return": 0.08,
            "max_drawdown": -0.05,
            "sharpe_ratio": 1.4,
        },
    }
    mock_detail.assert_called_once_with(17)


@pytest.mark.django_db
def test_backtest_equity_curve_is_staff_only_and_read_only(api_client, auth_user):
    staff = get_user_model().objects.create_user(
        username="backtest_staff",
        password="testpass123",
        is_staff=True,
    )
    backtest = BacktestResultModel.objects.create(
        user=staff,
        name="Persisted curve",
        status="completed",
        start_date="2026-01-01",
        end_date="2026-01-31",
        initial_capital=100000.0,
        rebalance_frequency="monthly",
        equity_curve=[
            {"date": "2026-01-01", "value": 100000.0},
            {"date": "2026-01-31", "value": 105000.0},
        ],
    )
    before_count = BacktestResultModel.objects.count()

    api_client.force_authenticate(user=auth_user)
    forbidden = api_client.get(f"/api/backtest/backtests/{backtest.id}/equity-curve/")

    api_client.force_authenticate(user=staff)
    with CaptureQueriesContext(connection) as queries:
        response = api_client.get(f"/api/backtest/backtests/{backtest.id}/equity-curve/")

    assert forbidden.status_code == 403
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "backtest_id": backtest.id,
        "status": "completed",
        "curve": [
            {"date": "2026-01-01", "value": 100000.0},
            {"date": "2026-01-31", "value": 105000.0},
        ],
        "point_count": 2,
    }
    assert BacktestResultModel.objects.count() == before_count
    assert all(
        not query["sql"]
        .lstrip()
        .upper()
        .startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "ALTER", "CREATE", "DROP"))
        for query in queries.captured_queries
    )


@pytest.mark.django_db
def test_backtest_list_rejects_non_integer_limit(authenticated_client):
    response = authenticated_client.get("/api/backtest/backtests/?limit=bad")

    assert response.status_code == 400
    assert response.json()["error"] == "limit must be an integer"


@pytest.mark.django_db
def test_backtest_run_rejects_invalid_date_order(authenticated_client):
    response = authenticated_client.post(
        "/api/backtest/run/",
        {
            "name": "invalid-range",
            "start_date": "2026-04-03",
            "end_date": "2026-04-03",
            "initial_capital": 100000,
            "rebalance_frequency": "monthly",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "start_date must be before end_date" in str(response.json()["errors"])


@pytest.mark.django_db
def test_backtest_viewset_create_does_not_forward_interface_run_async(
    authenticated_client,
):
    """The synchronous Application request must not receive the Interface-only flag."""

    with patch(
        "apps.backtest.interface.views.run_backtest_payload",
        return_value=SimpleNamespace(
            backtest_id=23,
            status="completed",
            result={"total_return": 0.05},
            errors=[],
            warnings=[],
        ),
    ) as run_backtest:
        response = authenticated_client.post(
            "/api/backtest/backtests/",
            {
                "name": "viewset-sync-contract",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "initial_capital": 100000,
                "rebalance_frequency": "monthly",
                "run_async": False,
            },
            format="json",
        )

    assert response.status_code == 201
    assert response.json()["backtest_id"] == 23
    forwarded = run_backtest.call_args.args[0]
    assert "run_async" not in forwarded


@pytest.mark.django_db
def test_backtest_rerun_returns_404_for_missing_backtest(authenticated_client):
    response = authenticated_client.post("/api/backtest/backtests/99999/rerun/", {}, format="json")

    assert response.status_code == 404
    assert response.json()["error"] == "Backtest not found"


@pytest.mark.django_db
def test_backtest_api_and_classic_pages_require_authentication(client):
    assert client.get("/api/backtest/backtests/").status_code in {401, 403}
    assert client.get("/api/backtest/statistics/").status_code == 302
    assert client.get("/backtest/").status_code == 302
    assert client.get("/backtest/create/").status_code == 302
    assert client.get("/backtest/17/").status_code == 302


@pytest.mark.django_db
def test_backtest_classic_pages_publish_exact_tui_task_links(client, test_user):
    client.force_login(test_user)
    with (
        patch(
            "apps.backtest.interface.views.load_backtest_list_context",
            return_value={"backtests": [], "stats": {}},
        ),
        patch(
            "apps.backtest.interface.views.load_backtest_create_context",
            return_value={"frequencies": [], "earliest_date": "", "latest_date": ""},
        ),
        patch(
            "apps.backtest.interface.views.load_backtest_detail_context",
            return_value={
                "backtest": SimpleNamespace(id=17, name="Migration check", status="pending"),
                "is_completed": False,
            },
        ),
    ):
        list_response = client.get("/backtest/")
        create_response = client.get("/backtest/create/")
        detail_response = client.get("/backtest/17/")

    assert list_response.status_code == 200
    assert create_response.status_code == 200
    assert detail_response.status_code == 200
    assert (
        "/tui/?screen=research.asset-lab&amp;action=backtest.list" in list_response.content.decode()
    )
    assert (
        "/tui/?screen=research.asset-lab&amp;action=backtest.run"
        in create_response.content.decode()
    )
    assert (
        "/tui/?screen=research.asset-lab&amp;action=backtest.detail&amp;pk=17"
        in detail_response.content.decode()
    )
