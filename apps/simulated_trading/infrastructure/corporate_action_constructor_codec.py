"""Bounded constructor codecs selected only by trusted static types, never payload type names."""

from __future__ import annotations

import types
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Union, cast, get_args, get_origin, get_type_hints
from uuid import UUID

from apps.audit.domain.system_audit_event import JSONValue

_MAX_DEPTH = 64


def encode_corporate_action_constructor(value: object, *, depth: int = 0) -> JSONValue:
    """Encode constructor fields only, preserving every original scalar exactly."""
    if depth > _MAX_DEPTH:
        raise ValueError("intent nesting exceeds its technical bound")
    if value is None or type(value) in (str, int, bool):
        return cast(JSONValue, value)
    if isinstance(value, Enum):
        return encode_corporate_action_constructor(value.value, depth=depth + 1)
    if isinstance(value, (datetime, date, UUID)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("intent decimal is not finite")
        return format(value, "f")
    if isinstance(value, tuple):
        return [encode_corporate_action_constructor(item, depth=depth + 1) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: encode_corporate_action_constructor(
                getattr(value, field.name), depth=depth + 1
            )
            for field in fields(value)
            if field.init
        }
    raise ValueError("unsupported intent constructor value")


def restore_corporate_action_constructor(
    value: JSONValue, expected: object, *, depth: int = 0
) -> object:
    """Narrow JSON recursively using trusted constructor annotations, without imports."""
    if depth > _MAX_DEPTH:
        raise ValueError("intent nesting exceeds its technical bound")
    origin = get_origin(expected)
    arguments = get_args(expected)
    if origin in (Union, types.UnionType):
        for option in arguments:
            try:
                return restore_corporate_action_constructor(value, option, depth=depth + 1)
            except (ValueError, TypeError):
                continue
        raise ValueError("intent union value is invalid")
    if origin is Literal:
        if any(type(value) is type(option) and value == option for option in arguments):
            return value
        raise ValueError("intent literal is invalid")
    if origin is tuple:
        if type(value) is not list or len(value) > 10_000:
            raise ValueError("intent tuple is invalid")
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(
                restore_corporate_action_constructor(item, arguments[0], depth=depth + 1)
                for item in value
            )
        if len(value) != len(arguments):
            raise ValueError("intent fixed tuple length differs")
        return tuple(
            restore_corporate_action_constructor(item, option, depth=depth + 1)
            for item, option in zip(value, arguments, strict=True)
        )
    if expected in (str, int, bool, type(None)):
        if type(value) is not expected:
            raise ValueError("intent primitive type differs")
        return value
    if expected in (date, datetime, Decimal, UUID):
        if type(value) is not str or len(value) > 128:
            raise ValueError("intent scalar text is invalid")
        if expected is Decimal:
            result = Decimal(value)
            if not result.is_finite():
                raise ValueError("intent decimal is not finite")
            return result
        if expected is datetime:
            instant = datetime.fromisoformat(value)
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError("intent instant is naive")
            return instant
        return date.fromisoformat(value) if expected is date else UUID(value)
    if isinstance(expected, type) and issubclass(expected, Enum):
        if not any(
            type(value) is type(member.value) and value == member.value for member in expected
        ):
            raise ValueError("intent enumeration is invalid")
        return expected(value)
    if isinstance(expected, type) and is_dataclass(expected):
        names = {field.name for field in fields(expected) if field.init}
        if type(value) is not dict or set(value) != names:
            raise ValueError("intent constructor fields differ")
        hints = get_type_hints(expected)
        constructor = cast(Callable[..., object], expected)
        return constructor(
            **{
                name: restore_corporate_action_constructor(
                    value[name], hints[name], depth=depth + 1
                )
                for name in names
            }
        )
    raise ValueError("unsupported trusted intent constructor type")
