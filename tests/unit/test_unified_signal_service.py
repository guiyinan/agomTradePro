from datetime import date
from types import SimpleNamespace

from apps.signal.application.unified_service import UnifiedSignalService


def _build_service(mocker) -> UnifiedSignalService:
    mocker.patch(
        "apps.signal.application.unified_service.UnifiedSignalRepository",
        return_value=mocker.Mock(),
    )
    mocker.patch("apps.signal.application.unified_service.ROTATION_AVAILABLE", False)
    mocker.patch("apps.signal.application.unified_service.HEDGE_AVAILABLE", False)
    mocker.patch("apps.signal.application.unified_service.FACTOR_AVAILABLE", False)
    return UnifiedSignalService()


def test_collect_all_signals_records_module_error_and_continues(mocker) -> None:
    service = _build_service(mocker)
    calc_date = date(2026, 5, 1)

    mocker.patch.object(
        service,
        "_collect_regime_signals",
        side_effect=ValueError("regime down"),
    )
    mocker.patch.object(service, "_collect_rotation_signals", return_value=[{"id": 1}])
    mocker.patch.object(service, "_collect_factor_signals", return_value=[{"id": 2}, {"id": 3}])
    mocker.patch.object(service, "_collect_hedge_signals", return_value=[])
    mocker.patch.object(service, "_collect_alpha_signals", return_value=[{"id": 4}])

    result = service.collect_all_signals(calc_date)

    assert result["regime_signals"] == 0
    assert result["rotation_signals"] == 1
    assert result["factor_signals"] == 2
    assert result["hedge_signals"] == 0
    assert result["alpha_signals"] == 1
    assert result["total_signals"] == 4
    assert result["errors"] == ["Regime: regime down"]


def test_collect_alpha_signals_emits_buy_and_degraded_alert(mocker) -> None:
    service = _build_service(mocker)
    calc_date = date(2026, 5, 1)
    repo = service.unified_repo
    repo.create_signal.side_effect = lambda **kwargs: kwargs
    service._alpha_service = lambda **kwargs: SimpleNamespace(
        success=True,
        scores=[
            SimpleNamespace(
                code="600519.SH",
                score=0.91,
                rank=1,
                confidence=0.88,
                source="cache",
                factors={"momentum": 0.9},
                model_id="model-1",
                model_artifact_hash="hash-1",
                asof_date=calc_date,
                universe_id="csi300",
            ),
            SimpleNamespace(
                code="000001.SH",
                score=0.41,
                rank=2,
                confidence=0.72,
                source="cache",
                factors={},
                model_id=None,
                model_artifact_hash=None,
                asof_date=None,
                universe_id="csi300",
            ),
        ],
        status="degraded",
        source="cache",
        staleness_days=2,
        error_message=None,
    )

    signals = service._collect_alpha_signals(calc_date)

    assert len(signals) == 2
    assert signals[0]["signal_type"] == "buy"
    assert signals[0]["asset_code"] == "600519.SH"
    assert signals[1]["signal_type"] == "alert"
    assert signals[1]["asset_code"] == "ALPHA_SYSTEM"
    assert signals[1]["extra_data"]["staleness_days"] == 2


def test_collect_rotation_signals_uses_application_batch_provider(mocker) -> None:
    service = _build_service(mocker)
    calc_date = date(2026, 5, 1)
    service.unified_repo.create_signal.side_effect = lambda **kwargs: kwargs
    service.rotation_signal_fetcher = lambda requested_date: {
        "signal_date": requested_date.isoformat(),
        "signals": [
            {
                "config_name": "cross-asset-momentum",
                "target_allocation": {"510300": 0.6, "511260": 0.4},
            }
        ],
    }

    signals = service._collect_rotation_signals(calc_date)

    assert [signal["asset_code"] for signal in signals] == ["510300", "511260"]
    assert signals[0]["target_weight"] == 0.6
    assert signals[0]["extra_data"]["config_name"] == "cross-asset-momentum"


def test_get_unified_signals_applies_minimum_priority(mocker) -> None:
    service = _build_service(mocker)
    calc_date = date(2026, 5, 1)
    service.unified_repo.get_signals_by_date.return_value = [
        {"id": 1, "priority": 7},
        {"id": 2, "priority": 3},
    ]

    signals = service.get_unified_signals(calc_date, min_priority=5)

    assert signals == [{"id": 1, "priority": 7}]
