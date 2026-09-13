"""Operation-scoped reuse for exact immutable ledger reads.

The cache is deliberately inactive by default. A caller may activate it only
after stabilizing every participating ledger for one read operation. Cache
keys include the repository object and exact method arguments, so another
cutoff or repository instance is always read again.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from functools import wraps
from typing import ParamSpec, TypeVar, cast

_P = ParamSpec("_P")
_R = TypeVar("_R")
_immutable_reads: ContextVar[dict[tuple[object, ...], object] | None] = ContextVar(
    "account_immutable_reads",
    default=None,
)
_MISSING = object()


@contextmanager
def immutable_read_snapshot() -> Iterator[None]:
    """Reuse exact successful reads within one caller-stabilized operation."""

    token: Token[dict[tuple[object, ...], object] | None] | None = None
    if _immutable_reads.get() is None:
        token = _immutable_reads.set({})
    try:
        yield
    finally:
        if token is not None:
            _immutable_reads.reset(token)


def reuse_immutable_read(
    namespace: str,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Reuse one exact repository read while an immutable snapshot is active."""

    if not namespace or namespace.strip() != namespace:
        raise ValueError("immutable read namespace must be a canonical token")

    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            current = _immutable_reads.get()
            if current is None or not args:
                return function(*args, **kwargs)
            signature = _exact_hashable_signature(args[1:], kwargs)
            if signature is None:
                return function(*args, **kwargs)
            key = (namespace, function, args[0], signature)
            try:
                hash(key)
            except TypeError:
                return function(*args, **kwargs)
            cached = current.get(key, _MISSING)
            if cached is not _MISSING:
                return cast(_R, cached)
            value = function(*args, **kwargs)
            current[key] = value
            return value

        return wrapped

    return decorate


def _exact_hashable_signature(
    positional: tuple[object, ...],
    keyword: dict[str, object],
) -> tuple[object, ...] | None:
    """Return a type-preserving key for bounded scalar read arguments."""

    try:
        items = tuple((name, type(value), value) for name, value in sorted(keyword.items()))
        key: tuple[object, ...] = (
            tuple((type(value), value) for value in positional),
            items,
        )
        hash(key)
    except (TypeError, ValueError):
        return None
    return key


__all__ = ["immutable_read_snapshot", "reuse_immutable_read"]
