"""AgomSAAF SDK - AI Provider 模块。"""

from typing import Any, Optional

from .base import BaseModule


class AIProviderModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/ai")

    def list_providers(self) -> list[dict[str, Any]]:
        response = self._get("api/providers/")
        if isinstance(response, list):
            return response
        return response.get("results", [])

    def get_provider(self, provider_id: int) -> dict[str, Any]:
        return self._get(f"api/providers/{provider_id}/")

    def create_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("api/providers/", json=payload)

    def update_provider(self, provider_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"api/providers/{provider_id}/", json=payload)

    def delete_provider(self, provider_id: int) -> None:
        self._delete(f"api/providers/{provider_id}/")

    def toggle_provider(self, provider_id: int) -> dict[str, Any]:
        return self._post(f"api/providers/{provider_id}/toggle_active/", json={})

    def provider_usage_stats(self, provider_id: int) -> dict[str, Any]:
        return self._get(f"api/providers/{provider_id}/usage_stats/")

    def overall_stats(self) -> dict[str, Any]:
        return self._get("api/providers/overall_stats/")

    def list_usage_logs(self, provider_id: Optional[int] = None, status: Optional[str] = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if provider_id is not None:
            params["provider"] = provider_id
        if status:
            params["status"] = status
        response = self._get("api/logs/", params=params)
        if isinstance(response, list):
            return response
        return response.get("results", [])