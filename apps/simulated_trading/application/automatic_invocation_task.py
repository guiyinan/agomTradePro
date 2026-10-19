"""Keep one business invocation key in each Celery automatic-trading message."""

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from celery import Task
from celery.result import AsyncResult

if TYPE_CHECKING:

    class _CeleryPublishTask:
        """Declare the verified Celery publish boundary for its untyped runtime class."""

        def apply_async(
            self,
            args: tuple[Any, ...] | list[Any] | None = None,
            kwargs: dict[str, Any] | None = None,
            task_id: str | None = None,
            producer: Any | None = None,
            link: Any | None = None,
            link_error: Any | None = None,
            shadow: str | None = None,
            **options: Any,
        ) -> AsyncResult:
            """Publish one message through Celery's public Task.apply_async signature."""
            ...

else:
    _CeleryPublishTask = Task


class DailyAutoTradingInvocationTask(_CeleryPublishTask):
    """Attach one business invocation key to each fresh Celery publication."""

    def apply_async(
        self,
        args: tuple[Any, ...] | list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        task_id: str | None = None,
        producer: Any | None = None,
        link: Any | None = None,
        link_error: Any | None = None,
        shadow: str | None = None,
        **options: Any,
    ) -> AsyncResult:
        """Publish with a stable-per-message key, without mutating caller kwargs."""
        invocation_kwargs = {} if kwargs is None else kwargs.copy()
        if "invocation_key" not in invocation_kwargs:
            invocation_kwargs["invocation_key"] = uuid4().hex
        return super().apply_async(
            args,
            invocation_kwargs,
            task_id,
            producer,
            link,
            link_error,
            shadow,
            **options,
        )
