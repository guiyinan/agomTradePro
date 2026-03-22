"""
E2E-style checks for audit admin console (Django client based).
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.audit.infrastructure.models import AttributionReport, ValidationSummaryModel
from apps.backtest.infrastructure.models import BacktestResultModel


@pytest.mark.django_db
class TestAuditAdminConsole:
    @pytest.fixture(autouse=True)
    def _override_cache_and_throttle(self, settings):
        settings.CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "audit-admin-e2e",
            }
        }
        settings.REST_FRAMEWORK = {
            **getattr(settings, "REST_FRAMEWORK", {}),
            "DEFAULT_THROTTLE_CLASSES": [],
            "DEFAULT_THROTTLE_RATES": {},
        }

    def test_admin_can_open_admin_page(self):
        user_model = get_user_model()
        admin = user_model.objects.create_user(
            username=f"admin_{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
            is_superuser=True,
        )

        client = Client()
        client.force_login(admin)

        response = client.get("/audit/operation-logs/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "操作审计日志" in content

    def test_review_route_renders_frontend_page(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username=f"review_{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
        )

        client = Client()
        client.force_login(user)

        response = client.get("/audit/review/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "审计复盘中心" in content
        assert "快速入口" in content
        assert "给 `/audit/review/` 一个真正可用的前端入口" in content

    def test_regular_user_gets_403_on_admin_page(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username=f"user_{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
        )
        user.rbac_role = "analyst"

        client = Client()
        client.force_login(user)

        response = client.get("/audit/operation-logs/")
        assert response.status_code == 403

    def test_review_page_is_user_facing_workspace(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username=f"user_{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
        )

        BacktestResultModel.objects.create(
            user=user,
            name="Macro Review Backtest",
            status="completed",
            start_date="2025-01-01",
            end_date="2025-03-31",
            initial_capital="1000000.00",
            rebalance_frequency="monthly",
        )
        reported_backtest = BacktestResultModel.objects.create(
            user=user,
            name="Reported Backtest",
            status="completed",
            start_date="2024-10-01",
            end_date="2024-12-31",
            initial_capital="1000000.00",
            rebalance_frequency="monthly",
        )
        AttributionReport.objects.create(
            backtest=reported_backtest,
            period_start="2024-10-01",
            period_end="2024-12-31",
            attribution_method="heuristic",
            regime_timing_pnl=0.02,
            asset_selection_pnl=0.03,
            interaction_pnl=0.01,
            total_pnl=0.06,
            regime_accuracy=0.72,
            regime_predicted="reflation",
            regime_actual="reflation",
        )
        ValidationSummaryModel.objects.create(
            validation_run_id=f"validation-{uuid.uuid4().hex[:8]}",
            evaluation_period_start="2025-01-01",
            evaluation_period_end="2025-03-31",
            total_indicators=12,
            approved_indicators=9,
            rejected_indicators=2,
            pending_indicators=1,
            avg_f1_score=0.681,
            avg_stability_score=0.702,
            overall_recommendation="继续使用当前核心指标组合",
            status="completed",
            is_shadow_mode=False,
        )

        client = Client()
        client.force_login(user)

        response = client.get("/audit/review/")
        assert response.status_code == 200

        content = response.content.decode("utf-8")
        assert "审计复核工作台" in content
        assert "Macro Review Backtest" in content
        assert "Reported Backtest" in content
        assert "/api/audit/" not in content
