"""Compose consistent database reads around current publication consumers."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from functools import wraps
from time import monotonic
from typing import ParamSpec, TypeVar

from apps.data_center.infrastructure.publication_read_snapshot import (
    MAX_PUBLICATION_READ_LOCK_SECONDS,
    consistent_publication_read,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


def publication_snapshot(
    dataset_key: str | None = None,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Keep the policy, frozen members and served facts in one read snapshot."""

    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def read(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            selected_dataset = dataset_key
            if selected_dataset is None:
                value = args[0] if args else kwargs.get("dataset_key")
                if not isinstance(value, str) or not value:
                    raise ValueError("A current publication read requires a dataset key")
                selected_dataset = value
            with consistent_publication_read(selected_dataset):
                return function(*args, **kwargs)

        return read

    return decorate


def publication_snapshot_for_datasets(
    dataset_keys: tuple[str, ...],
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Open every selected dataset boundary before a multi-dataset read.

    Dataset keys are acquired in lexical order so nested writable
    READ COMMITTED callers use one deterministic cross-dataset lock order.
    The underlying context preserves its existing isolation rules and bounded
    timeout; any unavailable boundary aborts the whole read.
    """

    normalized_keys = tuple(sorted({key.strip() for key in dataset_keys if key.strip()}))
    if not normalized_keys or len(normalized_keys) != len(dataset_keys):
        raise ValueError("A multi-dataset publication read requires non-empty dataset keys")

    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def read(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            deadline = monotonic() + MAX_PUBLICATION_READ_LOCK_SECONDS
            with ExitStack() as stack:
                for selected_dataset in normalized_keys:
                    stack.enter_context(
                        consistent_publication_read(selected_dataset, lock_deadline=deadline)
                    )
                return function(*args, **kwargs)

        return read

    return decorate
