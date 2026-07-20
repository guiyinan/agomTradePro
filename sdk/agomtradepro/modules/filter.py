"""AgomTradePro SDK - Filter 模块。"""

import warnings
from typing import Any

from .base import BaseModule

FILTER_SUNSET_DATE = "2026-09-30"


class FilterModuleDeprecationWarning(FutureWarning):
    """Warning emitted when the deprecated Filter SDK module is used."""


class FilterModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/filter")

    def list_filters(self) -> list[dict[str, Any]]:
        self._warn_deprecated()
        response = self._get("indicators/")
        indicators = (
            response.get("indicators", response) if isinstance(response, dict) else response
        )
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
        self._warn_deprecated()
        code = self._resolve_indicator_code(filter_id=filter_id, indicator_code=indicator_code)
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
        self._warn_deprecated()
        request_payload = dict(payload)
        request_payload.setdefault("filter_type", "HP")
        request_payload.setdefault("save_results", True)
        return self._post("", json=request_payload)

    def update_filter(
        self,
        filter_id: int | None = None,
        payload: dict[str, Any] | None = None,
        indicator_code: str | None = None,
    ) -> dict[str, Any]:
        self._warn_deprecated()
        indicator_code = self._resolve_indicator_code(
            filter_id=filter_id,
            indicator_code=indicator_code,
        )
        if not indicator_code:
            raise ValueError("filter not found")
        return self._patch(f"config/{indicator_code}/", json=dict(payload or {}))

    def delete_filter(
        self,
        filter_id: int | None = None,
        *,
        indicator_code: str | None = None,
    ) -> None:
        self._warn_deprecated()
        indicator_code = self._resolve_indicator_code(
            filter_id=filter_id,
            indicator_code=indicator_code,
        )
        if not indicator_code:
            raise ValueError("filter not found")
        self._delete(f"config/{indicator_code}/")

    def health(self) -> dict[str, Any]:
        self._warn_deprecated()
        return self._get("health/")

    @staticmethod
    def _warn_deprecated() -> None:
        """Warn callers without changing the existing SDK response contract."""

        warnings.warn(
            "FilterModule is deprecated and is scheduled for sunset on "
            f"{FILTER_SUNSET_DATE}; do not add new consumers.",
            FilterModuleDeprecationWarning,
            stacklevel=3,
        )

    def _resolve_indicator_code(
        self,
        *,
        filter_id: int | None = None,
        indicator_code: str | None = None,
    ) -> str | None:
        if indicator_code:
            return indicator_code
        if filter_id is None:
            return None
        filters = self.list_filters()
        matched = next((item for item in filters if item.get("id") == filter_id), None)
        if not isinstance(matched, dict):
            return None
        code = matched.get("code")
        return code if isinstance(code, str) and code else None
