"""AgomSAAF SDK - Decision Rhythm 模块。"""

from typing import Any

from .base import BaseModule


class DecisionRhythmModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/decision-rhythm")

    def list_quotas(self) -> list[dict[str, Any]]:
        response = self._get("quotas/")
        return response.get("results", response) if isinstance(response, dict) else response

    def list_cooldowns(self) -> list[dict[str, Any]]:
        response = self._get("cooldowns/")
        return response.get("results", response) if isinstance(response, dict) else response

    def list_requests(self) -> list[dict[str, Any]]:
        response = self._get("requests/")
        return response.get("results", response) if isinstance(response, dict) else response

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("submit/", json=payload)

    def submit_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("submit-batch/", json=payload)

    def summary(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload:
            return self._post("summary/", json=payload)
        return self._get("summary/")

    def reset_quota(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("reset-quota/", json=payload)

    def trend_data(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload:
            return self._post("trend-data/", json=payload)
        return self._get("trend-data/")

    def update_quota(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("quota/update/", json=payload)