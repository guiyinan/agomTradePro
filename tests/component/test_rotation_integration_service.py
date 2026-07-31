import logging
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from apps.rotation.domain.entities import RotationConfig, RotationStrategyType
from apps.rotation.infrastructure import services as rotation_services


@pytest.mark.django_db
def test_generate_rotation_signal_treats_empty_allocation_as_expected_gap(monkeypatch, caplog):
    service = rotation_services.RotationIntegrationService()
    config = RotationConfig(
        name="MomentumConfig",
        strategy_type=RotationStrategyType.MOMENTUM,
        asset_universe=["510300"],
    )

    monkeypatch.setattr(service.config_repo, "get_by_name", lambda name: config)
    monkeypatch.setattr(service, "_get_current_regime", lambda: None)

    class FakeRotationService:
        def __init__(self, context):
            self.context = context

        def generate_signal(self, config):
            raise ValueError("Target allocation weights must sum to 1.0, got 0")

    monkeypatch.setattr(rotation_services, "RotationService", FakeRotationService)

    with caplog.at_level(logging.ERROR):
        result = service.generate_rotation_signal("MomentumConfig", date(2026, 6, 22))

    assert result == {
        "config_name": "MomentumConfig",
        "signal_date": "2026-06-22",
        "status": "skipped",
        "error": "no_valid_allocation",
        "reason": "Target allocation weights must sum to 1.0, got 0",
        "target_allocation": {},
        "momentum_ranking": [],
    }
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.mark.django_db
def test_monthly_rotation_recommendation_stays_fresh_within_month(monkeypatch, caplog):
    service = rotation_services.RotationIntegrationService()
    as_of_date = date(2026, 7, 15)
    config = RotationConfig(
        name="MomentumConfig",
        description="fallback config",
        strategy_type=RotationStrategyType.MOMENTUM,
        asset_universe=["510300"],
    )
    model = SimpleNamespace(id=7)
    latest_signal = SimpleNamespace(
        config=SimpleNamespace(name="MomentumConfig"),
        signal_date=as_of_date - timedelta(days=1),
        target_allocation={"510300": 1.0},
        current_regime="Recovery",
        action_required="hold",
        reason="use stored",
        momentum_ranking=[("510300", 1.0)],
    )

    monkeypatch.setattr(service.config_repo, "get_active", lambda: [config])
    monkeypatch.setattr(service.config_repo, "get_model_by_name", lambda name: model)
    monkeypatch.setattr(service.signal_repo, "get_latest_signal", lambda config_id: latest_signal)
    monkeypatch.setattr(service, "generate_rotation_signal", lambda name: None)
    monkeypatch.setattr(rotation_services.timezone, "localdate", lambda: as_of_date)

    with caplog.at_level(logging.WARNING):
        result = service.get_rotation_recommendation("momentum")

    assert result["data_source"] == "stored_signal"
    assert result["is_stale"] is False
    assert result["warning_message"] is None
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_rotation_staleness_follows_rebalance_period():
    is_stale = rotation_services.is_rotation_signal_stale

    assert is_stale(date(2026, 7, 1), "monthly", date(2026, 7, 31)) is False
    assert is_stale(date(2026, 6, 30), "monthly", date(2026, 7, 1)) is True
    assert is_stale(date(2026, 7, 13), "weekly", date(2026, 7, 19)) is False
    assert is_stale(date(2026, 7, 19), "weekly", date(2026, 7, 20)) is True
    assert is_stale(date(2026, 7, 1), "quarterly", date(2026, 9, 30)) is False
    assert is_stale(date(2026, 9, 30), "quarterly", date(2026, 10, 1)) is True


def test_rotation_recommendation_uses_django_local_business_date(monkeypatch):
    service = rotation_services.RotationIntegrationService()
    config = RotationConfig(
        name="MonthlyConfig",
        strategy_type=RotationStrategyType.MOMENTUM,
        asset_universe=["510300"],
        rebalance_frequency="monthly",
    )
    latest_signal = SimpleNamespace(
        config=SimpleNamespace(name="MonthlyConfig"),
        signal_date=date(2026, 7, 31),
        target_allocation={"510300": 1.0},
        current_regime="Recovery",
        action_required="hold",
        reason="stored",
        momentum_ranking=[["510300", 1.0]],
    )

    monkeypatch.setattr(rotation_services.timezone, "localdate", lambda: date(2026, 8, 1))
    monkeypatch.setattr(service.config_repo, "get_active", lambda: [config])
    monkeypatch.setattr(
        service.config_repo,
        "get_model_by_name",
        lambda name: SimpleNamespace(id=7),
    )
    monkeypatch.setattr(service.signal_repo, "get_latest_signal", lambda config_id: latest_signal)

    result = service.get_rotation_recommendation("momentum", prefer_persisted=True)

    assert result["is_stale"] is True
    assert result["data_source"] == "stored_signal_fallback"


def test_risk_parity_quality_uses_allocation_coverage_not_momentum_ranking():
    config = RotationConfig(
        name="RiskParityConfig",
        strategy_type=RotationStrategyType.RISK_PARITY,
        asset_universe=["510300", "510500"],
    )
    signal = SimpleNamespace(
        target_allocation={"510300": 0.6, "510500": 0.4},
        momentum_ranking=[],
        expected_return=0.08,
        expected_volatility=0.12,
    )

    quality = rotation_services.RotationIntegrationService._build_signal_data_quality(
        signal,
        config,
    )

    assert quality["status"] == "ok"
    assert quality["coverage_ratio"] == 1.0
    assert "partial_price_coverage" not in quality["warnings"]
