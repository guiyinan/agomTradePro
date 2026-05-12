"""AgomTradePro SDK - Beta Gate 模块。"""

from typing import Any

from .base import BaseModule


class BetaGateModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/beta-gate")

    def list_configs(self) -> list[dict[str, Any]]:
        response = self._get("configs/")
        return response.get("results", response) if isinstance(response, dict) else response

    def get_config(self, config_id: str | int) -> dict[str, Any]:
        return self._get(f"configs/{config_id}/")

    def create_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("configs/", json=payload)

    def update_config(self, config_id: str | int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"configs/{config_id}/", json=payload)

    def delete_config(self, config_id: str | int) -> None:
        self._delete(f"configs/{config_id}/")

    def test_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("test/", json=payload)

    def version_compare(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("version/compare/", json=payload)

    def rollback_config(self, config_id: str) -> dict[str, Any]:
        return self._post(f"config/rollback/{config_id}/", json={})

    def suggest_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("config/suggest/", json=payload)
