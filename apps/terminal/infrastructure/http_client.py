"""HTTP client for terminal API commands."""

from typing import Any

import requests


class TerminalApiRequestError(RuntimeError):
    """Raised when a terminal API command request fails."""


class TerminalCommandHttpClient:
    """Execute terminal API commands through the infrastructure layer."""

    def request_json(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any],
        timeout: int,
    ) -> tuple[int, Any]:
        try:
            if method.upper() == "GET":
                response = requests.get(url, params=params, timeout=timeout)
            else:
                response = requests.request(
                    method=method.upper(),
                    url=url,
                    json=params,
                    timeout=timeout,
                )
            response.raise_for_status()
            return response.status_code, response.json()
        except requests.RequestException as exc:
            raise TerminalApiRequestError(str(exc)) from exc
