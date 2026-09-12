"""Bound repeated validation work to one immutable Account object graph."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from functools import wraps
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")
_T = TypeVar("_T")
_validated_nodes: ContextVar[dict[int, object] | None] = ContextVar(
    "account_validated_nodes",
    default=None,
)


def validation_graph_operation(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """Keep one short-lived validation cache for a complete graph operation."""

    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        current = _validated_nodes.get()
        token: Token[dict[int, object] | None] | None = None
        if current is None:
            token = _validated_nodes.set({})
        try:
            return function(*args, **kwargs)
        finally:
            if token is not None:
                _validated_nodes.reset(token)

    return wrapped


def validate_once_per_graph(function: Callable[[_T], None]) -> Callable[[_T], None]:
    """Run successful validation once per object identity in one graph operation."""

    @wraps(function)
    def wrapped(value: _T) -> None:
        current = _validated_nodes.get()
        if current is None:
            validation_graph_operation(wrapped)(value)
            return
        marker = id(value)
        if current.get(marker) is value:
            return
        function(value)
        current[marker] = value

    return wrapped


__all__ = ["validate_once_per_graph", "validation_graph_operation"]
