"""AgomSAAF SDK - Events 模块。"""

from typing import Any

from .base import BaseModule


class EventsModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/events")

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("publish/", json=payload)

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._get("query/", params=payload)

    def metrics(self) -> dict[str, Any]:
        return self._get("metrics/")

    def status(self) -> dict[str, Any]:
        return self._get("status/")

    def replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("replay/", json=payload)
