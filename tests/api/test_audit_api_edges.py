from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="audit_api_user",
        password="testpass123",
        email="audit@example.com",
        is_staff=True,
    )


@pytest.mark.django_db
def test_audit_run_validation_invalid_date_returns_400(authenticated_client):
    response = authenticated_client.post(
        "/api/audit/run-validation/",
        {"start_date": "2026/04/02", "end_date": "2026-04-03"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert "start_date" in payload["details"]


@pytest.mark.django_db
def test_audit_validate_all_requires_date_range(authenticated_client):
    response = authenticated_client.post(
        "/api/audit/validate-all-indicators/",
        {},
        format="json",
    )

    assert response.status_code == 400
    assert set(response.json()["details"]) == {"start_date", "end_date"}


@pytest.mark.django_db
def test_audit_summary_rejects_invalid_backtest_id(authenticated_client):
    response = authenticated_client.get("/api/audit/summary/?backtest_id=bad-id")

    assert response.status_code == 400
    assert response.json()["error"] == "backtest_id 必须是整数"


@pytest.mark.django_db
def test_audit_tui_reports_are_filtered_and_mark_generation_candidates(
    authenticated_client,
    monkeypatch,
):
    report = SimpleNamespace(
        id=7,
        backtest_id=11,
        attribution_method="heuristic",
        period_start="2026-01-01",
        period_end="2026-06-30",
        regime_timing_pnl=0.1,
        asset_selection_pnl=0.2,
        interaction_pnl=0.03,
        total_pnl=0.33,
        regime_accuracy=0.8,
        regime_predicted="recovery",
        regime_actual="recovery",
        created_at="2026-07-26T08:00:00+00:00",
    )
    generated = SimpleNamespace(
        id=11,
        name="已生成回测",
        status="completed",
        start_date="2026-01-01",
        end_date="2026-06-30",
    )
    candidate = SimpleNamespace(
        id=12,
        name="待归因回测",
        status="completed",
        start_date="2026-01-01",
        end_date="2026-06-30",
    )
    observed_methods = []

    def fake_context(method):
        observed_methods.append(method)
        return {
            "reports": [report],
            "total_count": 1,
            "backtests": [generated, candidate],
            "existing_backtest_ids": {11},
        }

    monkeypatch.setattr(
        "apps.audit.interface.tui_views.build_report_list_context",
        fake_context,
    )

    response = authenticated_client.get("/api/audit/tui/reports/?method=heuristic")

    assert response.status_code == 200
    payload = response.json()
    assert observed_methods == ["heuristic"]
    assert payload["reports"][0]["attribution_method"] == "heuristic"
    assert payload["generation_candidates"] == [
        {
            "id": 11,
            "name": "已生成回测",
            "status": "completed",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "already_generated": True,
        },
        {
            "id": 12,
            "name": "待归因回测",
            "status": "completed",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "already_generated": False,
        },
    ]


@pytest.mark.django_db
def test_audit_tui_reports_reject_unknown_method(authenticated_client):
    response = authenticated_client.get("/api/audit/tui/reports/?method=unsupported")

    assert response.status_code == 400
    assert "method" in response.json()["details"]


@pytest.mark.django_db
def test_audit_tui_attribution_projects_percentage_chart_rows(
    authenticated_client,
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.audit.interface.tui_views.get_attribution_chart_data_payload",
        lambda report_id: {
            "report_id": report_id,
            "regime_timing_pnl": 0.12,
            "asset_selection_pnl": -0.03,
            "interaction_pnl": 0.01,
            "total_pnl": 0.10,
            "regime_accuracy": 0.75,
            "period_attributions": [],
            "loss_analyses": [],
            "experience_summaries": [],
        },
    )

    response = authenticated_client.get("/api/audit/tui/attribution/7/")

    assert response.status_code == 200
    assert response.json()["contributions"] == [
        {"component": "Regime 择时", "value_percent": 12.0},
        {"component": "资产选择", "value_percent": -3.0},
        {"component": "交互效应", "value_percent": 1.0},
        {"component": "总收益", "value_percent": 10.0},
    ]


@pytest.mark.django_db
def test_audit_tui_indicator_performance_is_chart_ready(
    authenticated_client,
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.audit.interface.tui_views.build_indicator_performance_page_context",
        lambda: {
            "total_indicators": 1,
            "approved_indicators": 1,
            "pending_indicators": 0,
            "rejected_indicators": 0,
            "avg_f1_score": 0.8,
            "avg_stability_score": 0.7,
            "indicator_reports": [
                {
                    "indicator_code": "PMI",
                    "indicator_name": "采购经理指数",
                    "category": "growth",
                    "f1_score": 0.8,
                    "stability_score": 0.7,
                }
            ],
        },
    )

    response = authenticated_client.get("/api/audit/tui/indicator-performance/")

    assert response.status_code == 200
    assert response.json()["results"][0]["f1_percent"] == 80.0
    assert response.json()["results"][0]["stability_percent"] == 70.0


@pytest.mark.django_db
def test_audit_tui_thresholds_flattens_history(
    authenticated_client,
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.audit.interface.tui_views.build_threshold_validation_page_context",
        lambda: {
            "validation_status": "completed",
            "validation_status_label": "已完成",
            "validation_message": "ok",
            "threshold_configs": [
                {
                    "indicator_code": "PMI",
                    "indicator_name": "采购经理指数",
                    "level_low": 49.0,
                    "level_high": 51.0,
                    "validation_history": [
                        {
                            "validation_date": "2026-06-30",
                            "f1_score": 0.8,
                            "stability_score": 0.7,
                        }
                    ],
                }
            ],
        },
    )

    response = authenticated_client.get("/api/audit/tui/thresholds/")

    assert response.status_code == 200
    payload = response.json()
    assert "validation_history" not in payload["results"][0]
    assert payload["history"] == [
        {
            "observation": "PMI · 2026-06-30",
            "indicator_code": "PMI",
            "validation_date": "2026-06-30",
            "f1_percent": 80.0,
            "stability_percent": 70.0,
        }
    ]


@pytest.mark.django_db
def test_audit_tui_manual_trade_summary_preserves_portfolio_ids(
    authenticated_client,
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.audit.interface.tui_views.build_manual_trade_review_context_payload",
        lambda user_id: {
            "batches": [
                {
                    "id": 1,
                    "portfolio_id": 7,
                    "portfolio_name": "实盘",
                    "user_id": user_id,
                }
            ],
            "transactions": [
                {
                    "id": 2,
                    "portfolio_id": 7,
                    "portfolio_name": "实盘",
                    "asset_code": "000001.SZ",
                }
            ],
        },
    )

    response = authenticated_client.get("/api/audit/tui/manual-trades/")

    assert response.status_code == 200
    assert response.json()["batches"][0]["portfolio_id"] == 7
    assert response.json()["transactions"][0]["portfolio_id"] == 7


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url", "error"),
    [
        (
            "/api/audit/decision-traces/?page=bad",
            "page must be a positive integer",
        ),
        (
            "/api/audit/decision-traces/?page_size=101",
            "page_size must be between 1 and 100",
        ),
        (
            "/api/audit/execution-links/?limit=bad",
            "limit must be a positive integer",
        ),
        (
            "/api/audit/execution-links/?limit=501",
            "limit must be between 1 and 500",
        ),
    ],
)
def test_audit_list_endpoints_reject_invalid_pagination(
    authenticated_client,
    url,
    error,
):
    response = authenticated_client.get(url)

    assert response.status_code == 400
    assert response.json() == {"success": False, "error": error}
