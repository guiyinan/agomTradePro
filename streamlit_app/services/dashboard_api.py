"""HTTP client for Django dashboard v1 APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class DashboardApiClient:
    """Simple API client for Streamlit pages."""

    base_url: str
    token: str
    timeout: int = 10

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url.rstrip('/')}{path}",
            params=params,
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return {"data": data}
        return data

    def get_summary(self) -> dict[str, Any]:
        return self._get("/dashboard/api/v1/summary/")

    def get_regime_quadrant(self) -> dict[str, Any]:
        return self._get("/dashboard/api/v1/regime-quadrant/")

    def get_equity_curve(self, range_code: str) -> dict[str, Any]:
        return self._get("/dashboard/api/v1/equity-curve/", params={"range": range_code})

    def get_signal_status(self, limit: int = 50) -> dict[str, Any]:
        return self._get("/dashboard/api/v1/signal-status/", params={"limit": limit})
