"""AgomSAAF SDK - Sentiment 模块。"""

from typing import Any

from .base import BaseModule


class SentimentModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/sentiment")

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("analyze/", json=payload)

    def batch_analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("batch-analyze/", json=payload)

    def get_index(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload:
            return self._post("index/", json=payload)
        return self._get("index/")

    def index_range(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload:
            return self._post("index/range/", json=payload)
        return self._get("index/range/")

    def index_recent(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload:
            return self._post("index/recent/", json=payload)
        return self._get("index/recent/")

    def health(self) -> dict[str, Any]:
        return self._get("health/")

    def clear_cache(self) -> dict[str, Any]:
        return self._post("cache/clear/", json={})