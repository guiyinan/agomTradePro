from datetime import date

from apps.sector.application.use_cases import (
    AnalyzeSectorRotationRequest,
    AnalyzeSectorRotationUseCase,
    UpdateSectorDataRequest,
    UpdateSectorDataUseCase,
)
from apps.sector.domain.entities import SectorIndex, SectorInfo


class _EmptySectorRepo:
    def get_sector_weights_by_regime(self, regime: str):
        return {"801010": 1.0}

    def get_all_sectors(self, level=None):
        return []


def test_analyze_sector_rotation_resolves_latest_regime_when_missing(mocker) -> None:
    mocker.patch(
        "apps.sector.application.use_cases.get_latest_regime_diagnostic_payload",
        return_value={
            "dominant_regime": "Recovery",
            "observed_at": date(2026, 7, 12),
            "confidence": 0.8,
        },
    )
    result = AnalyzeSectorRotationUseCase(_EmptySectorRepo()).execute(
        AnalyzeSectorRotationRequest(regime=None, level="SW1")
    )

    assert result.success is False
    assert result.regime == "Recovery"
    assert result.warning_message == "sector_data_unavailable"


class _SingleSectorRepo:
    def get_sector_weights_by_regime(self, regime: str):
        return {"801010": 1.0}

    def get_all_sectors(self, level=None):
        return [SectorInfo(sector_code="801010", sector_name="农林牧渔", level="SW1")]

    def get_sector_index_range(self, sector_code, start_date, end_date):
        return [
            SectorIndex(
                sector_code="801010",
                trade_date=date_value,
                open_price=1000,
                high=1010,
                low=995,
                close=1005 + idx,
                volume=1000000,
                amount=10000000,
                change_pct=0.5 + idx,
                turnover_rate=None,
            )
            for idx, date_value in enumerate([date(2025, 3, 3), date(2025, 3, 4), date(2025, 3, 5)])
        ]


def test_analyze_sector_rotation_degrades_when_market_returns_are_unavailable(mocker) -> None:
    use_case = AnalyzeSectorRotationUseCase(_SingleSectorRepo())
    mocker.patch.object(use_case, "_get_market_returns", return_value=None)

    result = use_case.execute(AnalyzeSectorRotationRequest(regime="Recovery", level="SW1", top_n=5))

    assert result.success is True
    assert result.status == "degraded"
    assert result.data_source == "fallback"
    assert result.warning_message == "market_returns_fallback"
    assert "沪深300" in result.warning_detail
    assert len(result.top_sectors) == 1


def test_get_market_returns_pads_one_missing_benchmark_observation(mocker) -> None:
    use_case = AnalyzeSectorRotationUseCase(_SingleSectorRepo())
    mock_adapter = mocker.Mock()
    mock_adapter.get_index_daily_returns.return_value = {
        date(2025, 3, 4): 0.01,
        date(2025, 3, 5): -0.004,
    }
    use_case.market_adapter = mock_adapter

    returns = use_case._get_market_returns(
        start_date=date(2025, 3, 3),
        end_date=date(2025, 3, 5),
        expected_length=3,
    )

    assert returns == [0.0, 0.01, -0.004]
    mock_adapter.get_index_daily_returns.assert_called_once_with(
        index_code="000300.SH",
        start_date=date(2025, 3, 3),
        end_date=date(2025, 3, 5),
        hydrate=False,
    )


def test_get_market_returns_rejects_non_finite_provider_values(mocker) -> None:
    use_case = AnalyzeSectorRotationUseCase(_SingleSectorRepo())
    mock_adapter = mocker.Mock()
    mock_adapter.get_index_daily_returns.return_value = {
        date(2025, 3, 4): float("nan"),
        date(2025, 3, 5): 0.01,
    }
    use_case.market_adapter = mock_adapter

    returns = use_case._get_market_returns(
        start_date=date(2025, 3, 3),
        end_date=date(2025, 3, 5),
        expected_length=2,
    )

    assert returns is None


def test_sector_update_rejects_future_start_before_provider_or_write(mocker) -> None:
    repository = mocker.Mock()
    adapter = mocker.Mock()
    result = UpdateSectorDataUseCase(repository, adapter).execute(
        UpdateSectorDataRequest(
            level="SW1",
            start_date="2999-01-01",
            end_date=None,
        )
    )

    assert result.success is False
    assert result.error_code == "INVALID_SECTOR_DATE_RANGE"
    adapter.fetch_sw_industry_classify.assert_not_called()
    repository.save_sector_info.assert_not_called()


def test_sector_update_provider_failure_is_redacted(mocker) -> None:
    repository = mocker.Mock()
    adapter = mocker.Mock()
    adapter.fetch_sw_industry_classify.side_effect = RuntimeError(
        "https://secret-token@provider/sector"
    )

    result = UpdateSectorDataUseCase(repository, adapter).execute(
        UpdateSectorDataRequest(level="SW1")
    )

    assert result.success is False
    assert result.error == "Sector data update failed."
    assert result.error_code == "SECTOR_UPDATE_FAILED"
    assert "secret" not in result.error
