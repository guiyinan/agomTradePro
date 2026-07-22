"""Typed adapters for Celery's dynamically decorated task objects."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar, cast

from celery import shared_task

TaskResult = TypeVar("TaskResult", covariant=True)
DecoratedResult = TypeVar("DecoratedResult")


class AsyncTaskResult(Protocol):
    """Minimal asynchronous result surface used by task producers."""

    id: str


class EagerTaskResult(Protocol[TaskResult]):
    """Synchronous Celery result returned by ``Task.apply``."""

    def get(self, *args: Any, **kwargs: Any) -> TaskResult:
        """Return the task body's result or raise its failure."""

        ...


class TaskRequest(Protocol):
    """Celery request metadata consumed by bound task bodies."""

    id: str | None
    retries: int


class BoundTask(Protocol):
    """Minimal bound-task surface used by application task bodies."""

    request: TaskRequest
    max_retries: int

    def retry(self, *, exc: BaseException, countdown: int) -> BaseException:
        """Build Celery's retry exception."""

        ...


class TypedTask(Protocol[TaskResult]):
    """Callable Celery task with typed synchronous and asynchronous entrypoints."""

    name: str

    def __call__(self, *args: Any, **kwargs: Any) -> TaskResult: ...

    def run(self, *args: Any, **kwargs: Any) -> TaskResult: ...

    def delay(self, *args: Any, **kwargs: Any) -> AsyncTaskResult: ...

    def apply_async(self, *args: Any, **kwargs: Any) -> AsyncTaskResult: ...

    def apply(self, *args: Any, **kwargs: Any) -> EagerTaskResult[TaskResult]: ...


def typed_shared_task(
    *decorator_args: object,
    **decorator_kwargs: object,
) -> Callable[[Callable[..., DecoratedResult]], TypedTask[DecoratedResult]]:
    """Narrow Celery's untyped decorator while preserving task return types."""

    decorator = shared_task(*decorator_args, **decorator_kwargs)
    return cast(
        Callable[[Callable[..., DecoratedResult]], TypedTask[DecoratedResult]],
        decorator,
    )


__all__ = [
    "AsyncTaskResult",
    "BoundTask",
    "EagerTaskResult",
    "TaskRequest",
    "TypedTask",
    "typed_shared_task",
]
