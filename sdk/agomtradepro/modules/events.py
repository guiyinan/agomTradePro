"""AgomTradePro SDK - Events 模块。"""

from typing import Any

from .base import BaseModule


class EventsModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/events")

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Publish an event using the legacy payload-shaped SDK contract."""

        return self._post("publish/", json=payload)

    def publish_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: str,
        event_id: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish one canonical event with an explicit stable identity."""

        request_payload: dict[str, Any] = {
            "event_type": event_type,
            "payload": payload,
            "occurred_at": occurred_at,
            "event_id": event_id,
        }
        if metadata is not None:
            request_payload["metadata"] = metadata
        if correlation_id is not None:
            request_payload["correlation_id"] = correlation_id
        if causation_id is not None:
            request_payload["causation_id"] = causation_id
        return self._post("publish/", json=request_payload)

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._get("query/", params=payload)

    def metrics(self) -> dict[str, Any]:
        return self._get("metrics/")

    def status(self) -> dict[str, Any]:
        return self._get("status/")

    def replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compatibility alias for a controlled replay commit."""

        return self.replay_events(payload)

    def preview_event_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Preview a registered replay target without invoking its handler."""

        return self._post("replay/preview/", json=dict(payload))

    def commit_event_replay(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Commit one idempotent, staff-scoped controlled replay."""

        request_payload = dict(payload)
        request_payload["idempotency_key"] = idempotency_key
        return self._post("replay/commit/", json=request_payload)

    def replay_events(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compatibility wrapper requiring target and idempotency identity."""

        request_payload = dict(payload)
        target_key = str(request_payload.get("target_key") or "").strip()
        idempotency_key = str(request_payload.pop("idempotency_key", "") or "").strip()
        if not target_key:
            raise ValueError("target_key is required for controlled event replay")
        if not idempotency_key:
            raise ValueError("idempotency_key is required for controlled event replay")
        return self.commit_event_replay(
            request_payload,
            idempotency_key=idempotency_key,
        )
