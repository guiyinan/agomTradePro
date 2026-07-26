from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.backtest.infrastructure.models import BacktestResultModel
from apps.backtest.interface.serializers import (
    DecisionReplayBacktestSerializer,
    RunBacktestSerializer,
)


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
    mock_list.assert_called_once_with(user_id=1, status_filter="completed", limit=10)


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
    mock_detail.assert_called_once_with(17, user_id=1)


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
    assert response.json()["error"] == "limit must be a positive integer"


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
def test_backtest_run_rejects_unknown_fields_before_execution(authenticated_client):
    with patch("apps.backtest.interface.views.run_backtest_payload") as mock_run:
        response = authenticated_client.post(
            "/api/backtest/run/",
            {
                "name": "unknown-field",
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
                "initial_capital": 100000,
                "rebalance_frequency": "monthly",
                "transaction_cost": 0,
            },
            format="json",
        )

    assert response.status_code == 400
    assert "Unknown fields: transaction_cost" in str(response.json()["errors"])
    mock_run.assert_not_called()


@pytest.mark.django_db
def test_backtest_run_rejects_zero_capital_before_execution(authenticated_client):
    with patch("apps.backtest.interface.views.run_backtest_payload") as mock_run:
        response = authenticated_client.post(
            "/api/backtest/run/",
            {
                "name": "zero-capital",
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
                "initial_capital": 0,
            },
            format="json",
        )

    assert response.status_code == 400
    assert "greater than zero" in str(response.json()["errors"])
    mock_run.assert_not_called()


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("initial_capital", float("nan")),
        ("initial_capital", float("inf")),
        ("initial_capital", True),
        ("transaction_cost_bps", float("-inf")),
    ],
)
def test_backtest_run_serializer_rejects_non_finite_financial_values(
    field_name,
    value,
):
    payload = {
        "name": "invalid-financial-value",
        "start_date": "2026-01-01",
        "end_date": "2026-02-01",
        "initial_capital": 100000,
    }
    payload[field_name] = value
    serializer = RunBacktestSerializer(data=payload)

    assert serializer.is_valid() is False
    assert field_name in serializer.errors


def test_decision_replay_serializer_rejects_non_positive_portfolio_id():
    serializer = DecisionReplayBacktestSerializer(
        data={
            "portfolio_id": 0,
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
            "branch_type": "actual",
        }
    )

    assert serializer.is_valid() is False
    assert "portfolio_id" in serializer.errors


@pytest.mark.django_db
def test_backtest_rerun_returns_404_for_missing_backtest(authenticated_client):
    response = authenticated_client.post("/api/backtest/backtests/99999/rerun/", {}, format="json")

    assert response.status_code == 404
    assert response.json()["error"] == "Backtest not found"


@pytest.mark.django_db
def test_backtest_list_and_detail_are_owner_scoped(authenticated_client, auth_user):
    other_user = get_user_model().objects.create_user(
        username="other_backtest_user",
        password="testpass123",
    )
    own = BacktestResultModel.objects.create(
        user=auth_user,
        name="Own backtest",
        status="completed",
        start_date="2026-01-01",
        end_date="2026-01-31",
        initial_capital=100000.0,
        rebalance_frequency="monthly",
    )
    other = BacktestResultModel.objects.create(
        user=other_user,
        name="Other backtest",
        status="completed",
        start_date="2026-01-01",
        end_date="2026-01-31",
        initial_capital=100000.0,
        rebalance_frequency="monthly",
    )

    list_response = authenticated_client.get("/api/backtest/backtests/")
    detail_response = authenticated_client.get(f"/api/backtest/backtests/{other.id}/")
    delete_response = authenticated_client.delete(f"/api/backtest/backtests/{other.id}/")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["backtests"]] == [own.id]
    assert detail_response.status_code == 404
    assert delete_response.status_code == 404
    assert BacktestResultModel.objects.filter(id=other.id).exists()


@pytest.mark.django_db
def test_backtest_create_passes_owner_and_redacts_internal_failure(
    authenticated_client,
    auth_user,
):
    secret = "postgresql://internal-user:secret@database/backtest"
    failed = SimpleNamespace(
        status="failed",
        errors=[secret],
        warnings=[],
        backtest_id=None,
        result=None,
    )
    request_payload = {
        "name": "Owner-scoped run",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "initial_capital": 100000,
        "rebalance_frequency": "monthly",
    }

    with patch(
        "apps.backtest.interface.views.run_backtest_payload",
        return_value=failed,
    ) as mock_run:
        response = authenticated_client.post(
            "/api/backtest/backtests/",
            request_payload,
            format="json",
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": "Backtest failed",
        "error_code": "backtest_execution_failed",
        "warnings": [],
    }
    assert secret not in response.content.decode()
    assert mock_run.call_args.kwargs["user_id"] == auth_user.id


@pytest.mark.django_db
def test_backtest_rerun_does_not_report_false_success(authenticated_client, auth_user):
    backtest = BacktestResultModel.objects.create(
        user=auth_user,
        name="Existing backtest",
        status="completed",
        start_date="2026-01-01",
        end_date="2026-01-31",
        initial_capital=100000.0,
        rebalance_frequency="monthly",
    )

    response = authenticated_client.post(
        f"/api/backtest/backtests/{backtest.id}/rerun/",
        {},
        format="json",
    )

    assert response.status_code == 501
    assert response.json()["error_code"] == "backtest_rerun_not_implemented"
