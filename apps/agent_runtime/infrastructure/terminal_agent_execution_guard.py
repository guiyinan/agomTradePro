"""Cache-backed concurrency leases for Terminal Agent execution."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from django.core.cache import cache

from apps.agent_runtime.application.terminal_agent import (
    TerminalAgentBusyError,
    TerminalAgentChatRequestDTO,
    TerminalAgentExecutionGuard,
)

logger = logging.getLogger(__name__)


class _CacheBackend(Protocol):
    def add(self, key: str, value: str, timeout: int) -> bool: ...

    def get(self, key: str) -> Any: ...

    def delete(self, key: str) -> Any: ...


class CacheTerminalAgentExecutionGuard(TerminalAgentExecutionGuard):
    """Reject duplicate users and cap global runs with expiring cache leases."""

    def __init__(
        self,
        *,
        cache_backend: _CacheBackend | None = None,
        max_concurrency: int = 1,
        lease_timeout_seconds: int = 90,
    ) -> None:
        self._cache = cache_backend or cache
        self._max_concurrency = max(1, max_concurrency)
        self._lease_timeout_seconds = max(1, lease_timeout_seconds)

    @contextmanager
    def acquire(self, request: TerminalAgentChatRequestDTO) -> Iterator[None]:
        """Acquire per-user and global leases, failing closed on cache errors."""

        token = uuid.uuid4().hex
        user_key = self._user_key(request)
        slot_key: str | None = None
        try:
            if not self._cache.add(user_key, token, self._lease_timeout_seconds):
                raise TerminalAgentBusyError()

            for slot in range(self._max_concurrency):
                candidate = f"terminal-agent:execution:slot:{slot}"
                if self._cache.add(candidate, token, self._lease_timeout_seconds):
                    slot_key = candidate
                    break

            if slot_key is None:
                self._release_if_owned(user_key, token)
                raise TerminalAgentBusyError()
        except TerminalAgentBusyError:
            raise
        except Exception:
            logger.exception("Terminal Agent execution lease backend unavailable")
            self._release_if_owned(user_key, token)
            raise TerminalAgentBusyError() from None

        try:
            yield
        finally:
            if slot_key is not None:
                self._release_if_owned(slot_key, token)
            self._release_if_owned(user_key, token)

    def _user_key(self, request: TerminalAgentChatRequestDTO) -> str:
        identity = str(request.user_id) if request.user_id is not None else request.username
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return f"terminal-agent:execution:user:{digest}"

    def _release_if_owned(self, key: str, token: str) -> None:
        try:
            if self._cache.get(key) == token:
                self._cache.delete(key)
        except Exception:
            logger.warning("Terminal Agent execution lease cleanup failed", exc_info=True)
