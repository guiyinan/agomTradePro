"""AgomTradePro SDK - Config Center module."""

from typing import Any

from .base import BaseModule


class ConfigCenterModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/system")

    def get_snapshot(self) -> dict[str, Any]:
        response = self._get("config-center/")
        return response.get("data", response)

    def list_capabilities(self) -> list[dict[str, Any]]:
        response = self._get("config-capabilities/")
        if isinstance(response, list):
            return response
        return response.get("data", response)

    def get_qlib_runtime(self) -> dict[str, Any]:
        response = self._get("config-center/qlib/runtime/")
        return response.get("data", response)

    def update_qlib_runtime(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post("config-center/qlib/runtime/", json=payload)
        return response.get("data", response)

    def list_qlib_training_profiles(self) -> list[dict[str, Any]]:
        response = self._get("config-center/qlib/training-profiles/")
        if isinstance(response, list):
            return response
        return response.get("data", response)

    def save_qlib_training_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post("config-center/qlib/training-profiles/", json=payload)
        return response.get("data", response)

    def list_qlib_training_runs(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        params = {"limit": limit} if limit is not None else None
        response = self._get("config-center/qlib/training-runs/", params=params)
        if isinstance(response, list):
            return response
        return response.get("data", response)

    def get_qlib_training_run_detail(self, run_id: str) -> dict[str, Any]:
        response = self._get(f"config-center/qlib/training-runs/{run_id}/")
        return response.get("data", response)

    def trigger_qlib_training(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post("config-center/qlib/training-runs/trigger/", json=payload)
        return response.get("data", response)
