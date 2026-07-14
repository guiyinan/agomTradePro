"""Synchronous SDK iterator for authenticated realtime WebSocket events."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class RealtimeEnvelope:
    """Typed realtime event envelope."""

    type: str
    payload: dict[str, Any]

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> RealtimeEnvelope:
        """Separate the event type from its remaining payload."""

        payload = dict(value)
        event_type = str(payload.pop("type", ""))
        if not event_type:
            raise ValueError("realtime envelope is missing type")
        return cls(type=event_type, payload=payload)


class RealtimeStreamClosedError(Exception):
    """Raised when the realtime WebSocket closes with a protocol code."""

    def __init__(self, code: int | None, message: str) -> None:
        self.code = code
        super().__init__(message)


class RealtimeStream(Iterator[RealtimeEnvelope]):
    """Context-managed synchronous iterator over realtime event envelopes."""

    def __init__(
        self,
        *,
        base_url: str,
        authorization: str,
        asset_codes: list[str] | tuple[str, ...] = (),
        connection_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.authorization = authorization.strip()
        self.asset_codes = tuple(
            sorted({str(code).strip().upper() for code in asset_codes if str(code).strip()})
        )
        self._connection_factory = connection_factory
        self._connection: Any | None = None

    @property
    def websocket_url(self) -> str:
        """Return the canonical WebSocket URL derived from the API base URL."""

        parsed = urlsplit(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunsplit((scheme, parsed.netloc, "/ws/realtime/prices/", "", ""))

    def __enter__(self) -> RealtimeStream:
        factory = self._connection_factory
        if factory is None:
            from websockets.sync.client import connect

            factory = connect
        self._connection = factory(
            self.websocket_url,
            additional_headers={"Authorization": self.authorization},
        )
        if self.asset_codes:
            self._send(
                {
                    "action": "subscribe",
                    "request_id": uuid.uuid4().hex,
                    "asset_codes": list(self.asset_codes),
                }
            )
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def __iter__(self) -> RealtimeStream:
        return self

    def __next__(self) -> RealtimeEnvelope:
        if self._connection is None:
            raise RuntimeError("RealtimeStream must be opened as a context manager")
        try:
            raw = self._connection.recv()
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code is not None:
                raise RealtimeStreamClosedError(code, str(exc)) from exc
            raise
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("realtime event must be a JSON object")
        return RealtimeEnvelope.from_payload(value)

    def ping(self, request_id: str | None = None) -> str:
        """Send an application heartbeat and return its request ID."""

        resolved = request_id or uuid.uuid4().hex
        self._send({"action": "ping", "request_id": resolved})
        return resolved

    def close(self) -> None:
        """Close the underlying WebSocket idempotently."""

        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _send(self, payload: dict[str, Any]) -> None:
        if self._connection is None:
            raise RuntimeError("RealtimeStream is not connected")
        self._connection.send(json.dumps(payload, ensure_ascii=False))
