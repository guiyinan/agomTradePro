from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.regime.application.orchestration import (
    calculate_regime_after_sync,
    notify_regime_change_after_calculation,
)
from apps.regime.domain.entities import RegimeSnapshot
from apps.regime.infrastructure.repositories import DjangoRegimeRepository


def _mock_v2_response() -> SimpleNamespace:
    return SimpleNamespace(
        success=True,
        result=SimpleNamespace(
            regime=SimpleNamespace(value="Recovery"),
            confidence=0.33,
            distribution={
                "Recovery": 0.33,
                "Overheat": 0.19,
                "Stagflation": 0.18,
                "Deflation": 0.30,
            },
            trend_indicators=[
                SimpleNamespace(indicator_code="PMI", momentum_z=0.16),
                SimpleNamespace(indicator_code="CPI", momentum_z=-0.10),
            ],
        ),
        warnings=[],
        error=None,
    )


@pytest.mark.django_db
def test_calculate_regime_after_sync_persists_snapshot(mocker) -> None:
    use_case = Mock()
    use_case.execute.return_value = _mock_v2_response()
    mocker.patch(
        "apps.regime.application.use_cases.CalculateRegimeV2UseCase",
        return_value=use_case,
    )
    mocker.patch(
        "apps.regime.infrastructure.macro_data_provider.MacroRepositoryAdapter",
        return_value=Mock(),
    )

    result = calculate_regime_after_sync(as_of_date="2026-04-08", use_pit=True)

    latest = DjangoRegimeRepository().get_latest_snapshot()
    assert latest is not None
    assert latest.observed_at == date(2026, 4, 8)
    assert latest.dominant_regime == "Recovery"
    assert latest.growth_momentum_z == 0.16
    assert latest.inflation_momentum_z == -0.10
    assert result["status"] == "success"
    assert result["observed_at"] == "2026-04-08"
    assert result["is_fallback"] is False


def test_notify_regime_change_after_calculation_uses_previous_snapshot(mocker) -> None:
    previous_snapshot = RegimeSnapshot(
        growth_momentum_z=0.2,
        inflation_momentum_z=0.1,
        distribution={"Overheat": 1.0},
        dominant_regime="Overheat",
        confidence=0.5,
        observed_at=date(2026, 4, 7),
    )
    repo = Mock()
    repo.get_latest_snapshot.return_value = previous_snapshot
    mocker.patch(
        "apps.regime.infrastructure.repositories.DjangoRegimeRepository",
        return_value=repo,
    )
    notification_service = Mock()
    mocker.patch(
        "shared.infrastructure.notification_service.get_notification_service",
        return_value=notification_service,
    )

    result = notify_regime_change_after_calculation(
        {
            "status": "success",
            "as_of_date": "2026-04-08",
            "observed_at": "2026-04-08",
            "dominant_regime": "Recovery",
            "confidence": 0.33,
        }
    )

    repo.get_latest_snapshot.assert_called_once_with(before_date=date(2026, 4, 7))
    notification_service.send_alert.assert_called_once()
    assert result["status"] == "success"
