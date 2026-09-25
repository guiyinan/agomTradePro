"""Bounded, credential-free HTTP receipts for a dedicated rehearsal process."""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, cast
from urllib.parse import urlsplit

import requests

from core.exceptions import DataFetchError

from .rehearsal_response_store import (
    RehearsalResponseArtifactRef,
    RehearsalResponseContext,
    RehearsalResponseStore,
)


@dataclass(frozen=True)
class RehearsalHttpReceipt:
    """One observable transport dispatch, with no headers, query or request body."""

    host: str
    path_sha256: str
    method: str
    started_at: str
    finished_at: str
    status_code: int | None
    body_sha256: str
    body_bytes: int
    error_code: str
    response_artifact: RehearsalResponseArtifactRef | None = None


class RehearsalHttpCapture:
    """Observe actual requests in a one-shot CLI; never install this in a server."""

    def __init__(
        self,
        *,
        max_dispatches: int,
        max_seconds: float,
        max_body_bytes: int = 8_000_000,
        response_store: RehearsalResponseStore | None = None,
    ) -> None:
        """Set request bounds and optionally enable explicitly scoped response retention."""
        if (
            any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in (max_dispatches, max_body_bytes)
            )
            or isinstance(max_seconds, bool)
            or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds)
            or max_seconds <= 0
        ):
            raise ValueError("rehearsal HTTP budgets must be positive")
        self.max_dispatches = max_dispatches
        self.max_seconds = max_seconds
        self.max_body_bytes = max_body_bytes
        self.response_store = response_store
        self._response_context: ContextVar[RehearsalResponseContext | None] = ContextVar(
            f"rehearsal_response_context_{id(self)}", default=None
        )
        self.receipts: list[RehearsalHttpReceipt] = []
        self.dispatches = 0
        self.started = 0.0
        self._original_send: Callable[..., requests.Response] | None = None

    @contextmanager
    def provider_probe(self, context: RehearsalResponseContext) -> Iterator[None]:
        """Enable body retention only around one explicitly identified provider probe."""
        if self.response_store is None:
            raise DataFetchError(
                "Rehearsal response store is unavailable",
                code="REHEARSAL_RESPONSE_STORE_UNAVAILABLE",
            )
        if self._response_context.get() is not None:
            raise DataFetchError(
                "Nested response retention scopes are not supported",
                code="REHEARSAL_RESPONSE_SCOPE_NESTED",
            )
        token: Token[RehearsalResponseContext | None] = self._response_context.set(context)
        try:
            yield
        finally:
            self._response_context.reset(token)

    def __enter__(self) -> RehearsalHttpCapture:
        """Install a real-transport observer without replacing provider responses."""
        self.started = time.monotonic()
        original = requests.Session.send
        self._original_send = original

        def send(
            session: requests.Session, request: requests.PreparedRequest, **kwargs: Any
        ) -> requests.Response:
            remaining = self.max_seconds - (time.monotonic() - self.started)
            if self.dispatches >= self.max_dispatches or remaining <= 0:
                raise DataFetchError(
                    "Rehearsal HTTP budget exhausted", code="REHEARSAL_HTTP_BUDGET_EXCEEDED"
                )
            adapter = session.get_adapter(str(request.url))
            if not isinstance(adapter, requests.adapters.HTTPAdapter):
                raise DataFetchError(
                    "Unobservable HTTP adapter", code="REHEARSAL_TRANSPORT_UNOBSERVABLE"
                )
            retries = adapter.max_retries
            if retries.total not in (0, False):
                raise DataFetchError(
                    "Unobservable transport retries", code="REHEARSAL_HIDDEN_RETRIES"
                )
            self.dispatches += 1
            started_at = datetime.now(UTC).isoformat()
            url = urlsplit(str(request.url))
            timeout: object = kwargs.get("timeout")
            if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
                kwargs["timeout"] = min(float(timeout), remaining)
            elif isinstance(timeout, tuple) and len(timeout) == 2:
                kwargs["timeout"] = tuple(
                    min(float(part), remaining) if isinstance(part, (int, float)) else remaining
                    for part in timeout
                )
            else:
                kwargs["timeout"] = remaining
            response: requests.Response | None = None
            body = bytearray()
            error_code = ""
            response_artifact: RehearsalResponseArtifactRef | None = None
            finished_at = ""
            try:
                # Bound consumption before requests eagerly materializes the body.
                # Redirect following may also consume a body outside this observer.
                kwargs["stream"] = True
                kwargs["allow_redirects"] = False
                response = original(session, request, **kwargs)
                if response.is_redirect or response.is_permanent_redirect:
                    raise DataFetchError(
                        "Rehearsal redirect requires separate transport evidence",
                        code="REHEARSAL_REDIRECT_BLOCKED",
                    )
                for chunk in response.iter_content(chunk_size=65536):
                    if time.monotonic() - self.started > self.max_seconds:
                        raise DataFetchError(
                            "Rehearsal HTTP deadline exceeded",
                            code="REHEARSAL_HTTP_BUDGET_EXCEEDED",
                        )
                    body.extend(chunk)
                    if len(body) > self.max_body_bytes:
                        raise DataFetchError(
                            "Rehearsal response too large", code="REHEARSAL_BODY_LIMIT"
                        )
                # requests normally exposes this same decoded body to provider parsers.
                response._content = bytes(body)
                cast(Any, response)._content_consumed = True  # requests' private buffering boundary
                finished_at = datetime.now(UTC).isoformat()
                context = self._response_context.get()
                if response.status_code == 200 and context is not None:
                    store = self.response_store
                    if store is None:
                        raise DataFetchError(
                            "Rehearsal response store is unavailable",
                            code="REHEARSAL_RESPONSE_STORE_UNAVAILABLE",
                        )
                    response_artifact = store.persist_response(
                        context,
                        receipt_index=len(self.receipts),
                        host=url.hostname or "",
                        path_sha256=hashlib.sha256(url.path.encode()).hexdigest(),
                        method=str(request.method or ""),
                        started_at=started_at,
                        finished_at=finished_at,
                        status_code=response.status_code,
                        response_body=bytes(body),
                    )
                return response
            except (requests.RequestException, DataFetchError, OSError) as exc:
                error_code = (
                    exc.code if isinstance(exc, DataFetchError) else "REHEARSAL_HTTP_FAILED"
                )
                if response is not None:
                    response.close()
                raise
            finally:
                finished_at = finished_at or datetime.now(UTC).isoformat()
                self.receipts.append(
                    RehearsalHttpReceipt(
                        host=url.hostname or "",
                        path_sha256=hashlib.sha256(url.path.encode()).hexdigest(),
                        method=str(request.method or ""),
                        started_at=started_at,
                        finished_at=finished_at,
                        status_code=response.status_code if response is not None else None,
                        body_sha256=hashlib.sha256(body).hexdigest() if not error_code else "",
                        body_bytes=len(body),
                        error_code=error_code,
                        response_artifact=response_artifact,
                    )
                )

        cast(Any, requests.Session).send = send  # scoped third-party transport instrumentation
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Always restore the process transport when the probe succeeds or fails."""
        if self._original_send is not None:
            cast(Any, requests.Session).send = self._original_send

    def to_dict(self) -> dict[str, object]:
        """Return observed evidence, distinguishing dispatches from provider quota units."""
        return {
            "dispatch_count": self.dispatches,
            "count_unit": "requests_session_dispatch",
            "max_dispatches": self.max_dispatches,
            "max_seconds": self.max_seconds,
            "elapsed_seconds": round(time.monotonic() - self.started, 6),
            "receipts": [asdict(receipt) for receipt in self.receipts],
        }
