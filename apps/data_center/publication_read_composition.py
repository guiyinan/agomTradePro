"""Compose consistent database reads around current publication consumers."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from apps.data_center.infrastructure.publication_read_snapshot import consistent_publication_read

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
