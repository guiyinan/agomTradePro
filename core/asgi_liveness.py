"""Dependency-free ASGI liveness response used ahead of Django middleware."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from asgiref.typing import (
    ASGI3Application,
    ASGIReceiveCallable,
    ASGISendCallable,
    HTTPResponseBodyEvent,
    HTTPResponseStartEvent,
    Scope,
)


class LivenessApplication:
    """Serve liveness directly so blocked Django work cannot hide process health."""

    def __init__(self, application: ASGI3Application) -> None:
        self._application = application

    async def __call__(
        self,
        scope: Scope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        """Short-circuit the exact liveness route and delegate all other traffic."""

        if scope["type"] == "http" and scope.get("path") == "/api/health/":
            method = str(scope.get("method") or "GET").upper()
            if method in {"GET", "HEAD"}:
                payload = json.dumps(
                    {
                        "status": "ok",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                    separators=(",", ":"),
                ).encode("utf-8")
                start_event: HTTPResponseStartEvent = {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                        (b"content-length", str(len(payload)).encode("ascii")),
                    ],
                    "trailers": False,
                }
                await send(start_event)
                body_event: HTTPResponseBodyEvent = {
                    "type": "http.response.body",
                    "body": b"" if method == "HEAD" else payload,
                    "more_body": False,
                }
                await send(body_event)
                return
        await self._application(scope, receive, send)
