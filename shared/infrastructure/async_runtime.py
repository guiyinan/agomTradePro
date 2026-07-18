"""Safe synchronous bridges for infrastructure-owned async operations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import TypeVar

T = TypeVar("T")


def run_awaitable_sync(awaitable_factory: Callable[[], Awaitable[T]]) -> T:
    """Run an awaitable from sync code, including when a loop already runs here."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable_factory())

    context = copy_context()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="agom-async-bridge") as executor:
        return executor.submit(
            context.run,
            lambda: asyncio.run(awaitable_factory()),
        ).result()


def run_sync_compatible(operation: Callable[[], T]) -> T:
    """Run sync work safely when the caller is already inside an event loop."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return operation()

    context = copy_context()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="agom-sync-bridge") as executor:
        return executor.submit(context.run, operation).result()
