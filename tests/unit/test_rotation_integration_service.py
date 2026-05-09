from datetime import date, timedelta

import pytest

from apps.rotation.infrastructure.models import RotationConfigModel, RotationSignalModel
from apps.rotation.infrastructure.services import RotationIntegrationService


def _create_momentum_config(name: str = "测试动量配置") -> RotationConfigModel:
    return RotationConfigModel.objects.create(
        name=name,
        description="测试用动量配置",
        strategy_type="momentum",
        asset_universe=["510300", "515180"],
        params={"momentum_periods": [20, 60, 120]},
        top_n=2,
        is_active=True,
    )


@pytest.mark.django_db
def test_get_rotation_recommendation_reuses_same_day_signal(monkeypatch):
    config = _create_momentum_config()
    today = date.today()
    RotationSignalModel.objects.create(
        config=config,
        signal_date=today,
        target_allocation={"510300": 0.6, "515180": 0.4},
        current_regime="Recovery",
        momentum_ranking=[["510300", 0.12], ["515180", 0.08]],
        action_required="rebalance",
        reason="reuse stored signal",
    )

    service = RotationIntegrationService()

    def _unexpected_generate(_: str):
        raise AssertionError("should not regenerate when today's signal already exists")

    monkeypatch.setattr(service, "generate_rotation_signal", _unexpected_generate)

    result = service.get_rotation_recommendation("momentum")

    assert result["target_allocation"] == {"510300": 0.6, "515180": 0.4}
    assert result["signal_date"] == today.isoformat()
    assert result["data_source"] == "stored_signal"
    assert result["is_stale"] is False
    assert result["strategy_type"] == "momentum"
    assert result["warning_message"] is None


@pytest.mark.django_db
def test_get_rotation_recommendation_falls_back_to_latest_signal_when_generation_fails(monkeypatch):
    config = _create_momentum_config(name="测试动量配置-回退")
    signal_date = date.today() - timedelta(days=1)
    RotationSignalModel.objects.create(
        config=config,
        signal_date=signal_date,
        target_allocation={"515180": 1.0},
        current_regime="Recovery",
        momentum_ranking=[["515180", 0.11]],
        action_required="hold",
        reason="fallback to latest stored signal",
    )

    service = RotationIntegrationService()
    monkeypatch.setattr(service, "generate_rotation_signal", lambda _: None)

    result = service.get_rotation_recommendation("momentum")

    assert result["target_allocation"] == {"515180": 1.0}
    assert result["signal_date"] == signal_date.isoformat()
    assert result["data_source"] == "stored_signal_fallback"
    assert result["is_stale"] is True
    assert result["reason"] == "fallback to latest stored signal"
    assert "最近一次已落库信号" in result["warning_message"]


@pytest.mark.django_db
def test_get_rotation_recommendation_prefers_latest_persisted_signal_for_workspace(monkeypatch):
    config = _create_momentum_config(name="测试动量配置-工作台复用")
    signal_date = date.today() - timedelta(days=2)
    RotationSignalModel.objects.create(
        config=config,
        signal_date=signal_date,
        target_allocation={"510300": 0.55, "515180": 0.45},
        current_regime="Recovery",
        momentum_ranking=[["510300", 0.10], ["515180", 0.09]],
        action_required="hold",
        reason="reuse latest persisted signal for workspace",
    )

    service = RotationIntegrationService()
    monkeypatch.setattr(
        service,
        "generate_rotation_signal",
        lambda _: (_ for _ in ()).throw(
            AssertionError("workspace read path should not regenerate stale rotation data")
        ),
    )

    result = service.get_rotation_recommendation("momentum", prefer_persisted=True)

    assert result["target_allocation"] == {"510300": 0.55, "515180": 0.45}
    assert result["signal_date"] == signal_date.isoformat()
    assert result["data_source"] == "stored_signal_fallback"
    assert result["is_stale"] is True
    assert "工作台优先复用最近一次已落库轮动信号" in result["warning_message"]
