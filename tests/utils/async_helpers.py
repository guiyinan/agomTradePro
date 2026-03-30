"""Utilities for running async test helpers without loop interference."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from threading import Thread
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


def run_async_callable(
    async_callable: Callable[..., Awaitable[T]],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Run an async callable in a dedicated thread-bound event loop."""
    future: Future[T] = Future()

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(async_callable(*args, **kwargs))
            loop.run_until_complete(loop.shutdown_asyncgens())
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(result)
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    return future.result()
