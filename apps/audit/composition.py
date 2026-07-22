from apps.audit.application.forecast_scoreboard import GetForecastScoreboardUseCase
from apps.audit.infrastructure.forecast_scoreboard_repository import ForecastScoreboardRepository


def make_get_forecast_scoreboard_use_case() -> GetForecastScoreboardUseCase:
    return GetForecastScoreboardUseCase(ForecastScoreboardRepository())

