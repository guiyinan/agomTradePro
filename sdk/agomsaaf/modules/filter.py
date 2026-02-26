"""AgomSAAF SDK - Filter 模块。"""

from typing import Any

from .base import BaseModule


class FilterModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/filter/api")

    def list_filters(self) -> list[dict[str, Any]]:
        response = self._get("")
        return response.get("results", response) if isinstance(response, dict) else response

    def get_filter(self, filter_id: int) -> dict[str, Any]:
        return self._get(f"{filter_id}/")

    def create_filter(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("", json=payload)

    def update_filter(self, filter_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"{filter_id}/", json=payload)

    def delete_filter(self, filter_id: int) -> None:
        self._delete(f"{filter_id}/")

    def health(self) -> dict[str, Any]:
        return self._get("health/")