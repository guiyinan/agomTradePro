from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.audit.infrastructure.models import AttributionReport, ExperienceSummary, LossAnalysis
from apps.backtest.infrastructure.models import BacktestResultModel


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(
        username="audit-report-staff",
        password="testpass123",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def regular_client(db):
    user = User.objects.create_user(
        username="audit-report-regular",
        password="testpass123",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _create_backtest(*, status: str = "completed") -> BacktestResultModel:
    return BacktestResultModel._default_manager.create(
        name="Governed report backtest",
        status=status,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        initial_capital=100000,
        final_capital=110000,
        total_return=0.1,
        annualized_return=0.1,
        max_drawdown=-0.05,
        sharpe_ratio=1.0,
        equity_curve=[],
        regime_history=[],
        trades=[],
    )


@pytest.mark.django_db
def test_attribution_report_preview_is_staff_only_and_read_only(staff_client, regular_client):
    backtest = _create_backtest()
    before = (
        AttributionReport._default_manager.count(),
        LossAnalysis._default_manager.count(),
        ExperienceSummary._default_manager.count(),
    )
    payload = {"backtest_id": backtest.id}

    denied = regular_client.post("/api/audit/reports/generate/preview/", payload, format="json")
    response = staff_client.post("/api/audit/reports/generate/preview/", payload, format="json")

    assert denied.status_code == 403
    assert response.status_code == 200
    assert response.json()["preview"] == {
        "backtest": {
            "id": backtest.id,
            "name": "Governed report backtest",
            "status": "completed",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        },
        "existing_report_count": 0,
        "external_reads": ["historical_asset_prices"],
        "writes": [
            "audit_attribution_report",
            "audit_loss_analysis_if_applicable",
            "audit_experience_summary",
        ],
        "duplicate_reports_allowed": True,
        "partial_write_possible": True,
    }
    assert (
        AttributionReport._default_manager.count(),
        LossAnalysis._default_manager.count(),
        ExperienceSummary._default_manager.count(),
    ) == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"backtest_id": 0},
        {"backtest_id": 1, "unknown": True},
    ],
)
def test_attribution_report_generation_rejects_invalid_contract(staff_client, payload):
    with patch(
        "apps.audit.interface.attribution_report_api_views.generate_attribution_report_payload"
    ) as generate:
        response = staff_client.post("/api/audit/reports/generate/", payload, format="json")

    assert response.status_code == 400
    generate.assert_not_called()


@pytest.mark.django_db
def test_attribution_report_generation_rejects_missing_and_incomplete_backtests(staff_client):
    incomplete = _create_backtest(status="running")

    missing = staff_client.post(
        "/api/audit/reports/generate/preview/", {"backtest_id": 999999}, format="json"
    )
    not_completed = staff_client.post(
        "/api/audit/reports/generate/",
        {"backtest_id": incomplete.id},
        format="json",
    )

    assert missing.status_code == 404
    assert not_completed.status_code == 400


@pytest.mark.django_db
def test_attribution_report_commit_uses_exact_backtest_id(staff_client):
    backtest = _create_backtest()
    report = {
        "id": 42,
        "backtest_id": backtest.id,
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "regime_timing_pnl": 0.01,
        "asset_selection_pnl": 0.02,
        "interaction_pnl": 0.0,
        "total_pnl": 0.03,
        "regime_accuracy": 0.8,
        "regime_predicted": "Recovery",
        "regime_actual": "Recovery",
        "created_at": "2026-07-12T00:00:00Z",
        "loss_analyses": [],
        "experience_summaries": [],
    }
    with patch(
        "apps.audit.interface.attribution_report_api_views.generate_attribution_report_payload",
        return_value={"success": True, "error": None, "report": report},
    ) as generate:
        response = staff_client.post(
            "/api/audit/reports/generate/",
            {"backtest_id": backtest.id},
            format="json",
        )

    assert response.status_code == 201
    assert response.json()["id"] == 42
    generate.assert_called_once_with(backtest.id)
