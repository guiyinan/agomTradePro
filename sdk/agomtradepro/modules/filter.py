"""AgomTradePro SDK - Filter 模块。"""

from typing import Any

from .base import BaseModule


class FilterModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/filter")

    def list_filters(self) -> list[dict[str, Any]]:
        response = self._get("indicators/")
        indicators = response.get("indicators", response) if isinstance(response, dict) else response
        if not isinstance(indicators, list):
            return []
        return [
            {
                "id": index,
                **indicator,
            }
            for index, indicator in enumerate(indicators, start=1)
            if isinstance(indicator, dict)
        ]

    def get_filter(
        self,
        filter_id: int | None = None,
        indicator_code: str | None = None,
    ) -> dict[str, Any]:
        code = indicator_code
        if code is None and filter_id is not None:
            filters = self.list_filters()
            matched = next((item for item in filters if item.get("id") == filter_id), None)
            if matched:
                code = matched.get("code")
        if not code:
            return {
                "success": False,
                "error": "filter not found",
            }
        response = self._get(f"config/{code}/")
        if isinstance(response, dict) and "config" in response:
            payload = dict(response["config"])
            payload.setdefault("indicator_code", code)
            return payload
        return response

    def create_filter(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = dict(payload)
        request_payload.setdefault("filter_type", "HP")
        request_payload.setdefault("save_results", True)
        return self._post("", json=request_payload)

    def update_filter(self, filter_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"{filter_id}/", json=payload)

    def delete_filter(self, filter_id: int) -> None:
        self._delete(f"{filter_id}/")

    def health(self) -> dict[str, Any]:
        return self._get("health/")
