from datetime import date
from unittest.mock import Mock

from apps.filter.application.use_cases import ApplyFilterRequest, ApplyFilterUseCase
from apps.filter.domain.entities import FilterType


def test_kalman_calculation_without_result_persistence_does_not_save_state():
    repository = Mock()
    repository.get_filter_config.return_value = {
        "kalman_level_variance": 0.05,
        "kalman_slope_variance": 0.005,
        "kalman_observation_variance": 0.5,
    }
    repository.get_macro_indicator_data.return_value = [
        {"date": date(2026, 1, 1), "value": 50.0},
        {"date": date(2026, 2, 1), "value": 50.5},
    ]
    repository.get_latest_kalman_state.return_value = None

    response = ApplyFilterUseCase(repository).execute(
        ApplyFilterRequest(
            indicator_code="PMI",
            filter_type=FilterType.KALMAN,
            save_results=False,
        )
    )

    assert response.success is True
    repository.save_kalman_state.assert_not_called()
    repository.save_filter_results.assert_not_called()


def test_kalman_persistence_saves_state_and_results_together():
    repository = Mock()
    repository.get_filter_config.return_value = {
        "kalman_level_variance": 0.05,
        "kalman_slope_variance": 0.005,
        "kalman_observation_variance": 0.5,
    }
    repository.get_macro_indicator_data.return_value = [
        {"date": date(2026, 1, 1), "value": 50.0},
        {"date": date(2026, 2, 1), "value": 50.5},
    ]
    repository.get_latest_kalman_state.return_value = None

    response = ApplyFilterUseCase(repository).execute(
        ApplyFilterRequest(
            indicator_code="PMI",
            filter_type=FilterType.KALMAN,
            save_results=True,
        )
    )

    assert response.success is True
    repository.save_kalman_state.assert_called_once()
    repository.save_filter_results.assert_called_once_with(response.series)
