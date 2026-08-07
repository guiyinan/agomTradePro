from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from rest_framework import serializers

from apps.rotation.application import repository_provider
from apps.rotation.domain.entities import (
    RotationConfig,
    RotationSignal,
    RotationStrategyType,
)
from apps.rotation.infrastructure import services as rotation_services
from apps.rotation.infrastructure.models import RotationConfigModel
from apps.rotation.interface.serializers import PortfolioRotationConfigSerializer


def test_rotation_integration_returns_skipped_for_expected_empty_allocation(monkeypatch):
    class FakeRotationService:
        def __init__(self, context):
            self.context = context

        def generate_signal(self, config):
            raise ValueError("Target allocation weights must sum to 1.0, got 0")

    service = rotation_services.RotationIntegrationService(price_service=object())
    service.config_repo = SimpleNamespace(
        get_by_name=lambda name: SimpleNamespace(
            name=name,
            asset_universe=["510300"],
        )
    )
    monkeypatch.setattr(service, "_get_current_regime", lambda: "Recovery")
    monkeypatch.setattr(rotation_services, "RotationService", FakeRotationService)

    payload = service.generate_rotation_signal(
        "动量轮动配置",
        signal_date=date(2026, 6, 30),
    )

    assert payload["status"] == "skipped"
    assert payload["error"] == "no_valid_allocation"
    assert payload["target_allocation"] == {}


def test_generate_rotation_signals_counts_skipped_separately(monkeypatch):
    class FakeService:
        config_repo = SimpleNamespace(
            get_active=lambda: [
                SimpleNamespace(name="ok"),
                SimpleNamespace(name="skipped"),
                SimpleNamespace(name="failed"),
            ]
        )

        def generate_rotation_signal(self, name, signal_date):
            if name == "ok":
                return {"config_name": name, "target_allocation": {"510300": 1.0}}
            if name == "skipped":
                return {
                    "config_name": name,
                    "status": "skipped",
                    "error": "no_valid_allocation",
                }
            return None

    monkeypatch.setattr(
        repository_provider,
        "get_rotation_integration_service",
        lambda: FakeService(),
    )

    payload = repository_provider.generate_rotation_signals(date(2026, 6, 30))

    assert payload["successful"] == 1
    assert payload["skipped"] == 1
    assert payload["failed"] == 1


def test_rotation_signal_scheduler_counts_skipped_separately():
    class FakeIntegrationService:
        def generate_rotation_signal(self, name, signal_date):
            if name == "ok":
                return {"config_name": name, "target_allocation": {"510300": 1.0}}
            if name == "skipped":
                return {
                    "config_name": name,
                    "status": "skipped",
                    "error": "no_valid_allocation",
                }
            return None

    class FakeConfigRepository:
        def get_active(self):
            return [
                SimpleNamespace(name="ok", strategy_type=SimpleNamespace(value="momentum")),
                SimpleNamespace(
                    name="skipped",
                    strategy_type=SimpleNamespace(value="momentum"),
                ),
                SimpleNamespace(
                    name="failed",
                    strategy_type=SimpleNamespace(value="momentum"),
                ),
            ]

    config_repo = FakeConfigRepository()
    scheduler = rotation_services.RotationSignalScheduler(
        integration_service=FakeIntegrationService(),
        config_repo=config_repo,
    )

    payload = scheduler.generate_all_signals(date(2026, 6, 30))

    assert payload["successful"] == 1
    assert payload["skipped"] == 1
    assert payload["failed"] == 1
    assert scheduler.config_repo is config_repo


def test_generated_signal_is_returned_when_orm_config_is_missing(monkeypatch):
    """Signal computation must not be discarded when persistence cannot be linked."""

    config = RotationConfig(
        name="typed-rotation",
        asset_universe=["510300"],
        top_n=1,
    )
    generated = RotationSignal(
        config_name=config.name,
        signal_date=date(2026, 7, 24),
        target_allocation={"510300": 1.0},
    )

    class FakeRotationService:
        def __init__(self, context):
            self.context = context

        def generate_signal(self, domain_config):
            assert domain_config is config
            return generated

    service = rotation_services.RotationIntegrationService(price_service=object())
    service.config_repo = SimpleNamespace(
        get_by_name=lambda name: config,
        get_model_by_name=lambda name: None,
    )
    service.signal_repo = SimpleNamespace(
        save=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("signal without ORM config must not be persisted")
        )
    )
    monkeypatch.setattr(service, "_get_current_regime", lambda: "Recovery")
    monkeypatch.setattr(rotation_services, "RotationService", FakeRotationService)

    payload = service.generate_rotation_signal(
        config.name,
        signal_date=generated.signal_date,
    )

    assert payload is not None
    assert payload["config_name"] == config.name
    assert payload["target_allocation"] == {"510300": 1.0}


def test_rotation_price_reliability_fails_closed_when_provider_returns_none():
    class NullContractPriceProvider:
        def get_last_read_contract(self, asset_code):
            del asset_code
            return None

    service = rotation_services.RotationIntegrationService(
        price_service=NullContractPriceProvider(),
    )

    payload = service._build_price_reliability(["510300"])

    assert payload["status"] == "blocked"
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_assets"] == ["510300"]
    assert payload["by_asset"]["510300"]["blocked_reason"] == (
        "price_reliability_contract_unavailable"
    )


def test_rotation_allocations_reject_non_numeric_weights():
    """Reject JSON values that would otherwise fail inside sum()."""

    serializer = PortfolioRotationConfigSerializer()

    with pytest.raises(serializers.ValidationError, match="必须分别为非空字符串与数字"):
        serializer.validate_regime_allocations(
            {"Recovery": {"510300": "1.0"}},
        )


def test_rotation_config_model_to_domain_preserves_momentum_periods():
    model = RotationConfigModel(
        name="核心卫星策略",
        strategy_type="custom",
        asset_universe=["510300"],
        lookback_period=120,
        momentum_periods=[60, 120],
        top_n=1,
    )

    domain = model.to_domain()

    assert domain.strategy_type == RotationStrategyType.CUSTOM
    assert domain.momentum_periods == [60, 120]
