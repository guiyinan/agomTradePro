"""AgomSAAF SDK - Config Center module."""

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
        return response.get("data", response)
