import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings

from apps.equity.application.use_cases_valuation_repair import (
    GetValuationRepairStatusRequest,
    GetValuationRepairStatusUseCase,
)
from apps.equity.domain.entities_valuation_repair import ValuationRepairConfig


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(username="staff_cfg", password="pass1234", is_staff=True)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def normal_client(db):
    user = User.objects.create_user(username="normal_cfg", password="pass1234", is_staff=False)
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
@override_settings(EQUITY_VALUATION_TARGET_PERCENTILE=0.61)
def test_active_config_endpoint_reflects_settings_override(staff_client):
    response = staff_client.get("/api/equity/config/valuation-repair/active/")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["source"] == "settings"
    assert data["data"]["target_percentile"] == 0.61


@pytest.mark.django_db
def test_create_config_requires_staff(normal_client):
    response = normal_client.post(
        "/api/equity/config/valuation-repair/",
        data={"change_reason": "test", "target_percentile": 0.55},
        content_type="application/json",
    )

    assert response.status_code == 403


class _StubStockInfo:
    name = "测试股票"


class _StubValuation:
    def __init__(self, trade_date, pe, pb):
        self.trade_date = trade_date
        self.pe = pe
        self.pb = pb


class _StubStockRepository:
    def __init__(self, valuations):
        self._valuations = valuations

    def get_stock_info(self, stock_code):
        return _StubStockInfo()

    def get_valuation_history(self, stock_code, start_date, end_date):
        return self._valuations


@pytest.mark.django_db
def test_status_use_case_passes_runtime_config(monkeypatch):
    from datetime import date, timedelta

    import apps.equity.application.use_cases_valuation_repair as target_module

    captured = {}
    runtime_config = ValuationRepairConfig(target_percentile=0.66, repairing_threshold=0.12)

    valuations = [
        _StubValuation(date(2025, 1, 1) + timedelta(days=i), 10 + i * 0.1, 1 + i * 0.01)
        for i in range(150)
    ]

    def fake_get_valuation_repair_config():
        return runtime_config

    def fake_analyze_repair_status(**kwargs):
        captured["config"] = kwargs["config"]

        class _Status:
            stock_code = "000001.SZ"
            stock_name = "测试股票"
            as_of_date = date(2025, 6, 1)
            phase = "repairing"
            signal = "in_progress"
            current_pe = 12.0
            current_pb = 1.2
            pe_percentile = 0.2
            pb_percentile = 0.3
            composite_percentile = 0.24
            composite_method = "pe_pb_blend"
            repair_start_date = None
            repair_start_percentile = None
            lowest_percentile = 0.1
            lowest_percentile_date = date(2025, 3, 1)
            repair_progress = None
            target_percentile = kwargs["config"].target_percentile
            repair_speed_per_30d = None
            estimated_days_to_target = None
            is_stalled = False
            stall_start_date = None
            stall_duration_trading_days = 0
            repair_duration_trading_days = 0
            lookback_trading_days = 150
            confidence = 0.8
            description = "ok"

        return _Status()

    monkeypatch.setattr(target_module, "get_valuation_repair_config", fake_get_valuation_repair_config)
    monkeypatch.setattr(target_module, "analyze_repair_status", fake_analyze_repair_status)

    use_case = GetValuationRepairStatusUseCase(stock_repository=_StubStockRepository(valuations))
    response = use_case.execute(GetValuationRepairStatusRequest(stock_code="000001.SZ", lookback_days=150))

    assert response.success is True
    assert captured["config"] == runtime_config
    assert response.data["target_percentile"] == 0.66
