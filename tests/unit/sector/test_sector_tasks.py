"""Unit tests for the sector Celery task boundary."""

from datetime import date, timedelta

import pytest

from apps.sector.application import tasks
from apps.sector.application.use_cases import (
    SectorRotationResult,
    UpdateSectorDataResult,
)
from apps.sector.domain.entities import SectorScore


def test_update_daily_sector_data_uses_provider_factories(mocker) -> None:
    """The daily task validates its request and delegates through providers."""

    repository = object()
    adapter = object()
    get_repository = mocker.patch.object(
        tasks,
        "get_sector_repository",
        return_value=repository,
    )
    get_adapter = mocker.patch.object(
        tasks,
        "get_sector_adapter",
        return_value=adapter,
    )
    execute = mocker.Mock(
        return_value=UpdateSectorDataResult(
            success=True,
            updated_count=12,
        )
    )
    use_case_type = mocker.patch.object(tasks, "UpdateSectorDataUseCase")
    use_case_type.return_value.execute = execute

    payload = tasks.update_daily_sector_data.run("SW2")

    assert payload == {
        "success": True,
        "updated_count": 12,
        "error": None,
        "error_code": None,
    }
    get_repository.assert_called_once_with()
    get_adapter.assert_called_once_with()
    use_case_type.assert_called_once_with(repository, adapter)
    request = execute.call_args.args[0]
    assert request.level == "SW2"
    assert request.end_date == date.today().isoformat()
    assert request.start_date == (date.today() - timedelta(days=7)).isoformat()


def test_update_daily_sector_data_rejects_level_before_provider_access(mocker) -> None:
    """Invalid task input must fail before opening provider boundaries."""

    get_repository = mocker.patch.object(tasks, "get_sector_repository")
    get_adapter = mocker.patch.object(tasks, "get_sector_adapter")

    with pytest.raises(ValueError, match="Unsupported sector level"):
        tasks.update_daily_sector_data.run("UNKNOWN")

    get_repository.assert_not_called()
    get_adapter.assert_not_called()


def test_update_daily_sector_data_propagates_provider_failure_for_retry(mocker) -> None:
    """Infrastructure setup failures must reach Celery's autoretry wrapper."""

    mocker.patch.object(
        tasks,
        "get_sector_repository",
        side_effect=RuntimeError("database unavailable"),
    )
    get_adapter = mocker.patch.object(tasks, "get_sector_adapter")

    with pytest.raises(RuntimeError, match="database unavailable"):
        tasks.update_daily_sector_data.run()

    get_adapter.assert_not_called()


def test_analyze_sector_rotation_returns_stable_success_contract(mocker) -> None:
    """Successful analysis exposes ranking and diagnostic provenance."""

    repository = object()
    get_repository = mocker.patch.object(
        tasks,
        "get_sector_repository",
        return_value=repository,
    )
    score = SectorScore(
        sector_code="801010",
        sector_name="农林牧渔",
        trade_date=date(2026, 7, 24),
        momentum_score=81.234,
        relative_strength_score=72.345,
        regime_fit_score=90.456,
        total_score=80.567,
        rank=1,
    )
    execute = mocker.Mock(
        return_value=SectorRotationResult(
            success=True,
            regime="Recovery",
            analysis_date=date(2026, 7, 24),
            top_sectors=[score],
            status="degraded",
            data_source="fallback",
            warning_message="market_returns_fallback",
            warning_detail="benchmark unavailable",
        )
    )
    use_case_type = mocker.patch.object(tasks, "AnalyzeSectorRotationUseCase")
    use_case_type.return_value.execute = execute

    payload = tasks.analyze_sector_rotation.run("Recovery")

    assert payload == {
        "success": True,
        "regime": "Recovery",
        "analysis_date": "2026-07-24",
        "top_sectors": [
            {
                "rank": 1,
                "sector_code": "801010",
                "sector_name": "农林牧渔",
                "total_score": 80.57,
                "momentum_score": 81.23,
                "rs_score": 72.34,
                "regime_fit_score": 90.46,
            }
        ],
        "error": None,
        "error_code": None,
        "status": "degraded",
        "data_source": "fallback",
        "warning_message": "market_returns_fallback",
        "warning_detail": "benchmark unavailable",
    }
    get_repository.assert_called_once_with()
    use_case_type.assert_called_once_with(repository)
    request = execute.call_args.args[0]
    assert request.regime == "Recovery"
    assert request.lookback_days == 20
    assert request.top_n == 10


def test_analyze_sector_rotation_preserves_failure_diagnostics(mocker) -> None:
    """Business failures keep a stable schema and machine-readable diagnosis."""

    mocker.patch.object(tasks, "get_sector_repository", return_value=object())
    execute = mocker.Mock(
        return_value=SectorRotationResult(
            success=False,
            regime="Deflation",
            analysis_date=date(2026, 7, 24),
            top_sectors=[],
            error="No persisted sector data.",
            error_code="SECTOR_DATA_UNAVAILABLE",
            status="unavailable",
            data_source="persisted",
            warning_message="sector_data_unavailable",
            warning_detail="refresh sector data",
        )
    )
    use_case_type = mocker.patch.object(tasks, "AnalyzeSectorRotationUseCase")
    use_case_type.return_value.execute = execute

    payload = tasks.analyze_sector_rotation.run("Deflation")

    assert payload == {
        "success": False,
        "regime": "Deflation",
        "analysis_date": "2026-07-24",
        "top_sectors": [],
        "error": "No persisted sector data.",
        "error_code": "SECTOR_DATA_UNAVAILABLE",
        "status": "unavailable",
        "data_source": "persisted",
        "warning_message": "sector_data_unavailable",
        "warning_detail": "refresh sector data",
    }
