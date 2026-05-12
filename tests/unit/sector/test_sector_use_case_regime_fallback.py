from datetime import date
from types import SimpleNamespace

from apps.sector.application.use_cases import (
    AnalyzeSectorRotationRequest,
    AnalyzeSectorRotationUseCase,
)
from apps.sector.domain.entities import SectorIndex, SectorInfo


class _EmptySectorRepo:
    def get_sector_weights_by_regime(self, regime: str):
        return {"801010": 1.0}

    def get_all_sectors(self, level=None):
        return []


def test_analyze_sector_rotation_resolves_latest_regime_when_missing(mocker) -> None:
    mocker.patch(
        "apps.regime.application.current_regime.resolve_current_regime",
        return_value=SimpleNamespace(dominant_regime="Recovery"),
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
            for idx, date_value in enumerate(
                [date(2025, 3, 3), date(2025, 3, 4), date(2025, 3, 5)]
            )
        ]


def test_analyze_sector_rotation_degrades_when_market_returns_are_unavailable(mocker) -> None:
    use_case = AnalyzeSectorRotationUseCase(_SingleSectorRepo())
    mocker.patch.object(use_case, "_get_market_returns", return_value=None)

    result = use_case.execute(
        AnalyzeSectorRotationRequest(regime="Recovery", level="SW1", top_n=5)
    )

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
