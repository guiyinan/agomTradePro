"""Forecast scoreboard application boundary."""

from typing import Any, Protocol


class ForecastScoreboardGateway(Protocol):
    def summarize(self, group_by: str | None = None) -> dict[str, Any]: ...


class GetForecastScoreboardUseCase:
    def __init__(self, repository: ForecastScoreboardGateway):
        self._repository = repository

    def execute(self, group_by: str | None = None) -> dict[str, Any]:
        allowed = {None, "source", "strategy_version", "regime", "model_version", "prompt_version"}
        if group_by not in allowed:
            raise ValueError("unsupported scoreboard group_by")
        return self._repository.summarize(group_by)

