"""AgomSAAF SDK - Alpha Trigger 模块。"""

from typing import Any

from .base import BaseModule


class AlphaTriggerModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/alpha-triggers")

    def list_triggers(self) -> list[dict[str, Any]]:
        response = self._get("triggers/")
        return response.get("results", response) if isinstance(response, dict) else response

    def get_trigger(self, trigger_id: str) -> dict[str, Any]:
        return self._get(f"triggers/{trigger_id}/")

    def create_trigger(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("create/", json=payload)

    def check_invalidation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("check-invalidation/", json=payload)

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("evaluate/", json=payload)

    def generate_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("generate-candidate/", json=payload)

    def performance(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload:
            return self._post("performance/", json=payload)
        return self._get("performance/")

    def list_candidates(self) -> list[dict[str, Any]]:
        response = self._get("candidates/")
        return response.get("results", response) if isinstance(response, dict) else response

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        return self._get(f"candidates/{candidate_id}/")

    def update_candidate_status(
        self,
        candidate_id: str,
        status: str,
    ) -> dict[str, Any]:
        """
        更新候选状态。

        Args:
            candidate_id: 候选ID
            status: 新状态（WATCH/CANDIDATE/ACTIONABLE/EXECUTED/CANCELLED）
        """
        return self._post(
            f"candidates/{candidate_id}/update-status/",
            json={"status": status},
        )
