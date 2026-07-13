"""AgomTradePro SDK - Beta Gate 模块。"""

from typing import Any

from .base import BaseModule


class BetaGateModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/beta-gate")

    def list_configs(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        params = None if active_only else {"active_only": "false"}
        response = self._get("configs/", params=params) if params else self._get("configs/")
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
        version1 = payload.get("version1", payload.get("version_a", payload.get("from")))
        version2 = payload.get("version2", payload.get("version_b", payload.get("to")))
        params = {}
        if version1 is not None:
            params["version1"] = version1
        if version2 is not None:
            params["version2"] = version2
        return self._get("version/compare/", params=params or None)

    def rollback_config(self, config_id: str) -> dict[str, Any]:
        return self._post(f"config/rollback/{config_id}/", json={})

    def suggest_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("config/suggest/", json=payload)
