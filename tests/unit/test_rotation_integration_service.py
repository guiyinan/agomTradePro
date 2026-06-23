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

    assert result is None
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.mark.django_db
def test_get_rotation_recommendation_uses_stored_signal_fallback_without_warning(monkeypatch, caplog):
    service = rotation_services.RotationIntegrationService()
    config = RotationConfig(
        name="MomentumConfig",
        description="fallback config",
        strategy_type=RotationStrategyType.MOMENTUM,
        asset_universe=["510300"],
    )
    model = SimpleNamespace(id=7)
    latest_signal = SimpleNamespace(
        config=SimpleNamespace(name="MomentumConfig"),
        signal_date=date.today() - timedelta(days=1),
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

    with caplog.at_level(logging.WARNING):
        result = service.get_rotation_recommendation("momentum")

    assert result["data_source"] == "stored_signal_fallback"
    assert result["is_stale"] is True
    assert "最近一次已落库信号" in result["warning_message"]
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
