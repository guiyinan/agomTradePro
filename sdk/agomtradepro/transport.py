"""Scoped request transport overrides for embedded SDK hosts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol


class RequestTransport(Protocol):
    """Minimal transport contract consumed by :class:`AgomTradeProClient`."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        json: dict[str, Any] | None,
        files: dict[str, Any] | None,
        timeout: int,
    ) -> Any:
        """Return a response exposing ``status_code`` and ``json()``."""


_REQUEST_TRANSPORT: ContextVar[RequestTransport | None] = ContextVar(
    "agomtradepro_request_transport",
    default=None,
)


def get_request_transport() -> RequestTransport | None:
    """Return the transport scoped to the current execution context."""

    return _REQUEST_TRANSPORT.get()


@contextmanager
def use_request_transport(transport: RequestTransport) -> Iterator[None]:
    """Route SDK requests through ``transport`` for the current context only."""

    token = _REQUEST_TRANSPORT.set(transport)
    try:
        yield
    finally:
        _REQUEST_TRANSPORT.reset(token)
