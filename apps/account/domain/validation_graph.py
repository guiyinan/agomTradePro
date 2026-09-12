"""Bound repeated validation work to one immutable Account object graph."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar, Token
from functools import wraps
from typing import ParamSpec, TypeVar, cast

_P = ParamSpec("_P")
_R = TypeVar("_R")
_T = TypeVar("_T")
_validated_nodes: ContextVar[dict[int, object] | None] = ContextVar(
    "account_validated_nodes",
    default=None,
)
_decoded_values: ContextVar[dict[tuple[str, str], object] | None] = ContextVar(
    "account_decoded_values",
    default=None,
)


def validation_graph_operation(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """Keep one short-lived validation cache for a complete graph operation."""

    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        node_token: Token[dict[int, object] | None] | None = None
        decode_token: Token[dict[tuple[str, str], object] | None] | None = None
        if _validated_nodes.get() is None:
            node_token = _validated_nodes.set({})
        if _decoded_values.get() is None:
            decode_token = _decoded_values.set({})
        try:
            return function(*args, **kwargs)
        finally:
            if decode_token is not None:
                _decoded_values.reset(decode_token)
            if node_token is not None:
                _validated_nodes.reset(node_token)

    return wrapped


def reuse_validated_decode(
    namespace: str,
) -> Callable[[Callable[[object], _T]], Callable[[object], _T]]:
    """Reuse a successful immutable decode for the same exact JSON tree."""

    if not namespace or namespace.strip() != namespace:
        raise ValueError("decode cache namespace must be a canonical token")

    def decorate(function: Callable[[object], _T]) -> Callable[[object], _T]:
        @wraps(function)
        def wrapped(payload: object) -> _T:
            current = _decoded_values.get()
            if current is None:
                return validation_graph_operation(wrapped)(payload)
            signature = _exact_json_signature(payload)
            if signature is None:
                return function(payload)
            key = (namespace, signature)
            cached = current.get(key, _MISSING)
            if cached is not _MISSING:
                return cast(_T, cached)
            decoded = function(payload)
            current[key] = decoded
            return decoded

        return wrapped

    return decorate


_MISSING = object()


def _exact_json_signature(value: object) -> str | None:
    """Return canonical JSON only when every container and scalar has an exact type."""

    if not _is_exact_json_value(value):
        return None
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return None


def _is_exact_json_value(value: object) -> bool:
    if value is None or type(value) in (str, int, float, bool):
        return True
    if type(value) is list:
        return all(_is_exact_json_value(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _is_exact_json_value(item) for key, item in value.items())
    return False


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


__all__ = [
    "reuse_validated_decode",
    "validate_once_per_graph",
    "validation_graph_operation",
]
